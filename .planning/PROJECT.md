# watchdirs

## What This Is

`watchdirs` is a local forensic CLI for explaining disk space growth on `senbonzakura`. It periodically records directory aggregate snapshots so an agent can quickly answer what directory trees grew since a prior point in time, whether the growth matches real disk pressure, and where to drill down next without broad manual `du` sweeps.

The first version is an internal operations tool, not a UI-first disk visualizer. Its primary user is an agent investigating host disk pressure with evidence.

## Core Value

When disk usage changes unexpectedly, an agent can identify the largest growing directory trees and the evidence gaps behind `df`/`du` disagreements quickly and reproducibly.

## Requirements

### Validated

- [x] Phase 01 validates directory-only recursive snapshot collection for configured roots.
- [x] Phase 01 validates SQLite snapshot persistence with metadata and recursive directory aggregate rows.
- [x] Phase 01 validates disk-byte and apparent-byte recording with `du`-compatible hardlink semantics.
- [x] Phase 01 validates default filesystem safety: no symlink traversal, virtual/transient mount filtering, overlay/namespace pruning, and durable partial-error recording.
- [x] Phase 02 validates JSON-first `top`, `diff`, `report`, `deleted`, and `explain-path` reporting for the core disk-growth incident workflow.
- [x] Phase 02 validates filesystem and storage-domain grouping from persisted snapshot-time mount metadata.
- [x] Phase 03 validates df-vs-index reconciliation and separate deleted-open-files diagnostics when indexed totals and `df` disagree (DIAG-01, DIAG-02, DIAG-03).
- [x] Phase 03 validates disk/subsystem pressure summarization for capacity decisions: upgrade, migrate data, or repurpose older disks for swap, temp files, and caches (DIAG-05).
- [x] Phase 03 validates Docker/containerd enrichment as auxiliary evidence when relevant paths grow (DIAG-04).

### Active

- [ ] Install as a low-priority systemd timer with locking and retention.
- [ ] Prune old data by snapshot TTL, not by deleting individual historical path rows.

### Out of Scope

- UI-first disk visualizer - the first user is an agent consuming CLI/JSON evidence.
- Continuous filesystem-event monitoring - periodic snapshots are enough for the target incident class.
- Permanent full file inventory - directory aggregates should prove insufficient before adding file-level persistence.
- Large database service - this should remain a local embedded operational tool.
- Graph, time-series, DuckDB, or SurrealDB storage for v1 - the core query is a relational snapshot diff.
- Scanning virtual filesystems or container overlay mount views as normal directory trees - these create misleading or unsafe traversal.

## Context

On 2026-06-12 the root filesystem appeared to jump from roughly 137G used to around 170G used. Live investigation found multiple contributors: Docker/BuildKit/containerd cache, overlayfs snapshots, a large `~/.cache/uv` caused by heavy Python dependencies, and multi-gigabyte context-gateway logs.

Manual cleanup with `docker builder prune -af`, `docker image prune -f`, and `uv cache prune` improved free space from about 20G to about 45G. That confirmed a cleanup path but exposed the deeper pain point: the system had no historical evidence for which directory trees grew between "yesterday" and "now".

The README captures the initial design decision record. The core approach is to store directory aggregates, not a permanent file inventory. When a suspicious directory is identified, agents can run targeted temporary drill-down commands inside that subtree.

## Constraints

- **Host scope**: Target `senbonzakura` first - the tool exists because of a concrete local disk-pressure incident.
- **Storage**: Use SQLite for v1 - one local file, no service, snapshot diff queries are straightforward SQL.
- **Data model**: Store recursive directory aggregate rows - this keeps persistent state small while preserving the growth frontier.
- **Filesystem safety**: Do not follow symlinks and do not silently descend into virtual, transient, or container overlay filesystems.
- **Correctness**: Track both apparent bytes and disk bytes, and make hardlink semantics explicit.
- **Operations**: Use systemd timers, `nice`/idle I/O, locking, partial-failure recording, and retention by whole snapshots.
- **Interface**: JSON output is first-class - human-readable output is useful but secondary.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use SQLite as the primary store | Snapshot diff by path is relational and does not need a database service | Validated in Phases 01-02 |
| Store directory aggregates first | Investigations need the growth frontier before individual file inventory | Validated in Phases 01-02 |
| Skip permanent file-level indexing in v1 | File inventory increases size, runtime, retention complexity, and noise | - Pending |
| Treat Docker/containerd evidence as enrichment | Filesystem snapshots find growth, Docker commands explain reclaimability and ownership | - Pending |
| Keep deleted-open files outside directory rows | `df`/`du` disagreements require process/fd diagnostics, not fake directory attribution | - Pending |
| Use systemd timers instead of cron | Host maintenance already follows systemd patterns and needs locking/priority control | - Pending |
| Persist snapshot-time mount metadata for grouping | Live mount inference would make old reports unstable and wrong on multi-disk hosts | Validated in Phase 02 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check - still the right priority?
3. Audit Out of Scope - reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-14 after Phase 03 completion*
