---
phase: 04-scheduled-retention-operations
plan: 03
subsystem: operations
tags: [sqlite, vacuum, cli, locking, maintenance, tdd]

# Dependency graph
requires:
  - phase: 04-01
    provides: shared non-blocking writer lock for mutating operations
  - phase: 04-02
    provides: explicit prune path and retention helper module
  - phase: 03.1-04
    provides: WAL checkpoint and VACUUM measurement caveats
provides:
  - "explicit locked watchdirs vacuum maintenance command"
  - "vacuum result metrics with before/after SQLite counters and advisory warnings"
  - "tests proving vacuum is separate from prune and fails fast on lock contention"
affects: [phase-04-04-systemd, operator-maintenance-verification, sqlite-compaction-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "explicit maintenance reuses open_connection() and the shared writer lock instead of adding an ad hoc SQLite path"
    - "vacuum reports advisory free-space risk and WAL checkpoint status as stable JSON fields"

key-files:
  created:
    - tests/test_ops_vacuum.py
  modified:
    - src/watchdirs/db/retention.py
    - src/watchdirs/cli.py

key-decisions:
  - "Vacuum stays a separate explicit command under the same operation lock as collect and prune."
  - "The maintenance advisory threshold is three times the current page_count * page_size, compared against os.statvfs() free bytes."
  - "Post-VACUUM output exposes wal_checkpoint(TRUNCATE) busy/log/checkpointed values and warns on busy or partial progress."

patterns-established:
  - "Pattern 1: mutating maintenance commands open SQLite through open_connection(), initialize schema, then delegate the DB operation to retention helpers."
  - "Pattern 2: prune and vacuum stay behaviorally separate; prune never triggers compaction as a hidden side effect."

requirements-completed: [OPER-05, OPER-03]

# Metrics
duration: 2min
completed: 2026-06-17
status: complete
---

# Phase 04 Plan 03: Explicit Vacuum Maintenance Summary

**Locked SQLite VACUUM maintenance with before/after page metrics, free-space advisory output, WAL checkpoint status, and regression coverage that keeps prune separate**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-17T00:08:04Z
- **Completed:** 2026-06-17T00:09:21Z
- **Tasks:** 1 (TDD task with RED and GREEN commits)
- **Files modified:** 3

## Accomplishments

- Extended `src/watchdirs/db/retention.py` with `VacuumResult` and `vacuum_database()`, capturing before/after page and freelist counters, advisory free-space fields, and `wal_checkpoint(TRUNCATE)` status.
- Added `watchdirs vacuum` to `src/watchdirs/cli.py` with `--db` and `--json`, reusing the shared operation lock, centralized SQLite opener, schema initialization, and runtime error envelope.
- Added `tests/test_ops_vacuum.py` covering direct maintenance behavior, CLI JSON output, lock contention, prune/vacuum separation, and warning fields for low free space plus busy/partial checkpoints.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED-GREEN-REFACTOR explicit locked SQLite vacuum command** - `614c522` (test), `23aafe4` (feat)

## Files Created/Modified

- `tests/test_ops_vacuum.py` - direct helper, CLI, warning, and separation coverage for vacuum maintenance.
- `src/watchdirs/db/retention.py` - `VacuumResult`, advisory free-space calculation, `VACUUM`, and post-vacuum checkpoint reporting.
- `src/watchdirs/cli.py` - `watchdirs vacuum` parser/handler wiring and JSON payload rendering.

## Decisions Made

- Kept compaction as an explicit off-path maintenance command so prune, collect, and reporting stay bounded and predictable.
- Computed the advisory free-space requirement from the current main-file page bytes rather than a guessed file-size shrink target, matching the plan’s SQLite guidance.
- Reported checkpoint busy/log/checkpointed values directly so operators can tell whether post-vacuum WAL truncation was complete without reading SQLite internals.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## TDD Gate Compliance

- RED gate commit present: `614c522` (`test(04-03): add failing vacuum maintenance tests`)
- GREEN gate commit present: `23aafe4` (`feat(04-03): add explicit vacuum maintenance command`)
- REFACTOR: not required; the GREEN implementation passed the targeted ops suite and adjacent prune/lock regression tests as-is.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Next Phase Readiness

- Phase 04-04 can schedule `watchdirs vacuum` as a separate slower unit/timer without adding more product code to the maintenance surface.
- Operator docs can now point at stable JSON fields for pre-run free-space risk and post-run checkpoint status.
- No blockers found for the next plan.

## Self-Check: PASSED

- Files verified on disk: `.planning/phases/04-scheduled-retention-operations/04-03-SUMMARY.md`, `src/watchdirs/db/retention.py`, `src/watchdirs/cli.py`, `tests/test_ops_vacuum.py`
- Commits verified in git log: `614c522` (RED), `23aafe4` (GREEN)
