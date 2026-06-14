---
phase: 03-pressure-gap-diagnostics
reviewed: 2026-06-14T00:00:00Z
depth: standard
iteration: 3
files_reviewed: 16
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/diagnostics/__init__.py
  - src/watchdirs/diagnostics/df_index.py
  - src/watchdirs/diagnostics/deleted_open.py
  - src/watchdirs/diagnostics/docker.py
  - src/watchdirs/diagnostics/summary.py
  - src/watchdirs/reporting/__init__.py
  - src/watchdirs/reporting/queries.py
  - src/watchdirs/reporting/render.py
  - tests/test_diagnostics_df_index.py
  - tests/test_diagnostics_deleted_open.py
  - tests/test_diagnostics_docker.py
  - tests/test_diagnostics_summary.py
  - tests/test_cli_report_commands.py
  - tests/test_reporting_queries.py
findings:
  critical: 0
  warning: 0
  info: 2
  status: clean
status: clean
---

# Phase 3: Code Review Report (Iteration 3, final pass)

**Reviewed:** 2026-06-14
**Depth:** standard
**Status:** clean

## Summary

Final re-review of the Phase 3 pressure-gap diagnostics after the iteration-2 fix
pass (WR-01 and WR-02). I verified both prior Warning findings against the current
source, traced the changed code paths for newly introduced defects, and ran the
test suite (scoped: 107 passed; full repo: 169 passed).

**Both prior Warning findings are resolved, and the fixes introduced no new
Critical or Warning defect.**

### WR-01 (no CLI regression test for the storage-domain growth join): RESOLVED

A genuine end-to-end lock now exists:
`test_report_storage_domain_growth_joins_into_pressure_summary_recent_growth`
(`tests/test_cli_report_commands.py:1768-1817`). It runs the real CLI
`report --group-by storage-domain --json`, asserts the report `group_summary`
attributes growth to the domain key `8:1|/|ext4|/dev/root` (via
`resolve_group_for_path`'s storage-domain branch), then asserts the
`pressure_summary` section keyed by the *same* domain key carries
`recent_growth_disk_bytes == 2 GiB` (via `queries._domain_key`). This exercises
both key-producing code paths through subprocess execution, so a drift in either
key format or in the `args.group_by == "storage-domain"` gate
(`cli.py:516-523`) now fails the suite instead of silently zeroing the growth
column. The lock is real, not a tautology: the two keys are computed by
independent functions and only meet at runtime through the CLI.

### WR-02 (unknown-mount fallback charged a nested submount instead of root-fs): RESOLVED

`query_indexed_storage_domain_totals` now resolves the snapshot root to its
enclosing root-filesystem domain via longest mount-prefix
(`queries.py:228-238`) instead of the lexicographically lowest resolved key.
When the root path has no directory row, `_longest_mount_prefix(root_path_bytes,
snapshot_mounts)` returns the enclosing root-fs mount, and the count is charged
there (creating the accumulator on demand if the root-fs domain had no visible
rows). The lowest-keyed path survives only as a last-resort fallback for the
genuinely-unresolvable case (`queries.py:239-249`). A targeted regression test,
`test_query_indexed_storage_domain_totals_unknown_mount_falls_back_to_root_fs_not_lowest_key`
(`tests/test_reporting_queries.py:741-834`), proves the count lands on the
root-fs domain (`8:1|...`) and *not* the lower-sorting submount (`1:5|...`),
including an explicit `submount_key < root_fs_key` sanity assertion so the test
cannot pass by accident of key ordering.

### Adversarial verification of the WR-02 fix (no new defects)

I traced the new code path for regressions and confirmed each is sound:

- **On-demand accumulator creation** (`queries.py:238`): when the root-fs domain
  contributed no boundary/visible rows (all visible rows live under a submount),
  `setdefault` creates a fresh accumulator with `disk_bytes=0`,
  `indexed_visible_path_count=0`, `unknown_mount_count=N`. This becomes a
  legitimate zero-byte output domain representing the root filesystem where the
  unknown rows physically live — consistent with the fix's documented intent, not
  a spurious phantom domain. `negative_total_clamped` stays `False` (0 is not
  `< 0`), so no false clamp warning is emitted (`queries.py:316-318`).
- **No KeyError in the lowest-keyed fallback** (`queries.py:249`):
  `resolved_keys` is built from the same non-`None` `domain_by_path.values()`
  that the visible-path-count loop already `setdefault`-inserted
  (`queries.py:206-211`), so `accumulators[resolved_keys[0]]` is always present.
- **`unknown_mount` warning / `skipped_or_partial_scan_evidence` attribution**
  (`df_index.py:138-148`, `df_index.py:288-289`) now follow the count to the
  correct root-fs domain, so the incomplete-coverage signal no longer lands on a
  fully-covered submount.
- **Once-per-snapshot semantics** preserved: the count is added to exactly one
  `target` accumulator (`queries.py:250-251`), so the WR-05 fix from iteration 1
  is not reintroduced.

The two prior iteration-2 Info items were explicitly declared out of scope for
this pass and are carried over unchanged below for continuity.

## Narrative Findings (AI reviewer)

## Info

### IN-01: `_parse_size_text` mis-parses European decimal commas (carried over, out of scope)

**File:** `src/watchdirs/diagnostics/docker.py:92-98`
**Issue:** Digits plus both `.` and `,` are accumulated, then
`number.replace(",", "")` strips commas, so a locale-formatted `1,5GB` becomes
`15GB` (10x). Docker's `--format json` is normally locale-neutral, so the risk is
low. Explicitly out of scope for iteration 3 per the review brief; recorded for
continuity only.
**Fix:** Reject inputs containing both `.` and `,`, or treat a lone `,` as a
decimal point when no `.` is present.

### IN-02: df-index sections sorted twice; second sort reverses the stable key tie-break (carried over, out of scope)

**File:** `src/watchdirs/diagnostics/df_index.py:85-92`
**Issue:** Sections are sorted ascending by `storage_domain.key`, then re-sorted
with `reverse=True` on `(available, unattributed_or_0)`. `reverse=True` flips the
order of equal-key runs, so the intended ascending key tie-break becomes
descending for ties. Deterministic but not the documented ordering; no test
depends on the tie order. Explicitly out of scope for iteration 3 per the review
brief; recorded for continuity only.
**Fix:** Use a single sort with a composite key (negate the descending fields)
instead of two passes.

---

_Reviewed: 2026-06-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard (iteration 3, final pass)_
