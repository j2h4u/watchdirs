# Phase 4: Scheduled Retention Operations - Research

**Researched:** 2026-06-17
**Domain:** systemd-scheduled SQLite retention operations for a Python forensic CLI
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
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

### Deferred Ideas (OUT OF SCOPE)
- Automatic snapshots before and after cleanup windows.
- Cleanup orchestration such as Docker prune, logrotate changes, service restarts, or "safe to
  delete" actions.
- Weekly/monthly rollup summaries or top-delta aggregate tables.
- Alerting/observability metrics beyond verification commands and systemd/journal visibility.
- File-level retention or permanent file inventory.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPER-01 | Project provides systemd service and timer units for scheduled collection. [VERIFIED: .planning/REQUIREMENTS.md] | Use `Type=oneshot` services plus `OnCalendar` timers with `Persistent=true`; keep collect/prune/vacuum as explicit operations. [VERIFIED: .planning/REQUIREMENTS.md + man systemd.service + man systemd.timer] |
| OPER-02 | Scheduled collection runs with low CPU and I/O priority. [VERIFIED: .planning/REQUIREMENTS.md] | Set `Nice=19`, `IOSchedulingClass=best-effort`, `IOSchedulingPriority=7`; this matches the repo’s existing production benchmark precedent. [VERIFIED: .planning/REQUIREMENTS.md + src/watchdirs/bench/duration.py + man systemd.exec] |
| OPER-03 | Collection uses a lock so overlapping runs cannot corrupt or duplicate snapshots. [VERIFIED: .planning/REQUIREMENTS.md] | Add one non-blocking writer lock shared by collect/prune/vacuum, implemented inside Python so manual CLI and systemd both honor it. [VERIFIED: .planning/REQUIREMENTS.md + src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html] |
| OPER-04 | Project provides retention pruning by deleting whole snapshots according to hourly and daily TTL policy. [VERIFIED: .planning/REQUIREMENTS.md] | Prune by snapshot IDs per `root_path`, rely on existing FK cascades for `directory_sizes` and `snapshot_mounts`, then explicitly GC orphan `paths`. [VERIFIED: .planning/REQUIREMENTS.md + src/watchdirs/db/schema.sql + .planning/phases/03.1-storage-efficiency/03.1-RESEARCH.md][CITED: https://www.sqlite.org/foreignkeys.html] |
| OPER-05 | Project provides a slower maintenance path for SQLite vacuum after pruning. [VERIFIED: .planning/REQUIREMENTS.md] | Keep `VACUUM` separate from normal collect; run it off-peak under the same lock after prune windows. [VERIFIED: .planning/REQUIREMENTS.md + 04-CONTEXT.md][CITED: https://www.sqlite.org/lang_vacuum.html][CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum] |
| OPER-06 | Installation and operational docs explain the database path, timer behavior, retention policy, and expected verification commands. [VERIFIED: .planning/REQUIREMENTS.md] | Document `/var/lib/watchdirs/watchdirs.sqlite3`, `/etc/watchdirs/watchdirs.toml`, timer enable/list/status commands, journal checks, and retention verification SQL/CLI examples. [VERIFIED: .planning/REQUIREMENTS.md + README.md + man systemd.exec + man systemd.timer] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Target `senbonzakura` first. [VERIFIED: AGENTS.md]
- Keep SQLite as the v1 store. [VERIFIED: AGENTS.md]
- Keep recursive directory aggregate rows as the persistent model. [VERIFIED: AGENTS.md]
- Do not follow symlinks and do not silently descend into virtual, transient, or container overlay filesystems. [VERIFIED: AGENTS.md]
- Preserve both apparent-byte and disk-byte semantics, with explicit hardlink behavior. [VERIFIED: AGENTS.md]
- Use systemd timers, low priority, locking, partial-failure recording, and whole-snapshot retention. [VERIFIED: AGENTS.md]
- Keep JSON output as the first-class interface; human text is secondary. [VERIFIED: AGENTS.md]
- Do not recommend repo edits outside the active GSD workflow. This research stays inside the current planning workflow. [VERIFIED: AGENTS.md + .planning/config.json]

## Summary

Phase 4 should be planned as three finite write operations over one SQLite file: `collect`, `prune`, and `vacuum`, each exposed as an explicit CLI path and wrapped by systemd `Type=oneshot` services. `collect` runs hourly; `prune` runs on a slower cadence and deletes whole snapshots only; `vacuum` runs even less often and only after pruning. All three writer operations must share one non-blocking lock so that overlap becomes a visible failure instead of a race. [VERIFIED: 04-CONTEXT.md + src/watchdirs/cli.py + src/watchdirs/db/schema.sql + man systemd.service + man systemd.timer][CITED: https://docs.python.org/3/library/fcntl.html]

The retention algorithm has one important schema consequence that Phase 03.1 already foreshadowed: deleting `snapshots` will cascade `directory_sizes` and `snapshot_mounts`, but it will not remove orphaned rows from the dictionary-style `paths` table. Phase 4 therefore needs explicit `paths` garbage collection after snapshot pruning, or the database will keep growing even when old snapshots are expired. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/03.1-storage-efficiency/03.1-RESEARCH.md][CITED: https://www.sqlite.org/foreignkeys.html]

SQLite maintenance must stay conservative. `auto_vacuum=FULL` is already enabled on virgin databases in the repo, but SQLite’s own docs say FULL only truncates freelist pages and can worsen fragmentation; it does not replace `VACUUM`. `VACUUM` reclaims space and defragments, but it needs substantial free disk space and fails if another transaction or conflicting lock is active. That matches the user’s locked direction: prune normally, then provide a slower maintenance path under the same lock. [VERIFIED: src/watchdirs/db/connection.py + 04-CONTEXT.md][CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum][CITED: https://www.sqlite.org/lang_vacuum.html]

**Primary recommendation:** Plan Phase 4 around three systemd oneshot writer operations sharing one internal non-blocking `fcntl.flock` lock, with hourly `collect`, daily per-root whole-snapshot `prune` plus orphan-path GC, and off-peak weekly `vacuum`. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql + man systemd.service + man systemd.timer][CITED: https://docs.python.org/3/library/fcntl.html]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Hourly unattended collection | Frontend Server (SSR) | API / Backend | On this project the “frontend server” equivalent is the systemd service boundary that schedules and launches finite CLI work; the actual collection logic remains in Python backend code. [VERIFIED: AGENTS.md + 04-CONTEXT.md + src/watchdirs/cli.py + man systemd.service] |
| Overlap prevention across write operations | API / Backend | Frontend Server (SSR) | The lock must live in the CLI/runtime so both systemd and manual invocations share it; the unit file only launches the process. [VERIFIED: 04-CONTEXT.md + src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html] |
| Snapshot retention selection | API / Backend | Database / Storage | Bucket selection is application logic, while deletion cascades happen in SQLite. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/schema.sql] |
| Whole-snapshot delete and orphan-path GC | Database / Storage | API / Backend | Deletes execute in SQLite, but the app must choose snapshot IDs and explicitly clean unused `paths` rows. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/03.1-storage-efficiency/03.1-RESEARCH.md][CITED: https://www.sqlite.org/foreignkeys.html] |
| Slow database compaction | Database / Storage | Frontend Server (SSR) | `VACUUM` is a database operation, but the timer/service decides when to run it and how failures surface. [VERIFIED: 04-CONTEXT.md + man systemd.timer][CITED: https://www.sqlite.org/lang_vacuum.html] |
| Operator evidence and verification docs | Frontend Server (SSR) | API / Backend | Operators interact through systemctl/journalctl and the CLI’s JSON/text outputs, which are documented around the runtime behavior. [VERIFIED: README.md + src/watchdirs/cli.py + man systemd.exec] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`argparse`, `logging`, `sqlite3`, `fcntl`) | Project floor `>=3.11`; host `3.13.5`; host SQLite binding `3.46.1`. [VERIFIED: pyproject.toml + python3 --version + `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`] | CLI operations, journaling-friendly stderr logs, SQLite access, and lock implementation. [VERIFIED: src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html] | No new packages are needed; the repo already uses a stdlib-only runtime. [VERIFIED: pyproject.toml + src/watchdirs/cli.py] |
| SQLite | Host CLI `3.46.1`. [VERIFIED: sqlite3 --version] | Persistent snapshot store, prune SQL, and `VACUUM`. [VERIFIED: AGENTS.md + src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/lang_vacuum.html] | Locked by project scope and already integrated through `open_connection()` and migrations. [VERIFIED: AGENTS.md + src/watchdirs/db/connection.py + src/watchdirs/db/migrations.py] |
| systemd (`.service` + `.timer`) | Host `257`. [VERIFIED: systemctl --version] | Scheduling, low-priority execution, managed state directories, and journald visibility. [VERIFIED: 04-CONTEXT.md + AGENTS.md + man systemd.service + man systemd.timer + man systemd.exec] | D-07 locks systemd timers in; the target host already has systemd tooling available. [VERIFIED: 04-CONTEXT.md + AGENTS.md + systemctl --version] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `journalctl` | `257`. [VERIFIED: journalctl --version] | Verify missed runs, lock conflicts, and prune/vacuum failures. [VERIFIED: 04-CONTEXT.md + man systemd.exec] | Use for OPER-06 verification docs and live-host troubleshooting. [VERIFIED: .planning/REQUIREMENTS.md + journalctl --version] |
| `nice` / `ionice` | `nice 9.7`; `ionice` present. [VERIFIED: nice --version + command -v ionice] | Match the repo’s existing production-priority precedent. [VERIFIED: src/watchdirs/bench/duration.py + man systemd.exec] | Use in units through systemd execution properties, not ad hoc shell wrappers in the main design. [VERIFIED: src/watchdirs/bench/duration.py + man systemd.exec] |
| util-linux `flock(1)` | `2.41`. [VERIFIED: flock --version] | Verification aid and fallback mental model for advisory locking. [VERIFIED: man flock] | Use for manual debugging only if needed; the recommended product lock remains internal Python `fcntl.flock`. [VERIFIED: flock --version][CITED: https://docs.python.org/3/library/fcntl.html] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Internal Python lock helper | util-linux `flock -n` in unit files. [VERIFIED: flock --version + man flock] | Easier systemd wrapper, but manual CLI writes would bypass the lock unless every write path shells through a wrapper. The Python lock is more testable and applies everywhere. [VERIFIED: src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html] |
| Separate `VACUUM` path | Rely on `auto_vacuum=FULL` alone. [VERIFIED: src/watchdirs/db/connection.py] | FULL can shrink freelist pages but does not defragment and can worsen fragmentation, so it does not satisfy D-10 by itself. [VERIFIED: 04-CONTEXT.md][CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum][CITED: https://www.sqlite.org/lang_vacuum.html] |
| systemd timers | cron. | Directly contradicts D-07 and loses built-in journal integration plus systemd directory helpers. [VERIFIED: 04-CONTEXT.md + AGENTS.md + man systemd.timer] |

**Installation:**
```bash
# No external packages are required for this phase.
uv sync
```
[VERIFIED: pyproject.toml]

## Architecture Patterns

### System Architecture Diagram

```text
watchdirs-collect.timer (hourly, Persistent=true)
        |
        v
watchdirs-collect.service (Type=oneshot, low priority)
        |
        v
watchdirs collect --config /etc/watchdirs/watchdirs.toml --db /var/lib/watchdirs/watchdirs.sqlite3
        |
        v
global writer lock (non-blocking) ----X----> concurrent collect/prune/vacuum
        |
        v
SQLite snapshot write -> snapshot status finalize -> stderr/journal evidence

watchdirs-prune.timer (daily, offset from collect) ---> watchdirs-prune.service ---> watchdirs prune
                                                                  |
                                                                  v
                                           select kept snapshot ids per root/status/window
                                                                  |
                                                                  v
                                               DELETE old snapshots -> FK cascades
                                                                  |
                                                                  v
                                                      explicit orphan-path GC

watchdirs-vacuum.timer (weekly, off-peak) ---> watchdirs-vacuum.service ---> watchdirs vacuum
                                                                  |
                                                                  v
                                              acquire same writer lock -> VACUUM
                                                                  |
                                                                  v
                                                     journal-visible success/failure
```

### Recommended Project Structure

```text
src/watchdirs/
├── cli.py                 # Register new prune/vacuum commands and shared lock/error handling
├── config.py              # Reuse DB-path defaults and any systemd-path helpers
├── db/
│   ├── connection.py      # Keep SQLite connection/PRAGMA behavior centralized
│   └── retention.py       # New prune selection, snapshot delete, orphan-path GC, vacuum helpers
ops/systemd/
├── watchdirs-collect.service
├── watchdirs-collect.timer
├── watchdirs-prune.service
├── watchdirs-prune.timer
├── watchdirs-vacuum.service
└── watchdirs-vacuum.timer
tests/
├── test_ops_locking.py
├── test_ops_retention.py
├── test_ops_vacuum.py
└── test_systemd_units.py
```
[VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/connection.py + tests/ + 04-CONTEXT.md]

### Pattern 1: One Internal Writer Lock For All Mutating Commands

**What:** Acquire one advisory exclusive lock near the top of every mutating CLI command (`collect`, `prune`, `vacuum`) and fail immediately if the lock is already held. [VERIFIED: 04-CONTEXT.md + src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html]

**When to use:** Always for write operations on the SQLite database. Keep read-only commands unlocked. [VERIFIED: 04-CONTEXT.md + src/watchdirs/cli.py][ASSUMED]

**Example:**
```python
# Source: https://docs.python.org/3/library/fcntl.html
import errno
import fcntl
import os

fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as exc:
    if exc.errno in (errno.EACCES, errno.EAGAIN):
        raise OperationLocked(lock_path) from exc
    raise
```

### Pattern 2: Per-Root Snapshot Tiering, Then Whole-Snapshot Delete

**What:** Select retained snapshots per `root_path`, keep all recent snapshots, then one COMPLETE representative per day and later one COMPLETE representative per month. Delete old `snapshots` rows only after computing the keep-set. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql + 04-CONTEXT.md]

**When to use:** For the retention command only; do not mix with report queries or mutate child tables directly. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/schema.sql]

**Example:**
```sql
-- Source: schema + Phase 4 context
DELETE FROM snapshots
WHERE id IN (:expired_snapshot_ids);

DELETE FROM paths
WHERE NOT EXISTS (SELECT 1 FROM directory_sizes WHERE directory_sizes.path_id = paths.id)
  AND NOT EXISTS (SELECT 1 FROM directory_sizes WHERE directory_sizes.parent_id = paths.id)
  AND NOT EXISTS (SELECT 1 FROM directory_sizes WHERE directory_sizes.top_child_id = paths.id);
```

### Pattern 3: Separate Prune And Vacuum Cadences

**What:** Run prune frequently enough to enforce retention, but schedule `VACUUM` less often and off-peak because it rebuilds the database and can require up to roughly twice the database size in free disk space. [VERIFIED: 04-CONTEXT.md][CITED: https://www.sqlite.org/lang_vacuum.html]

**When to use:** Daily prune and weekly vacuum are the most conservative v1 plan shape for one host. [VERIFIED: 04-CONTEXT.md][ASSUMED]

**Example:**
```ini
# Source: man systemd.timer + man systemd.service
[Timer]
OnCalendar=hourly
Persistent=true
Unit=watchdirs-collect.service
```

### Anti-Patterns to Avoid

- **Row-level pruning of `directory_sizes` or `snapshot_mounts`:** It breaks the snapshot evidence model and contradicts D-04. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/schema.sql]
- **Unit-file-only locking:** A unit-file wrapper lock protects the timer path but not a manual `watchdirs prune` or `watchdirs vacuum`. [VERIFIED: src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html]
- **Bundling `VACUUM` into every collect:** It violates D-10’s slower maintenance path and needlessly increases hourly runtime and risk. [VERIFIED: 04-CONTEXT.md][CITED: https://www.sqlite.org/lang_vacuum.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Periodic scheduling | cron parser / custom daemon loop | systemd timers. [VERIFIED: 04-CONTEXT.md + man systemd.timer] | D-07 already locks this in, and systemd provides catch-up, dependencies, and journal integration. [VERIFIED: 04-CONTEXT.md + man systemd.timer] |
| Writer concurrency control | ad hoc PID files or sleep/retry loops | advisory file lock via Python `fcntl.flock`. [CITED: https://docs.python.org/3/library/fcntl.html] | PID files go stale; a real FD-held lock drops automatically on process exit and supports fail-fast semantics. [CITED: https://docs.python.org/3/library/fcntl.html] |
| Snapshot retention delete semantics | row-by-row child-table deletes | `DELETE FROM snapshots ...` plus FK cascades. [VERIFIED: src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/foreignkeys.html] | The schema already encodes the right boundary for `directory_sizes` and `snapshot_mounts`. [VERIFIED: src/watchdirs/db/schema.sql] |
| Database compaction | home-grown page-rewrite logic | SQLite `VACUUM`. [CITED: https://www.sqlite.org/lang_vacuum.html] | SQLite already defines the safe compaction path and its constraints. [CITED: https://www.sqlite.org/lang_vacuum.html] |

**Key insight:** The tricky part of this phase is not scheduling one command; it is preserving evidence semantics while mutating the same WAL database over months. The safest plan is to lean on systemd for orchestration, SQLite for cascade deletes and compaction, and stdlib `flock` for overlap prevention. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/schema.sql + man systemd.timer][CITED: https://docs.python.org/3/library/fcntl.html][CITED: https://www.sqlite.org/lang_vacuum.html]

## Common Pitfalls

### Pitfall 1: Forgetting orphan-path garbage collection

**What goes wrong:** Snapshot pruning appears to work, but the `paths` table keeps growing forever because nothing references it with `ON DELETE CASCADE`. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/03.1-storage-efficiency/03.1-RESEARCH.md]
**Why it happens:** `directory_sizes` references `paths`, not the other way around; deleting snapshots only removes child rows. [VERIFIED: src/watchdirs/db/schema.sql]
**How to avoid:** After deleting expired snapshots, run explicit orphan-path cleanup in the same transaction scope or immediately after it under the same writer lock. [VERIFIED: src/watchdirs/db/schema.sql][ASSUMED]
**Warning signs:** Snapshot count drops while file size or `SELECT COUNT(*) FROM paths` keeps trending upward. [VERIFIED: src/watchdirs/db/schema.sql][ASSUMED]

### Pitfall 2: Blocking lock acquisition hides evidence gaps

**What goes wrong:** A second collect/prune/vacuum waits silently for the first one, so operators see “late” snapshots instead of an explicit missed-run signal. [VERIFIED: 04-CONTEXT.md][CITED: https://docs.python.org/3/library/fcntl.html]
**Why it happens:** Default `flock(1)` behavior waits, and naive code often retries or blocks instead of failing. [VERIFIED: man flock][CITED: https://docs.python.org/3/library/fcntl.html]
**How to avoid:** Use `LOCK_EX | LOCK_NB` and convert `EACCES`/`EAGAIN` into a stable runtime error plus non-zero exit. [CITED: https://docs.python.org/3/library/fcntl.html]
**Warning signs:** Journal shows long-running overlapping units but no explicit “lock held” failure. [VERIFIED: 04-CONTEXT.md + man systemd.exec][ASSUMED]

### Pitfall 3: Assuming `auto_vacuum=FULL` replaces `VACUUM`

**What goes wrong:** The database shrinks only partially, remains fragmented, or keeps more space than expected after large prune waves. [VERIFIED: src/watchdirs/db/connection.py][CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum][CITED: https://www.sqlite.org/lang_vacuum.html]
**Why it happens:** SQLite says FULL truncates freelist pages but does not defragment and can worsen fragmentation. [CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum]
**How to avoid:** Keep FULL enabled for day-to-day behavior, but still provide a slower explicit `VACUUM` path after prune windows. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/connection.py][CITED: https://www.sqlite.org/lang_vacuum.html]
**Warning signs:** `freelist_count` drops but on-disk DB size stays stubbornly high until manual maintenance. [CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum][ASSUMED]

### Pitfall 4: Concurrent writers or checkpoints on the WAL database

**What goes wrong:** `VACUUM` or write operations fail with `SQLITE_BUSY`, or worse, you rely on a concurrency pattern SQLite explicitly treats as sensitive in WAL mode. [VERIFIED: src/watchdirs/db/connection.py + sqlite3 --version][CITED: https://www.sqlite.org/wal.html]
**Why it happens:** WAL mode persists across connections, and SQLite documents busy cases plus a recent WAL-reset race affecting multi-writer/checkpoint timing; the host’s `3.46.1` version predates the documented fix releases. [VERIFIED: sqlite3 --version][CITED: https://www.sqlite.org/wal.html]
**How to avoid:** Serialize all watchdirs writer operations with one lock and keep `VACUUM` off the normal hourly path. [VERIFIED: 04-CONTEXT.md][CITED: https://www.sqlite.org/wal.html]
**Warning signs:** Journal or CLI errors with `SQLITE_BUSY`, failed maintenance timers, or external ad hoc SQLite sessions during vacuum windows. [VERIFIED: man systemd.exec][CITED: https://www.sqlite.org/wal.html][ASSUMED]

## Code Examples

Verified patterns from official sources:

### Non-blocking writer lock
```python
# Source: https://docs.python.org/3/library/fcntl.html
import errno
import fcntl
import os

fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError as exc:
    if exc.errno in (errno.EACCES, errno.EAGAIN):
        return runtime_error("operation_locked", lock_path)
    raise
```

### Systemd oneshot collect unit
```ini
# Source: man systemd.service + man systemd.exec
[Service]
Type=oneshot
Nice=19
IOSchedulingClass=best-effort
IOSchedulingPriority=7
StateDirectory=watchdirs
ExecStart=/usr/bin/env PYTHONUNBUFFERED=1 watchdirs collect --config /etc/watchdirs/watchdirs.toml --db /var/lib/watchdirs/watchdirs.sqlite3 --verbose
```

### Off-peak catch-up timer
```ini
# Source: man systemd.timer
[Timer]
OnCalendar=hourly
Persistent=true
AccuracySec=1min
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual `df`/`du`/Docker sweeps after an incident. [VERIFIED: README.md] | Retained directory snapshots plus scheduled collection and explicit gap visibility. [VERIFIED: README.md + 04-CONTEXT.md] | Project direction locked by the README and Phase 4 context before 2026-06-17. [VERIFIED: README.md + 04-CONTEXT.md] | Agents can answer “what changed?” without starting from zero. [VERIFIED: README.md + .planning/PROJECT.md] |
| `auto_vacuum` assumed sufficient for long-lived SQLite maintenance. | `auto_vacuum=FULL` for routine shrink plus explicit off-peak `VACUUM` for real compaction. [VERIFIED: src/watchdirs/db/connection.py][CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum][CITED: https://www.sqlite.org/lang_vacuum.html] | SQLite docs current through 2025-07-12 keep the distinction explicit. [CITED: https://www.sqlite.org/lang_vacuum.html] | Planner must schedule a separate maintenance path, not just a delete command. [VERIFIED: 04-CONTEXT.md] |
| Multiple writer/checkpoint paths treated as ordinary WAL behavior. | Serialize mutating operations tightly; current SQLite docs document a recent WAL-reset race and the host runtime is older than the fix lines listed there. [VERIFIED: sqlite3 --version][CITED: https://www.sqlite.org/wal.html] | SQLite doc updated 2026-03-13 for the fix note. [CITED: https://www.sqlite.org/wal.html] | The global writer lock is not optional polish; it is a correctness control. [VERIFIED: 04-CONTEXT.md] |

**Deprecated/outdated:**
- Cron for this phase: it contradicts D-07 and discards the systemd-specific operational guarantees already chosen by the user. [VERIFIED: 04-CONTEXT.md + AGENTS.md]
- Retention by child-row deletion: it contradicts D-04 and the schema’s FK design. [VERIFIED: 04-CONTEXT.md + src/watchdirs/db/schema.sql]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Read-only commands can stay unlocked while only mutating commands share the writer lock. | Architecture Patterns / Common Pitfalls | A report command holding a read transaction during `VACUUM` could cause more maintenance retries than expected. |
| A2 | Daily and monthly representative snapshots should use the latest COMPLETE snapshot per `root_path` and calendar bucket. | Architecture Patterns | A different representative rule could change which evidence survives long-term retention. |
| A3 | A system service should run as root or an equivalently privileged account for senbonzakura’s likely forensic roots. | Summary / Security Domain | Running under too little privilege would create more partial snapshots and evidence gaps than intended. |

## Open Questions

1. **What exact representative-selection rule should Phase 4 lock for daily/monthly tiers?**
   - What we know: D-03 requires daily and monthly representative full snapshots, and collect creates one snapshot per root. [VERIFIED: 04-CONTEXT.md + src/watchdirs/cli.py]
   - What's unclear: whether “representative” means latest COMPLETE snapshot in the bucket, earliest COMPLETE, or a named wall-clock target. [VERIFIED: 04-CONTEXT.md][ASSUMED]
   - Recommendation: lock “latest COMPLETE snapshot per `root_path` per bucket” during planning because it maximizes retained freshness with the current schema. [ASSUMED]

2. **Should prune be inline with collect or a separate timer?**
   - What we know: D-10 separates pruning and slower maintenance from normal reporting, but does not force prune to be inside or outside collect. [VERIFIED: 04-CONTEXT.md]
   - What's unclear: whether the user wants one hourly service that also prunes or a distinct daily retention operation. [VERIFIED: 04-CONTEXT.md][ASSUMED]
   - Recommendation: plan prune as a separate daily service/timer so failure surfaces stay specific and hourly collection remains bounded. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `systemctl` / systemd | Timer/service install and verification | ✓ [VERIFIED: command -v systemctl] | `257`. [VERIFIED: systemctl --version] | None; systemd is a locked requirement. [VERIFIED: 04-CONTEXT.md] |
| `journalctl` | OPER-06 verification and failure visibility | ✓ [VERIFIED: command -v journalctl] | `257`. [VERIFIED: journalctl --version] | None on the target host. |
| `python3` | CLI runtime and stdlib lock implementation | ✓ [VERIFIED: command -v python3] | `3.13.5`. [VERIFIED: python3 --version] | Project floor is `>=3.11`; lower versions would need revalidation. [VERIFIED: pyproject.toml] |
| SQLite runtime | DB operations and vacuum | ✓ [VERIFIED: command -v sqlite3] | CLI `3.46.1`; Python binding `3.46.1`. [VERIFIED: sqlite3 --version + `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`] | None; SQLite is the locked store. [VERIFIED: AGENTS.md] |
| `ionice` / `nice` | Low-priority service execution | ✓ [VERIFIED: command -v ionice + command -v nice] | `nice 9.7`; `ionice` present. [VERIFIED: nice --version + command -v ionice] | systemd `Nice=` can still lower CPU priority even if `ionice` were unavailable, but that fallback is not needed on this host. [VERIFIED: man systemd.exec][ASSUMED] |
| `pytest` / `uv` | Validation workflow | ✓ [VERIFIED: command -v pytest + command -v uv] | `pytest 8.3.5`; `uv 0.11.21`. [VERIFIED: pytest --version + uv --version] | None needed. |

**Missing dependencies with no fallback:**
- None. [VERIFIED: command availability checks above]

**Missing dependencies with fallback:**
- None on this host. [VERIFIED: command availability checks above]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 8.3.5`. [VERIFIED: pytest --version] |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]`. [VERIFIED: pyproject.toml] |
| Quick run command | `pytest -q -x tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py` once those Wave 0 files exist. [VERIFIED: tests/ + pyproject.toml][ASSUMED] |
| Full suite command | `pytest -q`. [VERIFIED: pyproject.toml] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPER-01 | Unit files exist, reference the intended commands, and use oneshot semantics. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest -q tests/test_systemd_units.py::test_collect_units_exist -x` | ❌ Wave 0 |
| OPER-02 | Collect service carries low CPU and I/O priority settings. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest -q tests/test_systemd_units.py::test_collect_priority_settings -x` | ❌ Wave 0 |
| OPER-03 | Concurrent writer attempts fail fast without duplicate/corrupt snapshots. [VERIFIED: .planning/REQUIREMENTS.md] | unit/integration | `pytest -q tests/test_ops_locking.py::test_collect_lock_conflict_fails_fast -x` | ❌ Wave 0 |
| OPER-04 | Retention keeps the right per-root tiers, deletes whole snapshots, and removes orphan `paths`. [VERIFIED: .planning/REQUIREMENTS.md] | unit/integration | `pytest -q tests/test_ops_retention.py::test_prune_keeps_hourly_daily_monthly_and_gcs_paths -x` | ❌ Wave 0 |
| OPER-05 | Vacuum path acquires the same lock and fails visibly when the DB is busy. [VERIFIED: .planning/REQUIREMENTS.md] | unit/integration | `pytest -q tests/test_ops_vacuum.py::test_vacuum_requires_writer_lock -x` | ❌ Wave 0 |
| OPER-06 | Docs reference the real DB path, timer names, retention windows, and verification commands. [VERIFIED: .planning/REQUIREMENTS.md] | unit/manual | `pytest -q tests/test_systemd_units.py::test_docs_reference_live_artifacts -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest -q -x tests/test_ops_locking.py tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py` once added. [VERIFIED: tests/][ASSUMED]
- **Per wave merge:** `pytest -q`. [VERIFIED: pyproject.toml]
- **Phase gate:** Full suite green before `$gsd-verify-work`. [VERIFIED: .planning/config.json]

### Wave 0 Gaps

- [ ] `tests/test_ops_locking.py` — covers OPER-03.
- [ ] `tests/test_ops_retention.py` — covers OPER-04 and orphan-path GC.
- [ ] `tests/test_ops_vacuum.py` — covers OPER-05.
- [ ] `tests/test_systemd_units.py` — covers OPER-01, OPER-02, and OPER-06.
- [ ] A stable fixture/helper for synthetic multi-root snapshot timelines and retention buckets.
- [ ] The current full suite is not green: `pytest -q` failed on `tests/test_diagnostics_docker.py::test_collect_indexed_docker_path_hints_resolves_via_dictionary_join` (1 failed, 228 passed). [VERIFIED: pytest -q]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local system service; no end-user auth surface is introduced in this phase. [VERIFIED: 04-CONTEXT.md + AGENTS.md] |
| V3 Session Management | no | No session layer exists in the CLI/service model. [VERIFIED: src/watchdirs/cli.py + AGENTS.md] |
| V4 Access Control | yes | Keep the service least-privileged in unit configuration and avoid shell interpolation in `ExecStart=` lines. [VERIFIED: man systemd.service + man systemd.exec][ASSUMED] |
| V5 Input Validation | yes | Reuse existing `argparse` and TOML/path validation patterns for any new commands or config knobs. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/config.py] |
| V6 Cryptography | no | This phase does not add crypto. [VERIFIED: 04-CONTEXT.md + src/watchdirs/] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Lock bypass via manual CLI path | Tampering | Put the lock inside the Python writer commands, not only in systemd wrapper units. [VERIFIED: src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/fcntl.html] |
| Silent missed runs | Repudiation | Non-blocking lock failure plus journal-visible non-zero exit and documented `journalctl` checks. [VERIFIED: 04-CONTEXT.md + man systemd.exec] |
| Shell injection in service files | Elevation of Privilege | Use direct `ExecStart=` argv, no `sh -c`, and explicit config/DB paths. [VERIFIED: man systemd.service][ASSUMED] |
| DB corruption or busy failures from concurrent writers/checkpoints | Tampering / Denial of Service | One writer lock plus off-peak vacuum cadence. [VERIFIED: 04-CONTEXT.md + sqlite3 --version][CITED: https://www.sqlite.org/wal.html] |
| Over-retention of deleted evidence in the DB file | Information Disclosure | Use explicit prune plus periodic `VACUUM`; SQLite documents that deleted content may remain recoverable until vacuumed or `secure_delete` is enabled. [CITED: https://www.sqlite.org/lang_vacuum.html] |

## Sources

### Primary (HIGH confidence)
- `AGENTS.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/phases/04-scheduled-retention-operations/04-CONTEXT.md` - locked scope, requirements, and project constraints. [VERIFIED: AGENTS.md + .planning/REQUIREMENTS.md + .planning/STATE.md + .planning/ROADMAP.md + .planning/phases/04-scheduled-retention-operations/04-CONTEXT.md]
- `src/watchdirs/cli.py`, `src/watchdirs/config.py`, `src/watchdirs/db/connection.py`, `src/watchdirs/db/migrations.py`, `src/watchdirs/db/schema.sql`, `src/watchdirs/bench/duration.py` - current seams, PRAGMAs, and retention-relevant schema details. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/config.py + src/watchdirs/db/connection.py + src/watchdirs/db/migrations.py + src/watchdirs/db/schema.sql + src/watchdirs/bench/duration.py]
- Installed man pages: `man systemd.timer`, `man systemd.service`, `man systemd.exec`, `man flock`. [VERIFIED: man systemd.timer + man systemd.service + man systemd.exec + man flock]
- Host/runtime commands: `systemctl --version`, `journalctl --version`, `sqlite3 --version`, `python3 --version`, `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`, `pytest --version`, `uv --version`, `pytest -q`. [VERIFIED: command outputs]

### Secondary (MEDIUM confidence)
- Python `fcntl` docs - lock semantics and non-blocking error behavior. [CITED: https://docs.python.org/3/library/fcntl.html]
- SQLite `VACUUM` docs - reclaim/space/locking behavior. [CITED: https://www.sqlite.org/lang_vacuum.html]
- SQLite `PRAGMA auto_vacuum` docs - FULL vs incremental vs none. [CITED: https://www.sqlite.org/pragma.html#pragma_auto_vacuum]
- SQLite WAL docs - WAL persistence, busy cases, and the recent WAL-reset bug note. [CITED: https://www.sqlite.org/wal.html]
- SQLite foreign-key docs - `ON DELETE CASCADE` semantics. [CITED: https://www.sqlite.org/foreignkeys.html]

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - the stack is almost entirely locked or already present in the repo/runtime. [VERIFIED: AGENTS.md + pyproject.toml + systemctl --version + sqlite3 --version]
- Architecture: MEDIUM - the major seams are clear, but exact representative selection and timer split still need planning decisions. [VERIFIED: 04-CONTEXT.md][ASSUMED]
- Pitfalls: HIGH - the lock, orphan-path GC, and SQLite maintenance hazards are directly evidenced by the schema, docs, and live runtime. [VERIFIED: src/watchdirs/db/schema.sql + sqlite3 --version][CITED: https://www.sqlite.org/lang_vacuum.html][CITED: https://www.sqlite.org/wal.html]

**Research date:** 2026-06-17
**Valid until:** 2026-06-24
