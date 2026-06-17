from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from watchdirs.models import SnapshotStatus


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


@dataclass(frozen=True, slots=True)
class PruneResult:
    deleted_snapshot_ids: list[int]
    deleted_snapshot_count: int
    retained_snapshot_count: int
    deleted_path_count: int
    snapshots_before: int
    snapshots_after: int


def select_retained_snapshot_ids(
    connection: sqlite3.Connection,
    policy: RetentionPolicy,
    *,
    now: datetime | None = None,
) -> tuple[int, ...]:
    effective_now = _normalize_now(now)
    hourly_cutoff = effective_now - timedelta(days=policy.hourly_days)
    daily_cutoff = effective_now - timedelta(days=policy.daily_days)

    keep_ids: set[int] = set()
    daily_representatives: dict[tuple[str, datetime.date], tuple[datetime, int]] = {}
    monthly_representatives: dict[tuple[str, int, int], tuple[datetime, int]] = {}

    rows = connection.execute(
        """
        SELECT id, root_path, status, finished_at
        FROM snapshots
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        snapshot_id = int(row["id"])
        finished_at = _parse_snapshot_timestamp(row["finished_at"])
        if finished_at is None:
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
