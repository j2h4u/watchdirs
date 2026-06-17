<!-- refreshed: 2026-06-17 -->
# Architecture

**Analysis Date:** 2026-06-17

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                      CLI / Entry Layer                      │
├──────────────────┬──────────────────┬───────────────────────┤
│ `src/watchdirs/  │ `src/watchdirs/  │ `src/watchdirs/`      │
│ cli.py`          │ config.py`       │ __main__.py`          │
└────────┬─────────┴────────┬─────────┴──────────┬────────────┘
         │                  │                     │
         ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Core Feature Layers                      │
│ `src/watchdirs/collect/` `src/watchdirs/reporting/`         │
│ `src/watchdirs/diagnostics/` `src/watchdirs/db/`            │
└────────┬───────────────────────────┬────────────────────────┘
         │                           │
         ▼                           ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│ Snapshot scan / mount    │   │ SQLite storage / retention   │
│ policy / classification  │   │ `src/watchdirs/db/`          │
└────────┬─────────────────┘   └──────────────┬───────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                 Persistent Host State / Outputs             │
│ SQLite DB, systemd units, JSON payloads, journal logs        │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI | Parses commands, coordinates collection/reporting, manages sockets and JSON output | `src/watchdirs/cli.py` |
| Config | Loads TOML, validates roots, resolves defaults | `src/watchdirs/config.py` |
| Scanner | Walks directory trees, applies mount and collapse policy, produces aggregates | `src/watchdirs/collect/scanner.py` |
| Mount policy | Parses and matches `/proc/self/mountinfo` entries | `src/watchdirs/collect/mounts.py` |
| Classification | Decides whether a mount is included or skipped | `src/watchdirs/collect/classify.py` |
| Database | Opens SQLite connections, initializes schema, writes snapshots | `src/watchdirs/db/connection.py`, `src/watchdirs/db/migrations.py` |
| Retention | Prunes snapshots and vacuums the DB | `src/watchdirs/db/retention.py` |
| Reporting | Builds top/diff/report/deleted/explain-path outputs | `src/watchdirs/reporting/` |
| Diagnostics | Builds df-vs-index, deleted-open, Docker/containerd summaries | `src/watchdirs/diagnostics/` |

## Pattern Overview

**Overall:** layered local forensic CLI with a thin orchestration shell and explicit import boundaries.

**Key Characteristics:**
- Entry points stay thin and delegate to feature modules.
- Collection is separate from reporting and diagnostics.
- SQLite is the only persistent store; JSON payloads are first-class outputs.
- Systemd units own unattended collection and maintenance.

## Layers

**Entry layer:**
- Purpose: command dispatch and host defaults.
- Location: `src/watchdirs/cli.py`, `src/watchdirs/__main__.py`.
- Contains: argparse wiring, socket/query handling, stdout/stderr contract.
- Depends on: collection, reporting, diagnostics, DB, config, locking.
- Used by: shell command, systemd query socket.

**Collection layer:**
- Purpose: turn a configured root into snapshot rows.
- Location: `src/watchdirs/collect/`.
- Contains: tree walk, mount parsing, mount classification, collapse policy, hardlink handling.
- Depends on: `src/watchdirs/models.py`.
- Used by: collect command and snapshot ingestion path in `src/watchdirs/cli.py`.

**Storage layer:**
- Purpose: persist snapshots and support maintenance operations.
- Location: `src/watchdirs/db/`.
- Contains: schema init, insert/update helpers, prune, vacuum, connection opening.
- Depends on: `src/watchdirs/models.py`.
- Used by: collect, prune, vacuum, reporting queries.

**Reporting layer:**
- Purpose: answer growth and comparison questions from stored snapshots.
- Location: `src/watchdirs/reporting/`.
- Contains: pair selection, query builders, frontier pruning, renderers.
- Depends on: database results and model dataclasses.
- Used by: top, snapshots, diff, report, deleted, explain-path.

**Diagnostics layer:**
- Purpose: cross-check index totals against host reality.
- Location: `src/watchdirs/diagnostics/`.
- Contains: df-vs-index, deleted-open, Docker/containerd summaries.
- Depends on: reporting and DB data.
- Used by: diagnostic CLI commands.

## Data Flow

### Primary Request Path

1. Parse config and CLI arguments (`src/watchdirs/cli.py`, `src/watchdirs/config.py`).
2. Load mount metadata and scan the configured roots (`src/watchdirs/collect/mounts.py`, `src/watchdirs/collect/scanner.py`).
3. Create or open SQLite, write snapshot metadata and directory rows (`src/watchdirs/db/connection.py`, `src/watchdirs/db/migrations.py`).
4. Emit JSON or text renderings through reporting/diagnostics (`src/watchdirs/reporting/`, `src/watchdirs/diagnostics/`).

### Maintenance Flow

1. Open an existing DB in read-write mode only (`src/watchdirs/db/connection.py::open_existing_connection`).
2. Apply retention selection and pruning (`src/watchdirs/db/retention.py`).
3. Run vacuum/checkpoint work and report before/after metrics (`src/watchdirs/db/retention.py`).

**State Management:**
- Runtime state is mostly local to the current command invocation.
- Persistent state lives in SQLite tables for snapshots, directory rows, and snapshot mounts.
- Locking is externalized through `src/watchdirs/ops_lock.py`.

## Key Abstractions

**SnapshotRecord / SnapshotSummary / SnapshotStatus:**
- Purpose: represent lifecycle and result state for one scan.
- Examples: `src/watchdirs/models.py`, `src/watchdirs/db/migrations.py`.
- Pattern: immutable dataclasses plus explicit status values.

**DirectoryAggregate:**
- Purpose: one recursive directory row with apparent/disk bytes and child metadata.
- Examples: `src/watchdirs/models.py`, `src/watchdirs/collect/scanner.py`.
- Pattern: row-shaped dataclass persisted into SQLite.

**MountInfo / MountPolicy / MountDecision:**
- Purpose: describe host mounts and inclusion rules.
- Examples: `src/watchdirs/models.py`, `src/watchdirs/collect/mounts.py`, `src/watchdirs/collect/classify.py`.
- Pattern: parse `/proc/self/mountinfo`, then classify before descent.

**ReportRow families:**
- Purpose: represent query results for top, diff, deleted, and explain-path views.
- Examples: `src/watchdirs/models.py`, `src/watchdirs/reporting/queries.py`.
- Pattern: query module returns structured rows; render module formats them.

## Entry Points

**Package entrypoint:**
- Location: `src/watchdirs/__main__.py`.
- Triggers: `python -m watchdirs`.
- Responsibilities: call `src/watchdirs/cli.py::main`.

**CLI dispatcher:**
- Location: `src/watchdirs/cli.py`.
- Triggers: installed script, module entrypoint, systemd query socket.
- Responsibilities: collect, report, diagnostics, prune, vacuum, socket proxy.

**Systemd units:**
- Location: `ops/systemd/`.
- Triggers: timers and query socket.
- Responsibilities: unattended collection, prune, vacuum, read-only queries.

## Architectural Constraints

- **Threading:** command execution is synchronous; no worker pool is part of the runtime model.
- **Global state:** CLI defaults/config live in module-level dataclasses in `src/watchdirs/cli.py`; avoid adding mutable singletons.
- **Circular imports:** import boundaries are enforced by import-linter in `pyproject.toml`; feature layers should not back-import into `watchdirs.cli`.
- **Storage model:** SQLite is the only persistent store; schema lives in `src/watchdirs/db/schema.sql`.
- **Filesystem model:** scanner does not follow symlinks and does not descend into skipped mounts.

## Anti-Patterns

### Layer Reversal

**What happens:** reporting or diagnostics code imports collection or CLI helpers directly.
**Why it's wrong:** it breaks the import contracts in `pyproject.toml` and makes query/report code depend on orchestration.
**Do this instead:** keep shared row/query/render logic in `src/watchdirs/reporting/` and let `src/watchdirs/cli.py` orchestrate the call path.

### Unbounded Collection Coupling

**What happens:** scanner logic grows knowledge of SQLite schema or render formats.
**Why it's wrong:** collection becomes harder to test and harder to reuse for retention or diagnostics.
**Do this instead:** keep scan output as `DirectoryAggregate` rows in `src/watchdirs/models.py` and hand them to DB helpers in `src/watchdirs/db/migrations.py`.

## Error Handling

**Strategy:** fail fast on invalid config, missing DB paths, missing mount roots, and mount-policy mismatches; record partial scan errors on the snapshot when possible.

**Patterns:**
- `ConfigError` payloads from `src/watchdirs/config.py`.
- `FileNotFoundError` / lock errors for maintenance commands in `src/watchdirs/db/connection.py` and `src/watchdirs/ops_lock.py`.
- Scan failures surface as snapshot status and row-level error fields from `src/watchdirs/collect/scanner.py`.

## Cross-Cutting Concerns

**Logging:** collect progress and summary messages go to stderr; JSON output stays on stdout in `src/watchdirs/cli.py`.
**Validation:** configuration/root validation happens before scanning; mount and retention policies validate their inputs in `src/watchdirs/config.py` and `src/watchdirs/db/retention.py`.
**Authentication:** not applicable; the tool is local-host oriented and query access is gated by filesystem permissions and the optional Unix socket.

---

*Architecture analysis: 2026-06-17*
