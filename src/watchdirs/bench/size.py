"""Hybrid-A size benchmark: replicate -> VACUUM -> dbstat compare -> D-09 gate.

This is the D-08 method-A / D-10 deliverable that proves the phase worth shipping
(or, on a wide miss, triggers the D-07 DuckDB-escalation conversation).

What it does
------------
One real scan's rows are replicated into N synthetic snapshots (driven by the
churn rate measured by ``watchdirs.bench.churn`` on Plan 01) under BOTH schemas:

- NEW-DICT: the product schema (flat ``paths`` dictionary + int ``path_id`` FKs),
  built via ``initialize_database`` + ``open_connection`` PRAGMA setup and the
  ``insert_directory_rows`` batching path — i.e. exactly how collect writes.
- OLD-BLOB: an inline legacy DDL LOCAL to this harness (``path``/``parent_path``/
  ``name`` BLOB columns + the pre-rewrite indexes). This is benchmark scaffolding
  to measure the baseline, explicitly NOT a product compat shim -- the product
  schema has no old path.

BOTH DBs are built with IDENTICAL ``page_size`` / ``journal_mode`` / ``auto_vacuum``
PRAGMAs (Pitfall 4), ``VACUUM``ed, then measured. Size is read two independent ways
and reconciled: ``page_count*page_size`` MUST equal ``os.path.getsize()`` post-VACUUM
(Don't-Hand-Roll -- catches an uncheckpointed WAL). Per-object attribution comes from
the ``dbstat`` vtable (Research Pattern 3); the ``sqlite_autoindex_paths_1`` cost is
counted in the NEW total (Pitfall 6: the UNIQUE constraint re-stores the path bytes).

The D-09 gate (``evaluate_byte_budget``) is a per-snapshot byte budget set against the
MEASURED after-VACUUM size -- never an idealized model. The reduction ratio is reported
as color, NOT as the gate.

Run as a dev tool::

    uv run python -m watchdirs.bench.size <real_scan_db> --snapshots 412 --churn <measured>

which prints the OLD/NEW dbstat breakdown, the per-snapshot byte figure, the reduction
ratio, and the PASS/FAIL verdict to stdout (dev tool; stdout fine here).

Stdlib only (``sqlite3`` + ``dataclasses``). Path bytes are bound as ``?`` parameters in
both the OLD and NEW inline inserts; nothing is interpolated (T-03.1-04-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import os
import sqlite3
import sys

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import (
    INSERT_BATCH_SIZE,
    create_snapshot,
    initialize_database,
    insert_directory_rows,
)
from watchdirs.models import DirectoryAggregate


# --- OLD-BLOB legacy DDL (benchmark scaffolding, LOCAL to this harness) -------
#
# The pre-rewrite directory_sizes carrying raw path/parent_path/name BLOBs and the
# old path-keyed index. This exists ONLY to measure the baseline the dictionary
# rewrite replaced; it is NOT a product compat shim (the product schema has none).
# Page-store PRAGMAs are applied by the harness, identically to the NEW side, so the
# only variable between the two measurements is the schema shape.

OLD_BLOB_SCHEMA_SQL = """
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    root_path TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    error TEXT
);

CREATE TABLE directory_sizes (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path BLOB NOT NULL,
    parent_path BLOB,
    name BLOB NOT NULL,
    depth INTEGER NOT NULL,
    apparent_bytes INTEGER NOT NULL,
    disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    dir_count INTEGER NOT NULL,
    error TEXT
);

CREATE INDEX directory_sizes_path_snapshot_idx
    ON directory_sizes(path, snapshot_id);

CREATE INDEX directory_sizes_snapshot_size_idx
    ON directory_sizes(snapshot_id, disk_bytes);
"""

OLD_BLOB_INSERT_SQL = """
    INSERT INTO directory_sizes (
        snapshot_id, path, parent_path, name,
        depth, apparent_bytes, disk_bytes, file_count, dir_count, error
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# Pattern 3 (Research): per-object byte/cell attribution. dbstat reports one row
# per b-tree page; grouping by name yields table vs (each) index vs sqlite_schema.
DBSTAT_SQL = "SELECT name, SUM(pgsize) AS pgsize, SUM(ncell) AS ncell FROM dbstat GROUP BY name"


@dataclass(frozen=True)
class DbstatEntry:
    """Per-object byte/cell attribution from the dbstat vtable (Pattern 3)."""

    name: str
    pgsize: int
    ncell: int


@dataclass(frozen=True)
class SizeMeasurement:
    """Post-VACUUM size of one benchmark DB, measured two reconciling ways."""

    page_bytes: int  # page_count * page_size
    stat_bytes: int  # os.path.getsize()
    dbstat: tuple[DbstatEntry, ...]
    pragmas: dict[str, object]

    @property
    def reconciles(self) -> bool:
        return self.page_bytes == self.stat_bytes


@dataclass(frozen=True)
class Comparison:
    """OLD-vs-NEW comparison + the derived per-snapshot byte figure."""

    old: SizeMeasurement
    new: SizeMeasurement
    snapshots: int
    per_snapshot_bytes: int

    @property
    def reduction_ratio(self) -> float:
        return reduction_ratio(self.old.page_bytes, self.new.page_bytes)


@dataclass(frozen=True)
class BudgetVerdict:
    """D-09 gate outcome on the MEASURED per-snapshot byte figure."""

    per_snapshot_bytes: int
    budget_bytes: int
    passed: bool

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"


# --- synthetic replication ----------------------------------------------------


def replicate_snapshots(
    base_rows: list[DirectoryAggregate] | tuple[DirectoryAggregate, ...],
    *,
    snapshots: int,
    churn: float,
) -> list[list[DirectoryAggregate]]:
    """Replicate one real scan into ``snapshots`` synthetic snapshots at ``churn``.

    Each successive snapshot keeps the prior path set but rotates ``churn`` of its
    rows onto fresh paths (the new paths are unique to that snapshot). Low churn ->
    most paths recur across snapshots, so the flat dictionary stores them once and
    the NEW DB wins big; high churn -> fewer recurrences, so the win collapses
    toward index int-ization. This is what makes the measured win honest.
    """
    if snapshots < 1:
        raise ValueError("snapshots must be >= 1")
    if not 0.0 <= churn <= 1.0:
        raise ValueError("churn must be in [0.0, 1.0]")
    if not base_rows:
        return [[] for _ in range(snapshots)]

    n = len(base_rows)
    rotate = int(round(n * churn))
    fresh_counter = 0
    current = list(base_rows)
    result: list[list[DirectoryAggregate]] = []

    for snap_index in range(snapshots):
        if snap_index > 0 and rotate > 0:
            # Replace the first ``rotate`` rows with brand-new paths for this snapshot.
            rotated: list[DirectoryAggregate] = []
            for row in current[:rotate]:
                fresh_counter += 1
                rotated.append(
                    _with_path(row, b"/churn/s%05d_n%08d" % (snap_index, fresh_counter))
                )
            current = rotated + current[rotate:]
        result.append([_with_snapshot(row, snap_index) for row in current])

    return result


def _with_path(row: DirectoryAggregate, path: bytes) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=row.snapshot_id,
        path=path,
        parent_path=row.parent_path,
        depth=row.depth,
        apparent_bytes=row.apparent_bytes,
        disk_bytes=row.disk_bytes,
        file_count=row.file_count,
        dir_count=row.dir_count,
        error=row.error,
    )


def _with_snapshot(row: DirectoryAggregate, snapshot_id: int) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=row.path,
        parent_path=row.parent_path,
        depth=row.depth,
        apparent_bytes=row.apparent_bytes,
        disk_bytes=row.disk_bytes,
        file_count=row.file_count,
        dir_count=row.dir_count,
        error=row.error,
    )


# --- measurement --------------------------------------------------------------


def _read_pragmas(connection: sqlite3.Connection) -> dict[str, object]:
    """The build PRAGMAs that must match across OLD and NEW (Pitfall 4)."""
    return {
        "page_size": int(connection.execute("PRAGMA page_size").fetchone()[0]),
        "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
        "auto_vacuum": int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]),
    }


def measure_db_size(connection: sqlite3.Connection, db_path: Path) -> SizeMeasurement:
    """VACUUM, then read size two reconciling ways + the dbstat breakdown.

    ``page_count*page_size`` MUST equal ``os.path.getsize()`` post-VACUUM (a WAL
    checkpoint is forced by VACUUM); a mismatch means an uncheckpointed WAL is
    hiding bytes and the comparison would be a lie -- so we assert it.
    """
    pragmas = _read_pragmas(connection)
    connection.execute("VACUUM")
    connection.commit()
    # VACUUM does not checkpoint the WAL into the main file, so os.path.getsize()
    # on the main DB would under-report (bytes still in the -wal). Force a full
    # TRUNCATE checkpoint so the page store and stat() reconcile (Don't-Hand-Roll).
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.commit()

    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    page_bytes = page_size * page_count
    stat_bytes = os.path.getsize(db_path)

    dbstat = tuple(
        DbstatEntry(name=str(row[0]), pgsize=int(row[1]), ncell=int(row[2]))
        for row in connection.execute(DBSTAT_SQL).fetchall()
    )

    measurement = SizeMeasurement(
        page_bytes=page_bytes,
        stat_bytes=stat_bytes,
        dbstat=dbstat,
        pragmas=pragmas,
    )
    if not measurement.reconciles:
        raise AssertionError(
            f"size reconciliation failed for {db_path}: "
            f"page_count*page_size={page_bytes} != stat()={stat_bytes} "
            "(uncheckpointed WAL? VACUUM did not checkpoint)"
        )
    return measurement


def _remove_db_files(db_path: Path) -> None:
    """Delete a scratch DB and its ``-wal`` / ``-shm`` sidecars so a build starts empty.

    The benchmark builds into a FIXED scratch dir (``<db>/../.bench_size``). A prior
    run — or a crashed/timed-out one — leaves a partial DB there. The NEW side's
    ``CREATE TABLE IF NOT EXISTS`` would silently append to it (poisoning the path
    dictionary with the previous run's paths) and the OLD side's plain ``CREATE TABLE``
    would error. Wiping the file first makes every build idempotent and crash-proof.
    """
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(db_path) + suffix).unlink()
        except FileNotFoundError:
            pass


def _build_new_db(
    db_path: Path, snapshots: list[list[DirectoryAggregate]]
) -> SizeMeasurement:
    """NEW-DICT side: the product schema via the real collect write path."""
    _remove_db_files(db_path)
    connection = open_connection(db_path)
    try:
        initialize_database(connection)
        for rows in snapshots:
            snapshot = create_snapshot(connection, Path("/root"))
            persisted = [_with_snapshot(row, snapshot.id) for row in rows]
            insert_directory_rows(connection, persisted)
        return measure_db_size(connection, db_path)
    finally:
        connection.close()


def _build_old_db(
    db_path: Path, snapshots: list[list[DirectoryAggregate]]
) -> SizeMeasurement:
    """OLD-BLOB side: inline legacy DDL, IDENTICAL PRAGMAs to the NEW side."""
    # Reuse open_connection so the virgin-file page_size/auto_vacuum/journal PRAGMAs
    # are byte-identical to the NEW side -- the schema shape is the only variable.
    _remove_db_files(db_path)
    connection = open_connection(db_path)
    try:
        connection.executescript(OLD_BLOB_SCHEMA_SQL)
        connection.commit()
        for rows in snapshots:
            cursor = connection.execute(
                "INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error) "
                "VALUES ('1970-01-01T00:00:00Z', NULL, '/root', 'complete', NULL, NULL)"
            )
            snapshot_id = int(cursor.lastrowid)
            connection.commit()
            for start in range(0, len(rows), INSERT_BATCH_SIZE):
                batch = rows[start : start + INSERT_BATCH_SIZE]
                connection.executemany(
                    OLD_BLOB_INSERT_SQL,
                    [_old_blob_row_values(snapshot_id, row) for row in batch],
                )
            connection.commit()
        return measure_db_size(connection, db_path)
    finally:
        connection.close()


def _old_blob_row_values(snapshot_id: int, row: DirectoryAggregate) -> tuple[object, ...]:
    name = row.path.rsplit(b"/", 1)[-1]
    return (
        snapshot_id,
        sqlite3.Binary(row.path),
        sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
        sqlite3.Binary(name),
        row.depth,
        row.apparent_bytes,
        row.disk_bytes,
        row.file_count,
        row.dir_count,
        row.error,
    )


def compare_old_vs_new(
    base_rows: list[DirectoryAggregate] | tuple[DirectoryAggregate, ...],
    *,
    snapshots: int,
    churn: float,
    workdir: Path,
) -> Comparison:
    """Build OLD and NEW DBs (identical PRAGMAs), VACUUM both, return the delta.

    ``per_snapshot_bytes`` is the MEASURED after-VACUUM NEW total divided across the
    synthetic snapshots -- the figure the D-09 gate is set against.
    """
    replicated = replicate_snapshots(base_rows, snapshots=snapshots, churn=churn)
    workdir = Path(workdir)
    new = _build_new_db(workdir / "bench_new.sqlite3", replicated)
    old = _build_old_db(workdir / "bench_old.sqlite3", replicated)

    per_snapshot_bytes = new.page_bytes // snapshots if snapshots else new.page_bytes
    return Comparison(
        old=old,
        new=new,
        snapshots=snapshots,
        per_snapshot_bytes=per_snapshot_bytes,
    )


# --- D-09 gate (pure functions) ----------------------------------------------


def reduction_ratio(old_bytes: int, new_bytes: int) -> float:
    """OLD/NEW size reduction, reported as COLOR (never the gate). Div-by-zero -> 1.0."""
    if new_bytes == 0:
        return 1.0
    return old_bytes / new_bytes


def evaluate_byte_budget(per_snapshot_bytes: int, budget_bytes: int) -> BudgetVerdict:
    """D-09 gate: PASS when the measured per-snapshot bytes are within budget.

    The verdict is PASS/FAIL only; the reduction ratio is reported separately as
    color (see ``reduction_ratio``) and is explicitly NOT the gate.
    """
    return BudgetVerdict(
        per_snapshot_bytes=per_snapshot_bytes,
        budget_bytes=budget_bytes,
        passed=per_snapshot_bytes <= budget_bytes,
    )


# --- dev entry point ----------------------------------------------------------


def _load_real_scan_rows(db_path: str) -> list[DirectoryAggregate]:
    """Read one real scan's directory rows (latest snapshot) from a product DB.

    Reads via the dictionary JOIN so it works on the NEW product schema produced by
    a real ``collect`` run.
    """
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        snap = connection.execute(
            "SELECT id FROM snapshots ORDER BY started_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if snap is None:
            return []
        snapshot_id = int(snap["id"])
        rows = connection.execute(
            """
            SELECT p.path AS path, pp.path AS parent_path,
                   d.depth, d.apparent_bytes, d.disk_bytes,
                   d.file_count, d.dir_count, d.error
            FROM directory_sizes d
            JOIN paths p ON p.id = d.path_id
            LEFT JOIN paths pp ON pp.id = d.parent_id
            WHERE d.snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        DirectoryAggregate(
            snapshot_id=0,
            path=bytes(row["path"]),
            parent_path=bytes(row["parent_path"]) if row["parent_path"] is not None else None,
            depth=int(row["depth"]),
            apparent_bytes=int(row["apparent_bytes"]),
            disk_bytes=int(row["disk_bytes"]),
            file_count=int(row["file_count"]),
            dir_count=int(row["dir_count"]),
            error=row["error"],
        )
        for row in rows
    ]


def _print_breakdown(label: str, measurement: SizeMeasurement) -> None:
    print(f"{label}: total={measurement.page_bytes} bytes (stat={measurement.stat_bytes})")
    for entry in sorted(measurement.dbstat, key=lambda e: e.pgsize, reverse=True):
        print(f"    {entry.name:<32} {entry.pgsize:>12} bytes  ncell={entry.ncell}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m watchdirs.bench.size",
        description="Replicate->VACUUM->dbstat OLD-vs-NEW size benchmark + D-09 byte-budget gate.",
    )
    parser.add_argument("db", help="a real-scan product DB to replicate from")
    parser.add_argument("--snapshots", type=int, default=412, help="synthetic snapshots to replicate")
    parser.add_argument("--churn", type=float, required=True, help="measured churn rate (watchdirs.bench.churn)")
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="D-09 per-snapshot byte budget; if set, prints the PASS/FAIL verdict",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    base_rows = _load_real_scan_rows(args.db)
    if not base_rows:
        print(f"(no rows found in {args.db}; need a completed scan)", file=sys.stderr)
        return 2

    workdir = Path(args.db).resolve().parent / ".bench_size"
    workdir.mkdir(parents=True, exist_ok=True)
    comparison = compare_old_vs_new(
        base_rows, snapshots=args.snapshots, churn=args.churn, workdir=workdir
    )

    _print_breakdown("OLD-BLOB", comparison.old)
    _print_breakdown("NEW-DICT", comparison.new)
    print(
        f"snapshots={comparison.snapshots} churn={args.churn} "
        f"per_snapshot_bytes={comparison.per_snapshot_bytes}"
    )
    print(f"reduction_ratio={comparison.reduction_ratio:.2f}x  (color, NOT the gate)")

    if args.budget is not None:
        verdict = evaluate_byte_budget(comparison.per_snapshot_bytes, args.budget)
        print(
            f"D-09 budget={verdict.budget_bytes} bytes/snapshot -> {verdict.verdict} "
            f"(measured {verdict.per_snapshot_bytes})"
        )
    else:
        print("(no --budget given; set the D-09 budget against THIS measured per-snapshot figure)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
