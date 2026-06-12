---
phase: 01-trusted-snapshot-collection
reviewed: 2026-06-12T22:41:57Z
depth: deep
files_reviewed: 13
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/collect/scanner.py
  - src/watchdirs/collect/classify.py
  - src/watchdirs/collect/mounts.py
  - src/watchdirs/config.py
  - src/watchdirs/db/connection.py
  - src/watchdirs/db/migrations.py
  - src/watchdirs/db/schema.sql
  - src/watchdirs/models.py
  - tests/test_cli_collect.py
  - tests/test_mount_policy.py
  - tests/test_scanner_semantics.py
  - tests/test_db_schema.py
findings:
  critical: 1
  warning: 0
  info: 0
  total: 1
status: issues_found
---
# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T22:41:57Z
**Depth:** deep
**Files Reviewed:** 13
**Status:** issues_found

## Summary

I re-reviewed the Phase 01 source diff after fixes commit `691b5d7`, focusing on the prior blocker classes and adjacent persistence paths. The generic insert-failure rollback fix in [src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:115) is correct, and the hardlink dedup guard in [src/watchdirs/collect/scanner.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/scanner.py:346) now behaves correctly for ordinary single-link files.

The phase is still not clean. A failed-interrupt path remains: if `SIGINT` or `SIGTERM` arrives after at least one `directory_sizes` row has been written but before the transaction commits, the signal handler finalizes the snapshot without rolling back first and commits partial evidence.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Interrupt finalization can still commit partial directory rows

**Classification:** BLOCKER
**File:** `src/watchdirs/cli.py:70-79`
**Issue:** The new rollback only covers the generic `except Exception` path later in `run_collect()`. The signal handler still calls `finalize_snapshot()` directly for every active snapshot without first rolling back the current transaction. If `SIGTERM` or `SIGINT` lands after one or more `directory_sizes` inserts have executed but before `insert_directory_rows()` commits, `finalize_snapshot()` commits those staged rows together with the failed snapshot status. I reproduced this by monkeypatching `insert_directory_rows()` to write one row and then raise `SIGTERM`; the command returned `143`, the snapshot status was `failed`, and one `directory_sizes` row remained committed.
**Fix:**
```python
    def _handle_interrupt(signum: int, _frame) -> None:
        error = f"collection interrupted by signal {signal.Signals(signum).name}"
        connection.rollback()
        for snapshot_id in list(active_snapshot_ids):
            finalize_snapshot(
                connection,
                snapshot_id,
                status=SnapshotStatus.FAILED,
                error=error,
            )
```
Add a regression test that interrupts during `insert_directory_rows()` after at least one row has been staged, then assert the failed snapshot has zero committed `directory_sizes` rows.

---

_Reviewed: 2026-06-12T22:41:57Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
