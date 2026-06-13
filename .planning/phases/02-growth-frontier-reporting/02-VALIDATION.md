---
phase: 02
slug: growth-frontier-reporting
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-13
---

# Phase 02 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `pytest -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | ~2 seconds before Phase 2 test expansion |

---

## Sampling Rate

- **After every task commit:** Run `pytest -q`
- **After every plan wave:** Run `pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-W0-01 | TBD | 0 | REPT-01, REPT-02 | T-02-01 | Report commands expose explicit current/previous/delta labels and status flags. | integration | `pytest tests/test_cli_report_commands.py -q` | no - W0 | pending |
| 02-W0-02 | TBD | 0 | REPT-03, REPT-05, REPT-06 | T-02-02 | SQL/query layer classifies rows without dynamic SQL injection from CLI fields. | unit/integration | `pytest tests/test_reporting_queries.py -q` | no - W0 | pending |
| 02-W0-03 | TBD | 0 | REPT-01, REPT-04 | T-02-03 | Frontier pruning avoids duplicate parent/child noise while explain-path preserves drill-down evidence. | unit | `pytest tests/test_frontier.py -q` | no - W0 | pending |
| 02-W0-04 | TBD | 0 | REPT-07 | T-02-04 | Grouping uses persisted snapshot-time mount metadata instead of live-only mount inference. | integration | `pytest tests/test_grouping.py -q` | no - W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cli_report_commands.py` - CLI JSON/text contracts for `diff`, `report`, `top`, `deleted`, and `explain-path`
- [ ] `tests/test_reporting_queries.py` - snapshot-pair selection, classification, top, and deleted query behavior
- [ ] `tests/test_frontier.py` - parent/child growth frontier pruning and explain-path residual logic
- [ ] `tests/test_grouping.py` - filesystem/storage-domain grouping through persisted mount metadata

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Agent ergonomics of terse text output | REPT-01, REPT-02 | LLM readability is partly qualitative. | Run `./watchdirs diff --since 24h --limit 5` and confirm the first screen labels snapshot range, path, previous/current/delta bytes, status warnings, and next inspection targets without verbose tree dumps. |

---

## Validation Sign-Off

- [ ] All tasks have automated verify commands or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all missing Phase 2 test files
- [ ] No watch-mode flags
- [ ] Feedback latency < 30 seconds
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
