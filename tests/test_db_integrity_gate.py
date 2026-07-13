from __future__ import annotations

import sqlite3
from pathlib import Path

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import SCHEMA_VERSION, initialize_database


def _assert_sqlite_invariants(connection: sqlite3.Connection) -> None:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_initialize_database_gates_clean_v7_schema(tmp_path: Path) -> None:
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    try:
        _assert_sqlite_invariants(connection)
    finally:
        connection.close()
