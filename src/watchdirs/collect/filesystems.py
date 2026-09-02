from __future__ import annotations

import os
from pathlib import Path

from watchdirs.collect.classify import classify_mount
from watchdirs.collect.mounts import find_mount_for_path
from watchdirs.collect.scanner import path_bytes
from watchdirs.models import MountInfo, MountPolicy, SnapshotFilesystemUsage

PATH_SEPARATOR = b"/"


def collect_snapshot_filesystem_usage(
    *,
    snapshot_id: int,
    root_path: Path,
    mounts: tuple[MountInfo, ...],
    mount_policy: MountPolicy | None,
) -> tuple[SnapshotFilesystemUsage, ...]:
    root_raw = _normalize_path(path_bytes(root_path))
    root_mount = find_mount_for_path(root_raw, mounts)
    rows: list[SnapshotFilesystemUsage] = []
    seen_mount_points: set[bytes] = set()
    for mount in mounts:
        mount_point = _normalize_path(mount.mount_point)
        if mount_point in seen_mount_points:
            continue
        if not _mount_is_in_scope(mount=mount, root_mount=root_mount, mount_point=mount_point, root_raw=root_raw):
            continue
        decision = classify_mount(mount, mount_policy)
        if not decision.include:
            continue
        seen_mount_points.add(mount_point)
        rows.append(_filesystem_usage_row(snapshot_id, mount))
    return tuple(rows)


def _filesystem_usage_row(snapshot_id: int, mount: MountInfo) -> SnapshotFilesystemUsage:
    try:
        stat = os.statvfs(mount.mount_point)
    except OSError as exc:
        return SnapshotFilesystemUsage(
            snapshot_id=snapshot_id,
            mount_id=mount.mount_id,
            major_minor=mount.major_minor,
            root=mount.root,
            mount_point=mount.mount_point,
            filesystem_type=mount.filesystem_type,
            mount_source=mount.mount_source,
            total_bytes=None,
            used_bytes=None,
            free_bytes=None,
            available_bytes=None,
            capture_error=str(exc),
        )

    block_size = stat.f_frsize or stat.f_bsize
    total_bytes = stat.f_blocks * block_size
    free_bytes = stat.f_bfree * block_size
    return SnapshotFilesystemUsage(
        snapshot_id=snapshot_id,
        mount_id=mount.mount_id,
        major_minor=mount.major_minor,
        root=mount.root,
        mount_point=mount.mount_point,
        filesystem_type=mount.filesystem_type,
        mount_source=mount.mount_source,
        total_bytes=total_bytes,
        used_bytes=total_bytes - free_bytes,
        free_bytes=free_bytes,
        available_bytes=stat.f_bavail * block_size,
        capture_error=None,
    )


def _normalize_path(path_raw: bytes) -> bytes:
    normalized = path_raw.rstrip(PATH_SEPARATOR)
    return normalized or PATH_SEPARATOR


def _mount_is_in_scope(
    *,
    mount: MountInfo,
    root_mount: MountInfo | None,
    mount_point: bytes,
    root_raw: bytes,
) -> bool:
    if root_raw == PATH_SEPARATOR:
        return True
    if root_mount is not None and mount.mount_id == root_mount.mount_id:
        return True
    return mount_point == root_raw or mount_point.startswith(root_raw + PATH_SEPARATOR)
