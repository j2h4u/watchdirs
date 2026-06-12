from __future__ import annotations

import os
from pathlib import Path

from watchdirs.models import DirectoryAggregate, ScanResult, SnapshotStatus


def scan_root(root_path: Path) -> ScanResult:
    resolved_root = Path(root_path)
    try:
        rows, partial_error = _scan_directory(resolved_root, depth=0, snapshot_id=0)
    except OSError as exc:
        return ScanResult(
            root_path=resolved_root,
            rows=(),
            row_count=0,
            status=SnapshotStatus.FAILED,
            fatal_error=_format_os_error(exc),
        )

    status = SnapshotStatus.PARTIAL if partial_error else SnapshotStatus.COMPLETE
    return ScanResult(
        root_path=resolved_root,
        rows=rows,
        row_count=len(rows),
        status=status,
        fatal_error=None,
    )


def _scan_directory(path: Path, *, depth: int, snapshot_id: int) -> tuple[tuple[DirectoryAggregate, ...], bool]:
    path_stat = path.stat(follow_symlinks=False)
    apparent_bytes = path_stat.st_size
    disk_bytes = path_stat.st_blocks * 512
    file_count = 0
    dir_count = 0
    child_rows: list[DirectoryAggregate] = []
    partial_error = False
    directory_error: str | None = None

    with os.scandir(path) as entries:
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    nested_rows, child_partial = _scan_directory(
                        Path(entry.path),
                        depth=depth + 1,
                        snapshot_id=snapshot_id,
                    )
                    if not nested_rows:
                        continue
                    partial_error = partial_error or child_partial
                    child_root = nested_rows[0]
                    apparent_bytes += child_root.apparent_bytes
                    disk_bytes += child_root.disk_bytes
                    file_count += child_root.file_count
                    dir_count += child_root.dir_count + 1
                    child_rows.extend(nested_rows)
                    continue

                entry_stat = entry.stat(follow_symlinks=False)
                if entry.is_file(follow_symlinks=False):
                    file_count += 1
                    apparent_bytes += entry_stat.st_size
                    disk_bytes += entry_stat.st_blocks * 512
            except OSError as exc:
                partial_error = True
                if directory_error is None:
                    directory_error = _format_os_error(exc)

    current_row = DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=os.fsencode(path),
        parent_path=os.fsencode(path.parent) if depth > 0 else None,
        name=_path_name_bytes(path, is_root=depth == 0),
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=directory_error,
    )
    return (current_row, *child_rows), partial_error


def _path_name_bytes(path: Path, *, is_root: bool) -> bytes:
    if is_root and not path.name:
        return os.fsencode(path.anchor or str(path))
    return os.fsencode(path.name)


def _format_os_error(error: OSError) -> str:
    strerror = error.strerror or str(error)
    return f"{error.__class__.__name__}: {strerror}"
