---
phase: 04-scheduled-retention-operations
reviewed: 2026-06-17T00:27:46Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - AGENTS.md
  - .planning/phases/04-scheduled-retention-operations/04-CONTEXT.md
  - .planning/phases/04-scheduled-retention-operations/04-RESEARCH.md
  - .planning/phases/04-scheduled-retention-operations/04-VALIDATION.md
  - .planning/phases/04-scheduled-retention-operations/04-01-SUMMARY.md
  - .planning/phases/04-scheduled-retention-operations/04-02-SUMMARY.md
  - .planning/phases/04-scheduled-retention-operations/04-03-SUMMARY.md
  - .planning/phases/04-scheduled-retention-operations/04-04-SUMMARY.md
  - src/watchdirs/ops_lock.py
  - src/watchdirs/cli.py
  - src/watchdirs/db/retention.py
  - ops/systemd/watchdirs-collect.service
  - ops/systemd/watchdirs-collect.timer
  - ops/systemd/watchdirs-prune.service
  - ops/systemd/watchdirs-prune.timer
  - ops/systemd/watchdirs-vacuum.service
  - ops/systemd/watchdirs-vacuum.timer
  - tests/test_ops_locking.py
  - tests/test_ops_retention.py
  - tests/test_ops_vacuum.py
  - tests/test_systemd_units.py
findings:
  critical: 2
  warning: 1
  info: 0
  total: 3
status: issues_found
---
# Phase 04: Code Review Report

**Reviewed:** 2026-06-17T00:27:46Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Reviewed the Phase 04 retention, locking, systemd, and test changes. The targeted pytest suite passes, but the implementation still has two release-blocking correctness defects and one retention robustness gap. The most serious failures are that `prune`/`vacuum` silently create a fresh database when pointed at a missing path, and the shared writer lock can be bypassed by addressing the same SQLite file through a symlinked filename.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `prune` and `vacuum` silently succeed against a missing database path

**File:** `src/watchdirs/cli.py:578-580`, `src/watchdirs/cli.py:635-637`, `src/watchdirs/db/connection.py:16-20`
**Issue:** Both maintenance commands call `open_connection()` and `initialize_database()` unconditionally. `open_connection()` creates parent directories and lets SQLite create a new file, so a typoed or missing `--db` path is treated as a clean empty database instead of an operational failure. I reproduced this with `python3 -m watchdirs prune --db /tmp/.../missing/watchdirs.sqlite3 --json` and `vacuum` on the same path: both returned `ok: true`, and `vacuum` even reported byte/page counters for the newly created file. That violates the Phase 4 "evidence gaps must be visible" contract and makes the systemd units report success while touching the wrong database.
**Fix:**
```python
def open_existing_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"watchdirs database does not exist: {db_path}")

    connection = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection
```
Use this stricter opener from `run_prune()` and `run_vacuum()`, and add regression tests that assert both commands fail with JSON `database_error` when the DB file is absent.

### CR-02: The shared writer lock can be bypassed with a symlinked database filename

**File:** `src/watchdirs/ops_lock.py:34-36`
**Issue:** `operation_lock_path_for_db()` derives `<db>.lock` from the user-supplied path string without canonicalizing it. If the same SQLite file is accessed through a symlinked filename in another directory, the code creates a different sibling lock file and both locks can be acquired at once. I reproduced this with a real database path and a symlinked alias to the same file; `acquire_operation_lock(real_db.lock)` and `acquire_operation_lock(alias_db.lock)` both succeeded. That breaks the Phase 4 guarantee that `collect`, `prune`, and `vacuum` share one fail-fast writer lock across manual and scheduled entrypoints.
**Fix:**
```python
def operation_lock_path_for_db(db_path: Path) -> Path:
    canonical_db = Path(db_path).expanduser().resolve(strict=False)
    return canonical_db.with_name(f"{canonical_db.name}.lock")
```
Canonicalize the database path before deriving the lock path, and add a regression test that uses a symlinked database file path and asserts the second lock attempt raises `OperationLocked`.

## Warnings

### WR-01: Retention keeps stale unfinished snapshots forever

**File:** `src/watchdirs/db/retention.py:67-79`, `src/watchdirs/db/migrations.py:67-80`
**Issue:** `create_snapshot()` commits a row with `finished_at = NULL` before any scan work starts. If the process dies uncleanly before `finalize_snapshot()` runs, that row remains unfinished indefinitely. `select_retained_snapshot_ids()` currently keeps every `finished_at is None` snapshot forever, so those stale crash remnants never age out of retention and will keep inflating `snapshots_before`/`snapshots_after` counts. The current retention tests only seed finished snapshots, so this case is untested.
**Fix:**
```python
SELECT id, root_path, status, started_at, finished_at
FROM snapshots
ORDER BY id
```
Then treat unfinished snapshots as temporary evidence only inside the hourly window, for example by retaining them based on `started_at >= hourly_cutoff` and pruning older unfinished rows once they are clearly stale.

---

_Reviewed: 2026-06-17T00:27:46Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
