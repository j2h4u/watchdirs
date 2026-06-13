---
phase: 01
slug: trusted-snapshot-collection
status: complete
nyquist_compliant: true
wave_0_complete: true
audited_at: 2026-06-13T00:00:00Z
audited_by: codex
suite_status: green
suite_command: "pytest tests/test_cli_collect.py tests/test_db_schema.py tests/test_scanner_semantics.py tests/test_mount_policy.py -q"
suite_result: "51 passed in 4.27s"
---

# Phase 01 Validation

## Status

Phase 01 validation is green for `COLL-01` through `COLL-05` and `FSEM-01` through `FSEM-05`.

No new automated coverage gaps were found in the current repo state. The prior draft was stale because it referenced nonexistent `SUMMARY.md` / `REQUIREMENTS.md` files inside the phase directory and still marked implemented tests as Wave 0 pending.

## Test Infrastructure

| Property | Value |
|---|---|
| Framework | `pytest` |
| Test files | `tests/test_cli_collect.py`, `tests/test_db_schema.py`, `tests/test_scanner_semantics.py`, `tests/test_mount_policy.py` |
| No-install command surface | `./watchdirs collect`, `PYTHONPATH=src python3 -m watchdirs collect` |
| Focused suite | `pytest tests/test_cli_collect.py tests/test_db_schema.py tests/test_scanner_semantics.py tests/test_mount_policy.py -q` |
| Full suite | `pytest -q` |
| Latest focused result | `51 passed in 4.27s` |

## Requirement Map

| Requirement | Covered By | Test Type | Automated Command | Status |
|---|---|---|---|---|
| `COLL-01` | `test_repo_local_collect_creates_snapshot`, `test_module_collect_creates_snapshot`, `test_repo_local_collect_help_matches_module_help` | integration | `pytest tests/test_cli_collect.py::test_repo_local_collect_creates_snapshot tests/test_cli_collect.py::test_module_collect_creates_snapshot tests/test_cli_collect.py::test_repo_local_collect_help_matches_module_help -q` | green |
| `COLL-02` | `test_snapshot_lifecycle_fields`, `test_collect_json_row_count_matches_inserted_rows`, `test_failed_snapshot_records_fatal_error`, `test_collect_finalizes_snapshot_on_sigterm` | unit + integration | `pytest tests/test_db_schema.py::test_snapshot_lifecycle_fields tests/test_cli_collect.py::test_collect_json_row_count_matches_inserted_rows tests/test_cli_collect.py::test_failed_snapshot_records_fatal_error tests/test_cli_collect.py::test_collect_finalizes_snapshot_on_sigterm -q` | green |
| `COLL-03` | `test_recursive_rows_persisted`, `test_non_utf8_paths_round_trip_through_scanner_and_sqlite`, `test_iterative_postorder_handles_deep_tree_depth_1500`, `test_exclude_paths_are_pruned_and_recorded` | integration | `pytest tests/test_scanner_semantics.py::test_recursive_rows_persisted tests/test_scanner_semantics.py::test_non_utf8_paths_round_trip_through_scanner_and_sqlite tests/test_scanner_semantics.py::test_iterative_postorder_handles_deep_tree_depth_1500 tests/test_scanner_semantics.py::test_exclude_paths_are_pruned_and_recorded -q` | green |
| `COLL-04` | `test_disk_bytes_match_du_for_fixture`, `test_hardlinks_dedup_disk_bytes` | integration | `pytest tests/test_scanner_semantics.py::test_disk_bytes_match_du_for_fixture tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes -q` | green |
| `COLL-05` | `test_apparent_bytes_use_st_size_rules` | unit | `pytest tests/test_scanner_semantics.py::test_apparent_bytes_use_st_size_rules -q` | green |
| `FSEM-01` | `test_symlink_targets_not_descended`, `test_symlink_root_is_rejected_without_following_target` | unit | `pytest tests/test_scanner_semantics.py::test_symlink_targets_not_descended tests/test_scanner_semantics.py::test_symlink_root_is_rejected_without_following_target -q` | green |
| `FSEM-02` | `test_hardlinks_dedup_disk_bytes`, `test_hardlink_dedup_resource_limit_records_error` | unit | `pytest tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes tests/test_scanner_semantics.py::test_hardlink_dedup_resource_limit_records_error -q` | green |
| `FSEM-03` | `test_skip_default_pseudo_filesystems`, `test_scanner_stops_at_st_dev_boundary_in_one_filesystem_mode`, `test_collect_accepts_mountinfo_override` | unit + integration | `pytest tests/test_mount_policy.py::test_skip_default_pseudo_filesystems tests/test_mount_policy.py::test_scanner_stops_at_st_dev_boundary_in_one_filesystem_mode tests/test_cli_collect.py::test_collect_accepts_mountinfo_override -q` | green |
| `FSEM-04` | `test_skip_overlay_and_nsfs`, `test_bind_mount_cycle_rejected_by_mount_id` | unit | `pytest tests/test_mount_policy.py::test_skip_overlay_and_nsfs tests/test_mount_policy.py::test_bind_mount_cycle_rejected_by_mount_id -q` | green |
| `FSEM-05` | `test_permission_error_marks_partial_row` | integration | `pytest tests/test_scanner_semantics.py::test_permission_error_marks_partial_row -q` | green |

## Per-Task Map

| Task ID | Plan | Requirement | Evidence | Command | Status |
|---|---|---|---|---|---|
| `01-01-T1` | `01-01` | `COLL-01` | No-install command surface and config contract | `pytest tests/test_cli_collect.py::test_repo_local_collect_help_matches_module_help -q` | green |
| `01-01-T1` | `01-01` | `COLL-01` | JSON config failures and explicit roots | `pytest tests/test_cli_collect.py::test_collect_reports_malformed_toml_json tests/test_cli_collect.py::test_collect_rejects_nonexistent_root_json tests/test_cli_collect.py::test_collect_rejects_file_root_json -q` | green |
| `01-02-T1` | `01-02` | `COLL-01`, `COLL-02` | Snapshot creation and persisted rows | `pytest tests/test_cli_collect.py::test_repo_local_collect_creates_snapshot tests/test_cli_collect.py::test_module_collect_creates_snapshot -q` | green |
| `01-02-T1` | `01-02` | `COLL-02` | Schema, lifecycle, pragmas, batching, interrupt durability | `pytest tests/test_db_schema.py -q tests/test_cli_collect.py::test_collect_finalizes_snapshot_on_sigterm tests/test_cli_collect.py::test_collect_rolls_back_partial_directory_insert_on_sigterm -q` | green |
| `01-03-T1` | `01-03` | `COLL-03`, `COLL-04`, `COLL-05` | Recursive aggregate, byte semantics, deep-tree, non-UTF-8, excludes | `pytest tests/test_scanner_semantics.py::test_recursive_rows_persisted tests/test_scanner_semantics.py::test_non_utf8_paths_round_trip_through_scanner_and_sqlite tests/test_scanner_semantics.py::test_iterative_postorder_handles_deep_tree_depth_1500 tests/test_scanner_semantics.py::test_apparent_bytes_use_st_size_rules -q` | green |
| `01-03-T1` | `01-03` | `FSEM-01`, `FSEM-02`, `FSEM-05` | Symlink safety, hardlink dedup, permission-error persistence | `pytest tests/test_scanner_semantics.py::test_symlink_targets_not_descended tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes tests/test_scanner_semantics.py::test_permission_error_marks_partial_row -q` | green |
| `01-04-T1` | `01-04` | `FSEM-03`, `FSEM-04` | Mountinfo parsing, skip policy, one-filesystem pruning, cycle protection | `pytest tests/test_mount_policy.py -q` | green |
| `01-04-T1` | `01-04` | `FSEM-03` | CLI `--mountinfo` override path | `pytest tests/test_cli_collect.py::test_collect_accepts_mountinfo_override -q` | green |

## Manual-Only Coverage

None for `COLL-01..05` or `FSEM-01..05`. Phase verification also includes broader live-host sanity checks in `01-VERIFICATION.md`, but the requirement set in scope here has automated behavioral coverage.

## Audit Trail

| Date | Action | Result |
|---|---|---|
| `2026-06-13` | Read `01-01-PLAN.md` through `01-04-PLAN.md`, `01-01-SUMMARY.md` through `01-04-SUMMARY.md`, `01-REVIEW.md`, `01-VERIFICATION.md`, current `01-VALIDATION.md`, tests, and implementation | Validation draft confirmed stale; actual phase artifacts and tests differ from the old file |
| `2026-06-13` | Ran `pytest tests/test_cli_collect.py tests/test_db_schema.py tests/test_scanner_semantics.py tests/test_mount_policy.py -q` | `51 passed in 4.27s` |
| `2026-06-13` | Audited requirement-to-test mapping for `COLL-01..05` and `FSEM-01..05` | No new automated gap found |
| `2026-06-13` | Replaced stale validation map with accurate commands, statuses, and artifact references | complete |

## Files Covered By This Validation

- `tests/test_cli_collect.py`
- `tests/test_db_schema.py`
- `tests/test_scanner_semantics.py`
- `tests/test_mount_policy.py`
- `src/watchdirs/cli.py`
- `src/watchdirs/config.py`
- `src/watchdirs/models.py`
- `src/watchdirs/collect/scanner.py`
- `src/watchdirs/collect/mounts.py`
- `src/watchdirs/collect/classify.py`
- `src/watchdirs/db/connection.py`
- `src/watchdirs/db/migrations.py`

## Approval

Approved for Phase 01 Nyquist validation coverage in current repo state.
