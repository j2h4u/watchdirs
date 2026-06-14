---
phase: 03-pressure-gap-diagnostics
fixed_at: 2026-06-14T00:00:00Z
review_path: .planning/phases/03-pressure-gap-diagnostics/03-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report (Iteration 2)

**Fixed at:** 2026-06-14
**Source review:** .planning/phases/03-pressure-gap-diagnostics/03-REVIEW.md
**Iteration:** 2

**Summary:**
- Findings in scope: 2 (Warning-severity; `fix_scope=critical_warning`)
- Fixed: 2
- Skipped: 0
- Out of scope (Info, not attempted): 2 (IN-01, IN-02)

Full suite green after both fixes: `uv run --with pytest pytest -q` -> 169 passed.

## Fixed Issues

### WR-01: WR-03 recent-growth wiring has no CLI-level regression test (can silently regress)

**Files modified:** `tests/test_cli_report_commands.py`
**Commit:** 6faa032
**Applied fix:** Added an end-to-end CLI regression test,
`test_report_storage_domain_growth_joins_into_pressure_summary_recent_growth`,
modeled on the existing `_seed_domain_pair` pressure-summary tests. It seeds a
storage-domain pair whose `/srv` root row grows 8 GiB -> 10 GiB, runs
`report --group-by storage-domain --json`, and asserts that:
1. the report `group_summary` attributes `disk_bytes_delta == 2 GiB` to the
   storage-domain key `8:1|/|ext4|/dev/root`, and
2. the `pressure_summary` section keyed by the *same* domain key carries
   `recent_growth_disk_bytes == 2 GiB`.

This locks the cross-path key contract between `queries._domain_key` (df/index
side) and `resolve_group_for_path`'s storage-domain branch (report group side).
Any drift in either key format, or in the `args.group_by == "storage-domain"`
gate, now fails this test instead of silently zeroing the growth column (the
original WR-03 regression). Verified green; this was a coverage gap, not a
present correctness defect, so no source change was required.

### WR-02: unknown-mount fallback can attribute the snapshot's unknown rows to a nested-submount domain

**Files modified:** `src/watchdirs/reporting/queries.py`, `tests/test_reporting_queries.py`
**Commit:** 4b9d1ea
**Status:** fixed: requires human verification (logic/attribution change)
**Applied fix:** In `query_indexed_storage_domain_totals`, when the snapshot
root path has no directory row (so it is absent from the resolved-domain map),
the unknown-mount count is now resolved against the persisted snapshot mounts via
`_longest_mount_prefix(root_path_bytes, snapshot_mounts)` -- i.e. the enclosing
root-filesystem domain -- rather than falling back to the lexicographically
lowest resolved key. The lowest-keyed fallback could charge the
incomplete-coverage signal (and its downstream `unknown_mount` warning /
`skipped_or_partial_scan_evidence` classification) to a nested submount domain
that may have complete coverage, leaving the actually-incomplete root-fs domain
looking clean. The lowest-keyed path is retained only as a last resort when no
mount prefixes the root, and now selects among domains resolved *in that
snapshot* (preserving the prior per-snapshot semantics). The target accumulator
is created on demand via `setdefault` because the enclosing root-fs domain may
have contributed no boundary/visible rows yet.

Added regression test
`test_query_indexed_storage_domain_totals_unknown_mount_falls_back_to_root_fs_not_lowest_key`:
seeds a snapshot with no `/srv` root row, a root-fs domain (`8:1|...` via
`/srv/data`), a nested submount whose key (`1:5|/|tmpfs|tmpfs`) sorts lexically
*below* the root-fs key (via `/srv/cache`), and one unresolved `/mystery` row.
It asserts the unknown count lands once on the root-fs domain and the submount
stays at 0. Confirmed the test FAILS under the pre-fix lowest-keyed behavior
(count landed on the `1:5` submount) and PASSES with the fix, so it genuinely
exercises the regression.

**Human verification note:** this is an attribution/logic change. The syntax and
test tiers confirm the structure and the targeted case, but a reviewer should
confirm the longest-mount-prefix-of-root choice is the intended attribution
target for all real-world unresolved-root shapes before the phase proceeds.

## Skipped Issues

None in scope. The two Info-level findings below were intentionally out of scope
(`fix_scope=critical_warning`) and were not attempted:

- **IN-01:** `_parse_size_text` mis-parses European decimal commas
  (`src/watchdirs/diagnostics/docker.py:93-98`). Carried over, unfixed.
- **IN-02:** df-index sections sorted twice; the second `reverse=True` sort
  flips the ascending key tie-break (`src/watchdirs/diagnostics/df_index.py:85-92`).
  Carried over, unfixed.

---

_Fixed: 2026-06-14_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
