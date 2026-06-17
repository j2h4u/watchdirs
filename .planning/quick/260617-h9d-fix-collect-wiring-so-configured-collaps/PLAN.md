---
quick_id: 260617-h9d
slug: fix-collect-wiring-so-configured-collaps
status: planned
created: 2026-06-17T07:25:39Z
---

# Fix Collect Collapse Wiring

Fix `watchdirs collect` so configured collapse policy is passed into `scan_root`, and prevent descendant-count collapse from folding structural ancestors like `/` when the production sample config is enabled.

Verification:

- RED: `uv run pytest tests/test_cli_collect.py::test_collect_applies_configured_collapse_policy -q` failed before wiring fix.
- GREEN: targeted collapse/collect/report tests pass.
- GREEN: full suite passes.
- Production-scale measurement compares `/tmp/watchdirs-prod-root.sqlite3` before and `/tmp/watchdirs-prod-root-collapsed.sqlite3` after.
