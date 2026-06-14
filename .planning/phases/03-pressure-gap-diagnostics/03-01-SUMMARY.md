---
phase: 03-pressure-gap-diagnostics
plan: 01
subsystem: diagnostics
status: complete
tags: [diagnostics, df-vs-index, statvfs, storage-domain, reconciliation]
requires:
  - reporting/queries.resolve_top_snapshot_selection
  - db/migrations.load_snapshot_mounts
  - reporting/pairs.parse_finished_at_utc
provides:
  - diagnostics/df_index.build_df_index_diagnostic
  - reporting/queries.query_indexed_storage_domain_totals
  - reporting/render.render_df_index_payload
  - reporting/render.render_df_index_text
  - cli.run_df_vs_index (watchdirs df-vs-index)
affects:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/reporting/queries.py
  - src/watchdirs/reporting/render.py
tech-stack:
  added: []
  patterns:
    - injectable stat_provider / generated_at_provider / filesystem_scope_provider for deterministic tests
    - boundary-row aggregation with nested-submount subtraction for non-overlapping domain totals
    - per-domain OSError isolation so one statvfs failure never aborts the command
key-files:
  created:
    - src/watchdirs/diagnostics/__init__.py
    - src/watchdirs/diagnostics/df_index.py
    - tests/test_diagnostics_df_index.py
  modified:
    - src/watchdirs/models.py
    - src/watchdirs/reporting/queries.py
    - src/watchdirs/reporting/render.py
    - src/watchdirs/reporting/__init__.py
    - src/watchdirs/cli.py
decisions:
  - Indexed totals are computed per storage-domain (not per root) using boundary rows plus nested-submount subtraction, so each disk_bytes aggregate contributes to exactly one domain.
  - statvfs is probed only for storage domains returned by query_indexed_storage_domain_totals, never for every live mount.
  - Deleted-open suspicion is gated: it is emitted only when filesystem scope is covered by indexed roots AND snapshot evidence is complete; partial scope or partial snapshots downgrade the remainder to a coverage fact.
  - over_indexed_bytes is a first-class field (dataclass, JSON, text) to make snapshot-skew / indexed>df cases explicit.
metrics:
  duration: 18min
  completed: 2026-06-14
  tasks: 2
  files: 8
  tests_added: 10
  tests_total: 118
---

# Phase 3 Plan 1: df-vs-index Diagnostic Summary

`watchdirs df-vs-index --json` reconciles persisted visible indexed directory totals
against live `os.statvfs()` filesystem control totals per storage-domain, reporting an
explicit unattributed remainder, over-indexed skew, and bounded verification-only next
checks — all gated by coverage and snapshot completeness so partial evidence cannot
fabricate deleted-open conclusions.

## What Was Built

- **`query_indexed_storage_domain_totals()`** (reporting/queries.py): selects one latest
  usable snapshot per configured root, resolves each directory row to a storage-domain via
  persisted `snapshot_mounts` longest mount-prefix evidence, and computes non-overlapping
  per-domain totals using boundary rows (a row whose resolved domain differs from its
  parent's) with nested-submount aggregate subtraction from the enclosing ancestor domain.
- **`build_df_index_diagnostic()`** (diagnostics/df_index.py): probes statvfs only for the
  indexed domains, isolates each per-domain stat call so an `OSError` marks just that domain
  `stat_unavailable` (with nullable df-derived fields and a `filesystem_stat_unavailable`
  warning) while every other domain reconciles. Computes `unattributed_bytes`,
  `over_indexed_bytes`, ratios, coverage reason codes, and material-mismatch likely reasons.
- **Coverage gating:** `filesystem_scope_extends_beyond_indexed_roots` and
  `partial_snapshot_evidence` both block automatic `deleted_open_file_suspected` from
  df/index arithmetic; the remainder is surfaced as a partial-coverage fact instead.
- **Renderers** `render_df_index_payload` / `render_df_index_text` and the thin CLI command
  `df-vs-index` (`--db`, `--snapshot`, `--limit`, `--json`) with top-N truncation metadata.
- New frozen/slotted dataclasses: `FilesystemUsage`, `IndexedStorageDomainTotal`,
  `DfIndexSection`, `DfIndexDiagnostic`, `DiagnosticHint`.

## Verification

- `python3 -m pytest -q tests/test_diagnostics_df_index.py` — 10 passed (RED→GREEN).
- `python3 -m pytest -q tests/test_reporting_queries.py tests/test_cli_report_commands.py` — 46 passed.
- `python3 -m pytest -q` — 118 passed (108 prior + 10 new).
- Manual smoke test: `watchdirs df-vs-index --json` against a live host filesystem returned
  the full contract (df_bytes, indexed totals, remainder, over_indexed, ratios, likely
  reasons, coverage codes, snapshot ids/age) in JSON and terse text.

## Material Mismatch Contract

`MISMATCH_MIN_BYTES = 1 GiB` and `MISMATCH_MIN_RATIO = 0.05`; a mismatch is material only
when both the byte floor and the ratio threshold (denominator = filesystem used bytes) are
met. Verification commands are read-only: `df -h`, `watchdirs docker-enrichment --json`, and
— when deleted-open suspicion is allowed — `watchdirs deleted-open-files --json` and
`lsof +L1 -nP`. No destructive cleanup, process-control, or Docker mutation commands are ever
emitted (T-03-05).

## Threat Model Coverage

All `mitigate` dispositions in the plan threat register are satisfied: parameterized SQL
(T-03-01), snapshot ids/timestamps/age/partial counts/unknown-mount counts/warnings
(T-03-02, T-03-09), render escaping with JSON as the stable contract (T-03-03), limit range +
top-N truncation (T-03-04), verification-only commands (T-03-05), partial-coverage gating
(T-03-06), statvfs scoped to indexed domains only (T-03-07), per-domain OSError isolation
(T-03-08), and no new packages (T-03-SC).

## Deviations from Plan

None — plan executed exactly as written.

## TDD Gate Compliance

- RED: `test(03-01)` commit `4b7f661` added 10 failing tests (no module/command existed).
- GREEN: `feat(03-01)` commit `07d9210` made all 10 pass; full suite stayed green.
- REFACTOR: not required; implementation was clean on first GREEN.

## Self-Check: PASSED

All created files exist on disk and both per-task commits (`4b7f661`, `07d9210`) are present in git history.
