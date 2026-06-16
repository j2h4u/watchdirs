---
phase: 04
slug: scheduled-retention-operations
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-17
---

# Phase 04 - Validation Strategy

Per-phase validation contract for scheduled retention operations.

This file is derived from `04-RESEARCH.md` section `## Validation Architecture` and is the execution-phase Nyquist gate for OPER-01 through OPER-06.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py -q -x` |
| Full suite command | `uv run pytest -q` |
| Estimated runtime | Target under 60 seconds for the Phase 04 targeted suite |

---

## Sampling Rate

- After every RED test scaffold: run the relevant selector and confirm it fails for the missing behavior, not for import syntax or collection errors.
- After every task implementation: run that task's `<verify><automated>` command from the active `04-*-PLAN.md`.
- After every wave: run the accumulated Phase 04 targeted suite through the current wave.
- Before `/gsd-verify-work`: run the full Phase 04 targeted suite and `uv run pytest -q`. On the target host, run `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer` as advisory pre-deployment validation once systemd assets exist.
- Max feedback latency: keep targeted task checks under 60 seconds.

---

## Requirement To Test Map

| Req ID | Plan | Wave | Behavior | Test Type | Automated Command | Test File Status |
|--------|------|------|----------|-----------|-------------------|------------------|
| OPER-01 | 04-04 | 4 | Repo provides collect, prune, and vacuum systemd service/timer units with oneshot services and absolute `/usr/local/bin/watchdirs` ExecStart command surfaces. | unit/file contract | `uv run pytest tests/test_systemd_units.py::test_systemd_unit_files_exist_and_use_oneshot -q -x` | planned in 04-04 |
| OPER-02 | 04-04 | 4 | Scheduled collect service carries low CPU and I/O priority settings. | unit/file contract | `uv run pytest tests/test_systemd_units.py::test_collect_service_low_priority_settings -q -x` | planned in 04-04 |
| OPER-03 | 04-01 | 1 | A concurrent collect writer fails fast through the shared operation lock before creating duplicate or corrupt snapshot evidence. | integration | `uv run pytest tests/test_ops_locking.py::test_collect_lock_conflict_fails_fast_without_snapshot_write -q -x` | planned in 04-01 |
| OPER-04 | 04-02 | 2 | Prune keeps all recent hourly snapshots of every status, then latest COMPLETE snapshot per `root_path` per UTC day/month bucket, deletes aged PARTIAL/FAILED snapshots rather than promoting them, deletes whole snapshots only, removes orphan `paths`, and is idempotent on a second run. | unit/integration | `uv run pytest tests/test_ops_retention.py::test_prune_keeps_latest_complete_per_root_day_month_and_gcs_paths tests/test_ops_retention.py::test_prune_second_run_is_noop -q -x` | planned in 04-02 |
| OPER-05 | 04-03 | 3 | Vacuum is a separate slower maintenance path, uses the shared lock, emits before/after counters, reports free-space advisory fields and WAL checkpoint status, and fails visibly on lock contention. | unit/integration | `uv run pytest tests/test_ops_vacuum.py::test_vacuum_requires_writer_lock_and_reports_counters -q -x` | planned in 04-03 |
| OPER-06 | 04-04 | 4 | README documents the service command path, live DB path, config path, timer names, retention policy, and verification commands. | unit/file contract | `uv run pytest tests/test_systemd_units.py::test_readme_documents_operations_and_verification_commands -q -x` | planned in 04-04 |

Named tests above are the preferred selectors. If implementation uses equivalent test names, the executor must preserve one automated selector per requirement in this file or update this validation map in the same commit.

---

## Wave Validation Expectations

| Execution Point | Required Automated Validation |
|-----------------|-------------------------------|
| After 04-01 | `uv run pytest tests/test_ops_locking.py -q -x` |
| After 04-02 | `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py -q -x` |
| After 04-03 | `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py -q -x` |
| After 04-04 | `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py -q -x` |
| Phase gate | `uv run pytest -q` |

Execution must not count manual inspection as a replacement for the automated requirement map. Manual live-host enablement of timers and target-host `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer` can happen after repository assets are implemented and pytest file-contract tests pass; they are not substitutes for automated file-contract tests.

---

## Wave 0 Test Scaffold Expectations

- [ ] `tests/test_ops_locking.py` - created first in Plan 04-01 RED step for OPER-03.
- [ ] `tests/test_ops_retention.py` - created first in Plan 04-02 RED step for OPER-04, including latest-COMPLETE per-root UTC day/month retention, PARTIAL/FAILED aging behavior, and double-prune idempotency.
- [ ] `tests/test_ops_vacuum.py` - created first in Plan 04-03 RED step for OPER-05, including free-space advisory fields and WAL checkpoint status visibility.
- [ ] `tests/test_systemd_units.py` - created first in Plan 04-04 for OPER-01, OPER-02, and OPER-06 file-contract coverage, including absolute command path and prune timer collision avoidance.
- [ ] Synthetic multi-root snapshot timeline fixtures exist before retention logic is implemented.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live enabling of timers on `senbonzakura` | OPER-01, OPER-06 | Repository planning and execution can ship unit assets and docs, but enabling host timers changes live machine state. | After phase implementation, the operator may copy/install units, enable timers, then run `systemctl list-timers 'watchdirs-*'` and journal checks documented in README. |
| Target-host systemd unit validation | OPER-01, OPER-02 | `systemd-analyze verify` is useful operational evidence, but it can be unavailable or environment-dependent in CI/container contexts. | On `senbonzakura` or another systemd host, run `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer` before installing/enabling units. |

---

## Validation Sign-Off

- [x] Every OPER-01 through OPER-06 requirement has an automated test selector.
- [x] Every code-producing plan has a task-level automated verify command.
- [x] Sampling continuity is defined for every wave.
- [x] No watch-mode flags are required.
- [x] Execution-phase systemd validation is covered by automated pytest file-contract tests; `systemd-analyze verify` is target-host advisory validation.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** draft 2026-06-17
