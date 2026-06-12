# Walking Skeleton - watchdirs

**Phase:** 1
**Generated:** 2026-06-12

## Capability Proven End-to-End

An agent can run `./watchdirs collect --config <file> --db <file> --json` or `PYTHONPATH=src python3 -m watchdirs collect --config <file> --db <file> --json`, scan configured roots with native filesystem traversal, and persist trustworthy directory aggregate snapshot evidence in SQLite.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Framework | Stdlib-first Python CLI using `argparse` | Phase 1 needs a local forensic command, not an application framework, and the target host does not require runtime package installs. |
| Data layer | SQLite via stdlib `sqlite3`, schema versioned with `PRAGMA user_version` | Matches the single-file operational store and later path-diff SQL workload. |
| Auth | None | `watchdirs` is a local single-user CLI; filesystem access remains governed by OS permissions. |
| Deployment target | Local repo execution with repo-local `./watchdirs` and `PYTHONPATH=src python3 -m watchdirs`; verification does not require `pip` | The host currently lacks `pip`, so Phase 1 must remain runnable without install bootstrap while leaving D-18 systemd-managed state/cache directories for the later service-install phase. |
| Directory layout | `src/watchdirs` package, `collect/` for traversal and mount policy, `db/` for SQLite, `tests/` for pytest contracts | Mirrors the Phase 1 pattern map and keeps CLI/config, mount classification, traversal/aggregation, and persistence separate. |
| Configuration | TOML config file plus CLI overrides for config path, database path, notes, JSON output, and mountinfo source | Configured roots stay outside code and test runs can use temporary roots without hidden host constants. |
| Filesystem semantics | Native `os.scandir()` traversal, `stat(follow_symlinks=False)`, hardlink dedup by `(st_dev, st_ino)`, and `/proc/self/mountinfo` classification | Implements the locked filesystem safety and disk-byte correctness decisions directly. |

## Stack Touched in Phase 1

- [x] Project scaffold: `src/watchdirs`, `pyproject.toml`, and pytest configuration that works without `pip` installs.
- [x] Routing: `./watchdirs collect` command dispatch plus `python -m watchdirs` module fallback.
- [x] Database: one real SQLite write path for `snapshots` and `directory_sizes`, plus readback assertions in tests.
- [x] Interaction: CLI flags `collect --config --db --json --notes --mountinfo` wired to config, traversal, and persistence.
- [x] Local run: `./watchdirs collect --config examples/senbonzakura.watchdirs.toml --db /tmp/watchdirs.sqlite3 --json`.
- [x] Module fallback: `PYTHONPATH=src python3 -m watchdirs collect --config examples/senbonzakura.watchdirs.toml --db /tmp/watchdirs.sqlite3 --json`.

## Out of Scope (Deferred to Later Slices)

- Growth diff, report, top, deleted, and explain-path commands.
- Deleted-open-file diagnostics and `df` reconciliation.
- Docker/containerd enrichment.
- systemd unit installation, priority controls, retention pruning, locking, and vacuum maintenance.
- Permanent file-level inventory and UI-first visualization.

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering these architectural decisions:

- Phase 2: Agents can compare snapshots and surface growth frontiers as JSON.
- Phase 3: Agents can reconcile indexed growth with `df`, deleted-open files, and Docker/containerd evidence gaps.
- Phase 4: Operators can schedule, retain, prune, and verify collection unattended with systemd.
