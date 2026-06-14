---
phase: 03-pressure-gap-diagnostics
reviewed: 2026-06-14T00:00:00Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/diagnostics/__init__.py
  - src/watchdirs/diagnostics/df_index.py
  - src/watchdirs/diagnostics/deleted_open.py
  - src/watchdirs/diagnostics/docker.py
  - src/watchdirs/diagnostics/summary.py
  - src/watchdirs/reporting/__init__.py
  - src/watchdirs/reporting/queries.py
  - src/watchdirs/reporting/render.py
  - tests/test_diagnostics_df_index.py
  - tests/test_diagnostics_deleted_open.py
  - tests/test_diagnostics_docker.py
  - tests/test_diagnostics_summary.py
  - tests/test_cli_report_commands.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-14
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Reviewed the Phase 3 pressure-gap diagnostics: df-vs-index reconciliation, deleted-open detection (lsof/procfs), Docker/containerd enrichment, the compact pressure summary, and report integration.

The security posture is solid: every external-tool invocation uses a fixed argv with `shell=False` and no user interpolation (`deleted_open._LSOF_ARGV`, `docker._SYSTEM_DF_ARGV`/`_BUILDX_DU_ARGV`). All SQL uses parameterized placeholders, including the Docker hint GLOB query (`cli.py:893-900`). `statvfs`/`OSError` failures are isolated per-domain, lsof/Docker absence degrades to warnings, and external tool output is parsed defensively. CLI path input is normalized via `os.path.normpath` before root-prefix matching, so `..` traversal cannot escape a root.

The one BLOCKER is a correctness defect in the core non-overlapping storage-domain aggregation: when an intermediate directory is missing from the indexed rows (a tree "gap"), a nested submount's bytes are double-counted against the enclosing domain, violating the module's own "at most one storage-domain total" contract and corrupting every downstream `unattributed_bytes`/`over_indexed_bytes` figure for that filesystem. The test suite only exercises contiguous parent chains, so it never catches this.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Non-overlapping domain aggregation double-counts nested submounts across an indexed-path gap

**File:** `src/watchdirs/reporting/queries.py:150-185`
**Issue:** `query_indexed_storage_domain_totals` collapses recursive aggregates to "boundary rows" and, for each boundary row whose domain differs from its parent's, subtracts that row's aggregate from the **immediate parent's** domain (lines 181-185). The subtraction only fires when the immediate parent path is present in `rows_by_path`. When an intermediate directory is absent from the indexed rows (a gap — which happens when a scan skips a directory on error/permission, or when an intermediate level is otherwise not persisted), the nested submount row is still treated as a boundary (`parent_match is None` → `is_boundary=True`, line 158), its full aggregate is added to its own domain, but **no subtraction is applied to the enclosing ancestor domain**, which already counted the subtree via its recursive `disk_bytes`. The documented guarantee ("each `disk_bytes` aggregate contributes to at most one storage-domain total", lines 121-126) is broken.

Reproduced: indexed rows `/a` (disk=1000, domain A) and `/a/b/c` (disk=300, domain C) with `/a/b` absent yields A=1000 and C=300, sum=1300 instead of 1000. The inflated indexed total then propagates into `df_index._build_section`: `over_indexed = max(indexed - used, 0)` and `unattributed = max(used - indexed, 0)` (df_index.py:199-200) are both computed from the corrupted `indexed`, so the df/index reconciliation reports wrong remainders (e.g. spurious `over_indexed` or suppressed `unattributed`), which feeds wrong `likely_reasons` and pressure-summary hints.

**Fix:** Subtract a nested submount's aggregate from the *nearest indexed ancestor's resolved domain*, not only the immediate parent row. Walk parent links upward until an indexed ancestor row is found and subtract from that ancestor's domain; if no indexed ancestor exists, no subtraction is needed. For example:

```python
# Instead of relying on parent_path being a direct indexed row:
ancestor_path = parent_path
ancestor_match = None
while ancestor_path is not None:
    if ancestor_path in rows_by_path:
        ancestor_match = domain_by_path.get(ancestor_path)
        break
    ancestor_path = _parent_of(ancestor_path)  # byte-path dirname
if ancestor_match is not None and _domain_key(ancestor_match) != domain_key:
    ancestor = accumulators.setdefault(_domain_key(ancestor_match), _DomainAccumulator(ancestor_match))
    ancestor.disk_bytes -= row_disk
    ancestor.apparent_bytes -= row_apparent
```

Also reconsider `is_boundary`: a row whose immediate parent is absent should be classified relative to its nearest indexed ancestor's domain, not unconditionally treated as a fresh boundary. Add a regression test seeding `/a`, `/a/b/c` (gap at `/a/b`) on distinct domains and assert the domain totals still sum to the root aggregate.

## Warnings

### WR-01: `SnapshotPair` referenced in annotations but never imported in cli.py

**File:** `src/watchdirs/cli.py:1065,1089`
**Issue:** `_select_pair_for_target` and `_pair_scoped_warnings` annotate parameters/returns with `SnapshotPair`, but `SnapshotPair` is not in the `from .models import (...)` block (lines 25-33; verified via AST: not imported). Because `from __future__ import annotations` defers annotation evaluation to strings, this does not raise at import time — but it is a genuine undefined name that breaks `typing.get_type_hints()`, static type-checking (mypy/pyright), and any future `eval`-based annotation use. It is latent rot that will surface the moment annotations are introspected at runtime.
**Fix:** Add `SnapshotPair` to the models import block in `cli.py`.

### WR-02: `docker system df --format json` single-array output silently discarded

**File:** `src/watchdirs/diagnostics/docker.py:114-140`
**Issue:** `_iter_json_lines` assumes NDJSON (one object per line). Docker clients do not all agree: `docker system df --format json` emits a single JSON array (`[{...},{...}]`) in some client versions rather than newline-delimited objects. When a JSON array arrives, `json.loads` succeeds on the single line but `isinstance(decoded, dict)` is False, so the entire payload is dropped with one `docker_malformed_output` warning and `docker_available` may still flip true with zero categories. Verified: `_iter_json_lines(json.dumps([{...}]).encode())` returns `[]` plus a malformed warning. Real Docker output would then yield empty categories/build-cache totals with no clear signal that data was lost.
**Fix:** When a line decodes to a `list`, iterate its elements and accept each `dict` (recurse element-wise) instead of discarding the whole array:

```python
if isinstance(decoded, list):
    for item in decoded:
        if isinstance(item, dict):
            records.append(item)
        else:
            warnings.append(ReportWarning(code="docker_malformed_output", message="skipped a non-object Docker JSON element"))
    continue
```

### WR-03: report-time pressure summary can never surface recent growth

**File:** `src/watchdirs/cli.py:553-578`
**Issue:** `_build_report_pressure_summary` always calls `build_compact_pressure_summary(df_index=df_index, report_groups=())` with an empty `report_groups`. `summary._growth_by_domain` therefore always returns `{}` and every section's `recent_growth_disk_bytes` is 0, even though the report has already computed `summary.groups` (a `ReportGroupSummary` tuple) and `frontier_rows`. The "recent growth" column in the pressure summary is structurally dead for the `report` command. The inline comment acknowledges the gap ("re-grouping report rows by storage-domain is out of scope"), but the report does compute storage-domain group summaries when `--group-by storage-domain` is used, so the data exists and is being thrown away.
**Fix:** Pass the report's storage-domain-keyed `ReportGroupSummary` rows into `report_groups` when the group keys match the df/index domain keys (both use the same `major_minor|root|fs|source` key format), or document explicitly that growth wiring is deferred and drop the misleading `recent_growth_disk_bytes` field from the report payload until it is wired.

### WR-04: `query_indexed_storage_domain_totals` can emit negative domain totals

**File:** `src/watchdirs/reporting/queries.py:181-185`
**Issue:** The ancestor subtraction (`ancestor.disk_bytes -= row_disk`) is unbounded. If indexed aggregates are inconsistent (e.g. a submount aggregate larger than what the ancestor recorded for that subtree, which can occur with partial/stale snapshots or the gap described in CR-01), the ancestor accumulator can go negative. A negative `indexed_visible_disk_bytes` flows into `df_index._build_section` where `unattributed = max(used - indexed, 0)` would over-report unattributed bytes (treating phantom negative-indexed as real filesystem usage), producing false `deleted_open_file_suspected` hints. There is no clamp and no warning.
**Fix:** Clamp the per-domain accumulator at zero before constructing the total (`max(self.disk_bytes, 0)`), and emit a warning/coverage-reason code when a clamp occurs so the inconsistency is surfaced rather than silently masked.

### WR-05: `unknown_mount_count` is multiplied across every domain in the snapshot

**File:** `src/watchdirs/reporting/queries.py:195-201`
**Issue:** When a snapshot has `unknown_mount_count > 0`, that single count is added to **every** domain the snapshot contributes to (the loop over the domain-key set, lines 198-201). A snapshot resolving to three domains with two unknown-mount rows reports `unknown_mount_count=2` on each of the three domains, i.e. it both over-counts (6 total vs 2 actual) and mis-attributes (the unknown rows belong to no resolved domain). The downstream `unknown_mount` warning (df_index.py:138-148) and the `skipped_or_partial_scan_evidence` classifier (df_index.py:275-276) then fire on domains that may have complete coverage.
**Fix:** Attribute unknown-mount rows once, not per-domain — either to a synthetic "unknown" bucket or as a snapshot-level counter on the diagnostic, rather than fanning the same count out to each resolved domain.

### WR-06: lsof nonzero exit with usable stdout is accepted without a warning

**File:** `src/watchdirs/diagnostics/deleted_open.py:315-327`
**Issue:** When lsof exits nonzero but still writes stdout (common: lsof exits 1 on partial permission failures while emitting valid records for accessible processes), the code parses stdout and sets `used_lsof=True` with no record of the nonzero exit unless stderr happened to be non-empty. A nonzero exit means the deleted-open inventory is incomplete (some processes were inaccessible), but the diagnostic presents the partial result as authoritative with `evidence_source="lsof"` and no completeness caveat. The `permission_denied_count` total (line 354-356) only counts procfs-path warnings, so an lsof-path permission gap is invisible.
**Fix:** When `returncode not in (0, None)` and stdout was usable, append a warning (e.g. `lsof_partial`) noting the nonzero exit so the caller knows the inventory may be incomplete. Consider folding it into a completeness flag on `DeletedOpenDiagnostic`.

## Info

### IN-01: `_parse_size_text` mis-parses European decimal commas as thousands separators

**File:** `src/watchdirs/diagnostics/docker.py:93-98`
**Issue:** Digits and both `.` and `,` are accumulated into `number`, then `number.replace(",", "")` strips commas entirely. A locale-formatted Docker size like `1,5GB` becomes `15GB` (15×) rather than `1.5GB`. Docker's `--format json` is normally locale-neutral, so this is low-risk, but the silent 10× error would be hard to spot.
**Fix:** Either reject inputs containing both `.` and `,`, or treat a lone `,` as a decimal point when no `.` is present.

### IN-02: `os.fsdecode(os.fsencode(str(proc_root)))` is a redundant round-trip

**File:** `src/watchdirs/diagnostics/deleted_open.py:199`
**Issue:** `os.fsdecode(os.fsencode(str(proc_root)))` round-trips a `str` to `bytes` and back to `str`, which is a no-op for the warning message. It is dead complexity that obscures intent.
**Fix:** Use `str(proc_root)` directly.

### IN-03: df-index sections sorted twice with the second sort reversing the stable tie-break

**File:** `src/watchdirs/diagnostics/df_index.py:85-92`
**Issue:** Sections are sorted ascending by `storage_domain.key` (line 85) for a "stable secondary order", then immediately re-sorted with `reverse=True` on `(available, unattributed_or_0)` (lines 86-92). Python's sort is stable, but `reverse=True` reverses the order of equal-key runs, so the intended ascending key tie-break becomes descending for ties. The result is deterministic but not the documented ordering. Minor cosmetic ordering issue; no test depends on the tie order.
**Fix:** Use a single sort with a composite key (e.g. `key=lambda s: (s.filesystem_stat_available, s.unattributed_bytes or 0, ...)` and negate fields you want descending) instead of two passes, or apply the secondary key inside the same sort.

### IN-04: deleted-open `_flush` emits a row when a name appears with no fd

**File:** `src/watchdirs/diagnostics/deleted_open.py:89-127`
**Issue:** `_flush` returns early only when both `pending_fd is None and pending_name is None`. A malformed lsof stream that yields an `n` (name) field with no preceding `f` (fd) field produces a culprit row with `fd="?"` rather than a malformed-record warning. lsof always precedes the name with an fd field in practice, so this is defensive-only, but the fd-less branch silently fabricates `fd="?"` instead of flagging the anomaly.
**Fix:** If `pending_fd is None` but `pending_name is not None`, record a `deleted_open_malformed_record` warning rather than emitting a synthetic-fd row, to keep malformed records consistently surfaced.

---

_Reviewed: 2026-06-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
