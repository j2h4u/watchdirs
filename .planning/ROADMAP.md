# Roadmap: watchdirs

## Overview

`watchdirs` turns disk-pressure incidents from reactive `df`/`du` spelunking into repeatable evidence. The MVP starts by making snapshot collection trustworthy, then uses that history to surface growth deltas by path and filesystem, then explains the main evidence gaps behind `df`/`du` disagreements and disk capacity decisions, and finally operationalizes the tool with unattended scheduling, pruning, and verification docs.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Trusted Snapshot Collection** - Capture accurate directory-only snapshots that reflect real disk-pressure semantics. (completed 2026-06-12)
- [x] **Phase 2: Growth Frontier Reporting** - Turn snapshots into JSON-first diff and drill-down workflows for fast triage. (completed 2026-06-13)
- [x] **Phase 3: Pressure Gap Diagnostics** - Reconcile indexed growth with `df` mismatches and Docker/containerd evidence. (completed 2026-06-14)
- [ ] **Phase 4: Scheduled Retention Operations** - Run the tool unattended with systemd, locking, pruning, and operator guidance.

## Phase Details

### Phase 1: Trusted Snapshot Collection

**Goal**: Agents can create trustworthy directory snapshot evidence for configured roots
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: COLL-01, COLL-02, COLL-03, COLL-04, COLL-05, FSEM-01, FSEM-02, FSEM-03, FSEM-04, FSEM-05
**Success Criteria** (what must be TRUE):

  1. Agent can run repo-local `./watchdirs collect` or `PYTHONPATH=src python3 -m watchdirs collect` for configured roots and get a timestamped snapshot with collection status, timing, root path, notes, and fatal error metadata.
  2. Snapshot data exposes recursive directory aggregates with path relationships, counts, apparent bytes, disk bytes, and per-path errors for later diffing.
  3. Snapshot totals follow `du`-compatible physical-byte semantics without symlink traversal or hardlink double-counting within a snapshot.
  4. Collection skips virtual, transient, overlay, and namespace mount views by default so stored evidence reflects meaningful host usage.

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md - No-install collect command surface and explicit config loading

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md - SQLite schema, migrations, and snapshot lifecycle persistence

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md - Native scanner aggregate, byte, hardlink, symlink, and error semantics

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-04-PLAN.md - Mountinfo parsing, skip policy, scanner pruning, and phase verification

### Phase 2: Growth Frontier Reporting

**Goal**: Agents can identify what grew and where to drill down between snapshots
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: REPT-01, REPT-02, REPT-03, REPT-04, REPT-05, REPT-06, REPT-07
**Success Criteria** (what must be TRUE):

  1. Agent can run `watchdirs diff --since 24h --limit N --json` and receive paths sorted by disk-byte growth.
  2. Agent can run `watchdirs report --since 24h --json` and get a structured summary that distinguishes created, deleted, unchanged, grown, and shrunk paths.
  3. Agent can run `watchdirs top --snapshot latest --limit N --json` to inspect the largest current directory trees.
  4. Agent can run `watchdirs explain-path PATH --since 24h --json` and `watchdirs deleted --since 24h --json` to inspect one suspicious subtree and paths that disappeared since the earlier snapshot.
  5. Agent can group diff/report/top evidence by filesystem or mounted storage domain so hosts with multiple SSDs show which filesystem owns the current pressure and growth.

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 02-01-PLAN.md - Persist snapshot-time mount metadata for storage-domain grouping

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md - Add top latest current-usage report with persisted grouping

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md - Add same-root diff pairing, classifications, and growth frontier

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md - Add report, deleted, explain-path workflows and final verification

### Phase 3: Pressure Gap Diagnostics

**Goal**: Agents can reconcile indexed growth with real filesystem pressure and supporting evidence
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: DIAG-01, DIAG-02, DIAG-03, DIAG-04, DIAG-05
**Success Criteria** (what must be TRUE):

  1. Agent can run `watchdirs df-vs-index --json` and compare filesystem usage against indexed directory totals.
  2. Agent can inspect a deleted-open-files diagnostic and see which deleted files are still consuming space through open descriptors.
  3. When indexed totals diverge materially from `df`, watchdirs reports flag deleted-open-file suspicion instead of silently presenting incomplete conclusions.
  4. For Docker/containerd-related growth, agent can collect auxiliary Docker CLI evidence to separate reclaimable cache from active data.
  5. Agent can summarize disk or disk-subsystem pressure well enough to decide whether to upgrade a disk, migrate data, or repurpose an older device for swap, temp files, and caches.

**Plans**: 4/4 plans complete

Plans:
**Wave 1**

- [x] 03-01-PLAN.md - Add df-vs-index filesystem control-total reconciliation

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md - Add deleted-open-files live diagnostic

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03-PLAN.md - Add Docker/containerd enrichment diagnostic

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 03-04-PLAN.md - Add compact report hints and pressure summary

### Phase 03.1: Storage Efficiency (INSERTED)

**Goal:** Shrink watchdirs's own on-disk SQLite footprint via a flat path dictionary, prove the win with a real measured before/after size + scan-duration benchmark, and add `collect` observability — a hard prerequisite for Phase 4 scheduling.
**Requirements**: churn, path-dict, dedup-cache, schema, pragma-vacuum, reporting-equiv, docker-hints, size-harness, byte-budget, duration, observability (derived from locked decisions D-01..D-11; no formal REQ IDs declared)
**Depends on:** Phase 3
**Plans:** 5/5 plans complete

Plans:

**Wave 1**

- [x] 03.1-01-PLAN.md — Path churn/cardinality measurement on the existing schema (the ROI-determining first deliverable; sets the D-09 gate number)
- [x] 03.1-02-PLAN.md — Flat path-dictionary schema, dedup cache, drop `name`, int indexes, virgin-connection PRAGMAs (SCHEMA_VERSION 3)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03.1-03-PLAN.md — Reporting JOIN paths + int-equality diff + docker GLOB, with golden equivalence
- [x] 03.1-04-PLAN.md — Size benchmark harness (replicate/VACUUM/dbstat) + cold/warm duration + D-09 byte-budget gate

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03.1-05-PLAN.md — collect observability: stderr progress/ETA/summary with pure-JSON stdout

### Phase 4: Scheduled Retention Operations

**Goal**: Operators can rely on watchdirs to collect and retain evidence unattended
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: OPER-01, OPER-02, OPER-03, OPER-04, OPER-05, OPER-06
**Success Criteria** (what must be TRUE):

  1. Host can schedule collection with provided systemd service and timer units, and overlapping runs do not create duplicate or corrupted snapshots.
  2. Scheduled collection runs with low CPU and I/O priority and retains history by whole-snapshot TTL instead of deleting individual path rows.
  3. Maintenance can run a slower post-prune vacuum path to keep the SQLite database healthy over time.
  4. Installation and operational docs explain the database path, timer behavior, retention policy, and expected verification commands for the live host.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Trusted Snapshot Collection | 4/4 | Complete    | 2026-06-12 |
| 2. Growth Frontier Reporting | 4/4 | Complete    | 2026-06-13 |
| 3. Pressure Gap Diagnostics | 4/4 | Complete    | 2026-06-14 |
| 4. Scheduled Retention Operations | 0/TBD | Not started | - |
