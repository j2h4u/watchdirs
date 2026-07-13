# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import (
    SCHEMA_VERSION,
    create_snapshot,
    finalize_snapshot,
    initialize_database,
    insert_directory_rows,
)
from watchdirs.models import DirectoryAggregate, SnapshotStatus


def _fresh(tmp_path: Path) -> sqlite3.Connection:
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_v7_schema_uses_intervals_and_has_no_legacy_table(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 7
    tables = _table_names(connection)
    assert "directory_size_intervals" in tables
    assert "directory_size_diagnostics" in tables
    legacy_table = "directory" + "_sizes"
    assert legacy_table not in tables

    interval_columns = {row["name"] for row in connection.execute("PRAGMA table_info(directory_size_intervals)")}
    assert {
        "root_path",
        "path_id",
        "valid_from_snapshot_id",
        "valid_to_snapshot_id",
        "apparent_bytes",
        "disk_bytes",
        "collapsed",
        "top_child_id",
    } <= interval_columns
    foreign_keys = connection.execute("PRAGMA foreign_key_list(directory_size_intervals)").fetchall()
    assert not any(row["from"] in {"valid_from_snapshot_id", "valid_to_snapshot_id"} for row in foreign_keys)


def test_schema_initialization_is_idempotent_and_rejects_legacy_versions(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    initialize_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 7

    legacy = open_connection(tmp_path / "legacy.sqlite3")
    legacy.execute("PRAGMA user_version = 6")
    with pytest.raises(RuntimeError, match="clean schema version 7"):
        initialize_database(legacy)


def test_complete_snapshot_promotes_rows_to_one_interval_per_state(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    snapshot = create_snapshot(connection, Path("/root"))
    row = DirectoryAggregate(
        snapshot_id=snapshot.id,
        path=b"/root",
        parent_path=None,
        depth=0,
        apparent_bytes=111,
        disk_bytes=222,
        file_count=3,
        dir_count=1,
        error=None,
    )
    insert_directory_rows(connection, [row])
    finalize_snapshot(connection, snapshot.id, status=SnapshotStatus.COMPLETE)

    assert connection.execute("SELECT COUNT(*) FROM directory_size_diagnostics").fetchone()[0] == 0
    interval = connection.execute(
        "SELECT valid_from_snapshot_id, valid_to_snapshot_id, disk_bytes FROM directory_size_intervals"
    ).fetchone()
    assert tuple(interval) == (snapshot.id, None, 222)


def test_non_complete_snapshot_keeps_diagnostic_rows(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    snapshot = create_snapshot(connection, Path("/root"))
    insert_directory_rows(
        connection,
        [
            DirectoryAggregate(
                snapshot_id=snapshot.id,
                path=b"/root",
                parent_path=None,
                depth=0,
                apparent_bytes=1,
                disk_bytes=2,
                file_count=1,
                dir_count=0,
                error="partial",
            )
        ],
    )
    finalize_snapshot(connection, snapshot.id, status=SnapshotStatus.PARTIAL)

    assert connection.execute("SELECT COUNT(*) FROM directory_size_intervals").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM directory_size_diagnostics").fetchone()[0] == 1
