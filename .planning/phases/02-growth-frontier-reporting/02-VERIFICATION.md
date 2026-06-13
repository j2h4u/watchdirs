---
phase: 02-growth-frontier-reporting
verified: 2026-06-13T19:57:39Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
---

# Phase 2: Growth Frontier Reporting Verification Report

**Phase Goal:** Agents can identify what grew and where to drill down between snapshots
**Verified:** 2026-06-13T19:57:39Z
**Status:** passed
**Re-verification:** No — initial verification

Note: `ROADMAP.md` marks Phase 2 as `mode: mvp`, but the roadmap goal is not written in canonical `As a ..., I want ..., so that ...` form. The phase plans do carry that user-story wording, so the user-flow coverage below uses the plan user story plus the roadmap success criteria as the effective contract.

## User Flow Coverage

| # | User flow step | Expected outcome | Evidence in codebase | Status |
| --- | --- | --- | --- | --- |
| 1 | Inspect current biggest trees | `watchdirs top --snapshot latest --limit N --json` returns current usage rows with snapshot metadata | `run_top()` in `src/watchdirs/cli.py`, `query_top_rows()` in `src/watchdirs/reporting/queries.py`, CLI contract tests in `tests/test_cli_report_commands.py:170-240, 949-1119` | ✓ VERIFIED |
| 2 | Compare what grew since a prior point | `watchdirs diff --since 24h --limit N --json` returns ranked growth frontier rows | `run_diff()` in `src/watchdirs/cli.py`, `resolve_snapshot_pairs()` in `src/watchdirs/reporting/pairs.py`, `query_diff_rows()` and `prune_growth_frontier()` in reporting modules, tested in `tests/test_cli_report_commands.py:879-947, 1235-1460` | ✓ VERIFIED |
| 3 | Summarize the incident | `watchdirs report --since 24h --json` returns pairs, classifications, group summary, frontier, deleted preview, warnings | `run_report()` plus `summarize_diff_rows()` and `render_report_payload()`, tested in `tests/test_cli_report_commands.py:401-583` | ✓ VERIFIED |
| 4 | Look for deleted-space hints | `watchdirs deleted --since 24h --json` returns baseline-only deleted paths | `run_deleted()` plus `query_deleted_rows()`, tested in `tests/test_cli_report_commands.py:585-637` and `tests/test_reporting_queries.py:856-955` | ✓ VERIFIED |
| 5 | Explain one suspicious subtree | `watchdirs explain-path PATH --since 24h --json` resolves one exact target, returns drill-down and residuals | `run_explain_path()`, `_select_pair_for_target()`, `query_explain_path_rows()`, and `explain_path_breakdown()`, tested in `tests/test_cli_report_commands.py:639-825` and `tests/test_reporting_queries.py:957-1006` | ✓ VERIFIED |
| 6 | Attribute pressure to filesystem/storage domain | `top`, `diff`, and `report` can group from persisted snapshot-time mount metadata | `snapshot_mounts` schema/persistence in `src/watchdirs/db/schema.sql` and `src/watchdirs/db/migrations.py`, grouping in `resolve_group_for_path()`, tests in `tests/test_grouping.py:129-238` and `tests/test_cli_report_commands.py:1121-1233` | ✓ VERIFIED |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Each collected snapshot persists snapshot-time mount metadata for later report grouping. | ✓ VERIFIED | `snapshot_mounts` schema and insert/load helpers exist in `src/watchdirs/db/schema.sql` and `src/watchdirs/db/migrations.py:100-162`; collect wiring is in `src/watchdirs/cli.py:184-209`; persistence is tested in `tests/test_grouping.py:188-238`. |
| 2 | Reports group by filesystem or storage domain from stored evidence instead of live-only mount inference. | ✓ VERIFIED | `resolve_group_for_path()` loads `snapshot_mounts` for `mount`/`storage-domain` grouping in `src/watchdirs/reporting/queries.py:119-149, 366-409`; grouping contracts are tested in `tests/test_reporting_queries.py:228-311` and `tests/test_cli_report_commands.py:1121-1233`. |
| 3 | The persisted grouping model does not treat `mount_id` as a durable cross-snapshot key. | ✓ VERIFIED | Storage-domain key is composed from `major_minor|root|filesystem_type|mount_source` in `src/watchdirs/reporting/queries.py:397-408`; reuse safety is tested in `tests/test_grouping.py:241-320`. |
| 4 | Schema migration preserves v1 snapshot/directory rows and advances `PRAGMA user_version` only after schema success. | ✓ VERIFIED | Migration logic is centralized in `initialize_database()` in `src/watchdirs/db/migrations.py:15-37`; migration/idempotence coverage is in `tests/test_grouping.py` for v1 fixtures and schema version assertions. |
| 5 | `watchdirs top --snapshot latest --limit N --json` returns the largest current directory trees sorted by current disk bytes, with apparent bytes labeled separately. | ✓ VERIFIED | `query_top_rows()` orders by `disk_bytes DESC, path ASC` in `src/watchdirs/reporting/queries.py:121-137`; size semantics are tested in `tests/test_reporting_queries.py:153-225` and CLI output in `tests/test_cli_report_commands.py:170-240`. |
| 6 | `top --snapshot latest` resolves the latest usable snapshot per root and returns structured selector/limit errors. | ✓ VERIFIED | Snapshot selection and limit validation live in `src/watchdirs/reporting/queries.py:36-106`; multi-root latest and error cases are tested in `tests/test_reporting_queries.py:512-...` and `tests/test_cli_report_commands.py:949-1119`. |
| 7 | `watchdirs diff --since 24h --limit N --json` returns a compact growth frontier sorted by disk-byte growth with explicit previous/current/delta/classification fields. | ✓ VERIFIED | Same-root diff SQL is in `src/watchdirs/reporting/queries.py:171-257`; frontier pruning is in `src/watchdirs/reporting/frontier.py:9-85`; diff JSON contract is tested in `tests/test_reporting_queries.py:774-854` and `tests/test_cli_report_commands.py:1235-1414`. |
| 8 | Diff pairing is same-root and UTC-aware, and multi-root output is merged before one final global frontier limit. | ✓ VERIFIED | Pair selection and UTC parsing are in `src/watchdirs/reporting/pairs.py:23-164`; global frontier behavior is exercised in `tests/test_cli_report_commands.py:1235-1414` and parsing/error coverage in `tests/test_cli_report_commands.py:1416-1460`. |
| 9 | `watchdirs report --since 24h --json` returns a structured summary distinguishing created, deleted, unchanged, grown, and shrunk paths. | ✓ VERIFIED | `run_report()` and `summarize_diff_rows()` build raw classification counts plus frontier/group summaries from diff rows in `src/watchdirs/cli.py:424-497` and `src/watchdirs/reporting/queries.py:301-364`; tested in `tests/test_cli_report_commands.py:401-583`. |
| 10 | `watchdirs deleted --since 24h --json` and `watchdirs explain-path PATH --since 24h --json` provide deleted-space hints and exact subtree drill-down with residual math. | ✓ VERIFIED | Deleted and explain queries are in `src/watchdirs/reporting/queries.py:260-299`; explain residual math is in `src/watchdirs/reporting/frontier.py:106-159`; behavior is tested in `tests/test_cli_report_commands.py:585-825` and `tests/test_reporting_queries.py:856-1006`. |
| 11 | The end-to-end incident workflow from baseline snapshot to positive growth detection works. | ✓ VERIFIED | `tests/test_cli_report_commands.py:879-947` seeds baseline/current snapshots and proves `watchdirs diff --since 24h --json` surfaces a grown path with positive `disk_bytes_delta` and correct pair metadata. |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/watchdirs/db/schema.sql` | `snapshot_mounts` table and indexes for persisted grouping | ✓ VERIFIED | 39 lines; defines `snapshot_mounts` plus snapshot/mount-point/storage-domain indexes. |
| `src/watchdirs/db/migrations.py` | Schema v2 migration and snapshot mount persistence helpers | ✓ VERIFIED | 233 lines; `SCHEMA_VERSION`, `insert_snapshot_mounts()`, and `load_snapshot_mounts()` are implemented and used. |
| `tests/test_grouping.py` | REPT-07 and migration/persistence regression coverage | ✓ VERIFIED | 459+ lines of substantive SQLite/CLI contract coverage, including rollback and reused `mount_id` cases. |
| `src/watchdirs/reporting/queries.py` | Top/diff/report/deleted/explain query layer and grouping helpers | ✓ VERIFIED | 474 lines; dynamic SQLite queries, grouping, classification, and summary logic. |
| `src/watchdirs/reporting/render.py` | JSON/text renderers for top/diff/report/deleted/explain | ✓ VERIFIED | 598 lines; explicit JSON envelopes and escaped terse text output. |
| `tests/test_cli_report_commands.py` | CLI contract coverage for top/diff/report/deleted/explain | ✓ VERIFIED | 1400+ lines; command-level behavior and error handling coverage. |
| `src/watchdirs/reporting/pairs.py` | Same-root snapshot pairing with UTC-aware `--since` | ✓ VERIFIED | 198 lines; strict selector parsing and warning/error propagation. |
| `src/watchdirs/reporting/frontier.py` | Growth-frontier pruning and explain residual math | ✓ VERIFIED | 159 lines; two-pass frontier pruning and residual calculations. |
| `src/watchdirs/cli.py` | Thin CLI handlers wiring reporting into the main command surface | ✓ VERIFIED | `top`, `diff`, `report`, `deleted`, and `explain-path` handlers are implemented and exercised by tests. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `src/watchdirs/cli.py` | `src/watchdirs/db/migrations.py` | collect persists mountinfo rows for the snapshot id | ✓ VERIFIED | `run_collect()` calls `insert_snapshot_mounts()` inside the per-root transaction. |
| `src/watchdirs/db/migrations.py` | `src/watchdirs/collect/mounts.py` | MountInfo fields are stored as `snapshot_mounts` rows | ✓ VERIFIED | `insert_snapshot_mounts()` accepts `MountInfo` instances and stores their persisted identity fields. |
| `src/watchdirs/cli.py` | `src/watchdirs/reporting/queries.py` | top handler opens SQLite and calls `query_top_rows` | ✓ VERIFIED | `run_top()` wires selector parsing, query execution, and rendering. |
| `src/watchdirs/reporting/queries.py` | `src/watchdirs/db/migrations.py` | top grouping loads `snapshot_mounts` by snapshot id | ✓ VERIFIED | `query_top_rows()` and `query_diff_rows()` call `load_snapshot_mounts()` for mount/domain grouping. |
| `src/watchdirs/cli.py` | `src/watchdirs/reporting/pairs.py` | diff handler resolves same-root pairs for `--since` | ✓ VERIFIED | `run_diff()`, `run_report()`, `run_deleted()`, and `run_explain_path()` all call `resolve_snapshot_pairs()`. |
| `src/watchdirs/reporting/pairs.py` | `src/watchdirs/reporting/queries.py` | each valid pair feeds raw diff query | ✓ VERIFIED | Pair outputs are consumed by `query_diff_rows()`, `query_deleted_rows()`, and `query_explain_path_rows()`. |
| `src/watchdirs/reporting/queries.py` | `src/watchdirs/reporting/frontier.py` | raw rows are pruned into default growth frontier | ✓ VERIFIED | `run_diff()` and `run_report()` pass diff rows through `prune_growth_frontier()`. |
| `src/watchdirs/reporting/queries.py` | `src/watchdirs/reporting/render.py` | classification rows become JSON/text payloads with explicit labels | ✓ VERIFIED | CLI handlers render query results through `render_*_payload()` / `render_*_text()`. |
| `src/watchdirs/reporting/queries.py` | `src/watchdirs/db/schema.sql` | queries read `directory_sizes` and `snapshot_mounts` only | ✓ VERIFIED | Reporting code reads persisted snapshot tables; no live rescans occur in report commands. |
| `src/watchdirs/cli.py` | `src/watchdirs/reporting/frontier.py` | explain-path handler reuses exact subtree breakdown | ✓ VERIFIED | `run_explain_path()` calls `explain_path_breakdown()` after exact-row selection. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `src/watchdirs/cli.py` collect path | `mounts` | `load_mountinfo()` -> `insert_snapshot_mounts()` -> `snapshot_mounts` rows | Yes; verified by `tests/test_grouping.py:188-238` and round-trips in `load_snapshot_mounts()` | ✓ FLOWING |
| `src/watchdirs/reporting/queries.py` top | `query_rows` / `rows` | `directory_sizes` for one snapshot plus `snapshot_mounts` for grouping | Yes; SQL reads persisted snapshot rows and grouping metadata | ✓ FLOWING |
| `src/watchdirs/reporting/queries.py` diff | `query_rows` / `rows` | CTE union of baseline/current `directory_sizes` plus `snapshot_mounts` for grouping | Yes; dynamic previous/current/delta/classification fields are computed from persisted rows | ✓ FLOWING |
| `src/watchdirs/cli.py` report | `diff_rows`, `deleted_rows`, `summary` | `query_diff_rows()` + `query_deleted_rows()` + `summarize_diff_rows()` | Yes; report payload is assembled from live query results, not static placeholders | ✓ FLOWING |
| `src/watchdirs/cli.py` explain-path | `rows`, `breakdown` | `query_explain_path_rows()` + `explain_path_breakdown()` | Yes; target/children/residuals derive from exact matched diff rows | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full regression surface stays green after Phase 02 review fixes | `python3 -m pytest -q` | `108 passed in 6.98s` | ✓ PASS |
| Latest per-root top reporting works with partial warnings | `python3 -m pytest -q tests/test_cli_report_commands.py::test_top_latest_returns_latest_usable_snapshot_per_root_with_partial_warnings` | `1 passed in 0.13s` | ✓ PASS |
| Structured report summary returns pairs/frontier/groups/deleted preview | `python3 -m pytest -q tests/test_cli_report_commands.py::test_report_json_returns_pairs_summary_groups_frontier_deleted_preview_and_warnings` | `1 passed in 0.13s` | ✓ PASS |
| End-to-end diff incident workflow detects positive growth | `python3 -m pytest -q tests/test_cli_report_commands.py::test_diff_end_to_end_incident_workflow_detects_positive_growth` | `1 passed in 0.13s` | ✓ PASS |
| Exact explain-path normalization and residual drill-down work | `python3 -m pytest -q tests/test_cli_report_commands.py::test_explain_path_json_normalizes_user_path_and_returns_drilldown_with_residuals` | `1 passed in 0.15s` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Step 7c | Probe discovery in `scripts/**/tests/probe-*.sh` and phase docs | No probes declared or found | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `REPT-01` | `02-03`, `02-04` | `diff --since 24h --limit N --json` lists paths sorted by disk-byte growth | ✓ SATISFIED | `run_diff()` in `src/watchdirs/cli.py:358-422`, diff SQL/pruning in reporting modules, CLI tests `tests/test_cli_report_commands.py:879-947, 1235-1414`. |
| `REPT-02` | `02-04` | `report --since 24h --json` returns a structured investigation summary | ✓ SATISFIED | `run_report()` in `src/watchdirs/cli.py:424-497`, summary logic in `src/watchdirs/reporting/queries.py:301-364`, tests `tests/test_cli_report_commands.py:401-583`. |
| `REPT-03` | `02-02` | `top --snapshot latest --limit N --json` lists largest current directory trees | ✓ SATISFIED | `run_top()` in `src/watchdirs/cli.py:291-356`, `query_top_rows()` in `src/watchdirs/reporting/queries.py:109-168`, tests `tests/test_cli_report_commands.py:170-240, 949-1119`. |
| `REPT-04` | `02-04` | `explain-path PATH --since 24h --json` drills into one subtree's growth | ✓ SATISFIED | `run_explain_path()` and `explain_path_breakdown()`, tests `tests/test_cli_report_commands.py:639-825` and `tests/test_reporting_queries.py:957-1006`. |
| `REPT-05` | `02-04` | `deleted --since 24h --json` lists paths present earlier but absent later | ✓ SATISFIED | `run_deleted()` plus `query_deleted_rows()`, tests `tests/test_cli_report_commands.py:585-637` and `tests/test_reporting_queries.py:856-955`. |
| `REPT-06` | `02-03`, `02-04` | Reports distinguish created, deleted, unchanged, grown, and shrunk paths | ✓ SATISFIED | Classification SQL in `src/watchdirs/reporting/queries.py:204-212`, query tests `tests/test_reporting_queries.py:774-854`, report summary tests `tests/test_cli_report_commands.py:401-509`. |
| `REPT-07` | `02-01` through `02-04` | Reports group usage/growth by filesystem or mounted storage domain | ✓ SATISFIED | Persisted mount metadata in schema/migrations, grouping logic in `resolve_group_for_path()`, tests `tests/test_grouping.py:129-238`, `tests/test_reporting_queries.py:228-311, 376-509`, and `tests/test_cli_report_commands.py:511-583, 1121-1233`. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| Phase-modified implementation files | - | None | ℹ️ Info | No `TODO`/`FIXME`/`XXX` debt markers, placeholder text, or stub return paths were found. Grep hits for empty lists were confined to test fixtures/assertions, not runtime code. |

### Human Verification Required

None. This phase is a local CLI/reporting surface with deterministic SQLite-backed behavior, and the critical user flows were verified through code inspection plus command-level tests.

### Gaps Summary

No implementation gaps were found against the Phase 02 roadmap success criteria, plan must-haves, or requirement IDs `REPT-01` through `REPT-07`. The repository contains real persisted snapshot-time mount metadata, wired reporting commands (`top`, `diff`, `report`, `deleted`, `explain-path`), non-placeholder data flow from SQLite snapshots into rendered output, and end-to-end coverage for the target incident workflow.

---

_Verified: 2026-06-13T19:57:39Z_
_Verifier: the agent (gsd-verifier)_
