---
phase: 02-growth-frontier-reporting
plan: 03
subsystem: reporting
tags: [python, sqlite, cli, reporting, pytest, diff]
requires:
  - phase: 02-02
    provides: top-reporting package seams, limit validation, and persisted grouping helpers
provides:
  - same-root `watchdirs diff --since ...` snapshot pairing with UTC timestamp validation
  - raw diff classifications plus compact growth-frontier pruning
  - diff JSON and terse text rendering with pair metadata, warnings, and grouping
affects: [phase-02-reporting, report, deleted, explain-path, diagnostics]
tech-stack:
  added: [python-stdlib]
  patterns: [same-root-diff-pairing, two-pass-frontier-pruning, diff-bytes-until-render]
key-files:
  created:
    - src/watchdirs/reporting/pairs.py
    - src/watchdirs/reporting/frontier.py
    - tests/test_frontier.py
  modified:
    - src/watchdirs/cli.py
    - src/watchdirs/models.py
    - src/watchdirs/reporting/__init__.py
    - src/watchdirs/reporting/queries.py
    - src/watchdirs/reporting/render.py
    - tests/test_reporting_queries.py
    - tests/test_cli_report_commands.py
key-decisions:
  - "Diff pairing uses each selected current snapshot's parsed UTC finished_at as the --since cutoff basis instead of wall-clock now."
  - "Growth frontier pruning runs in two passes so near-equal descendants can evict ancestors before surviving ancestors suppress lower-signal children."
  - "Diff rows keep raw BLOB path identity through query and pruning layers; render-time grouping reuses the existing persisted mount and top-level subtree helpers."
patterns-established:
  - "Pair-selection pattern: choose newest non-failed same-root current snapshots, reject invalid timestamps with warnings, and fall back to oldest earlier baselines only with explicit warning codes."
  - "Diff-report pattern: SQL normalizes previous/current/delta byte fields and Python applies global multi-root frontier pruning plus final limit."
requirements-completed: [REPT-01, REPT-06, REPT-07]
duration: 6min
completed: 2026-06-13
status: complete
---

# Phase 2 Plan 03: Same-root diff pairing and growth frontier Summary

**`watchdirs diff` now selects same-root snapshot pairs, classifies path deltas, and returns a compact multi-root growth frontier with explicit byte fields and warnings.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-13T18:57:58Z
- **Completed:** 2026-06-13T19:03:39Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added RED coverage for strict `--since` grammar, UTC-equivalent timestamp handling, same-root pair selection, raw diff classifications, frontier pruning, multi-root global limiting, and CLI diff JSON/grouping contracts.
- Added `pairs.py` and `frontier.py` plus new diff dataclasses so reporting can resolve same-root pairs, validate timestamps, and prune positive growth into next-step inspection targets.
- Wired `watchdirs diff` through the CLI, query layer, and renderer with stable JSON/text output, pair metadata, classification counts, warnings, and root/top-level-subtree/mount/storage-domain grouping.

## Verification

- `pytest tests/test_reporting_queries.py -q` -> `10 passed`
- `pytest tests/test_frontier.py -q` -> `2 passed`
- `pytest tests/test_cli_report_commands.py -q` -> `19 passed`
- `pytest -q` -> `89 passed`

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing diff pair, classification, and frontier tests** - `2daee43` (`test`)
2. **Task 2: Implement diff pair selection and frontier output** - `71c2632` (`feat`)

## Files Created/Modified

- `src/watchdirs/reporting/pairs.py` - Strict `--since` parsing, UTC `finished_at` parsing, and same-root pair selection with structured warnings.
- `src/watchdirs/reporting/frontier.py` - Two-pass compact frontier pruning with the explicit `0.95` dominance ratio.
- `src/watchdirs/reporting/queries.py` - Raw diff classification query that normalizes previous/current/delta fields and reuses grouping helpers.
- `src/watchdirs/reporting/render.py` - Stable diff JSON payload and terse text renderer with pair metadata and frontier rows.
- `src/watchdirs/cli.py` - Registers and executes `watchdirs diff` with JSON/runtime error envelopes matching the existing CLI style.
- `src/watchdirs/models.py` - Adds `SnapshotPair`, `DiffRow`, and `FrontierRow` dataclasses for the new report contracts.
- `tests/test_reporting_queries.py` - Locks pair selection, strict `--since` parsing, UTC handling, and all five REPT-06 classifications.
- `tests/test_frontier.py` - Locks the dominance-ratio pruning and same-root/same-pair suppression boundaries.
- `tests/test_cli_report_commands.py` - Locks the diff JSON envelope, warnings, grouping, limits, and no-pair errors.

## Decisions Made

- Pair selection ignores failed snapshots entirely, rejects missing/naive/unparseable `finished_at` values with `invalid_snapshot_timestamp`, and only emits `no_snapshot_pairs` after all roots are evaluated.
- Diff classifications come from one SQL CTE over the union of baseline/current BLOB paths so created/deleted/grown/shrunk/unchanged rows share one normalized shape.
- Frontier pruning happens after merging all valid same-root pair outputs, so the final limit is global across roots instead of pre-limited per root.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Contract] Corrected RED expectations that contradicted the explicit frontier ordering and root-label semantics**
- **Found during:** Task 2 (Implement diff pair selection and frontier output)
- **Issue:** Two RED assertions expected a root frontier row to survive an impossible single-chain pruning case and expected sibling ordering that contradicted the plan's `disk_bytes_delta DESC`, `depth DESC`, `path ASC` tie-break.
- **Fix:** Reworked the grouping fixture to prove `.` labels with an independently retained root row and aligned the frontier-order assertion with the documented tie-break contract.
- **Files modified:** `tests/test_cli_report_commands.py`, `tests/test_frontier.py`
- **Verification:** `pytest tests/test_frontier.py -q`, `pytest tests/test_cli_report_commands.py -q`, `pytest -q`
- **Committed in:** `71c2632`

---

**Total deviations:** 1 auto-fixed (`Rule 1: 1`)
**Impact on plan:** The adjustment tightened the RED contract around the plan's explicit pruning semantics without changing feature scope.

## Issues Encountered

- The pruning logic needed a two-pass implementation because a descendant can become the correct inspection target only after it evicts an already-retained ancestor. A greedy single-pass suppressor kept stale ancestors in the frontier.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- REPT-01 and REPT-06 are now satisfied, and the reporting package has reusable pair-selection and frontier helpers ready for `report`, `deleted`, and `explain-path`.
- Phase `02-04` can build on the normalized diff rows and global pair metadata instead of re-solving snapshot pairing or pruning behavior.

## Self-Check: PASSED

- Verified `.planning/phases/02-growth-frontier-reporting/02-03-SUMMARY.md` exists on disk.
- Verified commit `2daee43` exists in git history.
- Verified commit `71c2632` exists in git history.
