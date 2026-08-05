from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import create_snapshot, finalize_snapshot, initialize_database, insert_directory_rows
from watchdirs.models import DirectoryAggregate, SnapshotStatus
from watchdirs.reporting.errors import ReportError
from watchdirs.reporting.queries import query_path_trends
from watchdirs.reporting.trends import GrowthShape


@dataclass(frozen=True, slots=True)
class _RowSpec:
    path: bytes
    parent_path: bytes | None
    depth: int
    disk_bytes: int
    apparent_bytes: int | None = None


def _open_db(tmp_path: Path) -> sqlite3.Connection:
    connection = open_connection(tmp_path / "watchdirs.sqlite3")
    initialize_database(connection)
    return connection


def _seed_snapshot(
    connection: sqlite3.Connection,
    *,
    root_path: Path,
    status: SnapshotStatus,
    finished_at: str,
    rows: tuple[_RowSpec, ...],
) -> int:
    snapshot = create_snapshot(connection, root_path)
    directory_rows = tuple(
        DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=row.path,
            parent_path=row.parent_path,
            depth=row.depth,
            apparent_bytes=row.apparent_bytes if row.apparent_bytes is not None else row.disk_bytes,
            disk_bytes=row.disk_bytes,
            file_count=0,
            dir_count=0,
            error=None,
        )
        for row in rows
    )
    insert_directory_rows(connection, directory_rows, commit=False)
    finalize_snapshot(connection, snapshot.id, status=status, commit=False)
    connection.execute(
        "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
        (finished_at, finished_at, snapshot.id),
    )
    connection.commit()
    return snapshot.id


def test_query_path_trends_uses_interval_backed_complete_snapshots(tmp_path: Path) -> None:
    connection = _open_db(tmp_path)
    for index, size in enumerate((100, 150, 210)):
        _seed_snapshot(
            connection,
            root_path=Path("/srv"),
            status=SnapshotStatus.COMPLETE,
            finished_at=f"2026-08-0{index + 1}T00:00:00Z",
            rows=(
                _RowSpec(path=b"/srv", parent_path=None, depth=0, disk_bytes=size),
                _RowSpec(path=b"/srv/cache", parent_path=b"/srv", depth=1, disk_bytes=size),
            ),
        )

    trends = query_path_trends(connection, since="7d", limit=10)
    by_path = {trend.path: trend for trend in trends}

    cache = by_path[b"/srv/cache"]
    assert cache.root_path == Path("/srv")
    assert cache.parent_path == b"/srv"
    assert cache.depth == 1
    assert cache.snapshot_ids == (1, 2, 3)
    assert cache.snapshot_statuses == ("complete",)
    assert cache.metrics.sample_count == 3
    assert cache.metrics.missing_sample_count == 0
    assert cache.metrics.net_disk_bytes_delta == 110
    assert cache.metrics.shape is GrowthShape.STEADY_GROWTH


def test_query_path_trends_counts_missing_path_samples_without_inventing_zeroes(tmp_path: Path) -> None:
    connection = _open_db(tmp_path)
    _seed_snapshot(
        connection,
        root_path=Path("/srv"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-01T00:00:00Z",
        rows=(
            _RowSpec(path=b"/srv", parent_path=None, depth=0, disk_bytes=100),
            _RowSpec(path=b"/srv/cache", parent_path=b"/srv", depth=1, disk_bytes=10),
        ),
    )
    _seed_snapshot(
        connection,
        root_path=Path("/srv"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-02T00:00:00Z",
        rows=(_RowSpec(path=b"/srv", parent_path=None, depth=0, disk_bytes=110),),
    )
    _seed_snapshot(
        connection,
        root_path=Path("/srv"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-03T00:00:00Z",
        rows=(
            _RowSpec(path=b"/srv", parent_path=None, depth=0, disk_bytes=130),
            _RowSpec(path=b"/srv/cache", parent_path=b"/srv", depth=1, disk_bytes=30),
        ),
    )

    trends = query_path_trends(connection, since="7d", limit=10)
    cache = {trend.path: trend for trend in trends}[b"/srv/cache"]

    assert cache.metrics.sample_count == 2
    assert cache.metrics.missing_sample_count == 1
    assert cache.metrics.start_disk_bytes == 10
    assert cache.metrics.end_disk_bytes == 30
    assert cache.metrics.shape is GrowthShape.UNKNOWN_INSUFFICIENT_SAMPLES


def test_query_path_trends_includes_partial_diagnostic_snapshots(tmp_path: Path) -> None:
    connection = _open_db(tmp_path)
    for index, status in enumerate((SnapshotStatus.COMPLETE, SnapshotStatus.PARTIAL, SnapshotStatus.COMPLETE)):
        _seed_snapshot(
            connection,
            root_path=Path("/var"),
            status=status,
            finished_at=f"2026-08-0{index + 1}T00:00:00Z",
            rows=(
                _RowSpec(path=b"/var", parent_path=None, depth=0, disk_bytes=100 + (index * 50)),
                _RowSpec(path=b"/var/log", parent_path=b"/var", depth=1, disk_bytes=100 + (index * 50)),
            ),
        )

    trends = query_path_trends(connection, since="7d", limit=10)
    log_trend = {trend.path: trend for trend in trends}[b"/var/log"]

    assert log_trend.snapshot_statuses == ("complete", "partial")
    assert log_trend.metrics.sample_count == 3
    assert log_trend.metrics.shape is GrowthShape.STEADY_GROWTH


def test_query_path_trends_uses_window_baseline_and_limit_ordering(tmp_path: Path) -> None:
    connection = _open_db(tmp_path)
    _seed_snapshot(
        connection,
        root_path=Path("/opt"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-01T00:00:00Z",
        rows=(
            _RowSpec(path=b"/opt", parent_path=None, depth=0, disk_bytes=0),
            _RowSpec(path=b"/opt/small", parent_path=b"/opt", depth=1, disk_bytes=10),
            _RowSpec(path=b"/opt/large", parent_path=b"/opt", depth=1, disk_bytes=10),
        ),
    )
    _seed_snapshot(
        connection,
        root_path=Path("/opt"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-04T00:00:00Z",
        rows=(
            _RowSpec(path=b"/opt", parent_path=None, depth=0, disk_bytes=0),
            _RowSpec(path=b"/opt/small", parent_path=b"/opt", depth=1, disk_bytes=20),
            _RowSpec(path=b"/opt/large", parent_path=b"/opt", depth=1, disk_bytes=100),
        ),
    )
    _seed_snapshot(
        connection,
        root_path=Path("/opt"),
        status=SnapshotStatus.COMPLETE,
        finished_at="2026-08-05T00:00:00Z",
        rows=(
            _RowSpec(path=b"/opt", parent_path=None, depth=0, disk_bytes=0),
            _RowSpec(path=b"/opt/small", parent_path=b"/opt", depth=1, disk_bytes=30),
            _RowSpec(path=b"/opt/large", parent_path=b"/opt", depth=1, disk_bytes=200),
        ),
    )

    trends = query_path_trends(connection, since="1d", limit=1)

    assert len(trends) == 1
    assert trends[0].path == b"/opt/large"
    assert trends[0].snapshot_ids == (2, 3)
    assert trends[0].metrics.net_disk_bytes_delta == 100


def test_query_path_trends_rejects_invalid_limit_and_missing_snapshots(tmp_path: Path) -> None:
    connection = _open_db(tmp_path)

    with pytest.raises(ReportError, match="limit"):
        query_path_trends(connection, since="24h", limit=0)
    with pytest.raises(ReportError, match="no complete or partial snapshots"):
        query_path_trends(connection, since="24h", limit=1)
