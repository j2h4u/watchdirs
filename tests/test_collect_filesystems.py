from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import watchdirs.collect.filesystems as filesystems
from watchdirs.collect.filesystems import collect_snapshot_filesystem_usage
from watchdirs.models import MountInfo, MountPolicy


@dataclass(frozen=True, slots=True)
class _StatvfsResult:
    f_frsize: int
    f_bsize: int
    f_blocks: int
    f_bfree: int
    f_bavail: int


def _mount(mount_id: int, mount_point: bytes, *, filesystem_type: str = "ext4") -> MountInfo:
    return MountInfo(
        mount_id=mount_id,
        parent_id=1,
        major_minor=f"8:{mount_id}",
        root=b"/",
        mount_point=mount_point,
        options=(),
        filesystem_type=filesystem_type,
        mount_source=f"source-{mount_id}",
        super_options=(),
    )


def test_collect_snapshot_filesystem_usage_records_statvfs_values(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_statvfs(path: bytes) -> _StatvfsResult:
        assert path == b"/data"
        return _StatvfsResult(f_frsize=4096, f_bsize=1024, f_blocks=100, f_bfree=25, f_bavail=20)

    monkeypatch.setattr(filesystems.os, "statvfs", fake_statvfs)

    rows = collect_snapshot_filesystem_usage(
        snapshot_id=123,
        root_path=Path("/data"),
        mounts=(_mount(41, b"/data"),),
        mount_policy=MountPolicy(),
    )

    assert len(rows) == 1
    assert rows[0].snapshot_id == 123
    assert rows[0].mount_id == 41
    assert rows[0].total_bytes == 409600
    assert rows[0].used_bytes == 307200
    assert rows[0].free_bytes == 102400
    assert rows[0].available_bytes == 81920
    assert rows[0].capture_error is None


def test_collect_snapshot_filesystem_usage_preserves_statvfs_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_statvfs(_path: bytes) -> _StatvfsResult:
        raise OSError("mount disappeared")

    monkeypatch.setattr(filesystems.os, "statvfs", fail_statvfs)

    rows = collect_snapshot_filesystem_usage(
        snapshot_id=123,
        root_path=Path("/data"),
        mounts=(_mount(41, b"/data"),),
        mount_policy=MountPolicy(),
    )

    assert len(rows) == 1
    assert rows[0].total_bytes is None
    assert rows[0].used_bytes is None
    assert rows[0].free_bytes is None
    assert rows[0].available_bytes is None
    assert rows[0].capture_error == "mount disappeared"


def test_collect_snapshot_filesystem_usage_filters_policy_scope_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []

    def fake_statvfs(path: bytes) -> _StatvfsResult:
        calls.append(path)
        return _StatvfsResult(f_frsize=1, f_bsize=1, f_blocks=10, f_bfree=4, f_bavail=3)

    monkeypatch.setattr(filesystems.os, "statvfs", fake_statvfs)

    rows = collect_snapshot_filesystem_usage(
        snapshot_id=123,
        root_path=Path("/"),
        mounts=(
            _mount(41, b"/data"),
            _mount(42, b"/data"),
            _mount(43, b"/proc", filesystem_type="proc"),
        ),
        mount_policy=MountPolicy(),
    )

    assert [row.mount_id for row in rows] == [41]
    assert calls == [b"/data"]


def test_collect_snapshot_filesystem_usage_includes_filesystem_containing_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []

    def fake_statvfs(path: bytes) -> _StatvfsResult:
        calls.append(path)
        return _StatvfsResult(f_frsize=1, f_bsize=1, f_blocks=10, f_bfree=4, f_bavail=3)

    monkeypatch.setattr(filesystems.os, "statvfs", fake_statvfs)

    rows = collect_snapshot_filesystem_usage(
        snapshot_id=123,
        root_path=Path("/data/project"),
        mounts=(
            _mount(1, b"/"),
            _mount(2, b"/data/project/nested"),
            _mount(3, b"/unrelated"),
        ),
        mount_policy=MountPolicy(),
    )

    assert [row.mount_id for row in rows] == [1, 2]
    assert calls == [b"/", b"/data/project/nested"]
