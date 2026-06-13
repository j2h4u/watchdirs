---
phase: 02-growth-frontier-reporting
plan: 01
subsystem: database
tags: [python, sqlite, mountinfo, pytest, reporting]
requires:
  - phase: 01-04
    provides: trusted snapshot collection, mountinfo parsing, and mount-policy semantics
provides:
  - persisted snapshot-time mount metadata for future filesystem and storage-domain grouping
  - schema version 2 migration with snapshot_mounts indexes and BLOB mount paths
  - collect-time transactional mount persistence with rollback-safe finalization
affects: [phase-02-reporting, collect, reporting-grouping]
tech-stack:
  added: [python-stdlib]
  patterns: [snapshot-mount-evidence, transactional-collect-persistence]
key-files:
  created:
    - tests/test_grouping.py
  modified:
    - src/watchdirs/models.py
    - src/watchdirs/db/schema.sql
    - src/watchdirs/db/migrations.py
    - src/watchdirs/cli.py
    - tests/test_cli_collect.py
key-decisions:
  - "Persist storage-domain identity from major_minor, root, filesystem_type, and mount_source while keeping mount_id only as snapshot-local debug/display context."
  - "Keep the snapshot row durable, but make directory rows, snapshot_mount rows, and successful finalization commit as one per-root transaction."
  - "Preserve Phase 1 monkeypatched helper seams by tolerating persistence helpers that do not accept the new commit keyword."
patterns-established:
  - "Mount persistence pattern: store root and mount_point as SQLite BLOB values and round-trip them as raw bytes."
  - "Collect transaction pattern: rollback directory/mount inserts first, then record failed snapshot state in a separate committed update."
requirements-completed: [REPT-07]
duration: 6min
completed: 2026-06-13
status: complete
---

# Phase 2 Plan 01: Persist snapshot-time mount metadata for storage-domain grouping Summary

**Schema v2 now stores snapshot-time mount evidence with BLOB path fidelity and collect persists it transactionally so later reports can group by mount or storage domain without live-only inference.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-13T18:24:47Z
- **Completed:** 2026-06-13T18:30:29Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added RED coverage for schema v2 mount persistence, v1 migration/idempotence, mount-id reuse, cascade cleanup, CLI collect wiring, and rollback on mount-row failure.
- Added `SnapshotMount`, `snapshot_mounts`, schema version 2 migrations, and `insert_snapshot_mounts` / `load_snapshot_mounts` helpers with BLOB storage for `root` and `mount_point`.
- Updated `collect` to persist mount rows from the same mount table used by `scan_root` and to commit directory rows, mount rows, and successful finalization in one transaction.

## Verification

- `pytest tests/test_grouping.py -q` -> `7 passed`
- `pytest tests/test_db_schema.py -q` -> `5 passed`
- `pytest tests/test_cli_collect.py -q` -> `25 passed`
- `pytest -q` -> `58 passed`

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing persisted grouping tests** - `6122c38` (`test`)
2. **Task 2: Implement snapshot_mounts persistence** - `e23cd4b` (`feat`)

## Files Created/Modified

- `tests/test_grouping.py` - REPT-07 regression coverage for mount persistence, migration safety, cascade delete, and collect rollback.
- `src/watchdirs/models.py` - Adds the frozen `SnapshotMount` dataclass for persisted snapshot-time mount evidence.
- `src/watchdirs/db/schema.sql` - Extends the schema with `snapshot_mounts` and indexes for snapshot, mount-point, and durable storage-domain lookup.
- `src/watchdirs/db/migrations.py` - Advances schema version to 2, preserves v1 data, and adds snapshot mount insert/load helpers plus transaction-compatible commits.
- `src/watchdirs/cli.py` - Persists mount rows during collect and keeps directory rows plus mount rows rollback-safe before successful finalization commits.
- `tests/test_cli_collect.py` - Keeps the interrupt verification deterministic under the new transaction and migration timing.

## Decisions Made

- Storage-domain identity intentionally excludes `mount_id` because mount ids are snapshot-local and reusable; durable grouping uses `major_minor`, `root`, `filesystem_type`, and `mount_source`.
- `MountInfo.options` and `MountInfo.super_options` remain unpersisted because Phase 2 grouping only needs identity and label fields, not volatile mount policy details.
- The collect command preserves the existing JSON envelope and snapshot-status model; this plan only adds stored grouping evidence for later reporting commands.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Regression] Preserved old monkeypatched helper seams during transactional collect writes**
- **Found during:** Task 2 (Implement snapshot_mounts persistence)
- **Issue:** Existing Phase 1 rollback tests monkeypatch `insert_directory_rows` with the old two-argument shape; the new `commit=` control broke those tests before the real rollback path ran.
- **Fix:** Added `_call_with_optional_commit()` in `src/watchdirs/cli.py` so collect uses transactional no-commit helpers when available, but still works with older monkeypatched helper signatures.
- **Files modified:** `src/watchdirs/cli.py`
- **Verification:** `pytest tests/test_cli_collect.py -q`, `pytest -q`
- **Committed in:** `e23cd4b`

**2. [Rule 1 - Test Stability] Removed a SIGTERM race in Phase 1 collect verification**
- **Found during:** Task 2 (Implement snapshot_mounts persistence)
- **Issue:** `test_collect_finalizes_snapshot_on_sigterm` treated mere SQLite file creation as proof that a snapshot row existed, which occasionally raced ahead of schema initialization/snapshot creation.
- **Fix:** Hardened the test to wait for the first persisted snapshot row before sending `SIGTERM`.
- **Files modified:** `tests/test_cli_collect.py`
- **Verification:** `pytest tests/test_cli_collect.py -q`, `pytest -q`
- **Committed in:** `e23cd4b`

---

**Total deviations:** 2 auto-fixed (`Rule 1: 2`)
**Impact on plan:** Both fixes were required to keep Phase 1 rollback verification intact while introducing the new REPT-07 persistence contract.

## Issues Encountered

- Adding transaction-safe commit ownership surfaced test seams that assumed the original helper signature and a looser SIGTERM wait condition. Both were tightened without changing the external `collect` contract.

## Authentication Gates

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- REPT-07 now has persisted snapshot-time mount evidence, so the next reporting plans can group current usage and growth by mount point or storage domain without live-only lookup.
- Phase 2 still needs the actual report commands (`top`, `diff`, `report`, `deleted`, `explain-path`); this plan only shipped the storage-domain foundation they depend on.

## Self-Check: PASSED

- Verified `.planning/phases/02-growth-frontier-reporting/02-01-SUMMARY.md` exists on disk.
- Verified commit `6122c38` exists in git history.
- Verified commit `e23cd4b` exists in git history.
