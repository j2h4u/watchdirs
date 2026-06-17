# watchdirs

`watchdirs` is a proposed local forensic tool for explaining disk space growth on `senbonzakura`.

The intended user is not primarily a human operator. The intended user is an agent that needs to answer, quickly and with evidence:

- what directory grew since the last known-good point in time;
- whether the growth is real disk usage or an artifact of hardlinks, mounts, or deleted-open files;
- where to drill down next without manually running broad `du` searches across the host.

## Origin

On 2026-06-12 the root filesystem appeared to jump from roughly `137G` used to around `170G` used. A live investigation found several contributors:

- Docker/BuildKit/containerd cache and image data had grown substantially.
- `docker system df` showed about `21.74G` of build cache, about `21.27G` reclaimable.
- `/var/lib/containerd` held tens of gigabytes of overlayfs snapshots.
- `~/.cache/uv` held about `25G`, mostly Python package archives related to heavy `dotmd/backend/.venv` dependencies such as `torch`, `triton`, `nvidia-cu13`, and `cudnn`.
- `/opt/docker/context-gateway/logs/` held several gigabytes, especially `compression.jsonl`.

After running:

```bash
docker builder prune -af
docker image prune -f
uv cache prune
```

free space improved from about `20G` to about `45G`. That confirmed the cleanup path, but it did not solve the deeper operational problem: the system lacked a historical explanation of which directory trees grew between "yesterday" and "now".

## Problem

Traditional disk investigation is reactive:

```bash
df -h /
du -xhd1 /home /var /opt /srv
docker system df -v
find ... -size +100M
```

This works, but it is slow and manual. It also only sees the current state. When the operator says "yesterday it was 137G, today it is 170G", the useful question is not simply "what is large now?" but:

- what changed between two points in time;
- what grew fastest;
- what disappeared;
- what moved from reclaimable cache to active data;
- why `df` and `du` might disagree.

The desired system should periodically record enough information to make these investigations cheap.

## Non-Goals

- Do not build a UI-first disk visualizer.
- Do not continuously monitor every filesystem event with inotify.
- Do not store every file as a permanent indexed row by default.
- Do not introduce a large database service for this.
- Do not scan virtual filesystems such as procfs, sysfs, devfs, cgroupfs, or transient namespace mounts.

## Ready-Made Tools Considered

### duc

`duc` is the closest existing tool. It indexes disk usage into a database and can inspect or visualize the result.

Reference: <https://duc.zevv.nl/>

Pros:

- purpose-built for disk usage indexing;
- mature sysadmin-style tool;
- supports CLI and visual inspection;
- available in Debian.

Cons:

- primarily answers "what does this index contain now?";
- historical diff between yesterday's and today's directory sizes is not the primary built-in workflow;
- would likely still need wrapper logic for timestamped indexes, retention, and agent-friendly JSON diff output.

### agedu

`agedu` helps find old data consuming disk space.

Reference: <https://www.tecmint.com/agedu-track-disk-space-usage-in-linux/>

Pros:

- useful for cleaning old cold data;
- gives a different view than plain `du`.

Cons:

- optimized around age of data, not sudden growth between snapshots;
- not ideal for "where did 30G appear since yesterday?"

### ncdu, gdu, dua

These are useful interactive disk usage viewers.

Pros:

- excellent for manual inspection;
- fast and familiar.

Cons:

- not historical;
- not agent-first;
- do not provide the desired snapshot diff model by themselves.

### Telegraf / Prometheus / Grafana

Directory sizes can be exported through custom scripts or plugins such as Telegraf `exec` or file-count style inputs.

Pros:

- integrates with existing observability systems;
- good for a small allowlist of known directories.

Cons:

- scanning all directories creates high-cardinality path labels;
- stale paths and deleted directories become awkward time series;
- "diff two snapshots by path and sort by delta" is easier in SQL than in metrics tooling;
- better suited for alerting on known surfaces than forensic discovery across the host.

## Recommended Direction

Build a small Python tool that stores directory-only snapshots in SQLite.

The key design choice is directory aggregates, not file inventory. The host may contain hundreds of thousands of files, but the investigation usually needs to know which directory subtree grew. Once a suspicious directory is identified, an agent can run an on-demand drill-down inside that subtree.

This keeps persistent state small while still answering the important question.

## Why Not Store Every File?

Permanent file-level indexing is probably overkill for this host.

If there are 1,000 relevant directories and 500,000 files, storing every file on every snapshot increases database size, write time, retention complexity, and noise. Most investigations do not start by needing a list of individual files. They need the growth frontier:

```text
/35G /var/lib/containerd
 +22G /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs
  +20G /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots
```

At that point the agent can do a targeted, temporary file-level scan in the suspicious subtree.

Possible future hybrid:

- frequent directory snapshots;
- optional one-shot file scan for a path;
- optional daily/weekly file inventory only if real incidents prove it necessary.

Do not start with permanent full file indexing.

## Storage Choice

### SQLite

SQLite is the recommended primary store.

Why:

- one local file;
- no service to operate;
- available everywhere;
- excellent for snapshot tables and path-based joins;
- simple TTL through deleting old snapshot IDs;
- supports indexes, transactions, and `VACUUM`;
- enough capacity for this workload by a very large margin.

Official SQLite limits are far above this use case: <https://sqlite.org/limits.html>

The central query is relational, not graph-native:

```sql
SELECT
  curr.path,
  curr.disk_bytes - COALESCE(prev.disk_bytes, 0) AS delta_bytes,
  prev.disk_bytes AS before_bytes,
  curr.disk_bytes AS after_bytes
FROM directory_sizes AS curr
LEFT JOIN directory_sizes AS prev
  ON prev.path = curr.path
 AND prev.snapshot_id = :previous_snapshot
WHERE curr.snapshot_id = :current_snapshot
ORDER BY delta_bytes DESC
LIMIT 50;
```

This is exactly what SQLite is good at.

### DuckDB

DuckDB is excellent for embedded analytics and could be useful for offline exploration or querying exported Parquet.

Reference: <https://duckdb.org/why_duckdb.html>

It is not the first choice for the operational database because this tool needs a small local write target for periodic systemd collection, not an OLAP analytics environment.

### Time-Series DB

An embedded time-series DB is not a good fit.

The data looks like time series superficially, but the primary operation is a snapshot diff across paths. Time-series systems make path churn and deleted directories awkward, and using full paths as labels creates cardinality problems.

### Embedded Graph DB

Graph databases such as Kuzu or multi-model systems such as SurrealDB were considered.

Kuzu reference: <https://kuzudb.github.io/docs>  
SurrealDB embedded reference: <https://surrealdb.com/docs/build/embedding/by-language/rust>

Filesystem data is tree-shaped, so graph storage is conceptually tempting. But the required queries are not graph-heavy:

- compare snapshot A to snapshot B by path;
- sort by delta;
- show deleted and created paths;
- drill down by parent path.

SQLite can represent the tree with `path`, `parent_path`, `name`, and `depth` without needing a graph engine. A graph or multi-model database would add runtime and operational complexity without making the core diff query simpler.

Recommendation: do not use graph storage for the first implementation.

## Proposed Data Model

```text
snapshots
  id INTEGER PRIMARY KEY
  started_at TEXT NOT NULL
  finished_at TEXT
  root_path TEXT NOT NULL
  status TEXT NOT NULL
  notes TEXT
  error TEXT

directory_sizes
  snapshot_id INTEGER NOT NULL
  path TEXT NOT NULL
  parent_path TEXT
  name TEXT NOT NULL
  depth INTEGER NOT NULL
  apparent_bytes INTEGER NOT NULL
  disk_bytes INTEGER NOT NULL
  file_count INTEGER NOT NULL
  dir_count INTEGER NOT NULL
  error TEXT
  PRIMARY KEY (snapshot_id, path)
```

Suggested indexes:

```sql
CREATE INDEX directory_sizes_path_snapshot_idx
  ON directory_sizes(path, snapshot_id);

CREATE INDEX directory_sizes_snapshot_size_idx
  ON directory_sizes(snapshot_id, disk_bytes);

CREATE INDEX directory_sizes_snapshot_parent_idx
  ON directory_sizes(snapshot_id, parent_path);
```

## Size Semantics

Store at least two size values:

- `apparent_bytes`: logical file sizes, equivalent to summing `st_size`;
- `disk_bytes`: physical allocation, equivalent to summing `st_blocks * 512`.

For disk pressure investigations, `disk_bytes` is the primary signal because it better matches `df`.

Directory rows should be recursive aggregates. A path row answers: "how much disk space is under this directory tree in this snapshot?"

## Hardlinks

Hardlinks are a correctness trap.

If a file has multiple paths but the same `(device, inode)`, counting it once per path can exaggerate physical usage. A `du`-like scanner usually avoids double-counting hardlinked files within a single traversal.

Recommended first implementation:

- use `du`-compatible semantics for `disk_bytes` if relying on `du`;
- if implementing native Python traversal, deduplicate `(st_dev, st_ino)` for physical bytes within one snapshot;
- optionally record a warning count for hardlinked files seen.

Important caveat: attribution is still imperfect. If one hardlinked inode appears in two directories, physical bytes may be attributed to whichever path the traversal sees first. For high-level growth detection this is acceptable, but the tool should not pretend hardlink attribution is mathematically perfect.

## Symlinks

Do not follow symlinks by default.

Store symlink metadata only if useful, but do not traverse through it. Following symlinks risks cycles and surprising scans outside the intended tree.

## Mounts and Virtual Filesystems

The scanner must skip virtual and transient filesystems.

Skip at least:

- `proc`
- `sysfs`
- `devtmpfs`
- `devpts`
- `tmpfs`, unless explicitly included
- `cgroup2`
- `pstore`
- `securityfs`
- `debugfs`
- `tracefs`
- `configfs`
- `fusectl`
- `nsfs`
- container overlay mount views

The scanner should read current mount information from `findmnt` or `/proc/self/mountinfo` and make an explicit decision for each mountpoint.

One design option:

- scan `/` as the main root;
- skip virtual filesystems;
- include real local filesystems by policy;
- treat tmpfs roots such as `/tmp` separately if desired.

Do not silently descend into container overlay views or namespace mounts.

## Deleted Paths

Deleted directories should remain queryable while their snapshot is retained.

This is not database garbage. It is historical evidence.

The correct retention model is snapshot TTL:

- every `directory_sizes` row belongs to a `snapshot_id`;
- old snapshots are deleted as a whole;
- deleted paths naturally disappear once all snapshots containing them expire.

Diff behavior:

- path exists in current but not previous: created or newly included;
- path exists in previous but not current: deleted or excluded;
- path exists in both: compare size delta.

## Deleted-Open Files

A known gap in directory scanning: `df` can show disk usage that `du` cannot find if a process holds an open file that has been deleted.

The tool should include a separate diagnostic command or collector for this condition:

```bash
lsof +L1
```

or a `/proc/*/fd`-based scan.

This should not be mixed into normal directory rows, but reports should call it out when `df` and indexed directory totals diverge substantially.

## Docker and Containerd Enrichment

Filesystem snapshots can identify `/var/lib/docker` and `/var/lib/containerd` growth, but agents benefit from structured Docker context.

Useful enrichment commands:

```bash
docker system df -v
docker builder du
docker image ls --filter dangling=true
```

These should be collected as auxiliary evidence, not as the primary storage model.

## Retention Policy

Phase 4 ships whole-snapshot retention with these defaults:

- keep all hourly snapshots for 14 days;
- keep one COMPLETE snapshot per UTC day for the next 90 days;
- keep one COMPLETE snapshot per UTC month beyond that.

Prune by deleting whole snapshots, not individual `directory_sizes` rows. SQLite
foreign-key cascades remove snapshot-owned rows, and watchdirs garbage-collects
orphaned `paths` entries after pruning.

`watchdirs vacuum` stays separate from `watchdirs prune`. Prune enforces the
retention policy; vacuum is the slower SQLite maintenance path that can reclaim
pages after pruning.

If the database grows too quickly in real operation, reduce the hourly window
before reducing snapshot fidelity.

## Scheduling

Use systemd timers rather than cron.

Repo-owned units live under `ops/systemd/`:

- `watchdirs-collect.service` and `watchdirs-collect.timer`
- `watchdirs-prune.service` and `watchdirs-prune.timer`
- `watchdirs-vacuum.service` and `watchdirs-vacuum.timer`
- `watchdirs-query.socket` and `watchdirs-query@.service`

The shipped service commands assume these host paths:

- command: `/usr/local/bin/watchdirs`
- config: `/etc/watchdirs/watchdirs.toml`
- database: `/var/lib/watchdirs/watchdirs.sqlite3`
- query socket: `/run/watchdirs/query.sock`

Before enabling timers, verify the command exists where the units expect it:

```bash
test -x /usr/local/bin/watchdirs
/usr/local/bin/watchdirs --help
```

Timer and query behavior:

- collect runs hourly with `Persistent=true`;
- prune runs daily at `00:17:00` with `RandomizedDelaySec=300`;
- vacuum runs weekly off-peak as a separate maintenance cadence.
- unprivileged read-only report commands use the same `/usr/local/bin/watchdirs`
  CLI and proxy through `watchdirs-query.socket` when no explicit `--db` is
  supplied.

All three scheduled services are `Type=oneshot` and intentionally run as
background work: `Nice=19`, `CPUSchedulingPolicy=idle`, `CPUWeight=idle`,
`IOSchedulingClass=idle`, and `IOWeight=1`. They share the same writer lock
boundary through the selected SQLite database path.

The query socket is a narrow local control surface: the SQLite database remains
root-owned under `/var/lib/watchdirs`, while approved local users connect through
`/run/watchdirs/query.sock` for `top`, `diff`, `report`, `deleted`,
`explain-path`, and `df-vs-index`. It does not expose `collect`, `prune`,
`vacuum`, arbitrary database paths, or a separate public CLI.

Advisory pre-deployment validation on a systemd host:

```bash
systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer ops/systemd/*.socket
```

## Agent-Facing Commands

The CLI is optimized for machine and agent use:

```bash
systemctl list-timers 'watchdirs-*'
systemctl status watchdirs-collect.timer watchdirs-prune.timer watchdirs-vacuum.timer watchdirs-query.socket
journalctl -u watchdirs-collect.service -u watchdirs-prune.service -u watchdirs-vacuum.service -u 'watchdirs-query@*'
/usr/local/bin/watchdirs
/usr/local/bin/watchdirs report --json
/usr/local/bin/watchdirs diff --json
/usr/local/bin/watchdirs report --since 24h --json
/usr/local/bin/watchdirs prune --db /var/lib/watchdirs/watchdirs.sqlite3 --json
/usr/local/bin/watchdirs vacuum --db /var/lib/watchdirs/watchdirs.sqlite3 --json
```

These are the core Phase 4 operations surface: regular collection, retention
pruning, and explicit SQLite maintenance. Cleanup orchestration remains out of
scope.

Common read-only commands have host-friendly defaults:

- `watchdirs` is shorthand for `watchdirs top --snapshot latest`;
- `watchdirs report`, `watchdirs diff`, `watchdirs deleted`, and
  `watchdirs explain-path PATH` default `--since` to `24h`;
- unprivileged users do not need `--db` for the host database because the CLI
  proxies read-only commands through `/run/watchdirs/query.sock`.

## Typical Investigation Flow

1. Agent sees `df` growth or operator asks "where did space go?"
2. Agent runs:

   ```bash
   watchdirs report --since 24h --json
   ```

3. Report identifies top growth paths.
4. If Docker/containerd paths appear, agent runs Docker enrichment.
5. If indexed total and `df` disagree, agent checks deleted-open files.
6. Agent drills down into the largest growing path.
7. Agent recommends cleanup only after classifying the growth source.

## Open Design Questions

- Should the first implementation use `du` output or native Python `os.scandir()` traversal?
- Should tmpfs roots such as `/tmp` be included as a separate scan root?
- How often is hourly scanning acceptable on this SSD?
- Should daily cleanup automatically run `watchdirs collect` before and after cleanup?
- Should context-gateway logs get their own logrotate policy independent of watchdirs?
- Should Docker enrichment be stored in SQLite or kept as separate report-time evidence?

## Current Recommendation

Build the first version as:

- Python CLI;
- SQLite database;
- directory-only recursive snapshots;
- no symlink following;
- hardlink-aware physical byte counting;
- mountpoint filtering;
- systemd timer;
- JSON-first diff/report commands;
- retention by snapshot TTL.

Do not start with SurrealDB, Kuzu, DuckDB, Prometheus, Influx, or permanent file-level indexing. Those add complexity before proving that the simple snapshot model is insufficient.
