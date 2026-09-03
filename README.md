# watchdirs

**Local forensic snapshots for explaining Linux disk space growth.**

`watchdirs` helps answer a specific operations question: “what changed on this
host, and why is the disk fuller than it was yesterday or last week?” It keeps
periodic recursive directory aggregate snapshots, then gives an operator or an
agent a bounded JSON report of likely growth contributors.

It is not a UI disk visualizer and it is not a permanent per-file inventory.
The production shape is deliberately small: a local CLI, systemd timers, one
SQLite database, and an optional read-only query socket for unprivileged
investigation commands.

## Why this exists

Manual disk-pressure investigations usually start with `df`, `du`,
Docker/cache commands, and ad-hoc `find` scans. That works for the current
state, but it is weak when the real question is historical:

> “Two days ago the root filesystem used much less space. Which directory trees
> grew since then?”

`watchdirs` records enough history to compare directory aggregates across
snapshots. An agent can start from a compact report, then drill into only the
paths that matter instead of sweeping the whole host blindly.

## What it tracks

- Recursive directory aggregate sizes.
- Apparent bytes and disk bytes; disk bytes are the main disk-pressure signal.
- Hardlink-sensitive accounting metadata.
- Created, deleted, grown, and shrunk paths across snapshots.
- Material burst growth, so sudden meaningful growth can outrank slow drift.
- Path relocation/churn signals, so moving files within the same filesystem is
  not confused with new disk pressure.
- `df` versus indexed directory reconciliation.
- Deleted-open files that may explain `df`/directory mismatches.
- Docker/containerd enrichment for common storage-growth surfaces.

The scanner skips virtual and transient filesystems such as `/proc`, `/sys`,
`/dev`, `/run`, tmpfs mounts, cgroups, and container overlay views by default.

## Operator workflow

On an installed host, start here:

```bash
watchdirs investigate
```

That command is the normal first pass for agents. It emits JSON with:

- current snapshot and storage metadata;
- ranked growth contributors;
- disk-pressure interpretation;
- relocation/churn suspects;
- blind spots;
- exact suggested next commands.

Then drill into the paths it recommends:

```bash
watchdirs explain-path /path/from/investigate --depth 3
watchdirs df-vs-index
watchdirs deleted-open-files
watchdirs docker-enrichment
```

Agent-operators should not need to know where the database lives. Normal
read-only commands use the host’s configured production storage automatically
and proxy through `/run/watchdirs/query.sock` when the systemd query socket is
available.

Useful status checks:

```bash
watchdirs stats --json
systemctl list-timers 'watchdirs-*'
systemctl status watchdirs-collect.timer watchdirs-prune.timer watchdirs-vacuum.timer watchdirs-query.socket
journalctl -u watchdirs-collect.service -u watchdirs-prune.service -u watchdirs-vacuum.service -u 'watchdirs-query@*'
/usr/local/bin/watchdirs investigate
```

## Installation on a host

The repository ships systemd units under `ops/systemd/` and an installer that
copies the current checkout launcher to `/usr/local/bin/watchdirs`.

```bash
sudo scripts/install-systemd-units.sh --restart-query-socket --clean-pycache
```

The installed service layout is:

- command: `/usr/local/bin/watchdirs`
- config: `/etc/watchdirs/watchdirs.toml`
- database: `/var/lib/watchdirs/watchdirs.sqlite3`
- query socket: `/run/watchdirs/query.sock`

Verify the units before installation or after editing them:

```bash
test -x /usr/local/bin/watchdirs
/usr/local/bin/watchdirs --help
systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer ops/systemd/*.socket
```

Enable/start the timers and query socket with normal `systemctl` commands for
the target host policy.

Run writer jobs manually only when intentionally operating the service:

```bash
systemctl start watchdirs-collect.service
systemctl start watchdirs-prune.service
systemctl start watchdirs-vacuum.service
```

Refresh installed units from the checkout after changing service files:

```bash
sudo scripts/install-systemd-units.sh --restart-query-socket --clean-pycache
just clean-pycache
```

Cleanup orchestration remains out of scope for watchdirs itself and should stay
in the host's normal maintenance policy, not in these units.

## Scheduled operation

The shipped units run unattended:

- `watchdirs-collect.timer` records hourly snapshots.
- `watchdirs-prune.timer` applies whole-snapshot retention daily.
- `watchdirs-vacuum.timer` runs weekly SQLite maintenance.
- `watchdirs-query.socket` serves read-only local CLI requests.

Writer operations share one advisory lock. By default, `collect`, `prune`, and
`vacuum` wait up to `10800` seconds for the writer lock, so slow disks or long
maintenance runs do not immediately become missed snapshots. Manual writer
commands can override this with `--lock-timeout`; `0` keeps fail-fast behavior.

Scheduled jobs are intentionally background-friendly: the systemd units use idle
CPU/I/O priority settings so collection and maintenance stay low impact.

## Retention

Retention deletes whole snapshots, not individual directory rows:

- keep hourly COMPLETE snapshots for 3 days;
- keep RUNNING, PARTIAL, and FAILED diagnostic snapshots for 24 hours;
- keep one COMPLETE snapshot per UTC day for the next 90 days;
- keep one COMPLETE snapshot per UTC month beyond that.

`prune` enforces retention. `vacuum` is separate maintenance that can reclaim
SQLite pages after old snapshots are removed.

## Development

Requirements:

- Linux for full filesystem and systemd behavior.
- Python 3.11+.
- `uv`.

From a checkout:

```bash
uv run python -m watchdirs --help
uv run python -m watchdirs collect --config examples/host.watchdirs.toml --db ./watchdirs.sqlite3 --json
uv run python -m watchdirs investigate --db ./watchdirs.sqlite3
```

`--db` is a development, test, and maintenance override. It is not part of the
normal operator workflow.

Quality gates:

```bash
just check
just unit
just coverage
just deps-audit
```

During small development loops, prefer targeted checks first and reserve the
full gates for review or release confidence.

## Documentation

- [Documentation map](docs/README.md) — product, operations, development, and
  generated maintainer context.
- [Best practices](docs/BEST_PRACTICES.md) — QA, dependency, CI, and PR-release
  contract.
- [Operator CLI redesign](docs/operator-cli-redesign.md) — rationale for the
  current agent-facing CLI surface.
- [Persistent disk growth investigation report](docs/persistent-disk-growth-investigation-report-2026-08-05.md)
  — anonymized real-host investigation feedback.
- [Persistent growth investigation plan](docs/persistent-growth-investigation-plan.md)
  — implementation plan that led to the first-class investigation workflow.

## Non-goals

- A UI-first disk visualizer.
- Continuous filesystem event monitoring with inotify.
- Permanent file-level history for every file.
- A server database such as PostgreSQL for local host operation.
- Scanning virtual filesystems, transient runtime mounts, or container overlay
  views as if they were normal disk directories.
