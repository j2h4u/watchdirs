---
phase: 01-trusted-snapshot-collection
reviewed: 2026-06-12T22:26:37Z
depth: quick
files_reviewed: 5
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/collect/scanner.py
  - tests/test_cli_collect.py
  - tests/test_scanner_semantics.py
  - tests/test_mount_policy.py
findings:
  critical: 1
  warning: 0
  info: 0
  total: 1
status: issues_found
---
# Phase 01: Code Review Report

**Reviewed:** 2026-06-12T22:26:37Z
**Depth:** quick
**Files Reviewed:** 5
**Status:** issues_found

## Summary

I re-reviewed the Phase 01 fix set with focus on the prior findings in the previous report. `CR-01`, `CR-02`, and `WR-01` are resolved in the current code and are covered by the new targeted regression tests. `CR-03` is only partially resolved: `open_connection()` failures are now wrapped, but database initialization failures still escape before any JSON-safe error envelope is emitted.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 [BLOCKER]: Database initialization failures still bypass `--json` error handling

**File:** `src/watchdirs/cli.py:51-59`, `src/watchdirs/cli.py:77-79`
**Issue:** The new wrapper only covers `open_connection(db_path)`. `initialize_database(connection)` still runs outside any `sqlite3.Error` handling, so initialization/migration failures raise out of `run_collect()` and produce no JSON payload. I verified this by forcing `initialize_database()` to raise and observed an uncaught exception with empty stdout. That means the original JSON-contract defect behind prior `CR-03` is still present on the schema/init path.
**Fix:**
```python
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
```
Add a regression test that monkeypatches `initialize_database()` to raise `sqlite3.OperationalError` and asserts `--json` returns a machine-readable `database_error` payload instead of propagating.

---

_Reviewed: 2026-06-12T22:26:37Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: quick_
