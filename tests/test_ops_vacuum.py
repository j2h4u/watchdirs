from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from test_cli_collect import import_module, parse_json_output, run_repo_local
from test_ops_retention import (
    _load_retention_module,
    _open_initialized_connection,
    _seed_retention_fixture,
)


class _CheckpointCursor:
    def __init__(self, row: tuple[int, int, int]) -> None:
        self._row = row

    def fetchone(self) -> tuple[int, int, int]:
        return self._row


class _RecordingConnection:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        wal_checkpoint_row: tuple[int, int, int] | None = None,
    ) -> None:
        self._connection = connection
        self.statements: list[str] = []
        self._wal_checkpoint_row = wal_checkpoint_row

    def execute(self, sql: str, parameters: object = ()) -> object:
        self.statements.append(" ".join(sql.strip().split()))
        normalized = " ".join(sql.strip().split()).upper()
        if normalized == "PRAGMA WAL_CHECKPOINT(TRUNCATE)" and self._wal_checkpoint_row is not None:
            return _CheckpointCursor(self._wal_checkpoint_row)
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)


def test_vacuum_database_records_before_after_counters(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    retention = _load_retention_module(repo_root)
    db_path, now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    retention.prune_snapshots(connection, retention.RetentionPolicy(), now=now)

    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count_before = int(connection.execute("PRAGMA page_count").fetchone()[0])
    freelist_count_before = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    monkeypatch.setattr(
        retention.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_frsize=4096, f_bavail=250000),
    )

    result = retention.vacuum_database(connection, db_path)

    assert result.db_bytes_before == page_count_before * page_size
    assert result.page_count_before == page_count_before
    assert result.freelist_count_before == freelist_count_before
    assert result.db_bytes_after == result.page_count_after * page_size
    assert result.page_count_after <= result.page_count_before
    assert result.freelist_count_after <= result.freelist_count_before
    assert result.available_free_bytes_before == 4096 * 250000
    assert result.estimated_vacuum_required_free_bytes == 3 * result.db_bytes_before
    assert isinstance(result.wal_checkpoint_busy, int)
    assert isinstance(result.wal_checkpoint_log_pages, int)
    assert isinstance(result.wal_checkpoint_checkpointed_pages, int)
    assert result.free_space_warning is None


def test_vacuum_cli_json_reports_maintenance_result(repo_root: Path, tmp_path: Path) -> None:
    retention = _load_retention_module(repo_root)
    db_path, now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    retention.prune_snapshots(connection, retention.RetentionPolicy(), now=now)
    connection.close()

    result = run_repo_local(repo_root, "vacuum", "--db", str(db_path), "--json")

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["ok"] is True
    assert payload["command"] == "vacuum"
    assert payload["db_path"] == str(db_path)
    for key in (
        "db_bytes_before",
        "db_bytes_after",
        "page_count_before",
        "page_count_after",
        "freelist_count_before",
        "freelist_count_after",
        "available_free_bytes_before",
        "estimated_vacuum_required_free_bytes",
        "free_space_warning",
        "wal_checkpoint_busy",
        "wal_checkpoint_log_pages",
        "wal_checkpoint_checkpointed_pages",
        "wal_checkpoint_warning",
    ):
        assert key in payload


def test_vacuum_cli_fails_when_database_is_missing_without_creating_it(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path = tmp_path / "missing" / "watchdirs.sqlite3"

    result = run_repo_local(repo_root, "vacuum", "--db", str(db_path), "--json")

    assert result.returncode != 0
    payload = parse_json_output(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "database_error"
    assert payload["error"]["db_path"] == str(db_path)
    assert not db_path.exists()
    assert not db_path.with_name(f"{db_path.name}.lock").exists()


def test_vacuum_cli_fails_fast_when_operation_lock_is_held(repo_root: Path, tmp_path: Path) -> None:
    db_path, _now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    lock_path = db_path.with_name(f"{db_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_file:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_repo_local(repo_root, "vacuum", "--db", str(db_path), "--json")

    assert result.returncode != 0
    payload = parse_json_output(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "operation_locked"
    assert payload["error"]["db_path"] == str(db_path)
    assert payload["error"]["lock_path"] == str(lock_path)


def test_prune_does_not_invoke_vacuum(repo_root: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    db_path, _now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    wrapped = _RecordingConnection(connection)

    monkeypatch.setattr(cli, "open_existing_connection", lambda _db_path: wrapped)
    monkeypatch.setattr(cli, "initialize_database", lambda _connection: None)
    monkeypatch.setattr(cli, "acquire_operation_lock", lambda _lock_path: contextlib.nullcontext())

    exit_code = cli.run_prune(
        argparse.Namespace(
            db=str(db_path),
            json=True,
            hourly_days=14,
            daily_days=90,
        )
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert all(statement.upper() != "VACUUM" for statement in wrapped.statements)
    assert all(statement.upper() != "PRAGMA WAL_CHECKPOINT(TRUNCATE)" for statement in wrapped.statements)


def test_vacuum_database_warns_on_low_free_space_and_busy_checkpoint(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    retention = _load_retention_module(repo_root)
    db_path, _now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    wrapped = _RecordingConnection(connection, wal_checkpoint_row=(1, 12, 3))
    monkeypatch.setattr(
        retention.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_frsize=1, f_bavail=1),
    )

    result = retention.vacuum_database(wrapped, db_path)

    assert result.available_free_bytes_before == 1
    assert result.free_space_warning
    assert result.wal_checkpoint_busy == 1
    assert result.wal_checkpoint_log_pages == 12
    assert result.wal_checkpoint_checkpointed_pages == 3
    assert result.wal_checkpoint_warning
