---
phase: 01-trusted-snapshot-collection
plan: 01
subsystem: cli
tags: [python, argparse, tomllib, xdg, pytest]
requires: []
provides:
  - repo-local `./watchdirs collect` command surface without pip installation
  - module entrypoint `PYTHONPATH=src python3 -m watchdirs collect`
  - TOML config loading with XDG state/cache defaults and JSON config errors
affects: [phase-01-02, phase-01-03, phase-01-04, collect]
tech-stack:
  added: [python-stdlib, setuptools-metadata, pytest]
  patterns: [repo-local launcher bootstrap, dataclass config boundary, JSON-first CLI errors]
key-files:
  created:
    - pyproject.toml
    - watchdirs
    - examples/senbonzakura.watchdirs.toml
    - src/watchdirs/__init__.py
    - src/watchdirs/__main__.py
    - src/watchdirs/cli.py
    - src/watchdirs/config.py
    - tests/conftest.py
    - tests/test_cli_collect.py
  modified: []
key-decisions:
  - "Collect requires an explicit TOML config file and keeps host roots out of implementation constants."
  - "The repo-local launcher bootstraps `src/` directly so Phase 1 does not depend on an installed console script."
  - "Config-loading failures share a single JSON envelope keyed by `config_error` for agent-friendly handling."
patterns-established:
  - "Repo-local executable pattern: bootstrap `src/` in a small launcher and delegate all behavior to `python -m watchdirs`."
  - "Config boundary pattern: resolve XDG paths and validate TOML roots in `config.py`, while `cli.py` only parses and formats results."
requirements-completed: [COLL-01]
duration: 4min
completed: 2026-06-12
status: complete
---

# Phase 1 Plan 01: No-install collect command surface and explicit config loading Summary

**Repo-local collect entrypoints now load explicit TOML root policy and return machine-readable config errors without requiring pip installation.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-13T02:27:40+05:00
- **Completed:** 2026-06-12T21:31:03Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments

- Added the RED contract tests for both accepted command surfaces, XDG state defaults, sample config policy, and JSON config failures.
- Implemented the `watchdirs` launcher, `python -m watchdirs` entrypoint, argparse collect surface, and dataclass-based TOML config loader.
- Shipped the `senbonzakura` sample config with `/` as explicit operator data and tmpfs-style paths excluded from defaults.

## Verification

- `pytest tests/test_cli_collect.py -q` -> `12 passed`
- `./watchdirs collect --help` -> exits `0` and shows `--config`, `--db`, `--json`, `--notes`, `--mountinfo`
- `PYTHONPATH=src python3 -m watchdirs collect --help` -> exits `0` and shows the same flag surface

## Commits

- `8fec310` — `test(01-01): add failing collect command and config contracts`
- `a5242aa` — `feat(01-01): implement collect CLI and explicit config loading`

## Decisions Made

- `collect` stays as a config-loading scaffold in 01-01; SQLite writes and traversal remain owned by 01-02 through 01-04.
- XDG state resolves to `${XDG_STATE_HOME}/watchdirs/watchdirs.sqlite3` or `~/.local/state/watchdirs/watchdirs.sqlite3`, while cache stays separate under `${XDG_CACHE_HOME:-~/.cache}/watchdirs`.
- `--mountinfo` is accepted at the CLI boundary now, but no mount-policy behavior is implied before 01-04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Added overlapping-root validation and TDD coverage**
- **Found during:** Task 1 threat review for T-01-01
- **Issue:** The threat register required rejecting overlapping configured roots, but the original RED test list did not assert that boundary explicitly.
- **Fix:** Added a failing overlapping-root test and implemented resolved-path overlap rejection in `config.py`.
- **Files modified:** `tests/test_cli_collect.py`, `src/watchdirs/config.py`
- **Verification:** `pytest tests/test_cli_collect.py -q`
- **Commits:** `8fec310`, `a5242aa`

**Total deviations:** 1 auto-fixed (`Rule 2: 1`)
**Impact:** Tightened the config trust boundary without expanding the plan scope.

## Authentication Gates

None.

## Security Transfers

- **T-01-04 transferred to Phase 4:** before any root-run systemd timer consumes TOML roots, the service-install work must verify config file ownership and mode for the service user. Phase 1 remains user-run and does not install privileged timers.

## Known Stubs

None. The collect command intentionally stops at validated config loading in this plan; traversal and persistence are deferred to later Phase 1 plans by design.

## Threat Flags

None.

## Self-Check: PASSED

- Verified `.planning/phases/01-trusted-snapshot-collection/01-01-SUMMARY.md` exists on disk.
- Verified commit `8fec310` exists in git history.
- Verified commit `a5242aa` exists in git history.
