# Requirements: watchdirs

**Defined:** 2026-06-12
**Core Value:** When disk usage changes unexpectedly, an agent can identify the largest growing directory trees and the evidence gaps behind `df`/`du` disagreements quickly and reproducibly.

## v1 Requirements

Requirements for the first usable local release.

### Collection

- [x] **COLL-01**: Agent can run `watchdirs collect` to create a timestamped directory-size snapshot for configured roots.
- [x] **COLL-02**: Collection records a snapshot status, start time, finish time, root path, notes, and any fatal error.
- [x] **COLL-03**: Collection records recursive directory aggregate rows with path, parent path, name, depth, apparent bytes, disk bytes, file count, directory count, and per-path error.
- [x] **COLL-04**: Collection stores disk bytes using physical allocation semantics compatible with `st_blocks * 512` or `du`.
- [x] **COLL-05**: Collection stores apparent bytes using logical file size semantics compatible with `st_size`.

### Filesystem Semantics

- [x] **FSEM-01**: Scanner does not follow symlinks by default.
- [x] **FSEM-02**: Scanner avoids double-counting physical bytes for hardlinked files within one snapshot.
- [x] **FSEM-03**: Scanner reads mount information and skips virtual/transient filesystems by default.
- [x] **FSEM-04**: Scanner avoids descending into container overlay mount views and namespace mounts by default.
- [x] **FSEM-05**: Scanner records partial path-level errors instead of silently dropping inaccessible subtrees.

### Reporting

- [x] **REPT-01**: Agent can run `watchdirs diff --since 24h --limit N --json` to list paths sorted by disk-byte growth.
- [x] **REPT-02**: Agent can run `watchdirs report --since 24h --json` to get a structured investigation summary.
- [x] **REPT-03**: Agent can run `watchdirs top --snapshot latest --limit N --json` to list largest current directory trees.
- [x] **REPT-04**: Agent can run `watchdirs explain-path PATH --since 24h --json` to drill into one subtree's growth.
- [x] **REPT-05**: Agent can run `watchdirs deleted --since 24h --json` to list paths present in the earlier snapshot but absent in the later snapshot.
- [x] **REPT-06**: Reports distinguish created, deleted, unchanged, grown, and shrunk paths.
- [x] **REPT-07**: Reports can group growth and current usage by filesystem or mounted storage domain so multi-SSD hosts show which filesystem owns the pressure.

### Diagnostics

- [ ] **DIAG-01**: Agent can run `watchdirs df-vs-index --json` to compare filesystem usage against indexed directory totals.
- [ ] **DIAG-02**: Agent can run a deleted-open-files diagnostic that reports files still held open after deletion.
- [ ] **DIAG-03**: Reports call out deleted-open-file suspicion when `df` usage and indexed totals diverge materially.
- [ ] **DIAG-04**: Agent can collect Docker/containerd enrichment for relevant growth paths using Docker CLI evidence when available.
- [ ] **DIAG-05**: Agent can summarize pressure and growth by attached disk or disk subsystem well enough to support capacity decisions such as upgrade, data migration, or repurposing an older disk for swap, temp files, and caches.

### Operations

- [ ] **OPER-01**: Project provides systemd service and timer units for scheduled collection.
- [ ] **OPER-02**: Scheduled collection runs with low CPU and I/O priority.
- [ ] **OPER-03**: Collection uses a lock so overlapping runs cannot corrupt or duplicate snapshots.
- [ ] **OPER-04**: Project provides retention pruning by deleting whole snapshots according to hourly and daily TTL policy.
- [ ] **OPER-05**: Project provides a slower maintenance path for SQLite vacuum after pruning.
- [ ] **OPER-06**: Installation and operational docs explain the database path, timer behavior, retention policy, and expected verification commands.

## v2 Requirements

Deferred until the directory-snapshot model proves insufficient.

### File Inventory

- **FILE-01**: Agent can run an on-demand temporary file-level scan for a suspicious subtree.
- **FILE-02**: Agent can optionally persist daily or weekly file inventory for selected roots.

### Rollups

- **ROLL-01**: Agent can retain weekly top-delta summaries for 6-12 months.
- **ROLL-02**: Agent can export snapshots or rollups to Parquet for offline analytics.

### Observability

- **OBSV-01**: Agent can emit small allowlisted metrics for known high-risk paths.
- **OBSV-02**: Agent can alert when a watched path exceeds a configured growth threshold.

## Out of Scope

Explicitly excluded from v1.

| Feature | Reason |
|---------|--------|
| UI-first disk visualizer | Agent-facing JSON and CLI evidence are the primary value. |
| Continuous inotify monitoring | The target incident is historical growth between points in time. |
| Permanent full file indexing | Directory aggregates should prove insufficient before paying this cost. |
| Graph database storage | Path snapshot diffs are simpler in SQLite. |
| Time-series database storage | Path churn and full path labels create cardinality and deletion problems. |
| Prometheus/Grafana as primary store | Better for known-surface alerting than forensic path diffs. |
| DuckDB as operational store | Good for offline analysis, but not the small periodic write target. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| COLL-01 | Phase 1 | Complete |
| COLL-02 | Phase 1 | Complete |
| COLL-03 | Phase 1 | Complete |
| COLL-04 | Phase 1 | Complete |
| COLL-05 | Phase 1 | Complete |
| FSEM-01 | Phase 1 | Complete |
| FSEM-02 | Phase 1 | Complete |
| FSEM-03 | Phase 1 | Complete |
| FSEM-04 | Phase 1 | Complete |
| FSEM-05 | Phase 1 | Complete |
| REPT-01 | Phase 2 | Complete |
| REPT-02 | Phase 2 | Complete |
| REPT-03 | Phase 2 | Complete |
| REPT-04 | Phase 2 | Complete |
| REPT-05 | Phase 2 | Complete |
| REPT-06 | Phase 2 | Complete |
| REPT-07 | Phase 2 | Complete |
| DIAG-01 | Phase 3 | Pending |
| DIAG-02 | Phase 3 | Pending |
| DIAG-03 | Phase 3 | Pending |
| DIAG-04 | Phase 3 | Pending |
| DIAG-05 | Phase 3 | Pending |
| OPER-01 | Phase 4 | Pending |
| OPER-02 | Phase 4 | Pending |
| OPER-03 | Phase 4 | Pending |
| OPER-04 | Phase 4 | Pending |
| OPER-05 | Phase 4 | Pending |
| OPER-06 | Phase 4 | Pending |
| FILE-01 | v2 | Deferred |
| FILE-02 | v2 | Deferred |
| ROLL-01 | v2 | Deferred |
| ROLL-02 | v2 | Deferred |
| OBSV-01 | v2 | Deferred |
| OBSV-02 | v2 | Deferred |

**Coverage:**

- v1 requirements: 28 total
- Mapped to phases: 28
- v2 deferred requirements: 6
- Unmapped: 0

---
*Requirements defined: 2026-06-12*
*Last updated: 2026-06-12 after roadmap creation*
