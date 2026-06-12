---
phase: 01-trusted-snapshot-collection
reviewed: 2026-06-12T22:29:51Z
depth: quick
files_reviewed: 2
files_reviewed_list:
  - src/watchdirs/cli.py
  - tests/test_cli_collect.py
findings:
  critical: 1
  warning: 0
  info: 0
  total: 1
status: issues_found
---
# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T22:29:51Z
**Depth:** quick
**Files Reviewed:** 2
**Status:** issues_found

## Summary

I re-reviewed the remaining JSON-error blocker in Phase 01 with focus on `collect`. The original initialization-path defect is resolved: `run_collect()` now wraps `initialize_database()` in the same database error handler as `open_connection()`, and `tests/test_cli_collect.py` now includes a regression test for that path. The phase is still not clean because a later database write failure during `create_snapshot()` still escapes before any `--json` payload is emitted.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Snapshot creation failures still bypass `--json`

**File:** `src/watchdirs/cli.py:86-89`
**Issue:** `create_snapshot(connection, configured_root.path, notes=args.notes)` runs before the per-root `try/except`, and the outer block only handles `CollectionInterrupted`. If SQLite fails while inserting the snapshot row, `run_collect()` raises out of `main()` instead of returning a machine-readable `database_error` payload. I verified this by monkeypatching `create_snapshot()` to raise `sqlite3.OperationalError("snapshot insert failed")`; the exception propagated with no JSON on stdout. This means the exact contract the prior blocker targeted is still broken for the next database write step after initialization.
**Fix:**
```python
        for configured_root in config.roots:
            try:
                snapshot = create_snapshot(connection, configured_root.path, notes=args.notes)
            except sqlite3.Error as exc:
                return _emit_runtime_error(
                    code="database_error",
                    message=str(exc),
                    as_json=args.json,
                    context={"db_path": str(db_path), "root_path": str(configured_root.path)},
                )

            active_snapshot_ids.add(snapshot.id)
            try:
                ...
```
Add a regression test that forces `create_snapshot()` to raise `sqlite3.OperationalError` and asserts `cli.main(... --json)` returns `1` and emits a `database_error` JSON object instead of propagating.

---

_Reviewed: 2026-06-12T22:29:51Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: quick_
