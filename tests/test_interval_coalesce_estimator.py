from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.estimate_interval_coalesce_savings import estimate_coalesce_savings
from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import initialize_database


def _path_id(connection: sqlite3.Connection, path: bytes) -> int:
    cursor = connection.execute(
        "INSERT INTO paths (path) VALUES (?)",
        (sqlite3.Binary(path),),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_interval(
    connection: sqlite3.Connection,
    *,
    path_id: int,
    valid_from: int,
    valid_to: int | None,
    disk_bytes: int,
) -> None:
    connection.execute(
        """
        INSERT INTO directory_size_intervals (
            root_path,
            path_id,
            valid_from_snapshot_id,
            valid_to_snapshot_id,
            parent_id,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error,
            collapsed,
            collapse_reason,
            collapsed_dirs,
            top_child_id,
            top_child_disk_bytes
        ) VALUES ('/root', ?, ?, ?, NULL, 1, ?, ?, 1, 0, NULL, 0, NULL, NULL, NULL, NULL)
        """,
        (path_id, valid_from, valid_to, disk_bytes, disk_bytes),
    )


def test_estimator_counts_only_adjacent_equal_interval_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "watchdirs.sqlite3"
    connection = open_connection(db_path)
    initialize_database(connection)
    single_pair = _path_id(connection, b"/root/single-pair")
    equal_chain = _path_id(connection, b"/root/equal-chain")
    changed_state = _path_id(connection, b"/root/changed-state")
    gap = _path_id(connection, b"/root/gap")

    _insert_interval(connection, path_id=single_pair, valid_from=1, valid_to=3, disk_bytes=100)
    _insert_interval(connection, path_id=single_pair, valid_from=3, valid_to=None, disk_bytes=100)
    _insert_interval(connection, path_id=equal_chain, valid_from=1, valid_to=3, disk_bytes=200)
    _insert_interval(connection, path_id=equal_chain, valid_from=3, valid_to=5, disk_bytes=200)
    _insert_interval(connection, path_id=equal_chain, valid_from=5, valid_to=None, disk_bytes=200)
    _insert_interval(connection, path_id=changed_state, valid_from=1, valid_to=3, disk_bytes=300)
    _insert_interval(connection, path_id=changed_state, valid_from=3, valid_to=None, disk_bytes=301)
    _insert_interval(connection, path_id=gap, valid_from=1, valid_to=3, disk_bytes=400)
    _insert_interval(connection, path_id=gap, valid_from=4, valid_to=None, disk_bytes=400)
    connection.commit()

    estimate = estimate_coalesce_savings(connection, db_path=db_path)

    assert estimate.interval_row_count == 9
    assert estimate.removable_interval_row_count == 3
    assert estimate.affected_path_count == 2
    assert estimate.removable_interval_row_percent == 33.333
    assert estimate.interval_storage_bytes is not None
    assert estimate.rough_reclaimable_storage_bytes is not None
