---
phase: 01-trusted-snapshot-collection
reviewed: 2026-06-12T22:21:16Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - examples/senbonzakura.watchdirs.toml
  - pyproject.toml
  - src/watchdirs/__init__.py
  - src/watchdirs/__main__.py
  - src/watchdirs/cli.py
  - src/watchdirs/collect/__init__.py
  - src/watchdirs/collect/classify.py
  - src/watchdirs/collect/mounts.py
  - src/watchdirs/collect/scanner.py
  - src/watchdirs/config.py
  - src/watchdirs/db/__init__.py
  - src/watchdirs/db/connection.py
  - src/watchdirs/db/migrations.py
  - src/watchdirs/db/schema.sql
  - src/watchdirs/models.py
  - tests/conftest.py
  - tests/test_cli_collect.py
  - tests/test_db_schema.py
  - tests/test_mount_policy.py
  - tests/test_scanner_semantics.py
  - watchdirs
findings:
  critical: 3
  warning: 1
  info: 0
  total: 4
status: issues_found
---
# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T22:21:16Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

I reviewed the Phase 01 source set with emphasis on CLI failure semantics, scanner unwind behavior, SQLite durability, and mount-policy edge cases. The implementation is close, but it currently misreports incomplete collections as successful, can persist structurally incomplete partial snapshots, leaks raw tracebacks for database/open failures even under `--json`, and undercounts directories when mount-pruned children are recorded.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER]: Partial scans are reported as successful collections

**File:** `src/watchdirs/cli.py:92-156`
**Issue:** `run_collect()` only flips `exit_code` when a snapshot finishes as `FAILED` (`line 100`), so any `PARTIAL` snapshot still returns exit code `0` and emits `"ok": true`. This is not theoretical: a hardlink-dedup limit hit after one completed child directory produces a persisted snapshot with `status="partial"` while the CLI reports success. That lets automation treat an incomplete forensic snapshot as trustworthy.
**Fix:**
```python
                finalized = finalize_snapshot(
                    connection,
                    snapshot.id,
                    status=scan_result.status,
                    notes=args.notes,
                    error=scan_result.fatal_error,
                )
                snapshot_payloads.append(_snapshot_payload(finalized, scan_result.row_count))
                if finalized.status is not SnapshotStatus.COMPLETE:
                    exit_code = 1
```
Add a CLI test that forces `scan_root()` to return `SnapshotStatus.PARTIAL` and assert non-zero exit plus `"ok": false`.

### CR-02 [BLOCKER]: Hardlink-limit abort drops the active directory stack and persists orphaned rows

**File:** `src/watchdirs/collect/scanner.py:214-226`
**Issue:** When `_disk_bytes_for_entry()` raises `_HardlinkLimitExceeded`, `scan_root()` returns immediately with only the already-completed `rows`. Any active frame, including the root directory, is discarded instead of being materialized with an error. In practice this yields partial snapshots that can contain only a finished descendant row and no root row at all, which corrupts the persisted tree shape and removes the context needed for later diff/report queries.
**Fix:**
```python
        except _HardlinkLimitExceeded as exc:
            error = exc.error
            errors.append(error)
            frame.error = frame.error or error.message
            had_failure = True
            # stop descending, then unwind the existing stack so every active
            # directory still gets a row with consistent parent/child shape
            frame.entries = []
            frame.next_index = len(frame.entries)
            continue
```
If you prefer a sentinel exception, catch it at the outer loop and explicitly flush `frame` plus every ancestor before returning. Add a regression test that asserts a partial snapshot still persists the root row and preserves the path-level error.

### CR-03 [BLOCKER]: `--json` does not protect database/open failures from raw tracebacks

**File:** `src/watchdirs/cli.py:49-50`
**Issue:** `open_connection(db_path)` runs before the main `try` block, so path/open failures (for example `--db` under a non-directory parent) escape as uncaught exceptions. With `--json`, the command prints a Python traceback on stderr and no machine-readable payload on stdout. That breaks the phase’s JSON-first contract for automation exactly at the storage boundary most likely to fail in operations.
**Fix:**
```python
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
    except OSError as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            db_path=db_path,
            as_json=args.json,
        )
    except sqlite3.Error as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            db_path=db_path,
            as_json=args.json,
        )
```
Add a CLI test that points `--db` at `tmp_path / "parent-file" / "watchdirs.sqlite3"` and asserts a JSON error envelope instead of a traceback.

## Warnings

### WR-01 [WARNING]: Mount-pruned child directories are persisted but never counted in the parent aggregate

**File:** `src/watchdirs/collect/scanner.py:178-189`, `src/watchdirs/collect/scanner.py:416-420`
**Issue:** When mount policy rejects a directory, the scanner appends a skipped row and continues without calling `_merge_child()`. The skipped directory therefore exists as a persisted row, but the parent `dir_count` omits it entirely. This makes aggregate counts inconsistent whenever a mount boundary is intentionally pruned.
**Fix:**
```python
                skipped_row = _skipped_directory_row(
                    path_raw=entry_path,
                    parent_path=frame.path_raw,
                    depth=frame.depth + 1,
                    error=decision.reason,
                )
                rows.append(skipped_row)
                _merge_child(frame, skipped_row)
                continue
```
Extend `tests/test_mount_policy.py` to assert the parent row’s `dir_count` includes the skipped mountpoint while its bytes remain zero.

---

_Reviewed: 2026-06-12T22:21:16Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
