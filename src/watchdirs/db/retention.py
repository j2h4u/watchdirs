from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import cast

from watchdirs.models import SnapshotStatus, snapshot_status_from_storage

PRUNE_SNAPSHOT_DELETE_BATCH_SIZE = 1


class RetentionTierMode(StrEnum):
    COMPLETE_IN_HOURLY_WINDOW = "complete_in_hourly_window"
    INCOMPLETE_IN_DIAGNOSTIC_WINDOW = "incomplete_in_diagnostic_window"
    LATEST_COMPLETE_PER_UTC_DAY = "latest_complete_per_utc_day"
    LATEST_COMPLETE_PER_UTC_MONTH = "latest_complete_per_utc_month"


@dataclass(frozen=True, slots=True)
class RetentionTier:
    name: str
    mode: RetentionTierMode
    window_days: int | None

    def __post_init__(self) -> None:
        if self.window_days is not None and self.window_days <= 0:
            raise ValueError(f"{self.name} retention window must be a positive integer")


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    hourly_days: int = 3
    daily_days: int = 90
    incomplete_hours: int = 24

    def __post_init__(self) -> None:
        if self.hourly_days <= 0:
            raise ValueError("hourly_days must be a positive integer")
        if self.daily_days <= 0:
            raise ValueError("daily_days must be a positive integer")
        if self.incomplete_hours <= 0:
            raise ValueError("incomplete_hours must be a positive integer")
        if self.daily_days < self.hourly_days:
            raise ValueError("daily_days must be greater than or equal to hourly_days")

    @property
    def tiers(self) -> tuple[RetentionTier, RetentionTier, RetentionTier, RetentionTier]:
        return (
            RetentionTier(
                name="hourly",
                mode=RetentionTierMode.COMPLETE_IN_HOURLY_WINDOW,
                window_days=self.hourly_days,
            ),
            RetentionTier(
                name="incomplete",
                mode=RetentionTierMode.INCOMPLETE_IN_DIAGNOSTIC_WINDOW,
                window_days=None,
            ),
            RetentionTier(
                name="daily",
                mode=RetentionTierMode.LATEST_COMPLETE_PER_UTC_DAY,
                window_days=self.daily_days,
            ),
            RetentionTier(
                name="monthly",
                mode=RetentionTierMode.LATEST_COMPLETE_PER_UTC_MONTH,
                window_days=None,
            ),
        )

    def tier(self, mode: RetentionTierMode) -> RetentionTier:
        for tier in self.tiers:
            if tier.mode == mode:
                return tier
        raise ValueError(f"retention tier missing: {mode}")


@dataclass(frozen=True, slots=True)
class PruneResult:
    deleted_snapshot_ids: list[int]
    deleted_snapshot_count: int
    retained_snapshot_count: int
    deleted_path_count: int
    snapshots_before: int
    snapshots_after: int


@dataclass(frozen=True, slots=True)
class VacuumResult:
    db_bytes_before: int
    db_bytes_after: int
    page_count_before: int
    page_count_after: int
    freelist_count_before: int
    freelist_count_after: int
    available_free_bytes_before: int
    estimated_vacuum_required_free_bytes: int
    free_space_warning: str | None
    wal_checkpoint_busy: int
    wal_checkpoint_log_pages: int
    wal_checkpoint_checkpointed_pages: int
    wal_checkpoint_warning: str | None


@dataclass(slots=True)
class _RetentionSelectionState:
    keep_ids: set[int]
    daily_representatives: dict[tuple[str, date], tuple[datetime, int]]
    monthly_representatives: dict[tuple[str, int, int], tuple[datetime, int]]


@dataclass(frozen=True, slots=True)
class _VacuumMetrics:
    db_bytes_before: int
    db_bytes_after: int
    page_count_before: int
    page_count_after: int
    freelist_count_before: int
    freelist_count_after: int
    available_free_bytes_before: int
    estimated_vacuum_required_free_bytes: int
    free_space_warning: str | None
    wal_checkpoint_busy: int
    wal_checkpoint_log_pages: int
    wal_checkpoint_checkpointed_pages: int
    wal_checkpoint_warning: str | None


def select_retained_snapshot_ids(
    connection: sqlite3.Connection,
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
) -> tuple[int, ...]:
    effective_now = _normalize_now(now)
    hourly_tier = policy.tier(RetentionTierMode.COMPLETE_IN_HOURLY_WINDOW)
    daily_tier = policy.tier(RetentionTierMode.LATEST_COMPLETE_PER_UTC_DAY)
    hourly_cutoff = effective_now - timedelta(days=_required_window_days(hourly_tier))
    daily_cutoff = effective_now - timedelta(days=_required_window_days(daily_tier))
    incomplete_cutoff = effective_now - timedelta(hours=policy.incomplete_hours)
    state = _RetentionSelectionState(keep_ids=set(), daily_representatives={}, monthly_representatives={})

    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
        SELECT id, root_path, status, started_at, finished_at
        FROM snapshots
        ORDER BY id
        """
        ).fetchall(),
    )
    for row in rows:
        _record_retained_snapshot_id(
            state,
            row,
            hourly_cutoff=hourly_cutoff,
            daily_cutoff=daily_cutoff,
            incomplete_cutoff=incomplete_cutoff,
        )

    state.keep_ids.update(snapshot_id for _finished_at, snapshot_id in state.daily_representatives.values())
    state.keep_ids.update(snapshot_id for _finished_at, snapshot_id in state.monthly_representatives.values())
    return tuple(sorted(state.keep_ids))


def prune_snapshots(
    connection: sqlite3.Connection,
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> PruneResult:
    retained_snapshot_ids = select_retained_snapshot_ids(connection, policy, now=now)
    retained_snapshot_id_set = set(retained_snapshot_ids)
    snapshot_ids = [
        int(cast(int | str, row["id"]))
        for row in cast(list[sqlite3.Row], connection.execute("SELECT id FROM snapshots ORDER BY id").fetchall())
    ]
    deleted_snapshot_ids = [snapshot_id for snapshot_id in snapshot_ids if snapshot_id not in retained_snapshot_id_set]
    snapshots_before = len(snapshot_ids)

    if commit:
        deleted_path_count = _prune_with_committed_batches(connection, deleted_snapshot_ids)
        return PruneResult(
            deleted_snapshot_ids=deleted_snapshot_ids,
            deleted_snapshot_count=len(deleted_snapshot_ids),
            retained_snapshot_count=len(retained_snapshot_ids),
            deleted_path_count=deleted_path_count,
            snapshots_before=snapshots_before,
            snapshots_after=snapshots_before - len(deleted_snapshot_ids),
        )

    connection.execute("BEGIN")
    try:
        if deleted_snapshot_ids:
            _delete_snapshot_batch(connection, deleted_snapshot_ids)
        deleted_path_count = _delete_orphan_paths(connection)
    except Exception:
        connection.rollback()
        raise
    else:
        if commit:
            connection.commit()

    return PruneResult(
        deleted_snapshot_ids=deleted_snapshot_ids,
        deleted_snapshot_count=len(deleted_snapshot_ids),
        retained_snapshot_count=len(retained_snapshot_ids),
        deleted_path_count=deleted_path_count,
        snapshots_before=snapshots_before,
        snapshots_after=snapshots_before - len(deleted_snapshot_ids),
    )


def _prune_with_committed_batches(connection: sqlite3.Connection, deleted_snapshot_ids: list[int]) -> int:
    for start in range(0, len(deleted_snapshot_ids), PRUNE_SNAPSHOT_DELETE_BATCH_SIZE):
        batch = deleted_snapshot_ids[start : start + PRUNE_SNAPSHOT_DELETE_BATCH_SIZE]
        connection.execute("BEGIN")
        try:
            _delete_snapshot_batch(connection, batch)
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    connection.execute("BEGIN")
    try:
        deleted_path_count = _delete_orphan_paths(connection)
    except Exception:
        connection.rollback()
        raise
    connection.commit()
    return deleted_path_count


def _delete_snapshot_batch(connection: sqlite3.Connection, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    connection.execute(
        f"DELETE FROM snapshots WHERE id IN ({placeholders})",
        snapshot_ids,
    )


def vacuum_database(connection: sqlite3.Connection, db_path: Path) -> VacuumResult:
    metrics = _collect_vacuum_metrics(connection, db_path)
    return VacuumResult(
        db_bytes_before=metrics.db_bytes_before,
        db_bytes_after=metrics.db_bytes_after,
        page_count_before=metrics.page_count_before,
        page_count_after=metrics.page_count_after,
        freelist_count_before=metrics.freelist_count_before,
        freelist_count_after=metrics.freelist_count_after,
        available_free_bytes_before=metrics.available_free_bytes_before,
        estimated_vacuum_required_free_bytes=metrics.estimated_vacuum_required_free_bytes,
        free_space_warning=metrics.free_space_warning,
        wal_checkpoint_busy=metrics.wal_checkpoint_busy,
        wal_checkpoint_log_pages=metrics.wal_checkpoint_log_pages,
        wal_checkpoint_checkpointed_pages=metrics.wal_checkpoint_checkpointed_pages,
        wal_checkpoint_warning=metrics.wal_checkpoint_warning,
    )


def _record_retained_snapshot_id(
    state: _RetentionSelectionState,
    row: sqlite3.Row,
    *,
    hourly_cutoff: datetime,
    daily_cutoff: datetime,
    incomplete_cutoff: datetime,
) -> None:
    snapshot_id = int(cast(int | str, row["id"]))
    raw_finished_at = cast(str | None, row["finished_at"])
    status = snapshot_status_from_storage(cast(str, row["status"]), finished_at=raw_finished_at)
    finished_at = _parse_snapshot_timestamp(raw_finished_at)
    if status is not SnapshotStatus.COMPLETE:
        evidence_at = finished_at or _parse_snapshot_timestamp(cast(str | None, row["started_at"]))
        if evidence_at is not None and evidence_at >= incomplete_cutoff:
            state.keep_ids.add(snapshot_id)
        return
    if finished_at is None:
        return
    if finished_at >= hourly_cutoff:
        state.keep_ids.add(snapshot_id)
        return

    root_path = cast(str, row["root_path"])
    representative = (finished_at, snapshot_id)
    if finished_at >= daily_cutoff:
        bucket = (root_path, finished_at.date())
        previous = state.daily_representatives.get(bucket)
        if previous is None or representative > previous:
            state.daily_representatives[bucket] = representative
        return

    bucket = (root_path, finished_at.year, finished_at.month)
    previous = state.monthly_representatives.get(bucket)
    if previous is None or representative > previous:
        state.monthly_representatives[bucket] = representative


def _collect_vacuum_metrics(connection: sqlite3.Connection, db_path: Path) -> _VacuumMetrics:
    db_path = Path(db_path).expanduser()
    baseline = _read_vacuum_baseline(connection, db_path.parent)
    _run_vacuum_maintenance(connection)
    checkpoint = _read_vacuum_checkpoint(connection, baseline.page_size)

    return _VacuumMetrics(
        db_bytes_before=baseline.db_bytes_before,
        db_bytes_after=checkpoint.db_bytes_after,
        page_count_before=baseline.page_count_before,
        page_count_after=checkpoint.page_count_after,
        freelist_count_before=baseline.freelist_count_before,
        freelist_count_after=checkpoint.freelist_count_after,
        available_free_bytes_before=baseline.available_free_bytes_before,
        estimated_vacuum_required_free_bytes=baseline.estimated_vacuum_required_free_bytes,
        free_space_warning=baseline.free_space_warning,
        wal_checkpoint_busy=checkpoint.wal_checkpoint_busy,
        wal_checkpoint_log_pages=checkpoint.wal_checkpoint_log_pages,
        wal_checkpoint_checkpointed_pages=checkpoint.wal_checkpoint_checkpointed_pages,
        wal_checkpoint_warning=checkpoint.wal_checkpoint_warning,
    )


@dataclass(frozen=True, slots=True)
class _VacuumBaselineMetrics:
    page_size: int
    db_bytes_before: int
    page_count_before: int
    freelist_count_before: int
    available_free_bytes_before: int
    estimated_vacuum_required_free_bytes: int
    free_space_warning: str | None


@dataclass(frozen=True, slots=True)
class _VacuumCheckpointMetrics:
    db_bytes_after: int
    page_count_after: int
    freelist_count_after: int
    wal_checkpoint_busy: int
    wal_checkpoint_log_pages: int
    wal_checkpoint_checkpointed_pages: int
    wal_checkpoint_warning: str | None


def _read_vacuum_baseline(connection: sqlite3.Connection, parent_path: Path) -> _VacuumBaselineMetrics:
    page_size_row = cast(sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA page_size").fetchone())
    page_count_row = cast(sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA page_count").fetchone())
    freelist_row = cast(sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA freelist_count").fetchone())
    if page_size_row is None or page_count_row is None or freelist_row is None:
        raise RuntimeError("sqlite did not return vacuum baseline rows")
    page_size = int(cast(int | str, page_size_row[0]))
    page_count_before = int(cast(int | str, page_count_row[0]))
    freelist_count_before = int(cast(int | str, freelist_row[0]))
    db_bytes_before = page_count_before * page_size
    available_free_bytes_before = _available_free_bytes(parent_path)
    estimated_vacuum_required_free_bytes = 3 * db_bytes_before
    free_space_warning = None
    if available_free_bytes_before < estimated_vacuum_required_free_bytes:
        free_space_warning = (
            "available free space may be too low for VACUUM "
            f"({available_free_bytes_before} < advisory {estimated_vacuum_required_free_bytes} bytes)"
        )
    return _VacuumBaselineMetrics(
        page_size=page_size,
        db_bytes_before=db_bytes_before,
        page_count_before=page_count_before,
        freelist_count_before=freelist_count_before,
        available_free_bytes_before=available_free_bytes_before,
        estimated_vacuum_required_free_bytes=estimated_vacuum_required_free_bytes,
        free_space_warning=free_space_warning,
    )


def _run_vacuum_maintenance(connection: sqlite3.Connection) -> None:
    connection.execute("VACUUM")
    connection.commit()


def _read_vacuum_checkpoint(
    connection: sqlite3.Connection,
    page_size: int,
) -> _VacuumCheckpointMetrics:
    wal_checkpoint_row = cast(
        sqlite3.Row | tuple[object, ...] | None,
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone(),
    )
    if wal_checkpoint_row is None:
        raise RuntimeError("sqlite did not return a wal checkpoint row")
    connection.commit()
    wal_checkpoint_busy = int(cast(int | str, wal_checkpoint_row[0]))
    wal_checkpoint_log_pages = int(cast(int | str, wal_checkpoint_row[1]))
    wal_checkpoint_checkpointed_pages = int(cast(int | str, wal_checkpoint_row[2]))

    wal_checkpoint_warning = None
    if wal_checkpoint_busy != 0 or wal_checkpoint_checkpointed_pages < wal_checkpoint_log_pages:
        wal_checkpoint_warning = (
            "wal_checkpoint(TRUNCATE) reported busy or partial progress "
            f"(busy={wal_checkpoint_busy}, log_pages={wal_checkpoint_log_pages}, "
            f"checkpointed_pages={wal_checkpoint_checkpointed_pages})"
        )

    page_count_after_row = cast(
        sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA page_count").fetchone()
    )
    freelist_count_after_row = cast(
        sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA freelist_count").fetchone()
    )
    if page_count_after_row is None or freelist_count_after_row is None:
        raise RuntimeError("sqlite did not return vacuum checkpoint rows")
    page_count_after = int(cast(int | str, page_count_after_row[0]))
    freelist_count_after = int(cast(int | str, freelist_count_after_row[0]))
    db_bytes_after = page_count_after * page_size
    return _VacuumCheckpointMetrics(
        db_bytes_after=db_bytes_after,
        page_count_after=page_count_after,
        freelist_count_after=freelist_count_after,
        wal_checkpoint_busy=wal_checkpoint_busy,
        wal_checkpoint_log_pages=wal_checkpoint_log_pages,
        wal_checkpoint_checkpointed_pages=wal_checkpoint_checkpointed_pages,
        wal_checkpoint_warning=wal_checkpoint_warning,
    )


def _delete_orphan_paths(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        """
        DELETE FROM paths
        WHERE NOT EXISTS (
            SELECT 1
            FROM directory_sizes
            WHERE path_id = paths.id
        )
          AND NOT EXISTS (
            SELECT 1
            FROM directory_sizes
            WHERE parent_id = paths.id
        )
          AND NOT EXISTS (
            SELECT 1
            FROM directory_sizes
            WHERE top_child_id = paths.id
        )
        """
    )
    return int(cursor.rowcount)


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _parse_snapshot_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)


def _required_window_days(tier: RetentionTier) -> int:
    if tier.window_days is None:
        raise ValueError(f"{tier.name} retention tier has no finite window")
    return tier.window_days


def _available_free_bytes(path: Path) -> int:
    stats = os.statvfs(path)
    fragment_size = stats.f_frsize or stats.f_bsize
    return int(fragment_size) * int(stats.f_bavail)
