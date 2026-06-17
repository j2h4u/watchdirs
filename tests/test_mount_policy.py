# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

from conftest import DirectoryAggregateLike, ScanResultLike

PSEUDO_FILESYSTEMS = (
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "tmpfs",
    "cgroup2",
    "pstore",
    "securityfs",
    "debugfs",
    "tracefs",
    "configfs",
    "fusectl",
    "nsfs",
)


def _escape_mount_path(path: Path | str) -> str:
    value = str(path)
    return value.replace("\\", "\\134").replace(" ", "\\040").replace("\n", "\\012").replace("\t", "\\011")


def _mountinfo_line(
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: Path | str,
    mount_point: Path | str,
    filesystem_type: str,
    mount_source: str,
    options: str = "rw",
    super_options: str = "rw",
) -> str:
    return (
        f"{mount_id} {parent_id} {major_minor} {_escape_mount_path(root)} "
        f"{_escape_mount_path(mount_point)} {options} - "
        f"{filesystem_type} {mount_source} {super_options}"
    )


def _dir_stat(*, st_dev: int, st_ino: int) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o755,
        st_dev=st_dev,
        st_ino=st_ino,
        st_nlink=1,
        st_size=0,
        st_blocks=0,
    )


class _FakeEntry:
    def __init__(self, path_raw: bytes, stat_result: SimpleNamespace) -> None:
        self.path = path_raw
        self._stat_result = stat_result

    def stat(self, *, follow_symlinks: bool = False) -> SimpleNamespace:
        assert follow_symlinks is False
        return self._stat_result


def _scan_result(import_watchdirs_module, root: Path, **option_overrides) -> ScanResultLike:
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")
    options = models.ScannerOptions(
        root=root,
        exclude_paths=tuple(option_overrides.pop("exclude_paths", ())),
        mounts=tuple(option_overrides.pop("mounts", ())),
        mount_policy=option_overrides.pop("mount_policy", models.MountPolicy()),
        record_skipped=option_overrides.pop("record_skipped", True),
        hardlink_dedup_max_entries=option_overrides.pop("hardlink_dedup_max_entries", 500000),
        **option_overrides,
    )
    return scanner.scan_root(options)


def _rows_by_path(rows: tuple[DirectoryAggregateLike, ...]) -> dict[bytes, DirectoryAggregateLike]:
    return {row.path: row for row in rows}


def test_parse_mountinfo_extracts_filesystem_type_and_mountpoint(import_watchdirs_module) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")

    parsed = mounts.parse_mountinfo(
        _mountinfo_line(
            mount_id=29,
            parent_id=24,
            major_minor="0:42",
            root="/",
            mount_point="/tmp/with space",
            filesystem_type="tmpfs",
            mount_source="tmpfs",
            options="rw,nosuid,nodev",
            super_options="rw,size=1024k,inode64",
        )
        + "\n"
    )

    assert len(parsed) == 1
    mount = parsed[0]
    assert mount.mount_id == 29
    assert mount.parent_id == 24
    assert mount.major_minor == "0:42"
    assert mount.root == b"/"
    assert mount.mount_point == b"/tmp/with space"
    assert mount.options == ("rw", "nosuid", "nodev")
    assert mount.filesystem_type == "tmpfs"
    assert mount.mount_source == "tmpfs"
    assert mount.super_options == ("rw", "size=1024k", "inode64")


def test_unescape_mount_path_handles_octal_space_backslash_newline_and_tab(import_watchdirs_module) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")

    assert mounts.unescape_mount_path(r"/tmp/with\040space\134slash\012line\011tab") == (
        b"/tmp/with space\\slash\nline\ttab"
    )


def test_skip_default_pseudo_filesystems(import_watchdirs_module) -> None:
    classify = import_watchdirs_module("watchdirs.collect.classify")
    models = import_watchdirs_module("watchdirs.models")

    for filesystem_type in PSEUDO_FILESYSTEMS:
        mount = models.MountInfo(
            mount_id=10,
            parent_id=1,
            major_minor="0:10",
            root=b"/",
            mount_point=b"/candidate",
            options=("rw",),
            filesystem_type=filesystem_type,
            mount_source=filesystem_type,
            super_options=("rw",),
        )
        decision = classify.classify_mount(mount)
        assert decision.include is False
        assert decision.filesystem_type == filesystem_type
        assert decision.mount_id == 10

    tmpfs_mount = models.MountInfo(
        mount_id=11,
        parent_id=1,
        major_minor="0:11",
        root=b"/",
        mount_point=b"/tmp",
        options=("rw",),
        filesystem_type="tmpfs",
        mount_source="tmpfs",
        super_options=("rw",),
    )
    included = classify.classify_mount(
        tmpfs_mount,
        policy=models.MountPolicy(included_filesystems=frozenset({"tmpfs"})),
    )
    assert included.include is True


def test_skip_overlay_and_nsfs(import_watchdirs_module) -> None:
    classify = import_watchdirs_module("watchdirs.collect.classify")
    models = import_watchdirs_module("watchdirs.models")

    for mount_id, filesystem_type in ((21, "overlay"), (22, "nsfs")):
        decision = classify.classify_mount(
            models.MountInfo(
                mount_id=mount_id,
                parent_id=1,
                major_minor="0:21",
                root=b"/",
                mount_point=b"/container",
                options=("rw",),
                filesystem_type=filesystem_type,
                mount_source=filesystem_type,
                super_options=("rw",),
            )
        )
        assert decision.include is False
        assert filesystem_type in decision.reason


def test_scanner_does_not_descend_into_skipped_mount(import_watchdirs_module, tmp_path: Path) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")

    root = tmp_path / "root"
    child_mount = root / "overlay-cache"
    nested = child_mount / "hidden"
    nested.mkdir(parents=True)
    (nested / "payload.txt").write_text("payload", encoding="utf-8")

    mount_table = mounts.parse_mountinfo(
        "\n".join((
            _mountinfo_line(
                mount_id=1,
                parent_id=0,
                major_minor="8:1",
                root="/",
                mount_point=root,
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mountinfo_line(
                mount_id=2,
                parent_id=1,
                major_minor="0:77",
                root="/",
                mount_point=child_mount,
                filesystem_type="overlay",
                mount_source="overlay",
            ),
        ))
        + "\n"
    )

    scan_result = _scan_result(import_watchdirs_module, root, mounts=mount_table)
    rows = _rows_by_path(scan_result.rows)

    assert os.fsencode(child_mount) in rows
    child_error = rows[os.fsencode(child_mount)].error
    assert child_error is not None
    assert b"overlay" in child_error.encode()
    assert os.fsencode(nested) not in rows
    assert rows[os.fsencode(root)].dir_count == 1
    assert scan_result.status.value == "complete"


def test_scanner_stops_at_st_dev_boundary_in_one_filesystem_mode(
    import_watchdirs_module, monkeypatch, tmp_path: Path
) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")

    root = tmp_path / "root"
    child_mount = root / "other-fs"
    child_mount.mkdir(parents=True)
    root_raw = os.fsencode(root)
    child_raw = os.fsencode(child_mount)
    root_stat = _dir_stat(st_dev=100, st_ino=1)
    child_stat = _dir_stat(st_dev=200, st_ino=2)
    original_stat = os.stat

    def fake_stat(path_raw: bytes, *, follow_symlinks: bool = False):
        if not isinstance(path_raw, bytes):
            return original_stat(path_raw, follow_symlinks=follow_symlinks)
        assert follow_symlinks is False
        if path_raw == root_raw:
            return root_stat
        raise AssertionError(f"pruned child should not be initialized: {path_raw!r}")

    def fake_sorted_entries(path_raw: bytes):
        if path_raw == root_raw:
            return [_FakeEntry(child_raw, child_stat)]
        raise AssertionError(f"unexpected scandir for pruned child: {path_raw!r}")

    monkeypatch.setattr(scanner.os, "stat", fake_stat)
    monkeypatch.setattr(scanner, "_sorted_entries", fake_sorted_entries)

    mount_table = mounts.parse_mountinfo(
        _mountinfo_line(
            mount_id=1,
            parent_id=0,
            major_minor="8:1",
            root="/",
            mount_point=root,
            filesystem_type="ext4",
            mount_source="/dev/root",
        )
        + "\n"
    )

    scan_result = _scan_result(import_watchdirs_module, root, mounts=mount_table)
    rows = _rows_by_path(scan_result.rows)

    assert os.fsencode(child_mount) in rows
    assert rows[os.fsencode(child_mount)].error is not None
    child_error = rows[os.fsencode(child_mount)].error
    assert child_error is not None
    assert "filesystem" in child_error
    assert rows[os.fsencode(root)].dir_count == 1
    assert scan_result.status.value == "complete"


def test_explicit_additional_root_allows_separate_filesystem_coverage(
    import_watchdirs_module, monkeypatch, tmp_path: Path
) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")

    root = tmp_path / "root"
    child_mount = root / "separate-fs"
    child_mount.mkdir(parents=True)
    root_raw = os.fsencode(root)
    child_raw = os.fsencode(child_mount)
    root_stat = _dir_stat(st_dev=100, st_ino=1)
    child_stat = _dir_stat(st_dev=200, st_ino=2)
    original_stat = os.stat

    def fake_stat(path_raw: bytes, *, follow_symlinks: bool = False):
        if not isinstance(path_raw, bytes):
            return original_stat(path_raw, follow_symlinks=follow_symlinks)
        assert follow_symlinks is False
        if path_raw == root_raw:
            return root_stat
        if path_raw == child_raw:
            return child_stat
        raise AssertionError(f"unexpected path: {path_raw!r}")

    def fake_sorted_entries(path_raw: bytes):
        if path_raw == root_raw:
            return [_FakeEntry(child_raw, child_stat)]
        if path_raw == child_raw:
            return []
        raise AssertionError(f"unexpected scandir path: {path_raw!r}")

    monkeypatch.setattr(scanner.os, "stat", fake_stat)
    monkeypatch.setattr(scanner, "_sorted_entries", fake_sorted_entries)

    mount_table = mounts.parse_mountinfo(
        "\n".join((
            _mountinfo_line(
                mount_id=1,
                parent_id=0,
                major_minor="8:1",
                root="/",
                mount_point=root,
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mountinfo_line(
                mount_id=2,
                parent_id=1,
                major_minor="9:9",
                root="/",
                mount_point=child_mount,
                filesystem_type="xfs",
                mount_source="/dev/child",
            ),
        ))
        + "\n"
    )

    pruned = _scan_result(import_watchdirs_module, root, mounts=mount_table)
    direct = _scan_result(import_watchdirs_module, child_mount, mounts=mount_table)
    direct_rows = _rows_by_path(direct.rows)

    assert os.fsencode(child_mount) in _rows_by_path(pruned.rows)
    assert direct.status.value == "complete"
    assert direct.row_count == 1
    assert direct_rows[os.fsencode(child_mount)].error is None


def test_bind_mount_cycle_rejected_by_mount_id(import_watchdirs_module) -> None:
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")

    mount = models.MountInfo(
        mount_id=20,
        parent_id=10,
        major_minor="8:1",
        root=b"/srv/root",
        mount_point=b"/srv/root/loop",
        options=("rw",),
        filesystem_type="ext4",
        mount_source="/dev/root",
        super_options=("rw",),
    )

    decision = scanner.should_descend(
        path_raw=b"/srv/root/loop",
        stat_result=_dir_stat(st_dev=8, st_ino=200),
        root_device=8,
        mount_info=mount,
        mount_policy=models.MountPolicy(),
        current_mount_id=10,
        current_mount_signature=("8:1", b"/", b"/srv/root"),
        active_mount_ids=frozenset({10, 20}),
        active_mount_signatures=frozenset({("8:1", b"/srv/root", b"/srv/root/loop")}),
        active_directory_keys=frozenset(),
    )

    assert decision.include is False
    assert decision.mount_id == 20
    assert "cycle" in decision.reason
