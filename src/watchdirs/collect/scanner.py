from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import stat

from watchdirs.collect.classify import classify_mount
from watchdirs.collect.mounts import find_mount_for_path
from watchdirs.models import (
    CollapsePolicy,
    DirectoryAggregate,
    MountDecision,
    MountInfo,
    MountPolicy,
    ScanError,
    ScanResult,
    ScannerOptions,
    SnapshotStatus,
)


PATH_SEPARATOR = os.fsencode(os.sep)


@dataclass(slots=True)
class _Frame:
    path_raw: bytes
    parent_path: bytes | None
    depth: int
    initial_stat: os.stat_result | object | None = None
    directory_identity: tuple[int, int] | None = None
    mount_id: int | None = None
    mount_signature: tuple[str, bytes, bytes] | None = None
    apparent_bytes: int = 0
    disk_bytes: int = 0
    file_count: int = 0
    dir_count: int = 0
    error: str | None = None
    row_start: int = 0
    collapse_reason: str | None = None
    direct_child_dir_count: int = 0
    top_child_path: bytes | None = None
    top_child_disk_bytes: int | None = None
    folded_evidence_counts: dict[str, int] = field(default_factory=dict)
    entries: list[os.DirEntry[bytes]] = field(default_factory=list)
    next_index: int = 0
    initialized: bool = False


def scan_root(options: ScannerOptions) -> ScanResult:
    root_path = Path(options.root).expanduser()
    if not root_path.is_absolute():
        root_path = root_path.absolute()
    root_raw = path_bytes(root_path)
    exclude_paths = tuple(path_bytes(Path(path).resolve(strict=False)) for path in options.exclude_paths)
    mounts = tuple(options.mounts)
    mount_policy = options.mount_policy if isinstance(options.mount_policy, MountPolicy) else MountPolicy()
    collapse_policy = options.collapse_policy if isinstance(options.collapse_policy, CollapsePolicy) else None
    collapse_never_paths = (
        tuple(path_bytes(Path(path).resolve(strict=False)) for path in collapse_policy.never)
        if collapse_policy is not None
        else ()
    )
    rows: list[DirectoryAggregate] = []
    errors: list[ScanError] = []
    had_failure = False
    hardlink_count = 0
    seen_inodes: set[tuple[int, int]] = set()
    if _has_symlink_component(root_path):
        error = _scan_error_message(
            root_raw,
            "symlink_root",
            "configured root must not traverse a symlinked path component",
        )
        return ScanResult(
            root_path=root_path,
            rows=(),
            row_count=0,
            status=SnapshotStatus.FAILED,
            fatal_error=error.message,
            errors=(error,),
            hardlink_count=0,
        )
    try:
        root_stat = os.stat(root_raw, follow_symlinks=False)
    except OSError as exc:
        error = _scan_error_message(root_raw, "root_error", str(exc))
        return ScanResult(
            root_path=root_path,
            rows=(),
            row_count=0,
            status=SnapshotStatus.FAILED,
            fatal_error=error.message,
            errors=(error,),
            hardlink_count=0,
        )
    if stat.S_ISLNK(root_stat.st_mode):
        error = _scan_error_message(root_raw, "symlink_root", "configured root must not be a symlink")
        return ScanResult(
            root_path=root_path,
            rows=(),
            row_count=0,
            status=SnapshotStatus.FAILED,
            fatal_error=error.message,
            errors=(error,),
            hardlink_count=0,
        )
    root_mount = find_mount_for_path(root_raw, mounts) if mounts else None

    if mounts and root_mount is None:
        error = _scan_error_message(root_raw, "mount_missing", "no mountinfo entry found for configured root")
        return ScanResult(
            root_path=root_path,
            rows=(),
            row_count=0,
            status=SnapshotStatus.FAILED,
            fatal_error=error.message,
            errors=(error,),
            hardlink_count=0,
        )

    if root_mount is not None:
        root_decision = classify_mount(root_mount, mount_policy)
        if not root_decision.include:
            error = _scan_error_message(root_raw, "mount_skipped", root_decision.reason)
            return ScanResult(
                root_path=root_path,
                rows=(),
                row_count=0,
                status=SnapshotStatus.FAILED,
                fatal_error=error.message,
                errors=(error,),
                hardlink_count=0,
            )

    stack = [
        _Frame(
            path_raw=root_raw,
            parent_path=None,
            depth=0,
            initial_stat=root_stat,
            mount_id=root_mount.mount_id if root_mount else None,
            mount_signature=_mount_signature(root_mount),
        )
    ]
    root_device: int | None = None

    while stack:
        frame = stack[-1]
        if not frame.initialized:
            try:
                directory_stat = frame.initial_stat or os.stat(frame.path_raw, follow_symlinks=False)
                if not stat.S_ISDIR(directory_stat.st_mode):
                    raise NotADirectoryError(display_path(frame.path_raw))
                frame.initial_stat = None
                frame.apparent_bytes = directory_stat.st_size
                frame.disk_bytes = directory_stat.st_blocks * 512
                frame.directory_identity = inode_key(directory_stat)
                if root_device is None:
                    root_device = directory_stat.st_dev
                if frame.mount_signature is None:
                    mount_info = find_mount_for_path(frame.path_raw, mounts) if mounts else None
                    frame.mount_id = mount_info.mount_id if mount_info else None
                    frame.mount_signature = _mount_signature(mount_info)
                frame.row_start = len(rows)
                frame.collapse_reason = _initial_collapse_reason(
                    path_raw=frame.path_raw,
                    collapse_policy=collapse_policy,
                    collapse_never_paths=collapse_never_paths,
                )
                frame.entries = _sorted_entries(frame.path_raw)
                frame.initialized = True
            except OSError as exc:
                error = _scan_error(frame.path_raw, exc)
                errors.append(error)
                _record_folded_evidence(frame, error.kind)
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
                _merge_child(stack[-1], row, child_evidence_counts=frame.folded_evidence_counts)
                had_failure = True
                continue

        if frame.next_index >= len(frame.entries):
            collapse_reason = frame.collapse_reason
            if (
                collapse_reason is None
                and collapse_policy is not None
                and not _is_protected_path(frame.path_raw, collapse_never_paths)
                and frame.dir_count >= collapse_policy.descendants
            ):
                collapse_reason = "descendant_count"

            if collapse_reason is not None:
                del rows[frame.row_start:]
                row = _collapsed_directory_row(frame, collapse_reason=collapse_reason)
            else:
                row = _directory_row(frame)
            stack.pop()
            rows.append(row)
            if stack:
                _merge_child(stack[-1], row, child_evidence_counts=frame.folded_evidence_counts)
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
                _record_folded_evidence(frame, error.kind)
                frame.error = frame.error or error.message
                had_failure = True
                continue

        if stat.S_ISDIR(entry_stat.st_mode):
            frame.direct_child_dir_count += 1
            if (
                frame.collapse_reason is None
                and collapse_policy is not None
                and not _is_protected_path(frame.path_raw, collapse_never_paths)
                and frame.direct_child_dir_count >= collapse_policy.fan_out
            ):
                frame.collapse_reason = "fan_out"
            decision = should_descend(
                path_raw=entry_path,
                stat_result=entry_stat,
                root_device=root_device if root_device is not None else entry_stat.st_dev,
                mount_info=find_mount_for_path(entry_path, mounts) if mounts else None,
                mount_policy=mount_policy,
                current_mount_id=frame.mount_id,
                current_mount_signature=frame.mount_signature,
                active_mount_ids=frozenset(candidate.mount_id for candidate in stack if candidate.mount_id is not None),
                active_mount_signatures=frozenset(
                    candidate.mount_signature for candidate in stack if candidate.mount_signature is not None
                ),
                active_directory_keys=frozenset(
                    candidate.directory_identity for candidate in stack if candidate.directory_identity is not None
                ),
            )
            if not decision.include:
                _record_folded_evidence(frame, "mount_skipped")
                if options.record_skipped:
                    errors.append(_scan_error_message(entry_path, "mount_skipped", decision.reason))
                skipped_row = _skipped_directory_row(
                    path_raw=entry_path,
                    parent_path=frame.path_raw,
                    depth=frame.depth + 1,
                    error=decision.reason,
                )
                rows.append(skipped_row)
                _merge_child(frame, skipped_row)
                continue

            mount_info = find_mount_for_path(entry_path, mounts) if mounts else None
            stack.append(
                _Frame(
                    path_raw=entry_path,
                    parent_path=frame.path_raw,
                    depth=frame.depth + 1,
                    initial_stat=entry_stat,
                    mount_id=mount_info.mount_id if mount_info else frame.mount_id,
                    mount_signature=_mount_signature(mount_info) or frame.mount_signature,
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
            _record_folded_evidence(frame, error.kind)
            frame.error = frame.error or error.message
            had_failure = True
            frame.entries = []
            frame.next_index = 0
            continue

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


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


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
        depth=row.depth,
        apparent_bytes=row.apparent_bytes,
        disk_bytes=row.disk_bytes,
        file_count=row.file_count,
        dir_count=row.dir_count,
        error=row.error,
        collapsed=row.collapsed,
        collapse_reason=row.collapse_reason,
        collapsed_dirs=row.collapsed_dirs,
        top_child_path=row.top_child_path,
        top_child_disk_bytes=row.top_child_disk_bytes,
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


def should_descend(
    *,
    path_raw: bytes,
    stat_result: os.stat_result | object,
    root_device: int,
    mount_info: MountInfo | None,
    mount_policy: MountPolicy | None,
    current_mount_id: int | None,
    current_mount_signature: tuple[str, bytes, bytes] | None,
    active_mount_ids: frozenset[int],
    active_mount_signatures: frozenset[tuple[str, bytes, bytes]],
    active_directory_keys: frozenset[tuple[int, int]],
) -> MountDecision:
    resolved_policy = mount_policy if isinstance(mount_policy, MountPolicy) else MountPolicy()
    decision = classify_mount(mount_info, resolved_policy)
    if not decision.include:
        return decision

    if resolved_policy.one_filesystem and stat_result.st_dev != root_device:
        return MountDecision(
            include=False,
            reason=(
                "separate filesystem skipped by one-filesystem policy "
                f"(root st_dev {root_device}, child st_dev {stat_result.st_dev})"
            ),
            filesystem_type=decision.filesystem_type,
            mount_id=decision.mount_id,
            device_changed=True,
        )

    mount_signature = _mount_signature(mount_info)
    if mount_info is not None and (
        mount_info.mount_id != current_mount_id or mount_signature != current_mount_signature
    ):
        if mount_info.mount_id in active_mount_ids:
            return MountDecision(
                include=False,
                reason=f"bind mount cycle detected for mount_id {mount_info.mount_id}",
                filesystem_type=mount_info.filesystem_type,
                mount_id=mount_info.mount_id,
                device_changed=False,
            )
        if mount_signature is not None and mount_signature in active_mount_signatures:
            return MountDecision(
                include=False,
                reason=f"bind mount cycle detected for mount_id {mount_info.mount_id}",
                filesystem_type=mount_info.filesystem_type,
                mount_id=mount_info.mount_id,
                device_changed=False,
            )

    directory_identity = inode_key(stat_result)
    if directory_identity in active_directory_keys:
        return MountDecision(
            include=False,
            reason=f"bind mount cycle detected for device/inode {directory_identity[0]}:{directory_identity[1]}",
            filesystem_type=mount_info.filesystem_type if mount_info else None,
            mount_id=mount_info.mount_id if mount_info else None,
            device_changed=False,
        )

    return decision


def _directory_row(frame: _Frame) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=0,
        path=frame.path_raw,
        parent_path=frame.parent_path,
        depth=frame.depth,
        apparent_bytes=frame.apparent_bytes,
        disk_bytes=frame.disk_bytes,
        file_count=frame.file_count,
        dir_count=frame.dir_count,
        error=frame.error,
    )


def _collapsed_directory_row(frame: _Frame, *, collapse_reason: str) -> DirectoryAggregate:
    error = _collapsed_evidence_summary(frame.folded_evidence_counts) or frame.error
    return DirectoryAggregate(
        snapshot_id=0,
        path=frame.path_raw,
        parent_path=frame.parent_path,
        depth=frame.depth,
        apparent_bytes=frame.apparent_bytes,
        disk_bytes=frame.disk_bytes,
        file_count=frame.file_count,
        dir_count=frame.dir_count,
        error=error,
        collapsed=True,
        collapse_reason=collapse_reason,
        collapsed_dirs=frame.dir_count,
        top_child_path=frame.top_child_path,
        top_child_disk_bytes=frame.top_child_disk_bytes,
    )


def _skipped_directory_row(*, path_raw: bytes, parent_path: bytes | None, depth: int, error: str) -> DirectoryAggregate:
    return DirectoryAggregate(
        snapshot_id=0,
        path=path_raw,
        parent_path=parent_path,
        depth=depth,
        apparent_bytes=0,
        disk_bytes=0,
        file_count=0,
        dir_count=0,
        error=error,
    )


def _disk_bytes_for_entry(
    stat_result: os.stat_result,
    seen_inodes: set[tuple[int, int]],
    max_entries: int,
    entry_path: bytes,
) -> tuple[int, bool]:
    if not stat.S_ISREG(stat_result.st_mode):
        return disk_bytes_from_stat(stat_result), False

    if stat_result.st_nlink <= 1:
        return disk_bytes_from_stat(stat_result), False

    key = inode_key(stat_result)
    if key in seen_inodes:
        return 0, True

    if len(seen_inodes) >= max_entries:
        raise _HardlinkLimitExceeded(
            _scan_error_message(
                entry_path,
                "hardlink_limit",
                f"hardlink dedup entry limit exceeded at {max_entries} inode keys",
            )
        )

    seen_inodes.add(key)
    return disk_bytes_from_stat(stat_result), True


def _merge_child(
    parent: _Frame,
    child_row: DirectoryAggregate,
    *,
    child_evidence_counts: dict[str, int] | None = None,
) -> None:
    parent.apparent_bytes += child_row.apparent_bytes
    parent.disk_bytes += child_row.disk_bytes
    parent.file_count += child_row.file_count
    parent.dir_count += child_row.dir_count + 1
    if parent.top_child_disk_bytes is None or child_row.disk_bytes > parent.top_child_disk_bytes:
        parent.top_child_path = child_row.path
        parent.top_child_disk_bytes = child_row.disk_bytes
    if child_evidence_counts is not None:
        _merge_evidence_counts(parent.folded_evidence_counts, child_evidence_counts)


def _is_excluded(path_raw: bytes, exclude_paths: tuple[bytes, ...]) -> bool:
    for excluded in exclude_paths:
        if path_raw == excluded:
            return True
        if excluded == PATH_SEPARATOR:
            return True
        if path_raw.startswith(excluded + PATH_SEPARATOR):
            return True
    return False


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


def _mount_signature(mount_info: MountInfo | None) -> tuple[str, bytes, bytes] | None:
    if mount_info is None:
        return None
    return (mount_info.major_minor, mount_info.root, mount_info.mount_point)


def _initial_collapse_reason(
    *,
    path_raw: bytes,
    collapse_policy: CollapsePolicy | None,
    collapse_never_paths: tuple[bytes, ...],
) -> str | None:
    if collapse_policy is None or _is_protected_path(path_raw, collapse_never_paths):
        return None
    basename = os.fsdecode(path_raw.rsplit(PATH_SEPARATOR, 1)[-1])
    if basename in collapse_policy.names:
        return "known_noise"
    return None


def _is_protected_path(path_raw: bytes, protected_paths: tuple[bytes, ...]) -> bool:
    for protected_path in protected_paths:
        if _is_same_or_descendant(path_raw, protected_path):
            return True
        if _is_same_or_descendant(protected_path, path_raw):
            return True
    return False


def _is_same_or_descendant(path_raw: bytes, ancestor_raw: bytes) -> bool:
    if path_raw == ancestor_raw:
        return True
    if ancestor_raw == PATH_SEPARATOR:
        return path_raw.startswith(PATH_SEPARATOR)
    return path_raw.startswith(ancestor_raw + PATH_SEPARATOR)


def _record_folded_evidence(frame: _Frame, kind: str) -> None:
    frame.folded_evidence_counts[kind] = frame.folded_evidence_counts.get(kind, 0) + 1


def _merge_evidence_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for kind, count in source.items():
        target[kind] = target.get(kind, 0) + count


def _collapsed_evidence_summary(folded_evidence_counts: dict[str, int]) -> str | None:
    if not folded_evidence_counts:
        return None
    kinds = ",".join(
        f"{kind}:{folded_evidence_counts[kind]}"
        for kind in sorted(folded_evidence_counts)
    )
    total = sum(folded_evidence_counts.values())
    return f"collapsed_subtree_evidence total={total} kinds={kinds}"


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
