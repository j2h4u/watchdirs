# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _fresh_db(repo_root: Path, tmp_path: Path) -> sqlite3.Connection:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    return connection


def _aggregate(models_module, *, snapshot_id, path, parent_path, depth, value):
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=parent_path,
        depth=depth,
        apparent_bytes=value,
        disk_bytes=value,
        file_count=1,
        dir_count=0,
        error=None,
    )


def test_paths_inserted_once_across_shared_snapshots(repo_root: Path, tmp_path: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    snap_a = migrations_module.create_snapshot(connection, "/root")
    snap_b = migrations_module.create_snapshot(connection, "/root")

    shared = [(b"/root", None), (b"/root/a", b"/root"), (b"/root/b", b"/root")]
    for snap in (snap_a, snap_b):
        rows = [
            _aggregate(
                models_module,
                snapshot_id=snap.id,
                path=path,
                parent_path=parent,
                depth=0 if parent is None else 1,
                value=10,
            )
            for path, parent in shared
        ]
        migrations_module.insert_directory_rows(connection, rows)

    # Each distinct path stored exactly once even though both snapshots share them.
    distinct_in_dict = connection.execute("SELECT COUNT(*) FROM paths").fetchone()[0]
    assert distinct_in_dict == len(shared)

    # Diagnostics retain rows until each complete snapshot is promoted.
    total_rows = connection.execute("SELECT COUNT(*) FROM directory_size_diagnostics").fetchone()[0]
    assert total_rows == 2 * len(shared)


def test_path_id_and_parent_id_resolve_back(repo_root: Path, tmp_path: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    snap = migrations_module.create_snapshot(connection, "/root")
    rows = [
        _aggregate(models_module, snapshot_id=snap.id, path=b"/root", parent_path=None, depth=0, value=5),
        _aggregate(models_module, snapshot_id=snap.id, path=b"/root/child", parent_path=b"/root", depth=1, value=7),
    ]
    migrations_module.insert_directory_rows(connection, rows)

    resolved = connection.execute(
        """
        SELECT p.path AS path, pp.path AS parent_path
        FROM directory_size_diagnostics d
        JOIN paths p ON p.id = d.path_id
        LEFT JOIN paths pp ON pp.id = d.parent_id
        ORDER BY d.depth
        """
    ).fetchall()

    root_row, child_row = resolved
    assert bytes(root_row["path"]) == b"/root"
    assert root_row["parent_path"] is None  # parent_path None -> parent_id None
    assert bytes(child_row["path"]) == b"/root/child"
    assert bytes(child_row["parent_path"]) == b"/root"


class RecordingConnection:
    def __init__(self) -> None:
        self.batches: list[tuple[str, list[tuple[object, ...]]]] = []
        self.commit_calls = 0
        self._next_id = 0
        self._ids: dict[bytes, int] = {}

    def execute(self, sql: str, params=()):
        # Serve _resolve_path_id's SELECT/INSERT without a real DB so the batching
        # assertion stays a pure unit test.
        return _RecordingCursor(self, sql, params)

    def executemany(self, sql: str, rows) -> None:
        self.batches.append((sql, list(rows)))

    def commit(self) -> None:
        self.commit_calls += 1


class _RecordingCursor:
    def __init__(self, conn: RecordingConnection, sql: str, params) -> None:
        self._conn = conn
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


def test_insert_directory_rows_uses_executemany_batches(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    rows = [
        _aggregate(
            models_module,
            snapshot_id=1,
            path=f"/root/dir-{index}".encode(),
            parent_path=b"/root",
            depth=1,
            value=index,
        )
        for index in range(10005)
    ]
    connection = RecordingConnection()

    migrations_module.insert_directory_rows(connection, rows)

    assert [len(batch) for _, batch in connection.batches] == [10000, 5]
    assert all("INSERT INTO directory_size_diagnostics" in sql for sql, _ in connection.batches)
    assert connection.commit_calls == 1
