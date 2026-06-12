from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def test_snapshot_lifecycle_fields(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    columns = {
        row["name"]: row["type"]
        for row in connection.execute("PRAGMA table_info('snapshots')")
    }

    assert columns["status"] == "TEXT"
    assert columns["started_at"] == "TEXT"
    assert columns["finished_at"] == "TEXT"
    assert columns["root_path"] == "TEXT"
    assert columns["notes"] == "TEXT"
    assert columns["error"] == "TEXT"


def test_schema_user_version_and_indexes(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    index_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='directory_sizes'"
        )
    }

    assert user_version == migrations_module.SCHEMA_VERSION
    assert "directory_sizes_path_snapshot_idx" in index_names
    assert "directory_sizes_snapshot_size_idx" in index_names
    assert "directory_sizes_snapshot_parent_idx" in index_names


def test_connection_pragmas_enabled(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)

    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert foreign_keys == 1
    assert busy_timeout == 5000


def test_directory_path_columns_are_blob_backed(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    columns = {
        row["name"]: row["type"]
        for row in connection.execute("PRAGMA table_info('directory_sizes')")
    }

    assert columns["path"] == "BLOB"
    assert columns["parent_path"] == "BLOB"
    assert columns["name"] == "BLOB"


class RecordingConnection:
    def __init__(self) -> None:
        self.batches: list[tuple[str, list[tuple[object, ...]]]] = []
        self.commit_calls = 0

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def executemany(self, sql: str, rows) -> None:
        batch = list(rows)
        self.batches.append((sql, batch))

    def commit(self) -> None:
        self.commit_calls += 1


def test_insert_directory_rows_uses_executemany_batches(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    rows = [
        models_module.DirectoryAggregate(
            snapshot_id=1,
            path=f"/root/dir-{index}".encode(),
            parent_path=b"/root",
            name=f"dir-{index}".encode(),
            depth=1,
            apparent_bytes=index,
            disk_bytes=index,
            file_count=1,
            dir_count=0,
            error=None,
        )
        for index in range(10005)
    ]
    connection = RecordingConnection()

    migrations_module.insert_directory_rows(connection, rows)

    assert [len(batch) for _, batch in connection.batches] == [10000, 5]
    assert all("INSERT INTO directory_sizes" in sql for sql, _ in connection.batches)
    assert connection.commit_calls == 1

