---
quick_id: 260617-h9d
slug: fix-collect-wiring-so-configured-collaps
status: complete
completed: 2026-06-17T07:32:00Z
---

# Summary

Implemented the collect wiring fix and a safety correction for collapse heuristics.

Changes:

- Passed `config.collapse_policy` into `ScannerOptions` in `run_collect`.
- Added a CLI regression proving configured known-noise collapse persists a collapsed boundary row.
- Removed arbitrary descendant-count collapse so enabling the sample config does not fold `/` into one row.
- Updated scanner semantics tests for the safer collapse behavior.

Verification:

- `uv run pytest tests/test_cli_collect.py::test_collect_applies_configured_collapse_policy -q` failed before the fix and passes after.
- `uv run pytest tests/test_cli_collect.py tests/test_scanner_semantics.py tests/test_reporting_equivalence.py tests/test_cli_report_commands.py::test_explain_path_descendant_inside_collapsed_subtree_uses_collapsed_ancestor -q -x` -> 67 passed.
- `uv run pytest tests/test_cli_collect.py::test_collect_applies_configured_collapse_policy tests/test_scanner_semantics.py -q -x` -> 26 passed after descendant-count safety fix.
- `uv run pytest -q` -> 253 passed.

Production-scale measurement:

- Before: `/tmp/watchdirs-prod-root.sqlite3`, 98,809 rows, about 29 MiB, page bytes 29,949,952.
- After: `/tmp/watchdirs-prod-root-collapsed.sqlite3`, 26,972 rows, about 6.6 MiB, page bytes 6,848,512.
- Collapsed boundary rows: 771; folded dirs: 71,845.
- Size reduction: about 4.37x / 77.1%; row reduction: about 3.66x / 72.7%.

Caveat: both production-scale runs are partial due host permission/skipped-filesystem evidence, but they are comparable root scans for footprint measurement.
