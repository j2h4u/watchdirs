---
phase: 01-trusted-snapshot-collection
reviewed: 2026-06-12T22:36:23Z
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
  critical: 2
  warning: 0
  info: 0
  total: 2
status: issues_found
---
# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T22:36:23Z
**Depth:** deep
**Files Reviewed:** 13
**Status:** issues_found

## Summary

I re-reviewed the trusted snapshot collection implementation after the prior fix round, focusing on the previously reported blocker classes plus adjacent data-integrity paths. The earlier issues called out in the prior review are fixed: partial scans now return non-zero/`ok: false`, hardlink-limit scans keep the root row, database open/init/create-snapshot failures emit JSON, and skipped mount rows increment the parent `dir_count`.

The phase is still not clean. Two blocker-class correctness defects remain in the current implementation: failed row insertion can still commit an incomplete snapshot, and the hardlink dedup limit is applied to ordinary single-link files, which can mark large healthy trees as partial for the wrong reason.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Failed row inserts can commit a partial snapshot

**Classification:** BLOCKER
**File:** `src/watchdirs/cli.py:115-137`, `src/watchdirs/db/migrations.py:75-78`
**Issue:** `insert_directory_rows()` runs inside the per-root `try`, but the failure path in `run_collect()` goes straight to `finalize_snapshot(..., status=FAILED)` without first rolling back the active transaction. In SQLite, a mid-batch `executemany()` failure leaves earlier successful inserts pending. `finalize_snapshot()` then commits that pending work together with the failed status update. I reproduced this with a trigger that raises on the second `directory_sizes` insert: the snapshot finished as `failed`, but one `directory_sizes` row remained committed. That violates the trusted-snapshot contract because downstream consumers can read an incomplete failed snapshot as if it were persisted evidence.
**Fix:**
```python
            except Exception as exc:
                exit_code = 1
                connection.rollback()
                finalized = finalize_snapshot(
                    connection,
                    snapshot.id,
                    status=SnapshotStatus.FAILED,
                    notes=args.notes,
                    error=str(exc),
                )
```
Add a regression test that forces `insert_directory_rows()` to fail after at least one row has been inserted, then assert the failed snapshot has zero `directory_sizes` rows.

### CR-02: The hardlink guard wrongly treats every regular file as a dedup entry

**Classification:** BLOCKER
**File:** `src/watchdirs/collect/scanner.py:394-408`
**Issue:** `_disk_bytes_for_entry()` adds every regular file inode to `seen_inodes`, even when `st_nlink == 1`. That means `hardlink_dedup_max_entries` is really a cap on total regular files seen, not on hardlink tracking state. A tree with no hardlinks can therefore become `partial` with a `hardlink_limit` error once the file count crosses the limit. Direct repro: two ordinary files plus `hardlink_dedup_max_entries=1` returns `partial` and records `hardlink_limit`, even though no hardlink exists. On a host-level forensic tool, this can falsely degrade large normal scans and misreport the reason.
**Fix:**
```python
    if not stat.S_ISREG(stat_result.st_mode):
        return disk_bytes_from_stat(stat_result), False
    if stat_result.st_nlink <= 1:
        return disk_bytes_from_stat(stat_result), False

    key = inode_key(stat_result)
    if key in seen_inodes:
        return 0, True
```
Keep the limit only on multi-link inode tracking, and add a regression test asserting that many single-link files do not trigger `hardlink_limit`.

---

_Reviewed: 2026-06-12T22:36:23Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
