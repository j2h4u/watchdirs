# Phase 04: Scheduled Retention Operations - Pattern Map

**Mapped:** 2026-06-17
**Files analyzed:** 16
**Analogs found:** 10 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/watchdirs/cli.py` | controller | request-response | `src/watchdirs/cli.py` | exact |
| `src/watchdirs/db/retention.py` | service | CRUD | `src/watchdirs/db/migrations.py` | role-match |
| `src/watchdirs/db/connection.py` | service | CRUD | `src/watchdirs/db/connection.py` | exact |
| `README.md` | config | request-response | `README.md` | exact |
| `examples/senbonzakura.watchdirs.toml` | config | request-response | `examples/senbonzakura.watchdirs.toml` | exact |
| `tests/conftest.py` | test | request-response | `tests/conftest.py` | exact |
| `tests/test_ops_retention.py` | test | CRUD | `tests/test_db_schema.py` | role-match |
| `tests/test_ops_locking.py` | test | request-response | `tests/test_collect_observability.py` | partial |
| `tests/test_ops_vacuum.py` | test | CRUD | `tests/test_db_schema.py` | role-match |
| `tests/test_systemd_units.py` | test | request-response | `tests/test_cli_collect.py` | partial |
| `ops/systemd/watchdirs-collect.service` | config | request-response | none in repo | no-analog |
| `ops/systemd/watchdirs-collect.timer` | config | event-driven | none in repo | no-analog |
| `ops/systemd/watchdirs-prune.service` | config | request-response | none in repo | no-analog |
| `ops/systemd/watchdirs-prune.timer` | config | event-driven | none in repo | no-analog |
| `ops/systemd/watchdirs-vacuum.service` | config | request-response | none in repo | no-analog |
| `ops/systemd/watchdirs-vacuum.timer` | config | event-driven | none in repo | no-analog |

## Pattern Assignments

### `src/watchdirs/cli.py` (controller, request-response)

**Analog:** `src/watchdirs/cli.py`

**Imports + command registration pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:15)):
```python
from .config import ConfigError, default_db_path, load_config
from .db.connection import open_connection
from .db.migrations import (
    create_snapshot,
    finalize_snapshot,
    initialize_database,
    insert_directory_rows,
    insert_snapshot_mounts,
    load_snapshot_mounts,
)
```

**Subcommand wiring pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:190)):
```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="watchdirs", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", allow_abbrev=False)
    collect.add_argument("--config", required=True, help="Path to the TOML watchdirs config file")
    collect.add_argument("--db", help="Override the SQLite database path")
    collect.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    collect.set_defaults(handler=run_collect)
```

**Mutating-command transaction + snapshot finalization pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:305)):
```python
def run_collect(args: argparse.Namespace) -> int:
    ...
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
    except (OSError, sqlite3.Error) as exc:
        ...

    ...
    snapshot = create_snapshot(connection, configured_root.path, notes=args.notes)
    ...
    connection.execute("BEGIN")
    try:
        _call_with_optional_commit(insert_directory_rows, connection, persisted_rows, commit=False)
        _call_with_optional_commit(
            insert_snapshot_mounts,
            connection,
            snapshot.id,
            mounts,
            commit=False,
        )
        finalized = finalize_snapshot(
            connection,
            snapshot.id,
            status=scan_result.status,
            notes=args.notes,
            error=scan_result.fatal_error,
            commit=False,
        )
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()
```

**JSON/error envelope pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:1128)):
```python
def emit_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")

def _emit_runtime_error(
    *,
    code: str,
    message: str,
    as_json: bool,
    context: dict[str, object] | None = None,
) -> int:
    if as_json:
        error: dict[str, object] = {"code": code, "message": message}
        if context:
            error.update(context)
        emit_json({"ok": False, "error": error})
```

**Copy for Phase 4:** Add `prune` and `vacuum` beside `collect`, keep stdout JSON-only, and wrap lock failures / SQLite failures through `_emit_runtime_error()` rather than printing ad hoc text.

---

### `src/watchdirs/db/retention.py` (service, CRUD)

**Analog:** `src/watchdirs/db/migrations.py`

**DB helper import/style pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:1)):
```python
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
import sqlite3

from watchdirs.models import DirectoryAggregate, MountInfo, SnapshotMount, SnapshotRecord, SnapshotStatus
```

**Commit-optional helper pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:60)):
```python
def create_snapshot(
    connection: sqlite3.Connection,
    root_path,
    *,
    notes: str | None = None,
    commit: bool = True,
) -> SnapshotRecord:
    ...
    if commit:
        connection.commit()
```

**Bulk SQL helper pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:145)):
```python
def insert_snapshot_mounts(
    connection: sqlite3.Connection,
    snapshot_id: int,
    mounts: list[MountInfo] | tuple[MountInfo, ...],
    *,
    commit: bool = True,
) -> None:
    ...
    connection.executemany(sql, [_snapshot_mount_row_values(snapshot_id, mount) for mount in mounts])
    if commit:
        connection.commit()
```

**Snapshot lifecycle / record-return pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:210)):
```python
def finalize_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    status: SnapshotStatus,
    notes: str | None = None,
    error: str | None = None,
    commit: bool = True,
) -> SnapshotRecord:
    ...
    row = connection.execute(
        """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
```

**Copy for Phase 4:** Implement retention helpers as narrow DB-layer functions with `sqlite3.Connection` arguments, optional `commit`, and explicit return payloads (`deleted_snapshot_ids`, counts, reclaimed candidates) instead of embedding SQL in systemd files or CLI handlers.

---

### `src/watchdirs/db/connection.py` (service, CRUD)

**Analog:** `src/watchdirs/db/connection.py`

**Connection/open pattern** ([src/watchdirs/db/connection.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/connection.py:16)):
```python
def open_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_virgin = not db_path.exists() or db_path.stat().st_size == 0
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
```

**SQLite PRAGMA pattern** ([src/watchdirs/db/connection.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/connection.py:22)):
```python
if is_virgin:
    connection.execute(f"PRAGMA page_size={WATCHDIRS_PAGE_SIZE}")
    connection.execute("PRAGMA auto_vacuum=FULL")
    connection.execute(f"PRAGMA application_id={WATCHDIRS_APPLICATION_ID}")
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA foreign_keys=ON")
connection.execute("PRAGMA busy_timeout=5000")
```

**Copy for Phase 4:** Keep `VACUUM`/maintenance using the same `open_connection()` path so WAL/foreign-key/busy-timeout behavior stays centralized. Do not create a second ad hoc SQLite opener.

---

### `README.md` (config, request-response)

**Analog:** `README.md`

**Policy-doc pattern** ([README.md](/home/j2h4u/repos/j2h4u/watchdirs/README.md:375)):
```markdown
## Retention Policy

Initial recommendation:

- hourly directory snapshots: 14 days;
- daily retained snapshots: 90 days;
- optional weekly rollups or top-delta summaries: 6-12 months;
- run SQLite `VACUUM` after pruning on a slower cadence.

Prune by deleting whole snapshots, not individual paths.
```

**Scheduling-doc pattern** ([README.md](/home/j2h4u/repos/j2h4u/watchdirs/README.md:388)):
```markdown
## Scheduling

Use systemd timers rather than cron.

Suggested behavior:

- run with `nice` and idle I/O priority;
- avoid overlapping with backup and cleanup windows;
- use a lock so only one collection runs at a time;
- record partial failures in the snapshot metadata rather than failing silently;
```

**Agent-command doc pattern** ([README.md](/home/j2h4u/repos/j2h4u/watchdirs/README.md:402)):
```markdown
## Agent-Facing Commands

```bash
watchdirs collect
watchdirs report --since 24h --json
watchdirs diff --since 24h --limit 50
watchdirs top --snapshot latest --limit 50
```
```

**Copy for Phase 4:** Update these sections instead of inventing a separate ops doc. Keep docs oriented around concrete commands, DB/config paths, timer verification, and evidence-gap behavior.

---

### `examples/senbonzakura.watchdirs.toml` (config, request-response)

**Analog:** `examples/senbonzakura.watchdirs.toml`

**Example-config shape** ([examples/senbonzakura.watchdirs.toml](/home/j2h4u/repos/j2h4u/watchdirs/examples/senbonzakura.watchdirs.toml:1)):
```toml
exclude_paths = [
  "/proc",
  "/sys",
  "/dev",
  "/run",
  "/tmp",
  "/dev/shm",
]

[collapse]
...

[[roots]]
path = "/"
```

**Copy for Phase 4:** Keep live-host example config minimal and declarative. If Phase 4 adds install-path examples in docs, mirror the same TOML formatting and section ordering.

---

### `tests/conftest.py` (test, request-response)

**Analog:** `tests/conftest.py`

**Shared fixture/writer pattern** ([tests/conftest.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/conftest.py:10)):
```python
@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

@pytest.fixture
def write_config(tmp_path: Path):
    def _write_config(... ) -> Path:
        config_path = tmp_path / "watchdirs.toml"
        ...
        config_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return config_path
```

**Copy for Phase 4:** Put reusable config/unit-file fixture helpers in `conftest.py` when multiple ops tests need them; do not duplicate temp config writers per test file.

---

### `tests/test_ops_retention.py` (test, CRUD)

**Analog:** `tests/test_db_schema.py`

**Import helper pattern** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:10)):
```python
def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])
```

**Fresh-DB setup pattern** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:17)):
```python
def _open_connection(repo_root: Path, db_path: Path) -> sqlite3.Connection:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    return connection_module.open_connection(db_path)

def _initialize_database(repo_root: Path, connection: sqlite3.Connection):
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    migrations_module.initialize_database(connection)
    return migrations_module
```

**Schema/assertion style** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:129)):
```python
def test_schema_user_version_and_indexes(repo_root: Path, tmp_path: Path) -> None:
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    connection = _fresh_db(repo_root, tmp_path)

    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    ...
    assert user_version == migrations_module.SCHEMA_VERSION
```

**Copy for Phase 4:** Seed snapshots directly in SQLite and assert prune behavior by querying remaining snapshot IDs plus cascade side effects, using the same import/setup style as schema tests.

---

### `tests/test_ops_locking.py` (test, request-response)

**Analog:** `tests/test_collect_observability.py`

**CLI-module import pattern** ([tests/test_collect_observability.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_collect_observability.py:22)):
```python
from test_cli_collect import (
    create_sample_tree,
    import_module,
    parse_json_output,
    run_repo_local,
)
```

**Behavioral assertion style** ([tests/test_collect_observability.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_collect_observability.py:30)):
```python
result = run_repo_local(..., "--json", "--verbose")

assert result.returncode == 0, result.stderr
payload = parse_json_output(result)
assert payload["command"] == "collect"
...
assert "collect summary" in stderr
```

**Copy for Phase 4:** Test lock contention at the CLI boundary the same way: execute the command, assert nonzero exit, parse JSON/stdout contract, and check stderr/journal-oriented failure text without reaching into internals first.

---

### `tests/test_ops_vacuum.py` (test, CRUD)

**Analog:** `tests/test_db_schema.py`

**SQLite assertion pattern** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:149)):
```python
def test_connection_pragmas_enabled(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)

    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
```

**Copy for Phase 4:** Verify vacuum/maintenance through database-observable effects (`page_count`, freelist, file size, free-space advisory fields, WAL checkpoint status fields, failure when lock held) using the same direct-SQL style as existing DB tests.

---

### `tests/test_systemd_units.py` (test, request-response)

**Analog:** `tests/test_cli_collect.py`

**Subprocess/assert-output pattern** ([tests/test_cli_collect.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_collect.py:22)):
```python
def run_repo_local(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = shlex.join(["./watchdirs", *args])
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        env=_command_env(repo_root, env),
        text=True,
        capture_output=True,
        check=False,
    )
```

**File-content assertion style** ([tests/test_cli_collect.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_collect.py:130)):
```python
def test_repo_local_collect_help_matches_module_help(repo_root: Path) -> None:
    repo_local = run_repo_local(repo_root, "collect", "--help")
    module = run_module(repo_root, "collect", "--help")

    assert repo_local.returncode == 0, repo_local.stderr
    assert module.returncode == 0, module.stderr
```

**Copy for Phase 4:** Treat systemd unit tests as repository-file contract tests: read the unit files, assert exact absolute `/usr/local/bin/watchdirs` `ExecStart`, `Type=oneshot`, `Persistent=true`, prune timer `RandomizedDelaySec=300`, and low-priority settings, with no shell interpolation.

## Shared Patterns

### JSON-First CLI Error Handling
**Source:** [src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:1128)
**Apply to:** `src/watchdirs/cli.py`, lock-conflict paths, prune/vacuum command handlers
```python
def emit_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")

def _emit_runtime_error(...):
    ...
    emit_json({"ok": False, "error": error})
```

### Snapshot Write Transaction Boundary
**Source:** [src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:384)
**Apply to:** All mutating commands (`collect`, `prune`, `vacuum`)
```python
connection.execute("BEGIN")
try:
    ...
except Exception:
    connection.rollback()
    raise
else:
    connection.commit()
```

### Whole-Snapshot Cascade Boundary
**Source:** [src/watchdirs/db/schema.sql](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/schema.sql:20)
**Apply to:** `src/watchdirs/db/retention.py`, retention tests
```sql
CREATE TABLE IF NOT EXISTS directory_sizes (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES paths(id),
    parent_id INTEGER REFERENCES paths(id),
    ...
);

CREATE TABLE IF NOT EXISTS snapshot_mounts (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    ...
);
```

### Centralized SQLite Open/PRAGMA Setup
**Source:** [src/watchdirs/db/connection.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/connection.py:16)
**Apply to:** Prune/vacuum commands and DB tests
```python
connection = sqlite3.connect(db_path)
connection.row_factory = sqlite3.Row
...
connection.execute("PRAGMA journal_mode=WAL")
connection.execute("PRAGMA foreign_keys=ON")
connection.execute("PRAGMA busy_timeout=5000")
```

### Low-Priority Execution Precedent
**Source:** [src/watchdirs/bench/duration.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/bench/duration.py:54)
**Apply to:** `ops/systemd/*.service`, README scheduling docs
```python
NICE_BIN = "/usr/bin/nice"
IONICE_BIN = "/usr/bin/ionice"
IONICE_ARGS = ("-c2", "-n7")
```

## No Analog Found

Files with no close in-repo analog; planner should use the concrete systemd guidance already captured in `04-RESEARCH.md`, the absolute `/usr/local/bin/watchdirs` service-command contract, and the low-priority precedent from `src/watchdirs/bench/duration.py`.

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `ops/systemd/watchdirs-collect.service` | config | request-response | Repo has no existing `.service` files or unit tests. |
| `ops/systemd/watchdirs-collect.timer` | config | event-driven | Repo has no existing `.timer` files or timer conventions to copy directly. |
| `ops/systemd/watchdirs-prune.service` | config | request-response | Same service family, but no local unit-file analog exists yet. |
| `ops/systemd/watchdirs-prune.timer` | config | event-driven | Same timer family, but no local timer analog exists yet. |
| `ops/systemd/watchdirs-vacuum.service` | config | request-response | Same service family, but no local unit-file analog exists yet. |
| `ops/systemd/watchdirs-vacuum.timer` | config | event-driven | Same timer family, but no local timer analog exists yet. |

## Metadata

**Analog search scope:** `src/watchdirs/`, `tests/`, `examples/`, `README.md`, prior `.planning/phases/*/*PATTERNS.md`
**Files scanned:** 13
**Pattern extraction date:** 2026-06-17
