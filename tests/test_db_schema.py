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
    assert migrations_module.SCHEMA_VERSION == 3
    assert "directory_sizes_path_snapshot_idx" not in index_names
    assert "directory_sizes_pathid_snapshot_idx" in index_names
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


def test_directory_sizes_uses_path_dictionary(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    directory_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info('directory_sizes')")
    }
    paths_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info('paths')")
    }

    # The flat dictionary table exists with id + path.
    assert paths_columns == {"id", "path"}
    # directory_sizes references it via int FKs; the old blob columns are gone.
    assert "path_id" in directory_columns
    assert "parent_id" in directory_columns
    assert "name" not in directory_columns
    assert "path" not in directory_columns
    assert "parent_path" not in directory_columns


def test_virgin_connection_pragmas(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)

    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    auto_vacuum = connection.execute("PRAGMA auto_vacuum").fetchone()[0]
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]

    assert page_size == connection_module.WATCHDIRS_PAGE_SIZE
    assert auto_vacuum == 1  # FULL
    assert application_id == connection_module.WATCHDIRS_APPLICATION_ID


class _RecordingCursor:
    def __init__(self, conn: "RecordingConnection", sql: str, params) -> None:
        self._row = None
        self.lastrowid = None
        upper = sql.upper()
        path = params[0] if params else None
        if path is not None and not isinstance(path, (bytes, bytearray)):
            path = bytes(path)
        if "SELECT" in upper and "FROM PATHS" in upper:
            self._row = (conn._ids[path],) if path in conn._ids else None
        elif "INSERT" in upper and "PATHS" in upper:
            conn._next_id += 1
            conn._ids[path] = conn._next_id
            self.lastrowid = conn._next_id

    def fetchone(self):
        return self._row


class RecordingConnection:
    def __init__(self) -> None:
        self.batches: list[tuple[str, list[tuple[object, ...]]]] = []
        self.commit_calls = 0
        self._next_id = 0
        self._ids: dict[bytes, int] = {}

    def __enter__(self) -> RecordingConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=()):
        # Serve _resolve_path_id's SELECT/INSERT so this stays a pure unit test.
        return _RecordingCursor(self, sql, params)

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

