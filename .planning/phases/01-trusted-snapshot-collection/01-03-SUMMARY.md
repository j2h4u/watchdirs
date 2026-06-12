---
phase: 01-trusted-snapshot-collection
plan: 03
subsystem: filesystem
tags: [python, pytest, sqlite, scandir, hardlinks]
requires:
  - phase: 01-02
    provides: snapshot lifecycle persistence, BLOB-backed directory identity columns, collect CLI wiring
provides:
  - iterative post-order scanner for recursive directory aggregate rows
  - byte-safe path handling for non-UTF-8 directory identity through SQLite BLOB storage
  - exact hardlink disk-byte dedup with bounded inode tracking and durable scan errors
affects: [phase-01-04, collect, reporting]
tech-stack:
  added: [python-stdlib]
  patterns: [iterative stack scanner, byte-first filesystem identity, bounded hardlink dedup]
key-files:
  created:
    - tests/test_scanner_semantics.py
  modified:
    - src/watchdirs/cli.py
    - src/watchdirs/collect/scanner.py
    - src/watchdirs/models.py
    - tests/conftest.py
key-decisions:
  - "Scanner traversal now operates on raw filesystem bytes internally and only decodes at display boundaries."
  - "Configured excludes are passed through ScannerOptions with skip evidence enabled, while aggregate totals omit excluded subtree contents."
  - "Exact hardlink dedup stays on by default with a `500000` inode-key cap; exceeding the cap stops the scan with a durable resource error instead of falling back silently."
patterns-established:
  - "Scanner boundary: `cli.py` builds `ScannerOptions`, `collect/scanner.py` owns traversal semantics, and SQLite persistence stays in `db/*`."
  - "Recursive aggregate rows are emitted in iterative post-order so parent totals are computed from completed child rows without Python recursion."
requirements-completed: [COLL-03, COLL-04, COLL-05, FSEM-01, FSEM-02, FSEM-05]
duration: 5min
completed: 2026-06-13
status: complete
---

# Phase 1 Plan 03: Native scanner aggregate, byte, hardlink, symlink, and error semantics Summary

**Recursive directory aggregates now scan in byte-safe post-order, preserve non-UTF-8 identity in SQLite BLOB columns, and enforce exact hardlink disk semantics with bounded resource usage.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-13T02:50:48+05:00
- **Completed:** 2026-06-12T21:55:34Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added RED scanner semantics coverage for recursive aggregates, `du` tolerance, non-UTF-8 names, iterative depth, symlink handling, hardlink behavior, excludes, and permission errors.
- Replaced the recursive scanner with an iterative `os.scandir()` implementation that emits post-order directory rows, keeps raw path bytes, and records path-level scan errors.
- Wired `collect` through `ScannerOptions` so configured excludes and bounded hardlink dedup semantics are active on the real CLI path without changing the SQLite schema contract from 01-02.

## Verification

- `pytest tests/test_scanner_semantics.py -q` -> `10 passed`
- `pytest tests/test_scanner_semantics.py::test_non_utf8_paths_round_trip_through_scanner_and_sqlite -q` -> `1 passed`
- `pytest tests/test_scanner_semantics.py::test_iterative_postorder_handles_deep_tree_depth_1500 -q` -> `1 passed`
- `pytest tests/test_cli_collect.py -q` -> `17 passed`
- `pytest -q` -> `32 passed`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create failing scanner semantics tests** - `14cd150` (`test`)
2. **Task 2: Implement native recursive aggregate semantics** - `df6bca2` (`feat`)

## Files Created/Modified

- `tests/test_scanner_semantics.py` - RED/GREEN contract coverage for recursive aggregates, byte identity, hardlinks, symlinks, excludes, `du` tolerance, and permission errors.
- `tests/conftest.py` - Shared module import fixture for direct scanner and SQLite contract tests.
- `src/watchdirs/models.py` - Added `ScannerOptions`, `ScanError`, and richer `ScanResult` metadata while preserving 01-02 field names.
- `src/watchdirs/collect/scanner.py` - Implemented byte-safe iterative traversal, directory aggregation, special-file semantics, path error recording, and bounded hardlink dedup.
- `src/watchdirs/cli.py` - Builds `ScannerOptions` from loaded config and routes real collection runs through the hardened scanner interface.

## Decisions Made

- Internal scanner traversal uses raw bytes paths end-to-end so invalid UTF-8 names stay lossless through aggregation and SQLite insertion.
- Directory rows remain the only persisted row type in Phase 1; non-directory semantics are folded into aggregate counts and bytes while detailed skip/error evidence stays on `DirectoryAggregate.error` and `ScanResult.errors`.
- Exceeding the hardlink inode budget fails closed instead of disabling dedup, because approximate fallback would make disk-pressure evidence untrustworthy.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The initial SQLite round-trip test inserted directory rows without a parent snapshot row. The test fixture was corrected during implementation so the assertion exercised the BLOB path contract instead of a foreign-key failure.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `01-04` can now layer mountinfo-driven skip policy onto a scanner that already honors byte-safe path identity, iterative traversal, and partial-error semantics.
- Reporting phases can rely on persisted directory rows having stable hierarchy, disk-byte, apparent-byte, and error semantics without revisiting the SQLite row shape.

## Self-Check: PASSED

- Verified `.planning/phases/01-trusted-snapshot-collection/01-03-SUMMARY.md` exists on disk.
- Verified commit `14cd150` exists in git history.
- Verified commit `df6bca2` exists in git history.
