---
phase: 01-trusted-snapshot-collection
plan: 02
subsystem: database
tags: [python, sqlite, pytest, signals]
requires:
  - phase: 01-01
    provides: collect CLI scaffold, repo-local launcher, explicit TOML config loading
provides:
  - SQLite schema and connection setup for snapshot collection
  - snapshot lifecycle persistence with status, notes, and fatal error fields
  - collect wiring that persists directory aggregates and finalizes active snapshots on interrupt
affects: [phase-01-03, phase-01-04, reporting]
tech-stack:
  added: [python-stdlib, sqlite3]
  patterns: [snapshot-first persistence, batched sqlite inserts, json-first CLI evidence]
key-files:
  created:
    - src/watchdirs/models.py
    - src/watchdirs/collect/__init__.py
    - src/watchdirs/collect/scanner.py
    - src/watchdirs/db/__init__.py
    - src/watchdirs/db/connection.py
    - src/watchdirs/db/migrations.py
    - src/watchdirs/db/schema.sql
    - tests/test_db_schema.py
  modified:
    - src/watchdirs/cli.py
    - tests/test_cli_collect.py
key-decisions:
  - "Store directory identity columns as SQLite BLOB values so path, parent_path, and name preserve raw filesystem bytes."
  - "Create the snapshot row before scanning and finalize it after inserts or signal interruption so partial evidence remains durable."
  - "Keep CLI, scanner, and SQLite responsibilities split across `cli.py`, `collect/scanner.py`, and `db/*` so later filesystem-semantics work can extend the scanner without rewriting persistence."
patterns-established:
  - "Connection boundary: `open_connection()` owns WAL, foreign keys, busy timeout, and row factory configuration."
  - "Lifecycle boundary: `initialize_database()`, `create_snapshot()`, `insert_directory_rows()`, and `finalize_snapshot()` form the stable persistence contract for future phases."
requirements-completed: [COLL-01, COLL-02]
duration: 4min
completed: 2026-06-13
status: complete
---

# Phase 1 Plan 02: Snapshot persistence lifecycle Summary

**SQLite-backed collect now records snapshot lifecycle rows, batched directory aggregates, and durable interrupt failures for both supported command surfaces.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-13T02:38:23+05:00
- **Completed:** 2026-06-12T21:42:36Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added RED tests for the collect persistence path, schema fields/indexes, connection pragmas, batched inserts, fatal snapshot errors, and SIGTERM finalization.
- Implemented the SQLite layer with `schema.sql`, `PRAGMA user_version`, WAL/foreign key/busy timeout setup, snapshot lifecycle helpers, and `executemany()` insertion batches of 10,000 rows.
- Wired `./watchdirs collect` and `python3 -m watchdirs collect` through the scanner boundary so each configured root creates a durable snapshot row plus JSON snapshot evidence.

## Verification

- `pytest tests/test_db_schema.py -q` -> `5 passed`
- `pytest tests/test_cli_collect.py -q` -> `17 passed`
- `pytest -q` -> `22 passed`

## Task Commits

1. **Task 1: Create failing SQLite lifecycle and collect persistence contracts** - `259138d` (`test`)
2. **Task 2: Implement SQLite schema, snapshot lifecycle, and collect persistence** - `133300d` (`feat`)

## Files Created/Modified

- `src/watchdirs/models.py` - Base dataclasses and `SnapshotStatus` enum for persisted snapshot and directory rows.
- `src/watchdirs/collect/scanner.py` - Scanner boundary returning `ScanResult` rows for persistence.
- `src/watchdirs/db/connection.py` - SQLite connection factory with required pragmas.
- `src/watchdirs/db/migrations.py` - Schema initialization, snapshot lifecycle helpers, and batched aggregate insertion.
- `src/watchdirs/db/schema.sql` - `snapshots` and `directory_sizes` schema plus required indexes.
- `src/watchdirs/cli.py` - Collect execution path that initializes SQLite, persists rows, emits JSON, and finalizes active snapshots on interrupt.
- `tests/test_cli_collect.py` and `tests/test_db_schema.py` - CLI and database persistence contracts for Phase 01-02.

## Decisions Made

- Used one snapshot row per configured root so lifecycle status, notes, and fatal errors remain attributable even when multiple roots are collected in one command.
- Kept `root_path` as text metadata while directory identity fields stay BLOB-backed, which matches the config boundary and preserves raw subtree bytes where filesystem names can be non-UTF-8.
- Returned a non-zero exit code and a JSON interruption envelope after finalizing active snapshots on `SIGINT`/`SIGTERM` so automation can distinguish operator/system interrupts from successful collection.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `01-03` can harden byte, hardlink, symlink, and partial-error semantics on top of the established `ScanResult`/`DirectoryAggregate` and SQLite contracts.
- `01-04` can add mountinfo-driven pruning without changing the persisted schema or interrupt-finalization path.

## Self-Check: PASSED

- Verified `.planning/phases/01-trusted-snapshot-collection/01-02-SUMMARY.md` exists on disk.
- Verified commit `259138d` exists in git history.
- Verified commit `133300d` exists in git history.
