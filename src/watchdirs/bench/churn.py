"""Path churn / cardinality measurement on the ``directory_sizes`` schema.

This is the D-08 method-C benchmark deliverable. Since the Plan 02 dictionary rewrite
it reads the integer ``path_id`` FK (each distinct path is stored once in ``paths``);
distinct ``path_id`` count equals distinct-path count, so cardinality semantics are
unchanged from the pre-rewrite blob version.

The measured churn rate and ``dedup_ratio`` are the ROI-determining input to the D-09
per-snapshot byte budget gate: high ``dedup_ratio`` / low churn implies a ~5-6x size
win from the flat path dictionary; high churn collapses the win toward index int-ization.

Stdlib only (``sqlite3``, ``dataclasses``). Snapshot ids are bound as named parameters;
no path bytes are ever interpolated into SQL (T-03.1-01-01 mitigation).

Run as a dev tool:

    uv run python -m watchdirs.bench.churn <db_path>

which prints the per-root churn series and the global dedup_ratio to stdout. This is a
dev/CI tool, not the collect runtime, so plain stdout is fine here.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import sys

# --- SQL (verbatim from 03.1-RESEARCH.md ## Code Examples) -------------------
#
# Reads ``path`` on the OLD blob schema. ``EXCEPT`` computes set difference of the
# path columns between the two snapshots; ``COUNT(DISTINCT path)`` measures the
# cross-snapshot duplication that the dictionary would eliminate.

CHURN_SQL = """
SELECT
  (SELECT COUNT(*) FROM directory_sizes WHERE snapshot_id = :prev) AS rows_prev,
  (SELECT COUNT(*) FROM directory_sizes WHERE snapshot_id = :curr) AS rows_curr,
  (SELECT COUNT(*) FROM (
      SELECT path_id FROM directory_sizes WHERE snapshot_id = :curr
      EXCEPT
      SELECT path_id FROM directory_sizes WHERE snapshot_id = :prev)) AS new_paths,
  (SELECT COUNT(*) FROM (
      SELECT path_id FROM directory_sizes WHERE snapshot_id = :prev
      EXCEPT
      SELECT path_id FROM directory_sizes WHERE snapshot_id = :curr)) AS deleted_paths
"""

CARDINALITY_SQL = """
SELECT
  (SELECT COUNT(DISTINCT path_id) FROM directory_sizes) AS distinct_paths,
  (SELECT COUNT(*)                FROM directory_sizes) AS total_rows
"""


@dataclass(frozen=True)
class ChurnResult:
    """Churn between one consecutive (prev, curr) snapshot pair of a root."""

    prev_snapshot_id: int
    curr_snapshot_id: int
    rows_prev: int
    rows_curr: int
    new_paths: int
    deleted_paths: int

    @property
    def churn_rate(self) -> float:
        """Fraction of the current snapshot's rows that are newly introduced.

        Guarded against div-by-zero (empty current snapshot -> 0.0).
        """
        if self.rows_curr == 0:
            return 0.0
        return self.new_paths / self.rows_curr


@dataclass(frozen=True)
class CardinalityResult:
    """Distinct-vs-total path cardinality across all snapshots in the DB."""

    distinct_paths: int
    total_rows: int

    @property
    def dedup_ratio(self) -> float:
        """How many times the average path is stored across snapshots.

        ``total_rows / distinct_paths``. This IS the ROI driver per the panel.
        Guarded against div-by-zero (no distinct paths -> 1.0, i.e. nothing to dedup).
        """
        if self.distinct_paths == 0:
            return 1.0
        return self.total_rows / self.distinct_paths


def measure_churn(
    connection: sqlite3.Connection,
    prev_snapshot_id: int,
    curr_snapshot_id: int,
) -> ChurnResult:
    """Measure path churn between two consecutive snapshots of the same root.

    Returns the four raw counts plus a derived ``churn_rate``. Snapshot ids are
    bound as named parameters (``:prev`` / ``:curr``); nothing is interpolated.
    """
    row = connection.execute(
        CHURN_SQL,
        {"prev": prev_snapshot_id, "curr": curr_snapshot_id},
    ).fetchone()
    return ChurnResult(
        prev_snapshot_id=prev_snapshot_id,
        curr_snapshot_id=curr_snapshot_id,
        rows_prev=int(row["rows_prev"]),
        rows_curr=int(row["rows_curr"]),
        new_paths=int(row["new_paths"]),
        deleted_paths=int(row["deleted_paths"]),
    )


def measure_cardinality(connection: sqlite3.Connection) -> CardinalityResult:
    """Measure distinct vs total path rows across every snapshot in the DB.

    The derived ``dedup_ratio`` (total / distinct) quantifies how much the flat
    path dictionary would save by storing each distinct path once.
    """
    row = connection.execute(CARDINALITY_SQL).fetchone()
    return CardinalityResult(
        distinct_paths=int(row["distinct_paths"]),
        total_rows=int(row["total_rows"]),
    )


def _consecutive_snapshot_pairs(connection: sqlite3.Connection) -> list[tuple[str, int, int]]:
    """Yield ``(root_path, prev_id, curr_id)`` for each consecutive pair, per root.

    Snapshots are ordered by ``started_at`` then ``id`` within each ``root_path``
    so a multi-scan dev DB produces a churn series per root.
    """
    rows = connection.execute(
        """
        SELECT id, root_path
        FROM snapshots
        ORDER BY root_path, started_at, id
        """
    ).fetchall()

    by_root: dict[str, list[int]] = {}
    for row in rows:
        by_root.setdefault(row["root_path"], []).append(int(row["id"]))

    pairs: list[tuple[str, int, int]] = []
    for root_path, ids in by_root.items():
        for prev_id, curr_id in zip(ids, ids[1:]):
            pairs.append((root_path, prev_id, curr_id))
    return pairs


def measure_churn_series(connection: sqlite3.Connection) -> list[tuple[str, ChurnResult]]:
    """Driver: measure churn over every consecutive same-root snapshot pair.

    Returns ``(root_path, ChurnResult)`` tuples in chronological order per root.
    Feed this series into method A's synthetic replication and the D-09 budget.
    """
    return [
        (root_path, measure_churn(connection, prev_id, curr_id))
        for root_path, prev_id, curr_id in _consecutive_snapshot_pairs(connection)
    ]


def _open_readonly(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m watchdirs.bench.churn <db_path>", file=sys.stderr)
        return 2

    db_path = args[0]
    connection = _open_readonly(db_path)
    try:
        series = measure_churn_series(connection)
        cardinality = measure_cardinality(connection)
    finally:
        connection.close()

    if not series:
        print("(no consecutive snapshot pairs; need >= 2 scans of a root)")
    for root_path, result in series:
        print(
            f"{root_path}: "
            f"rows_prev={result.rows_prev} rows_curr={result.rows_curr} "
            f"new={result.new_paths} deleted={result.deleted_paths} "
            f"churn_rate={result.churn_rate:.4f}"
        )
    print(
        f"cardinality: distinct_paths={cardinality.distinct_paths} "
        f"total_rows={cardinality.total_rows} "
        f"dedup_ratio={cardinality.dedup_ratio:.2f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
