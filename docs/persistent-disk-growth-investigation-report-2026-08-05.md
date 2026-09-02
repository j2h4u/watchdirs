# Persistent Disk Growth Investigation: Product Feedback Report

Date: 2026-08-05  
Environment: anonymized single-host Linux server  
Repository: `watchdirs`  
Audience: maintainers and agents planning product work on `watchdirs`

## Privacy note

This report is derived from a real host investigation, but hostnames, usernames,
repository names, application names, and server-specific paths have been
removed or generalized. Sizes and timelines are retained because they explain
the product gap; they should be treated as incident evidence, not as current
state for any particular machine.

## Executive summary

The operator's actual problem was not a sudden one-off disk incident. The
observed pattern was gradual capacity loss: free space appeared to fall by
roughly 1-2 GiB per day even after manual cleanup and aggressive backup pruning.
A large one-time import of repositories had happened earlier, but that could
not explain continuing daily loss.

`watchdirs` materially improved the investigation. Its retained directory
snapshots quickly identified the dominant seven-day growth surfaces without a
broad root-level `du` scan:

- local search/index state under the user's home directory: about +13.90 GiB;
- development repositories and worktrees under `~/repos`: about +3.41 GiB;
- container runtime state under `/var/lib/containerd`: about +2.61 GiB;
- user cache data under `~/.cache`: about +0.91 GiB;
- smaller contributors included agent history, application data, observability
  WAL files, package-manager cache, and Docker volumes.

The investigation exposed the central missing product capability: `watchdirs`
currently answers "what changed between two snapshots" much better than it
answers "which path is persistently consuming space every day." A large
one-time import, a new index generation, steady growth, periodic build bursts,
and grow-then-clean churn can all appear as positive endpoint deltas.

The highest-value next feature is therefore a first-class, agent-oriented
persistent-growth investigation workflow:

```bash
watchdirs investigate --since 14d --json
```

It should analyze a time series of retained snapshots, reconcile it with
historical filesystem capacity, classify growth shape, produce a Pareto
explanation, distinguish one-time jumps from steady daily growth, and show what
happened after the latest snapshot.

## User scenario

The operator approached the agent with approximately this request:

> Free disk space keeps falling. This is not just the last few hours; it has
> been happening over recent weeks. It may be losing one or two gigabytes every
> day. Run `watchdirs` and explain what regularly consumes the space.

This is the core product scenario to optimize for:

1. The operator notices a long-running downward trend in free capacity.
2. They do not know whether the cause is repositories, caches, Docker, logs,
   application state, deleted-open files, or something else.
3. They want the agent to start with historical evidence rather than generic
   cleanup advice.
4. They need the agent to separate one-time events from recurring growth.
5. They want a short causal verdict, followed by evidence and safe drill-down
   commands.

At a sustained 1 GiB/day, an additional 1 TiB lasts roughly 2.8 years. At
2 GiB/day it lasts roughly 1.4 years, before reserve space and legitimate data
growth. Capacity expansion alone is therefore not a substitute for attribution.

## Operational context

Relevant host facts at investigation time:

- Debian headless server, root filesystem on ext4.
- Docker and containerd workloads were active.
- Development agents, local repositories, backups, and persistent services ran
  on the same machine.
- `watchdirs` collected root-scoped snapshots hourly through systemd.
- The live database was `/var/lib/watchdirs/watchdirs.sqlite3`.
- Read-only access was available through the query socket for an unprivileged
  operator.
- Retention used hourly, daily, and monthly representatives.
- The root filesystem was repeatedly near capacity.
- A concurrent Docker Buildx operation temporarily changed free capacity by
  many gigabytes within minutes.

## Investigation workflow performed

The agent started with `watchdirs` rather than a broad whole-filesystem scan.
Useful commands and diagnostic surfaces included:

```bash
watchdirs snapshots --limit 20 --json
watchdirs report --since 24h --json
watchdirs report --since 7d --json
watchdirs diff --since 7d --json
watchdirs explain-path ~/.ctx --since 7d --depth 3 --json
watchdirs explain-path ~/repos --since 7d --depth 4 --json
watchdirs df-vs-index --json
watchdirs deleted-open-files --json
watchdirs docker-enrichment --json
```

After `watchdirs` identified the dominant paths, targeted live checks were still
required:

```bash
du -xhd2 PATH
find PATH -xdev -type f -size +100M ...
lsof +L1 -nP
docker system df
docker buildx du
df -hT /
```

This was better than starting with broad `du`, but it remained a multi-command
expert workflow. The desired product experience is one investigation command
that returns the causal summary and the highest-value next probes.

## Evidence from the seven-day report

The selected comparison covered about seven days. The report's positive
classifications showed approximately:

- 22.61 GiB of disk-byte growth in existing paths;
- 0.22 GiB in newly created paths;
- 1,254 grown paths and 5,388 created paths before frontier pruning.

The high-signal frontier was:

| Path category | Seven-day disk delta | Current disk size | Interpretation discovered later |
|---|---:|---:|---|
| Local search/index state | +13.90 GiB | 16.93 GiB | Index generations and temporary SQLite source snapshots |
| Development repositories | +3.41 GiB | 11.54 GiB | Worktrees, `.venv`, and `node_modules`, not source text |
| `/var/lib/containerd` | +2.61 GiB | 42.55 GiB | Container runtime and build-related data |
| `~/.cache` | +0.91 GiB | 13.86 GiB | Package, model, browser, and tool caches |
| `~/.local` | +0.44 GiB | 4.58 GiB | Local tooling and environments |
| Agent session history | +0.29 GiB | 3.67 GiB | Retained local agent session data |
| Root-owned npm cache | +0.21 GiB | 3.07 GiB | Package-manager cache created by privileged tasks |
| Application data under `/srv` | +0.20 GiB | 4.28 GiB | Legitimate persistent application data |
| Observability WAL | +0.15 GiB | 0.48 GiB | Remote-write buffering |

This was valuable evidence, but it did not say whether each delta was steady,
bursty, or a one-time creation.

## Drill-down findings

### Repository growth was not source text

Repository storage grew by about 3.41 GiB on disk. Most of the growth came from
active worktrees and dependency environments:

- worktree directories created during the period;
- multiple worktrees with separate `node_modules`;
- Python `.venv` directories;
- `.mypy_cache` directories;
- local pre-clone or backup directories left by development workflows.

The `.git` and source-code portions were comparatively small. Directory names
alone were insufficient: a directory called `repos` is not primarily text once
worktrees and dependency environments accumulate inside it.

No repository cleanup was performed during this investigation. Worktrees and
environments may be owned by active agents and require coordination.

### Cache inventory

At investigation time, `~/.cache` was about 14 GiB.

| Cache category | Approximate size | Last content modification observed | Meaning |
|---|---:|---|---|
| Python package/environment cache | 7.0 GiB | recent | Actively used; hardlink semantics matter |
| Model cache | 2.9 GiB | older | Downloaded machine-learning model weights |
| Browser automation cache | 1.3 GiB | older | Downloaded browser binaries |
| Vulnerability database cache | 1.2 GiB | older | Regenerable vulnerability database |
| E2E browser cache | 622 MiB | recent | Browser binaries used by tests |
| Backup client cache | 542 MiB | recent | Useful for backup performance |
| JavaScript package-manager cache | 330 MiB | older | Package-manager metadata/cache |
| Active tool cache | 168 MiB | recent | Runtime cache for local tooling |
| Tool-installer cache | 105 MiB | older | Regenerable installer cache |

After exact inventory and explicit operator confirmation, the investigation
removed only selected regenerable host caches. Active package caches, backup
caches, local search/index state, and repository data were not removed.

Important semantic warning: some package caches may be hardlinked into
environment directories. Apparent `du` totals can look duplicated, and deletion
does not necessarily reclaim the sum of all apparent sizes. Future cache
recommendations must distinguish apparent size from physically reclaimable
bytes.

### Local search/index state was the largest growth surface

The largest growth surface was local search/index state under the user's home
directory. Read-only evidence showed:

- about 17 GiB total live size;
- about 7.5 GiB in temporary provider SQLite snapshots;
- about 8.0 GiB in lexical search state;
- about 7.4 GiB in generated lexical index data;
- a primary relational SQLite database of about 1.6 GiB;
- an empty primary SQLite WAL at inspection time.

No search/index files were deleted or changed in this investigation because
that state belonged to a separate tool boundary.

### Docker and current-vs-snapshot drift

During the investigation, another process launched a large Docker
Compose/Buildx operation. Free capacity changed rapidly:

- after backup compaction, about 11 GiB was free;
- roughly ten minutes later, only about 2.9 GiB was free;
- build cache and image state changed while the investigation continued;
- later cleanup and reclamation returned free capacity into the teens.

This exposed an important gap: the latest hourly `watchdirs` snapshot could not
attribute a large write burst that occurred after collection. `df-vs-index`
could show a live discrepancy, but the workflow still required manual process
inspection to identify the active writer.

At one observation point, Docker reported approximately:

- images: 31.7 GiB, with about 11.6 GiB potentially reclaimable;
- containers: 2.26 GiB;
- local volumes: 10.54 GiB, with 1.62 GiB reported unused but not safe to delete
  without ownership inspection;
- Buildx cache: about 22 GiB, mostly or entirely active during the build.

No Docker cleanup was performed while the active build was running.

### Logs, `/tmp`, and deleted-open files were not dominant

Targeted checks found:

- `/tmp`: about 408 MiB;
- journald: tens of MiB, not GiB;
- non-runtime Docker configuration/bind data outside runtime layers: about
  2.2 GiB, mostly legitimate application data;
- deleted-open files: about 367 MiB, primarily binaries held by long-running
  agent-related processes.

These were not the primary explanation for the multi-gigabyte weekly trend.

## Product gap

The investigation should have been answerable by one read-only command:

```bash
watchdirs investigate --since 14d --json
```

Today the agent must manually combine:

- endpoint directory deltas;
- per-path drill-downs;
- live filesystem capacity;
- Docker enrichment;
- deleted-open files;
- ad hoc `du`, `find`, `lsof`, `docker`, and `df` commands;
- human judgement about one-time jumps vs recurring growth.

That is too much operational choreography for the core problem the tool exists
to solve.

## Product recommendations

### P0

1. Add historical filesystem-usage records
   - Store filesystem usage alongside snapshots or in a related table.
   - Preserve source path, mount point, filesystem type, total bytes, used
     bytes, available bytes, and capture errors.
   - This lets `watchdirs` compare directory growth against actual `df`
     pressure over time.

2. Add multi-snapshot trend metrics
   - Analyze all retained snapshots in the requested window, not only baseline
     and endpoint.
   - Compute net delta, gross positive delta, gross negative delta, daily
     slope, volatility, first appearance, last growth, peak size, current size,
     and sample count.

3. Implement `watchdirs investigate --since --json`
   - Return a short verdict first.
   - Rank frontier path categories by contribution to persistent growth.
   - Include confidence, evidence window, and known blind spots.
   - Recommend read-only next probes.

4. Classify growth shape deterministically
   - Suggested labels: `steady_growth`, `one_time_jump`, `bursty_growth`,
     `grow_then_clean`, `current_burst_after_latest_snapshot`,
     `stable_large`, and `unknown_insufficient_samples`.

5. Include current-vs-index drift
   - If live `df` pressure is materially worse than the latest snapshot,
     report that the active writer may be newer than the retained index and
     surface Docker/deleted-open/process-oriented next probes.

### P1

1. Add multi-window comparison
   - Compare 24h, 7d, and requested windows in one output.
   - This highlights "large over a week but quiet today" versus "currently
     growing."

2. Improve Pareto drill-down
   - For each top-level frontier, show child contributors.
   - Preserve path-category evidence without requiring the reader to parse a
     huge raw diff.

3. Add compaction and reclaimability warnings
   - Flag hardlink-sensitive caches and runtime stores where apparent bytes may
     not equal reclaimable bytes.
   - Keep cleanup advice explicitly non-destructive.

4. Compact Docker and deleted-open summaries
   - Include only high-signal totals and warnings in `investigate`.
   - Leave destructive Docker cleanup outside `watchdirs`.

### P2

1. Add `watchdirs inspect-cold PATH`
   - Find old, large subtrees inside a chosen path.
   - This complements historical deltas with current cold-data inventory.

2. Add cache recognizers
   - Classify common cache families as regenerable, active, hardlink-sensitive,
     or coordination-required.
   - Recognizers should produce warnings, not deletion commands.

3. Emit "next-check commands" only
   - Commands should be read-only unless an operator explicitly asks for cleanup
     outside `watchdirs`.

## Design boundaries

- Keep collection, query, analysis, diagnostics, and rendering separable.
- SQLite remains appropriate for v1.
- Do not add permanent per-file history.
- Do not make `watchdirs` a cleanup tool.
- Do not silently cross filesystem boundaries.
- Keep JSON first-class; human-readable rendering is secondary.
- Query-socket `investigate` must stay read-only.

## Acceptance criteria for the next product increment

- `watchdirs investigate --since 14d --json` produces one top-level verdict,
  ranked growth contributors, growth-shape labels, and read-only next probes.
- The command uses multiple snapshots across the window, not just endpoint
  deltas.
- Filesystem-capacity history is recorded and surfaced in the result.
- Output distinguishes persistent growth, one-time jumps, grow-then-clean churn,
  and current-vs-index drift.
- The query socket can serve the investigation result without writer access.
- Tests cover deterministic classification and JSON schema stability.
