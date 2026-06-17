# pyright: reportAny=false
from __future__ import annotations

import fcntl
import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_cli_collect import import_module, parse_json_output, run_repo_local


def _load_retention_module(repo_root: Path):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec = importlib.util.find_spec("watchdirs.db.retention")
    assert spec is not None, "watchdirs.db.retention module is missing"
    return import_module(repo_root, "watchdirs.db.retention")


def _open_initialized_connection(repo_root: Path, db_path: Path) -> sqlite3.Connection:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    return connection


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_path_id(connection: sqlite3.Connection, path: bytes) -> int:
    row = connection.execute(
        "SELECT id FROM paths WHERE path = ?",
        (sqlite3.Binary(path),),
    ).fetchone()
    if row is not None:
        assert row[0] is not None
        return int(row[0])
    cursor = connection.execute(
        "INSERT INTO paths (path) VALUES (?)",
        (sqlite3.Binary(path),),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _insert_snapshot(
    connection: sqlite3.Connection,
    *,
    root_path: str,
    status: str,
    finished_at: datetime | None,
    breadcrumb_path: bytes | None = None,
    unique_path: bytes | None = None,
) -> int:
    started_at = (
        finished_at - timedelta(minutes=5) if finished_at is not None else datetime(2026, 6, 17, 11, 55, tzinfo=UTC)
    )
    cursor = connection.execute(
        """
        INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error)
        VALUES (?, ?, ?, ?, NULL, NULL)
        """,
        (
            _timestamp(started_at),
            _timestamp(finished_at) if finished_at is not None else None,
            root_path,
            status,
        ),
    )
    assert cursor.lastrowid is not None
    snapshot_id = int(cursor.lastrowid)

    root_bytes = root_path.encode("utf-8")
    shared_bytes = root_bytes + b"/shared"
    root_path_id = _resolve_path_id(connection, root_bytes)
    shared_path_id = _resolve_path_id(connection, shared_bytes)
    breadcrumb_id = _resolve_path_id(connection, breadcrumb_path) if breadcrumb_path is not None else None
    unique_path_id = _resolve_path_id(connection, unique_path) if unique_path is not None else None

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
            error,
            collapsed,
            collapse_reason,
            collapsed_dirs,
            top_child_id,
            top_child_disk_bytes
        ) VALUES (?, ?, NULL, 0, 1000, 1200, 10, 3, NULL, 0, NULL, NULL, ?, ?)
        """,
        (snapshot_id, root_path_id, breadcrumb_id, 512 if breadcrumb_id is not None else None),
    )
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
            error,
            collapsed,
            collapse_reason,
            collapsed_dirs,
            top_child_id,
            top_child_disk_bytes
        ) VALUES (?, ?, ?, 1, 400, 512, 4, 0, NULL, 0, NULL, NULL, NULL, NULL)
        """,
        (snapshot_id, shared_path_id, root_path_id),
    )
    if unique_path_id is not None:
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
                error,
                collapsed,
                collapse_reason,
                collapsed_dirs,
                top_child_id,
                top_child_disk_bytes
            ) VALUES (?, ?, ?, 1, 200, 256, 1, 0, NULL, 0, NULL, NULL, NULL, NULL)
            """,
            (snapshot_id, unique_path_id, root_path_id),
        )

    connection.execute(
        """
        INSERT INTO snapshot_mounts (
            snapshot_id,
            mount_id,
            parent_id,
            major_minor,
            root,
            mount_point,
            filesystem_type,
            mount_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            snapshot_id,
            0,
            "0:0",
            sqlite3.Binary(b"/"),
            sqlite3.Binary(root_bytes),
            "tmpfs",
            root_path,
        ),
    )
    return snapshot_id


def _insert_unfinished_snapshot(
    connection: sqlite3.Connection,
    *,
    root_path: str,
    status: str,
    started_at: datetime,
    unique_path: bytes | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error)
        VALUES (?, NULL, ?, ?, NULL, NULL)
        """,
        (_timestamp(started_at), root_path, status),
    )
    assert cursor.lastrowid is not None
    snapshot_id = int(cursor.lastrowid)
    root_bytes = root_path.encode("utf-8")
    root_path_id = _resolve_path_id(connection, root_bytes)
    unique_path_id = _resolve_path_id(connection, unique_path) if unique_path is not None else None
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
            error,
            collapsed,
            collapse_reason,
            collapsed_dirs,
            top_child_id,
            top_child_disk_bytes
        ) VALUES (?, ?, NULL, 0, 1000, 1200, 10, 3, NULL, 0, NULL, NULL, NULL, NULL)
        """,
        (snapshot_id, root_path_id),
    )
    if unique_path_id is not None:
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
                error,
                collapsed,
                collapse_reason,
                collapsed_dirs,
                top_child_id,
                top_child_disk_bytes
            ) VALUES (?, ?, ?, 1, 100, 128, 1, 0, NULL, 0, NULL, NULL, NULL, NULL)
            """,
            (snapshot_id, unique_path_id, root_path_id),
        )
    return snapshot_id


def _seed_retention_fixture(repo_root: Path, tmp_path: Path) -> tuple[Path, datetime, dict[str, int], bytes]:
    db_path = tmp_path / "watchdirs.sqlite3"
    connection = _open_initialized_connection(repo_root, db_path)
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    breadcrumb_path = b"/beta/breadcrumb-only"

    snapshot_ids = {
        "alpha_recent_complete": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=now - timedelta(days=1),
        ),
        "alpha_recent_partial": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="partial",
            finished_at=now - timedelta(days=7),
        ),
        "alpha_recent_failed": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="failed",
            finished_at=now - timedelta(days=12),
        ),
        "alpha_daily_complete_early": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-daily-early",
        ),
        "alpha_daily_complete_late": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=datetime(2026, 5, 20, 18, 0, tzinfo=UTC),
        ),
        "alpha_daily_failed": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="failed",
            finished_at=datetime(2026, 5, 20, 23, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-daily-failed",
        ),
        "alpha_daily_partial": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="partial",
            finished_at=datetime(2026, 5, 15, 12, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-daily-partial",
        ),
        "alpha_daily_complete_other": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=datetime(2026, 4, 1, 7, 0, tzinfo=UTC),
        ),
        "alpha_monthly_complete_early": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=datetime(2026, 1, 5, 5, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-monthly-early",
        ),
        "alpha_monthly_complete_late": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="complete",
            finished_at=datetime(2026, 1, 28, 5, 0, tzinfo=UTC),
        ),
        "alpha_monthly_failed": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="failed",
            finished_at=datetime(2026, 1, 30, 5, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-monthly-failed",
        ),
        "alpha_monthly_partial": _insert_snapshot(
            connection,
            root_path="/alpha",
            status="partial",
            finished_at=datetime(2025, 12, 10, 5, 0, tzinfo=UTC),
            unique_path=b"/alpha/deleted-monthly-partial",
        ),
        "beta_daily_complete": _insert_snapshot(
            connection,
            root_path="/beta",
            status="complete",
            finished_at=datetime(2026, 5, 20, 1, 0, tzinfo=UTC),
            breadcrumb_path=breadcrumb_path,
        ),
        "beta_monthly_complete": _insert_snapshot(
            connection,
            root_path="/beta",
            status="complete",
            finished_at=datetime(2026, 1, 20, 5, 0, tzinfo=UTC),
        ),
        "beta_recent_failed": _insert_snapshot(
            connection,
            root_path="/beta",
            status="failed",
            finished_at=now - timedelta(days=2),
        ),
    }
    connection.commit()
    connection.close()
    return db_path, now, snapshot_ids, breadcrumb_path


def _fetch_scalar(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def test_retention_policy_requires_positive_windows(repo_root: Path) -> None:
    retention = _load_retention_module(repo_root)

    with pytest.raises(ValueError):
        retention.RetentionPolicy(hourly_days=0)

    with pytest.raises(ValueError):
        retention.RetentionPolicy(daily_days=0)

    with pytest.raises(ValueError):
        retention.RetentionPolicy(incomplete_hours=0)


def test_retention_policy_exposes_explicit_hourly_daily_monthly_tiers(repo_root: Path) -> None:
    retention = _load_retention_module(repo_root)
    policy = retention.RetentionPolicy(hourly_days=7, daily_days=60, incomplete_hours=12)

    assert policy.hourly_days == 7
    assert policy.daily_days == 60
    assert policy.incomplete_hours == 12
    assert policy.tiers == (
        retention.RetentionTier(
            name="hourly",
            mode=retention.RetentionTierMode.COMPLETE_IN_HOURLY_WINDOW,
            window_days=7,
        ),
        retention.RetentionTier(
            name="incomplete",
            mode=retention.RetentionTierMode.INCOMPLETE_IN_DIAGNOSTIC_WINDOW,
            window_days=None,
        ),
        retention.RetentionTier(
            name="daily",
            mode=retention.RetentionTierMode.LATEST_COMPLETE_PER_UTC_DAY,
            window_days=60,
        ),
        retention.RetentionTier(
            name="monthly",
            mode=retention.RetentionTierMode.LATEST_COMPLETE_PER_UTC_MONTH,
            window_days=None,
        ),
    )
    assert policy.tier(retention.RetentionTierMode.LATEST_COMPLETE_PER_UTC_MONTH).name == "monthly"


def test_select_retained_snapshot_ids_keeps_latest_complete_per_root_day_and_month(
    repo_root: Path, tmp_path: Path
) -> None:
    retention = _load_retention_module(repo_root)
    db_path, now, snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    policy = retention.RetentionPolicy()

    retained_ids = set(retention.select_retained_snapshot_ids(connection, policy, now=now))

    assert retained_ids == {
        snapshot_ids["alpha_recent_complete"],
        snapshot_ids["alpha_daily_complete_late"],
        snapshot_ids["alpha_daily_complete_other"],
        snapshot_ids["alpha_monthly_complete_late"],
        snapshot_ids["beta_daily_complete"],
        snapshot_ids["beta_monthly_complete"],
    }
    assert snapshot_ids["alpha_recent_partial"] not in retained_ids
    assert snapshot_ids["alpha_recent_failed"] not in retained_ids
    assert snapshot_ids["alpha_daily_failed"] not in retained_ids
    assert snapshot_ids["alpha_daily_partial"] not in retained_ids
    assert snapshot_ids["alpha_monthly_failed"] not in retained_ids
    assert snapshot_ids["alpha_monthly_partial"] not in retained_ids
    assert snapshot_ids["beta_recent_failed"] not in retained_ids


def test_prune_keeps_latest_complete_per_root_day_month_and_gcs_paths(repo_root: Path, tmp_path: Path) -> None:
    retention = _load_retention_module(repo_root)
    db_path, now, snapshot_ids, breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    policy = retention.RetentionPolicy()

    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        result = retention.prune_snapshots(connection, policy, now=now)
    finally:
        connection.set_trace_callback(None)

    assert result.deleted_snapshot_ids == [
        snapshot_ids["alpha_recent_partial"],
        snapshot_ids["alpha_recent_failed"],
        snapshot_ids["alpha_daily_complete_early"],
        snapshot_ids["alpha_daily_failed"],
        snapshot_ids["alpha_daily_partial"],
        snapshot_ids["alpha_monthly_complete_early"],
        snapshot_ids["alpha_monthly_failed"],
        snapshot_ids["alpha_monthly_partial"],
        snapshot_ids["beta_recent_failed"],
    ]
    assert result.deleted_snapshot_count == 9
    assert result.retained_snapshot_count == 6
    assert result.snapshots_before == 15
    assert result.snapshots_after == 6
    assert result.deleted_path_count == 6

    delete_statements = [
        statement.upper() for statement in statements if statement.lstrip().upper().startswith("DELETE")
    ]
    assert any("DELETE FROM SNAPSHOTS" in statement for statement in delete_statements)
    assert any("DELETE FROM PATHS" in statement for statement in delete_statements)
    assert not any("DELETE FROM DIRECTORY_SIZES" in statement for statement in delete_statements)
    assert not any("DELETE FROM SNAPSHOT_MOUNTS" in statement for statement in delete_statements)

    remaining_snapshot_ids = {int(row["id"]) for row in connection.execute("SELECT id FROM snapshots")}
    assert remaining_snapshot_ids == set(retention.select_retained_snapshot_ids(connection, policy, now=now))
    assert _fetch_scalar(connection, "SELECT COUNT(*) FROM directory_sizes") == 12
    assert _fetch_scalar(connection, "SELECT COUNT(*) FROM snapshot_mounts") == 6
    assert _fetch_scalar(connection, "SELECT COUNT(*) FROM paths") == 5

    remaining_paths = {bytes(row["path"]) for row in connection.execute("SELECT path FROM paths")}
    assert breadcrumb_path in remaining_paths
    assert b"/alpha/deleted-daily-early" not in remaining_paths
    assert b"/alpha/deleted-daily-failed" not in remaining_paths
    assert b"/alpha/deleted-daily-partial" not in remaining_paths
    assert b"/alpha/deleted-monthly-early" not in remaining_paths
    assert b"/alpha/deleted-monthly-failed" not in remaining_paths
    assert b"/alpha/deleted-monthly-partial" not in remaining_paths


def test_prune_deletes_stale_unfinished_snapshots(repo_root: Path, tmp_path: Path) -> None:
    retention = _load_retention_module(repo_root)
    db_path = tmp_path / "watchdirs.sqlite3"
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    connection = _open_initialized_connection(repo_root, db_path)
    recent_unfinished_id = _insert_unfinished_snapshot(
        connection,
        root_path="/alpha",
        status="partial",
        started_at=now - timedelta(hours=23),
    )
    stale_unfinished_id = _insert_unfinished_snapshot(
        connection,
        root_path="/alpha",
        status="partial",
        started_at=now - timedelta(hours=25),
        unique_path=b"/alpha/stale-unfinished",
    )
    connection.commit()
    policy = retention.RetentionPolicy()

    retained_ids = set(retention.select_retained_snapshot_ids(connection, policy, now=now))
    result = retention.prune_snapshots(connection, policy, now=now)

    assert recent_unfinished_id in retained_ids
    assert stale_unfinished_id not in retained_ids
    assert result.deleted_snapshot_ids == [stale_unfinished_id]
    assert _fetch_scalar(connection, "SELECT COUNT(*) FROM snapshots") == 1
    remaining_paths = {bytes(row["path"]) for row in connection.execute("SELECT path FROM paths")}
    assert b"/alpha/stale-unfinished" not in remaining_paths


def test_prune_cli_returns_json_payload(repo_root: Path, tmp_path: Path) -> None:
    _retention = _load_retention_module(repo_root)
    db_path, _now, snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)

    result = run_repo_local(repo_root, "prune", "--db", str(db_path), "--json")

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["ok"] is True
    assert payload["command"] == "prune"
    assert payload["db_path"] == str(db_path)
    assert payload["policy"] == {"hourly_days": 14, "daily_days": 90, "incomplete_hours": 24}
    assert payload["snapshots_before"] == 15
    assert payload["snapshots_after"] == 6
    assert payload["retained_snapshot_count"] == 6
    assert payload["deleted_snapshot_count"] == 9
    assert payload["deleted_path_count"] == 6
    assert payload["deleted_snapshot_ids"] == [
        snapshot_ids["alpha_recent_partial"],
        snapshot_ids["alpha_recent_failed"],
        snapshot_ids["alpha_daily_complete_early"],
        snapshot_ids["alpha_daily_failed"],
        snapshot_ids["alpha_daily_partial"],
        snapshot_ids["alpha_monthly_complete_early"],
        snapshot_ids["alpha_monthly_failed"],
        snapshot_ids["alpha_monthly_partial"],
        snapshot_ids["beta_recent_failed"],
    ]


def test_prune_cli_fails_when_database_is_missing_without_creating_it(repo_root: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "missing" / "watchdirs.sqlite3"

    result = run_repo_local(repo_root, "prune", "--db", str(db_path), "--json")

    assert result.returncode != 0
    payload = parse_json_output(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "database_error"
    assert payload["error"]["db_path"] == str(db_path)
    assert not db_path.exists()
    assert not db_path.with_name(f"{db_path.name}.lock").exists()


def test_prune_cli_fails_fast_when_operation_lock_is_held(repo_root: Path, tmp_path: Path) -> None:
    _retention = _load_retention_module(repo_root)
    db_path, _now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    lock_path = db_path.with_name(f"{db_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_repo_local(repo_root, "prune", "--db", str(db_path), "--json")

    assert result.returncode != 0
    payload = parse_json_output(result)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "operation_locked"
    assert payload["error"]["db_path"] == str(db_path)
    assert payload["error"]["lock_path"] == str(lock_path)

    connection = _open_initialized_connection(repo_root, db_path)
    assert _fetch_scalar(connection, "SELECT COUNT(*) FROM snapshots") == 15


def test_prune_second_run_is_noop(repo_root: Path, tmp_path: Path) -> None:
    retention = _load_retention_module(repo_root)
    db_path, now, _snapshot_ids, _breadcrumb_path = _seed_retention_fixture(repo_root, tmp_path)
    connection = _open_initialized_connection(repo_root, db_path)
    policy = retention.RetentionPolicy()

    first = retention.prune_snapshots(connection, policy, now=now)
    second = retention.prune_snapshots(connection, policy, now=now)

    assert first.deleted_snapshot_count == 9
    assert second.deleted_snapshot_ids == []
    assert second.deleted_snapshot_count == 0
    assert second.deleted_path_count == 0
    assert second.retained_snapshot_count == first.retained_snapshot_count == 6
    assert second.snapshots_before == 6
    assert second.snapshots_after == 6
