from __future__ import annotations

from dataclasses import dataclass
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
class ScanResult:
    root_path: Path
    rows: tuple[DirectoryAggregate, ...]
    row_count: int
    status: SnapshotStatus
    fatal_error: str | None
