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


def _collapse_policy(
    import_watchdirs_module,
    *,
    names: frozenset[str] | None = None,
    fan_out: int = 500,
    descendants: int = 10000,
    never: tuple[Path, ...] = (),
):
    models = import_watchdirs_module("watchdirs.models")
    return models.CollapsePolicy(
        names=frozenset() if names is None else names,
        fan_out=fan_out,
        descendants=descendants,
        never=never,
    )


def test_recursive_rows_persisted(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    child, grandchild = _make_nested_fixture(root)

    scan_result = _scan_result(import_watchdirs_module, root)
    rows = _rows_by_path(scan_result.rows)

    assert tuple(row.depth for row in scan_result.rows) == (2, 1, 0)
    assert rows[os.fsencode(root)].parent_path is None
    assert rows[os.fsencode(root)].file_count == 3
    assert rows[os.fsencode(root)].dir_count == 2

    assert rows[os.fsencode(child)].parent_path == os.fsencode(root)
    assert rows[os.fsencode(child)].file_count == 2
    assert rows[os.fsencode(child)].dir_count == 1

    assert rows[os.fsencode(grandchild)].parent_path == os.fsencode(child)
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
        migrations.create_snapshot(connection, root)
        persisted_rows = tuple(
            type(row)(
                snapshot_id=1,
                path=row.path,
                parent_path=row.parent_path,
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
            for row in connection.execute(
                "SELECT p.path AS path FROM directory_sizes ds "
                "JOIN paths p ON p.id = ds.path_id ORDER BY ds.id"
            )
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


def test_symlink_root_is_rejected_without_following_target(import_watchdirs_module, tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    (real_root / "payload.txt").write_text("payload", encoding="utf-8")
    symlink_root = tmp_path / "link-root"
    symlink_root.symlink_to(real_root, target_is_directory=True)

    scan_result = _scan_result(import_watchdirs_module, symlink_root)

    assert scan_result.status.value == "failed"
    assert scan_result.row_count == 0
    assert scan_result.root_path == symlink_root
    assert all(row.path != os.fsencode(real_root) for row in scan_result.rows)
    assert any(error.kind == "symlink_root" and error.path == os.fsencode(symlink_root) for error in scan_result.errors)


def test_root_with_symlinked_ancestor_is_rejected_without_following_target(
    import_watchdirs_module,
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-root"
    nested_root = real_root / "nested"
    nested_root.mkdir(parents=True)
    (nested_root / "payload.txt").write_text("payload", encoding="utf-8")
    ancestor_link = tmp_path / "link-root"
    ancestor_link.symlink_to(real_root, target_is_directory=True)
    rooted_through_symlink = ancestor_link / "nested"

    scan_result = _scan_result(import_watchdirs_module, rooted_through_symlink)

    assert scan_result.status.value == "failed"
    assert scan_result.row_count == 0
    assert scan_result.root_path == rooted_through_symlink
    assert all(row.path != os.fsencode(nested_root) for row in scan_result.rows)
    assert any(
        error.kind == "symlink_root" and error.path == os.fsencode(rooted_through_symlink)
        for error in scan_result.errors
    )


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
    first = root / "first.bin"
    first.write_bytes(b"first")
    os.link(first, root / "first-link.bin")
    second = root / "second.bin"
    second.write_bytes(b"second")
    os.link(second, root / "second-link.bin")

    scan_result = _scan_result(import_watchdirs_module, root, hardlink_dedup_max_entries=1)

    assert scan_result.status.value in {"partial", "failed"}
    assert any(error.kind == "hardlink_limit" for error in scan_result.errors)


def test_hardlink_dedup_limit_ignores_regular_files_without_links(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "first.bin").write_bytes(b"first")
    (root / "second.bin").write_bytes(b"second")

    scan_result = _scan_result(import_watchdirs_module, root, hardlink_dedup_max_entries=1)

    assert scan_result.status.value == "complete"
    assert not any(error.kind == "hardlink_limit" for error in scan_result.errors)


def test_hardlink_limit_preserves_root_row_and_error(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    child = root / "child"
    child.mkdir()
    first = child / "first.bin"
    first.write_bytes(b"first")
    os.link(first, child / "first-link.bin")
    second = root / "second.bin"
    second.write_bytes(b"second")
    os.link(second, root / "second-link.bin")

    scan_result = _scan_result(import_watchdirs_module, root, hardlink_dedup_max_entries=1)
    rows = _rows_by_path(scan_result.rows)
    root_raw = os.fsencode(root)
    child_raw = os.fsencode(child)

    assert scan_result.status.value == "partial"
    assert root_raw in rows
    assert child_raw in rows
    assert rows[root_raw].error
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


def test_known_noise_directory_collapses_into_one_boundary_row(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    collapsed_dir = root / "node_modules"
    larger_child = collapsed_dir / "large-package"
    nested_child = larger_child / "nested"
    smaller_child = collapsed_dir / "small-package"
    nested_child.mkdir(parents=True)
    smaller_child.mkdir(parents=True)
    (nested_child / "payload.bin").write_bytes(b"x" * 8192)
    (smaller_child / "payload.txt").write_text("small", encoding="utf-8")

    expanded_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module),
    )
    collapsed_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, names=frozenset({"node_modules"})),
    )

    expanded_rows = _rows_by_path(expanded_result.rows)
    collapsed_rows = _rows_by_path(collapsed_result.rows)
    collapsed_path = os.fsencode(collapsed_dir)

    assert collapsed_rows[collapsed_path].collapsed is True
    assert collapsed_rows[collapsed_path].collapse_reason == "known_noise"
    assert collapsed_rows[collapsed_path].collapsed_dirs == 3
    assert collapsed_rows[collapsed_path].top_child_path == os.fsencode(larger_child)
    assert collapsed_rows[collapsed_path].top_child_disk_bytes == expanded_rows[os.fsencode(larger_child)].disk_bytes
    assert collapsed_rows[collapsed_path].apparent_bytes == expanded_rows[collapsed_path].apparent_bytes
    assert collapsed_rows[collapsed_path].disk_bytes == expanded_rows[collapsed_path].disk_bytes
    assert collapsed_rows[collapsed_path].file_count == expanded_rows[collapsed_path].file_count
    assert collapsed_rows[collapsed_path].dir_count == expanded_rows[collapsed_path].dir_count
    assert os.fsencode(larger_child) not in collapsed_rows
    assert os.fsencode(nested_child) not in collapsed_rows
    assert os.fsencode(smaller_child) not in collapsed_rows
    assert _root_row(collapsed_result).apparent_bytes == _root_row(expanded_result).apparent_bytes
    assert _root_row(collapsed_result).disk_bytes == _root_row(expanded_result).disk_bytes
    assert _root_row(collapsed_result).file_count == _root_row(expanded_result).file_count
    assert _root_row(collapsed_result).dir_count == _root_row(expanded_result).dir_count


def test_shallowest_qualifying_directory_wins(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    parent = root / "cache"
    child = parent / "cache"
    grandchild = child / "leaf"
    grandchild.mkdir(parents=True)
    (grandchild / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, names=frozenset({"cache"})),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(parent)].collapsed is True
    assert rows[os.fsencode(parent)].collapse_reason == "known_noise"
    assert os.fsencode(child) not in rows
    assert os.fsencode(grandchild) not in rows


def test_never_listed_known_noise_subtree_stays_expanded(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    protected = root / "protected" / "node_modules"
    nested = protected / "pkg"
    nested.mkdir(parents=True)
    (nested / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(
            import_watchdirs_module,
            names=frozenset({"node_modules"}),
            never=(protected,),
        ),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(protected)].collapsed is False
    assert os.fsencode(nested) in rows


def test_protected_descendant_blocks_ancestor_collapse(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    blocked = root / "cache"
    protected = blocked / "data" / "protected"
    allowed = root / "other" / "cache"
    (protected / "payload.txt").parent.mkdir(parents=True)
    (protected / "payload.txt").write_text("protected", encoding="utf-8")
    (allowed / "pkg").mkdir(parents=True)
    (allowed / "pkg" / "payload.txt").write_text("allowed", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(
            import_watchdirs_module,
            names=frozenset({"cache"}),
            never=(protected,),
        ),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(blocked)].collapsed is False
    assert os.fsencode(blocked / "data") in rows
    assert os.fsencode(protected) in rows
    assert rows[os.fsencode(allowed)].collapsed is True


def test_never_matching_uses_path_components(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    protected = root / "cache" / "data"
    similar = root / "cache" / "database"
    (protected / "keep.txt").parent.mkdir(parents=True)
    (protected / "keep.txt").write_text("protected", encoding="utf-8")
    (similar / "pkg").mkdir(parents=True)
    (similar / "pkg" / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(
            import_watchdirs_module,
            names=frozenset({"database"}),
            never=(protected,),
        ),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(protected)].collapsed is False
    assert rows[os.fsencode(similar)].collapsed is True


def test_fan_out_collapse_triggers_at_threshold_equality(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    collapsed_dir = root / "fanout"
    for index in range(3):
        child = collapsed_dir / f"child-{index}"
        child.mkdir(parents=True)
        (child / "payload.txt").write_text(f"payload-{index}", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, fan_out=3, descendants=99),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(collapsed_dir)].collapsed is True
    assert rows[os.fsencode(collapsed_dir)].collapse_reason == "fan_out"
    assert rows[os.fsencode(collapsed_dir)].collapsed_dirs == 3
    assert os.fsencode(collapsed_dir / "child-0") not in rows


def test_descendant_count_collapse_triggers_at_threshold_equality(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    branch = root / "deep"
    nested = branch / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, fan_out=99, descendants=2),
    )
    rows = _rows_by_path(scan_result.rows)
    collapsed_row = _root_row(scan_result)

    assert collapsed_row.collapsed is True
    assert collapsed_row.collapse_reason == "descendant_count"
    assert collapsed_row.collapsed_dirs == 3
    assert os.fsencode(branch) not in rows
    assert os.fsencode(branch / "one") not in rows
    assert os.fsencode(nested) not in rows


def test_depth_alone_never_triggers_collapse(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    current = root / "deep"
    for _ in range(5):
        current.mkdir(parents=True, exist_ok=True)
        (current / "payload.txt").write_text("payload", encoding="utf-8")
        current = current / "next"

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, fan_out=99, descendants=10),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(root / "deep")].collapsed is False
    assert os.fsencode(root / "deep" / "next" / "next") in rows


def test_known_noise_reason_takes_precedence_over_other_triggers(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "node_modules"
    for index in range(2):
        child = root / f"child-{index}"
        child.mkdir(parents=True)
        (child / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(
            import_watchdirs_module,
            names=frozenset({"node_modules"}),
            fan_out=1,
            descendants=1,
        ),
    )

    assert _root_row(scan_result).collapse_reason == "known_noise"


def test_protected_descendants_block_fan_out_and_descendant_count(import_watchdirs_module, tmp_path: Path) -> None:
    root = tmp_path / "root"
    fanout = root / "fanout"
    fanout_protected = fanout / "child-0" / "protected"
    (fanout_protected / "payload.txt").parent.mkdir(parents=True)
    (fanout_protected / "payload.txt").write_text("payload", encoding="utf-8")
    (fanout / "child-1").mkdir(parents=True)

    descendant = root / "descendant"
    descendant_protected = descendant / "one" / "two" / "protected"
    descendant_protected.mkdir(parents=True)
    (descendant_protected / "payload.txt").write_text("payload", encoding="utf-8")

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(
            import_watchdirs_module,
            fan_out=2,
            descendants=2,
            never=(root, fanout_protected, descendant_protected),
        ),
    )
    rows = _rows_by_path(scan_result.rows)

    assert rows[os.fsencode(fanout)].collapsed is False
    assert rows[os.fsencode(descendant)].collapsed is False


def test_collapsed_boundary_surfaces_folded_evidence_summary(
    import_watchdirs_module,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")

    root = tmp_path / "root"
    collapsed_dir = root / "node_modules"
    healthy = collapsed_dir / "healthy"
    denied = collapsed_dir / "denied"
    skipped = collapsed_dir / "skipped"
    healthy.mkdir(parents=True)
    denied.mkdir(parents=True)
    skipped.mkdir(parents=True)
    (healthy / "payload.txt").write_text("healthy", encoding="utf-8")
    (denied / "payload.txt").write_text("denied", encoding="utf-8")
    (skipped / "payload.txt").write_text("skipped", encoding="utf-8")

    original_sorted_entries = scanner._sorted_entries
    original_should_descend = scanner.should_descend

    def fake_sorted_entries(path_raw: bytes):
        if path_raw == os.fsencode(denied):
            raise PermissionError("permission denied for fixture")
        return original_sorted_entries(path_raw)

    def fake_should_descend(**kwargs):
        if kwargs["path_raw"] == os.fsencode(skipped):
            return models.MountDecision(
                include=False,
                reason="fixture skip",
                filesystem_type=None,
                mount_id=None,
                device_changed=False,
            )
        return original_should_descend(**kwargs)

    monkeypatch.setattr(scanner, "_sorted_entries", fake_sorted_entries)
    monkeypatch.setattr(scanner, "should_descend", fake_should_descend)

    scan_result = _scan_result(
        import_watchdirs_module,
        root,
        collapse_policy=_collapse_policy(import_watchdirs_module, names=frozenset({"node_modules"})),
        record_skipped=True,
    )
    rows = _rows_by_path(scan_result.rows)
    collapsed_row = rows[os.fsencode(collapsed_dir)]

    assert collapsed_row.collapsed is True
    assert collapsed_row.error == "collapsed_subtree_evidence total=2 kinds=mount_skipped:1,permission_denied:1"
    assert os.fsencode(healthy) not in rows
    assert os.fsencode(denied) not in rows
    assert os.fsencode(skipped) not in rows
    assert str(denied) not in collapsed_row.error
    assert str(skipped) not in collapsed_row.error
    assert _error_paths(scan_result.errors) >= {os.fsencode(denied), os.fsencode(skipped)}
