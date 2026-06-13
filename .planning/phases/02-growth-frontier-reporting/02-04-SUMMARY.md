---
phase: 02-growth-frontier-reporting
plan: 04
subsystem: reporting
tags: [python, sqlite, cli, reporting, pytest, diff]
requires:
  - phase: 02-03
    provides: same-root diff pairing, growth frontier pruning, and grouping-ready diff rows
provides:
  - agent-usable `watchdirs report --since ...` investigation summaries
  - agent-usable `watchdirs deleted --since ...` baseline-only evidence
  - agent-usable `watchdirs explain-path PATH --since ...` subtree drill-down with residual math
affects: [phase-02-reporting, phase-03-diagnostics, report-contracts, explain-path]
tech-stack:
  added: [python-stdlib]
  patterns: [frontier-summary-slice, exact-path-drilldown, blob-safe-report-rendering]
key-files:
  created: []
  modified:
    - src/watchdirs/cli.py
    - src/watchdirs/models.py
    - src/watchdirs/reporting/__init__.py
    - src/watchdirs/reporting/frontier.py
    - src/watchdirs/reporting/queries.py
    - src/watchdirs/reporting/render.py
    - tests/test_cli_report_commands.py
    - tests/test_reporting_queries.py
    - tests/test_frontier.py
key-decisions:
  - "Report classification counts use all raw diff rows, but report delta totals and group summaries use the displayed non-overlapping frontier slice to avoid recursive parent-child double counting."
  - "Explain-path normalizes user input without resolving symlinks, converts the canonical path with `os.fsencode()`, and requires one exact indexed target under one selected root."
  - "Explain-path residual math subtracts only shown immediate-child recursive deltas; grandchildren shown by depth are context, not additional subtraction."
patterns-established:
  - "Reporting closeout pattern: CLI handlers stay thin while query helpers return raw BLOB-backed rows and render helpers own JSON/text envelopes."
  - "Exact drill-down pattern: same-root pair selection plus scoped warnings, subtree diff filtering, and deterministic child rendering for one target path."
requirements-completed: [REPT-02, REPT-04, REPT-05, REPT-06, REPT-07]
duration: 7min
completed: 2026-06-13
status: complete
---

# Phase 2 Plan 04: Reporting Command Surface Summary

**`watchdirs` now exposes the full Phase 2 incident workflow with compact report summaries, deleted-path evidence, and exact-path subtree drill-down over stored snapshot diffs.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-13T19:16:58Z
- **Completed:** 2026-06-13T19:23:36Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added RED coverage for `report`, `deleted`, and `explain-path`, including exact-path matching, residual math, grouping, terse text output, and the end-to-end diff incident workflow.
- Implemented the three missing CLI commands on top of the existing same-root pair selection, raw diff rows, persisted mount grouping, and frontier pruning from 02-03.
- Added report-summary aggregation that separates raw classification counts from non-overlapping frontier-slice totals, plus deleted-path queries and exact subtree drill-down helpers.

## Verification

- `pytest tests/test_cli_report_commands.py -q` -> `29 passed`
- `pytest tests/test_reporting_queries.py -q` -> `12 passed`
- `pytest tests/test_frontier.py -q` -> `4 passed`
- `pytest tests/test_cli_report_commands.py tests/test_reporting_queries.py tests/test_frontier.py tests/test_grouping.py -q` -> `52 passed`
- `pytest -q` -> `103 passed`

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing report, deleted, and explain-path tests** - `cd412c8` (`test`)
2. **Task 2: Implement report, deleted, and explain-path commands** - `1f193ff` (`feat`)
3. **Task 3: Run full Phase 2 verification** - captured by the docs closeout commit that records this summary and `.planning` state updates

## Files Created/Modified

- `src/watchdirs/cli.py` - Registers `report`, `deleted`, and `explain-path`, validates `--limit`/`--depth`, normalizes exact path input, scopes warnings, and emits JSON/text responses.
- `src/watchdirs/models.py` - Adds report-summary and explain-path result contracts while keeping diff rows BLOB-first with a cheap `path_bytes_hex` accessor.
- `src/watchdirs/reporting/queries.py` - Adds deleted-path queries, exact subtree diff filtering, and non-overlapping report-summary aggregation.
- `src/watchdirs/reporting/frontier.py` - Adds deterministic explain-path child selection and unshown-or-direct residual calculations.
- `src/watchdirs/reporting/render.py` - Adds stable JSON/text renderers for report, deleted, and explain-path payloads.
- `src/watchdirs/reporting/__init__.py` - Re-exports the new helpers and renderers through the reporting package seam.
- `tests/test_cli_report_commands.py` - Locks CLI contracts for the new commands plus the end-to-end diff incident workflow.
- `tests/test_reporting_queries.py` - Locks deleted-path query behavior and exact subtree diff retrieval.
- `tests/test_frontier.py` - Locks explain-path residual math and depth behavior.

## Decisions Made

- Exact path matching happens after same-root pair resolution and before rendering; paths outside all selected roots, inside multiple roots, or absent from the indexed union return structured JSON errors.
- Report JSON/text output stays compact and explicit: every comparison exposes baseline/current ids, timestamps, statuses, warning codes, previous/current/delta byte fields, and BLOB-safe path hex.
- Persisted snapshot-time mount metadata remains the source of truth for mount/storage-domain grouping; no historical grouping uses live mount inference.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- None during implementation after the RED test harness was aligned to fail on the missing 02-04 surface instead of fixture issues.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no external services, credentials, or manual environment steps are required.

## Next Phase Readiness

- Phase 2 now covers REPT-01 through REPT-07 with active tests and live CLI behavior, so Phase 3 can focus on `df` vs indexed totals, deleted-open-files diagnostics, and Docker/containerd enrichment.
- Deferred Phase 3 and Phase 4 items remained out of scope here: no `df` reconciliation, deleted-open-file diagnostics, Docker reclaimability advice, scheduling, retention, or capacity-planning output was added.

## Self-Check: PASSED

- Verified `.planning/phases/02-growth-frontier-reporting/02-04-SUMMARY.md` exists on disk.
- Verified commits `cd412c8` and `1f193ff` exist in git history.
