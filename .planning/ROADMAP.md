# Roadmap: watchdirs

## Overview

`watchdirs` turns disk-pressure incidents from reactive `df`/`du` spelunking into repeatable evidence. The MVP starts by making snapshot collection trustworthy, then uses that history to surface growth deltas, then explains the main evidence gaps behind `df`/`du` disagreements, and finally operationalizes the tool with unattended scheduling, pruning, and verification docs.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Trusted Snapshot Collection** - Capture accurate directory-only snapshots that reflect real disk-pressure semantics.
- [ ] **Phase 2: Growth Frontier Reporting** - Turn snapshots into JSON-first diff and drill-down workflows for fast triage.
- [ ] **Phase 3: Pressure Gap Diagnostics** - Reconcile indexed growth with `df` mismatches and Docker/containerd evidence.
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

- [ ] 01-01-PLAN.md - No-install collect command surface and explicit config loading

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 01-02-PLAN.md - SQLite schema, migrations, and snapshot lifecycle persistence

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 01-03-PLAN.md - Native scanner aggregate, byte, hardlink, symlink, and error semantics

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 01-04-PLAN.md - Mountinfo parsing, skip policy, scanner pruning, and phase verification

### Phase 2: Growth Frontier Reporting

**Goal**: Agents can identify what grew and where to drill down between snapshots
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: REPT-01, REPT-02, REPT-03, REPT-04, REPT-05, REPT-06
**Success Criteria** (what must be TRUE):

  1. Agent can run `watchdirs diff --since 24h --limit N --json` and receive paths sorted by disk-byte growth.
  2. Agent can run `watchdirs report --since 24h --json` and get a structured summary that distinguishes created, deleted, unchanged, grown, and shrunk paths.
  3. Agent can run `watchdirs top --snapshot latest --limit N --json` to inspect the largest current directory trees.
  4. Agent can run `watchdirs explain-path PATH --since 24h --json` and `watchdirs deleted --since 24h --json` to inspect one suspicious subtree and paths that disappeared since the earlier snapshot.

**Plans**: TBD

### Phase 3: Pressure Gap Diagnostics

**Goal**: Agents can reconcile indexed growth with real filesystem pressure and supporting evidence
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: DIAG-01, DIAG-02, DIAG-03, DIAG-04
**Success Criteria** (what must be TRUE):

  1. Agent can run `watchdirs df-vs-index --json` and compare filesystem usage against indexed directory totals.
  2. Agent can inspect a deleted-open-files diagnostic and see which deleted files are still consuming space through open descriptors.
  3. When indexed totals diverge materially from `df`, watchdirs reports flag deleted-open-file suspicion instead of silently presenting incomplete conclusions.
  4. For Docker/containerd-related growth, agent can collect auxiliary Docker CLI evidence to separate reclaimable cache from active data.

**Plans**: TBD

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
| 1. Trusted Snapshot Collection | 0/4 | Not started | - |
| 2. Growth Frontier Reporting | 0/TBD | Not started | - |
| 3. Pressure Gap Diagnostics | 0/TBD | Not started | - |
| 4. Scheduled Retention Operations | 0/TBD | Not started | - |
