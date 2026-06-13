from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    return connection, migrations_module, models_module


def _directory_row(models_module, snapshot_id: int, path: bytes, *, disk_bytes: int, apparent_bytes: int, depth: int,
                   parent_path: bytes | None, file_count: int = 0, dir_count: int = 0, error: str | None = None):
    stripped = path.rstrip(b"/")
    name = b"/" if stripped == b"" else stripped.split(b"/")[-1]
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=parent_path,
        name=name,
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
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
):
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
    rows: list[object],
    mounts: list[object] | None = None,
    notes: str | None = None,
    error: str | None = None,
) -> int:
    snapshot = migrations_module.create_snapshot(connection, root_path, notes=notes)
    persisted_rows = [
        models_module.DirectoryAggregate(
            snapshot_id=snapshot.id,
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


def test_query_top_rows_unknown_mount_rows_use_null_group_and_warning(
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
    assert [warning.code for warning in mount_warnings] == ["unknown_mount"]
    assert [warning.code for warning in domain_warnings] == ["unknown_mount"]
    assert _textish(mount_warnings[0].path) == "/mystery"


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
        rows=[_directory_row(models_module, 1, b"/alpha", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
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
        rows=[_directory_row(models_module, 1, b"/alpha", disk_bytes=110, apparent_bytes=105, depth=0, parent_path=None)],
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
        rows=[_directory_row(models_module, 1, b"/beta", disk_bytes=220, apparent_bytes=220, depth=0, parent_path=None)],
    )

    selections = queries.resolve_top_snapshot_selection(connection, "latest")

    assert [(selection.root_path, selection.id) for selection in selections] == [
        (Path("/alpha"), alpha_partial),
        (Path("/beta"), beta_complete),
    ]
    assert all(selection.status is not models_module.SnapshotStatus.FAILED for selection in selections)
    assert alpha_complete not in [selection.id for selection in selections]
