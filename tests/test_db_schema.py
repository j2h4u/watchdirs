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

FILESYSTEM_HISTORY_LEGACY_SCHEMA_VERSION = 7


def _fresh(tmp_path: Path) -> sqlite3.Connection:
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _index_names(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def test_v9_schema_uses_intervals_filesystems_hardlink_metrics_and_has_no_legacy_table(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 9
    tables = _table_names(connection)
    assert "directory_size_intervals" in tables
    assert "directory_size_diagnostics" in tables
    assert "snapshot_filesystems" in tables
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
        "hardlink_file_count",
        "hardlink_duplicate_count",
        "hardlink_duplicate_disk_bytes",
        "hardlink_first_seen_disk_bytes",
        "collapsed",
        "top_child_id",
    } <= interval_columns
    foreign_keys = connection.execute("PRAGMA foreign_key_list(directory_size_intervals)").fetchall()
    assert not any(row["from"] in {"valid_from_snapshot_id", "valid_to_snapshot_id"} for row in foreign_keys)


def test_schema_indexes_orphan_path_lookup_columns(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)

    indexes = _index_names(connection)

    assert "directory_size_intervals_path_id_idx" in indexes
    assert "directory_size_intervals_root_snapshot_idx" in indexes
    assert "directory_size_diagnostics_path_id_idx" in indexes
    assert "snapshot_filesystems_snapshot_idx" in indexes
    assert "snapshot_filesystems_snapshot_mount_point_idx" in indexes
    assert "snapshot_filesystems_snapshot_domain_idx" in indexes


def test_existing_v7_database_receives_idempotent_schema_maintenance(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    connection.execute("DROP INDEX directory_size_intervals_path_id_idx")
    connection.execute("DROP INDEX directory_size_diagnostics_path_id_idx")
    connection.commit()
    assert "directory_size_intervals_path_id_idx" not in _index_names(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    initialize_database(connection)

    indexes = _index_names(connection)
    assert "directory_size_intervals_path_id_idx" in indexes
    assert "directory_size_diagnostics_path_id_idx" in indexes
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_existing_v7_database_upgrades_to_v9_filesystem_history_and_hardlink_metrics(tmp_path: Path) -> None:
    connection = open_connection(tmp_path / "legacy-v7.sqlite3")
    connection.executescript("""
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            error TEXT
        );
        INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error)
        VALUES ('2026-08-05T00:00:00Z', NULL, '/root', 'running', NULL, NULL);
    """)
    connection.execute(f"PRAGMA user_version = {FILESYSTEM_HISTORY_LEGACY_SCHEMA_VERSION}")

    initialize_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 9
    assert "snapshot_filesystems" in _table_names(connection)
    assert "snapshot_filesystems_snapshot_domain_idx" in _index_names(connection)
    interval_columns = {row["name"] for row in connection.execute("PRAGMA table_info(directory_size_intervals)")}
    assert "hardlink_duplicate_disk_bytes" in interval_columns
    assert connection.execute("SELECT root_path FROM snapshots WHERE id = 1").fetchone()[0] == "/root"


def test_existing_v8_database_upgrades_to_v9_hardlink_metrics(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    connection.execute("PRAGMA user_version = 8")
    for table_name in ("directory_size_intervals", "directory_size_diagnostics"):
        for column_name in (
            "hardlink_file_count",
            "hardlink_duplicate_count",
            "hardlink_duplicate_disk_bytes",
            "hardlink_first_seen_disk_bytes",
        ):
            connection.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
    connection.commit()

    initialize_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 9
    for table_name in ("directory_size_intervals", "directory_size_diagnostics"):
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
        assert "hardlink_file_count" in columns
        assert "hardlink_duplicate_disk_bytes" in columns


def test_schema_initialization_is_idempotent_and_rejects_legacy_versions(tmp_path: Path) -> None:
    connection = _fresh(tmp_path)
    initialize_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 9

    legacy = open_connection(tmp_path / "legacy.sqlite3")
    legacy.execute("PRAGMA user_version = 6")
    with pytest.raises(RuntimeError, match="clean schema version 9"):
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
