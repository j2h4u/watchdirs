from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import os
from pathlib import Path
import sqlite3

from watchdirs.models import SnapshotStatus


class RetentionTierMode(StrEnum):
    ALL_STATUSES_IN_WINDOW = "all_statuses_in_window"
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
    hourly_days: int = 14
    daily_days: int = 90

    def __post_init__(self) -> None:
        if self.hourly_days <= 0:
            raise ValueError("hourly_days must be a positive integer")
        if self.daily_days <= 0:
            raise ValueError("daily_days must be a positive integer")
        if self.daily_days < self.hourly_days:
            raise ValueError("daily_days must be greater than or equal to hourly_days")

    @property
    def tiers(self) -> tuple[RetentionTier, RetentionTier, RetentionTier]:
        return (
            RetentionTier(
                name="hourly",
                mode=RetentionTierMode.ALL_STATUSES_IN_WINDOW,
                window_days=self.hourly_days,
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


def select_retained_snapshot_ids(
    connection: sqlite3.Connection,
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
) -> tuple[int, ...]:
    effective_now = _normalize_now(now)
    hourly_tier = policy.tier(RetentionTierMode.ALL_STATUSES_IN_WINDOW)
    daily_tier = policy.tier(RetentionTierMode.LATEST_COMPLETE_PER_UTC_DAY)
    hourly_cutoff = effective_now - timedelta(days=_required_window_days(hourly_tier))
    daily_cutoff = effective_now - timedelta(days=_required_window_days(daily_tier))

    keep_ids: set[int] = set()
    daily_representatives: dict[tuple[str, datetime.date], tuple[datetime, int]] = {}
    monthly_representatives: dict[tuple[str, int, int], tuple[datetime, int]] = {}

    rows = connection.execute(
        """
        SELECT id, root_path, status, started_at, finished_at
        FROM snapshots
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        snapshot_id = int(row["id"])
        finished_at = _parse_snapshot_timestamp(row["finished_at"])
        if finished_at is None:
            started_at = _parse_snapshot_timestamp(row["started_at"])
            if started_at is None or started_at >= hourly_cutoff:
                keep_ids.add(snapshot_id)
            continue
        if finished_at >= hourly_cutoff:
            keep_ids.add(snapshot_id)
            continue
        if row["status"] != SnapshotStatus.COMPLETE.value:
            continue
        root_path = row["root_path"]
        representative = (finished_at, snapshot_id)
        if finished_at >= daily_cutoff:
            bucket = (root_path, finished_at.date())
            previous = daily_representatives.get(bucket)
            if previous is None or representative > previous:
                daily_representatives[bucket] = representative
            continue
        bucket = (root_path, finished_at.year, finished_at.month)
        previous = monthly_representatives.get(bucket)
        if previous is None or representative > previous:
            monthly_representatives[bucket] = representative

    keep_ids.update(snapshot_id for _finished_at, snapshot_id in daily_representatives.values())
    keep_ids.update(snapshot_id for _finished_at, snapshot_id in monthly_representatives.values())
    return tuple(sorted(keep_ids))


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
        int(row["id"])
        for row in connection.execute("SELECT id FROM snapshots ORDER BY id").fetchall()
    ]
    deleted_snapshot_ids = [
        snapshot_id
        for snapshot_id in snapshot_ids
        if snapshot_id not in retained_snapshot_id_set
    ]
    snapshots_before = len(snapshot_ids)

    connection.execute("BEGIN")
    try:
        if deleted_snapshot_ids:
            placeholders = ",".join("?" for _ in deleted_snapshot_ids)
            connection.execute(
                f"DELETE FROM snapshots WHERE id IN ({placeholders})",
                deleted_snapshot_ids,
            )
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


def vacuum_database(connection: sqlite3.Connection, db_path: Path) -> VacuumResult:
    db_path = Path(db_path).expanduser()
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count_before = int(connection.execute("PRAGMA page_count").fetchone()[0])
    freelist_count_before = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    db_bytes_before = page_count_before * page_size
    available_free_bytes_before = _available_free_bytes(db_path.parent)
    estimated_vacuum_required_free_bytes = 3 * db_bytes_before
    free_space_warning = None
    if available_free_bytes_before < estimated_vacuum_required_free_bytes:
        free_space_warning = (
            "available free space may be too low for VACUUM "
            f"({available_free_bytes_before} < advisory {estimated_vacuum_required_free_bytes} bytes)"
        )

    connection.execute("VACUUM")
    connection.commit()

    wal_checkpoint_row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    connection.commit()
    wal_checkpoint_busy = int(wal_checkpoint_row[0])
    wal_checkpoint_log_pages = int(wal_checkpoint_row[1])
    wal_checkpoint_checkpointed_pages = int(wal_checkpoint_row[2])

    wal_checkpoint_warning = None
    if wal_checkpoint_busy != 0 or wal_checkpoint_checkpointed_pages < wal_checkpoint_log_pages:
        wal_checkpoint_warning = (
            "wal_checkpoint(TRUNCATE) reported busy or partial progress "
            f"(busy={wal_checkpoint_busy}, log_pages={wal_checkpoint_log_pages}, "
            f"checkpointed_pages={wal_checkpoint_checkpointed_pages})"
        )

    page_count_after = int(connection.execute("PRAGMA page_count").fetchone()[0])
    freelist_count_after = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    db_bytes_after = page_count_after * page_size

    return VacuumResult(
        db_bytes_before=db_bytes_before,
        db_bytes_after=db_bytes_after,
        page_count_before=page_count_before,
        page_count_after=page_count_after,
        freelist_count_before=freelist_count_before,
        freelist_count_after=freelist_count_after,
        available_free_bytes_before=available_free_bytes_before,
        estimated_vacuum_required_free_bytes=estimated_vacuum_required_free_bytes,
        free_space_warning=free_space_warning,
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
            WHERE directory_sizes.path_id = paths.id
        )
          AND NOT EXISTS (
            SELECT 1
            FROM directory_sizes
            WHERE directory_sizes.parent_id = paths.id
        )
          AND NOT EXISTS (
            SELECT 1
            FROM directory_sizes
            WHERE directory_sizes.top_child_id = paths.id
        )
        """
    )
    return int(cursor.rowcount)


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_snapshot_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _required_window_days(tier: RetentionTier) -> int:
    if tier.window_days is None:
        raise ValueError(f"{tier.name} retention tier has no finite window")
    return tier.window_days


def _available_free_bytes(path: Path) -> int:
    stats = os.statvfs(path)
    fragment_size = stats.f_frsize or stats.f_bsize
    return int(fragment_size) * int(stats.f_bavail)
