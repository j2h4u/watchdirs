from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from watchdirs.db import connection as connection_module


class _FakeConnection:
    def __init__(self, *, fail_on_execute: bool = False) -> None:
        self.closed = False
        self.fail_on_execute = fail_on_execute
        self.row_factory = None

    def execute(self, _sql: str):
        if self.fail_on_execute:
            raise sqlite3.OperationalError("setup failed")
        return self

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    "factory",
    [
        connection_module.open_connection,
        connection_module.open_existing_connection,
        connection_module.open_readonly_connection,
    ],
)
def test_connection_factory_closes_when_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    factory: Callable[[Path], sqlite3.Connection],
) -> None:
    db_path = tmp_path / "watchdirs.sqlite3"
    if factory is not connection_module.open_connection:
        db_path.touch()
    fake = _FakeConnection(fail_on_execute=True)
    monkeypatch.setattr(connection_module.sqlite3, "connect", lambda *args, **kwargs: fake)

    with pytest.raises(sqlite3.OperationalError, match="setup failed"):
        factory(db_path)

    assert fake.closed


def test_owned_connection_closes_on_scope_exit(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:")

    with connection_module.owned_connection(lambda _path: connection, tmp_path / "db.sqlite3") as owned:
        assert owned is connection
        owned.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_owned_connection_closes_when_scope_body_fails(tmp_path: Path) -> None:
    connection = sqlite3.connect(":memory:")

    with (
        pytest.raises(RuntimeError, match="body failed"),
        connection_module.owned_connection(lambda _path: connection, tmp_path / "db.sqlite3"),
    ):
        raise RuntimeError("body failed")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
