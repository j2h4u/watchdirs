# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import DirectoryAggregateLike, MountInfoLike


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def test_reporting_state_relation_has_no_legacy_directory_sizes_reference(repo_root: Path) -> None:
    queries = import_module(repo_root, "watchdirs.reporting.queries")
    state_sql = queries._snapshot_state_cte()

    assert "directory_size_diagnostics" in state_sql
    assert "directory_sizes" not in state_sql


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    return connection, migrations_module, models_module


def _directory_row(
    models_module,
    snapshot_id: int,
    path: bytes,
    *,
    disk_bytes: int,
    apparent_bytes: int,
    depth: int,
    parent_path: bytes | None,
    file_count: int = 0,
    dir_count: int = 0,
    error: str | None = None,
    collapsed: bool = False,
    collapse_reason: str | None = None,
    collapsed_dirs: int | None = None,
    top_child_path: bytes | None = None,
    top_child_disk_bytes: int | None = None,
) -> DirectoryAggregateLike:
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=parent_path,
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
        collapsed=collapsed,
        collapse_reason=collapse_reason,
        collapsed_dirs=collapsed_dirs,
        top_child_path=top_child_path,
        top_child_disk_bytes=top_child_disk_bytes,
    )


def _mount(
    models_module,
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: bytes,
    mount_point: bytes,
    filesystem_type: str,
    mount_source: str,
) -> MountInfoLike:
    return models_module.MountInfo(
        mount_id=mount_id,
        parent_id=parent_id,
        major_minor=major_minor,
        root=root,
        mount_point=mount_point,
        options=("rw",),
        filesystem_type=filesystem_type,
        mount_source=mount_source,
        super_options=("rw",),
    )


def _seed_snapshot(
    connection,
    migrations_module,
    models_module,
    *,
    root_path: Path,
    status: str,
    started_at: str,
    finished_at: str,
    rows: list[DirectoryAggregateLike],
    mounts: list[MountInfoLike] | None = None,
    notes: str | None = None,
    error: str | None = None,
) -> int:
    snapshot = migrations_module.create_snapshot(connection, root_path, notes=notes)
    persisted_rows = [
        models_module.DirectoryAggregate(
            snapshot_id=snapshot.id,
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
        for row in rows
    ]
    if persisted_rows:
        migrations_module.insert_directory_rows(connection, persisted_rows, commit=False)
    if mounts:
        migrations_module.insert_snapshot_mounts(connection, snapshot.id, mounts, commit=False)
    migrations_module.finalize_snapshot(
        connection,
        snapshot.id,
        status=models_module.SnapshotStatus(status),
        notes=notes,
        error=error,
        commit=False,
    )
    connection.execute(
        "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
        (started_at, finished_at, snapshot.id),
    )
    connection.commit()
    return snapshot.id


def _textish(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return os.fsdecode(value)
    return str(value)


def _snapshot_pair(models_module, *, root_path: str, baseline_id: int, current_id: int):
    return models_module.SnapshotPair(
        root_path=Path(root_path),
        baseline=models_module.SnapshotRecord(
            id=baseline_id,
            started_at="2026-06-12T18:00:00Z",
            finished_at="2026-06-12T18:00:00Z",
            root_path=Path(root_path),
            status=models_module.SnapshotStatus.COMPLETE,
            notes=None,
            error=None,
        ),
        current=models_module.SnapshotRecord(
            id=current_id,
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            root_path=Path(root_path),
            status=models_module.SnapshotStatus.PARTIAL,
            notes=None,
            error="permission denied",
        ),
        warning_codes=("partial_snapshot",),
    )


def test_query_top_rows_orders_by_current_disk_bytes_and_keeps_apparent_size_separate(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1200,
                apparent_bytes=900,
                depth=0,
                parent_path=None,
                file_count=3,
                dir_count=3,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/tmp",
                disk_bytes=700,
                apparent_bytes=250,
                depth=1,
                parent_path=b"/srv",
                file_count=2,
                dir_count=0,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/var",
                disk_bytes=700,
                apparent_bytes=500,
                depth=1,
                parent_path=b"/srv",
                file_count=4,
                dir_count=1,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/log",
                disk_bytes=400,
                apparent_bytes=390,
                depth=1,
                parent_path=b"/srv",
                file_count=5,
                dir_count=0,
            ),
        ],
    )

    rows, warnings = queries.query_top_rows(connection, snapshot_id=snapshot_id, limit=4, group_by="root")

    assert warnings == ()
    assert [row.path for row in rows] == [b"/srv", b"/srv/tmp", b"/srv/var", b"/srv/log"]
    assert [row.current_disk_bytes for row in rows] == [1200, 700, 700, 400]
    assert rows[1].current_apparent_bytes == 250
    assert rows[2].current_apparent_bytes == 500
    assert rows[1].current_apparent_bytes != rows[1].current_disk_bytes
    assert rows[0].path_bytes_hex == b"/srv".hex()
    assert rows[0].root_path == Path("/srv")
    assert not hasattr(rows[0], "disk_bytes_delta")


def test_reporting_reads_pruned_interval_origins_and_preserves_reappearance_classification(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")
    pairs_module = import_module(repo_root, "watchdirs.reporting.pairs")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/reappear", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    middle_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T19:00:00Z",
        finished_at="2026-06-12T19:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T20:00:00Z",
        finished_at="2026-06-12T20:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=110, apparent_bytes=110, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/reappear", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    # Simulate retention removing the snapshot that opened the still-active
    # interval. The marker is deliberately not a snapshot FK in v7.
    connection.execute(
        "UPDATE directory_size_intervals SET valid_from_snapshot_id = 0 WHERE valid_from_snapshot_id = ?",
        (baseline_id,),
    )
    connection.commit()

    top_rows, top_warnings = queries.query_top_rows(connection, snapshot_id=current_id, limit=10, group_by="root")
    recent_pairs, pair_warnings = pairs_module.resolve_snapshot_pairs(connection, since="1h")
    recent_rows, diff_warnings = queries.query_diff_rows(connection, pair=recent_pairs[0], group_by="root")
    recent_classifications = {row.path: row.classification for row in recent_rows}
    full_pairs, _ = pairs_module.resolve_snapshot_pairs(connection, since="36h")
    full_rows, _ = queries.query_diff_rows(connection, pair=full_pairs[0], group_by="root")
    full_classifications = {row.path: row.classification for row in full_rows}

    assert top_warnings == ()
    assert pair_warnings == ()
    assert diff_warnings == ()
    assert [row.path for row in top_rows] == [b"/srv", b"/srv/reappear"]
    assert recent_pairs[0].baseline.id == middle_id
    assert recent_classifications[b"/srv/reappear"] == "created"
    assert full_classifications[b"/srv/gone"] == "deleted"


def test_query_top_rows_mount_and_storage_domain_grouping_use_persisted_snapshot_mounts(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:02:00Z",
        finished_at="2026-06-13T18:03:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv/archive",
                disk_bytes=800,
                apparent_bytes=650,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/log",
                disk_bytes=300,
                apparent_bytes=290,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/srv/archive",
                filesystem_type="xfs",
                mount_source="/dev/archive",
            ),
        ],
    )

    mount_rows, mount_warnings = queries.query_top_rows(
        connection,
        snapshot_id=snapshot_id,
        limit=2,
        group_by="mount",
    )
    storage_rows, storage_warnings = queries.query_top_rows(
        connection,
        snapshot_id=snapshot_id,
        limit=2,
        group_by="storage-domain",
    )

    assert mount_warnings == ()
    assert storage_warnings == ()
    assert mount_rows[0].group is not None
    assert mount_rows[0].group.kind == "mount"
    assert _textish(mount_rows[0].group.mount_point) == "/srv/archive"
    assert _textish(mount_rows[0].group.key) == "/srv/archive"
    assert storage_rows[0].group is not None
    assert storage_rows[0].group.kind == "storage-domain"
    assert storage_rows[0].group.key == "8:17|/|xfs|/dev/archive"
    assert _textish(storage_rows[0].group.mount_point) == "/srv/archive"
    assert storage_rows[0].group.filesystem_type == "xfs"
    assert storage_rows[0].group.mount_source == "/dev/archive"


def test_query_top_rows_top_level_subtree_groups_use_segment_boundaries_and_root_label(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/"),
        status="complete",
        started_at="2026-06-13T18:04:00Z",
        finished_at="2026-06-13T18:05:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/",
                disk_bytes=2000,
                apparent_bytes=1600,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                b"/var/log",
                disk_bytes=900,
                apparent_bytes=600,
                depth=2,
                parent_path=b"/var",
            ),
            _directory_row(
                models_module,
                1,
                b"/varlib/cache",
                disk_bytes=850,
                apparent_bytes=700,
                depth=2,
                parent_path=b"/varlib",
            ),
        ],
    )

    rows, warnings = queries.query_top_rows(
        connection,
        snapshot_id=snapshot_id,
        limit=3,
        group_by="top-level-subtree",
    )

    rows_by_path = {row.path: row for row in rows}
    assert warnings == ()
    assert rows_by_path[b"/"].group is not None
    assert rows_by_path[b"/"].group.kind == "top-level-subtree"
    assert rows_by_path[b"/"].group.key == "."
    assert rows_by_path[b"/var/log"].group is not None
    assert rows_by_path[b"/var/log"].group.key == "var"
    assert rows_by_path[b"/varlib/cache"].group is not None
    assert rows_by_path[b"/varlib/cache"].group.key == "varlib"


def test_query_top_rows_unknown_mount_rows_use_null_group_and_warning(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:06:00Z",
        finished_at="2026-06-13T18:07:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv/data",
                disk_bytes=700,
                apparent_bytes=600,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=900,
                apparent_bytes=850,
                depth=1,
                parent_path=b"/",
                error="outside persisted mount coverage",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=21,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
        error="permission denied",
    )

    mount_rows, mount_warnings = queries.query_top_rows(
        connection,
        snapshot_id=snapshot_id,
        limit=5,
        group_by="mount",
    )
    domain_rows, domain_warnings = queries.query_top_rows(
        connection,
        snapshot_id=snapshot_id,
        limit=5,
        group_by="storage-domain",
    )

    mystery_mount_row = next(row for row in mount_rows if row.path == b"/mystery")
    mystery_domain_row = next(row for row in domain_rows if row.path == b"/mystery")
    assert mystery_mount_row.group is None
    assert mystery_domain_row.group is None
    assert [warning.code for warning in mount_warnings] == ["path_outside_root"]
    assert [warning.code for warning in domain_warnings] == ["path_outside_root"]
    assert _textish(mount_warnings[0].path) == "/mystery"


def test_query_top_rows_outside_root_rows_warn_instead_of_fabricating_root_or_subtree_groups(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:06:00Z",
        finished_at="2026-06-13T18:07:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=900,
                apparent_bytes=850,
                depth=1,
                parent_path=b"/",
                error="outside snapshot root",
            ),
        ],
        error="permission denied",
    )

    connection.execute(
        """
        INSERT INTO snapshot_mounts (
            snapshot_id, mount_id, parent_id, major_minor, root,
            mount_point, filesystem_type, mount_source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            1,
            0,
            "0:99",
            b"/",
            b"/",
            "overlay",
            "rootfs",
        ),
    )
    connection.commit()

    for group_by in ("root", "top-level-subtree", "mount", "storage-domain"):
        rows, warnings = queries.query_top_rows(
            connection,
            snapshot_id=snapshot_id,
            limit=5,
            group_by=group_by,
        )

        assert rows[0].group is None
        assert [warning.code for warning in warnings] == ["path_outside_root"]
        assert _textish(warnings[0].path) == "/mystery"
        assert "not under snapshot root" in warnings[0].message


def test_query_top_rows_returns_collapsed_metadata_and_ordinary_row_defaults(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1600,
                apparent_bytes=1200,
                depth=0,
                parent_path=None,
                file_count=20,
                dir_count=5,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=900,
                apparent_bytes=650,
                depth=1,
                parent_path=b"/srv",
                file_count=12,
                dir_count=1200,
                error="collapsed_subtree_evidence total=2 kinds=mount_skipped:1,scan_error:1",
                collapsed=True,
                collapse_reason="fan_out",
                collapsed_dirs=1200,
                top_child_path=b"/srv/cache/node_modules",
                top_child_disk_bytes=640,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/log",
                disk_bytes=200,
                apparent_bytes=180,
                depth=1,
                parent_path=b"/srv",
                file_count=4,
                dir_count=0,
            ),
        ],
    )

    rows, warnings = queries.query_top_rows(connection, snapshot_id=snapshot_id, limit=3, group_by="root")

    assert warnings == ()
    rows_by_path = {row.path: row for row in rows}

    collapsed = rows_by_path[b"/srv/cache"]
    assert collapsed.collapsed is True
    assert collapsed.collapse_reason == "fan_out"
    assert collapsed.collapsed_dirs == 1200
    assert collapsed.top_child_path == b"/srv/cache/node_modules"
    assert collapsed.top_child_disk_bytes == 640
    assert isinstance(collapsed.top_child_path, bytes)

    ordinary = rows_by_path[b"/srv/log"]
    assert ordinary.collapsed is False
    assert ordinary.collapse_reason is None
    assert ordinary.collapsed_dirs is None
    assert ordinary.top_child_path is None
    assert ordinary.top_child_disk_bytes is None


def test_resolve_top_snapshot_selection_latest_returns_latest_usable_snapshot_per_root(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    alpha_complete = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-13T17:00:00Z",
        finished_at="2026-06-13T17:01:00Z",
        rows=[
            _directory_row(models_module, 1, b"/alpha", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="failed",
        started_at="2026-06-13T17:30:00Z",
        finished_at="2026-06-13T17:31:00Z",
        rows=[],
        error="scan crashed",
    )
    alpha_partial = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(models_module, 1, b"/alpha", disk_bytes=110, apparent_bytes=105, depth=0, parent_path=None)
        ],
        error="permission denied",
    )
    beta_complete = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/beta"),
        status="complete",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[
            _directory_row(models_module, 1, b"/beta", disk_bytes=220, apparent_bytes=220, depth=0, parent_path=None)
        ],
    )

    selections = queries.resolve_top_snapshot_selection(connection, "latest")

    assert [(selection.root_path, selection.id) for selection in selections] == [
        (Path("/alpha"), alpha_partial),
        (Path("/beta"), beta_complete),
    ]
    assert all(selection.status is not models_module.SnapshotStatus.FAILED for selection in selections)
    assert alpha_complete not in [selection.id for selection in selections]


def test_query_indexed_storage_domain_totals_subtracts_nested_submount_across_indexed_path_gap(
    repo_root: Path, tmp_path: Path
) -> None:
    """A nested submount under a missing intermediate directory must not be
    double-counted against the enclosing domain (CR-01 regression).

    Indexed rows ``/a`` (domain A) and ``/a/b/c`` (domain C) with ``/a/b``
    absent: the recursive aggregate of ``/a`` already includes the bytes of
    ``/a/b/c``. The nested submount must therefore be subtracted from the
    nearest indexed ancestor (``/a``, domain A), so the per-domain totals still
    sum to the root aggregate (1000) rather than 1300.
    """

    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/a"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/a",
                disk_bytes=1000,
                apparent_bytes=900,
                depth=0,
                parent_path=None,
            ),
            # /a/b is intentionally absent (gap). /a/b/c parent points at the
            # missing intermediate directory.
            _directory_row(
                models_module,
                1,
                b"/a/b/c",
                disk_bytes=300,
                apparent_bytes=250,
                depth=2,
                parent_path=b"/a/b",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/a",
                filesystem_type="ext4",
                mount_source="/dev/domainA",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/a/b/c",
                filesystem_type="xfs",
                mount_source="/dev/domainC",
            ),
        ],
    )
    del snapshot_id

    totals = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")

    by_key = {total.storage_domain.key: total for total in totals}
    domain_a = by_key["8:1|/|ext4|/dev/domainA"]
    domain_c = by_key["8:17|/|xfs|/dev/domainC"]

    # Domain C keeps its own aggregate; domain A is reduced by the nested
    # submount so the totals reconcile to the root aggregate.
    assert domain_c.indexed_visible_disk_bytes == 300
    assert domain_a.indexed_visible_disk_bytes == 700
    assert domain_c.indexed_visible_apparent_bytes == 250
    assert domain_a.indexed_visible_apparent_bytes == 650
    total_disk = sum(total.indexed_visible_disk_bytes for total in totals)
    total_apparent = sum(total.indexed_visible_apparent_bytes for total in totals)
    assert total_disk == 1000
    assert total_apparent == 900


def test_query_indexed_storage_domain_totals_counts_collapsed_boundary_rows_with_folded_evidence(
    repo_root: Path, tmp_path: Path
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1000,
                apparent_bytes=920,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=200,
                apparent_bytes=170,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=50,
                top_child_path=b"/srv/cache/pip",
                top_child_disk_bytes=120,
                error="collapsed_subtree_evidence total=2 kinds=mount_skipped:1,scan_error:1",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/data/projects/db",
                disk_bytes=300,
                apparent_bytes=260,
                depth=3,
                parent_path=b"/srv/data/projects",
                collapsed=True,
                collapse_reason="fan_out",
                collapsed_dirs=700,
                top_child_path=b"/srv/data/projects/db/tenant-a",
                top_child_disk_bytes=180,
                error="collapsed_subtree_evidence total=3 kinds=mount_skipped:2,scan_error:1",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/srv/data/projects/db",
                filesystem_type="xfs",
                mount_source="/dev/db",
            ),
        ],
        error="permission denied",
    )

    totals = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")
    rows, warnings = queries.query_top_rows(connection, snapshot_id=1, limit=5, group_by="storage-domain")

    assert warnings == ()
    rows_by_path = {row.path: row for row in rows}
    assert rows_by_path[b"/srv/data/projects/db"].collapsed is True
    assert rows_by_path[b"/srv/data/projects/db"].error == (
        "collapsed_subtree_evidence total=3 kinds=mount_skipped:2,scan_error:1"
    )

    by_key = {total.storage_domain.key: total for total in totals}
    assert by_key["8:1|/|ext4|/dev/root"].indexed_visible_disk_bytes == 700
    assert by_key["8:17|/|xfs|/dev/db"].indexed_visible_disk_bytes == 300
    assert by_key["8:1|/|ext4|/dev/root"].indexed_visible_apparent_bytes == 660
    assert by_key["8:17|/|xfs|/dev/db"].indexed_visible_apparent_bytes == 260
    assert sum(total.indexed_visible_disk_bytes for total in totals) == 1000
    assert sum(total.indexed_visible_apparent_bytes for total in totals) == 920


def test_query_indexed_storage_domain_totals_attributes_unknown_mounts_once_not_per_domain(
    repo_root: Path, tmp_path: Path
) -> None:
    """An unknown-mount count must be charged once per snapshot, not fanned out
    to every resolved domain (WR-05 regression).

    A snapshot resolving to two domains plus an unresolved row must report the
    unknown count exactly once (on the root's domain), not duplicated across
    every domain.
    """

    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1000, apparent_bytes=900, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/archive", disk_bytes=400, apparent_bytes=350, depth=1, parent_path=b"/srv"
            ),
            # Unresolved row: no persisted mount prefix matches it.
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=200,
                apparent_bytes=180,
                depth=1,
                parent_path=b"/",
                error="outside persisted mount coverage",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/srv/archive",
                filesystem_type="xfs",
                mount_source="/dev/archive",
            ),
        ],
        error="permission denied",
    )

    totals = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")

    by_key = {total.storage_domain.key: total for total in totals}
    # Two resolved domains exist.
    assert "8:1|/|ext4|/dev/root" in by_key
    assert "8:17|/|xfs|/dev/archive" in by_key
    # The unknown-mount count is charged exactly once across all domains, not
    # multiplied per-domain.
    total_unknown = sum(total.unknown_mount_count for total in totals)
    assert total_unknown == 1
    # It lands on the root domain, leaving the fully-covered submount domain at 0.
    assert by_key["8:1|/|ext4|/dev/root"].unknown_mount_count == 1
    assert by_key["8:17|/|xfs|/dev/archive"].unknown_mount_count == 0


def test_query_indexed_storage_domain_totals_unknown_mount_falls_back_to_root_fs_not_lowest_key(
    repo_root: Path, tmp_path: Path
) -> None:
    """When the snapshot root path has no directory row, the unknown-mount count
    must be charged to the enclosing root-filesystem domain (longest mount prefix
    of the root path), not the lexicographically lowest resolved key (WR-02
    regression).

    Setup: the snapshot root ``/srv`` has no row of its own, so it is absent from
    the resolved-domain map. The snapshot resolves rows on both the enclosing
    root-filesystem mount (``/srv`` -> ``8:1|...``) and a nested submount
    (``/srv/cache`` -> ``1:5|...``) whose domain key sorts *lower* than the
    root-fs key. An unresolved ``/mystery`` row produces one unknown-mount count.

    Pre-fix, the lowest-keyed fallback charged the count to the submount domain
    (``1:5|...``) -- which may have complete coverage -- while the actually
    incomplete root-fs domain looked clean. The fix resolves the root path via
    longest mount prefix, so the count lands on the root-fs domain.
    """

    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        # Note: no row at the root path "/srv" itself -> root is unresolved via the
        # directory-row map and must be resolved via the persisted mounts.
        rows=[
            _directory_row(
                models_module, 1, b"/srv/data", disk_bytes=600, apparent_bytes=550, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=400, apparent_bytes=350, depth=1, parent_path=b"/srv"
            ),
            # Unresolved row: no persisted mount prefix matches it.
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=200,
                apparent_bytes=180,
                depth=1,
                parent_path=b"/",
                error="outside persisted mount coverage",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            # Submount whose domain key ("1:5|...") sorts lexically BEFORE the
            # root-fs key ("8:1|...").
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="1:5",
                root=b"/",
                mount_point=b"/srv/cache",
                filesystem_type="tmpfs",
                mount_source="tmpfs",
            ),
        ],
        error="permission denied",
    )

    totals = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")

    by_key = {total.storage_domain.key: total for total in totals}
    root_fs_key = "8:1|/|ext4|/dev/root"
    submount_key = "1:5|/|tmpfs|tmpfs"
    # Sanity: the submount key really does sort lower than the root-fs key, so the
    # old lowest-keyed fallback would have mis-charged it.
    assert submount_key < root_fs_key
    assert root_fs_key in by_key
    assert submount_key in by_key
    # The unknown-mount count is charged exactly once.
    assert sum(total.unknown_mount_count for total in totals) == 1
    # It lands on the enclosing root-filesystem domain, NOT the lower-keyed submount.
    assert by_key[root_fs_key].unknown_mount_count == 1
    assert by_key[submount_key].unknown_mount_count == 0


def test_parse_since_accepts_integer_plus_single_unit_and_rejects_invalid_grammar(
    repo_root: Path,
) -> None:
    pairs = import_module(repo_root, "watchdirs.reporting.pairs")

    assert pairs.parse_since("15s") == timedelta(seconds=15)
    assert pairs.parse_since("24h") == timedelta(hours=24)
    assert pairs.parse_since("7d") == timedelta(days=7)

    for raw_value in ("", "0h", "-1h", "1.5h", "1h30m", "24 h", "5w", "banana"):
        with pytest.raises(Exception):
            pairs.parse_since(raw_value)


def test_resolve_snapshot_pairs_selects_same_root_pairs_uses_current_finished_at_cutoff_and_excludes_failed_snapshots(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    pairs = import_module(repo_root, "watchdirs.reporting.pairs")

    srv_boundary = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T17:59:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T11:59:00Z",
        finished_at="2026-06-13T12:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=140, apparent_bytes=140, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T17:59:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[],
        error="scan crashed",
    )
    srv_partial = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:59:00Z",
        finished_at="2026-06-13T19:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=180, depth=0, parent_path=None)],
        error="permission denied",
    )
    var_old = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-12T20:00:00Z",
        finished_at="2026-06-12T20:00:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=300, apparent_bytes=300, depth=0, parent_path=None)],
    )
    var_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T21:00:00Z",
        finished_at="2026-06-13T21:00:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=420, apparent_bytes=400, depth=0, parent_path=None)],
    )

    resolved_pairs, warnings = pairs.resolve_snapshot_pairs(connection, since="24h")

    assert [(pair.root_path, pair.baseline.id, pair.current.id) for pair in resolved_pairs] == [
        (Path("/srv"), srv_boundary, srv_partial),
        (Path("/var"), var_old, var_current),
    ]
    assert "partial_snapshot" in resolved_pairs[0].warning_codes
    assert resolved_pairs[0].current.status is models_module.SnapshotStatus.PARTIAL
    assert {warning.code for warning in warnings} >= {"failed_snapshot_excluded", "partial_snapshot"}


def test_resolve_snapshot_pairs_falls_back_to_oldest_earlier_snapshot_and_raises_when_no_same_root_pair_exists(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    pairs = import_module(repo_root, "watchdirs.reporting.pairs")

    fallback_baseline = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/opt"),
        status="complete",
        started_at="2026-06-13T08:00:00Z",
        finished_at="2026-06-13T08:00:00Z",
        rows=[_directory_row(models_module, 1, b"/opt", disk_bytes=80, apparent_bytes=80, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/opt"),
        status="complete",
        started_at="2026-06-13T09:00:00Z",
        finished_at="2026-06-13T09:00:00Z",
        rows=[_directory_row(models_module, 1, b"/opt", disk_bytes=90, apparent_bytes=90, depth=0, parent_path=None)],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/opt"),
        status="complete",
        started_at="2026-06-13T10:00:00Z",
        finished_at="2026-06-13T10:00:00Z",
        rows=[_directory_row(models_module, 1, b"/opt", disk_bytes=140, apparent_bytes=140, depth=0, parent_path=None)],
    )

    resolved_pairs, warnings = pairs.resolve_snapshot_pairs(connection, since="24h")

    assert len(resolved_pairs) == 1
    assert resolved_pairs[0].baseline.id == fallback_baseline
    assert resolved_pairs[0].current.id == current_id
    assert "baseline_before_since_unavailable" in resolved_pairs[0].warning_codes
    assert "baseline_before_since_unavailable" in {warning.code for warning in warnings}

    lonely_connection, migrations_module, models_module = _open_db(repo_root, tmp_path / "lonely")
    _seed_snapshot(
        lonely_connection,
        migrations_module,
        models_module,
        root_path=Path("/lonely"),
        status="complete",
        started_at="2026-06-13T12:00:00Z",
        finished_at="2026-06-13T12:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/lonely", disk_bytes=10, apparent_bytes=10, depth=0, parent_path=None)
        ],
    )

    with pytest.raises(Exception):
        pairs.resolve_snapshot_pairs(lonely_connection, since="24h")


def test_resolve_snapshot_pairs_treats_offset_timestamps_as_utc_equivalent_and_flags_invalid_finished_at(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    pairs = import_module(repo_root, "watchdirs.reporting.pairs")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-12T11:59:00Z",
        finished_at="2026-06-12T12:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/alpha", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-12T12:30:00Z",
        finished_at="2026-06-12T12:30:00",
        rows=[
            _directory_row(models_module, 1, b"/alpha", disk_bytes=105, apparent_bytes=105, depth=0, parent_path=None)
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-13T06:59:00Z",
        finished_at="2026-06-13T05:00:00-07:00",
        rows=[
            _directory_row(models_module, 1, b"/alpha", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None)
        ],
    )

    resolved_pairs, warnings = pairs.resolve_snapshot_pairs(connection, since="24h")

    assert len(resolved_pairs) == 1
    assert resolved_pairs[0].baseline.id == baseline_id
    assert resolved_pairs[0].current.id == current_id
    assert "invalid_snapshot_timestamp" in {warning.code for warning in warnings}


def test_query_diff_rows_classifies_created_deleted_grown_shrunk_and_unchanged_rows(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/grow", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/shrink", disk_bytes=60, apparent_bytes=60, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=150, apparent_bytes=120, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/grow", disk_bytes=90, apparent_bytes=85, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/shrink", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/new", disk_bytes=25, apparent_bytes=25, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"
            ),
        ],
    )

    pair = models_module.SnapshotPair(
        root_path=Path("/srv"),
        baseline=models_module.SnapshotRecord(
            id=baseline_id,
            started_at="2026-06-12T18:00:00Z",
            finished_at="2026-06-12T18:00:00Z",
            root_path=Path("/srv"),
            status=models_module.SnapshotStatus.COMPLETE,
            notes=None,
            error=None,
        ),
        current=models_module.SnapshotRecord(
            id=current_id,
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            root_path=Path("/srv"),
            status=models_module.SnapshotStatus.COMPLETE,
            notes=None,
            error=None,
        ),
        warning_codes=(),
    )

    rows, warnings = queries.query_diff_rows(connection, pair=pair, group_by="root")

    assert warnings == ()
    rows_by_path = {row.path: row for row in rows}
    assert rows_by_path[b"/srv/new"].classification == "created"
    assert rows_by_path[b"/srv/new"].previous_disk_bytes == 0
    assert rows_by_path[b"/srv/new"].current_disk_bytes == 25
    assert rows_by_path[b"/srv/new"].disk_bytes_delta == 25
    assert rows_by_path[b"/srv/gone"].classification == "deleted"
    assert rows_by_path[b"/srv/gone"].previous_disk_bytes == 20
    assert rows_by_path[b"/srv/gone"].current_disk_bytes == 0
    assert rows_by_path[b"/srv/grow"].classification == "grown"
    assert rows_by_path[b"/srv/grow"].disk_bytes_delta == 50
    assert rows_by_path[b"/srv/shrink"].classification == "shrunk"
    assert rows_by_path[b"/srv/shrink"].disk_bytes_delta == -50
    assert rows_by_path[b"/srv/same"].classification == "unchanged"
    assert rows_by_path[b"/srv/same"].apparent_bytes_delta == 0


def test_query_diff_rows_uses_current_first_and_baseline_fallback_collapse_metadata(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=400, apparent_bytes=350, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/current-collapsed",
                disk_bytes=90,
                apparent_bytes=70,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/policy-drift",
                disk_bytes=80,
                apparent_bytes=60,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=10,
                top_child_path=b"/srv/policy-drift/a",
                top_child_disk_bytes=55,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/deleted-collapsed",
                disk_bytes=70,
                apparent_bytes=50,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="fan_out",
                collapsed_dirs=40,
                top_child_path=b"/srv/deleted-collapsed/node_modules",
                top_child_disk_bytes=44,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/ordinary",
                disk_bytes=60,
                apparent_bytes=40,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=420, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/current-collapsed",
                disk_bytes=120,
                apparent_bytes=95,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="descendant_count",
                collapsed_dirs=55,
                top_child_path=b"/srv/current-collapsed/packages",
                top_child_disk_bytes=88,
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/policy-drift",
                disk_bytes=85,
                apparent_bytes=65,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/ordinary",
                disk_bytes=90,
                apparent_bytes=60,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, warnings = queries.query_diff_rows(connection, pair=pair, group_by="root")

    assert warnings == ()
    rows_by_path = {row.path: row for row in rows}

    current_collapsed = rows_by_path[b"/srv/current-collapsed"]
    assert current_collapsed.collapsed is True
    assert current_collapsed.collapse_reason == "descendant_count"
    assert current_collapsed.collapsed_dirs == 55
    assert current_collapsed.top_child_path == b"/srv/current-collapsed/packages"
    assert current_collapsed.top_child_disk_bytes == 88

    policy_drift = rows_by_path[b"/srv/policy-drift"]
    assert policy_drift.collapsed is False
    assert policy_drift.collapse_reason is None
    assert policy_drift.collapsed_dirs is None
    assert policy_drift.top_child_path is None
    assert policy_drift.top_child_disk_bytes is None

    deleted = rows_by_path[b"/srv/deleted-collapsed"]
    assert deleted.classification == "deleted"
    assert deleted.collapsed is True
    assert deleted.collapse_reason == "fan_out"
    assert deleted.collapsed_dirs == 40
    assert deleted.top_child_path == b"/srv/deleted-collapsed/node_modules"
    assert deleted.top_child_disk_bytes == 44

    ordinary = rows_by_path[b"/srv/ordinary"]
    assert ordinary.collapsed is False
    assert ordinary.collapse_reason is None
    assert ordinary.collapsed_dirs is None


def test_query_diff_rows_marks_baseline_descendants_hidden_by_current_collapse(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=80, apparent_bytes=80, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/cache/packages",
                disk_bytes=60,
                apparent_bytes=60,
                depth=2,
                parent_path=b"/srv/cache",
            ),
            _directory_row(
                models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=80,
                apparent_bytes=80,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=1,
                top_child_path=b"/srv/cache/packages",
                top_child_disk_bytes=60,
            ),
        ],
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, warnings = queries.query_diff_rows(connection, pair=pair, group_by="root")
    deleted_rows, deleted_warnings = queries.query_deleted_rows(connection, pair=pair, limit=10)

    rows_by_path = {row.path: row for row in rows}
    assert warnings == ()
    assert deleted_warnings == ()
    assert rows_by_path[b"/srv/cache/packages"].classification == "hidden_by_collapse"
    assert rows_by_path[b"/srv/gone"].classification == "deleted"
    assert [row.path for row in deleted_rows] == [b"/srv/gone"]


def test_render_payloads_and_text_show_collapse_metadata_only_for_collapsed_rows(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    render = import_module(repo_root, "watchdirs.reporting.render")

    snapshot = models_module.SnapshotRecord(
        id=42,
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        root_path=Path("/srv"),
        status=models_module.SnapshotStatus.COMPLETE,
        notes=None,
        error=None,
    )
    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=10, current_id=11)
    collapsed_top = models_module.TopRow(
        snapshot_id=42,
        root_path=Path("/srv"),
        path=b"/srv/cache",
        path_bytes_hex=b"/srv/cache".hex(),
        depth=1,
        current_apparent_bytes=650,
        current_disk_bytes=900,
        file_count=12,
        dir_count=1200,
        error="collapsed_subtree_evidence total=2 kinds=mount_skipped:1,scan_error:1",
        collapsed=True,
        collapse_reason="fan_out",
        collapsed_dirs=1200,
        top_child_path=b"/srv/cache/node_modules",
        top_child_disk_bytes=640,
    )
    ordinary_top = models_module.TopRow(
        snapshot_id=42,
        root_path=Path("/srv"),
        path=b"/srv/log",
        path_bytes_hex=b"/srv/log".hex(),
        depth=1,
        current_apparent_bytes=180,
        current_disk_bytes=200,
        file_count=4,
        dir_count=0,
        error=None,
    )
    collapsed_diff = models_module.DiffRow(
        root_path=Path("/srv"),
        baseline_snapshot_id=10,
        current_snapshot_id=11,
        path=b"/srv/cache",
        parent_path=b"/srv",
        depth=1,
        classification="grown",
        previous_apparent_bytes=400,
        current_apparent_bytes=650,
        apparent_bytes_delta=250,
        previous_disk_bytes=500,
        current_disk_bytes=900,
        disk_bytes_delta=400,
        error="collapsed_subtree_evidence total=2 kinds=mount_skipped:1,scan_error:1",
        collapsed=True,
        collapse_reason="fan_out",
        collapsed_dirs=1200,
        top_child_path=b"/srv/cache/node_modules",
        top_child_disk_bytes=640,
    )
    ordinary_diff = models_module.DiffRow(
        root_path=Path("/srv"),
        baseline_snapshot_id=10,
        current_snapshot_id=11,
        path=b"/srv/log",
        parent_path=b"/srv",
        depth=1,
        classification="unchanged",
        previous_apparent_bytes=180,
        current_apparent_bytes=180,
        apparent_bytes_delta=0,
        previous_disk_bytes=200,
        current_disk_bytes=200,
        disk_bytes_delta=0,
        error=None,
    )
    frontier_rows = (
        models_module.FrontierRow(
            row=collapsed_diff,
            suppressed_descendant_count=0,
            suppressed_ancestor_count=0,
            reason="displayed",
        ),
        models_module.FrontierRow(
            row=ordinary_diff,
            suppressed_descendant_count=0,
            suppressed_ancestor_count=0,
            reason="displayed",
        ),
    )

    top_payload = render.render_top_payload(
        snapshot_selector="latest",
        limit=5,
        effective_limit=5,
        group_by="root",
        sections=[{"snapshot": snapshot, "warnings": (), "rows": (collapsed_top, ordinary_top)}],
    )
    diff_payload = render.render_diff_payload(
        since="24h",
        limit=5,
        effective_limit=5,
        group_by="root",
        pairs=(pair,),
        rows=frontier_rows,
        classification_counts={"grown": 1, "unchanged": 1},
        warnings=(),
    )
    report_summary = models_module.ReportSummary(
        snapshot_pairs=(pair,),
        classification_counts={"grown": 1, "unchanged": 1},
        disk_bytes_delta_by_classification={"grown": 400, "unchanged": 0},
        apparent_bytes_delta_by_classification={"grown": 250, "unchanged": 0},
        frontier=frontier_rows,
        groups=(),
        deleted_preview=(collapsed_diff, ordinary_diff),
        warnings=(),
    )
    report_payload = render.render_report_payload(
        since="24h",
        limit=5,
        effective_limit=5,
        group_by="root",
        summary=report_summary,
    )
    top_text = render.render_top_text(
        snapshot_selector="latest",
        limit=5,
        effective_limit=5,
        group_by="root",
        sections=[{"snapshot": snapshot, "warnings": (), "rows": (collapsed_top, ordinary_top)}],
    )
    diff_text = render.render_diff_text(
        since="24h",
        limit=5,
        effective_limit=5,
        group_by="root",
        pairs=(pair,),
        rows=frontier_rows,
        warnings=(),
    )

    collapsed_top_payload = top_payload["sections"][0]["rows"][0]
    ordinary_top_payload = top_payload["sections"][0]["rows"][1]
    assert collapsed_top_payload["collapsed"] is True
    assert collapsed_top_payload["collapse_reason"] == "fan_out"
    assert collapsed_top_payload["collapsed_dirs"] == 1200
    assert collapsed_top_payload["top_child"] == {
        "path": "/srv/cache/node_modules",
        "path_bytes_hex": b"/srv/cache/node_modules".hex(),
        "disk_bytes": 640,
    }
    assert "top_child" not in collapsed_top_payload["top_child"]
    assert "collapsed" not in ordinary_top_payload
    assert "collapse_reason" not in ordinary_top_payload
    assert "collapsed_dirs" not in ordinary_top_payload
    assert "top_child" not in ordinary_top_payload

    collapsed_frontier_payload = diff_payload["rows"][0]
    ordinary_frontier_payload = diff_payload["rows"][1]
    assert collapsed_frontier_payload["collapsed"] is True
    assert collapsed_frontier_payload["top_child"]["disk_bytes"] == 640
    assert "collapsed" not in ordinary_frontier_payload
    assert "top_child" not in ordinary_frontier_payload

    collapsed_deleted_payload = report_payload["deleted_preview"][0]
    ordinary_deleted_payload = report_payload["deleted_preview"][1]
    assert collapsed_deleted_payload["collapsed"] is True
    assert collapsed_deleted_payload["top_child"]["path"] == "/srv/cache/node_modules"
    assert "collapsed" not in ordinary_deleted_payload
    assert "top_child" not in ordinary_deleted_payload

    collapsed_top_line = next(line for line in top_text.splitlines() if "path=/srv/cache" in line)
    ordinary_top_line = next(line for line in top_text.splitlines() if "path=/srv/log" in line)
    assert "collapsed=true" in collapsed_top_line
    assert "reason=fan_out" in collapsed_top_line
    assert "collapsed_dirs=1200" in collapsed_top_line
    assert "top_child=/srv/cache/node_modules" in collapsed_top_line
    assert "top_child_disk_bytes=640" in collapsed_top_line
    assert "collapsed=" not in ordinary_top_line
    assert "top_child=" not in ordinary_top_line

    collapsed_diff_line = next(line for line in diff_text.splitlines() if "path=/srv/cache" in line)
    ordinary_diff_line = next(line for line in diff_text.splitlines() if "path=/srv/log" in line)
    assert "collapsed=true" in collapsed_diff_line
    assert "top_child=/srv/cache/node_modules" in collapsed_diff_line
    assert "collapsed=" not in ordinary_diff_line
    assert "top_child=" not in ordinary_diff_line


def test_query_deleted_rows_returns_baseline_only_paths_sorted_by_previous_disk_bytes(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/old-big", disk_bytes=90, apparent_bytes=80, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/old-small", disk_bytes=25, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=120, apparent_bytes=120, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/new", disk_bytes=50, apparent_bytes=50, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, warnings = queries.query_deleted_rows(connection, pair=pair, limit=1)

    assert warnings == ()
    assert len(rows) == 1
    assert rows[0].path == b"/srv/old-big"
    assert rows[0].classification == "deleted"
    assert rows[0].previous_disk_bytes == 90
    assert rows[0].current_disk_bytes == 0
    assert rows[0].disk_bytes_delta == -90
    assert rows[0].path_bytes_hex == b"/srv/old-big".hex()


def test_query_deleted_rows_uses_requested_grouping_for_deleted_rows(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/deleted", disk_bytes=90, apparent_bytes=80, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=120, apparent_bytes=120, depth=0, parent_path=None)],
        mounts=[
            _mount(
                models_module,
                mount_id=21,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, warnings = queries.query_deleted_rows(connection, pair=pair, limit=1, group_by="mount")

    assert warnings == ()
    assert len(rows) == 1
    assert rows[0].path == b"/srv/deleted"
    assert rows[0].group == models_module.GroupLabel(kind="mount", key="/srv", mount_point=b"/srv")


def test_query_explain_path_rows_returns_exact_target_and_descendants_without_fuzzy_prefix_matches(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/cache/a", disk_bytes=20, apparent_bytes=20, depth=2, parent_path=b"/srv/cache"
            ),
            _directory_row(
                models_module, 1, b"/srv/cache2", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=160, apparent_bytes=160, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=120, apparent_bytes=120, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/cache/a", disk_bytes=80, apparent_bytes=80, depth=2, parent_path=b"/srv/cache"
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/cache/a/leaf",
                disk_bytes=70,
                apparent_bytes=70,
                depth=3,
                parent_path=b"/srv/cache/a",
            ),
            _directory_row(
                models_module, 1, b"/srv/cache2", disk_bytes=12, apparent_bytes=12, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, effective_target_path, warnings = queries.query_explain_path_rows(
        connection,
        pair=pair,
        target_path=b"/srv/cache",
        group_by="root",
    )

    assert warnings == ()
    assert effective_target_path == b"/srv/cache"
    assert [row.path for row in rows] == [b"/srv/cache", b"/srv/cache/a", b"/srv/cache/a/leaf"]
    assert rows[0].classification == "grown"
    assert rows[0].path_bytes_hex == b"/srv/cache".hex()

    with pytest.raises(Exception):
        queries.query_explain_path_rows(connection, pair=pair, target_path=b"/srv/cac", group_by="root")


def test_query_explain_path_rows_returns_deepest_collapsed_ancestor_for_path_inside_folded_subtree(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")
    render = import_module(repo_root, "watchdirs.reporting.render")

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=40,
                apparent_bytes=40,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=10,
                top_child_path=b"/srv/cache/pip",
                top_child_disk_bytes=20,
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=160, apparent_bytes=160, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=120,
                apparent_bytes=120,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="fan_out",
                collapsed_dirs=200,
                top_child_path=b"/srv/cache/node_modules",
                top_child_disk_bytes=80,
            ),
            _directory_row(
                models_module, 1, b"/srv/cache2", disk_bytes=12, apparent_bytes=12, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, effective_target_path, warnings = queries.query_explain_path_rows(
        connection,
        pair=pair,
        target_path=b"/srv/cache/deep/file.txt",
        group_by="root",
    )

    assert warnings == ()
    assert effective_target_path == b"/srv/cache"
    assert [row.path for row in rows] == [b"/srv/cache"]
    assert rows[0].collapsed is True
    assert rows[0].collapse_reason == "fan_out"
    assert rows[0].top_child_path == b"/srv/cache/node_modules"

    result = models_module.ExplainPathResult(
        target=rows[0],
        children=tuple(rows[1:]),
        unshown_or_direct_disk_bytes_delta=rows[0].disk_bytes_delta,
        unshown_or_direct_apparent_bytes_delta=rows[0].apparent_bytes_delta,
    )
    payload = render.render_explain_path_payload(
        since="24h",
        limit=5,
        effective_limit=5,
        depth=3,
        group_by="root",
        pairs=(pair,),
        result=result,
        warnings=warnings,
    )

    assert payload["target"]["collapsed"] is True
    assert payload["target"]["top_child"]["path"] == "/srv/cache/node_modules"
    assert payload["children"] == []
