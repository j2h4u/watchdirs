from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

tests_path = str(Path(__file__).resolve().parent)
if tests_path not in sys.path:
    sys.path.insert(0, tests_path)

from test_db_schema import (  # noqa: E402 - reuse existing test schema helpers after adding tests/ to sys.path.
    _create_v3_database,
    _fresh_db,
    _initialize_database,
    _seed_v3_row,
)


def _assert_sqlite_invariants(connection: sqlite3.Connection) -> None:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_initialize_database_gates_fresh_schema(repo_root: Path, tmp_path: Path) -> None:
    connection = _fresh_db(repo_root, tmp_path, filename="watchdirs-fresh.sqlite3")
    try:
        _assert_sqlite_invariants(connection)
    finally:
        connection.close()


def test_initialize_database_gates_migrated_v3_schema(repo_root: Path, tmp_path: Path) -> None:
    connection = _create_v3_database(repo_root, tmp_path, filename="watchdirs-v3.sqlite3")
    _seed_v3_row(connection)
    _initialize_database(repo_root, connection)
    try:
        _assert_sqlite_invariants(connection)
    finally:
        connection.close()
