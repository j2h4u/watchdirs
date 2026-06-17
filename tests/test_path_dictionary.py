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


class CountingConnection:
    """Wraps a real connection, counting execute() calls so a cache hit can be
    proven to issue ZERO SQL."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner
        self.execute_calls = 0

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        return self._inner.execute(*args, **kwargs)


def test_cache_hit_issues_no_sql(repo_root: Path, tmp_path: Path) -> None:
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)
    counting = CountingConnection(connection)

    cache: dict[bytes, int] = {}
    first_id = migrations_module._resolve_path_id(counting, cache, b"/root/a")
    calls_after_first = counting.execute_calls

    # Second resolution of the SAME path must be served from the cache: no SQL.
    second_id = migrations_module._resolve_path_id(counting, cache, b"/root/a")

    assert second_id == first_id
    assert counting.execute_calls == calls_after_first  # cache hit -> zero new SQL


def test_already_seen_path_resolves_to_existing_id(repo_root: Path, tmp_path: Path) -> None:
    # D-04 / Pitfall-1 regression guard: resolving an already-inserted path with a
    # FRESH cache must SELECT its existing id, never return None / an empty cursor.
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    first_id = migrations_module._resolve_path_id(connection, {}, b"/root/dup")
    assert first_id is not None

    # Fresh cache forces the SELECT-on-miss path against the populated table.
    second_id = migrations_module._resolve_path_id(connection, {}, b"/root/dup")
    assert second_id == first_id
    assert second_id is not None


def test_non_utf8(repo_root: Path, tmp_path: Path) -> None:
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    bad = b"/root/\x80\xff-name"
    path_id = migrations_module._resolve_path_id(connection, {}, bad)

    stored = connection.execute("SELECT path FROM paths WHERE id = ?", (path_id,)).fetchone()[0]
    assert bytes(stored) == bad  # byte-exact lossless roundtrip
