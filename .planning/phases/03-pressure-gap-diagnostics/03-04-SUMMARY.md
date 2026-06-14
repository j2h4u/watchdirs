---
phase: 03-pressure-gap-diagnostics
plan: 04
subsystem: diagnostics
status: complete
tags: [diagnostics, pressure-summary, report-hints, df-index, capacity, DIAG-03, DIAG-05]
requires:
  - diagnostics/df_index.build_df_index_diagnostic
  - reporting/queries.query_indexed_storage_domain_totals
  - reporting/queries.summarize_diff_rows
  - diagnostics/deleted_open.collect_deleted_open_files
  - diagnostics/docker.collect_docker_enrichment
provides:
  - diagnostics/summary.build_compact_pressure_summary
  - reporting/render.render_report_payload (diagnostic_hints + pressure_summary fields)
  - reporting/render.render_report_text (pressure_summary lines)
  - cli.run_report (bounded report-time df/index reconciliation)
affects:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/diagnostics/__init__.py
  - src/watchdirs/diagnostics/summary.py
  - src/watchdirs/reporting/render.py
tech-stack:
  added: []
  patterns:
    - pure deterministic transform over previous-plan dataclasses (no live probes)
    - injectable report-time statvfs seam (WATCHDIRS_TEST_DF_STAT_JSON) scoped to indexed domains only
    - per-section truncation flags plus envelope limits/truncated_sections (D-14..D-16)
    - deleted-open suspicion gated by full coverage AND complete snapshot evidence OR independent probe
key-files:
  created:
    - src/watchdirs/diagnostics/summary.py
    - tests/test_diagnostics_summary.py
  modified:
    - src/watchdirs/models.py
    - src/watchdirs/diagnostics/__init__.py
    - src/watchdirs/reporting/render.py
    - src/watchdirs/cli.py
    - tests/test_cli_report_commands.py
decisions:
  - The pressure summary is a pure transformation over df/index sections, report groups, deleted-open totals, and Docker enrichment; it runs no live probes itself.
  - report computes a cheap df/index reconciliation calling statvfs only for indexed storage-domains; it never enumerates live mounts and never auto-runs lsof or Docker.
  - Report-time per-domain statvfs failures surface as filesystem_stat_unavailable hints/warnings and never crash the report (inherited from the 03-01 builder).
  - Deleted-open suspicion in report hints requires full filesystem coverage plus complete snapshot evidence, or independent deleted-open evidence; partial scope or partial snapshots downgrade the remainder to coverage facts.
  - Containerd evidence stays honest: containerd_enrichment_unavailable warnings propagate, no containerd category totals are fabricated.
  - Capacity guidance is cautious evaluation language only (upgrade/migration/repurposing as next checks); it never claims an action is safe (D-17).
metrics:
  duration: 14min
  completed: 2026-06-14
  tasks: 3
  files: 7
  tests_added: 15
  tests_total: 162
---

# Phase 3 Plan 4: Compact Pressure Summary and Report Hints Summary

`watchdirs report --since <window> --json` now answers the short "where did free
space go?" question directly: it adds a bounded `diagnostic_hints` array and a
top-N `pressure_summary` built from the Phase 3 df/index, deleted-open, and Docker
slices, honoring D-14 through D-17 (compactness, truncation, verification-only
cautious next checks) and gating deleted-open suspicion behind full filesystem
coverage plus complete snapshot evidence.

## What Was Built

- **`build_compact_pressure_summary()`** (diagnostics/summary.py): a pure,
  deterministic, side-effect-free transform that combines a `DfIndexDiagnostic`,
  report `ReportGroupSummary` growth groups, optional `DeletedOpenDiagnostic`
  totals, and optional `DockerEnrichment` into bounded `PressureSummarySection`s.
  It ranks sections by material unattributed bytes, then over-indexed skew, then
  high filesystem usage ratio; caps to `max_sections=4` and
  `max_items_per_section=5` with per-section `truncated` flags and envelope
  `limits` + `truncated_sections`; and emits prioritized verification-only
  `next_checks` (`watchdirs df-vs-index --json`, `watchdirs deleted-open-files
  --json`, `watchdirs docker-enrichment --json`, `df -h`).
- **Gating logic:** deleted-open suspicion is emitted only when the df/index
  section has full coverage AND complete snapshot evidence, OR when independent
  deleted-open evidence is supplied. `filesystem_scope_extends_beyond_indexed_roots`
  and `partial_snapshot_evidence` produce explicit coverage hints that block
  deleted-open suspicion from remainder arithmetic alone. Stat-unavailable domains
  yield `filesystem_stat_unavailable` hints/warnings and still render.
- **Capacity case:** near-full filesystems with little unexplained remainder emit
  `capacity_pressure` with cautious "evaluate upgrade/migration/repurposing"
  wording — never a destructive or "safe" claim (D-17).
- **Models:** new `PressureSummary` and `PressureSummarySection` dataclasses;
  `DiagnosticHint` gained `next_checks` and `storage_domain_key`.
- **Renderers:** `render_report_payload` / `render_report_text` accept an optional
  `pressure_summary` and emit `diagnostic_hints` + `pressure_summary` (JSON) and
  `diagnostic_hint` / `pressure_section` / `pressure_fact` / `pressure_next_check`
  (terse text), reusing the existing escaping and warning de-duplication.
- **CLI integration:** `run_report` builds a cheap df/index diagnostic via
  `build_df_index_diagnostic` (statvfs scoped to indexed storage-domains only),
  then the compact summary. A test seam `WATCHDIRS_TEST_DF_STAT_JSON` pins
  per-mountpoint df totals or forces an `OSError`, with optional
  `WATCHDIRS_TEST_DF_STAT_RECORD` to assert exactly which mount points are probed.
  No lsof or Docker probe runs during report.

## Verification

- `python3 -m pytest -q tests/test_diagnostics_summary.py` — 8 passed (RED→GREEN).
- `python3 -m pytest -q tests/test_cli_report_commands.py` — 39 passed (7 new
  report-hint cases plus the pre-existing report/diff/top/explain coverage).
- `python3 -m pytest -q tests/test_diagnostics_df_index.py
  tests/test_diagnostics_deleted_open.py tests/test_diagnostics_docker.py
  tests/test_diagnostics_summary.py` — 47 passed.
- `python3 -m pytest -q` — 162 passed (147 prior + 8 summary + 7 CLI diagnostic).

## DIAG-01 through DIAG-05 Command Evidence (live, no-mutation probes)

Collected two backdated snapshots of `src/` into a temp DB, then ran each command
read-only:

- **DIAG-01 / DIAG-02** `watchdirs df-vs-index --json`: `ok=true`, one indexed
  storage-domain, summary `total_unattributed_bytes` ~167 GiB against live
  `statvfs`, `total_over_indexed_bytes=0`, non-overlapping indexed total computed
  from boundary rows.
- **DIAG-03 / DIAG-05** `watchdirs report --since 30d --json`: `ok=true`,
  `diagnostic_hints=[unattributed_usage, filesystem_scope_extends_beyond_indexed_roots]`,
  and crucially **no** `deleted_open_file_suspected` because `/src` is a subtree of
  `/` (partial filesystem coverage gating worked live). `pressure_summary` carried
  `limits={max_sections:4, max_items_per_section:5}`, `truncated_sections=false`,
  section `unattributed_bytes` ~167 GiB, `filesystem_usage_ratio≈0.773`, and
  `next_checks=["watchdirs df-vs-index --json"]`.
- **DIAG-04** `watchdirs deleted-open-files --json`: `ok=true`,
  `evidence_source=lsof`, 42 culprits — and it ran only as an explicit command,
  not from inside `report`.
- **DIAG-04 aux** `watchdirs docker-enrichment --json`: `ok=true`,
  `docker_available=true`, `containerd_available=false`.

The closeout specifically confirms: non-overlapping df/index aggregation (03-01),
partial filesystem coverage gating (live + unit), indexed-only `statvfs()` calls
(`test_report_json_statvfs_called_only_for_indexed_domains` records exactly
`["/srv"]`), explicit `over_indexed_bytes`, injected deleted-open probes (03-02
seams), containerd unavailable warnings propagated honestly (03-03), and report
hint gating for partial scope / partial snapshots / stat failures.

## Review Feedback Closeout

`03-REVIEWS.md` Cycle 1 had one HIGH (single-root-aggregate vs whole-filesystem
statvfs attribution) — resolved in 03-01 via non-overlapping boundary-row
aggregation, and consumed correctly here through
`query_indexed_storage_domain_totals`. Cycles 2 and 3 recorded HIGH: 0. The
plan's Review Feedback table maps every finding (false df/index deleted-open
suspicion, statvfs scoping, containerd visibility, per-domain statvfs failure,
partial snapshot weakening) to Task 1/2 resolutions; all are implemented and
covered by tests. No findings were rejected.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `build_df_index_diagnostic` rejects `stat_provider=None`**
- **Found during:** Task 2 (GREEN) — the pre-existing
  `test_report_json_applies_group_by_to_deleted_preview_rows` crashed because the
  report path passed `stat_provider=None`, which the builder then tried to call.
- **Fix:** `run_report` omits the `stat_provider` kwarg entirely when no test seam
  is active, letting the builder use its live `default_stat_provider`.
- **Files modified:** src/watchdirs/cli.py
- **Commit:** 4cd4c0f

### Test fixture adjustments during GREEN

- The synthetic `_df_section` builder in `tests/test_diagnostics_summary.py` was
  given a `FilesystemUsage` so the usage-ratio contract is exercised (the real
  df/index builder always populates `df_usage` when stat is available).
- The CLI partial-coverage test was reseeded with root `/srv/app` under a `/srv`
  mount so the df/index default scope detector (which keys on the snapshot root
  vs mount point) correctly reports `filesystem_scope_extends_beyond_indexed_roots`.

These adjustments refine the RED fixtures to match the real dataclass shapes; the
asserted behavior (absent before, present after) is unchanged.

## TDD Gate Compliance

- RED: `test(03-04)` commit `1873717` added the failing summary + report-hint
  tests (module/fields absent).
- GREEN: `feat(03-04)` commit `4cd4c0f` made them pass; full suite stayed green at
  162 passed.
- REFACTOR: minor cleanup folded into GREEN (removed unused `os` import, hoisted
  the threshold import to module level); no separate refactor commit needed.

## Threat Model Coverage

All `mitigate` dispositions are satisfied: source sections / snapshot ids /
truncation fields / warning propagation in the summary (T-03-16); hints derived
only from tested df/index thresholds with no fabricated attribution (T-03-17);
report runs only cheap statvfs/index reconciliation for indexed domains, lsof and
Docker stay explicit (T-03-18); escaped text fields with cautious evidence labels
(T-03-19); verification-only next checks, no destructive / service-control /
Docker mutation commands anywhere (T-03-20); `filesystem_scope_extends_beyond_indexed_roots`
carried into hints and blocking deleted-open suspicion (T-03-21);
`filesystem_stat_unavailable` evidence rendered while the report continues
(T-03-22); partial snapshot counters/reason codes carried into hints and gating
deleted-open suspicion (T-03-23); no package installs (T-03-SC).

## Self-Check: PASSED

- Created files exist: `src/watchdirs/diagnostics/summary.py`,
  `tests/test_diagnostics_summary.py`.
- Commits present in git history: `1873717` (RED), `4cd4c0f` (GREEN).
