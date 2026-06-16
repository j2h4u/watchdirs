"""Wave-0 test for the size harness (D-08 method A / D-10).

Pins, on small deterministic fixtures (~3 synthetic snapshots), the
measurement-integrity contract the full ~412-snapshot operator benchmark
relies on:

- Both the OLD-BLOB baseline DB and the NEW-DICT DB are built with IDENTICAL
  ``page_size`` / ``journal_mode`` / ``auto_vacuum`` PRAGMAs (Pitfall 4 guard).
- After ``VACUUM``, ``page_count*page_size == os.path.getsize()`` for EACH DB
  (the WAL-not-checkpointed reconciliation, Don't-Hand-Roll).
- The NEW dbstat per-object breakdown counts ``sqlite_autoindex_paths_1`` in the
  total (Pitfall 6: the UNIQUE autoindex re-stores the path bytes).
- For a low-churn fixture, the NEW total is directionally smaller than OLD.
- The D-09 gate evaluator is a pure function: PASS under budget, FAIL over, and
  the reduction ratio is reported as color, not gated on.

The FULL ~412-snapshot benchmark + the cold/warm duration leg are the operator's
manual run (see the Plan 04 human-verify checkpoint), NOT this unit suite.
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import sys


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


# Realistic path lengths matter: the dictionary win comes from NOT re-storing the
# full path bytes in every snapshot. With unrealistically short paths the fixed
# dictionary overhead (separate paths table + UNIQUE autoindex) dominates and the
# win only appears at huge snapshot counts. A representative deep path keeps the
# fixture small while still demonstrating the win the operator's 412-snapshot run
# measures at full scale.
_PARENT = b"/var/lib/some/service/data/cache/objects"


def _scan_rows(models_module, count: int) -> list:
    """A tiny synthetic 'real scan': ``count`` rows under one deep root."""
    rows = []
    for i in range(count):
        rows.append(
            models_module.DirectoryAggregate(
                snapshot_id=0,  # replaced per synthetic snapshot by the harness
                path=_PARENT + b"/segment%05d" % i,
                parent_path=_PARENT,
                depth=8,
                apparent_bytes=4096 * (i + 1),
                disk_bytes=4096 * (i + 1),
                file_count=i,
                dir_count=1,
                error=None,
            )
        )
    return rows


def _aggregate_row(
    models_module,
    path: bytes,
    *,
    parent_path: bytes | None,
    depth: int,
    disk_bytes: int = 0,
    apparent_bytes: int = 0,
    collapsed: bool = False,
    top_child_path: bytes | None = None,
    top_child_disk_bytes: int | None = None,
):
    return models_module.DirectoryAggregate(
        snapshot_id=0,
        path=path,
        parent_path=parent_path,
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=0,
        dir_count=0,
        error=None,
        collapsed=collapsed,
        top_child_path=top_child_path,
        top_child_disk_bytes=top_child_disk_bytes,
    )


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


def _rows_by_path(rows) -> dict[bytes, object]:
    return {row.path: row for row in rows}


def _root_row(scan_result):
    return scan_result.rows[-1]


def _real_collapse_fixture(root: Path) -> tuple[Path, Path, Path, int]:
    noisy = root / "node_modules"
    large_package = noisy / "large-package"
    nested = large_package / "nested"
    nested.mkdir(parents=True)
    (nested / "payload.bin").write_bytes(b"x" * 32768)

    collapsed_dirs = 2
    for index in range(200):
        package = noisy / f"pkg-{index:02d}"
        package.mkdir(parents=True)
        (package / "payload.txt").write_text(f"payload-{index}", encoding="utf-8")
        collapsed_dirs += 1

    stable = root / "stable" / "keep"
    stable.mkdir(parents=True)
    (stable / "keep.txt").write_text("stable", encoding="utf-8")
    return noisy, large_package, nested, collapsed_dirs


def test_identical_pragmas_reconciliation_autoindex_and_win(
    repo_root: Path, tmp_path: Path
) -> None:
    """OLD vs NEW: identical PRAGMAs, post-VACUUM reconciliation, autoindex counted, NEW < OLD."""
    size = import_module(repo_root, "watchdirs.bench.size")
    models_module = import_module(repo_root, "watchdirs.models")

    base_rows = _scan_rows(models_module, 300)

    comparison = size.compare_old_vs_new(
        base_rows,
        snapshots=8,  # enough recurrence to amortize the dictionary's fixed overhead
        churn=0.02,  # low churn -> the dictionary win exists, directionally
        workdir=tmp_path,
    )

    old = comparison.old
    new = comparison.new

    # (a) IDENTICAL build PRAGMAs on both DBs (Pitfall 4).
    assert old.pragmas == new.pragmas
    assert old.pragmas["page_size"] == new.pragmas["page_size"]
    assert old.pragmas["journal_mode"] == new.pragmas["journal_mode"]
    assert old.pragmas["auto_vacuum"] == new.pragmas["auto_vacuum"]

    # (b) Post-VACUUM reconciliation: page_count*page_size == stat() for EACH DB.
    assert old.page_bytes == old.stat_bytes
    assert new.page_bytes == new.stat_bytes

    # (c) NEW dbstat breakdown counts the UNIQUE autoindex (Pitfall 6).
    new_objects = {entry.name for entry in new.dbstat}
    assert "sqlite_autoindex_paths_1" in new_objects
    autoindex_bytes = sum(
        entry.pgsize for entry in new.dbstat if entry.name == "sqlite_autoindex_paths_1"
    )
    assert autoindex_bytes > 0
    # The autoindex cost is part of the measured NEW total: the dbstat page sum
    # accounts for all but the auto_vacuum(FULL) pointer-map/freelist overhead
    # pages (which dbstat's aggregate view does not attribute to a named object),
    # so it equals page_bytes to within that fixed page overhead -- never more.
    dbstat_sum = sum(entry.pgsize for entry in new.dbstat)
    assert dbstat_sum <= new.page_bytes
    assert new.page_bytes - dbstat_sum < new.pragmas["page_size"] * 4

    # (d) The win exists directionally for a low-churn fixture.
    assert new.page_bytes < old.page_bytes
    assert comparison.per_snapshot_bytes > 0


def test_evaluate_byte_budget_pass_fail_and_ratio_is_color(repo_root: Path) -> None:
    """D-09 gate: PASS under budget, FAIL over; ratio reported separately (not the gate)."""
    size = import_module(repo_root, "watchdirs.bench.size")

    under = size.evaluate_byte_budget(per_snapshot_bytes=800, budget_bytes=1000)
    assert under.verdict == "PASS"
    assert under.passed is True

    over = size.evaluate_byte_budget(per_snapshot_bytes=1200, budget_bytes=1000)
    assert over.verdict == "FAIL"
    assert over.passed is False

    # Exactly on budget is within budget (<=).
    boundary = size.evaluate_byte_budget(per_snapshot_bytes=1000, budget_bytes=1000)
    assert boundary.verdict == "PASS"


def test_reduction_ratio_is_reported_as_color_not_gated(repo_root: Path) -> None:
    """The reduction ratio is descriptive color, computed independently of PASS/FAIL."""
    size = import_module(repo_root, "watchdirs.bench.size")

    # NEW is half of OLD -> 2.0x reduction. Reported, never gated on.
    ratio = size.reduction_ratio(old_bytes=2000, new_bytes=1000)
    assert ratio == 2.0

    # A FAIL verdict still carries an honest ratio (color), proving ratio != gate.
    result = size.evaluate_byte_budget(per_snapshot_bytes=1200, budget_bytes=1000)
    assert result.verdict == "FAIL"
    assert size.reduction_ratio(old_bytes=1500, new_bytes=1200) == 1500 / 1200


def test_rerun_in_same_workdir_is_idempotent(repo_root: Path, tmp_path: Path) -> None:
    """A second build in the SAME workdir must rebuild from scratch, not append.

    Regression (caught at the Plan 04 operator gate): the scratch DBs
    (``bench_new.sqlite3`` / ``bench_old.sqlite3``) are built with
    ``CREATE TABLE IF NOT EXISTS`` and were never deleted first, so a prior — or
    crashed/timed-out — run's rows were silently appended to on the next run. That
    inflated the NEW side (its path dictionary accumulated BOTH runs' paths) and
    produced a false "dictionary is 16x bigger" result. Each build MUST start from
    an empty file so the measurement is idempotent and a crashed run cannot poison
    the next one.
    """
    size = import_module(repo_root, "watchdirs.bench.size")
    models_module = import_module(repo_root, "watchdirs.models")
    base_rows = _scan_rows(models_module, 200)

    first = size.compare_old_vs_new(base_rows, snapshots=5, churn=0.0, workdir=tmp_path)
    second = size.compare_old_vs_new(base_rows, snapshots=5, churn=0.0, workdir=tmp_path)

    # Byte-for-byte identical: the second run did not append to the first.
    assert second.new.page_bytes == first.new.page_bytes
    assert second.old.page_bytes == first.old.page_bytes

    # The path dictionary holds only the base path set, not an accumulated 2x.
    def _autoindex_cells(comparison) -> int:
        return sum(
            entry.ncell
            for entry in comparison.new.dbstat
            if entry.name == "sqlite_autoindex_paths_1"
        )

    assert _autoindex_cells(second) == _autoindex_cells(first)


def test_replicate_snapshots_keeps_leaf_churn_hierarchy_valid(repo_root: Path) -> None:
    size = import_module(repo_root, "watchdirs.bench.size")
    models_module = import_module(repo_root, "watchdirs.models")

    base_rows = [
        _aggregate_row(
            models_module,
            b"/root",
            parent_path=None,
            depth=0,
            disk_bytes=100,
            apparent_bytes=100,
            top_child_path=b"/root/cache/leaf",
            top_child_disk_bytes=30,
        ),
        _aggregate_row(
            models_module,
            b"/root/cache",
            parent_path=b"/root",
            depth=1,
            disk_bytes=60,
            apparent_bytes=60,
            collapsed=True,
            top_child_path=b"/root/cache/leaf",
            top_child_disk_bytes=30,
        ),
        _aggregate_row(
            models_module,
            b"/root/cache/leaf",
            parent_path=b"/root/cache",
            depth=2,
            disk_bytes=30,
            apparent_bytes=30,
        ),
        _aggregate_row(
            models_module,
            b"/root/logs",
            parent_path=b"/root",
            depth=1,
            disk_bytes=20,
            apparent_bytes=20,
        ),
    ]

    replicated = size.replicate_snapshots(base_rows, snapshots=2, churn=0.5)

    assert [row.path for row in replicated[0]] == [row.path for row in base_rows]

    snapshot_one = replicated[1]
    rows_by_path = _rows_by_path(snapshot_one)
    assert b"/root" in rows_by_path
    assert b"/root/cache" in rows_by_path
    assert b"/root/cache/leaf" not in rows_by_path
    assert b"/root/logs" not in rows_by_path
    assert all(row.parent_path is None or row.parent_path in rows_by_path for row in snapshot_one)

    rotated_leaf = next(row for row in snapshot_one if row.parent_path == b"/root/cache")
    rotated_logs = next(row for row in snapshot_one if row.parent_path == b"/root" and row.path != b"/root/cache")
    assert rotated_leaf.path.startswith(b"/root/cache/churn-s00001-")
    assert rotated_logs.path.startswith(b"/root/churn-s00001-")
    assert rows_by_path[b"/root"].top_child_path == rotated_leaf.path
    assert rows_by_path[b"/root/cache"].top_child_path == rotated_leaf.path


def test_compare_uncollapsed_vs_collapsed_uses_real_scan_root_and_product_schema(
    import_watchdirs_module,
    repo_root: Path,
    tmp_path: Path,
) -> None:
    size = import_module(repo_root, "watchdirs.bench.size")
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")

    root = tmp_path / "root"
    noisy, large_package, nested, collapsed_dirs = _real_collapse_fixture(root)

    no_collapse_policy = _collapse_policy(
        import_watchdirs_module,
        names=frozenset(),
        fan_out=1_000_000_000,
        descendants=1_000_000_000,
    )
    collapsed_policy = _collapse_policy(
        import_watchdirs_module,
        names=frozenset({"node_modules"}),
        fan_out=1_000_000_000,
        descendants=1_000_000_000,
    )

    uncollapsed = scanner.scan_root(models.ScannerOptions(root=root, collapse_policy=no_collapse_policy))
    collapsed = scanner.scan_root(models.ScannerOptions(root=root, collapse_policy=collapsed_policy))

    uncollapsed_rows = _rows_by_path(uncollapsed.rows)
    collapsed_rows = _rows_by_path(collapsed.rows)
    noisy_raw = os.fsencode(noisy)
    large_raw = os.fsencode(large_package)
    nested_raw = os.fsencode(nested)

    assert _root_row(collapsed).apparent_bytes == _root_row(uncollapsed).apparent_bytes
    assert _root_row(collapsed).disk_bytes == _root_row(uncollapsed).disk_bytes
    assert _root_row(collapsed).file_count == _root_row(uncollapsed).file_count
    assert _root_row(collapsed).dir_count == _root_row(uncollapsed).dir_count
    assert collapsed.row_count < uncollapsed.row_count
    assert noisy_raw in collapsed_rows
    assert large_raw not in collapsed_rows
    assert nested_raw not in collapsed_rows
    assert collapsed_rows[noisy_raw].collapsed is True
    assert collapsed_rows[noisy_raw].collapse_reason == "known_noise"
    assert collapsed_rows[noisy_raw].collapsed_dirs == collapsed_dirs
    assert collapsed_rows[noisy_raw].top_child_path == large_raw
    assert collapsed_rows[noisy_raw].top_child_disk_bytes == uncollapsed_rows[large_raw].disk_bytes

    comparison = size.compare_uncollapsed_vs_collapsed(
        uncollapsed.rows,
        collapsed.rows,
        snapshots=6,
        churn=0.0,
        workdir=tmp_path / "collapse-proof",
    )

    assert comparison.uncollapsed_row_count == uncollapsed.row_count
    assert comparison.collapsed_row_count == collapsed.row_count
    assert comparison.row_count_reduction_ratio > 1.0
    assert comparison.per_snapshot_bytes_reduction_ratio > 1.0
    assert comparison.collapsed.page_bytes < comparison.uncollapsed.page_bytes

    collapsed_db = sqlite3.connect(tmp_path / "collapse-proof" / "collapsed.sqlite3")
    collapsed_db.row_factory = sqlite3.Row
    try:
        assert int(collapsed_db.execute("PRAGMA user_version").fetchone()[0]) == 4
        persisted = collapsed_db.execute(
            """
            SELECT ds.collapsed, ds.collapse_reason, ds.collapsed_dirs,
                   ds.top_child_disk_bytes, tp.path AS top_child_path
            FROM directory_sizes ds
            JOIN paths p ON p.id = ds.path_id
            LEFT JOIN paths tp ON tp.id = ds.top_child_id
            WHERE p.path = ?
            """,
            (sqlite3.Binary(noisy_raw),),
        ).fetchone()
    finally:
        collapsed_db.close()

    assert persisted is not None
    assert int(persisted["collapsed"]) == 1
    assert persisted["collapse_reason"] == "known_noise"
    assert int(persisted["collapsed_dirs"]) == collapsed_dirs
    assert bytes(persisted["top_child_path"]) == large_raw
    assert int(persisted["top_child_disk_bytes"]) == uncollapsed_rows[large_raw].disk_bytes

    loaded_rows = size._load_real_scan_rows(str(tmp_path / "collapse-proof" / "collapsed.sqlite3"))
    loaded_rows_by_path = _rows_by_path(loaded_rows)
    assert loaded_rows_by_path[noisy_raw].collapsed is True
    assert loaded_rows_by_path[noisy_raw].collapse_reason == "known_noise"
    assert loaded_rows_by_path[noisy_raw].collapsed_dirs == collapsed_dirs
    assert loaded_rows_by_path[noisy_raw].top_child_path == large_raw
    assert loaded_rows_by_path[noisy_raw].top_child_disk_bytes == uncollapsed_rows[large_raw].disk_bytes
