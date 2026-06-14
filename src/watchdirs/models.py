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

    @property
    def path_bytes_hex(self) -> str:
        return self.path.hex()


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
class ReportGroupSummary:
    group: GroupLabel | None
    path_count: int
    disk_bytes_delta: int
    apparent_bytes_delta: int


@dataclass(frozen=True, slots=True)
class ReportSummary:
    snapshot_pairs: tuple[SnapshotPair, ...]
    classification_counts: dict[str, int]
    disk_bytes_delta_by_classification: dict[str, int]
    apparent_bytes_delta_by_classification: dict[str, int]
    frontier: tuple[FrontierRow, ...]
    groups: tuple[ReportGroupSummary, ...]
    deleted_preview: tuple[DiffRow, ...]
    warnings: tuple[ReportWarning, ...]


@dataclass(frozen=True, slots=True)
class ExplainPathResult:
    target: DiffRow
    children: tuple[DiffRow, ...]
    unshown_or_direct_disk_bytes_delta: int
    unshown_or_direct_apparent_bytes_delta: int
    warnings: tuple[ReportWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexedStorageDomainTotal:
    storage_domain: GroupLabel
    indexed_visible_disk_bytes: int
    indexed_visible_apparent_bytes: int
    indexed_visible_path_count: int
    indexed_root_paths: tuple[bytes, ...]
    indexed_mount_points: tuple[bytes, ...]
    snapshot_ids: tuple[int, ...]
    snapshot_statuses: tuple[str, ...]
    finished_at_min: str | None
    finished_at_max: str | None
    partial_snapshot_count: int
    unknown_mount_count: int


@dataclass(frozen=True, slots=True)
class FilesystemUsage:
    size_bytes: int
    used_bytes: int
    free_total_bytes: int
    avail_unprivileged_bytes: int


@dataclass(frozen=True, slots=True)
class DiagnosticHint:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class DfIndexSection:
    storage_domain: GroupLabel
    snapshot_ids: tuple[int, ...]
    snapshot_statuses: tuple[str, ...]
    finished_at_min: str | None
    finished_at_max: str | None
    max_snapshot_age_seconds: int | None
    filesystem_stat_available: bool
    filesystem_status: str
    df_usage: FilesystemUsage | None
    df_used_bytes: int | None
    indexed_visible_disk_bytes: int
    indexed_visible_apparent_bytes: int
    indexed_visible_path_count: int
    indexed_root_paths: tuple[bytes, ...]
    indexed_mount_points: tuple[bytes, ...]
    partial_snapshot_count: int
    unknown_mount_count: int
    filesystem_scope_extends_beyond_indexed_roots: bool
    coverage_reason_codes: tuple[str, ...]
    unattributed_bytes: int | None
    unattributed_ratio: float | None
    over_indexed_bytes: int | None
    over_indexed_ratio: float | None
    likely_reasons: tuple[str, ...]
    verification_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DfIndexDiagnostic:
    ok: bool
    snapshot_selector: str
    limit: int
    effective_limit: int
    generated_at: str
    filesystems: tuple[DfIndexSection, ...]
    truncated: bool
    total_filesystem_count: int
    warnings: tuple[ReportWarning, ...]


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
