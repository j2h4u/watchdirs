from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import stat

from watchdirs.models import DirectoryAggregate, ScanError, ScanResult, ScannerOptions, SnapshotStatus


PATH_SEPARATOR = os.fsencode(os.sep)


@dataclass(slots=True)
class _Frame:
    path_raw: bytes
    parent_path: bytes | None
    depth: int
    apparent_bytes: int = 0
    disk_bytes: int = 0
    file_count: int = 0
    dir_count: int = 0
    error: str | None = None
    entries: list[os.DirEntry[bytes]] = field(default_factory=list)
    next_index: int = 0
    initialized: bool = False


def scan_root(options: ScannerOptions) -> ScanResult:
    root_path = Path(options.root).resolve(strict=False)
    root_raw = path_bytes(root_path)
    exclude_paths = tuple(path_bytes(Path(path).resolve(strict=False)) for path in options.exclude_paths)
    rows: list[DirectoryAggregate] = []
    errors: list[ScanError] = []
    had_failure = False
    hardlink_count = 0
    seen_inodes: set[tuple[int, int]] = set()

    stack = [_Frame(path_raw=root_raw, parent_path=None, depth=0)]

    while stack:
        frame = stack[-1]
        if not frame.initialized:
            try:
                directory_stat = os.stat(frame.path_raw, follow_symlinks=False)
                if not stat.S_ISDIR(directory_stat.st_mode):
                    raise NotADirectoryError(display_path(frame.path_raw))
                frame.apparent_bytes = directory_stat.st_size
                frame.disk_bytes = directory_stat.st_blocks * 512
                frame.entries = _sorted_entries(frame.path_raw)
                frame.initialized = True
            except OSError as exc:
                error = _scan_error(frame.path_raw, exc)
                errors.append(error)
                if frame.depth == 0:
                    return ScanResult(
                        root_path=root_path,
                        rows=tuple(rows),
                        row_count=len(rows),
                        status=SnapshotStatus.FAILED,
                        fatal_error=error.message,
                        errors=tuple(errors),
                        hardlink_count=hardlink_count,
                    )

                frame.error = error.message
                row = _directory_row(frame)
                stack.pop()
                rows.append(row)
                _merge_child(stack[-1], row)
                had_failure = True
                continue

        if frame.next_index >= len(frame.entries):
            row = _directory_row(frame)
            stack.pop()
            rows.append(row)
            if stack:
                _merge_child(stack[-1], row)
            continue

        entry = frame.entries[frame.next_index]
        frame.next_index += 1
        entry_path = path_bytes(entry.path)

        if _is_excluded(entry_path, exclude_paths):
            if options.record_skipped:
                errors.append(_scan_error_message(entry_path, "excluded", "excluded by configuration"))
            continue

        try:
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as exc:
            error = _scan_error(entry_path, exc)
            errors.append(error)
            frame.error = frame.error or error.message
            had_failure = True
            continue

        if stat.S_ISDIR(entry_stat.st_mode):
            stack.append(
                _Frame(
                    path_raw=entry_path,
                    parent_path=frame.path_raw,
                    depth=frame.depth + 1,
                )
            )
            continue

        frame.file_count += 1
        frame.apparent_bytes += apparent_bytes_from_stat(entry_stat)

        try:
            disk_bytes, counted_as_hardlink = _disk_bytes_for_entry(
                entry_stat,
                seen_inodes,
                options.hardlink_dedup_max_entries,
                entry_path,
            )
        except _HardlinkLimitExceeded as exc:
            error = exc.error
            errors.append(error)
            status = SnapshotStatus.PARTIAL if rows else SnapshotStatus.FAILED
            return ScanResult(
                root_path=root_path,
                rows=tuple(rows),
                row_count=len(rows),
                status=status,
                fatal_error=error.message if status is SnapshotStatus.FAILED else None,
                errors=tuple(errors),
                hardlink_count=hardlink_count,
            )

        frame.disk_bytes += disk_bytes
        if counted_as_hardlink:
            hardlink_count += 1

    return ScanResult(
        root_path=root_path,
        rows=tuple(rows),
        row_count=len(rows),
        status=SnapshotStatus.PARTIAL if had_failure else SnapshotStatus.COMPLETE,
        fatal_error=None,
        errors=tuple(errors),
        hardlink_count=hardlink_count,
    )


def scan_directory(path: Path | bytes, *, parent_path: bytes | None, depth: int) -> _Frame:
    return _Frame(
        path_raw=path_bytes(path),
        parent_path=parent_path,
        depth=depth,
    )


def aggregate_entry(row: DirectoryAggregate, *, snapshot_id: int = 0) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=row.path,
        parent_path=row.parent_path,
        name=row.name,
        depth=row.depth,
        apparent_bytes=row.apparent_bytes,
        disk_bytes=row.disk_bytes,
        file_count=row.file_count,
        dir_count=row.dir_count,
        error=row.error,
    )


def disk_bytes_from_stat(stat_result: os.stat_result) -> int:
    if stat.S_ISREG(stat_result.st_mode) or stat.S_ISLNK(stat_result.st_mode):
        return stat_result.st_blocks * 512
    return 0


def apparent_bytes_from_stat(stat_result: os.stat_result) -> int:
    if stat.S_ISREG(stat_result.st_mode) or stat.S_ISLNK(stat_result.st_mode):
        return stat_result.st_size
    return 0


def path_bytes(path_value: os.PathLike[str] | os.PathLike[bytes] | str | bytes) -> bytes:
    raw_path = os.fspath(path_value)
    if isinstance(raw_path, bytes):
        return raw_path
    return os.fsencode(raw_path)


def display_path(path_value: os.PathLike[str] | os.PathLike[bytes] | str | bytes) -> str:
    raw_path = os.fspath(path_value)
    if isinstance(raw_path, bytes):
        return os.fsdecode(raw_path)
    return os.fsdecode(os.fsencode(raw_path))


def inode_key(stat_result: os.stat_result) -> tuple[int, int]:
    return (stat_result.st_dev, stat_result.st_ino)


def _directory_row(frame: _Frame) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=0,
        path=frame.path_raw,
        parent_path=frame.parent_path,
        name=_path_name_bytes(frame.path_raw, is_root=frame.depth == 0),
        depth=frame.depth,
        apparent_bytes=frame.apparent_bytes,
        disk_bytes=frame.disk_bytes,
        file_count=frame.file_count,
        dir_count=frame.dir_count,
        error=frame.error,
    )


def _disk_bytes_for_entry(
    stat_result: os.stat_result,
    seen_inodes: set[tuple[int, int]],
    max_entries: int,
    entry_path: bytes,
) -> tuple[int, bool]:
    if not stat.S_ISREG(stat_result.st_mode):
        return disk_bytes_from_stat(stat_result), False

    key = inode_key(stat_result)
    if key in seen_inodes:
        return 0, stat_result.st_nlink > 1

    if len(seen_inodes) >= max_entries:
        raise _HardlinkLimitExceeded(
            _scan_error_message(
                entry_path,
                "hardlink_limit",
                f"hardlink dedup entry limit exceeded at {max_entries} inode keys",
            )
        )

    seen_inodes.add(key)
    return disk_bytes_from_stat(stat_result), stat_result.st_nlink > 1


def _merge_child(parent: _Frame, child_row: DirectoryAggregate) -> None:
    parent.apparent_bytes += child_row.apparent_bytes
    parent.disk_bytes += child_row.disk_bytes
    parent.file_count += child_row.file_count
    parent.dir_count += child_row.dir_count + 1


def _is_excluded(path_raw: bytes, exclude_paths: tuple[bytes, ...]) -> bool:
    for excluded in exclude_paths:
        if path_raw == excluded:
            return True
        if excluded == PATH_SEPARATOR:
            return True
        if path_raw.startswith(excluded + PATH_SEPARATOR):
            return True
    return False


def _path_name_bytes(path_raw: bytes, *, is_root: bool) -> bytes:
    normalized = path_raw.rstrip(PATH_SEPARATOR) or PATH_SEPARATOR
    name = os.path.basename(normalized)
    if name:
        return name
    if is_root:
        return PATH_SEPARATOR
    return normalized


def _scan_error(path_raw: bytes, error: OSError) -> ScanError:
    return _scan_error_message(path_raw, _error_kind(error), _format_os_error(error))


def _scan_error_message(path_raw: bytes, kind: str, message: str) -> ScanError:
    return ScanError(
        path=path_raw,
        path_bytes_hex=path_raw.hex(),
        message=message,
        kind=kind,
    )


def _sorted_entries(path_raw: bytes) -> list[os.DirEntry[bytes]]:
    with os.scandir(path_raw) as entries:
        return sorted(entries, key=lambda entry: path_bytes(entry.path))


def _error_kind(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, FileNotFoundError):
        return "missing_path"
    if isinstance(error, NotADirectoryError):
        return "not_a_directory"
    return "os_error"


def _format_os_error(error: OSError) -> str:
    strerror = error.strerror or str(error)
    return f"{error.__class__.__name__}: {strerror}"


class _HardlinkLimitExceeded(Exception):
    def __init__(self, error: ScanError) -> None:
        super().__init__(error.message)
        self.error = error
