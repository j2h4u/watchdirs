# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _open_connection(repo_root: Path, db_path: Path) -> sqlite3.Connection:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    return connection_module.open_connection(db_path)


def _open_readonly_connection(repo_root: Path, db_path: Path) -> sqlite3.Connection:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    return connection_module.open_readonly_connection(db_path)


def _initialize_database(repo_root: Path, connection: sqlite3.Connection):
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    migrations_module.initialize_database(connection)
    return migrations_module


def _fresh_db(repo_root: Path, tmp_path: Path, *, filename: str = "watchdirs.sqlite3") -> sqlite3.Connection:
    connection = _open_connection(repo_root, tmp_path / filename)
    _initialize_database(repo_root, connection)
    return connection


def _create_v3_database(
    repo_root: Path, tmp_path: Path, *, filename: str = "watchdirs-v3.sqlite3"
) -> sqlite3.Connection:
    connection = _open_connection(repo_root, tmp_path / filename)
    connection.executescript(
        """
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            error TEXT
        );

        CREATE TABLE paths (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL UNIQUE
        );

        CREATE TABLE directory_sizes (
            id INTEGER PRIMARY KEY,
            snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            path_id INTEGER NOT NULL REFERENCES paths(id),
            parent_id INTEGER REFERENCES paths(id),
            depth INTEGER NOT NULL,
            apparent_bytes INTEGER NOT NULL,
            disk_bytes INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            dir_count INTEGER NOT NULL,
            error TEXT
        );

        CREATE INDEX directory_sizes_pathid_snapshot_idx
            ON directory_sizes(path_id, snapshot_id);
        CREATE INDEX directory_sizes_snapshot_size_idx
            ON directory_sizes(snapshot_id, disk_bytes);
        CREATE INDEX directory_sizes_snapshot_parent_idx
            ON directory_sizes(snapshot_id, parent_id);

        PRAGMA user_version = 3;
        """
    )
    return connection


def _create_v4_database(
    repo_root: Path, tmp_path: Path, *, filename: str = "watchdirs-v4.sqlite3"
) -> sqlite3.Connection:
    connection = _create_v3_database(repo_root, tmp_path, filename=filename)
    connection.executescript(
        """
        ALTER TABLE directory_sizes ADD COLUMN collapsed INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE directory_sizes ADD COLUMN collapse_reason TEXT;
        ALTER TABLE directory_sizes ADD COLUMN collapsed_dirs INTEGER;
        ALTER TABLE directory_sizes ADD COLUMN top_child_id INTEGER REFERENCES paths(id);
        ALTER TABLE directory_sizes ADD COLUMN top_child_disk_bytes INTEGER;
        PRAGMA user_version = 4;
        """
    )
    return connection


def _table_info(connection: sqlite3.Connection, table_name: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in connection.execute(f"PRAGMA table_info('{table_name}')")}


def _seed_v3_row(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO snapshots (id, started_at, finished_at, root_path, status, notes, error)
        VALUES (1, '2026-06-16T00:00:00Z', '2026-06-16T00:01:00Z', '/root', 'complete', NULL, NULL)
        """
    )
    connection.execute("INSERT INTO paths (id, path) VALUES (1, ?)", (sqlite3.Binary(b"/root"),))
    connection.execute(
        """
        INSERT INTO directory_sizes (
            snapshot_id,
            path_id,
            parent_id,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (1, 1, None, 0, 123, 456, 7, 3, None),
    )
    connection.commit()


def test_snapshot_lifecycle_fields(repo_root: Path, tmp_path: Path) -> None:
    connection = _fresh_db(repo_root, tmp_path)

    columns = {row["name"]: row["type"] for row in connection.execute("PRAGMA table_info('snapshots')")}

    assert columns["status"] == "TEXT"
    assert columns["started_at"] == "TEXT"
    assert columns["finished_at"] == "TEXT"
    assert columns["root_path"] == "TEXT"
    assert columns["notes"] == "TEXT"
    assert columns["error"] == "TEXT"


def test_create_snapshot_starts_as_running(repo_root: Path, tmp_path: Path) -> None:
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")
    connection = _fresh_db(repo_root, tmp_path)

    snapshot = migrations_module.create_snapshot(connection, "/root")

    assert snapshot.status is models_module.SnapshotStatus.RUNNING
    assert snapshot.finished_at is None
    row = connection.execute("SELECT status, finished_at FROM snapshots WHERE id = ?", (snapshot.id,)).fetchone()
    assert row is not None
    assert row["status"] == "running"
    assert row["finished_at"] is None


def test_schema_user_version_and_indexes(repo_root: Path, tmp_path: Path) -> None:
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    index_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='directory_sizes'"
        )
    }

    assert user_version == migrations_module.SCHEMA_VERSION
    assert migrations_module.SCHEMA_VERSION == 5
    assert "directory_sizes_path_snapshot_idx" not in index_names
    assert "directory_sizes_pathid_snapshot_idx" in index_names
    assert "directory_sizes_snapshot_pathid_idx" in index_names
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


def test_directory_sizes_uses_path_dictionary_and_collapse_columns(repo_root: Path, tmp_path: Path) -> None:
    connection = _fresh_db(repo_root, tmp_path)

    directory_columns = {row["name"] for row in connection.execute("PRAGMA table_info('directory_sizes')")}
    paths_columns = {row["name"] for row in connection.execute("PRAGMA table_info('paths')")}

    assert paths_columns == {"id", "path"}
    assert "path_id" in directory_columns
    assert "parent_id" in directory_columns
    assert "name" not in directory_columns
    assert "path" not in directory_columns
    assert "parent_path" not in directory_columns
    assert "collapsed" in directory_columns
    assert "collapse_reason" in directory_columns
    assert "collapsed_dirs" in directory_columns
    assert "top_child_id" in directory_columns
    assert "top_child_disk_bytes" in directory_columns


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


def test_initialize_database_migrates_v3_database_to_latest(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v3_database(repo_root, tmp_path)
    _seed_v3_row(connection)

    _initialize_database(repo_root, connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    columns = _table_info(connection, "directory_sizes")
    assert columns["collapsed"]["type"] == "INTEGER"
    assert columns["collapsed"]["notnull"] == 1
    assert columns["collapsed"]["dflt_value"] == "0"
    assert columns["collapse_reason"]["type"] == "TEXT"
    assert columns["collapsed_dirs"]["type"] == "INTEGER"
    assert columns["top_child_id"]["type"] == "INTEGER"
    assert columns["top_child_id"]["notnull"] == 0
    assert columns["top_child_disk_bytes"]["type"] == "INTEGER"

    migrated_row = connection.execute(
        """
        SELECT collapsed, collapse_reason, collapsed_dirs, top_child_id, top_child_disk_bytes
        FROM directory_sizes
        WHERE id = 1
        """
    ).fetchone()
    assert migrated_row["collapsed"] == 0
    assert migrated_row["collapse_reason"] is None
    assert migrated_row["collapsed_dirs"] is None
    assert migrated_row["top_child_id"] is None
    assert migrated_row["top_child_disk_bytes"] is None
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='directory_sizes'"
        )
    }
    assert "directory_sizes_snapshot_pathid_idx" in indexes


def test_initialize_database_migrates_v4_database_to_v5(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v4_database(repo_root, tmp_path)

    _initialize_database(repo_root, connection)

    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='directory_sizes'"
        )
    }
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert "directory_sizes_snapshot_pathid_idx" in indexes


def test_initialize_database_migration_is_idempotent(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v3_database(repo_root, tmp_path)
    _initialize_database(repo_root, connection)

    before = tuple(connection.execute("PRAGMA table_info('directory_sizes')"))
    _initialize_database(repo_root, connection)
    after = tuple(connection.execute("PRAGMA table_info('directory_sizes')"))

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert before == after


def test_initialize_database_recovers_partial_v3_collapse_columns(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v3_database(repo_root, tmp_path)
    connection.execute("ALTER TABLE directory_sizes ADD COLUMN collapsed INTEGER NOT NULL DEFAULT 0")
    connection.execute("ALTER TABLE directory_sizes ADD COLUMN collapse_reason TEXT")
    connection.commit()

    _initialize_database(repo_root, connection)

    columns = _table_info(connection, "directory_sizes")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert set(columns) >= {
        "collapsed",
        "collapse_reason",
        "collapsed_dirs",
        "top_child_id",
        "top_child_disk_bytes",
    }


def test_initialize_database_rejects_invalid_partial_collapse_shape(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v3_database(repo_root, tmp_path)
    connection.execute("ALTER TABLE directory_sizes ADD COLUMN collapsed TEXT")
    connection.commit()

    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    with pytest.raises(RuntimeError, match="collapse column"):
        migrations_module.initialize_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_readonly_connection_does_not_allow_writes(repo_root: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "watchdirs.sqlite3"
    writer = _open_connection(repo_root, db_path)
    _initialize_database(repo_root, writer)
    writer.close()

    reader = _open_readonly_connection(repo_root, db_path)
    try:
        assert reader.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match=r"readonly|query only"):
            reader.execute(
                """
                INSERT INTO snapshots (started_at, root_path, status)
                VALUES ('2026-06-17T00:00:00Z', '/', 'complete')
                """
            )
    finally:
        reader.close()


def test_initialize_database_rejects_unsupported_pre_dictionary_schema(repo_root: Path, tmp_path: Path) -> None:
    connection = _open_connection(repo_root, tmp_path / "watchdirs-v2.sqlite3")
    connection.executescript(
        """
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL,
            notes TEXT,
            error TEXT
        );
        PRAGMA user_version = 2;
        """
    )

    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    with pytest.raises(RuntimeError, match="unsupported schema version"):
        migrations_module.initialize_database(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_insert_directory_rows_persists_collapse_metadata(repo_root: Path, tmp_path: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    snapshot = migrations_module.create_snapshot(connection, "/root")
    row = models_module.DirectoryAggregate(
        snapshot_id=snapshot.id,
        path=b"/root",
        parent_path=None,
        depth=0,
        apparent_bytes=111,
        disk_bytes=222,
        file_count=3,
        dir_count=4,
        error=None,
        collapsed=True,
        collapse_reason="known_noise",
        collapsed_dirs=9,
        top_child_path=b"/root/largest-child",
        top_child_disk_bytes=444,
    )

    migrations_module.insert_directory_rows(connection, [row])

    persisted = connection.execute(
        """
        SELECT
            d.collapsed,
            d.collapse_reason,
            d.collapsed_dirs,
            d.top_child_disk_bytes,
            p.path AS row_path,
            tp.path AS top_child_path
        FROM directory_sizes d
        JOIN paths p ON p.id = d.path_id
        LEFT JOIN paths tp ON tp.id = d.top_child_id
        """
    ).fetchone()

    assert persisted["collapsed"] == 1
    assert persisted["collapse_reason"] == "known_noise"
    assert persisted["collapsed_dirs"] == 9
    assert persisted["top_child_disk_bytes"] == 444
    assert bytes(persisted["row_path"]) == b"/root"
    assert bytes(persisted["top_child_path"]) == b"/root/largest-child"


class _RecordingCursor:
    def __init__(self, conn: RecordingConnection, sql: str, params) -> None:
        self._row = None
        self.lastrowid = None
        upper = sql.upper()
        path = params[0] if params else None
        assert path is not None
        path_bytes = path if isinstance(path, bytes) else bytes(path)
        if "SELECT" in upper and "FROM PATHS" in upper:
            self._row = (conn._ids[path_bytes],) if path_bytes in conn._ids else None
        elif "INSERT" in upper and "PATHS" in upper:
            conn._next_id += 1
            conn._ids[path_bytes] = conn._next_id
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

    def __exit__(self, _exc_type, exc, _tb) -> bool:
        return False

    def execute(self, sql: str, params=()):
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
