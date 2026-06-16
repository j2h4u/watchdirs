---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 03.2-01-PLAN.md
last_updated: "2026-06-16T19:24:15.057Z"
last_activity: 2026-06-16 -- Phase 03.2 execution started
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 21
  completed_plans: 18
  percent: 86
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12)

**Core value:** When disk usage changes unexpectedly, an agent can identify the largest growing directory trees and the evidence gaps behind `df`/`du` disagreements quickly and reproducibly.
**Current focus:** Phase 03.2 — scan-time-folder-collapse

## Current Position

Phase: 03.2 (scan-time-folder-collapse) — EXECUTING
Plan: 2 of 4
Status: Ready to execute
Last activity: 2026-06-16 -- Phase 03.2 execution started

Progress: [█████████░] 86%

## Performance Metrics

**Velocity:**

- Total plans completed: 17
- Average duration: 6.5 min
- Total execution time: 0.9 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | 20 min | 5 min |
| 02 | 4 | 32 min | 8 min |
| 03 | 4 | - | - |
| 03.1 | 5 | - | - |

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

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

### Roadmap Evolution

- Phase 03.1 inserted after Phase 3: Storage Efficiency (URGENT)

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-06-16T19:24:15.042Z
Stopped at: Completed 03.2-01-PLAN.md
Resume file: .planning/phases/03.2-scan-time-folder-collapse/03.2-CONTEXT.md
