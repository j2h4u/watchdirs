---
phase: 04-scheduled-retention-operations
plan: 01
subsystem: cli
tags: [locking, sqlite, cli, operations, tdd, flock]

# Dependency graph
requires:
  - phase: 03.1-05
    provides: collect stderr-only observability and JSON purity contract
  - phase: 03.2-04
    provides: current collect/report CLI surface and schema version 4 baseline
provides:
  - "shared non-blocking writer lock helper derived from the SQLite database path"
  - "collect fail-fast lock conflict handling via stable operation_locked runtime errors"
  - "CLI and helper tests proving lock contention does not create extra snapshot rows"
affects: [phase-04-02-retention, phase-04-03-vacuum, systemd-journal-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "mutating operations derive a sibling lock file from the configured SQLite database path"
    - "lock contention is non-blocking and surfaces through the existing JSON/stderr runtime error envelope"

key-files:
  created:
    - src/watchdirs/ops_lock.py
    - tests/test_ops_locking.py
  modified:
    - src/watchdirs/cli.py

key-decisions:
  - "The shared writer lock path is derived as <db>.lock so manual and scheduled collect invocations contend on the same file."
  - "Only an actual held flock maps to operation_locked; lock-path filesystem failures stay database_error to preserve existing CLI behavior."

patterns-established:
  - "Pattern 1: acquire the shared operation lock before open_connection() on every mutating CLI path."
  - "Pattern 2: include both db_path and lock_path in lock-related runtime error context for JSON and journal visibility."

requirements-completed: [OPER-03]

# Metrics
duration: 7min
completed: 2026-06-17
status: complete
---

# Phase 04 Plan 01: Shared Writer Lock Summary

**Shared non-blocking `<db>.lock` writer guard for `collect`, with stable `operation_locked` JSON/stderr evidence and tests proving contention does not create extra snapshots**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-16T23:41:48Z
- **Completed:** 2026-06-16T23:48:42Z
- **Tasks:** 1 (TDD task with RED and GREEN commits)
- **Files modified:** 3

## Accomplishments
- Added `src/watchdirs/ops_lock.py` with a non-blocking `fcntl.flock(... LOCK_EX | LOCK_NB)` context manager and deterministic lock-path derivation from the SQLite database path.
- Wired `run_collect()` to acquire the shared lock before opening SQLite and to emit `operation_locked` through the existing runtime error envelope with both `db_path` and `lock_path`.
- Added lock-behavior coverage proving contention fails fast without creating a second snapshot row and that a later collect succeeds once the lock holder exits.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED-GREEN-REFACTOR shared fail-fast writer lock for collect** - `eb5db31` (test), `76accf1` (feat)

## Files Created/Modified
- `tests/test_ops_locking.py` - subprocess and helper tests for lock contention, deterministic sibling lock-path derivation, and lock release behavior.
- `src/watchdirs/ops_lock.py` - shared operation-lock helper with `OperationLocked`, `OperationLock`, `operation_lock_path_for_db()`, and `acquire_operation_lock()`.
- `src/watchdirs/cli.py` - collect integration that acquires the shared lock before SQLite access and surfaces lock conflicts through `_emit_runtime_error()`.

## Decisions Made
- Derived the lock file as a sibling of the selected database (`<db>.lock`) so manual runs and future scheduled runs automatically share the same contention boundary.
- Preserved the existing `database_error` contract for lock-path filesystem failures such as a non-directory DB parent; only an actual held lock returns `operation_locked`.
- Kept the lock on mutating work only; read-only commands remain unlocked per the plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored JSON database_error handling for invalid DB parent paths**
- **Found during:** Task 1 (RED-GREEN-REFACTOR shared fail-fast writer lock for collect)
- **Issue:** The first lock implementation raised an uncaught `FileExistsError` while creating the sibling lock path when `--db` pointed under a non-directory parent, causing a traceback instead of the existing JSON error envelope.
- **Fix:** Narrowed `acquire_operation_lock()` so only `BlockingIOError` maps to `OperationLocked`, and mapped lock-path `OSError` failures in `run_collect()` through `database_error` with `db_path` and `lock_path` context.
- **Files modified:** `src/watchdirs/ops_lock.py`, `src/watchdirs/cli.py`
- **Verification:** `uv run pytest tests/test_cli_collect.py tests/test_collect_observability.py tests/test_ops_locking.py -q -x`
- **Committed in:** `76accf1` (part of task commit)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 bug)
**Impact on plan:** The fix preserved pre-existing collect error semantics while keeping the new lock behavior intact. No scope creep.

## Issues Encountered
- The first GREEN pass satisfied the new locking tests but regressed an existing `database_error` path for invalid DB parents. The adjacent collect suite caught it immediately and the fix stayed inside the same task commit.

## TDD Gate Compliance
- RED gate commit present: `eb5db31` (`test(04-01): add failing writer-lock tests`)
- GREEN gate commit present: `76accf1` (`feat(04-01): add shared writer lock for collect`)
- REFACTOR: not required; the implementation stayed clean after the regression fix.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `OPER-03` is satisfied for `collect`, and the shared lock helper is ready for `prune` and `vacuum` reuse in Plans 04-02 and 04-03.
- No blockers found for the next plan.

## Self-Check: PASSED

- Files verified on disk: `.planning/phases/04-scheduled-retention-operations/04-01-SUMMARY.md`, `src/watchdirs/ops_lock.py`, `tests/test_ops_locking.py`
- Commits verified in git log: `eb5db31` (RED), `76accf1` (GREEN)

---
*Phase: 04-scheduled-retention-operations*
*Completed: 2026-06-17*
