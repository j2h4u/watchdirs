---
phase: 02-growth-frontier-reporting
reviewed: 2026-06-13T19:49:40Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/reporting/queries.py
  - src/watchdirs/reporting/render.py
  - tests/test_cli_report_commands.py
  - tests/test_reporting_queries.py
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: issues_found
---
# Phase 02: Code Review Rerun

**Reviewed:** 2026-06-13T19:49:40Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Re-reviewed the Phase 02 fixes with focus on CR-01, WR-01, and WR-02. CR-01 is fixed: `report --group-by ...` now propagates the requested grouping into `deleted_preview`. WR-01 is fixed in the reviewed renderers: text-mode path, warning, group, and error fields are escaped, and the scoped suite passed (`46 passed`). WR-02 is only partially fixed: out-of-root rows now warn for `root` and `top-level-subtree`, but `mount` and `storage-domain` still fabricate group labels for the same corrupted rows.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: Out-of-root rows still fabricate `mount` and `storage-domain` groups

**Severity:** WARNING
**File:** `src/watchdirs/reporting/queries.py:373-396`
**Issue:** The new `path_outside_root` guard only runs when `group_by` is `root` or `top-level-subtree`. If a corrupted row lies outside the snapshot root and persisted mounts include `/`, `resolve_group_for_path()` still returns a synthetic `mount` or `storage-domain` label with no warning. I reproduced this against the current code by seeding a `/srv` snapshot containing `/mystery` plus a persisted `/` mount; `query_top_rows(..., group_by="mount")` returned `GroupLabel(kind='mount', key='/')` and `warnings == []`, and `group_by="storage-domain"` behaved the same. That means the original “warn instead of fabricate” requirement is still violated for two grouping modes. The current tests only cover the root/subtree branch ([tests/test_reporting_queries.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_reporting_queries.py:477)) and the happy-path mount grouping ([tests/test_cli_report_commands.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_report_commands.py:572)).
**Fix:**
```python
def resolve_group_for_path(
    path_bytes: bytes,
    *,
    root_path_bytes: bytes,
    group_by: str,
    snapshot_mounts: tuple[SnapshotMount, ...] = (),
) -> tuple[GroupLabel | None, ReportWarning | None]:
    if not _matches_path_prefix(path_bytes, root_path_bytes):
        return None, ReportWarning(
            code="path_outside_root",
            message=f"path {os.fsdecode(path_bytes)!r} is not under snapshot root {os.fsdecode(root_path_bytes)!r}",
            path=path_bytes,
        )

    if group_by == "root":
        ...
```

---

_Reviewed: 2026-06-13T19:49:40Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
