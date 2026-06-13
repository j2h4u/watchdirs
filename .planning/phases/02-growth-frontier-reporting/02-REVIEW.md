---
phase: 02-growth-frontier-reporting
reviewed: 2026-06-13T19:34:51Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/db/migrations.py
  - src/watchdirs/db/schema.sql
  - src/watchdirs/models.py
  - src/watchdirs/reporting/__init__.py
  - src/watchdirs/reporting/frontier.py
  - src/watchdirs/reporting/pairs.py
  - src/watchdirs/reporting/queries.py
  - src/watchdirs/reporting/render.py
  - tests/test_cli_report_commands.py
  - tests/test_frontier.py
  - tests/test_grouping.py
  - tests/test_reporting_queries.py
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues_found
---
# Phase 02: Code Review Report

**Reviewed:** 2026-06-13T19:34:51Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the Phase 02 reporting and grouping changes at standard depth, including targeted runtime repros against temporary SQLite fixtures and the scoped test suite (`52 passed`). I found one blocker and two warnings. The most severe defect is that `report --group-by ...` only applies the requested grouping to part of the payload; `deleted_preview` rows are always labeled as `root`, which makes the JSON contract internally inconsistent.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `report --group-by ...` lies about `deleted_preview` grouping

**File:** `src/watchdirs/cli.py:437-450`, `src/watchdirs/reporting/queries.py:266-271`, `src/watchdirs/reporting/render.py:208-210`

**Issue:** `run_report()` advertises one `group_by` mode for the whole report, but it builds `deleted_preview` through `query_deleted_rows()`, and that helper hard-codes `group_by="root"`. As a result, `watchdirs report --group-by mount --json` returns frontier rows grouped by mount while `deleted_preview` rows still carry `{"kind": "root", ...}`. I reproduced this with a temporary DB: the payload reported `group_by: "mount"`, `frontier[0].group.kind == "mount"`, and `deleted_preview[0].group.kind == "root"`. That is incorrect behavior in the shipped API and it also suppresses `unknown_mount` coverage for deleted rows.

**Fix:**
```python
def query_deleted_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    limit: int,
    group_by: str,
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    diff_rows, warnings = query_diff_rows(connection, pair=pair, group_by=group_by)
    deleted_rows = sorted(
        (row for row in diff_rows if row.classification == "deleted"),
        key=lambda row: (-row.previous_disk_bytes, row.path),
    )
    return tuple(deleted_rows[:limit]), warnings
```

## Warnings

### WR-01: Text renderers trust raw filesystem names and allow line-spoofing

**File:** `src/watchdirs/reporting/render.py:20-28`, `src/watchdirs/reporting/render.py:89-105`, `src/watchdirs/reporting/render.py:161-183`, `src/watchdirs/reporting/render.py:240-293`, `src/watchdirs/reporting/render.py:340-355`, `src/watchdirs/reporting/render.py:411-446`

**Issue:** every text renderer interpolates decoded paths and warning text directly into newline-delimited output. A directory name containing `\n`, tabs, or terminal control bytes can therefore forge extra lines that look like real warnings or rows. I reproduced this by inserting a path named `b"/srv/evil\\nwarning code=fake message=hijacked"` and running `watchdirs top`; the output emitted a fake standalone `warning code=fake ...` line. This is a spoofing vulnerability in an operations tool whose text mode is supposed to be trustworthy evidence.

**Fix:**
```python
def _escape_text_field(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")

def _text_path(path_bytes: bytes) -> str:
    return _escape_text_field(os.fsdecode(path_bytes))
```
Use the escaped helper for every text-mode `path=` and warning/message field, while keeping JSON output unchanged.

### WR-02: Rows outside the snapshot root are silently assigned bogus root/subtree labels

**File:** `src/watchdirs/reporting/queries.py:372-415`

**Issue:** `resolve_group_for_path()` returns a `root` label unconditionally, and `resolve_top_level_subtree_group()` never checks that the row path is actually under `root_path_bytes`. If inconsistent data reaches the reporting layer, `group_by="root"` falsely attributes the row to the configured root and `group_by="top-level-subtree"` can even return an empty subtree key. I reproduced this by seeding snapshot root `/srv` with a row at `/mystery`; `query_top_rows(..., group_by="top-level-subtree")` returned `GroupLabel(kind='top-level-subtree', key='')` with no warning. For a forensic tool, silently inventing a group is worse than surfacing broken evidence.

**Fix:**
```python
if not _matches_path_prefix(path_bytes, root_path_bytes):
    return None, ReportWarning(
        code="path_outside_root",
        message=f"path {os.fsdecode(path_bytes)!r} is not under snapshot root {os.fsdecode(root_path_bytes)!r}",
        path=path_bytes,
    )
```
Apply the guard before returning `root` or `top-level-subtree` labels, and add coverage for corrupted/out-of-root rows.

---

_Reviewed: 2026-06-13T19:34:51Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
