from __future__ import annotations

import fcntl
import sqlite3
from pathlib import Path

from test_cli_collect import (
    create_sample_tree,
    import_module,
    parse_json_output,
    run_repo_local,
)


def _snapshot_count(db_path: Path) -> int:
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])


def test_collect_lock_conflict_fails_fast_without_snapshot_write(
    repo_root: Path, write_config, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    first = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )
    assert first.returncode == 0, first.stderr
    assert _snapshot_count(db_path) == 1

    lock_path = db_path.with_name(f"{db_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = run_repo_local(
            repo_root,
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        )

    assert result.returncode != 0
    payload = parse_json_output(result)
    assert payload["ok"] is False
    error = payload["error"]
    assert error["code"] == "operation_locked"
    assert error["db_path"] == str(db_path)
    assert error["lock_path"] == str(lock_path)
    assert _snapshot_count(db_path) == 1


def test_operation_lock_path_and_release(repo_root: Path, tmp_path: Path) -> None:
    ops_lock = import_module(repo_root, "watchdirs.ops_lock")
    db_path = tmp_path / "watchdirs.sqlite3"
    expected_lock_path = tmp_path / "watchdirs.sqlite3.lock"

    lock_path = ops_lock.operation_lock_path_for_db(db_path)

    assert lock_path == expected_lock_path

    with ops_lock.acquire_operation_lock(lock_path):
        with expected_lock_path.open("a+b") as competing_handle:
            try:
                fcntl.flock(competing_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError("expected the operation lock to hold the lock file")

    with expected_lock_path.open("a+b") as competing_handle:
        fcntl.flock(competing_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_operation_lock_path_canonicalizes_database_symlink(
    repo_root: Path, tmp_path: Path
) -> None:
    ops_lock = import_module(repo_root, "watchdirs.ops_lock")
    real_db_path = tmp_path / "real" / "watchdirs.sqlite3"
    real_db_path.parent.mkdir()
    real_db_path.touch()
    alias_db_path = tmp_path / "alias.sqlite3"
    alias_db_path.symlink_to(real_db_path)

    real_lock_path = ops_lock.operation_lock_path_for_db(real_db_path)
    alias_lock_path = ops_lock.operation_lock_path_for_db(alias_db_path)

    assert alias_lock_path == real_lock_path
    with ops_lock.acquire_operation_lock(real_lock_path):
        try:
            ops_lock.acquire_operation_lock(alias_lock_path)
        except ops_lock.OperationLocked:
            pass
        else:
            raise AssertionError("expected symlink alias to contend on the same lock")


def test_collect_succeeds_after_lock_holder_exits(
    repo_root: Path, write_config, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"
    lock_path = db_path.with_name(f"{db_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        blocked = run_repo_local(
            repo_root,
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        )

    assert blocked.returncode != 0

    result = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["ok"] is True
    assert payload["snapshots"][0]["status"] == "complete"
    assert _snapshot_count(db_path) == 1
