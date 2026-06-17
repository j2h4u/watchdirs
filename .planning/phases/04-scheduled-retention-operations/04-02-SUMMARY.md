---
phase: 04-scheduled-retention-operations
plan: 02
subsystem: database
tags: [sqlite, retention, pruning, cli, operations, tdd]

# Dependency graph
requires:
  - phase: 04-01
    provides: shared non-blocking writer lock for mutating operations
  - phase: 03.1-02
    provides: path dictionary schema that requires explicit orphan-path GC after snapshot cascades
  - phase: 03.2-01
    provides: schema version 4 baseline for retained directory rows
provides:
  - per-root tiered whole-snapshot retention selection across hourly, daily, and monthly windows
  - locked `watchdirs prune` CLI with stable JSON mutation output
  - orphan `paths` garbage collection after snapshot FK cascades
affects: [phase-04-03-vacuum, phase-04-04-systemd, operator-retention-verification]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - per-root retention selection uses UTC finished_at buckets and only promotes COMPLETE snapshots beyond the hourly window
    - prune mutates snapshots only, then garbage-collects orphan path-dictionary rows after FK cascades

key-files:
  created:
    - src/watchdirs/db/retention.py
    - tests/test_ops_retention.py
  modified:
    - src/watchdirs/cli.py

key-decisions:
  - "Tiered retention is computed per root_path from snapshot finished_at in UTC, keeping all statuses only inside the hourly window and promoting COMPLETE snapshots only for daily and monthly representatives."
  - "Prune deletes from snapshots only and relies on FK cascades for directory_sizes and snapshot_mounts before explicit orphan paths GC."
  - "Retention policy validation rejects non-positive or inverted windows before any delete set is computed."

patterns-established:
  - "Pattern 1: retention selectors return a whole-snapshot keep-set before any destructive SQL runs."
  - "Pattern 2: mutating prune CLI paths acquire the shared operation lock before opening SQLite and emit runtime failures through the existing JSON envelope."

requirements-completed: [OPER-04, OPER-03]

# Metrics
duration: 3min
completed: 2026-06-17
status: complete
---

# Phase 04 Plan 02: Tiered Retention Pruning Summary

**Locked `watchdirs prune` retention with per-root UTC hourly/daily/monthly snapshot selection, whole-snapshot deletes, and orphan path cleanup**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-16T23:58:18Z
- **Completed:** 2026-06-17T00:00:37Z
- **Tasks:** 1 (TDD task with RED and GREEN commits)
- **Files modified:** 3

## Accomplishments
- Added `src/watchdirs/db/retention.py` with `RetentionPolicy`, `PruneResult`, a per-root UTC keep-set selector, whole-snapshot prune execution, and orphan `paths` garbage collection.
- Added `watchdirs prune` to `src/watchdirs/cli.py` with `--db`, `--json`, `--hourly-days`, and `--daily-days`, reusing the shared operation lock and runtime error envelope.
- Added `tests/test_ops_retention.py` covering tiered retention selection, snapshot-only deletion boundaries, orphan-path GC, stable JSON output, lock contention, and second-run idempotency.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED-GREEN-REFACTOR tiered whole-snapshot prune command** - `1836ace` (test), `3b52658` (feat)

## Files Created/Modified
- `src/watchdirs/db/retention.py` - retention policy validation, keep-set selection, prune execution, and orphan path GC helpers.
- `src/watchdirs/cli.py` - prune command registration, shared-lock acquisition, JSON payload rendering, and runtime error handling.
- `tests/test_ops_retention.py` - deterministic schema-version-4 retention fixtures and CLI/integration coverage for prune behavior.

## Decisions Made
- Used `finished_at` timestamps in UTC as the retention bucketing boundary so daily and monthly representatives are deterministic across roots.
- Kept aged `PARTIAL` and `FAILED` snapshots only inside the hourly window; they are deleted instead of being promoted into daily or monthly representatives.
- Scoped destructive SQL to `snapshots` plus post-cascade orphan `paths` cleanup so child row removal remains the responsibility of SQLite foreign-key cascades.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## TDD Gate Compliance

- RED gate commit present: `1836ace` (`test(04-02): add failing retention prune tests`)
- GREEN gate commit present: `3b52658` (`feat(04-02): add snapshot retention prune command`)
- REFACTOR: not required; the GREEN implementation passed targeted and adjacent CLI regression coverage as-is.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The shared writer lock now covers both `collect` and `prune`, so Phase 04-03 can reuse the same pattern for `vacuum`.
- Retention JSON outputs now expose exact deleted snapshot IDs and counts, which Phase 04-04 can reference in operator verification docs.
- No blockers found for the next plan.

## Self-Check: PASSED

- Files verified on disk: `.planning/phases/04-scheduled-retention-operations/04-02-SUMMARY.md`, `src/watchdirs/db/retention.py`, `tests/test_ops_retention.py`
- Commits verified in git log: `1836ace` (RED), `3b52658` (GREEN)
