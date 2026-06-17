---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: completed
stopped_at: Completed 04-scheduled-retention-operations-04-PLAN.md
last_updated: "2026-06-17T10:39:00.000Z"
last_activity: 2026-06-17 - Completed quick task 260617-lo2: Add practical default watchdirs CLI behavior for common read-only use
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 25
  completed_plans: 25
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12)

**Core value:** When disk usage changes unexpectedly, an agent can identify the largest growing directory trees and the evidence gaps behind `df`/`du` disagreements quickly and reproducibly.
**Current focus:** Phase 04 — scheduled-retention-operations

## Current Position

Phase: 04 — COMPLETE
Plan: 4 of 4
Status: Phase 04 complete
Last activity: 2026-06-17 - Completed quick task 260617-lo2: Add practical default watchdirs CLI behavior for common read-only use

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 23
- Average duration: 6.5 min
- Total execution time: 0.9 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | 20 min | 5 min |
| 02 | 4 | 32 min | 8 min |
| 03 | 4 | - | - |
| 03.1 | 5 | - | - |
| 03.2 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: 01-04 (7 min), 02-01 (6 min), 02-02 (13 min), 02-03 (6 min), 02-04 (7 min)
- Trend: Stable within the expanded Phase 2 reporting scope

**This Phase:**

| Plan | Duration | Scope | Notes |
|------|----------|-------|-------|
| 02-01 | 6min | 2 tasks | 6 files |
| 02-02 | 13min | 2 tasks | 7 files |
| Phase 02 P03 | 6min | 2 tasks | 10 files |
| Phase 02 P04 | 7min | 3 tasks | 9 files |
| Phase 03 P01 | 18min | 2 tasks | 8 files |
| Phase 03 P02 | 7min | 2 tasks | 7 files |
| Phase 03 P03 | 6min | 2 tasks | 7 files |
| Phase 03 P04 | 14 | 3 tasks | 7 files |
| Phase 03.1 P01 | 3 | 2 tasks | 4 files |
| Phase 03.1 P02 | 9 | 4 tasks | 10 files |
| Phase 03.1 P03 | 18 | 3 tasks | 10 files |
| Phase 03.1 P04 | 1min | 4 tasks | 3 files |
| Phase 03.1 P05 | 20min | 2 tasks | 2 files |
| Phase 03.2 P01 | 7min | 2 tasks | 8 files |
| Phase 03.2 P02 | 6 | 2 tasks | 2 files |
| Phase 03.2 P03 | 5min | 2 tasks | 4 files |
| Phase 03.2 P04 | 8min | 2 tasks | 3 files |
| Phase 04 P01 | 7min | 1 tasks | 3 files |
| Phase 04 P02 | 3min | 1 tasks | 3 files |
| Phase 04 P03 | 2min | 1 tasks | 3 files |
| Phase 04-scheduled-retention-operations P04 | 5min | 2 tasks | 8 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- The MVP validates the SQLite plus directory-aggregate model before any file-level persistence or observability expansion.
- Roadmap order follows the incident workflow: collect trustworthy snapshots, diff growth, explain evidence gaps, then automate ongoing collection.
- [Phase 01]: Collect requires an explicit TOML config file and keeps host roots out of implementation constants.
- [Phase 01]: The repo-local launcher bootstraps src directly so Phase 1 does not depend on an installed console script.
- [Phase 01]: Config-loading failures share a single JSON envelope keyed by config_error for agent-friendly handling.
- [Phase 01]: Directory identity columns are stored as SQLite BLOB values so raw filesystem bytes remain lossless.
- [Phase 01]: Collect creates the snapshot row before scanning and finalizes it after inserts or signal interruption so failures remain durable.
- [Phase 01]: CLI, scanner, and SQLite persistence stay split across dedicated modules so later filesystem-semantics work can extend the scanner without rewriting storage.
- [Phase 01]: Scanner traversal now operates on raw filesystem bytes internally and only decodes at display boundaries.
- [Phase 01]: Configured excludes are passed through ScannerOptions with skip evidence enabled, while aggregate totals omit excluded subtree contents.
- [Phase 01]: Exact hardlink dedup stays on by default with a 500000 inode-key cap; exceeding the cap stops the scan with a durable resource error instead of falling back silently.
- [Phase 01]: Production collection now parses /proc/self/mountinfo directly and never shells out to findmnt.
- [Phase 01]: Tmpfs, pseudo filesystems, overlay views, and namespace mounts are skipped by default unless config explicitly includes their filesystem types.
- [Phase 01]: Skipped child mounts and one-filesystem boundaries emit zero-byte directory rows with error context instead of silently disappearing.
- [Phase 02]: Product scope is the narrow incident job: help an agent answer where free disk space went since the previous useful snapshot.
- [Phase 02]: Reports should be compact and agent-facing, with stable JSON plus terse labeled text rather than broad human dashboard output.
- [Phase 02]: Default diff behavior should surface a ranked growth frontier, not every changed descendant row.
- [Phase 02]: Planning must resolve minimal reliable filesystem/storage-domain grouping because Phase 1 does not persist a first-class mount/device table.
- [Phase 02]: Persist storage-domain identity from major_minor, root, filesystem_type, and mount_source while keeping mount_id only as snapshot-local debug/display context.
- [Phase 02]: Keep the snapshot row durable, but make directory rows, snapshot_mount rows, and successful finalization commit as one per-root transaction.
- [Phase 02]: Preserve Phase 1 monkeypatched helper seams by tolerating persistence helpers that do not accept the new commit keyword.
- [Phase 02]: Top reporting selects the latest complete or partial snapshot per root path instead of one global latest snapshot.
- [Phase 02]: Mount and storage-domain grouping use persisted snapshot_mounts with longest-prefix matching rather than live mount inference.
- [Phase 02]: Raw path identity stays as BLOB bytes through query and model layers; decoding happens only in render helpers.
- [Phase 02]: Diff pairing uses each selected current snapshot's parsed UTC finished_at as the --since cutoff basis instead of wall-clock now.
- [Phase 02]: Growth frontier pruning runs in two passes so near-equal descendants can evict ancestors before surviving ancestors suppress lower-signal children.
- [Phase 02]: Diff rows keep raw BLOB path identity through query and pruning layers; render-time grouping reuses the existing persisted mount and top-level subtree helpers.
- [Phase 02]: Report classification counts use all raw diff rows, but report delta totals and group summaries use the displayed non-overlapping frontier slice to avoid recursive parent-child double counting.
- [Phase 02]: Explain-path normalizes user input without resolving symlinks, converts the canonical path with os.fsencode(), and requires one exact indexed target under one selected root.
- [Phase 02]: Explain-path residual math subtracts only shown immediate-child recursive deltas; grandchildren shown by depth are context, not additional subtraction.
- [Phase 03]: Deleted-open evidence is a live process/fd diagnostic only and is never persisted as directory_sizes rows (D-10).
- [Phase 03]: deleted-open-files prefers fixed-argv lsof -nP +L1 -F0 via an injectable runner and falls back to a bounded procfs scan via an injectable proc_root; both seams default to the live host only in the CLI.
- [Phase 03]: deleted-open action hints are cautious non-command guidance and verification commands are read-only (lsof +L1 -nP, readlink /proc/<pid>/fd/<fd>).
- [Phase 03]: report emits bounded diagnostic_hints plus a top-N pressure_summary, computing a cheap df/index reconciliation with statvfs scoped to indexed storage-domains only and never auto-running lsof or Docker.
- [Phase 03]: report-time deleted-open suspicion requires full filesystem coverage plus complete snapshot evidence (or an independent probe); partial scope, partial snapshots, and stat failures downgrade to coverage facts.
- [Phase ?]: [Phase 03.1]: Churn/cardinality measured on the existing blob schema before the rewrite (D-08 method C); dedup_ratio (total_rows/distinct_paths) is the ROI driver feeding the D-09 byte budget.
- [Phase ?]: Path dictionary: paths(id, path UNIQUE) + int path_id/parent_id FKs in directory_sizes (SCHEMA_VERSION 3)
- [Phase ?]: _resolve_path_id uses SELECT-on-miss then INSERT (no OR IGNORE/RETURNING) — D-04 empty-cursor regression structurally impossible
- [Phase ?]: Virgin-connection PRAGMAs: page_size=8192, auto_vacuum=FULL, application_id=0x57645273 before first table
- [Phase ?]: [Phase 03.1]: D-09 byte-budget gate PASSED on real host data across a churn sweep 0-40% (reduction 3.16x-4.83x; per-snapshot 29,805-40,900 B all under the 49,152 B / ~117 B-per-dir budget for the 421-dir reference tree); D-07 DuckDB escalation NOT triggered.
- [Phase ?]: [Phase 03.1]: With measured back-to-back churn=0 (D-09's gameable best case), the gate was closed on a churn SWEEP rather than a single rate; the absolute budget is the /opt reference tree and reads normalized (~117 B/dir/snapshot), pinning the exact prod operating point on a future time-spaced collect series + prod-root scan.
- [Phase ?]: 03.1-05: collect observability logs to stderr only (StreamHandler bound to sys.stderr); stdout stays pure JSON
- [Phase ?]: 03.1-05: ETA from time.monotonic() rate via compute_eta(elapsed=...) for deterministic tests; A4 seed from previous COMPLETE snapshot row_count
- [Phase 03.2]: Persist top_child_disk_bytes alongside top_child_id to satisfy the locked D-08 breadcrumb contract.
- [Phase 03.2]: Migrate only schema version 3 forward to 4; schema versions 1 and 2 fail fast as unsupported pre-dictionary inputs.
- [Phase 03.2]: Verify directory_sizes collapse column shape before bumping PRAGMA user_version to 4.
- [Phase 03.2]: Collapse stays as a row-emission policy layered on the existing post-order aggregate walk instead of rewriting aggregate math. — Preserves existing recursive byte and hardlink semantics while changing only persisted row cardinality.
- [Phase 03.2]: collapse.never protection uses exact, descendant, and ancestor-of-never path-component matching over raw filesystem bytes. — Prevents /data-style allowlists from leaking to sibling names and blocks ancestor collapse for protected descendants.
- [Phase 03.2]: Collapsed boundary rows replace descendant error text with a bounded collapsed_subtree_evidence summary while exact descendant paths remain in ScanResult.errors. — Keeps collapsed rows bounded and machine-stable without discarding detailed descendant evidence.
- [Phase 03.2]: Diff metadata uses the current row's collapse fields whenever the current row exists, and falls back to baseline metadata only for deleted rows.
- [Phase 03.2]: Explain-path resolves deep targets inside folded subtrees by directly locating the deepest collapsed indexed ancestor instead of requiring an exact descendant row.
- [Phase 03.2]: Rendered top_child metadata stays breadcrumb-only: path identity plus disk bytes, with no recursive expansion chain.
- [Phase 03.2]: No-collapse regression coverage should use a known-noise basename under an explicit empty CollapsePolicy so the test proves policy control instead of fixture luck. — Captured in 03.2-04 summary.
- [Phase 03.2]: Collapsed-vs-uncollapsed storage proof must compare two schema-version-4 product databases rather than reusing the old blob-schema benchmark. — Captured in 03.2-04 summary.
- [Phase 03.2]: Synthetic benchmark replication must preserve collapsed metadata so persisted top_child and collapsed_dirs survive the proof path. — Captured in 03.2-04 summary.
- [Phase 04]: The shared writer lock path is derived as <db>.lock so manual and scheduled collect invocations share the same contention boundary. — Deriving the sibling lock path from the selected SQLite database keeps contention aligned automatically across manual and future systemd-driven mutating commands.
- [Phase 04]: Only an actual held flock maps to operation_locked; lock-path filesystem failures stay database_error to preserve existing CLI behavior. — This preserves the pre-existing collect error contract for invalid database paths while still exposing real lock conflicts as explicit evidence gaps.
- [Phase 04]: Tiered retention is computed per root_path from snapshot finished_at in UTC, keeping all statuses only inside the hourly window and promoting COMPLETE snapshots only for daily and monthly representatives.
- [Phase 04]: Prune deletes from snapshots only and relies on FK cascades for directory_sizes and snapshot_mounts before explicit orphan paths GC.
- [Phase 04]: Retention policy validation rejects non-positive or inverted windows before any delete set is computed.
- [Phase 04]: Vacuum stays a separate explicit command under the same operation lock as collect and prune.
- [Phase 04]: The maintenance advisory threshold is three times the current page_count * page_size, compared against os.statvfs() free bytes.
- [Phase 04]: Post-VACUUM output exposes wal_checkpoint(TRUNCATE) busy/log/checkpointed values and warns on busy or partial progress.
- [Phase 04-scheduled-retention-operations]: Systemd units invoke fixed absolute /usr/local/bin/watchdirs commands with /etc/watchdirs/watchdirs.toml and /var/lib/watchdirs/watchdirs.sqlite3 so timer-launched writes match the documented host install contract.
- [Phase 04-scheduled-retention-operations]: Collect, prune, and vacuum services all carry the same low-priority execution settings and oneshot service shape, while prune and vacuum run on slower explicit timer cadences.
- [Phase 04-scheduled-retention-operations]: README operations guidance is enforced by pytest so retention windows, verification commands, and the out-of-scope cleanup boundary stay synchronized with the shipped assets.

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260617-h9d | Fix collect wiring so configured collapse policy is passed to scanner; add CLI regression and measure prod-root row/DB reduction | 2026-06-17 | b39b8ac | [260617-h9d-fix-collect-wiring-so-configured-collaps](./quick/260617-h9d-fix-collect-wiring-so-configured-collaps/) |
| 260617-kjf | Refactor retention policy into explicit hourly/daily/monthly tier dataclasses without changing behavior; identify pragmatic next options with Kaizen | 2026-06-17 | 0919f5c | [260617-kjf-refactor-retention-policy-into-explicit-](./quick/260617-kjf-refactor-retention-policy-into-explicit-/) |
| 260617-kwt | Roll out watchdirs user-level observation timers and document sudo-blocked system install | 2026-06-17 | e5e1116 | [260617-kwt-roll-out-watchdirs-user-level-observatio](./quick/260617-kwt-roll-out-watchdirs-user-level-observatio/) |
| 260617-l5l | Add single watchdirs CLI control surface backed by root query socket for unprivileged reports | 2026-06-17 | 5a5eb85 | [260617-l5l-add-single-watchdirs-cli-control-surface](./quick/260617-l5l-add-single-watchdirs-cli-control-surface/) |
| 260617-lo2 | Add practical default watchdirs CLI behavior for common read-only use | 2026-06-17 | bae8cbc | [260617-lo2-add-practical-default-watchdirs-cli-beha](./quick/260617-lo2-add-practical-default-watchdirs-cli-beha/) |

### Roadmap Evolution

- Phase 03.1 inserted after Phase 3: Storage Efficiency (URGENT)

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-17T00:18:36.626Z
Stopped at: Completed 04-scheduled-retention-operations-04-PLAN.md
Resume file: None
