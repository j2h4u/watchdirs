from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

DEFAULT_DB_PATH = Path("/var/lib/watchdirs/watchdirs.sqlite3")
INTERVAL_TABLE_NAME = "directory_size_intervals"
STATE_COLUMNS = (
    "parent_id",
    "depth",
    "apparent_bytes",
    "disk_bytes",
    "file_count",
    "dir_count",
    "error",
    "hardlink_file_count",
    "hardlink_duplicate_count",
    "hardlink_duplicate_disk_bytes",
    "hardlink_first_seen_disk_bytes",
    "collapsed",
    "collapse_reason",
    "collapsed_dirs",
    "top_child_id",
    "top_child_disk_bytes",
)


@dataclass(frozen=True, slots=True)
class CoalesceSavingsEstimate:
    db_path: str
    interval_row_count: int
    removable_interval_row_count: int
    affected_path_count: int
    removable_interval_row_percent: float
    interval_storage_bytes: int | None
    rough_reclaimable_storage_bytes: int | None


def estimate_coalesce_savings(connection: sqlite3.Connection, *, db_path: Path) -> CoalesceSavingsEstimate:
    interval_row_count = _fetch_required_int(
        connection,
        f"SELECT COUNT(*) FROM {INTERVAL_TABLE_NAME}",
    )
    removable_interval_row_count = _fetch_required_int(connection, _removable_interval_count_sql())
    affected_path_count = _fetch_required_int(connection, _affected_path_count_sql())
    removable_interval_row_percent = (
        0.0 if interval_row_count == 0 else removable_interval_row_count / interval_row_count * 100
    )
    interval_storage_bytes = _interval_storage_bytes(connection)
    rough_reclaimable_storage_bytes = (
        None
        if interval_storage_bytes is None or interval_row_count == 0
        else round(interval_storage_bytes * removable_interval_row_count / interval_row_count)
    )
    return CoalesceSavingsEstimate(
        db_path=str(db_path),
        interval_row_count=interval_row_count,
        removable_interval_row_count=removable_interval_row_count,
        affected_path_count=affected_path_count,
        removable_interval_row_percent=round(removable_interval_row_percent, 3),
        interval_storage_bytes=interval_storage_bytes,
        rough_reclaimable_storage_bytes=rough_reclaimable_storage_bytes,
    )


def _open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    resolved_db_path = db_path.resolve()
    uri = f"file:{resolved_db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _removable_interval_count_sql() -> str:
    return f"""
        WITH ordered AS (
            SELECT
                root_path,
                path_id,
                valid_from_snapshot_id,
                valid_to_snapshot_id,
                {", ".join(STATE_COLUMNS)},
                LAG(valid_to_snapshot_id) OVER interval_order AS previous_valid_to_snapshot_id,
                {_previous_state_columns_sql()}
            FROM {INTERVAL_TABLE_NAME}
            WINDOW interval_order AS (
                PARTITION BY root_path, path_id
                ORDER BY valid_from_snapshot_id
            )
        )
        SELECT COUNT(*)
        FROM ordered
        WHERE previous_valid_to_snapshot_id = valid_from_snapshot_id
          AND {_state_columns_equal_sql()}
        """


def _affected_path_count_sql() -> str:
    return f"""
        WITH ordered AS (
            SELECT
                root_path,
                path_id,
                valid_from_snapshot_id,
                valid_to_snapshot_id,
                {", ".join(STATE_COLUMNS)},
                LAG(valid_to_snapshot_id) OVER interval_order AS previous_valid_to_snapshot_id,
                {_previous_state_columns_sql()}
            FROM {INTERVAL_TABLE_NAME}
            WINDOW interval_order AS (
                PARTITION BY root_path, path_id
                ORDER BY valid_from_snapshot_id
            )
        )
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT root_path, path_id
            FROM ordered
            WHERE previous_valid_to_snapshot_id = valid_from_snapshot_id
              AND {_state_columns_equal_sql()}
        )
        """


def _previous_state_columns_sql() -> str:
    return ",\n                ".join(
        f"LAG({column_name}) OVER interval_order AS previous_{column_name}" for column_name in STATE_COLUMNS
    )


def _state_columns_equal_sql() -> str:
    return "\n          AND ".join(f"previous_{column_name} IS {column_name}" for column_name in STATE_COLUMNS)


def _interval_storage_bytes(connection: sqlite3.Connection) -> int | None:
    try:
        dbstat_names = _interval_dbstat_names(connection)
        if not dbstat_names:
            return None
        placeholders = ",".join("?" for _ in dbstat_names)
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                f"SELECT SUM(pgsize) FROM dbstat WHERE name IN ({placeholders})",
                dbstat_names,
            ).fetchone(),
        )
    except sqlite3.DatabaseError:
        return None
    if row is None or row[0] is None:
        return None
    return int(cast(int | str, row[0]))


def _interval_dbstat_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
            SELECT name
            FROM sqlite_schema
            WHERE tbl_name = ?
              AND type IN ('table', 'index')
            ORDER BY name
            """,
            (INTERVAL_TABLE_NAME,),
        ).fetchall(),
    )
    names = {INTERVAL_TABLE_NAME}
    names.update(cast(str, row["name"]) for row in rows)
    return tuple(sorted(names))


def _fetch_required_int(connection: sqlite3.Connection, sql: str) -> int:
    row = cast(sqlite3.Row | None, connection.execute(sql).fetchone())
    if row is None or row[0] is None:
        raise RuntimeError("sqlite query unexpectedly returned no integer result")
    return int(cast(int | str, row[0]))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Estimate read-only savings from coalescing adjacent equal watchdirs interval rows.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"watchdirs SQLite database path; default: {DEFAULT_DB_PATH}",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    db_path = cast(Path, args.db)
    try:
        connection = _open_readonly_connection(db_path)
    except sqlite3.Error as exc:
        print(
            json.dumps(
                {
                    "db_path": str(db_path),
                    "error": {"code": "database_open_failed", "message": str(exc)},
                    "ok": False,
                },
                sort_keys=True,
            )
        )
        return 1
    try:
        estimate = estimate_coalesce_savings(connection, db_path=db_path)
    except sqlite3.Error as exc:
        print(
            json.dumps(
                {
                    "db_path": str(db_path),
                    "error": {"code": "estimate_failed", "message": str(exc)},
                    "ok": False,
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        connection.close()
    print(json.dumps({"estimate": asdict(estimate), "ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
