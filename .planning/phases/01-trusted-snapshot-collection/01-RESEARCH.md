# Phase 1: Trusted Snapshot Collection - Research

**Researched:** 2026-06-12
**Domain:** Python CLI filesystem traversal with SQLite-backed snapshot storage on Linux [VERIFIED: python3 --version + sqlite3 --version + https://docs.python.org/3/library/os.html + https://docs.python.org/3/library/sqlite3.html]
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
Verbatim from `01-CONTEXT.md`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Scanner Engine
- **D-01:** Use a native Python scanner built around `os.scandir()`/`DirEntry`/`stat(follow_symlinks=False)` as the primary collection engine. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-02:** Treat `du` as a verification oracle and troubleshooting comparison, not as the primary data source. Tests and manual diagnostics should compare selected subtrees against `du -x`-style semantics where practical. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-03:** The scanner must compute both `apparent_bytes` from logical size and `disk_bytes` from allocated blocks. `disk_bytes` is the primary disk-pressure signal. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-04:** Deduplicate physical bytes by `(st_dev, st_ino)` within a snapshot for hardlinked files. Attribute the counted bytes to the first path encountered and document that hardlink attribution is traversal-order dependent. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Root and Mount Policy
- **D-05:** Use README.md as the bootstrap/canonical design note for root and mount policy. The README already captures the pain point and open design questions. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-06:** `collect` should operate from configured roots, not from an implicit broad host scan hidden in code. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-07:** Provide a sensible local sample/default for the target host: scan `/` as one filesystem, and allow explicit additional roots when the operator wants separate mount coverage. Avoid overlapping roots by default. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-08:** Read live mount information from `/proc/self/mountinfo` or `findmnt` and classify every mountpoint explicitly. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-09:** Skip virtual and transient filesystems by default, including procfs, sysfs, devfs/devtmpfs, devpts, tmpfs unless explicitly included, cgroup2, pstore, securityfs, debugfs, tracefs, configfs, fusectl, nsfs, and container overlay namespace views. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-10:** Do not follow symlinks by default. Record enough metadata/error context to explain skipped paths, but do not traverse through symlinks. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Snapshot State and Errors
- **D-11:** A snapshot is `complete` only when all configured roots were scanned without fatal root-level failure and without unhandled traversal exceptions. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-12:** A snapshot is `partial` when at least one path/subtree failed but collection still produced useful rows for one or more roots. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-13:** A snapshot is `failed` when no trustworthy directory aggregate data was produced for the requested collection. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-14:** Store fatal snapshot errors on the `snapshots` row and per-path/subtree errors on `directory_sizes.error`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-15:** Per-path errors must not silently disappear. Later reporting can decide whether to show warnings, but collection must preserve them. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Storage and Config Locations
- **D-16:** For user-run local usage, default persistent state to `${XDG_STATE_HOME:-~/.local/state}/watchdirs/watchdirs.sqlite3`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-17:** Use `${XDG_CACHE_HOME:-~/.cache}/watchdirs/` only for rebuildable cache or temporary collection artifacts, not as the primary SQLite state path. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-18:** For future systemd/system service installation, use systemd-managed persistent state/cache directories: `StateDirectory=watchdirs` for `/var/lib/watchdirs` and `CacheDirectory=watchdirs` for `/var/cache/watchdirs`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-19:** Do not put the main SQLite database in `/var/tmp`; that location is appropriate only for large persistent temporary files. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **D-20:** Configuration should be explicit and file-based, with roots/excludes/mount-policy stored outside code. Planning can choose the exact format, but the collector must not hide host-specific roots in implementation constants. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### the agent's Discretion
Verbatim from `01-CONTEXT.md`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

The user deferred low-level implementation choices to the agent when performance/correctness tradeoffs are technical. Downstream agents should prefer correctness and debuggability over shaving initial implementation time, and may use expert-panel or Exa-backed research for deep Linux/filesystem choices. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

Phase 1 implementation should avoid design choices that prevent later low-priority scheduling. The actual strong `nice`/`ionice` service behavior belongs to Phase 4, but the collector should remain callable in a way that systemd can wrap with CPU/I/O priority controls. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Deferred Ideas (OUT OF SCOPE)
Verbatim from `01-CONTEXT.md`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

- Store Docker enrichment in SQLite vs report-time evidence remains deferred to Phase 3. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- Systemd timer install details, retention TTL enforcement, and vacuum scheduling remain deferred to Phase 4. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- Strong `nice`/`ionice` priority reduction for scheduled scans is deferred to Phase 4, but must not be forgotten. The user explicitly wants watchdirs to avoid interfering with other host workloads. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- File-level inventory remains v2 unless directory aggregate snapshots prove insufficient. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COLL-01 | Agent can run `watchdirs collect` to create a timestamped directory-size snapshot for configured roots. [VERIFIED: .planning/REQUIREMENTS.md] | CLI scaffold, snapshot transaction flow, and JSON-first output recommendations define the Phase 1 command contract. [CITED: https://docs.python.org/3/library/argparse.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| COLL-02 | Collection records a snapshot status, start time, finish time, root path, notes, and any fatal error. [VERIFIED: .planning/REQUIREMENTS.md] | SQLite schema and finalize-state pattern define `complete`/`partial`/`failed` plus fatal-error persistence. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md + https://docs.python.org/3/library/sqlite3.html] |
| COLL-03 | Collection records recursive directory aggregate rows with path, parent path, name, depth, apparent bytes, disk bytes, file count, directory count, and per-path error. [VERIFIED: .planning/REQUIREMENTS.md] | Post-order aggregation pattern, schema guidance, and per-path error recording cover the row model. [CITED: https://docs.python.org/3/library/os.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| COLL-04 | Collection stores disk bytes using physical allocation semantics compatible with `st_blocks * 512` or `du`. [VERIFIED: .planning/REQUIREMENTS.md] | Native scanner should use `stat_result.st_blocks * 512` and compare selected subtrees against `du`. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][CITED: https://docs.python.org/3/library/os.html] |
| COLL-05 | Collection stores apparent bytes using logical file size semantics compatible with `st_size`. [VERIFIED: .planning/REQUIREMENTS.md] | Apparent-byte rules follow `st_size` for regular files and symlinks, with non-regular special files contributing zero logical bytes. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][CITED: https://docs.python.org/3/library/os.html] |
| FSEM-01 | Scanner does not follow symlinks by default. [VERIFIED: .planning/REQUIREMENTS.md] | `DirEntry.stat(follow_symlinks=False)` and explicit refusal to recurse through symlinked directories implement this. [CITED: https://docs.python.org/3/library/os.html] |
| FSEM-02 | Scanner avoids double-counting physical bytes for hardlinked files within one snapshot. [VERIFIED: .planning/REQUIREMENTS.md] | Deduplicate by `(st_dev, st_ino)` at snapshot scope and attribute counted bytes to first-seen path. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| FSEM-03 | Scanner reads mount information and skips virtual/transient filesystems by default. [VERIFIED: .planning/REQUIREMENTS.md] | Parse `/proc/self/mountinfo` into an explicit policy table keyed by mountpoint and filesystem type. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| FSEM-04 | Scanner avoids descending into container overlay mount views and namespace mounts by default. [VERIFIED: .planning/REQUIREMENTS.md] | Mount classifier must mark `overlay`, `nsfs`, and related pseudo/transient surfaces as skipped before traversal enters them. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| FSEM-05 | Scanner records partial path-level errors instead of silently dropping inaccessible subtrees. [VERIFIED: .planning/REQUIREMENTS.md] | Directory rows should be emitted even when child scan operations fail, with `error` persisted and snapshot downgraded to `partial` when usable data remains. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://docs.python.org/3/library/os.html] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Target `senbonzakura` first; Phase 1 should optimize for the real host incident rather than a generic cross-platform disk visualizer. [VERIFIED: AGENTS.md]
- Use SQLite for v1 storage. [VERIFIED: AGENTS.md]
- Store recursive directory aggregate rows rather than permanent file inventory. [VERIFIED: AGENTS.md]
- Do not follow symlinks and do not silently descend into virtual, transient, or container overlay filesystems. [VERIFIED: AGENTS.md]
- Track both apparent bytes and disk bytes, and make hardlink semantics explicit. [VERIFIED: AGENTS.md]
- Keep JSON output first-class. [VERIFIED: AGENTS.md]
- Respect GSD workflow boundaries for later implementation work; planning artifacts are authoritative. [VERIFIED: AGENTS.md]

## Summary

Phase 1 can stay runtime-stdlib-only: Python 3.13.5 already provides `argparse`, `os.scandir()`, `os.DirEntry.stat(follow_symlinks=False)`, and `sqlite3`, and those APIs align directly with the locked native-scanner and SQLite decisions. [VERIFIED: python3 --version][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/os.html][CITED: https://docs.python.org/3/library/sqlite3.html]

Use `/proc/self/mountinfo` as the primary mount source and treat `findmnt` as a verification/debugging fallback only. Linux documents the mountinfo fields needed for classification, and the `findmnt` man page explicitly warns that its default output is unstable for scripts unless columns are specified. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html]

The core implementation pattern should be a post-order DFS over configured roots: classify the root mount first, traverse with `os.scandir()`, stat each entry without following symlinks, deduplicate physical bytes by `(st_dev, st_ino)` for hardlinks, aggregate child totals upward, and persist both snapshot-level and path-level errors in one explicit SQLite transaction sequence. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://docs.python.org/3/library/os.html][CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][CITED: https://docs.python.org/3/library/sqlite3.html]

**Primary recommendation:** Build Phase 1 as a stdlib-first Python package with a `collect` subcommand, direct `/proc/self/mountinfo` parsing, post-order `os.scandir()` traversal, and schema-versioned SQLite writes via `PRAGMA user_version`. [CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/os.html][CITED: https://sqlite.org/pragma.html]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CLI parsing and command dispatch | API / Backend | — | `watchdirs collect` is a local process concern; `argparse` is sufficient and standard for basic CLIs. [CITED: https://docs.python.org/3/library/argparse.html] |
| Filesystem traversal, hardlink dedup, and error capture | API / Backend | Database / Storage | Traversal decisions depend on Linux stat and mount semantics; only final aggregates belong in SQLite. [CITED: https://docs.python.org/3/library/os.html][CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html] |
| Mount classification and skip policy | API / Backend | — | The scanner must decide before descent whether a path is on an allowed mount. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] |
| Snapshot and aggregate persistence | Database / Storage | API / Backend | SQLite owns durable state, schema versioning, and queryable snapshot rows; the collector owns transaction boundaries and final status calculation. [CITED: https://docs.python.org/3/library/sqlite3.html][CITED: https://sqlite.org/pragma.html] |
| JSON result emission | API / Backend | — | JSON-first output is part of the CLI contract, not a storage concern. [VERIFIED: AGENTS.md] |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`argparse`, `os`, `sqlite3`) | 3.13.5 [VERIFIED: python3 --version] | CLI parsing, traversal, stats, and embedded persistence. [CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/os.html][CITED: https://docs.python.org/3/library/sqlite3.html] | Keeps Phase 1 runtime dependency-free on a host where `pip` is currently absent. [VERIFIED: python3 -m pip --version] |
| SQLite engine | 3.46.1 [VERIFIED: sqlite3 --version + sqlite3.sqlite_version] | Local snapshot store, indexes, transactions, and schema versioning. [CITED: https://sqlite.org/pragma.html] | Matches the project’s one-file operational store requirement and later diff-query workload. [VERIFIED: AGENTS.md + README.md] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| GNU `du` | 9.7 [VERIFIED: du --version] | Verification oracle for `disk_bytes`, hardlink, symlink, and one-filesystem semantics. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html] | Use in tests and manual diagnostics, not as the primary collector. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| `findmnt` | 2.41 [VERIFIED: findmnt --version] | Human/debug fallback for inspecting live mounts and validating classifier decisions. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | Use when debugging mount policy or comparing parsed `/proc/self/mountinfo` to system output. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] |
| `pytest` | 8.3.5 installed locally; 9.0.3 current on PyPI [VERIFIED: pytest --version][CITED: https://pypi.org/project/pytest/] | Tempdir fixtures, shared fixtures, and concise filesystem tests. [CITED: https://docs.pytest.org/en/stable/how-to/tmp_path.html][CITED: https://docs.pytest.org/en/stable/reference/fixtures.html] | Use for the Phase 1 test suite if the repo accepts a preinstalled tool or later adds a pinned dev dependency. [ASSUMED] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct `/proc/self/mountinfo` parsing [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] | `findmnt --json --output ...` [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | `findmnt` is easier to inspect manually, but direct mountinfo parsing avoids subprocess cost and avoids depending on CLI output shape. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html][ASSUMED] |
| Stdlib `argparse` [CITED: https://docs.python.org/3/library/argparse.html] | `click`/`typer` [ASSUMED] | External CLI frameworks add dependency/bootstrap work that does not buy much for one Phase 1 subcommand. [ASSUMED] |
| Stdlib-only dev flow with repo-local execution fallback [VERIFIED: python3 -m pip --version] | Immediate installable console script via backend package such as `setuptools` [CITED: https://packaging.python.org/en/latest/guides/creating-command-line-tools/][CITED: https://pypi.org/project/setuptools/] | Installable entry points are cleaner long term, but this host currently lacks `pip`, so planners should not assume packaging bootstrap is free. [VERIFIED: python3 -m pip --version] |

**Installation:**
```bash
# No runtime package install is required for the recommended Phase 1 collector path.
# If the planner wants an installable console script or isolated dev environment:
python3 -m ensurepip --upgrade
python3 -m pip install setuptools pytest
```
[VERIFIED: python3 -m ensurepip --help][VERIFIED: python3 -m pip --version][CITED: https://packaging.python.org/en/latest/guides/creating-command-line-tools/]

**Version verification:** `python3`, `sqlite3`, `pytest`, `du`, and `findmnt` were verified locally. `python3 -m pip` is missing on this host, so package-registry CLI verification for future optional installs could not be executed directly and must be treated as a bootstrap task. [VERIFIED: python3 --version + sqlite3 --version + pytest --version + du --version + findmnt --version + python3 -m pip --version]

## Package Legitimacy Audit

Phase 1 does not require new runtime package installs if the planner keeps the collector stdlib-only and uses the already-installed `pytest` for local validation. [VERIFIED: python3 --version + pytest --version + python3 -m pip --version]

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `setuptools` [WARNING: flagged as suspicious — verify before using.] | PyPI [CITED: https://pypi.org/project/setuptools/] | Latest release 82.0.1 on 2026-03-09. [CITED: https://pypi.org/project/setuptools/] | Unknown to seam. [VERIFIED: package-legitimacy check] | `github.com/pypa/setuptools` [CITED: https://pypi.org/project/setuptools/] | SUS [VERIFIED: package-legitimacy check] | Flagged — planner must add `checkpoint:human-verify` before install. [VERIFIED: package-legitimacy check] |
| `pytest` [WARNING: flagged as suspicious — verify before using.] | PyPI [CITED: https://pypi.org/project/pytest/] | Latest release 9.0.3 on 2026-04-07. [CITED: https://pypi.org/project/pytest/] | Unknown to seam. [VERIFIED: package-legitimacy check] | `github.com/pytest-dev/pytest` via PyPI project links. [CITED: https://pypi.org/project/pytest/] | SUS [VERIFIED: package-legitimacy check] | Prefer the already-installed `pytest 8.3.5`; if pinning/installing later, add `checkpoint:human-verify`. [VERIFIED: pytest --version][VERIFIED: package-legitimacy check] |

**Packages removed due to [SLOP] verdict:** none. [VERIFIED: package-legitimacy check]
**Packages flagged as suspicious [SUS]:** `setuptools`, `pytest`. [VERIFIED: package-legitimacy check]

## Architecture Patterns

### System Architecture Diagram

Recommended collection flow for Phase 1. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://docs.python.org/3/library/os.html][CITED: https://sqlite.org/pragma.html]

```text
Config file / explicit roots
  -> CLI parser (`watchdirs collect`)
  -> Root planner
     -> mountinfo loader/classifier
     -> per-root traversal engine
        -> scandir DFS
        -> lstat-style metadata reads
        -> hardlink dedup set
        -> per-path error capture
     -> recursive aggregate builder
  -> SQLite writer
     -> insert snapshot start row
     -> insert directory_sizes rows
     -> finalize snapshot status/error
  -> JSON result / exit code
```

### Recommended Project Structure
```text
src/
└── watchdirs/
    ├── __init__.py          # package marker and version surface
    ├── __main__.py          # python -m watchdirs entry
    ├── cli.py               # argparse parser and command dispatch
    ├── config.py            # XDG paths + file-based config loading
    ├── models.py            # snapshot/directory row dataclasses
    ├── collect/
    │   ├── scanner.py       # post-order traversal and aggregation
    │   ├── mounts.py        # /proc/self/mountinfo parsing + policy
    │   └── classify.py      # filesystem-type skip/include decisions
    └── db/
        ├── connection.py    # sqlite connection setup + row factory
        ├── migrations.py    # PRAGMA user_version migrations
        └── schema.sql       # initial schema/index definitions

tests/
├── conftest.py              # shared temp fixtures and helper factories
├── test_cli_collect.py      # command contract + JSON output
├── test_scanner_semantics.py# hardlinks, symlinks, special files, errors
├── test_mount_policy.py     # mount classifier coverage
└── test_db_schema.py        # migrations and snapshot persistence
```
[CITED: https://packaging.python.org/en/latest/guides/creating-command-line-tools/][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://sqlite.org/pragma.html][ASSUMED]

### Pattern 1: Post-Order Aggregate Traversal
**What:** Traverse each configured root with an explicit DFS stack, emit child aggregates before parent aggregates, and maintain one snapshot-wide hardlink dedup set keyed by `(st_dev, st_ino)`. [CITED: https://docs.python.org/3/library/os.html][CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
**When to use:** Use for all recursive collection work in Phase 1 because parent rows need final child totals and mount/symlink policies must be applied before descent. [VERIFIED: .planning/REQUIREMENTS.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
**Example:**
```python
import os

def iter_entries(path):
    with os.scandir(path) as entries:
        for entry in entries:
            stat_result = entry.stat(follow_symlinks=False)
            yield entry, stat_result
```
```python
# Source: adapted from Python os docs
# https://docs.python.org/3/library/os.html
```

### Pattern 2: Snapshot-First Transaction Finalization
**What:** Insert the `snapshots` row immediately with `started_at` and provisional `status`, then update `finished_at`, final `status`, `notes`, and fatal `error` only after traversal outcome is known. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://docs.python.org/3/library/sqlite3.html]
**When to use:** Use on every collection run so partial data and fatal failures remain inspectable and later phases never need to infer whether a snapshot was trustworthy. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
**Example:**
```python
con.autocommit = False
snapshot_id = con.execute(
    "INSERT INTO snapshots(started_at, root_path, status) VALUES (?, ?, ?)",
    (started_at, root_path, "failed"),
).lastrowid
# ... insert directory_sizes rows ...
con.execute(
    "UPDATE snapshots SET finished_at=?, status=?, notes=?, error=? WHERE id=?",
    (finished_at, status, notes, fatal_error, snapshot_id),
)
con.commit()
```
```python
# Source: adapted from Python sqlite3 docs
# https://docs.python.org/3/library/sqlite3.html
```

### Anti-Patterns to Avoid
- **Primary-engine shellout to `du`:** This blocks per-path error capture, makes mount policy harder to explain, and conflicts with the locked native-scanner decision. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- **Parsing `findmnt` default tree output:** The man page says default output may change; scripts should request explicit columns. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html]
- **Top-down parent aggregation:** Parent rows will be incomplete unless child totals are revisited or buffered. [CITED: https://docs.python.org/3/library/os.html][ASSUMED]
- **Silently dropping permission or stat errors:** Phase 1 requires partial-failure evidence, not invisible omissions. [VERIFIED: .planning/REQUIREMENTS.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Schema migrations | Filename-guessing migration state [ASSUMED] | `PRAGMA user_version` plus explicit migration functions. [CITED: https://sqlite.org/pragma.html] | SQLite already provides app-owned schema version storage. [CITED: https://sqlite.org/pragma.html] |
| Mount discovery | Parsing `mount` text output [ASSUMED] | `/proc/self/mountinfo` parser, with `findmnt` only for verification. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | `mountinfo` exposes mount IDs, parent IDs, device IDs, and filesystem types directly. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| Disk-byte estimation | `ceil(st_size / block_size)` or ad hoc rounding [ASSUMED] | `st_blocks * 512` for native collection. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html] | `du` semantics are block-allocation-based, not logical-size-based. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html] |
| Hardlink identity | Path-string deduplication [ASSUMED] | `(st_dev, st_ino)` snapshot-scope dedup set. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://docs.python.org/3/library/os.html] | Hardlinks are inode/device aliases, not path aliases. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html] |

**Key insight:** The hard parts in this phase are Linux filesystem semantics and failure visibility, not framework breadth, so the safe plan is to lean on kernel-exposed metadata and stdlib primitives instead of adding abstraction layers. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][CITED: https://docs.python.org/3/library/os.html][ASSUMED]

## Common Pitfalls

### Pitfall 1: Parent Totals Written Before Child Totals
**What goes wrong:** Parent rows end up missing subdirectory bytes or require fragile patch-up passes. [ASSUMED]
**Why it happens:** `os.walk(topdown=True)` is natural to write, but bottom-up aggregation is what recursive totals need. [CITED: https://docs.python.org/3/library/os.html]
**How to avoid:** Use an explicit DFS stack or bottom-up traversal semantics and write each directory row only after all descendants are processed. [CITED: https://docs.python.org/3/library/os.html][ASSUMED]
**Warning signs:** Root totals differ from `du` while leaf rows look correct. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][ASSUMED]

### Pitfall 2: Hardlink Dedup Hides Path Attribution Ambiguity
**What goes wrong:** Disk totals are right, but individual subtree attribution varies with traversal order. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
**Why it happens:** `du`-style semantics count one hardlink, and whichever path is seen first gets the bytes. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
**How to avoid:** Document this explicitly, keep the dedup set snapshot-wide, and never present subtree attribution as mathematically exact. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
**Warning signs:** Reordering traversal changes subtree byte distribution but not total snapshot bytes. [ASSUMED]

### Pitfall 3: Symlink and Mount Boundary Leakage
**What goes wrong:** The collector includes bytes outside the intended root or crosses into pseudo/transient/container mounts. [VERIFIED: AGENTS.md + .planning/REQUIREMENTS.md]
**Why it happens:** Default recursive code often follows directory-like entries without classifying symlinks or checking mount-device changes. [CITED: https://docs.python.org/3/library/os.html][ASSUMED]
**How to avoid:** Stat entries with `follow_symlinks=False`, never recurse into symlinked directories, and compare candidate child mount/device identity against the root policy before descent. [CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][ASSUMED]
**Warning signs:** Rows appear under `/proc`, `/sys`, `overlay`, or `nsfs` even when not explicitly configured. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

### Pitfall 4: Special Files Inflate Logical Bytes
**What goes wrong:** FIFOs, sockets, device nodes, or directories contribute nonsensical `apparent_bytes`. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
**Why it happens:** `st_size` exists on many file types, but GNU `du` documents apparent-size meaning only for regular files and symlinks. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
**How to avoid:** Count logical bytes only for regular files and symlinks; still record `disk_bytes` from allocated blocks where present. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][ASSUMED]
**Warning signs:** Named pipes or sockets show large logical-byte deltas with no matching disk pressure. [ASSUMED]

## Code Examples

Verified patterns from official sources:

### CLI Subcommand Layout
```python
import argparse

parser = argparse.ArgumentParser(prog="watchdirs", allow_abbrev=False)
subparsers = parser.add_subparsers(dest="command", required=True)
collect = subparsers.add_parser("collect")
collect.add_argument("--json", action="store_true")
```
```python
# Source: adapted from Python argparse docs
# https://docs.python.org/3/library/argparse.html
```

### SQLite Row Factory for Report Queries
```python
import sqlite3

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row
```
```python
# Source: adapted from Python sqlite3 docs
# https://docs.python.org/3/library/sqlite3.html
```

### Pytest Tempdir Fixture
```python
def test_collect_uses_temp_tree(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    # arrange files under root, run scanner, assert snapshot rows
```
```python
# Source: adapted from pytest tmp_path docs
# https://docs.pytest.org/en/stable/how-to/tmp_path.html
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `os.listdir()`-style traversal plus separate `stat()` calls [ASSUMED] | `os.walk()` internally uses `os.scandir()`, and direct `os.scandir()` gives the most control for collectors like this. [CITED: https://docs.python.org/3/library/os.html] | Python 3.5 for `os.walk()` internals. [CITED: https://docs.python.org/3/library/os.html] | Direct `scandir()` keeps metadata caching and custom skip logic explicit. [CITED: https://docs.python.org/3/library/os.html][ASSUMED] |
| `sqlite3.isolation_level`-centric transaction control [CITED: https://docs.python.org/3/library/sqlite3.html] | `Connection.autocommit` is the recommended transaction-control surface. [CITED: https://docs.python.org/3/library/sqlite3.html] | Python 3.12+ docs recommendation. [CITED: https://docs.python.org/3/library/sqlite3.html] | Prefer explicit `commit()`/`rollback()` flow in migrations and snapshot finalization. [CITED: https://docs.python.org/3/library/sqlite3.html][ASSUMED] |
| Script parsing of `findmnt` default output [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | Direct `/proc/self/mountinfo` parsing or `findmnt` with explicit columns only. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | Current util-linux documentation as of 2026-05-24. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] | Prevents silent breakage from output-shape drift. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html] |

**Deprecated/outdated:**
- Parsing `findmnt` default human output in scripts is outdated because the man page warns that default output is subject to change. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html]
- Treating `st_size` as logical bytes for all file types is outdated because GNU `du` says apparent size is meaningful only for regular files and symlinks. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | For Phase 1, `file_count` should count encountered file paths while `disk_bytes` alone is hardlink-deduped. [ASSUMED] | Common Pitfalls / planning implications | Later reporting may need reinterpretation if stakeholders expect unique-inode counts. |
| A2 | Direct `os.scandir()` with an explicit stack is preferable to `os.walk(topdown=False)` because the collector needs fine-grained mount, error, and dedup control. [ASSUMED] | Architecture Patterns | Implementation might be slightly more complex than necessary if `os.walk()` proves sufficient. |
| A3 | If `pip` bootstrap is deferred, Phase 1 development can still proceed with `python -m watchdirs` or a repo-local launcher while preserving the long-term package shape. [ASSUMED] | Standard Stack / Open Questions | Planner may need an extra task later to converge on an installable entry point. |

## Open Questions (RESOLVED)

1. **Should `file_count` reflect directory entries or unique inodes when hardlinks exist?**
   - What we know: `disk_bytes` must deduplicate by `(st_dev, st_ino)`, and subtree attribution is first-path-wins. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
   - Resolution: `file_count` is path-count for encountered file entries. Hardlink dedup applies to `disk_bytes`, not `file_count`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

2. **Should Phase 1 require an installable `watchdirs` entry point on this host, or is `python -m watchdirs` acceptable during implementation?**
   - What we know: The success criterion names `watchdirs collect`, but the host currently lacks `pip`; `ensurepip` is available. [VERIFIED: .planning/ROADMAP.md + python3 -m pip --version + python3 -m ensurepip --help]
   - Resolution: Phase 1 should provide a repo-local executable `./watchdirs collect` for no-install literal command semantics, plus `PYTHONPATH=src python3 -m watchdirs collect` as a module fallback. Installed console-script behavior may be represented in metadata, but Phase 1 execution and verification must not require `pip`. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

3. **Should tmpfs roots like `/tmp` be excluded entirely by default on `senbonzakura`, or added only as explicit extra roots?**
   - What we know: The locked policy says skip `tmpfs` unless explicitly included. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
   - Resolution: Treat `/tmp` and other tmpfs roots as explicit operator choices in config, not hidden built-in defaults. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Collector runtime | ✓ [VERIFIED: python3 --version] | 3.13.5 [VERIFIED: python3 --version] | — |
| SQLite engine / stdlib module | Snapshot storage | ✓ [VERIFIED: sqlite3 --version + sqlite3.sqlite_version] | 3.46.1 [VERIFIED: sqlite3 --version + sqlite3.sqlite_version] | — |
| `du` | Semantics verification | ✓ [VERIFIED: du --version] | 9.7 [VERIFIED: du --version] | Manual spot checks omitted if unavailable. [ASSUMED] |
| `findmnt` | Mount-policy debugging fallback | ✓ [VERIFIED: findmnt --version] | 2.41 [VERIFIED: findmnt --version] | Parse `/proc/self/mountinfo` directly. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| `pytest` | Automated validation | ✓ [VERIFIED: pytest --version] | 8.3.5 [VERIFIED: pytest --version] | `unittest` is possible but less ergonomic for tmp-path fixtures. [ASSUMED] |
| `pip` | Optional packaging/bootstrap installs | ✗ [VERIFIED: python3 -m pip --version] | — | `python3 -m ensurepip --upgrade`, or defer installs and use repo-local execution. [VERIFIED: python3 -m ensurepip --help][ASSUMED] |
| `systemctl` | Future Phase 4 ops, not required for Phase 1 code | ✓ [VERIFIED: systemctl --version] | 257 [VERIFIED: systemctl --version] | None needed in this phase. [VERIFIED: .planning/ROADMAP.md] |

**Missing dependencies with no fallback:**
- None for the recommended stdlib-only Phase 1 collector path. [VERIFIED: python3 --version + sqlite3 --version + python3 -m pip --version]

**Missing dependencies with fallback:**
- `pip` is missing, so any plan step that installs or pins `setuptools`/`pytest` must first bootstrap `pip` with `ensurepip` or deliberately avoid installs in Phase 1. [VERIFIED: python3 -m pip --version + python3 -m ensurepip --help]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 8.3.5` installed locally. [VERIFIED: pytest --version] |
| Config file | none — create in Wave 0 only if needed. [VERIFIED: rg --files scaffold/test scan] |
| Quick run command | `pytest tests/test_scanner_semantics.py -q` [ASSUMED] |
| Full suite command | `pytest -q` [VERIFIED: pytest --version][ASSUMED] |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COLL-01 | `collect` creates a snapshot for configured roots. [VERIFIED: .planning/REQUIREMENTS.md] | integration | `pytest tests/test_cli_collect.py::test_collect_creates_snapshot -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| COLL-02 | Snapshot row records status, timing, root, notes, fatal error. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_db_schema.py::test_snapshot_lifecycle_fields -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| COLL-03 | Directory aggregate rows persist hierarchy, counts, bytes, and errors. [VERIFIED: .planning/REQUIREMENTS.md] | integration | `pytest tests/test_scanner_semantics.py::test_recursive_rows_persisted -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| COLL-04 | `disk_bytes` matches physical-byte semantics. [VERIFIED: .planning/REQUIREMENTS.md] | integration | `pytest tests/test_scanner_semantics.py::test_disk_bytes_match_du_for_fixture -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| COLL-05 | `apparent_bytes` matches logical-size semantics. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_scanner_semantics.py::test_apparent_bytes_use_st_size_rules -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| FSEM-01 | Symlinks are not followed. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_scanner_semantics.py::test_symlink_targets_not_descended -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| FSEM-02 | Hardlinked files are not double-counted physically. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_scanner_semantics.py::test_hardlinks_dedup_disk_bytes -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| FSEM-03 | Virtual/transient filesystems are skipped by default. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_mount_policy.py::test_skip_default_pseudo_filesystems -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| FSEM-04 | Overlay and namespace mount views are skipped. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `pytest tests/test_mount_policy.py::test_skip_overlay_and_nsfs -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |
| FSEM-05 | Partial path-level errors are preserved. [VERIFIED: .planning/REQUIREMENTS.md] | integration | `pytest tests/test_scanner_semantics.py::test_permission_error_marks_partial_row -q` [ASSUMED] | ❌ Wave 0 [VERIFIED: rg --files scaffold/test scan] |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scanner_semantics.py -q` or a narrower requirement-targeted test. [ASSUMED]
- **Per wave merge:** `pytest -q`. [VERIFIED: pytest --version][ASSUMED]
- **Phase gate:** Full Phase 1 suite green, plus one manual `du` spot check on a controlled fixture tree. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][ASSUMED]

### Wave 0 Gaps
- [ ] `tests/conftest.py` — shared temporary-tree and SQLite-db fixtures. [CITED: https://docs.pytest.org/en/stable/reference/fixtures.html]
- [ ] `tests/test_cli_collect.py` — covers `COLL-01`. [ASSUMED]
- [ ] `tests/test_scanner_semantics.py` — covers `COLL-03` through `COLL-05` and `FSEM-01`, `FSEM-02`, `FSEM-05`. [ASSUMED]
- [ ] `tests/test_mount_policy.py` — covers `FSEM-03` and `FSEM-04`. [ASSUMED]
- [ ] `tests/test_db_schema.py` — covers `COLL-02` and migration behavior. [ASSUMED]
- [ ] Package/bootstrap decision — either rely on installed `pytest 8.3.5` or add an explicit bootstrap task before isolated env setup. [VERIFIED: pytest --version + python3 -m pip --version]

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [ASSUMED] | Not applicable to a local single-user forensic CLI. [ASSUMED] |
| V3 Session Management | no [ASSUMED] | Not applicable to a batch-style local collector. [ASSUMED] |
| V4 Access Control | no [ASSUMED] | Host filesystem permissions remain OS-enforced; Phase 1 should record permission failures rather than bypass them. [VERIFIED: .planning/REQUIREMENTS.md][ASSUMED] |
| V5 Input Validation | yes [ASSUMED] | Validate config roots, normalize paths, reject overlapping roots by default, and classify mounts before traversal. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md][ASSUMED] |
| V6 Cryptography | no [ASSUMED] | No cryptographic requirement is in scope for local snapshot storage in Phase 1. [ASSUMED] |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Symlink traversal into unintended trees | Tampering | `follow_symlinks=False` on stat, never recurse into symlinked directories, and record skipped/error context. [CITED: https://docs.python.org/3/library/os.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| Namespace/overlay mount inclusion creates misleading evidence | Spoofing | Parse mountinfo first, classify pseudo/overlay/nsfs roots, and prune before descent. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| Partial failures silently erase evidence | Repudiation | Persist snapshot fatal error plus per-path `error` fields and downgrade status to `partial` when needed. [VERIFIED: .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md] |
| SQLite corruption from ambiguous transaction boundaries | Tampering | Use explicit transaction control and schema-versioned migrations instead of ad hoc DDL at read time. [CITED: https://docs.python.org/3/library/sqlite3.html][CITED: https://sqlite.org/pragma.html][ASSUMED] |

## Sources

### Primary (HIGH confidence)
- None in this session; the available providers classified official-doc lookups as MEDIUM confidence rather than HIGH. [VERIFIED: classify-confidence websearch/exa --verified]

### Secondary (MEDIUM confidence)
- `https://docs.python.org/3/library/os.html` - `os.scandir()`, `DirEntry`, `stat(follow_symlinks=False)`, `os.walk()` traversal semantics. [CITED: https://docs.python.org/3/library/os.html]
- `https://docs.python.org/3/library/argparse.html` - stdlib CLI guidance and subcommand-capable parser surface. [CITED: https://docs.python.org/3/library/argparse.html]
- `https://docs.python.org/3/library/sqlite3.html` - transaction control and row factories. [CITED: https://docs.python.org/3/library/sqlite3.html]
- `https://sqlite.org/pragma.html` - `PRAGMA user_version` for schema versioning. [CITED: https://sqlite.org/pragma.html]
- `https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html` - mountinfo field definitions. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
- `https://man7.org/linux/man-pages/man8/findmnt.8.html` - scripting cautions and mountinfo-backed lookup behavior. [CITED: https://man7.org/linux/man-pages/man8/findmnt.8.html]
- `https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html` - hardlink, apparent-size, symlink, and one-file-system semantics. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html]
- `https://docs.pytest.org/en/stable/how-to/tmp_path.html` and `https://docs.pytest.org/en/stable/reference/fixtures.html` - tempdir and shared fixture patterns. [CITED: https://docs.pytest.org/en/stable/how-to/tmp_path.html][CITED: https://docs.pytest.org/en/stable/reference/fixtures.html]
- `https://packaging.python.org/en/latest/guides/creating-command-line-tools/` and `https://packaging.python.org/en/latest/specifications/entry-points/` - `src` layout and console-script entry-point shape. [CITED: https://packaging.python.org/en/latest/guides/creating-command-line-tools/][CITED: https://packaging.python.org/en/latest/specifications/entry-points/]
- Local environment commands: `python3 --version`, `sqlite3 --version`, `pytest --version`, `findmnt --version`, `du --version`, `python3 -m ensurepip --help`, `python3 -m pip --version`. [VERIFIED: local command probes]

### Tertiary (LOW confidence)
- Inferred implementation recommendations about `file_count` semantics, exact stack shape around packaging bootstrap, and some test-command filenames remain assumptions for the planner to confirm. [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - runtime stack is strongly grounded in local environment and official docs, but packaging bootstrap is constrained by missing `pip`. [VERIFIED: python3 --version + python3 -m pip --version][CITED: https://packaging.python.org/en/latest/guides/creating-command-line-tools/]
- Architecture: MEDIUM - traversal, mount, and SQLite patterns are well-supported, but some planner-level choices such as launcher/bootstrap shape remain assumptions. [CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html][ASSUMED]
- Pitfalls: MEDIUM - the filesystem semantics are well-documented, but some failure modes are extrapolated from those semantics into this specific tool design. [CITED: https://www.gnu.org/software/coreutils/manual/html_node/du-invocation.html][ASSUMED]

**Research date:** 2026-06-12
**Valid until:** 2026-07-12 for Python/stdlib/SQLite semantics; re-check sooner if the target host bootstrap environment changes. [VERIFIED: current_date + local environment]
