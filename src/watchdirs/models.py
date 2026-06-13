from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SnapshotStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    id: int
    started_at: str
    finished_at: str | None
    root_path: Path
    status: SnapshotStatus
    notes: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class DirectoryAggregate:
    snapshot_id: int
    path: bytes
    parent_path: bytes | None
    name: bytes
    depth: int
    apparent_bytes: int
    disk_bytes: int
    file_count: int
    dir_count: int
    error: str | None


@dataclass(frozen=True, slots=True)
class MountInfo:
    mount_id: int
    parent_id: int
    major_minor: str
    root: bytes
    mount_point: bytes
    options: tuple[str, ...]
    filesystem_type: str
    mount_source: str
    super_options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotMount:
    snapshot_id: int
    mount_id: int
    parent_id: int
    major_minor: str
    root: bytes
    mount_point: bytes
    filesystem_type: str
    mount_source: str


@dataclass(frozen=True, slots=True)
class GroupLabel:
    kind: str
    key: str
    mount_point: bytes | None = None
    filesystem_type: str | None = None
    mount_source: str | None = None
    major_minor: str | None = None
    root: bytes | None = None


@dataclass(frozen=True, slots=True)
class ReportWarning:
    code: str
    message: str
    path: bytes | None = None


@dataclass(frozen=True, slots=True)
class SnapshotPair:
    root_path: Path
    baseline: SnapshotRecord
    current: SnapshotRecord
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiffRow:
    root_path: Path
    baseline_snapshot_id: int
    current_snapshot_id: int
    path: bytes
    parent_path: bytes | None
    depth: int
    classification: str
    previous_apparent_bytes: int
    current_apparent_bytes: int
    apparent_bytes_delta: int
    previous_disk_bytes: int
    current_disk_bytes: int
    disk_bytes_delta: int
    error: str | None
    group: GroupLabel | None = None


@dataclass(frozen=True, slots=True)
class FrontierRow:
    row: DiffRow
    suppressed_descendant_count: int
    suppressed_ancestor_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class TopRow:
    snapshot_id: int
    root_path: Path
    path: bytes
    path_bytes_hex: str
    depth: int
    current_apparent_bytes: int
    current_disk_bytes: int
    file_count: int
    dir_count: int
    error: str | None
    group: GroupLabel | None = None


@dataclass(frozen=True, slots=True)
class MountDecision:
    include: bool
    reason: str
    filesystem_type: str | None
    mount_id: int | None
    device_changed: bool


@dataclass(frozen=True, slots=True)
class MountPolicy:
    skipped_filesystems: frozenset[str] = field(default_factory=frozenset)
    included_filesystems: frozenset[str] = field(default_factory=frozenset)
    skip_overlay: bool = True
    skip_namespace: bool = True
    one_filesystem: bool = True


@dataclass(frozen=True, slots=True)
class ScanResult:
    root_path: Path
    rows: tuple[DirectoryAggregate, ...]
    row_count: int
    status: SnapshotStatus
    fatal_error: str | None
    errors: tuple[ScanError, ...]
    hardlink_count: int


@dataclass(frozen=True, slots=True)
class ScannerOptions:
    root: Path
    exclude_paths: tuple[Path, ...] = ()
    mounts: tuple[MountInfo, ...] = ()
    mount_policy: MountPolicy | None = None
    record_skipped: bool = False
    hardlink_dedup_max_entries: int = 500000


@dataclass(frozen=True, slots=True)
class ScanError:
    path: bytes
    path_bytes_hex: str
    message: str
    kind: str
