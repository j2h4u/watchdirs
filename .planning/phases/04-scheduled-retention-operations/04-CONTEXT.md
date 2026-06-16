# Phase 4: Scheduled Retention Operations - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 turns `watchdirs` from an on-demand forensic CLI into unattended local evidence collection
for `senbonzakura`. The product goal is not "run a timer" by itself; the goal is that when disk
space starts disappearing, an agent can quickly explain the likely cause from fresh retained
history and can immediately see whether that history has gaps.

**In scope:** systemd service/timer units, low-priority scheduled collection, overlap prevention,
fail-fast evidence-gap behavior, snapshot-level retention pruning, slower SQLite maintenance after
pruning, and operator documentation/verification commands.

**Out of scope:** cleanup orchestration, Docker pruning, service restarts, before/after cleanup
snapshots, UI/dashboard output, permanent file-level indexing, and rollup-summary analytics.
</domain>

<decisions>
## Implementation Decisions

### Product guarantee
- **D-01:** The primary guarantee is **fast disk-pressure explanation**, not a bare retention
  checkbox. A future agent should be able to answer "what is eating disk?" quickly using recent
  snapshot history, tiered older history, diagnostics, and explicit freshness/gap signals.
- **D-02:** Evidence gaps are product-visible failures. If scheduled collection cannot run, cannot
  acquire the operation lock, or cannot write a valid snapshot, the failure should be visible
  through systemd/journal and documented verification commands instead of being silently ignored.

### Retention policy
- **D-03:** v1 retention target: keep **hourly snapshots for 14 days**, **daily representative full
  snapshots for 90 days**, and **monthly representative full snapshots beyond that**.
- **D-04:** Retention deletes **whole snapshots only**. Do not prune individual `directory_sizes`,
  `paths`, or mount rows independently. Existing snapshot foreign-key cascades are the right
  deletion boundary.
- **D-05:** Monthly retention means selecting representative full snapshots, not creating rollup
  summary tables, top-delta summaries, or lossy aggregates. Rollups remain v2/deferred.
- **D-06:** If the database grows too quickly in real operation, reduce the high-frequency hourly
  window before reducing snapshot fidelity or adding a different storage engine.

### Scheduling and failure posture
- **D-07:** Use systemd timers, not cron. The unit should run collection with low CPU and I/O
  priority and integrate with journal logs.
- **D-08:** Overlap prevention is mandatory across collection, pruning, and vacuum-style
  maintenance. The planner may choose the lock mechanism, but the user-visible behavior must be
  fail-fast rather than two writers racing.
- **D-09:** A missed or failed timer run should preserve existing history and make the new evidence
  gap obvious. It should not corrupt or partially prune retained snapshots.

### Maintenance
- **D-10:** Pruning and slower SQLite maintenance are separate from normal reporting. After pruning,
  provide a slower maintenance path that can reclaim database pages (`VACUUM` or the safest
  SQLite-appropriate equivalent selected by planning).
- **D-11:** Maintenance must be safe under the same operation-lock model as collection. It must not
  run concurrently with `collect`.

### Deferred cleanup-window snapshots
- **D-12:** Automatic "snapshot before and after cleanup" behavior is deferred. It sounds useful for
  future cleanup workflows, but Phase 4 should first deliver reliable regular evidence collection
  and retention. Do not couple this phase to Docker prune, logrotate, service restart, or manual
  cleanup windows.

### the agent's Discretion
- Exact systemd unit filenames, install location, timer calendar expression, lock implementation,
  pruning command shape, and maintenance command naming are delegated to research/planning.
- Planners should choose a minimal, testable CLI surface that satisfies OPER-01 through OPER-06 and
  keeps JSON-first behavior intact.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and requirements
- `.planning/ROADMAP.md` — Phase 4 goal, dependencies, requirements OPER-01 through OPER-06, and
  success criteria.
- `.planning/REQUIREMENTS.md` — Operations requirements and traceability rows for OPER-01 through
  OPER-06.
- `.planning/PROJECT.md` — Active operations requirements, host scope, systemd decision, and core
  product value.
- `README.md` §Retention Policy and §Scheduling — original policy defaults and operational
  rationale; update if implementation changes them.
- `AGENTS.md` — project constraints: local forensic CLI, SQLite v1, systemd timers, low priority,
  locking, retention by whole snapshots, JSON-first interface.

### Prior phase decisions
- `.planning/phases/03.1-storage-efficiency/03.1-CONTEXT.md` — scheduling and retention were
  explicitly held for Phase 4; SQLite page/VACUUM and benchmark decisions constrain maintenance.
- `.planning/phases/03.1-storage-efficiency/03.1-VERIFICATION.md` — storage efficiency gate passed,
  so Phase 4 can proceed without DuckDB escalation.
- `.planning/phases/03.2-scan-time-folder-collapse/03.2-CONTEXT.md` — scan-time collapse makes the
  Phase 4 retention budget feasible; tiered retention was deferred here.
- `.planning/phases/03.2-scan-time-folder-collapse/03.2-VERIFICATION.md` — collapse verification and
  post-review fixes; planners should assume schema version 4 and collapsed rows exist.

### Code surfaces
- `src/watchdirs/cli.py` — existing command registration, `collect` handler, DB opening, error
  envelopes, stderr collect logging, and JSON-first behavior.
- `src/watchdirs/config.py` — default state/database path and TOML config parsing.
- `src/watchdirs/db/connection.py` — SQLite connection PRAGMAs, `busy_timeout`, WAL mode, foreign
  keys, page size, and auto-vacuum setup.
- `src/watchdirs/db/migrations.py` — snapshot lifecycle helpers, insert/finalize semantics, and
  snapshot FK cascade behavior.
- `src/watchdirs/db/schema.sql` — snapshots, path dictionary, directory rows, and snapshot mounts;
  retention must preserve schema invariants.
- `src/watchdirs/bench/duration.py` — existing production-priority `nice`/`ionice` precedent and
  timing harness comments.
- `examples/senbonzakura.watchdirs.toml` — current live-host example config.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `default_db_path()` in `src/watchdirs/config.py` already points to the XDG state location for the
  default SQLite database.
- `run_collect()` in `src/watchdirs/cli.py` already uses stderr logging, snapshot creation,
  transactional directory/mount inserts, and failed-snapshot finalization.
- `snapshots` has `ON DELETE CASCADE` dependents through `directory_sizes` and `snapshot_mounts`,
  which supports whole-snapshot retention pruning.
- `open_connection()` enables WAL, foreign keys, busy timeout, page size, application id, and
  auto-vacuum behavior.
- `src/watchdirs/bench/duration.py` already documents and implements `nice`/`ionice -c2 -n7` as
  the production-priority precedent.

### Established Patterns
- JSON output is the stable agent contract; human text is secondary.
- Operational logs and progress go to stderr/journal, not stdout JSON.
- CLI/config, scanning, DB persistence, diagnostics, and rendering stay separated.
- Snapshot rows are durable evidence; failed/partial snapshots are recorded rather than hidden.
- No backward-compat shims for obsolete schemas unless an already-supported migration path requires
  them.

### Integration Points
- Add any new CLI commands through `build_parser()` / handler functions in `src/watchdirs/cli.py`.
- Add retention/maintenance DB logic near the DB/query layer rather than embedding ad hoc SQL in
  systemd unit files.
- Add systemd/service assets and install docs in repo-owned paths selected by planning.
- Tests should exercise lock behavior, whole-snapshot pruning, cascade effects, maintenance safety,
  and operator verification commands.
</code_context>

<specifics>
## Specific Ideas

- User clarified the product goal as: "my agent can understand as quickly as possible why disk
  space is running out."
- User explicitly chose **fail fast** for scheduled-collection failure posture.
- User clarified the retention shape as: hourly for 14 days, daily for 90 days, and the rest
  monthly.
- The phrase "incident" means a disk-pressure situation such as `df` suddenly growing or free
  space getting low, not necessarily a service outage.
- Expert panel convergence: prioritize explicit freshness/gap signals, keep monthly as full
  snapshots rather than rollups, guard collect/prune/vacuum with one operation-lock model, and
  defer cleanup-window snapshots.
</specifics>

<deferred>
## Deferred Ideas

- Automatic snapshots before and after cleanup windows.
- Cleanup orchestration such as Docker prune, logrotate changes, service restarts, or "safe to
  delete" actions.
- Weekly/monthly rollup summaries or top-delta aggregate tables.
- Alerting/observability metrics beyond verification commands and systemd/journal visibility.
- File-level retention or permanent file inventory.
</deferred>

---

*Phase: 4-Scheduled Retention Operations*
*Context gathered: 2026-06-17*
