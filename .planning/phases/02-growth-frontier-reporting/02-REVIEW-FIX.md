---
phase: 02
fixed_at: 2026-06-13T19:45:06Z
review_path: .planning/phases/02-growth-frontier-reporting/02-REVIEW.md
iteration: 1
findings_in_scope: 3
fixed: 3
skipped: 0
status: all_fixed
---
# Phase 02: Code Review Fix Report

**Fixed at:** 2026-06-13T19:45:06Z
**Source review:** `.planning/phases/02-growth-frontier-reporting/02-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 3
- Fixed: 3
- Skipped: 0

## Fixed Issues

### CR-01: `report --group-by ...` lies about `deleted_preview` grouping

**Status:** fixed: requires human verification
**Files modified:** `src/watchdirs/reporting/queries.py`, `src/watchdirs/cli.py`, `tests/test_reporting_queries.py`, `tests/test_cli_report_commands.py`
**Commit:** `34dbd67`
**Applied fix:** Propagated the requested `group_by` value through `query_deleted_rows()` and the `report` command so deleted preview rows now keep the same grouping contract and warnings as the rest of the report payload.

### WR-01: Text renderers trust raw filesystem names and allow line-spoofing

**Status:** fixed
**Files modified:** `src/watchdirs/reporting/render.py`, `tests/test_cli_report_commands.py`
**Commit:** `3a2ef79`
**Applied fix:** Escaped text-mode filesystem, warning, group, and error fields with `unicode_escape` while preserving the existing JSON payload values.

### WR-02: Rows outside the snapshot root are silently assigned bogus root/subtree labels

**Status:** fixed: requires human verification
**Files modified:** `src/watchdirs/reporting/queries.py`, `tests/test_reporting_queries.py`, `tests/test_cli_report_commands.py`
**Commit:** `653508e`
**Applied fix:** Added an out-of-root guard for `root` and `top-level-subtree` grouping so corrupted rows now surface `path_outside_root` warnings and `group=None` instead of fabricated labels.

---

_Fixed: 2026-06-13T19:45:06Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
