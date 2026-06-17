---
phase: 04-scheduled-retention-operations
verified: 2026-06-17T00:44:13Z
status: passed
score: 20/20 repo must-haves verified
behavior_unverified: 0
overrides_applied: 0
manual_follow_up:
  - test: "Install or copy the watchdirs command to /usr/local/bin/watchdirs on senbonzakura, install the units from ops/systemd, enable the timers, then run systemctl list-timers 'watchdirs-*' and journalctl -u watchdirs-collect.service -u watchdirs-prune.service -u watchdirs-vacuum.service."
    expected: "The three timers appear, the services launch on their expected cadence, and failures surface visibly in the journal instead of silently blocking."
    why_human: "This verifier can inspect the repo and run tests, but it cannot mutate or inspect the target host's live systemd state."
  - test: "On a systemd host where /usr/local/bin/watchdirs exists, run systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer."
    expected: "The unit files verify cleanly once the documented command-path precondition is satisfied."
    why_human: "The current environment does not provide /usr/local/bin/watchdirs, so local verification reports the documented install precondition rather than target-host readiness."
---

# Phase 4: Scheduled Retention Operations Verification Report

**Phase Goal:** Operators can rely on watchdirs to collect and retain evidence unattended
**Verified:** 2026-06-17T00:44:13Z
**Status:** passed
**Re-verification:** No - initial verification

**MVP Mode Note:** `ROADMAP.md` marks Phase 4 as `mode: mvp`, but the roadmap goal is not stored in strict user-story syntax (`user-story.validate` returned `valid: false`). This report therefore verifies the roadmap success criteria plus the plan must-haves directly.

## User Flow Coverage

| Step | Expected | Evidence | Status |
| --- | --- | --- | --- |
| Install operational surface | Repo ships concrete collect/prune/vacuum units and operator docs name the exact host paths and verification commands. | `ops/systemd/*.service`, `ops/systemd/*.timer`, `README.md:375-448`, `tests/test_systemd_units.py:56-140` | ✓ VERIFIED |
| Prevent overlap corruption | A second writer fails fast on the shared lock before it can create another snapshot. | `src/watchdirs/ops_lock.py:34-48`, `src/watchdirs/cli.py:339-365`, `tests/test_ops_locking.py:25-67` | ✓ VERIFIED |
| Retain useful history | Prune keeps hourly/daily/monthly whole snapshots and removes orphaned path-dictionary rows. | `src/watchdirs/db/retention.py:53-148`, `src/watchdirs/db/schema.sql:20-48`, `tests/test_ops_retention.py:326-408` | ✓ VERIFIED |
| Maintain DB health | Vacuum is separate from prune, runs under the same lock, and reports counters plus warnings. | `src/watchdirs/db/retention.py:151-201`, `src/watchdirs/cli.py:614-669`, `tests/test_ops_vacuum.py:48-198` | ✓ VERIFIED |
| Rely on live host scheduling | The repo ships installable units, documented host paths, verification commands, and automated file-contract coverage; live enablement remains a documented post-install operation. | `ops/systemd/*.service`, `ops/systemd/*.timer`, README commands (`README.md:404-443`), automated unit-contract tests, and manual-only classification in `04-VALIDATION.md:79-84`. | ✓ VERIFIED_FOR_REPO_SCOPE |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Host can schedule collection with provided systemd service and timer units, and overlapping runs do not create duplicate or corrupted snapshots. | ✓ VERIFIED_FOR_REPO_SCOPE | Overlap protection is proven by `tests/test_ops_locking.py::test_collect_lock_conflict_fails_fast_without_snapshot_write`; shipped units exist at `ops/systemd/*`; live host enablement is explicitly manual-only/advisory per `04-VALIDATION.md:79-84` and is preserved as a post-install follow-up below. |
| 2 | Scheduled collection runs with low CPU and I/O priority and retains history by whole-snapshot TTL instead of deleting individual path rows. | ✓ VERIFIED | `watchdirs-collect.service` sets `Nice=19`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=7` (`ops/systemd/watchdirs-collect.service:5-13`); prune deletes from `snapshots` only and relies on FK cascades plus orphan `paths` GC (`src/watchdirs/db/retention.py:125-148`, `src/watchdirs/db/schema.sql:20-48`). |
| 3 | Maintenance can run a slower post-prune vacuum path to keep the SQLite database healthy over time. | ✓ VERIFIED | `watchdirs vacuum` is a separate subcommand (`src/watchdirs/cli.py:226-229`, `614-675`) backed by `vacuum_database()` metrics and checkpoint reporting (`src/watchdirs/db/retention.py:151-201`). |
| 4 | Installation and operational docs explain the database path, timer behavior, retention policy, and expected verification commands for the live host. | ✓ VERIFIED | README documents retention, host paths, timer cadence, advisory `systemd-analyze verify`, and operator commands (`README.md:375-448`), with contract coverage in `tests/test_systemd_units.py:107-140`. |
| 5 | A second mutating watchdirs command fails immediately when another writer holds the operation lock. | ✓ VERIFIED | `acquire_operation_lock()` uses non-blocking `flock(... LOCK_EX | LOCK_NB)` (`src/watchdirs/ops_lock.py:39-48`); lock-conflict test passes (`tests/test_ops_locking.py:25-67`). |
| 6 | Lock-conflict failures are visible through the CLI JSON error envelope and stderr/journal text. | ✓ VERIFIED | `run_collect`, `run_prune`, and `run_vacuum` map `OperationLocked` through `_emit_runtime_error(... code="operation_locked")` (`src/watchdirs/cli.py:343-353`, `562-572`, `627-637`); tests assert JSON payload fields (`tests/test_ops_locking.py:60-67`, `tests/test_ops_retention.py:376-389`, `tests/test_ops_vacuum.py:131-144`). |
| 7 | Manual collect invocations and later scheduled collect invocations share the same lock path derived from the SQLite database path. | ✓ VERIFIED | Lock path derives from the DB path via `operation_lock_path_for_db()` (`src/watchdirs/ops_lock.py:34-36`), and the collect/prune/vacuum units all target `/var/lib/watchdirs/watchdirs.sqlite3` (`ops/systemd/watchdirs-collect.service:7`, `watchdirs-prune.service:7`, `watchdirs-vacuum.service:7`). |
| 8 | Operator can run `watchdirs prune --db PATH --json` and delete expired history only at whole-snapshot boundaries. | ✓ VERIFIED | `run_prune()` calls `prune_snapshots()` under the shared lock (`src/watchdirs/cli.py:533-611`); `prune_snapshots()` deletes from `snapshots` and not child tables (`src/watchdirs/db/retention.py:125-148`); tests assert no direct deletes from `directory_sizes` or `snapshot_mounts` (`tests/test_ops_retention.py:348-364`). |
| 9 | Retention keeps all recent hourly snapshots of every status, daily COMPLETE representatives for the middle window, and monthly COMPLETE representatives for older history. | ✓ VERIFIED | `select_retained_snapshot_ids()` implements hourly/all-status, daily COMPLETE, and monthly COMPLETE buckets (`src/watchdirs/db/retention.py:53-102`); fixture test proves exact retained IDs (`tests/test_ops_retention.py:293-324`). |
| 10 | PARTIAL and FAILED snapshots that age beyond the hourly window are deleted rather than promoted to daily or monthly representatives. | ✓ VERIFIED | Non-COMPLETE rows older than the hourly window are skipped during daily/monthly representative selection (`src/watchdirs/db/retention.py:82-98`); tests assert failed/partial snapshots are not retained beyond the hourly window (`tests/test_ops_retention.py:320-324`, `326-357`, `365-390`). |
| 11 | Pruning removes orphan dictionary paths left behind by snapshot cascades. | ✓ VERIFIED | `_delete_orphan_paths()` deletes unreferenced `paths` rows after snapshot deletion (`src/watchdirs/db/retention.py:204-225`); retention test verifies deleted path count and missing orphan entries (`tests/test_ops_retention.py:343-364`). |
| 12 | Prune uses the same fail-fast writer lock as collect. | ✓ VERIFIED | `run_prune()` derives the same lock path and acquires it before opening SQLite (`src/watchdirs/cli.py:559-588`); lock-conflict CLI test passes (`tests/test_ops_retention.py:370-390`). |
| 13 | Operator can run `watchdirs vacuum --db PATH --json` as a slower explicit maintenance operation. | ✓ VERIFIED | `build_parser()` registers `vacuum` separately (`src/watchdirs/cli.py:226-229`); `run_vacuum()` is an explicit command path (`src/watchdirs/cli.py:614-675`); `./watchdirs --help` lists `vacuum`. |
| 14 | Vacuum maintenance uses the same fail-fast operation lock as collect and prune. | ✓ VERIFIED | `run_vacuum()` derives the DB lock path and acquires it before opening SQLite (`src/watchdirs/cli.py:624-653`); lock-conflict test passes (`tests/test_ops_vacuum.py:131-144`). |
| 15 | Vacuum result output reports observable before/after SQLite page and byte counts. | ✓ VERIFIED | `VacuumResult` and `_vacuum_payload()` expose byte/page/freelist counters (`src/watchdirs/db/retention.py:36-50`, `151-201`; `src/watchdirs/cli.py:1395-1413`); tests assert these fields exist and shrink appropriately (`tests/test_ops_vacuum.py:48-80`, `83-112`). |
| 16 | Vacuum result output reports pre-VACUUM free-space risk and WAL checkpoint busy/partial status. | ✓ VERIFIED | `vacuum_database()` computes free-space advisory and WAL checkpoint warning fields (`src/watchdirs/db/retention.py:157-180`); warning-path test passes (`tests/test_ops_vacuum.py:176-198`). |
| 17 | Repo provides systemd service and timer units for collect, prune, and vacuum. | ✓ VERIFIED | Six unit files exist under `ops/systemd/` and are pinned by `tests/test_systemd_units.py:56-65`; the file-contract suite passed. |
| 18 | Scheduled collect service runs at low CPU and I/O priority and emits logs to the journal. | ✓ VERIFIED | Low-priority settings are present in `ops/systemd/watchdirs-collect.service:5-13`; collect logging is stderr-only (`src/watchdirs/cli.py:72-121`), which systemd captures in the journal. |
| 19 | Operator docs state the service command path, config path, database path, timer cadence, retention policy, and verification commands. | ✓ VERIFIED | README covers `/usr/local/bin/watchdirs`, `/etc/watchdirs/watchdirs.toml`, `/var/lib/watchdirs/watchdirs.sqlite3`, timer cadence, retention defaults, and verification commands (`README.md:404-443`). |
| 20 | Docs keep Phase 4 scoped to regular evidence collection, pruning, and maintenance only. | ✓ VERIFIED | README explicitly limits the operations surface to collection, pruning, and explicit maintenance and says cleanup orchestration remains out of scope (`README.md:446-448`); tests assert cleanup hooks are absent (`tests/test_systemd_units.py:88-104`, `135-140`). |

**Score:** 20/20 repo-scope truths verified. Live target-host enablement remains a documented post-install follow-up, not a repository phase blocker.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `src/watchdirs/ops_lock.py` | Shared non-blocking writer lock for mutating operations | ✓ VERIFIED | Substantive lock helper with deterministic lock-path derivation and `flock(... LOCK_NB)` acquisition (`1-48`); imported by `src/watchdirs/cli.py`. |
| `src/watchdirs/cli.py` | `collect`, `prune`, and `vacuum` lock/maintenance integration | ✓ VERIFIED | Registers subcommands (`192-229`), acquires the shared lock for each mutating path (`339-365`, `559-588`, `624-653`), and emits structured JSON payloads (`1377-1413`). |
| `src/watchdirs/db/retention.py` | Tiered whole-snapshot prune, orphan path GC, and vacuum maintenance | ✓ VERIFIED | Implements retention selection (`53-102`), snapshot-only prune (`105-148`), orphan path cleanup (`204-225`), and explicit vacuum metrics/warnings (`151-201`). |
| `tests/test_ops_locking.py` | Lock-conflict helper/CLI coverage | ✓ VERIFIED | Covers fail-fast collect conflict, lock release, symlink canonicalization, and post-release success (`25-153`). |
| `tests/test_ops_retention.py` | Retention-policy, orphan-path, stale-unfinished, and idempotency coverage | ✓ VERIFIED | Substantive fixture-driven tests cover representative selection, snapshot-only prune, stale unfinished pruning, JSON output, conflict handling, and second-run noop (`293-409`). |
| `tests/test_ops_vacuum.py` | Vacuum behavior, warnings, and prune separation coverage | ✓ VERIFIED | Covers counter reporting, CLI JSON, missing DB safety, lock conflict, prune/vacuum separation, and warning fields (`48-198`). |
| `tests/test_systemd_units.py` | Unit-file and README operations contract coverage | ✓ VERIFIED | Pins unit contents, low-priority settings, collision avoidance, lack of cron/cleanup hooks, and README commands (`56-140`). |
| `ops/systemd/watchdirs-collect.service` | Low-priority oneshot collect service | ✓ VERIFIED | Absolute collect command, config/db paths, and low-priority settings are present (`5-13`). |
| `ops/systemd/watchdirs-collect.timer` | Persistent hourly collect timer | ✓ VERIFIED | `OnCalendar=hourly`, `Persistent=true`, and service binding are present (`4-10`). |
| `ops/systemd/watchdirs-prune.service` | Daily prune service with retention defaults | ✓ VERIFIED | Absolute prune command with `--hourly-days 14 --daily-days 90` is present (`5-13`). |
| `ops/systemd/watchdirs-prune.timer` | Daily prune timer offset from collect | ✓ VERIFIED | `00:17:00`, `RandomizedDelaySec=300`, and `Persistent=true` are present (`4-11`). |
| `ops/systemd/watchdirs-vacuum.service` | Weekly explicit vacuum service | ✓ VERIFIED | Absolute vacuum command and low-priority settings are present (`5-13`). |
| `ops/systemd/watchdirs-vacuum.timer` | Persistent weekly vacuum timer | ✓ VERIFIED | Weekly `OnCalendar` and service binding are present (`4-10`). |
| `README.md` | Operator install/scheduling/retention guidance | ✓ VERIFIED | Retention, scheduling, host-path assumptions, advisory validation, and agent-facing commands are documented (`375-448`). |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `src/watchdirs/cli.py` | `src/watchdirs/ops_lock.py` | `run_collect` acquires the DB-derived lock before opening/writing SQLite | WIRED | `run_collect()` derives `lock_path` and acquires `acquire_operation_lock()` before `open_connection()` (`src/watchdirs/cli.py:339-367`). |
| `tests/test_ops_locking.py` | `src/watchdirs/cli.py` | subprocess collect lock-conflict assertion | WIRED | `run_repo_local(... collect --json ...)` asserts `operation_locked` and unchanged snapshot count (`tests/test_ops_locking.py:33-67`). |
| `src/watchdirs/cli.py` | `src/watchdirs/db/retention.py` | `run_prune` opens the configured DB and calls `prune_snapshots` under the shared lock | WIRED | `run_prune()` acquires the shared lock, opens existing DB read-write, initializes schema, then calls `prune_snapshots()` (`src/watchdirs/cli.py:559-588`). |
| `src/watchdirs/db/retention.py` | `src/watchdirs/db/schema.sql` | `DELETE FROM snapshots` relies on cascade cleanup | WIRED | `directory_sizes.snapshot_id` and `snapshot_mounts.snapshot_id` both reference `snapshots(id) ON DELETE CASCADE` (`src/watchdirs/db/schema.sql:20-48`). |
| `src/watchdirs/cli.py` | `src/watchdirs/db/retention.py` | `run_vacuum` opens the configured DB and calls `vacuum_database` under the shared lock | WIRED | `run_vacuum()` acquires the same lock, opens existing DB read-write, initializes schema, then calls `vacuum_database()` (`src/watchdirs/cli.py:624-653`). |
| `src/watchdirs/db/retention.py` | `src/watchdirs/db/connection.py` | vacuum command reuses centralized PRAGMA setup | WIRED | `run_vacuum()` uses `open_existing_connection()` from `connection.py` (`src/watchdirs/db/connection.py:35-45`) rather than ad hoc SQLite opening. |
| `ops/systemd/watchdirs-collect.service` | `src/watchdirs/cli.py` | ExecStart invokes `watchdirs collect` with fixed host paths | WIRED | `ExecStart=/usr/local/bin/watchdirs collect --config /etc/watchdirs/watchdirs.toml --db /var/lib/watchdirs/watchdirs.sqlite3 --json --verbose` (`ops/systemd/watchdirs-collect.service:7`). |
| `ops/systemd/watchdirs-prune.service` | `src/watchdirs/cli.py` | ExecStart invokes `watchdirs prune` with retention defaults | WIRED | `ExecStart=/usr/local/bin/watchdirs prune --db /var/lib/watchdirs/watchdirs.sqlite3 --hourly-days 14 --daily-days 90 --json` (`ops/systemd/watchdirs-prune.service:7`). |
| `ops/systemd/watchdirs-vacuum.service` | `src/watchdirs/cli.py` | ExecStart invokes `watchdirs vacuum` on a separate cadence | WIRED | `ExecStart=/usr/local/bin/watchdirs vacuum --db /var/lib/watchdirs/watchdirs.sqlite3 --json` (`ops/systemd/watchdirs-vacuum.service:7`). |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `src/watchdirs/cli.py` (`run_collect`) | `db_path`, `lock_path`, `snapshot_payloads` | CLI args/config -> `operation_lock_path_for_db()` -> `open_connection()` -> `create_snapshot()` / `insert_directory_rows()` / `finalize_snapshot()` | Yes | ✓ FLOWING |
| `src/watchdirs/cli.py` (`run_prune`) | `policy`, `result.deleted_snapshot_ids` | CLI args -> `RetentionPolicy` -> `prune_snapshots()` -> `SELECT id FROM snapshots` / `DELETE FROM snapshots` / `_delete_orphan_paths()` | Yes | ✓ FLOWING |
| `src/watchdirs/cli.py` (`run_vacuum`) | `result.db_bytes_before`, `wal_checkpoint_*` | CLI args -> `open_existing_connection()` -> `vacuum_database()` -> PRAGMAs + `VACUUM` + `wal_checkpoint(TRUNCATE)` | Yes | ✓ FLOWING |
| `ops/systemd/*.service` | fixed `ExecStart` arguments | Unit files -> `watchdirs` CLI -> mutating handlers above | Yes, subject to host install of `/usr/local/bin/watchdirs` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| CLI exposes the Phase 4 command surface | `./watchdirs --help` | Listed `collect, prune, vacuum, ...` | ✓ PASS |
| Overlapping collect fails fast without duplicate snapshot writes | `uv run pytest tests/test_ops_locking.py::test_collect_lock_conflict_fails_fast_without_snapshot_write -q -x` | `1 passed in 0.50s` | ✓ PASS |
| Tiered whole-snapshot prune keeps representatives and stays idempotent | `uv run pytest tests/test_ops_retention.py::test_prune_keeps_latest_complete_per_root_day_month_and_gcs_paths tests/test_ops_retention.py::test_prune_second_run_is_noop -q -x` | `2 passed in 0.14s` | ✓ PASS |
| Vacuum reports counters, respects the shared lock, and docs/unit contracts hold | `uv run pytest tests/test_ops_vacuum.py::test_vacuum_database_records_before_after_counters tests/test_ops_vacuum.py::test_vacuum_cli_fails_fast_when_operation_lock_is_held tests/test_systemd_units.py::test_systemd_unit_files_exist_and_use_oneshot tests/test_systemd_units.py::test_readme_documents_operations_and_verification_commands -q -x` | `4 passed in 0.39s` | ✓ PASS |
| Phase 04 targeted suite passes end-to-end | `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py -q -x` | `23 passed in 2.01s` | ✓ PASS |
| Full local suite remained green after fixes | `uv run pytest -q` | Inspected user-provided result: `252 passed` | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED (no phase-declared probes and no conventional `scripts/*/tests/probe-*.sh` for this phase)

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `OPER-01` | `04-04` | Project provides systemd service and timer units for scheduled collection. | ✓ SATISFIED | Six unit files exist under `ops/systemd/`; unit-contract tests passed; live enablement remains manual-only per `04-VALIDATION.md:79-84`. |
| `OPER-02` | `04-04` | Scheduled collection runs with low CPU and I/O priority. | ✓ SATISFIED | Collect service sets `Nice=19`, `IOSchedulingClass=best-effort`, and `IOSchedulingPriority=7` (`ops/systemd/watchdirs-collect.service:11-13`); file-contract test passed. |
| `OPER-03` | `04-01`, `04-02`, `04-03` | Collection uses a lock so overlapping runs cannot corrupt or duplicate snapshots. | ✓ SATISFIED | Shared lock helper exists (`src/watchdirs/ops_lock.py:34-48`) and is used by collect/prune/vacuum (`src/watchdirs/cli.py:339-365`, `559-588`, `624-653`); targeted lock tests passed. |
| `OPER-04` | `04-02` | Project provides retention pruning by deleting whole snapshots according to hourly/daily TTL policy. | ✓ SATISFIED | Retention selector and prune executor implement whole-snapshot tiering and orphan path GC (`src/watchdirs/db/retention.py:53-148`, `204-225`); retention tests passed. |
| `OPER-05` | `04-03` | Project provides a slower maintenance path for SQLite vacuum after pruning. | ✓ SATISFIED | `watchdirs vacuum` exists as a separate command with metrics and warnings (`src/watchdirs/cli.py:614-675`, `src/watchdirs/db/retention.py:151-201`); vacuum tests passed. |
| `OPER-06` | `04-04` | Installation and operational docs explain the database path, timer behavior, retention policy, and expected verification commands. | ✓ SATISFIED | README documents the required host paths, timers, retention defaults, and verification commands (`README.md:375-448`); README contract test passed. |

No orphaned Phase 4 requirements were found in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

No blocker or warning anti-patterns found in the Phase 04 implementation files. Debt-marker scan over the Phase 04 code/docs surface found no `TBD`, `FIXME`, `XXX`, `TODO`, `HACK`, or placeholder implementations.

### Manual Post-Install Follow-Up

### 1. Live Timer Enablement

**Test:** Install or copy the command to `/usr/local/bin/watchdirs`, install the six shipped units on `senbonzakura`, enable the timers, then run `systemctl list-timers 'watchdirs-*'`, `systemctl status watchdirs-collect.timer watchdirs-prune.timer watchdirs-vacuum.timer`, and `journalctl -u watchdirs-collect.service -u watchdirs-prune.service -u watchdirs-vacuum.service`.

**Expected:** The timers are active, services run on the documented cadence, and lock/contention or runtime failures surface visibly in the journal rather than silently waiting.

**Why manual:** Enabling host timers changes live machine state and `04-VALIDATION.md` classifies it as manual-only, outside the repository phase gate.

### 2. Target-Host Unit Verification

**Test:** On a systemd host where `/usr/local/bin/watchdirs` exists, run `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer`.

**Expected:** The units verify cleanly once the documented host-path precondition is satisfied.

**Why manual:** Running this locally produced `Command /usr/local/bin/watchdirs is not executable: No such file or directory`, which reflects the documented install precondition rather than a repo-file syntax error. `04-VALIDATION.md` classifies this as target-host advisory validation.

### Commands Inspected or Run

- Ran `./watchdirs --help` -> listed `collect`, `prune`, `vacuum`, and the pre-existing reporting/diagnostic commands.
- Ran `uv run pytest tests/test_ops_locking.py::test_collect_lock_conflict_fails_fast_without_snapshot_write -q -x` -> `1 passed in 0.50s`.
- Ran `uv run pytest tests/test_ops_retention.py::test_prune_keeps_latest_complete_per_root_day_month_and_gcs_paths tests/test_ops_retention.py::test_prune_second_run_is_noop -q -x` -> `2 passed in 0.14s`.
- Ran `uv run pytest tests/test_ops_vacuum.py::test_vacuum_database_records_before_after_counters tests/test_ops_vacuum.py::test_vacuum_cli_fails_fast_when_operation_lock_is_held tests/test_systemd_units.py::test_systemd_unit_files_exist_and_use_oneshot tests/test_systemd_units.py::test_readme_documents_operations_and_verification_commands -q -x` -> `4 passed in 0.39s`.
- Ran `uv run pytest tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py -q -x` -> `23 passed in 2.01s`.
- Inspected the supplied full-suite result `uv run pytest -q` -> `252 passed`.
- Ran `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer` in this environment -> exit `1`; the relevant Phase 04-specific output was `watchdirs-collect.service: Command /usr/local/bin/watchdirs is not executable: No such file or directory` plus the same message for prune/vacuum. This matches the README's documented requirement to verify `/usr/local/bin/watchdirs` before enabling timers.
- Ran a debt-marker scan over the Phase 04 code/docs surface -> no TODO/FIXME/XXX/HACK/placeholder markers found.

### Gaps Summary

No repository implementation gaps were found for the Phase 04 code, tests, unit files, or docs. The remaining target-host checks are documented post-install follow-ups: verifying the installed `/usr/local/bin/watchdirs` path and enabling/checking live systemd timers on `senbonzakura`.

---

_Verified: 2026-06-17T00:44:13Z_
_Verifier: the agent (gsd-verifier)_
