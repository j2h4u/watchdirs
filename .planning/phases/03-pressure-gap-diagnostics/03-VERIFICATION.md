---
phase: 03-pressure-gap-diagnostics
verified: 2026-06-14T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
mode: mvp
---

# Phase 3: Pressure Gap Diagnostics Verification Report

**Phase Goal:** Agents can reconcile indexed growth with real filesystem pressure and supporting evidence (Mode: mvp)
**Verified:** 2026-06-14
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is a Mode: mvp user-story goal ("Agents can reconcile indexed growth with real filesystem pressure and supporting evidence"). The ROADMAP Success Criteria 1-5 are the success conditions and map 1:1 to DIAG-01 through DIAG-05. Every criterion was verified by running the actual CLI against a live snapshot, not by trusting SUMMARY.md.

### User Flow Coverage

| Step (Success Criterion) | Expected | Evidence in codebase | Status |
|---|---|---|---|
| SC1 (DIAG-01) compare filesystem usage vs indexed totals | `watchdirs df-vs-index --json` returns control totals beside indexed totals | Live run: `ok=true`, 1 filesystem, `summary` has `total_indexed_visible_disk_bytes`, `total_unattributed_bytes`, `total_over_indexed_bytes`; section carried `df_bytes`, `unattributed_bytes=167412166656`, `over_indexed_bytes=0` | VERIFIED |
| SC2 (DIAG-02) inspect deleted-open files | `watchdirs deleted-open-files --json` lists files held open after deletion | Live run: `ok=true`, `evidence_source=lsof`, `culprit_count=35`, stable envelope | VERIFIED |
| SC3 (DIAG-03) flag deleted-open suspicion on material divergence | report flags suspicion instead of silently incomplete; gated by coverage/snapshot completeness | Live `report --since 30d --json`: `ok=true`, `diagnostic_hints=[unattributed_usage, filesystem_scope_extends_beyond_indexed_roots]`; `deleted_open_file_suspected` correctly **suppressed** because `/src` is a subtree of `/` (partial coverage gating) | VERIFIED |
| SC4 (DIAG-04) Docker/containerd evidence separating reclaimable vs active | `watchdirs docker-enrichment --json` collects Docker CLI category evidence | Live run: `ok=true`, `docker_available=true`, `containerd_available=false`; categories + build_cache parsed via fixed read-only argv | VERIFIED |
| SC5 (DIAG-05) summarize disk-subsystem pressure for capacity decisions | compact pressure summary supporting upgrade/migrate/repurpose decisions | Live `report` `pressure_summary` present: `limits={max_sections:4,max_items_per_section:5}`, `truncated_sections=false`, section `filesystem_usage_ratio=0.773`, `unattributed_bytes`, prioritized `next_checks` | VERIFIED |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `src/watchdirs/diagnostics/df_index.py` | statvfs-backed reconciliation, `build_df_index_diagnostic` | VERIFIED | 343 lines; per-domain stat isolation, non-overlapping totals, mismatch thresholds, scope gating, over_indexed |
| `src/watchdirs/diagnostics/deleted_open.py` | lsof/procfs probe, `collect_deleted_open_files`, `parse_lsof_field_output` | VERIFIED | 419 lines; injectable lsof_runner + proc_root seams, NUL-field parser, procfs fallback; no directory_sizes writes (D-10) |
| `src/watchdirs/diagnostics/docker.py` | Docker CLI adapters, `collect_docker_enrichment`, `parse_docker_system_df`, `parse_docker_buildx_du` | VERIFIED | 414 lines; fixed read-only argv, NDJSON parsing, containerd path-hint honesty |
| `src/watchdirs/diagnostics/summary.py` | compact summary, `build_compact_pressure_summary` | VERIFIED | 375 lines; pure transform, top-N ranking, truncation, gating logic |
| `src/watchdirs/reporting/queries.py` | `query_indexed_storage_domain_totals` | VERIFIED | Boundary-row detection + nested-submount subtraction guarantees each aggregate maps to at most one domain |
| `src/watchdirs/reporting/render.py` | df-index/deleted-open/docker/report renderers + diagnostic_hints/pressure_summary | VERIFIED | All payload functions present; emits over_indexed_bytes, containerd_available, hint codes |
| `src/watchdirs/cli.py` | 4 commands registered | VERIFIED | `df-vs-index`, `deleted-open-files`, `docker-enrichment` parsers + `run_report` integration all wired with handlers |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| cli.py | diagnostics/df_index.py | `build_df_index_diagnostic` | WIRED | `run_df_vs_index` and `_build_report_pressure_summary` both call it |
| cli.py | diagnostics/deleted_open.py | `collect_deleted_open_files` | WIRED | `run_deleted_open_files` calls it |
| cli.py | diagnostics/docker.py | `collect_docker_enrichment` | WIRED | `run_docker_enrichment` calls it |
| cli.py | diagnostics/summary.py | `build_compact_pressure_summary` | WIRED | `_build_report_pressure_summary` calls it; output flows to render_report_payload |
| df_index.py | reporting/queries.py | `query_indexed_storage_domain_totals` | WIRED | Builder consumes persisted indexed totals |
| queries.py | snapshot_mounts / directory_sizes | longest-prefix resolution | WIRED | Reads both tables, resolves per-row storage-domain |

### Data-Flow Trace (Level 4)

| Artifact | Data Source | Produces Real Data | Status |
|---|---|---|---|
| df-vs-index output | live `os.statvfs()` + persisted `directory_sizes`/`snapshot_mounts` | Yes — live run returned real 167 GiB unattributed against actual filesystem | FLOWING |
| deleted-open output | live `lsof +L1` (default) / procfs fallback | Yes — 35 real culprits from host lsof | FLOWING |
| docker output | live `docker system df` / `docker buildx du` | Yes — real `docker_available=true` from host daemon | FLOWING |
| report pressure_summary | df/index reconciliation + report groups | Yes — real usage_ratio 0.773 from live statvfs | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| df-vs-index runs | `watchdirs df-vs-index --db ... --json` | ok=true, 1 fs, full summary | PASS |
| deleted-open runs | `watchdirs deleted-open-files --db ... --json --limit 3` | ok=true, lsof, 35 culprits | PASS |
| docker-enrichment runs | `watchdirs docker-enrichment --db ... --json` | ok=true, docker_available=true | PASS |
| report diagnostic hints + gating | `watchdirs report --db ... --since 30d --json` | ok=true, hints present, deleted_open correctly suppressed for subtree | PASS |
| CLI help lists commands | `watchdirs --help` | all 3 new commands listed | PASS |
| Diagnostics tests exist | `pytest --collect-only` | 47 tests collected | PASS |
| Full suite | `uv run --with pytest pytest -q` | 162 passed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| DIAG-01 | 03-01 | `df-vs-index --json` compares fs usage vs indexed totals | SATISFIED | Live run returns control totals + indexed totals + remainder |
| DIAG-02 | 03-02 | deleted-open diagnostic reports files held open after deletion | SATISFIED | Live run: 35 culprits via lsof |
| DIAG-03 | 03-01, 03-02, 03-04 | reports call out deleted-open suspicion on material divergence | SATISFIED | report diagnostic_hints + gating (suppressed correctly for partial coverage) |
| DIAG-04 | 03-03 | Docker/containerd enrichment via Docker CLI | SATISFIED | Live run: docker_available=true, containerd path-hint honesty |
| DIAG-05 | 03-01, 03-03, 03-04 | summarize pressure by disk/subsystem for capacity decisions | SATISFIED | pressure_summary with usage ratio, limits, cautious capacity next checks |

All 5 requirement IDs from PLAN frontmatter (DIAG-01..05) are present in REQUIREMENTS.md Phase 3 and accounted for. No orphaned requirements: REQUIREMENTS.md maps exactly DIAG-01..05 to Phase 3, all covered by plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| (none) | - | No TBD/FIXME/XXX/HACK/PLACEHOLDER markers in any Phase 3 file | - | - |
| (none) | - | No mutation commands (docker rm/prune, rm -rf, kill, systemctl stop) in diagnostics | - | Read-only contract D-13/D-17 honored |
| (none) | - | deleted_open.py performs no directory_sizes writes | - | D-10 honored |

### Human Verification Required

None. All success criteria were verifiable programmatically by running the actual CLI commands against a live snapshot and observing real evidence flow. No visual/UX/real-time concerns — this is an agent-facing JSON CLI.

### Gaps Summary

No gaps. Every ROADMAP Success Criterion (SC1-SC5 = DIAG-01..05) was exercised end-to-end against a live database:

- The non-overlapping storage-domain aggregation, partial-coverage gating, indexed-only statvfs scoping, and `over_indexed_bytes` are genuinely implemented (read in `queries.py` and `df_index.py`), not stubs.
- The deleted-open suspicion gating worked **live**: against `/src` (a subtree of `/`), the report correctly emitted `filesystem_scope_extends_beyond_indexed_roots` and suppressed `deleted_open_file_suspected` — the exact DIAG-03 contract behavior.
- Read-only constraints (D-10, D-13, D-17) verified by source scan: no directory_sizes writes from deleted-open, no Docker/process mutation commands anywhere.
- Full suite is 162 passed in a single run; all claimed RED→GREEN TDD commits exist in git history.

Note: One harness friction during spot-checks (not a code defect): `collect` requires `[[roots]]` TOML tables and `report` requires two same-root snapshots with valid ISO-Z timestamps. Both are correct Phase 1/2 preconditions; once satisfied, the Phase 3 chain ran fully.

---

_Verified: 2026-06-14_
_Verifier: Claude (gsd-verifier)_
