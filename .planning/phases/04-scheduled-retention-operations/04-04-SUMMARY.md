---
phase: 04-scheduled-retention-operations
plan: 04
subsystem: infra
tags: [systemd, operations, retention, sqlite, docs, testing]

# Dependency graph
requires:
  - phase: 04-01
    provides: shared writer lock semantics for collect and future scheduled mutating commands
  - phase: 04-02
    provides: prune CLI surface and retention defaults documented by the shipped units
  - phase: 04-03
    provides: vacuum CLI surface and maintenance result fields documented for operators
provides:
  - repo-owned collect, prune, and vacuum systemd units with fixed host paths and low-priority execution
  - README operations guidance for installation, retention policy, timer cadence, and verification commands
  - contract tests that pin unit-file contents and README operations guidance
affects: [host-installation, operator-verification, scheduled-operations]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fixed absolute ExecStart paths in systemd units keep timer-launched writes aligned with the documented CLI surface
    - README operations guidance is pinned by file-contract tests so docs drift is caught in pytest

key-files:
  created:
    - ops/systemd/watchdirs-collect.service
    - ops/systemd/watchdirs-collect.timer
    - ops/systemd/watchdirs-prune.service
    - ops/systemd/watchdirs-prune.timer
    - ops/systemd/watchdirs-vacuum.service
    - ops/systemd/watchdirs-vacuum.timer
  modified:
    - README.md
    - tests/test_systemd_units.py

key-decisions:
  - "Systemd units invoke fixed absolute /usr/local/bin/watchdirs commands with /etc/watchdirs/watchdirs.toml and /var/lib/watchdirs/watchdirs.sqlite3 so timer-launched writes match the documented host install contract."
  - "Collect, prune, and vacuum services all carry the same low-priority execution settings and oneshot service shape, while prune and vacuum run on slower explicit timer cadences."
  - "README operations guidance is enforced by pytest so retention windows, verification commands, and the out-of-scope cleanup boundary stay synchronized with the shipped assets."

patterns-established:
  - "Pattern 1: repo-owned operational assets live under ops/systemd and are validated by literal file-contract tests."
  - "Pattern 2: operator docs must name exact command/config/database paths and timer verification commands, not generic systemd advice."

requirements-completed: [OPER-01, OPER-02, OPER-06]

# Metrics
duration: 5min
completed: 2026-06-17
status: complete
---

# Phase 04 Plan 04: Scheduled Operations Assets Summary

**Repo-owned systemd collect/prune/vacuum units with exact host-path contracts, low-priority scheduling, and operator verification docs pinned by pytest**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-17T00:11:00Z
- **Completed:** 2026-06-17T00:15:44Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Added repo-owned `systemd` service/timer assets for hourly collect, daily prune, and weekly vacuum under `ops/systemd/`.
- Documented the live operations surface in `README.md`, including the concrete command, config, database, timer, and verification contracts.
- Added file-contract coverage that pins both the unit contents and the README operations guidance.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add repo-owned systemd units and unit-file contract tests** - `ae43610` (feat)
2. **Task 2: Update README with install, retention, scheduling, and verification commands** - `7a156c9` (docs)

## Files Created/Modified

- `ops/systemd/watchdirs-collect.service` - hourly oneshot collect service with fixed host paths, JSON output, verbose journal logging, and low-priority execution settings.
- `ops/systemd/watchdirs-collect.timer` - hourly persistent timer for unattended collection.
- `ops/systemd/watchdirs-prune.service` - daily oneshot retention-prune service with the Phase 4 default windows.
- `ops/systemd/watchdirs-prune.timer` - daily prune timer offset from hourly collect with randomized delay for collision reduction.
- `ops/systemd/watchdirs-vacuum.service` - weekly oneshot SQLite maintenance service for explicit vacuum runs.
- `ops/systemd/watchdirs-vacuum.timer` - weekly persistent off-peak maintenance timer.
- `tests/test_systemd_units.py` - file-contract tests for unit presence, oneshot shape, absolute ExecStart paths, low-priority collect settings, timer persistence, README commands, and the no-cron/no-cleanup boundary.
- `README.md` - operations documentation for installation checks, retention policy, timer cadence, advisory systemd verification, and runtime verification commands.

## Decisions Made

- Fixed all systemd `ExecStart` commands to `/usr/local/bin/watchdirs` with concrete config and database paths so scheduled runs cannot drift from the documented host installation contract.
- Kept the Phase 4 operational surface narrow: regular collection, whole-snapshot pruning, and separate vacuum maintenance only; no cleanup orchestration or before/after cleanup snapshots.
- Treated README operations text as a tested contract, not a loose guide, so future command or cadence drift will fail in CI.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - the repo now ships the unit assets and operator docs; live host installation and timer enablement remain a normal deployment step.

## Known Stubs

None.

## Next Phase Readiness

- Phase 04 now has the repo-owned scheduled-operations assets needed for host rollout on `senbonzakura`.
- Operators have exact verification commands for timer state, journal visibility, report output, prune execution, and vacuum execution.
- No blockers found for the next phase.

## Self-Check: PASSED

- Files verified on disk: `.planning/phases/04-scheduled-retention-operations/04-04-SUMMARY.md`, `ops/systemd/watchdirs-collect.service`, `ops/systemd/watchdirs-prune.service`, `ops/systemd/watchdirs-vacuum.service`, `tests/test_systemd_units.py`
- Commits verified in git log: `ae43610` (Task 1), `7a156c9` (Task 2)
