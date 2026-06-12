---
phase: 01
slug: trusted-snapshot-collection
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-12
---

# Phase 01 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 8.3.5` installed locally |
| **Config file** | none yet - Wave 0 creates test scaffold |
| **Quick run command** | `pytest tests/test_scanner_semantics.py -q` |
| **Full suite command** | `pytest -q` |
| **Estimated runtime** | < 10 seconds for Phase 1 unit/integration fixtures |

---

## Sampling Rate

- **After every task commit:** Run the narrowest relevant `pytest ... -q` command for the touched module.
- **After every plan wave:** Run `pytest -q`.
- **Before `/gsd-verify-work`:** Full suite must be green and one controlled `du` comparison must pass.
- **Max feedback latency:** 10 seconds for automated tests in this phase.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-W0-01 | TBD | 0 | COLL-01 | — | CLI accepts configured roots without hidden host constants | integration | `pytest tests/test_cli_collect.py::test_collect_creates_snapshot -q` | ❌ W0 | ⬜ pending |
| 01-W0-02 | TBD | 0 | COLL-02 | — | Snapshot lifecycle preserves status, timing, root, notes, fatal error | unit | `pytest tests/test_db_schema.py::test_snapshot_lifecycle_fields -q` | ❌ W0 | ⬜ pending |
| 01-W0-03 | TBD | 0 | COLL-03 | — | Recursive rows persist hierarchy, counts, bytes, and per-path errors | integration | `pytest tests/test_scanner_semantics.py::test_recursive_rows_persisted -q` | ❌ W0 | ⬜ pending |
| 01-W0-04 | TBD | 0 | COLL-04 | — | Physical bytes use `st_blocks * 512` and align with controlled `du` fixture | integration | `pytest tests/test_scanner_semantics.py::test_disk_bytes_match_du_for_fixture -q` | ❌ W0 | ⬜ pending |
| 01-W0-05 | TBD | 0 | COLL-05 | — | Apparent bytes follow `st_size` rules for regular files and symlinks | unit | `pytest tests/test_scanner_semantics.py::test_apparent_bytes_use_st_size_rules -q` | ❌ W0 | ⬜ pending |
| 01-W0-06 | TBD | 0 | FSEM-01 | T-01 | Symlink targets are not traversed | unit | `pytest tests/test_scanner_semantics.py::test_symlink_targets_not_descended -q` | ❌ W0 | ⬜ pending |
| 01-W0-07 | TBD | 0 | FSEM-02 | — | Hardlinks do not double-count physical bytes | unit | `pytest tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes -q` | ❌ W0 | ⬜ pending |
| 01-W0-08 | TBD | 0 | FSEM-03 | T-02 | Virtual/transient filesystems are skipped by default | unit | `pytest tests/test_mount_policy.py::test_skip_default_pseudo_filesystems -q` | ❌ W0 | ⬜ pending |
| 01-W0-09 | TBD | 0 | FSEM-04 | T-02 | Overlay and namespace mount views are skipped by default | unit | `pytest tests/test_mount_policy.py::test_skip_overlay_and_nsfs -q` | ❌ W0 | ⬜ pending |
| 01-W0-10 | TBD | 0 | FSEM-05 | T-03 | Permission/stat errors are recorded and downgrade snapshot to partial when useful rows exist | integration | `pytest tests/test_scanner_semantics.py::test_permission_error_marks_partial_row -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` - shared temporary-tree and SQLite database fixtures.
- [ ] `tests/test_cli_collect.py` - CLI command contract and JSON output fixture coverage.
- [ ] `tests/test_scanner_semantics.py` - traversal, byte semantics, hardlink, symlink, and partial-error fixtures.
- [ ] `tests/test_mount_policy.py` - mountinfo parser and filesystem skip-policy fixtures.
- [ ] `tests/test_db_schema.py` - schema migration and snapshot lifecycle coverage.
- [ ] Package/bootstrap decision - either use installed `pytest 8.3.5` or add an explicit bootstrap task before isolated env setup.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Controlled `du` spot check | COLL-04, FSEM-02 | `du` is an external oracle and should validate at least one real fixture tree outside pure unit assertions | Run a fixture-backed or temporary-tree comparison using `du -x`-style semantics and compare expected `disk_bytes`. |
| Live mount classifier sanity check | FSEM-03, FSEM-04 | Unit tests can cover synthetic mountinfo, but host safety depends on the live mount table shape | Run the collector or classifier dry path against current `/proc/self/mountinfo` and confirm pseudo/container filesystems are skipped. |

---

## Validation Sign-Off

- [ ] All tasks have automated `pytest` verification or Wave 0 dependencies.
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify.
- [ ] Wave 0 covers all missing test files.
- [ ] No watch-mode flags.
- [ ] Feedback latency < 10s.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending
