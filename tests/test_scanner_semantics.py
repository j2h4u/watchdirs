from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess

import pytest


DU_TOLERANCE_BYTES = 1024


def _scan_result(import_watchdirs_module, root: Path, **option_overrides):
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")
    options = models.ScannerOptions(
        root=root,
        exclude_paths=tuple(option_overrides.pop("exclude_paths", ())),
        mount_policy=option_overrides.pop("mount_policy", ()),
        record_skipped=option_overrides.pop("record_skipped", False),
        hardlink_dedup_max_entries=option_overrides.pop("hardlink_dedup_max_entries", 500000),
        **option_overrides,
    )
    return scanner.scan_root(options)


def _rows_by_path(rows) -> dict[bytes, object]:
    return {row.path: row for row in rows}


def _error_paths(errors) -> set[bytes]:
    return {error.path for error in errors}


def _make_nested_fixture(root: Path) -> tuple[Path, Path]:
    child = root / "child"
    grandchild = child / "grandchild"
    grandchild.mkdir(parents=True)
    (root / "root.txt").write_text("root-data", encoding="utf-8")
    (child / "child.txt").write_text("child-data", encoding="utf-8")
    (grandchild / "grandchild.txt").write_text("grandchild-data", encoding="utf-8")
    return child, grandchild


def _root_row(scan_result):
    return scan_result.rows[-1]


def test_recursive_rows_persisted(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    child, grandchild = _make_nested_fixture(root)

    scan_result = _scan_result(import_watchdirs_module, root)
    rows = _rows_by_path(scan_result.rows)

    assert tuple(row.depth for row in scan_result.rows) == (2, 1, 0)
    assert rows[os.fsencode(root)].parent_path is None
    assert rows[os.fsencode(root)].name == b"root"
    assert rows[os.fsencode(root)].file_count == 3
    assert rows[os.fsencode(root)].dir_count == 2

    assert rows[os.fsencode(child)].parent_path == os.fsencode(root)
    assert rows[os.fsencode(child)].name == b"child"
    assert rows[os.fsencode(child)].file_count == 2
    assert rows[os.fsencode(child)].dir_count == 1

    assert rows[os.fsencode(grandchild)].parent_path == os.fsencode(child)
    assert rows[os.fsencode(grandchild)].name == b"grandchild"
    assert rows[os.fsencode(grandchild)].file_count == 1
    assert rows[os.fsencode(grandchild)].dir_count == 0


def test_non_utf8_paths_round_trip_through_scanner_and_sqlite(import_watchdirs_module, tmp_path: Path) -> None:
    connection_module = import_watchdirs_module("watchdirs.db.connection")
    migrations = import_watchdirs_module("watchdirs.db.migrations")

    root = tmp_path / "root"
    root.mkdir()
    bad_dir = os.fsencode(root) + b"/bad-\xff-dir"
    bad_file = bad_dir + b"/name-\xfe.bin"
    os.mkdir(bad_dir)
    fd = os.open(bad_file, os.O_CREAT | os.O_WRONLY, 0o644)
    os.write(fd, b"payload")
    os.close(fd)

    scan_result = _scan_result(import_watchdirs_module, root)
    assert any(row.path == bad_dir for row in scan_result.rows)
    assert all(isinstance(row.path, bytes) for row in scan_result.rows)

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    try:
        migrations.initialize_database(connection)
        persisted_rows = tuple(
            type(row)(
                snapshot_id=1,
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
            for row in scan_result.rows
        )
        migrations.insert_directory_rows(connection, persisted_rows)

        stored_paths = {
            row["path"]
            for row in connection.execute("SELECT path FROM directory_sizes ORDER BY id")
        }
    finally:
        connection.close()

    assert bad_dir in stored_paths
    assert {type(path) for path in stored_paths} == {bytes}
    assert all(error.path_bytes_hex for error in scan_result.errors if error.path == bad_dir)


def test_iterative_postorder_handles_deep_tree_depth_1500(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    current = root
    for _ in range(1500):
        current = current / "d"
        current.mkdir()

    scan_result = _scan_result(import_watchdirs_module, root)

    assert scan_result.row_count == 1501
    assert scan_result.rows[0].depth == 1500
    assert scan_result.rows[-1].depth == 0
    assert tuple(row.depth for row in scan_result.rows[:5]) == (1500, 1499, 1498, 1497, 1496)


def test_disk_bytes_match_du_for_fixture(import_watchdirs_module, tmp_path: Path) -> None:
    if shutil.which("du") is None:
        pytest.skip("du is not available")

    root = tmp_path / "root"
    root.mkdir()
    _make_nested_fixture(root)
    (root / "sparse.bin").write_bytes(b"x" * 8192)

    scan_result = _scan_result(import_watchdirs_module, root)
    root_row = _root_row(scan_result)

    du_result = subprocess.run(
        ["du", "-skx", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert du_result.returncode == 0, du_result.stderr
    du_bytes = int(du_result.stdout.split()[0]) * 1024
    tolerance = DU_TOLERANCE_BYTES * max(1, root_row.dir_count + 1)

    assert abs(root_row.disk_bytes - du_bytes) <= tolerance


def test_apparent_bytes_use_st_size_rules(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    regular = root / "regular.txt"
    regular.write_bytes(b"abcdef")
    symlink = root / "regular-link"
    symlink.symlink_to(regular.name)
    fifo = root / "named-pipe"
    os.mkfifo(fifo)
    socket_path = root / "unix.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    try:
        scan_result = _scan_result(import_watchdirs_module, root)
    finally:
        server.close()

    root_row = _root_row(scan_result)
    root_stat = os.lstat(root)
    regular_stat = os.lstat(regular)
    symlink_stat = os.lstat(symlink)

    expected_apparent = root_stat.st_size + regular_stat.st_size + symlink_stat.st_size
    expected_disk = (root_stat.st_blocks + regular_stat.st_blocks + symlink_stat.st_blocks) * 512

    assert root_row.apparent_bytes == expected_apparent
    assert root_row.disk_bytes == expected_disk
    assert root_row.file_count == 4


def test_symlink_targets_not_descended(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_text("outside-data", encoding="utf-8")
    symlink = root / "outside-link"
    symlink.symlink_to(outside, target_is_directory=True)

    scan_result = _scan_result(import_watchdirs_module, root)
    root_row = _root_row(scan_result)

    assert root_row.file_count == 1
    assert root_row.dir_count == 0
    assert all(row.path != os.fsencode(outside) for row in scan_result.rows)


def test_hardlinks_dedup_disk_bytes(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = root / "first.bin"
    first.write_bytes(b"hardlink-data")
    second = root / "second.bin"
    os.link(first, second)

    scan_result = _scan_result(import_watchdirs_module, root)
    root_row = _root_row(scan_result)
    root_stat = os.lstat(root)
    file_stat = os.lstat(first)

    assert root_row.file_count == 2
    assert root_row.disk_bytes == root_stat.st_blocks * 512 + file_stat.st_blocks * 512


def test_hardlink_dedup_resource_limit_records_error(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "first.bin").write_bytes(b"first")
    (root / "second.bin").write_bytes(b"second")

    scan_result = _scan_result(import_watchdirs_module, root, hardlink_dedup_max_entries=1)

    assert scan_result.status.value in {"partial", "failed"}
    assert any(error.kind == "hardlink_limit" for error in scan_result.errors)


def test_exclude_paths_are_pruned_and_recorded(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    included = root / "included"
    excluded = root / "excluded"
    included.mkdir()
    excluded.mkdir()
    (included / "kept.txt").write_text("keep", encoding="utf-8")
    (excluded / "skip.txt").write_text("skip", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        exclude_paths=(excluded,),
        record_skipped=True,
    )

    rows = _rows_by_path(scan_result.rows)
    root_row = _root_row(scan_result)

    assert scan_result.status.value == "complete"
    assert os.fsencode(excluded) not in rows
    assert root_row.file_count == 1
    assert any(error.kind == "excluded" and error.path == os.fsencode(excluded) for error in scan_result.errors)


def test_permission_error_marks_partial_row(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    restricted = root / "restricted"
    restricted.mkdir()
    (restricted / "secret.txt").write_text("secret", encoding="utf-8")

    restricted.chmod(0)
    try:
        if os.geteuid() == 0 or os.access(restricted, os.R_OK | os.X_OK):
            pytest.skip("platform/user can still traverse chmod 000 directories")

        scan_result = _scan_result(import_watchdirs_module, root)
    finally:
        restricted.chmod(0o755)

    rows = _rows_by_path(scan_result.rows)

    assert scan_result.status.value == "partial"
    assert scan_result.row_count >= 1
    assert (
        os.fsencode(restricted) in _error_paths(scan_result.errors)
        or rows.get(os.fsencode(restricted), None) is not None and rows[os.fsencode(restricted)].error
    )
