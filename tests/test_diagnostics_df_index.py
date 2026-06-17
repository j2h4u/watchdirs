# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import DirectoryAggregateLike, MountInfoLike


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    return db_path, connection, migrations_module, models_module


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


class _StatResult:
    """Mimic os.statvfs_result for the fields the diagnostic consumes."""

    def __init__(self, *, f_frsize: int, f_blocks: int, f_bfree: int, f_bavail: int) -> None:
        self.f_frsize = f_frsize
        self.f_blocks = f_blocks
        self.f_bfree = f_bfree
        self.f_bavail = f_bavail


def _stat(*, size: int, free_total: int, avail_unprivileged: int, frsize: int = 1) -> _StatResult:
    assert size % frsize == 0
    return _StatResult(
        f_frsize=frsize,
        f_blocks=size // frsize,
        f_bfree=free_total // frsize,
        f_bavail=avail_unprivileged // frsize,
    )


def _recording_provider(mapping: dict[str, _StatResult | OSError], calls: list[str]):
    def provider(path: bytes) -> _StatResult:
        text = os.fsdecode(path)
        calls.append(text)
        if text not in mapping:
            raise AssertionError(f"unexpected statvfs path: {text!r}")
        result = mapping[text]
        if isinstance(result, OSError):
            raise result
        return result

    return provider


GIB = 1024**3


# ---------------------------------------------------------------------------
# Task 1 tests: df-vs-index reconciliation contract.
# ---------------------------------------------------------------------------


def test_indexed_storage_domain_totals_are_non_overlapping_with_nested_submount(
    repo_root: Path, tmp_path: Path
) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    # /srv root spans a nested submount /srv/archive on a different storage domain.
    # /srv aggregate (root) includes the bytes of the nested submount; the domain
    # total for the / device must subtract the nested submount aggregate.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1000, apparent_bytes=900, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/data", disk_bytes=400, apparent_bytes=380, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/archive", disk_bytes=600, apparent_bytes=520, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/archive/old",
                disk_bytes=300,
                apparent_bytes=250,
                depth=2,
                parent_path=b"/srv/archive",
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

    domains = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")
    by_key = {domain.storage_domain.key: domain for domain in domains}

    root_domain = by_key["8:1|/|ext4|/dev/root"]
    archive_domain = by_key["8:17|/|xfs|/dev/archive"]

    # Root domain total = /srv (1000) minus the nested submount aggregate (/srv/archive=600) = 400.
    assert root_domain.indexed_visible_disk_bytes == 400
    # Nested submount domain receives only its own aggregate.
    assert archive_domain.indexed_visible_disk_bytes == 600
    # No double counting: the two domains sum to the root aggregate.
    assert root_domain.indexed_visible_disk_bytes + archive_domain.indexed_visible_disk_bytes == 1000
    assert _textish(root_domain.storage_domain.mount_point) in {"/srv", "/srv/archive"}


def test_latest_selector_picks_one_snapshot_per_root_across_distinct_domains(repo_root: Path, tmp_path: Path) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    # Two current snapshots for the same root: latest must win, the older ignored.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T17:00:00Z",
        finished_at="2026-06-13T17:01:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=111, apparent_bytes=111, depth=0, parent_path=None)],
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
            )
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=480, depth=0, parent_path=None)],
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
            )
        ],
    )
    # A second, distinct root on a distinct storage-domain.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/data"),
        status="complete",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[
            _directory_row(models_module, 1, b"/data", disk_bytes=700, apparent_bytes=650, depth=0, parent_path=None)
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=20,
                parent_id=1,
                major_minor="8:33",
                root=b"/",
                mount_point=b"/data",
                filesystem_type="ext4",
                mount_source="/dev/data",
            )
        ],
    )

    domains = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")
    by_key = {domain.storage_domain.key: domain for domain in domains}

    srv_domain = by_key["8:1|/|ext4|/dev/root"]
    data_domain = by_key["8:33|/|ext4|/dev/data"]

    # Only the latest /srv snapshot contributes (500), not 111 and not 611.
    assert srv_domain.indexed_visible_disk_bytes == 500
    assert data_domain.indexed_visible_disk_bytes == 700
    # One selected snapshot id per domain (no double-summed current snapshots).
    assert len(srv_domain.snapshot_ids) == 1
    assert len(data_domain.snapshot_ids) == 1


def test_statvfs_provider_called_only_for_indexed_domains_and_reports_unattributed(
    repo_root: Path, tmp_path: Path
) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            )
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
            )
        ],
    )

    calls: list[str] = []
    provider = _recording_provider(
        {
            "/srv": _stat(size=100 * GIB, free_total=70 * GIB, avail_unprivileged=65 * GIB),
        },
        calls,
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
    )

    # Only the one indexed storage-domain mount point was probed (not all live mounts).
    assert calls == ["/srv"]
    assert len(diagnostic.filesystems) == 1
    section = diagnostic.filesystems[0]
    # df used = size - free_total = 100 - 70 = 30 GiB. indexed = 10 GiB.
    assert section.filesystem_stat_available is True
    assert section.df_used_bytes == 30 * GIB
    assert section.indexed_visible_disk_bytes == 10 * GIB
    assert section.unattributed_bytes == 20 * GIB
    assert section.over_indexed_bytes == 0


def test_per_domain_statvfs_failure_marks_only_that_domain_unavailable(repo_root: Path, tmp_path: Path) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            )
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
            )
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/data"),
        status="complete",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/data", disk_bytes=5 * GIB, apparent_bytes=5 * GIB, depth=0, parent_path=None
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=20,
                parent_id=1,
                major_minor="8:33",
                root=b"/",
                mount_point=b"/data",
                filesystem_type="ext4",
                mount_source="/dev/data",
            )
        ],
    )

    calls: list[str] = []
    provider = _recording_provider(
        {
            "/srv": OSError("permission denied"),
            "/data": _stat(size=50 * GIB, free_total=40 * GIB, avail_unprivileged=38 * GIB),
        },
        calls,
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:20:00Z",
    )

    assert diagnostic.ok is True
    sections = {os.fsdecode(s.storage_domain.mount_point): s for s in diagnostic.filesystems}

    failed = sections["/srv"]
    assert failed.filesystem_stat_available is False
    assert failed.filesystem_status == "stat_unavailable"
    assert "filesystem_stat_unavailable" in failed.coverage_reason_codes
    assert failed.df_used_bytes is None
    assert failed.unattributed_bytes is None
    assert failed.over_indexed_bytes is None
    # Indexed visible totals are still present for the unavailable domain.
    assert failed.indexed_visible_disk_bytes == 10 * GIB

    ok_section = sections["/data"]
    assert ok_section.filesystem_stat_available is True
    assert ok_section.df_used_bytes == 10 * GIB
    assert ok_section.unattributed_bytes == 5 * GIB

    warning_codes = {warning.code for warning in diagnostic.warnings}
    assert "filesystem_stat_unavailable" in warning_codes
    unavailable_warning = next(w for w in diagnostic.warnings if w.code == "filesystem_stat_unavailable")
    assert _textish(unavailable_warning.path) == "/srv"


def test_partial_filesystem_coverage_blocks_automatic_deleted_open_suspicion(repo_root: Path, tmp_path: Path) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    # Indexed root /srv is a subtree of the / filesystem; statvfs covers the whole device.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/srv",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
    )

    provider = _recording_provider(
        {"/srv": _stat(size=200 * GIB, free_total=20 * GIB, avail_unprivileged=18 * GIB)},
        [],
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
        filesystem_scope_provider=lambda domain: True,  # filesystem broader than indexed roots
    )

    section = diagnostic.filesystems[0]
    assert section.filesystem_scope_extends_beyond_indexed_roots is True
    assert "indexed_roots_are_subtrees_of_filesystem" in section.coverage_reason_codes
    # Material remainder exists (df_used 180 GiB vs indexed 10 GiB) but deleted-open
    # suspicion must NOT be emitted from partial coverage alone.
    assert section.unattributed_bytes == 170 * GIB
    assert "deleted_open_file_suspected" not in section.likely_reasons


def test_indexed_greater_than_df_exposes_over_indexed_bytes_in_json_and_text(repo_root: Path, tmp_path: Path) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")
    render = import_module(repo_root, "watchdirs.reporting.render")

    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=40 * GIB, apparent_bytes=38 * GIB, depth=0, parent_path=None
            )
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
            )
        ],
    )

    provider = _recording_provider(
        {"/srv": _stat(size=100 * GIB, free_total=70 * GIB, avail_unprivileged=68 * GIB)},
        [],
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
    )

    section = diagnostic.filesystems[0]
    # df used = 30 GiB, indexed = 40 GiB -> over_indexed = 10 GiB, unattributed = 0.
    assert section.over_indexed_bytes == 10 * GIB
    assert section.unattributed_bytes == 0

    payload = render.render_df_index_payload(diagnostic)
    payload_section = payload["filesystems"][0]
    assert payload_section["over_indexed_bytes"] == 10 * GIB

    text = render.render_df_index_text(diagnostic)
    assert "over_indexed_bytes=" in text
    assert str(10 * GIB) in text


def test_partial_snapshots_and_stale_and_unknown_mounts_are_surfaced_as_counters(
    repo_root: Path, tmp_path: Path
) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    # Partial snapshot with an unknown-mount row that has no persisted mount prefix.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-10T18:00:00Z",
        finished_at="2026-06-10T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            ),
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=3 * GIB,
                apparent_bytes=3 * GIB,
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
            )
        ],
        error="permission denied",
    )

    provider = _recording_provider(
        {"/srv": _stat(size=100 * GIB, free_total=70 * GIB, avail_unprivileged=68 * GIB)},
        [],
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-14T18:05:00Z",
    )

    section = diagnostic.filesystems[0]
    # Partial snapshot evidence surfaces.
    assert section.partial_snapshot_count >= 1
    assert "partial_snapshot_evidence" in section.coverage_reason_codes
    # Unknown mount row is counted, not hidden.
    assert section.unknown_mount_count >= 1
    # Snapshot age is surfaced and positive given generated_at is days later.
    assert section.max_snapshot_age_seconds is not None
    assert section.max_snapshot_age_seconds > 0
    warning_codes = {warning.code for warning in diagnostic.warnings}
    assert "unknown_mount" in warning_codes


def test_partial_snapshot_evidence_blocks_deleted_open_suspicion(repo_root: Path, tmp_path: Path) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    # Partial snapshot, indexed roots fully cover the filesystem, but evidence is
    # non-complete so a material remainder must NOT yield deleted-open suspicion.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            )
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
            )
        ],
        error="permission denied",
    )

    provider = _recording_provider(
        {"/srv": _stat(size=200 * GIB, free_total=20 * GIB, avail_unprivileged=18 * GIB)},
        [],
    )

    diagnostic = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
        filesystem_scope_provider=lambda domain: False,  # indexed roots cover the filesystem
    )

    section = diagnostic.filesystems[0]
    assert "partial_snapshot_evidence" in section.coverage_reason_codes
    assert section.unattributed_bytes == 170 * GIB
    assert "deleted_open_file_suspected" not in section.likely_reasons


def test_complete_coverage_material_mismatch_emits_bounded_reasons_and_verification_commands(
    repo_root: Path, tmp_path: Path
) -> None:
    _db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    df_index = import_module(repo_root, "watchdirs.diagnostics.df_index")

    # Complete snapshot, indexed roots fully cover the filesystem, large remainder ->
    # deleted-open suspicion is allowed, plus verification-only commands.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv", disk_bytes=10 * GIB, apparent_bytes=9 * GIB, depth=0, parent_path=None
            )
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
            )
        ],
    )

    provider = _recording_provider(
        {"/srv": _stat(size=200 * GIB, free_total=20 * GIB, avail_unprivileged=18 * GIB)},
        [],
    )

    material = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
        filesystem_scope_provider=lambda domain: False,
    )
    section = material.filesystems[0]
    assert section.unattributed_bytes == 170 * GIB
    assert "deleted_open_file_suspected" in section.likely_reasons
    # Verification commands are checks only -- no destructive / process-control / docker mutation.
    commands = " ".join(section.verification_commands)
    assert "lsof +L1" in commands or "deleted-open-files" in commands
    forbidden = ("rm ", "kill", "docker builder prune", "docker image prune", "prune -af", "docker rmi")
    for token in forbidden:
        assert token not in commands

    # df used = 200 - 180 = 20 GiB; indexed 10 GiB; remainder 10 GiB but ratio 10/20=0.5 (material).
    # Use a tiny gap below the byte floor to verify the floor gate.
    tiny_provider = _recording_provider(
        {
            "/srv": _stat(
                size=200 * GIB, free_total=200 * GIB - (10 * GIB + 100 * 1024 * 1024), avail_unprivileged=180 * GIB
            )
        },
        [],
    )
    tiny = df_index.build_df_index_diagnostic(
        connection,
        snapshot_selector="latest",
        limit=20,
        stat_provider=tiny_provider,
        generated_at_provider=lambda: "2026-06-13T18:05:00Z",
        filesystem_scope_provider=lambda domain: False,
    )
    tiny_section = tiny.filesystems[0]
    # df used = 10 GiB + 100 MiB; indexed 10 GiB; remainder 100 MiB < 1 GiB floor -> not material.
    assert tiny_section.unattributed_bytes == 100 * 1024 * 1024
    assert tiny_section.likely_reasons == ()


def test_df_vs_index_cli_json_limit_truncates_and_emits_metadata(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)

    # Three distinct roots / domains so --limit 2 truncates to top-2 by df remainder.
    specs = [
        (Path("/srv"), "8:1", "/dev/root", b"/srv", 10 * GIB),
        (Path("/data"), "8:33", "/dev/data", b"/data", 5 * GIB),
        (Path("/opt"), "8:49", "/dev/opt", b"/opt", 2 * GIB),
    ]
    for root_path, major_minor, source, mount_point, disk_bytes in specs:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=root_path,
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:01:00Z",
            rows=[
                _directory_row(
                    models_module,
                    1,
                    os.fsencode(str(root_path)),
                    disk_bytes=disk_bytes,
                    apparent_bytes=disk_bytes,
                    depth=0,
                    parent_path=None,
                )
            ],
            mounts=[
                _mount(
                    models_module,
                    mount_id=10,
                    parent_id=1,
                    major_minor=major_minor,
                    root=b"/",
                    mount_point=mount_point,
                    filesystem_type="ext4",
                    mount_source=source,
                )
            ],
        )
    connection.close()

    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}:{env['PYTHONPATH']}"
    result = subprocess.run(
        ["python3", "-m", "watchdirs", "df-vs-index", "--db", str(db_path), "--json", "--limit", "2"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "df-vs-index"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert len(payload["filesystems"]) == 2
    assert payload["truncated"] is True
    assert "summary" in payload
    assert "warnings" in payload
    # Each section carries the required contract fields.
    for section in payload["filesystems"]:
        assert "indexed_visible_disk_bytes" in section
        assert "unattributed_bytes" in section
        assert "over_indexed_bytes" in section
        assert "filesystem_stat_available" in section
        assert "snapshot_ids" in section
