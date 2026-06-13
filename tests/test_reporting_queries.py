from __future__ import annotations

from datetime import timedelta
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
        rows=[_directory_row(models_module, 1, b"/lonely", disk_bytes=10, apparent_bytes=10, depth=0, parent_path=None)],
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
        rows=[_directory_row(models_module, 1, b"/alpha", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-12T12:30:00Z",
        finished_at="2026-06-12T12:30:00",
        rows=[_directory_row(models_module, 1, b"/alpha", disk_bytes=105, apparent_bytes=105, depth=0, parent_path=None)],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/alpha"),
        status="complete",
        started_at="2026-06-13T06:59:00Z",
        finished_at="2026-06-13T05:00:00-07:00",
        rows=[_directory_row(models_module, 1, b"/alpha", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None)],
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
            _directory_row(models_module, 1, b"/srv/grow", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/shrink", disk_bytes=60, apparent_bytes=60, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv/grow", disk_bytes=90, apparent_bytes=85, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/shrink", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/new", disk_bytes=25, apparent_bytes=25, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv/old-big", disk_bytes=90, apparent_bytes=80, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/old-small", disk_bytes=25, apparent_bytes=20, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv/new", disk_bytes=50, apparent_bytes=50, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv/cache", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/cache/a", disk_bytes=20, apparent_bytes=20, depth=2, parent_path=b"/srv/cache"),
            _directory_row(models_module, 1, b"/srv/cache2", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv/cache", disk_bytes=120, apparent_bytes=120, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/cache/a", disk_bytes=80, apparent_bytes=80, depth=2, parent_path=b"/srv/cache"),
            _directory_row(models_module, 1, b"/srv/cache/a/leaf", disk_bytes=70, apparent_bytes=70, depth=3, parent_path=b"/srv/cache/a"),
            _directory_row(models_module, 1, b"/srv/cache2", disk_bytes=12, apparent_bytes=12, depth=1, parent_path=b"/srv"),
        ],
        error="permission denied",
    )

    pair = _snapshot_pair(models_module, root_path="/srv", baseline_id=baseline_id, current_id=current_id)
    rows, warnings = queries.query_explain_path_rows(connection, pair=pair, target_path=b"/srv/cache", group_by="root")

    assert warnings == ()
    assert [row.path for row in rows] == [b"/srv/cache", b"/srv/cache/a", b"/srv/cache/a/leaf"]
    assert rows[0].classification == "grown"
    assert rows[0].path_bytes_hex == b"/srv/cache".hex()

    with pytest.raises(Exception):
        queries.query_explain_path_rows(connection, pair=pair, target_path=b"/srv/cac", group_by="root")
