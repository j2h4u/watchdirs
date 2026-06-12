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
| **No-install command contract** | `./watchdirs collect` plus `PYTHONPATH=src python3 -m watchdirs collect` per D-26 |
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
| 01-W0-01 | TBD | 0 | COLL-01 | — | CLI accepts configured roots through `./watchdirs collect` and module fallback without hidden host constants | integration | `pytest tests/test_cli_collect.py::test_repo_local_collect_creates_snapshot -q` | ❌ W0 | ⬜ pending |
| 01-W0-02 | TBD | 0 | COLL-02 | — | Snapshot lifecycle preserves status, timing, root, notes, fatal error | unit | `pytest tests/test_db_schema.py::test_snapshot_lifecycle_fields -q` | ❌ W0 | ⬜ pending |
| 01-W0-03 | TBD | 0 | COLL-03 | — | Recursive rows persist hierarchy, counts, bytes, and per-path errors | integration | `pytest tests/test_scanner_semantics.py::test_recursive_rows_persisted -q` | ❌ W0 | ⬜ pending |
| 01-W0-04 | TBD | 0 | COLL-04 | — | Physical bytes use `st_blocks * 512` and align with controlled `du -skx` fixture within documented 1 KiB-per-directory tolerance | integration | `pytest tests/test_scanner_semantics.py::test_disk_bytes_match_du_for_fixture -q` | ❌ W0 | ⬜ pending |
| 01-W0-05 | TBD | 0 | COLL-05 | — | Apparent bytes follow `st_size` rules for regular files/symlinks and 0-byte contribution for non-regular special files | unit | `pytest tests/test_scanner_semantics.py::test_apparent_bytes_use_st_size_rules -q` | ❌ W0 | ⬜ pending |
| 01-W0-06 | TBD | 0 | FSEM-01 | T-01 | Symlink targets are not traversed | unit | `pytest tests/test_scanner_semantics.py::test_symlink_targets_not_descended -q` | ❌ W0 | ⬜ pending |
| 01-W0-07 | TBD | 0 | FSEM-02 | — | Hardlinks do not double-count physical bytes | unit | `pytest tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes -q` | ❌ W0 | ⬜ pending |
| 01-W0-08 | TBD | 0 | FSEM-03 | T-02 | Virtual/transient filesystems are skipped by default | unit | `pytest tests/test_mount_policy.py::test_skip_default_pseudo_filesystems -q` | ❌ W0 | ⬜ pending |
| 01-W0-09 | TBD | 0 | FSEM-04 | T-02 | Overlay and namespace mount views are skipped by default | unit | `pytest tests/test_mount_policy.py::test_skip_overlay_and_nsfs -q` | ❌ W0 | ⬜ pending |
| 01-W0-10 | TBD | 0 | FSEM-05 | T-03 | Real chmod permission errors are recorded and downgrade snapshot to partial when useful rows exist | integration | `pytest tests/test_scanner_semantics.py::test_permission_error_marks_partial_row -q` | ❌ W0 | ⬜ pending |
| 01-W0-11 | TBD | 0 | COLL-01 | T-01 | Config failures share a JSON error envelope for missing, malformed, unreadable, nonexistent-root, and file-root cases | integration | `pytest tests/test_cli_collect.py::test_collect_reports_malformed_toml_json -q` | ❌ W0 | ⬜ pending |
| 01-W0-12 | TBD | 0 | COLL-01 | — | Default user DB path falls back to `~/.local/state/watchdirs/watchdirs.sqlite3` when `XDG_STATE_HOME` is unset | unit | `pytest tests/test_cli_collect.py::test_user_db_default_falls_back_to_dot_local_state -q` | ❌ W0 | ⬜ pending |
| 01-W0-13 | TBD | 0 | COLL-02 | T-04 | SIGINT/SIGTERM finalizes active snapshots with failed status, finished_at, and interrupt error | integration | `pytest tests/test_cli_collect.py::test_collect_finalizes_snapshot_on_sigterm -q` | ❌ W0 | ⬜ pending |
| 01-W0-14 | TBD | 0 | COLL-02 | T-05 | SQLite connections enable WAL, foreign keys, busy timeout, and directory rows insert through executemany batches | unit | `pytest tests/test_db_schema.py::test_connection_pragmas_enabled -q && pytest tests/test_db_schema.py::test_insert_directory_rows_uses_executemany_batches -q` | ❌ W0 | ⬜ pending |
| 01-W0-15 | TBD | 0 | COLL-03 | T-10 | Non-UTF-8 byte paths round-trip through scanner and SQLite BLOB storage without JSON serialization failure | integration | `pytest tests/test_scanner_semantics.py::test_non_utf8_paths_round_trip_through_scanner_and_sqlite -q` | ❌ W0 | ⬜ pending |
| 01-W0-16 | TBD | 0 | COLL-03 | T-08 | Iterative post-order traversal handles a 1500-level directory tree without recursion failure | integration | `pytest tests/test_scanner_semantics.py::test_iterative_postorder_handles_deep_tree_depth_1500 -q` | ❌ W0 | ⬜ pending |
| 01-W0-17 | TBD | 0 | FSEM-02 | T-09 | Hardlink dedup has an exact resource limit path that records an error rather than growing memory without bound | unit | `pytest tests/test_scanner_semantics.py::test_hardlink_dedup_resource_limit_records_error -q` | ❌ W0 | ⬜ pending |
| 01-W0-18 | TBD | 0 | COLL-03 | T-11 | Configured exclude paths are pruned and recorded as skipped evidence | unit | `pytest tests/test_scanner_semantics.py::test_exclude_paths_are_pruned_and_recorded -q` | ❌ W0 | ⬜ pending |
| 01-W0-19 | TBD | 0 | FSEM-03 | T-14 | Default one-filesystem mode prunes child directories whose `st_dev` differs from the configured root | unit | `pytest tests/test_mount_policy.py::test_scanner_stops_at_st_dev_boundary_in_one_filesystem_mode -q` | ❌ W0 | ⬜ pending |
| 01-W0-20 | TBD | 0 | FSEM-03 | T-09 | Mountinfo path unescaping handles octal space, backslash, newline, and tab escapes | unit | `pytest tests/test_mount_policy.py::test_unescape_mount_path_handles_octal_space_backslash_newline_and_tab -q` | ❌ W0 | ⬜ pending |
| 01-W0-21 | TBD | 0 | FSEM-04 | T-13 | Bind-mount cycles are rejected or pruned by mount-id/device tracking | unit | `pytest tests/test_mount_policy.py::test_bind_mount_cycle_rejected_by_mount_id -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` - shared temporary-tree and SQLite database fixtures.
- [ ] `tests/test_cli_collect.py` - repo-local `./watchdirs collect`, module fallback, CLI command contract, and JSON output fixture coverage.
- [ ] `tests/test_scanner_semantics.py` - traversal, byte semantics, hardlink, symlink, and partial-error fixtures.
- [ ] `tests/test_mount_policy.py` - mountinfo parser and filesystem skip-policy fixtures.
- [ ] `tests/test_db_schema.py` - schema migration and snapshot lifecycle coverage.
- [ ] Package/bootstrap decision - use installed `pytest 8.3.5` and D-26 no-install command surfaces; do not require `pip` for Phase 1 verification.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Controlled `du` spot check | COLL-04, FSEM-02 | `du` is an external oracle and should validate at least one real fixture tree outside pure unit assertions | Run a fixture-backed or temporary-tree comparison using `du -x`-style semantics and confirm `disk_bytes` is within the documented 1 KiB-per-directory tolerance. |
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
