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

from pathlib import Path
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
