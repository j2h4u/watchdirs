#!/usr/bin/env python3
"""Benchmark a disposable interval representation of the watchdirs database.

This is intentionally independent of the production package.  It reads a
source database through SQLite's read-only URI mode and creates a new database
under an output directory that must not already exist.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SOURCE_TABLES = {
    "snapshots": ("id", "started_at", "finished_at", "root_path", "status", "notes", "error"),
    "paths": ("id", "path"),
    "snapshot_mounts": (
        "id",
        "snapshot_id",
        "mount_id",
        "parent_id",
        "major_minor",
        "root",
        "mount_point",
        "filesystem_type",
        "mount_source",
    ),
}
STATE_COLUMNS = (
    "parent_id",
    "depth",
    "apparent_bytes",
    "disk_bytes",
    "file_count",
    "dir_count",
    "error",
    "collapsed",
    "collapse_reason",
    "collapsed_dirs",
    "top_child_id",
    "top_child_disk_bytes",
)
REQUIRED_DIRECTORY_COLUMNS = ("snapshot_id", "path_id", *STATE_COLUMNS)


def fail(message: str) -> None:
    raise RuntimeError(message)


def connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(f"source database does not exist or is not a regular file: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.Error as exc:
        fail(f"cannot open source database read-only: {exc}")


@contextmanager
def locked_source(path: Path) -> Iterator[None]:
    """Prevent a collect/prune writer while SQLite copies the live database."""
    lock_path = Path(f"{path}.lock")
    if not lock_path.is_file():
        fail(f"watchdirs operation lock does not exist: {lock_path}")
    with lock_path.open("rb") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "watchdirs is collecting or maintaining the source database; retry after it finishes"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error as exc:
        fail(f"cannot inspect source table {table!r}: {exc}")


def validate_source(connection: sqlite3.Connection) -> None:
    for table, columns in (*SOURCE_TABLES.items(), ("directory_sizes", REQUIRED_DIRECTORY_COLUMNS)):
        actual = table_columns(connection, table)
        missing = sorted(set(columns) - actual)
        if missing:
            fail(f"source table {table!r} is missing required columns: {', '.join(missing)}")


def create_candidate(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            error TEXT
        );
        CREATE TABLE paths (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE);
        CREATE TABLE snapshot_mounts (
            id INTEGER PRIMARY KEY,
            snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            mount_id INTEGER NOT NULL,
            parent_id INTEGER NOT NULL,
            major_minor TEXT NOT NULL,
            root BLOB NOT NULL,
            mount_point BLOB NOT NULL,
            filesystem_type TEXT NOT NULL,
            mount_source TEXT NOT NULL
        );
        CREATE TABLE directory_size_intervals (
            id INTEGER PRIMARY KEY,
            root_path TEXT NOT NULL,
            path_id INTEGER NOT NULL REFERENCES paths(id),
            valid_from_snapshot_id INTEGER NOT NULL,
            valid_to_snapshot_id INTEGER,
            parent_id INTEGER REFERENCES paths(id),
            depth INTEGER NOT NULL,
            apparent_bytes INTEGER NOT NULL,
            disk_bytes INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            dir_count INTEGER NOT NULL,
            error TEXT,
            collapsed INTEGER NOT NULL,
            collapse_reason TEXT,
            collapsed_dirs INTEGER,
            top_child_id INTEGER REFERENCES paths(id),
            top_child_disk_bytes INTEGER
        );
        CREATE INDEX intervals_path_idx
            ON directory_size_intervals(root_path, path_id, valid_from_snapshot_id);
        CREATE INDEX intervals_state_idx
            ON directory_size_intervals(valid_from_snapshot_id, valid_to_snapshot_id, root_path, path_id);
        """
    )


def copy_table(source: sqlite3.Connection, candidate: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> int:
    quoted = ", ".join(columns)
    rows = source.execute(f"SELECT {quoted} FROM {table} ORDER BY id").fetchall()
    candidate.executemany(
        f"INSERT INTO {table} ({quoted}) VALUES ({', '.join('?' for _ in columns)})",
        ([row[column] for column in columns] for row in rows),
    )
    return len(rows)


def state_tuple(row: sqlite3.Row) -> tuple[Any, ...]:
    return tuple(row[column] for column in STATE_COLUMNS)


def build_root_intervals(
    source: sqlite3.Connection,
    candidate: sqlite3.Connection,
    root_path: str,
    snapshots: list[int],
    insert_sql: str,
) -> tuple[int, int]:
    active: dict[int, tuple[int, tuple[Any, ...]]] = {}
    source_rows = 0
    interval_count = 0
    for snapshot_id in snapshots:
        rows = source.execute(
            f"SELECT path_id, {', '.join(STATE_COLUMNS)} FROM directory_sizes WHERE snapshot_id = ? ORDER BY path_id",
            (snapshot_id,),
        ).fetchall()
        current: dict[int, tuple[Any, ...]] = {}
        for row in rows:
            path_id = row["path_id"]
            if path_id in current:
                fail(f"source snapshot {snapshot_id} has duplicate directory_sizes path_id {path_id}")
            current[path_id] = state_tuple(row)
        source_rows += len(rows)
        for path_id, (start_id, _previous) in list(active.items()):
            if path_id not in current:
                candidate.execute(
                    "UPDATE directory_size_intervals SET valid_to_snapshot_id = ? WHERE root_path = ? AND path_id = ? AND valid_from_snapshot_id = ?",
                    (snapshot_id, root_path, path_id, start_id),
                )
                del active[path_id]
        for path_id, state in current.items():
            prior = active.get(path_id)
            if prior is not None and prior[1] == state:
                continue
            if prior is not None:
                candidate.execute(
                    "UPDATE directory_size_intervals SET valid_to_snapshot_id = ? WHERE root_path = ? AND path_id = ? AND valid_from_snapshot_id = ?",
                    (snapshot_id, root_path, path_id, prior[0]),
                )
            candidate.execute(insert_sql, (root_path, path_id, snapshot_id, *state))
            interval_count += 1
            active[path_id] = (snapshot_id, state)
    return source_rows, interval_count


def build_intervals(source: sqlite3.Connection, candidate: sqlite3.Connection) -> tuple[int, int]:
    snapshot_columns = table_columns(source, "snapshots")
    snapshot_query = (
        "SELECT id, root_path FROM snapshots" if "root_path" in snapshot_columns else "SELECT id FROM snapshots"
    )
    if "status" in snapshot_columns:
        snapshot_query += " WHERE status = 'complete'"
    snapshot_query += " ORDER BY id"
    snapshot_rows = source.execute(snapshot_query).fetchall()
    snapshots_by_root: dict[str, list[int]] = {}
    for snapshot in snapshot_rows:
        root_path = snapshot["root_path"] if "root_path" in snapshot.keys() else "/"  # noqa: SIM118
        snapshots_by_root.setdefault(root_path, []).append(snapshot["id"])
    insert_sql = f"""
        INSERT INTO directory_size_intervals
        (root_path, path_id, valid_from_snapshot_id, valid_to_snapshot_id, {", ".join(STATE_COLUMNS)})
        VALUES (?, ?, ?, NULL, {", ".join("?" for _ in STATE_COLUMNS)})
    """
    source_rows = interval_count = 0
    for root_path, snapshot_ids in snapshots_by_root.items():
        root_rows, root_intervals = build_root_intervals(source, candidate, root_path, snapshot_ids, insert_sql)
        source_rows += root_rows
        interval_count += root_intervals
    return source_rows, interval_count


def state_at(connection: sqlite3.Connection, snapshot_id: int, interval: bool) -> list[sqlite3.Row]:
    if interval:
        query = """
            SELECT directory_size_intervals.root_path, directory_size_intervals.path_id,
                   directory_size_intervals.parent_id, directory_size_intervals.depth,
                   directory_size_intervals.apparent_bytes, directory_size_intervals.disk_bytes,
                   directory_size_intervals.file_count, directory_size_intervals.dir_count,
                   directory_size_intervals.error, directory_size_intervals.collapsed,
                   directory_size_intervals.collapse_reason, directory_size_intervals.collapsed_dirs,
                   directory_size_intervals.top_child_id, directory_size_intervals.top_child_disk_bytes
            FROM directory_size_intervals
            JOIN snapshots ON snapshots.id = ? AND directory_size_intervals.root_path = snapshots.root_path
            WHERE valid_from_snapshot_id <= ?
              AND (valid_to_snapshot_id IS NULL OR ? < valid_to_snapshot_id)
            ORDER BY directory_size_intervals.root_path, directory_size_intervals.path_id
        """
        return connection.execute(query, (snapshot_id, snapshot_id, snapshot_id)).fetchall()
    if "root_path" in table_columns(connection, "snapshots"):
        query = f"SELECT snapshots.root_path, directory_sizes.path_id, {', '.join('directory_sizes.' + column for column in STATE_COLUMNS)} FROM directory_sizes JOIN snapshots ON snapshots.id = directory_sizes.snapshot_id WHERE directory_sizes.snapshot_id = ? ORDER BY snapshots.root_path, directory_sizes.path_id"
    else:
        query = f"SELECT '/' AS root_path, path_id, {', '.join(STATE_COLUMNS)} FROM directory_sizes WHERE snapshot_id = ? ORDER BY path_id"
    return connection.execute(query, (snapshot_id,)).fetchall()


def diff_rows(rows_before: list[sqlite3.Row], rows_after: list[sqlite3.Row]) -> dict[str, int]:
    before = {(row["root_path"], row["path_id"]): row for row in rows_before}
    after = {(row["root_path"], row["path_id"]): row for row in rows_after}
    changed = 0
    apparent_delta = 0
    disk_delta = 0
    for path_id in before.keys() | after.keys():
        old = before.get(path_id)
        new = after.get(path_id)
        old_apparent = old["apparent_bytes"] if old else 0
        new_apparent = new["apparent_bytes"] if new else 0
        old_disk = old["disk_bytes"] if old else 0
        new_disk = new["disk_bytes"] if new else 0
        if old is None or new is None or state_tuple(old) != state_tuple(new):
            changed += 1
        apparent_delta += new_apparent - old_apparent
        disk_delta += new_disk - old_disk
    return {"changed_rows": changed, "apparent_delta": apparent_delta, "disk_delta": disk_delta}


def timed(call: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call()
    return result, time.perf_counter() - started


def validate_all_complete_states(
    source: sqlite3.Connection, candidate: sqlite3.Connection, snapshot_ids: list[int]
) -> None:
    for snapshot_id in snapshot_ids:
        source_state = state_at(source, snapshot_id, False)
        candidate_state = state_at(candidate, snapshot_id, True)
        if [tuple(row) for row in source_state] != [tuple(row) for row in candidate_state]:
            fail(f"candidate state does not exactly match baseline at complete snapshot {snapshot_id}")


def database_bytes(path: Path) -> int:
    return path.stat().st_size


def make_baseline(source_path: Path, baseline_path: Path) -> None:
    with locked_source(source_path):
        source = connect_read_only(source_path)
        try:
            baseline = sqlite3.connect(baseline_path)
            try:
                source.backup(baseline)
                baseline.execute("PRAGMA foreign_keys = ON")
                baseline.execute("DELETE FROM snapshots WHERE status != 'complete'")
                baseline.execute(
                    """
                    DELETE FROM paths
                    WHERE NOT EXISTS (SELECT 1 FROM directory_sizes WHERE path_id = paths.id)
                      AND NOT EXISTS (SELECT 1 FROM directory_sizes WHERE parent_id = paths.id)
                      AND NOT EXISTS (SELECT 1 FROM directory_sizes WHERE top_child_id = paths.id)
                    """
                )
                baseline.commit()
                baseline.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
                baseline.execute("VACUUM")
                baseline.commit()
            finally:
                baseline.close()
        finally:
            source.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", type=Path, required=True, help="read-only source SQLite database")
    parser.add_argument("--output-dir", type=Path, required=True, help="new, non-existent candidate directory")
    parser.add_argument("--from-snapshot", type=int, help="lower snapshot id for the diff benchmark")
    parser.add_argument("--to-snapshot", type=int, help="upper snapshot id for the diff benchmark")
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:  # noqa: PLR0914, PLR0915
    source_path = args.source_db.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        fail(f"refusing candidate output directory because it already exists: {output_dir}")
    if args.from_snapshot is not None and args.to_snapshot is None:
        fail("--from-snapshot requires --to-snapshot")
    if args.to_snapshot is not None and args.from_snapshot is None:
        fail("--to-snapshot requires --from-snapshot")
    if args.from_snapshot is not None and args.from_snapshot >= args.to_snapshot:
        fail("--from-snapshot must be less than --to-snapshot")
    if not source_path.is_file():
        fail(f"source database does not exist or is not a regular file: {source_path}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir()
    baseline_path = output_dir / "baseline.sqlite3"
    candidate_path = output_dir / "candidate.sqlite3"
    make_baseline(source_path, baseline_path)
    source = connect_read_only(baseline_path)
    try:
        validate_source(source)
        candidate = sqlite3.connect(candidate_path)
        candidate.row_factory = sqlite3.Row
        try:
            create_candidate(candidate)
            copied_rows = {
                table: copy_table(source, candidate, table, columns) for table, columns in SOURCE_TABLES.items()
            }
            source_row_count, interval_count = build_intervals(source, candidate)
            candidate.commit()
            source_snapshot_ids = [
                row["id"] for row in source.execute("SELECT id FROM snapshots WHERE status = 'complete' ORDER BY id")
            ]
            if not source_snapshot_ids:
                fail("source database contains no complete snapshots")
            from_id = (
                args.from_snapshot
                if args.from_snapshot is not None
                else source_snapshot_ids[-2]
                if len(source_snapshot_ids) > 1
                else source_snapshot_ids[0]
            )
            to_id = args.to_snapshot if args.to_snapshot is not None else source_snapshot_ids[-1]
            if from_id not in source_snapshot_ids or to_id not in source_snapshot_ids:
                fail(f"requested snapshot ids are not present in source: {from_id}, {to_id}")
            validate_all_complete_states(source, candidate, source_snapshot_ids)

            source_state_before, source_state_time_before = timed(lambda: state_at(source, from_id, False))
            source_state_after, source_state_time_after = timed(lambda: state_at(source, to_id, False))
            candidate_state_before, candidate_state_time_before = timed(lambda: state_at(candidate, from_id, True))
            candidate_state_after, candidate_state_time_after = timed(lambda: state_at(candidate, to_id, True))
            source_diff, source_diff_time = timed(lambda: diff_rows(source_state_before, source_state_after))
            candidate_diff, candidate_diff_time = timed(
                lambda: diff_rows(candidate_state_before, candidate_state_after)
            )
            if source_diff != candidate_diff:
                fail(f"candidate diff does not match source: source={source_diff!r} candidate={candidate_diff!r}")
            candidate.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            candidate.execute("VACUUM")
            candidate.commit()
        finally:
            candidate.close()
    finally:
        source.close()

    original_bytes = database_bytes(baseline_path)
    candidate_bytes = database_bytes(candidate_path)
    return {
        "source": str(source_path),
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "scope": "complete snapshots only; incomplete snapshot rows are excluded from both state benchmarks",
        "snapshots": len(source_snapshot_ids),
        "copied_rows": copied_rows,
        "original_rows": {"directory_sizes": source_row_count},
        "candidate_rows": {"directory_size_intervals": interval_count},
        "original_bytes": original_bytes,
        "candidate_bytes": candidate_bytes,
        "savings_bytes": original_bytes - candidate_bytes,
        "savings_percent": (100 * (original_bytes - candidate_bytes) / original_bytes) if original_bytes else 0.0,
        "benchmark": {
            "from_snapshot": from_id,
            "to_snapshot": to_id,
            "state_at_snapshot": {
                "source_seconds": source_state_time_before + source_state_time_after,
                "candidate_seconds": candidate_state_time_before + candidate_state_time_after,
                "source_rows": len(source_state_after),
                "candidate_rows": len(candidate_state_after),
            },
            "diff": {
                "source_seconds": source_diff_time,
                "candidate_seconds": candidate_diff_time,
                "source": source_diff,
                "candidate": candidate_diff,
            },
        },
    }


def main() -> int:
    try:
        print(json.dumps(run(parse_args()), indent=2, sort_keys=True))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"interval storage spike failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
