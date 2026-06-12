# Phase 01: trusted-snapshot-collection - Pattern Map

**Mapped:** 2026-06-12
**Files analyzed:** 14
**Analogs found:** 0 / 14

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/watchdirs/__init__.py` | config | request-response | None | none |
| `src/watchdirs/__main__.py` | controller | request-response | None | none |
| `src/watchdirs/cli.py` | controller | request-response | None | none |
| `src/watchdirs/config.py` | utility | file-I/O | None | none |
| `src/watchdirs/models.py` | model | transform | None | none |
| `src/watchdirs/collect/scanner.py` | service | file-I/O | None | none |
| `src/watchdirs/collect/mounts.py` | service | file-I/O | None | none |
| `src/watchdirs/collect/classify.py` | utility | transform | None | none |
| `src/watchdirs/db/connection.py` | service | CRUD | None | none |
| `src/watchdirs/db/migrations.py` | migration | CRUD | None | none |
| `src/watchdirs/db/schema.sql` | config | CRUD | None | none |
| `tests/conftest.py` | test | transform | None | none |
| `tests/test_cli_collect.py` | test | request-response | None | none |
| `tests/test_scanner_semantics.py` | test | file-I/O | None | none |
| `tests/test_mount_policy.py` | test | file-I/O | None | none |
| `tests/test_db_schema.py` | test | CRUD | None | none |

## Pattern Assignments

This repo is still greenfield. There are no source analogs under `src/` or `tests/`; the only current patterns are the phase docs and bootstrap design note. Use those as design contracts, not as copy-paste implementation examples.

### `src/watchdirs/__init__.py` (config, request-response)

**Analog:** None in codebase.

**File to copy structure from:** `01-RESEARCH.md` recommended project structure ([`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178)-[189](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:189))

**Pattern to follow:**
- Keep package root minimal.
- Expose only stable package/version surface.
- Do not bury host-specific defaults here; config must stay file-based per D-20.

### `src/watchdirs/__main__.py` (controller, request-response)

**Analog:** None in codebase.

**Command-entry pattern source:** `01-RESEARCH.md` recommended structure and CLI example ([`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178)-[180](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:180), [287](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:287)-[295](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:295))

**Pattern to follow:**
```python
import argparse

parser = argparse.ArgumentParser(prog="watchdirs", allow_abbrev=False)
subparsers = parser.add_subparsers(dest="command", required=True)
collect = subparsers.add_parser("collect")
collect.add_argument("--json", action="store_true")
```

Use `python -m watchdirs` as the first runnable entrypoint and delegate real work to `cli.py`.

### `src/watchdirs/cli.py` (controller, request-response)

**Analog:** None in codebase.

**Responsibility split source:** D-21 through D-24 in context plus recommended structure ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:46`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:46)-[50](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:50), [84](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:84)-[85](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:84), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178)-[180](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:180))

**Pattern to follow:**
- Parse args and dispatch only.
- Keep JSON output first-class per README.
- Do not mix traversal, mount parsing, and SQLite writes into this file.

**Output-contract source:** [`README.md:402`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:402)-[416](/home/j2h4u/repos/j2h4u/watchdirs/README.md:416)

### `src/watchdirs/config.py` (utility, file-I/O)

**Analog:** None in codebase.

**Config/default-location source:** D-16 through D-20 and recommended structure ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:39`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:39)-[44](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:44), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:180`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:180)-[181](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:181))

**Pattern to follow:**
- Resolve XDG state/cache paths here.
- Load file-based root/mount policy here.
- Keep configured roots explicit; never hide `/` or host-specific roots in constants.

### `src/watchdirs/models.py` (model, transform)

**Analog:** None in codebase.

**Data-shape source:** D-22 and README schema/data semantics ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:48`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:48)-[49](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:49), [`README.md:227`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:227)-[250](/home/j2h4u/repos/j2h4u/watchdirs/README.md:250))

**Pattern to follow:**
- Use small `@dataclass` types for snapshot metadata, directory aggregate rows, mount decisions, scanner options, and scan outcomes.
- Match field names to the persistent schema where practical.

### `src/watchdirs/collect/scanner.py` (service, file-I/O)

**Analog:** None in codebase.

**Primary behavior source:** phase boundary, scanner decisions, post-order traversal pattern, and README semantics ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:9`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:9)-[10](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:10), [19](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19)-[22](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19), [28](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:28)-[37](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:37), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:200`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:200)-[212](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:212), [`README.md:266`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:266)-[327](/home/j2h4u/repos/j2h4u/watchdirs/README.md:327))

**Core pattern excerpt** (from research example, for semantics only):
```python
import os

def iter_entries(path):
    with os.scandir(path) as entries:
        for entry in entries:
            stat_result = entry.stat(follow_symlinks=False)
            yield entry, stat_result
```

**Behavioral requirements to copy:**
- Post-order aggregation: write parent totals only after children are processed.
- Use `stat(follow_symlinks=False)`.
- Compute `apparent_bytes` and `disk_bytes`.
- Deduplicate hardlinked physical bytes by `(st_dev, st_ino)` at snapshot scope.
- Preserve per-path errors and downgrade snapshot status to `partial` when warranted.

### `src/watchdirs/collect/mounts.py` (service, file-I/O)

**Analog:** None in codebase.

**Mount-loading source:** D-08 through D-10, README mount policy, and research anti-patterns ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:28`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:28)-[30](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:30), [`README.md:297`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:297)-[327](/home/j2h4u/repos/j2h4u/watchdirs/README.md:327), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:240`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:240)-[253](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:253))

**Pattern to follow:**
- Parse `/proc/self/mountinfo` directly.
- Treat `findmnt` as debug/verification only.
- Return explicit mount records and classification inputs, not ad hoc booleans hidden in traversal code.

### `src/watchdirs/collect/classify.py` (utility, transform)

**Analog:** None in codebase.

**Classification-policy source:** D-09, README skip list, and research pitfalls ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:29`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:29)-[30](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:30), [`README.md:301`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:301)-[327](/home/j2h4u/repos/j2h4u/watchdirs/README.md:327), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:271`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:271)-[275](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:275))

**Pattern to follow:**
- Centralize include/skip decisions by filesystem type and mount traits.
- Keep overlay/nsfs/tmpfs handling explicit and testable.
- Make decisions explainable so later reports can say why a subtree was skipped.

### `src/watchdirs/db/connection.py` (service, CRUD)

**Analog:** None in codebase.

**DB-setup source:** recommended structure and sqlite row-factory example ([`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:186`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:186)-[189](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:189), [301](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:301)-[307](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:301))

**Pattern excerpt** (from research example, for semantics only):
```python
import sqlite3

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row
```

**Pattern to follow:**
- Create and configure SQLite connections here.
- Keep transaction ownership explicit.
- Support later report queries by standardizing row shape early.

### `src/watchdirs/db/migrations.py` (migration, CRUD)

**Analog:** None in codebase.

**Migration source:** primary recommendation and anti-hand-rolled guidance ([`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:126`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:126)-[128](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:128), [248](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:248)-[250](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:248))

**Pattern to follow:**
- Use `PRAGMA user_version`.
- Keep migrations explicit and numbered in code.
- Do not infer schema state from filenames.

### `src/watchdirs/db/schema.sql` (config, CRUD)

**Analog:** None in codebase.

**Schema source:** README proposed data model and indexes ([`README.md:227`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:227)-[263](/home/j2h4u/repos/j2h4u/watchdirs/README.md:263))

**Schema excerpt to copy from:**
```sql
CREATE INDEX directory_sizes_path_snapshot_idx
  ON directory_sizes(path, snapshot_id);

CREATE INDEX directory_sizes_snapshot_size_idx
  ON directory_sizes(snapshot_id, disk_bytes);

CREATE INDEX directory_sizes_snapshot_parent_idx
  ON directory_sizes(snapshot_id, parent_path);
```

Use the README schema as the initial contract; keep column names aligned with `models.py`.

### `tests/conftest.py` (test, transform)

**Analog:** None in codebase.

**Test-shared-fixture source:** recommended structure ([`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:191`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:191)-[196](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:196))

**Pattern to follow:**
- Put temp-tree builders and shared DB helpers here.
- Keep scanner-semantic fixtures reusable across CLI, scanner, and DB tests.

### `tests/test_cli_collect.py` (test, request-response)

**Analog:** None in codebase.

**Command-contract source:** `COLL-01`, JSON-first requirement, and agent-facing CLI examples ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:9`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:9)-[10](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:10), [`README.md:402`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:402)-[416](/home/j2h4u/repos/j2h4u/watchdirs/README.md:416))

**Pattern to follow:**
- Assert `watchdirs collect` works as the first command.
- Assert JSON mode is stable and machine-readable.
- Keep human-readable output secondary.

### `tests/test_scanner_semantics.py` (test, file-I/O)

**Analog:** None in codebase.

**Semantic-test source:** D-01 through D-04, D-10, D-14, D-15, and research pitfalls ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19)-[22](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19), [30](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:30)-[37](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:30), [259](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:259)-[280](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:280), [313](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:313)-[319](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:313))

**Pattern excerpt** (from research example, for semantics only):
```python
def test_collect_uses_temp_tree(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    # arrange files under root, run scanner, assert snapshot rows
```

**Coverage to copy:**
- hardlinks
- symlinks
- special files
- path-level permission/stat failures
- `du` comparison for selected trees

### `tests/test_mount_policy.py` (test, file-I/O)

**Analog:** None in codebase.

**Policy-test source:** D-08 through D-10 and README skip list ([`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:28`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:28)-[30](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:30), [`README.md:297`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:297)-[327](/home/j2h4u/repos/j2h4u/watchdirs/README.md:327))

**Pattern to follow:**
- Table-drive filesystem-type classification cases.
- Assert overlay/nsfs/tmpfs defaults are explicit.
- Assert roots do not silently cross skipped mount boundaries.

### `tests/test_db_schema.py` (test, CRUD)

**Analog:** None in codebase.

**Persistence-test source:** README schema plus snapshot-finalization pattern ([`README.md:227`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:227)-[263](/home/j2h4u/repos/j2h4u/watchdirs/README.md:263), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:218`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:218)-[234](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:234))

**Transaction excerpt** (from research example, for semantics only):
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

Test schema creation, indexes, migration versioning, and `complete`/`partial`/`failed` finalization.

## Shared Patterns

### Package Layout
**Source:** [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:178)-[196](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:196)

Apply the package split exactly: CLI/config/models at package root, scanner/mount helpers under `collect/`, DB code under `db/`, and semantic tests under `tests/`.

### Responsibility Boundaries
**Source:** [`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:46`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:46)-[50](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:50)

Keep these boundaries explicit:
- CLI/config loading
- mount classification
- traversal/aggregation
- SQLite persistence

Do not collapse them into one collector module.

### Snapshot Status and Error Recording
**Source:** [`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:32`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:32)-[37](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:32), [`.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:218`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:218)-[234](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-RESEARCH.md:234)

Persist fatal snapshot errors on `snapshots.error`, per-path failures on `directory_sizes.error`, and finalize status only after traversal outcome is known.

### Filesystem Semantics
**Source:** [`README.md:266`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:266)-[327](/home/j2h4u/repos/j2h4u/watchdirs/README.md:327), [`.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19`](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19)-[30](/home/j2h4u/repos/j2h4u/watchdirs/.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md:19)

Shared rules across scanner, mount policy, and tests:
- `apparent_bytes` uses logical size semantics.
- `disk_bytes` uses allocated-block semantics.
- hardlinks dedupe by `(st_dev, st_ino)`.
- symlinks are never followed.
- virtual/transient/container-overlay mounts are skipped by default.

### JSON-First Interface
**Source:** [`README.md:402`](/home/j2h4u/repos/j2h4u/watchdirs/README.md:402)-[416](/home/j2h4u/repos/j2h4u/watchdirs/README.md:416), `AGENTS.md` project constraints

All Phase 1 CLI work should preserve machine-readable output as a first-class contract.

## No Analog Found

Files with no close match in the codebase:

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| All listed Phase 1 files | mixed | mixed | The repository currently contains only `README.md`, `AGENTS.md`, and planning docs; no source modules or tests exist yet. |

Planner should treat the README and phase docs as contract sources, not implementation analogs.

## Metadata

**Analog search scope:** repo root via `rg --files`
**Files scanned:** 4 required reads + full repo file list
**Pattern extraction date:** 2026-06-12
