from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import (
    create_snapshot,
    finalize_snapshot,
    initialize_database,
    insert_directory_rows,
)
from watchdirs.db.retention import RetentionPolicy, prune_snapshots
from watchdirs.models import DirectoryAggregate, SnapshotStatus


def _row(snapshot_id: int, value: int) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=b"/root",
        parent_path=None,
        depth=0,
        apparent_bytes=value,
        disk_bytes=value,
        file_count=1,
        dir_count=0,
        error=None,
    )


def _complete(connection: sqlite3.Connection, value: int) -> int:
    snapshot = create_snapshot(connection, Path("/root"))
    insert_directory_rows(connection, [_row(snapshot.id, value)])
    finalize_snapshot(connection, snapshot.id, status=SnapshotStatus.COMPLETE)
    return snapshot.id


def _set_finished_at(connection: sqlite3.Connection, snapshot_id: int, value: datetime) -> None:
    connection.execute(
        "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
        (value.isoformat().replace("+00:00", "Z"), value.isoformat().replace("+00:00", "Z"), snapshot_id),
    )


def _interval_state_at(connection: sqlite3.Connection, snapshot_id: int) -> list[tuple[object, ...]]:
    return [
        tuple(row)
        for row in cast(
            list[sqlite3.Row],
            connection.execute(
                "SELECT path_id, apparent_bytes, disk_bytes, file_count, dir_count "
                "FROM directory_size_intervals WHERE root_path = '/root' "
                "AND valid_from_snapshot_id <= ? "
                "AND (valid_to_snapshot_id IS NULL OR ? < valid_to_snapshot_id) "
                "ORDER BY path_id",
                (snapshot_id, snapshot_id),
            ).fetchall(),
        )
    ]


def test_v7_schema_has_unbound_interval_markers(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)

    foreign_keys = cast(
        list[sqlite3.Row], connection.execute("PRAGMA foreign_key_list('directory_size_intervals')").fetchall()
    )
    assert not any(row[3] in {"valid_from_snapshot_id", "valid_to_snapshot_id"} for row in foreign_keys)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 7


def test_path_gc_lookups_use_independent_partial_indexes(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)

    cases = (
        ("directory_size_intervals", "parent_id", "directory_size_intervals_parent_idx"),
        ("directory_size_intervals", "top_child_id", "directory_size_intervals_top_child_idx"),
        ("directory_size_diagnostics", "parent_id", "directory_size_diagnostics_parent_idx"),
        ("directory_size_diagnostics", "top_child_id", "directory_size_diagnostics_top_child_idx"),
    )
    for table, column, index_name in cases:
        plan = cast(
            list[sqlite3.Row],
            connection.execute(f"EXPLAIN QUERY PLAN SELECT id FROM {table} WHERE {column} = ?", (1,)).fetchall(),
        )
        assert index_name in " ".join(cast(str, row[3]) for row in plan)


def test_complete_rows_become_half_open_intervals(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)

    first = _complete(connection, 10)
    second = _complete(connection, 20)

    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            "SELECT valid_from_snapshot_id, valid_to_snapshot_id, disk_bytes "
            "FROM directory_size_intervals ORDER BY valid_from_snapshot_id"
        ).fetchall(),
    )
    assert [tuple(row) for row in rows] == [(first, second, 10), (second, None, 20)]
    assert connection.execute("SELECT COUNT(*) FROM directory_size_diagnostics").fetchone()[0] == 0


def test_pruning_boundary_snapshot_preserves_later_interval_state(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    now = datetime(2026, 6, 10, tzinfo=UTC)

    may = _complete(connection, 1)
    boundary = _complete(connection, 2)
    retained = _complete(connection, 2)
    _set_finished_at(connection, may, now - timedelta(days=40))
    _set_finished_at(connection, boundary, now - timedelta(days=9))
    _set_finished_at(connection, retained, now - timedelta(hours=1))
    connection.commit()

    result = prune_snapshots(connection, RetentionPolicy(hourly_days=1, daily_days=1), now=now)

    assert boundary in result.deleted_snapshot_ids
    assert connection.execute("SELECT 1 FROM snapshots WHERE id = ?", (boundary,)).fetchone() is None
    interval_starts = [
        row[0]
        for row in cast(
            list[sqlite3.Row],
            connection.execute(
                "SELECT valid_from_snapshot_id FROM directory_size_intervals ORDER BY valid_from_snapshot_id"
            ).fetchall(),
        )
    ]
    assert boundary not in interval_starts
    row = cast(
        sqlite3.Row | None,
        connection.execute(
            "SELECT disk_bytes FROM directory_size_intervals "
            "WHERE root_path = '/root' AND valid_from_snapshot_id <= ? "
            "AND (valid_to_snapshot_id IS NULL OR ? < valid_to_snapshot_id)",
            (retained, retained),
        ).fetchone(),
    )
    assert row is not None
    assert row[0] == 2


def test_boundary_normalization_preserves_every_retained_interval_state(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    now = datetime(2026, 6, 10, tzinfo=UTC)

    oldest = _complete(connection, 1)
    pruned_change = _complete(connection, 2)
    latest = _complete(connection, 3)
    _set_finished_at(connection, oldest, now - timedelta(days=40))
    _set_finished_at(connection, pruned_change, now - timedelta(days=9))
    _set_finished_at(connection, latest, now - timedelta(hours=1))
    connection.commit()

    retained_ids = (oldest, latest)
    before = {snapshot_id: _interval_state_at(connection, snapshot_id) for snapshot_id in retained_ids}
    result = prune_snapshots(connection, RetentionPolicy(hourly_days=1, daily_days=1), now=now)
    after = {snapshot_id: _interval_state_at(connection, snapshot_id) for snapshot_id in retained_ids}

    assert pruned_change in result.deleted_snapshot_ids
    assert after == before
    bounds = cast(
        list[sqlite3.Row],
        connection.execute(
            "SELECT valid_from_snapshot_id, valid_to_snapshot_id, disk_bytes "
            "FROM directory_size_intervals ORDER BY valid_from_snapshot_id"
        ).fetchall(),
    )
    assert [tuple(row) for row in bounds] == [(oldest, latest, 1), (latest, None, 3)]


def test_non_complete_rows_remain_full_row_diagnostics(repo_root: Path, tmp_path: Path) -> None:
    del repo_root
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    snapshot = create_snapshot(connection, Path("/root"))
    insert_directory_rows(connection, [_row(snapshot.id, 7)])
    finalize_snapshot(connection, snapshot.id, status=SnapshotStatus.PARTIAL)

    diagnostic = cast(
        sqlite3.Row | None,
        connection.execute("SELECT snapshot_id, disk_bytes FROM directory_size_diagnostics").fetchone(),
    )
    assert diagnostic is not None
    assert tuple(diagnostic) == (snapshot.id, 7)
