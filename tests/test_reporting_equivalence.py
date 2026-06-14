"""Golden-equivalence harness for the path-dictionary report rewrite (D-01).

These tests pin the EXACT row values that ``query_diff_rows``, ``query_top_rows``
and ``query_indexed_storage_domain_totals`` produced before the BLOB-column
SELECTs were rewritten to ``JOIN paths`` on the integer ``path_id`` dictionary.
The expected values are hard-coded golden constants derived by hand from the
fixture, so they pin behaviour regardless of the SQL shape under test (they are
NOT recomputed from the same query). A non-UTF-8 path is carried through diff and
top to prove the join is byte-lossless.

The fixture builders (``_open_db``, ``_seed_snapshot``, ``_directory_row``,
``_mount``) are reused from ``tests.test_reporting_queries`` so the two suites
stay in lockstep -- ``_directory_row`` there already drops ``name=`` per Plan 02.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

# Reuse the canonical fixture builders from the sibling reporting suite.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reporting_queries import (  # noqa: E402
    _directory_row,
    _mount,
    _open_db,
    _seed_snapshot,
    import_module,
)


# A deliberately non-UTF-8 path: it must round-trip byte-exact through the JOIN.
_NON_UTF8_PATH = b"/srv/bad-\xff-dir"


def _build_two_snapshot_fixture(connection, migrations_module, models_module):
    """Two snapshots of /srv covering created/deleted/grown/shrunk/unchanged.

    /srv/new      -> created
    /srv/gone     -> deleted
    /srv/grow     -> grown
    /srv/shrink   -> shrunk
    /srv/same     -> unchanged
    _NON_UTF8_PATH-> grown (also asserts byte-exact round-trip)
    """

    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/srv/grow", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/shrink", disk_bytes=60, apparent_bytes=60, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, _NON_UTF8_PATH, disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"),
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
            _directory_row(models_module, 1, b"/srv", disk_bytes=255, apparent_bytes=225, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/srv/grow", disk_bytes=90, apparent_bytes=85, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/shrink", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/new", disk_bytes=25, apparent_bytes=25, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/same", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, _NON_UTF8_PATH, disk_bytes=55, apparent_bytes=50, depth=1, parent_path=b"/srv"),
        ],
    )
    return baseline_id, current_id


def _pair(models_module, baseline_id: int, current_id: int):
    return models_module.SnapshotPair(
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


# Golden diff expectations: (classification, previous_disk, current_disk,
# disk_delta, parent_path). Hand-derived from the fixture, NOT recomputed.
_GOLDEN_DIFF = {
    b"/srv": ("grown", 200, 255, 55, None),
    b"/srv/grow": ("grown", 40, 90, 50, b"/srv"),
    b"/srv/shrink": ("shrunk", 60, 10, -50, b"/srv"),
    b"/srv/gone": ("deleted", 20, 0, -20, b"/srv"),
    b"/srv/new": ("created", 0, 25, 25, b"/srv"),
    b"/srv/same": ("unchanged", 30, 30, 0, b"/srv"),
    _NON_UTF8_PATH: ("grown", 10, 55, 45, b"/srv"),
}


def test_diff_rows_match_golden_and_int_equality_ordering(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id, current_id = _build_two_snapshot_fixture(connection, migrations_module, models_module)
    pair = _pair(models_module, baseline_id, current_id)

    rows, warnings = queries.query_diff_rows(connection, pair=pair, group_by="root")

    assert warnings == ()
    by_path = {row.path: row for row in rows}
    assert set(by_path) == set(_GOLDEN_DIFF)

    for path, (classification, prev_disk, curr_disk, delta, parent_path) in _GOLDEN_DIFF.items():
        row = by_path[path]
        assert row.classification == classification, path
        assert row.previous_disk_bytes == prev_disk, path
        assert row.current_disk_bytes == curr_disk, path
        assert row.disk_bytes_delta == delta, path
        assert row.parent_path == parent_path, path

    # Exact ORDER BY: disk_bytes_delta DESC, depth DESC, path ASC. The deltas are
    # /srv=+55(d0), grow=+50(d1), _NON_UTF8=+45(d1), new=+25(d1), same=0(d1),
    # gone=-20(d1), shrink=-50(d1). Hand-derived golden ordering:
    expected_order = [
        b"/srv",            # +55
        b"/srv/grow",       # +50
        _NON_UTF8_PATH,     # +45
        b"/srv/new",        # +25
        b"/srv/same",       # 0
        b"/srv/gone",       # -20
        b"/srv/shrink",     # -50
    ]
    assert [row.path for row in rows] == expected_order


def test_non_utf8_path_round_trips_byte_exact_through_diff(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    baseline_id, current_id = _build_two_snapshot_fixture(connection, migrations_module, models_module)
    pair = _pair(models_module, baseline_id, current_id)

    rows, _ = queries.query_diff_rows(connection, pair=pair, group_by="root")
    by_path = {row.path: row for row in rows}

    assert _NON_UTF8_PATH in by_path
    row = by_path[_NON_UTF8_PATH]
    assert isinstance(row.path, bytes)
    assert row.path == _NON_UTF8_PATH  # byte-exact, no lossy decode through JOIN
    assert row.parent_path == b"/srv"


# Golden top expectations for the current snapshot, ordered disk_bytes DESC,
# path ASC. Hand-derived from the current-snapshot fixture rows.
_GOLDEN_TOP_ORDER = [
    b"/srv",            # 255
    b"/srv/grow",       # 90
    _NON_UTF8_PATH,     # 55
    b"/srv/same",       # 30
    b"/srv/new",        # 25
    b"/srv/shrink",     # 10
]
_GOLDEN_TOP_DISK = {
    b"/srv": 255,
    b"/srv/grow": 90,
    _NON_UTF8_PATH: 55,
    b"/srv/same": 30,
    b"/srv/new": 25,
    b"/srv/shrink": 10,
}


def test_top_rows_match_golden_order_and_disk_bytes(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    _, current_id = _build_two_snapshot_fixture(connection, migrations_module, models_module)

    rows, warnings = queries.query_top_rows(
        connection, snapshot_id=current_id, limit=20, group_by="root"
    )

    assert warnings == ()
    assert [row.path for row in rows] == _GOLDEN_TOP_ORDER
    for row in rows:
        assert row.current_disk_bytes == _GOLDEN_TOP_DISK[row.path], row.path
    # Non-UTF-8 path survives the top JOIN byte-exact.
    non_utf8 = next(row for row in rows if row.path == _NON_UTF8_PATH)
    assert isinstance(non_utf8.path, bytes)


def test_storage_domain_totals_match_golden_two_domain_layout(repo_root: Path, tmp_path: Path) -> None:
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    queries = import_module(repo_root, "watchdirs.reporting.queries")

    # One root /srv on the root filesystem, with a nested submount at
    # /srv/data on a different storage domain. Boundary rows: /srv (root-fs)
    # and /srv/data (submount); /srv/data is subtracted from the enclosing
    # root-fs domain so the two domains do not double-count.
    mounts = [
        _mount(
            models_module,
            mount_id=1,
            parent_id=0,
            major_minor="8:1",
            root=b"/",
            mount_point=b"/srv",
            filesystem_type="ext4",
            mount_source="/dev/sda1",
        ),
        _mount(
            models_module,
            mount_id=2,
            parent_id=1,
            major_minor="8:16",
            root=b"/",
            mount_point=b"/srv/data",
            filesystem_type="xfs",
            mount_source="/dev/sdb1",
        ),
    ]
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/srv/data", disk_bytes=40, apparent_bytes=35, depth=1, parent_path=b"/srv"),
        ],
        mounts=mounts,
    )

    totals = queries.query_indexed_storage_domain_totals(connection, snapshot_selector="latest")

    by_fs = {total.storage_domain.filesystem_type: total for total in totals}
    assert set(by_fs) == {"ext4", "xfs"}
    # ext4 root-fs domain: /srv boundary (100) minus the nested xfs submount (40).
    assert by_fs["ext4"].indexed_visible_disk_bytes == 60
    assert by_fs["ext4"].indexed_visible_apparent_bytes == 55
    # xfs submount domain: the /srv/data boundary aggregate stands alone.
    assert by_fs["xfs"].indexed_visible_disk_bytes == 40
    assert by_fs["xfs"].indexed_visible_apparent_bytes == 35
    # Ordering: disk_bytes DESC -> ext4 (60) before xfs (40).
    assert [t.storage_domain.filesystem_type for t in totals] == ["ext4", "xfs"]
