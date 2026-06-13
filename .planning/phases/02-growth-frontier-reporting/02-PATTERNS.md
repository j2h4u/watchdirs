# Phase 02: Growth Frontier Reporting - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 12
**Analogs found:** 12 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/watchdirs/cli.py` | controller | request-response | `src/watchdirs/cli.py` | exact |
| `src/watchdirs/models.py` | model | transform | `src/watchdirs/models.py` | exact |
| `src/watchdirs/db/schema.sql` | migration | CRUD | `src/watchdirs/db/schema.sql` | exact |
| `src/watchdirs/db/migrations.py` | service | CRUD | `src/watchdirs/db/migrations.py` | exact |
| `src/watchdirs/reporting/pairs.py` | utility | transform | `src/watchdirs/config.py` | role-match |
| `src/watchdirs/reporting/queries.py` | service | CRUD | `src/watchdirs/db/migrations.py` | role-match |
| `src/watchdirs/reporting/frontier.py` | utility | transform | `src/watchdirs/collect/scanner.py` | partial |
| `src/watchdirs/reporting/render.py` | utility | request-response | `src/watchdirs/cli.py` | role-match |
| `tests/test_cli_report_commands.py` | test | request-response | `tests/test_cli_collect.py` | exact |
| `tests/test_reporting_queries.py` | test | CRUD | `tests/test_db_schema.py` | role-match |
| `tests/test_frontier.py` | test | transform | `tests/test_scanner_semantics.py` | role-match |
| `tests/test_grouping.py` | test | transform | `tests/test_mount_policy.py` | role-match |

## Pattern Assignments

### `src/watchdirs/cli.py` (controller, request-response)

**Analog:** `src/watchdirs/cli.py`

**Imports + command registration** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:3)):
```python
import argparse
from dataclasses import replace
import json
from pathlib import Path
import signal
import sqlite3
import sys
from typing import Sequence

from .collect.mounts import load_mountinfo
from .collect.scanner import scan_root
from .config import ConfigError, default_db_path, load_config
from .db.connection import open_connection
from .db.migrations import create_snapshot, finalize_snapshot, initialize_database, insert_directory_rows
from .models import ScanResult, ScannerOptions, SnapshotRecord, SnapshotStatus
```

**Subparser pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:20)):
```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="watchdirs", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", allow_abbrev=False)
    collect.add_argument("--config", required=True, help="Path to the TOML watchdirs config file")
    collect.add_argument("--db", help="Override the SQLite database path")
    collect.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    collect.add_argument("--notes", help="Attach free-form notes to the collection run")
    collect.add_argument("--mountinfo", help="Optional mountinfo path accepted for the Phase 01-04 mount policy work")
    collect.set_defaults(handler=run_collect)

    return parser
```

**Handler shape** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:44)):
```python
def run_collect(args: argparse.Namespace) -> int:
    try:
        config = load_config(Path(args.config))
    except ConfigError as exc:
        return _emit_config_error(exc, as_json=args.json)

    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
    except (OSError, sqlite3.Error) as exc:
        if connection is not None:
            connection.close()
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
```

**JSON + stderr rendering helpers** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:185)):
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
        error: dict[str, object] = {
            "code": code,
            "message": message,
        }
        if context:
            error.update(context)
        emit_json({"ok": False, "error": error})
    else:
        detail = f"{code}: {message}"
        if context:
            suffix = ", ".join(f"{key}={value}" for key, value in sorted(context.items()))
            detail = f"{detail} ({suffix})"
        print(detail, file=sys.stderr)
    return 1
```

Use this for all new `diff` / `report` / `top` / `deleted` / `explain-path` command handlers.

---

### `src/watchdirs/models.py` (model, transform)

**Analog:** `src/watchdirs/models.py`

**Dataclass convention** ([src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:14)):
```python
@dataclass(frozen=True, slots=True)
class SnapshotRecord:
    id: int
    started_at: str
    finished_at: str | None
    root_path: Path
    status: SnapshotStatus
    notes: str | None
    error: str | None
```

**Byte-path persistence model** ([src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:25)):
```python
@dataclass(frozen=True, slots=True)
class DirectoryAggregate:
    snapshot_id: int
    path: bytes
    parent_path: bytes | None
    name: bytes
    depth: int
    apparent_bytes: int
    disk_bytes: int
    file_count: int
    dir_count: int
    error: str | None
```

**Existing mount metadata shape** ([src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:39)):
```python
@dataclass(frozen=True, slots=True)
class MountInfo:
    mount_id: int
    parent_id: int
    major_minor: str
    root: bytes
    mount_point: bytes
    options: tuple[str, ...]
    filesystem_type: str
    mount_source: str
    super_options: tuple[str, ...]
```

Add Phase 2 report row / grouping / snapshot-selection dataclasses in this same frozen `slots=True` style.

---

### `src/watchdirs/db/schema.sql` (migration, CRUD)

**Analog:** `src/watchdirs/db/schema.sql`

**Table-first schema pattern** ([src/watchdirs/db/schema.sql](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/schema.sql:1)):
```sql
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    root_path TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS directory_sizes (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path BLOB NOT NULL,
    parent_path BLOB,
    name BLOB NOT NULL,
    depth INTEGER NOT NULL,
    apparent_bytes INTEGER NOT NULL,
    disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    dir_count INTEGER NOT NULL,
    error TEXT
);
```

**Index naming pattern** ([src/watchdirs/db/schema.sql](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/schema.sql:21)):
```sql
CREATE INDEX IF NOT EXISTS directory_sizes_path_snapshot_idx
    ON directory_sizes(path, snapshot_id);

CREATE INDEX IF NOT EXISTS directory_sizes_snapshot_size_idx
    ON directory_sizes(snapshot_id, disk_bytes);

CREATE INDEX IF NOT EXISTS directory_sizes_snapshot_parent_idx
    ON directory_sizes(snapshot_id, parent_path);
```

Extend this file for `snapshot_mounts` and any diff/grouping indexes rather than inventing a separate migration format.

---

### `src/watchdirs/db/migrations.py` (service, CRUD)

**Analog:** `src/watchdirs/db/migrations.py`

**Schema version gate** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:11)):
```python
SCHEMA_VERSION = 1
INSERT_BATCH_SIZE = 10000


def initialize_database(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {user_version} is newer than supported version {SCHEMA_VERSION}"
        )
    if user_version == SCHEMA_VERSION:
        return

    schema_sql = resources.files("watchdirs.db").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema_sql)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
```

**SQLite write helper pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:56)):
```python
def insert_directory_rows(connection, rows: list[DirectoryAggregate] | tuple[DirectoryAggregate, ...]) -> None:
    if not rows:
        connection.commit()
        return

    sql = """
        INSERT INTO directory_sizes (
            snapshot_id,
            path,
            parent_path,
            name,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        connection.executemany(sql, [_directory_row_values(row) for row in batch])
    connection.commit()
```

**Typed row reconstruction pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:81)):
```python
def finalize_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    status: SnapshotStatus,
    notes: str | None = None,
    error: str | None = None,
) -> SnapshotRecord:
    finished_at = _timestamp_now()
    connection.execute(
        """
        UPDATE snapshots
        SET finished_at = ?, status = ?, notes = ?, error = ?
        WHERE id = ?
        """,
        (finished_at, status.value, notes, error, snapshot_id),
    )
    connection.commit()
    row = connection.execute(
        """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    return SnapshotRecord(
        id=int(row["id"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        root_path=Path(row["root_path"]),
        status=SnapshotStatus(row["status"]),
        notes=row["notes"],
        error=row["error"],
    )
```

Use this file for schema-v2 initialization and any insert helpers for persisted snapshot-time mount metadata.

---

### `src/watchdirs/reporting/pairs.py` (utility, transform)

**Analog:** `src/watchdirs/config.py`

**Input normalization + validation helper pattern** ([src/watchdirs/config.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/config.py:63)):
```python
def load_config(path: Path) -> WatchConfig:
    config_path = Path(path).expanduser()
    data = _read_toml(config_path)
    roots = _parse_roots(data, config_path)
    exclude_paths = _parse_exclude_paths(data, config_path)
    mount_policy = _parse_mount_policy(data, config_path)
    validate_roots(roots)
    return WatchConfig(roots=roots, exclude_paths=exclude_paths, mount_policy=mount_policy)
```

**Fail-fast validation style** ([src/watchdirs/config.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/config.py:73)):
```python
def validate_roots(roots: tuple[ConfiguredRoot, ...]) -> None:
    if not roots:
        raise ConfigError("no_roots", "", "configuration must declare at least one root")

    resolved_roots: list[Path] = []
    for root in roots:
        path = root.path
        if not path.exists():
            raise ConfigError("missing_root", str(path), "configured root does not exist")
        if path.is_symlink():
            raise ConfigError("symlink_root", str(path), "configured root must not be a symlink")
        if not path.is_dir():
            raise ConfigError("file_root", str(path), "configured root must be a directory")
```

`pairs.py` should follow this small-helper pattern: normalize inputs, resolve same-root candidates, and raise one explicit error/result when pairing is impossible.

---

### `src/watchdirs/reporting/queries.py` (service, CRUD)

**Analog:** `src/watchdirs/db/migrations.py`

**DB module import shape** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:1)):
```python
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
import sqlite3

from watchdirs.models import DirectoryAggregate, SnapshotRecord, SnapshotStatus
```

**Connection usage pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:15)):
```python
def initialize_database(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    ...
    connection.executescript(schema_sql)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
```

**Binary-path binding pattern** ([src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:118)):
```python
def _directory_row_values(row: DirectoryAggregate) -> tuple[object, ...]:
    return (
        row.snapshot_id,
        sqlite3.Binary(row.path),
        sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
        sqlite3.Binary(row.name),
        row.depth,
        row.apparent_bytes,
        row.disk_bytes,
        row.file_count,
        row.dir_count,
        row.error,
    )
```

`queries.py` should keep raw SQL close to `connection.execute(...)` calls, rely on `sqlite3.Row`, and preserve BLOB path handling at the DB boundary.

---

### `src/watchdirs/reporting/frontier.py` (utility, transform)

**Analog:** `src/watchdirs/collect/scanner.py`

**Tree-aware iterative processing pattern** ([src/watchdirs/collect/scanner.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/scanner.py:25)):
```python
@dataclass(slots=True)
class _Frame:
    path_raw: bytes
    parent_path: bytes | None
    depth: int
    initial_stat: os.stat_result | object | None = None
    directory_identity: tuple[int, int] | None = None
    mount_id: int | None = None
    mount_signature: tuple[str, bytes, bytes] | None = None
    apparent_bytes: int = 0
    disk_bytes: int = 0
    file_count: int = 0
    dir_count: int = 0
    error: str | None = None
```

**Deterministic parent/child traversal shape** ([src/watchdirs/collect/scanner.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/scanner.py:121)):
```python
while stack:
    frame = stack[-1]
    if not frame.initialized:
        ...

    if frame.next_index >= len(frame.entries):
        row = _directory_row(frame)
        stack.pop()
        rows.append(row)
        if stack:
            _merge_child(stack[-1], row)
        continue
```

Use the same deterministic, hierarchy-aware style for frontier pruning: operate on ordered rows, keep parent/child suppression explicit, and avoid recursive ambiguity in the final default diff output.

---

### `src/watchdirs/reporting/render.py` (utility, request-response)

**Analog:** `src/watchdirs/cli.py`

**Stable JSON envelope pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:167)):
```python
payload = {
    "ok": exit_code == 0,
    "command": "collect",
    "db_path": str(db_path),
    "notes": args.notes,
    "mountinfo": args.mountinfo,
    "roots": [str(root.path) for root in config.roots],
    "exclude_paths": [str(path) for path in config.exclude_paths],
    "snapshots": snapshot_payloads,
}

if args.json:
    emit_json(payload)
else:
    print(f"watchdirs collected {len(snapshot_payloads)} snapshot(s)")
```

**Snapshot payload formatter** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:222)):
```python
def _snapshot_payload(snapshot: SnapshotRecord, row_count: int) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_path": str(snapshot.root_path),
        "status": snapshot.status.value,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "notes": snapshot.notes,
        "error": snapshot.error,
        "row_count": row_count,
    }
```

Keep reporting renderers as pure payload/text-format helpers so CLI handlers stay thin.

---

### `tests/test_cli_report_commands.py` (test, request-response)

**Analog:** `tests/test_cli_collect.py`

**CLI execution helpers** ([tests/test_cli_collect.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_collect.py:21)):
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


def run_module(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    ...
    return subprocess.run(
        ["python3", "-m", "watchdirs", *args],
        cwd=repo_root,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )
```

**JSON assertion helper** ([tests/test_cli_collect.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_collect.py:77)):
```python
def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, f"expected JSON on stdout, got stderr={result.stderr!r}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            "stdout was not valid JSON\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}\n"
            f"error={exc}"
        )
    assert isinstance(payload, dict)
    return payload
```

**Command help / contract assertions** ([tests/test_cli_collect.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_collect.py:129)):
```python
def test_repo_local_collect_help_matches_module_help(repo_root: Path) -> None:
    repo_local = run_repo_local(repo_root, "collect", "--help")
    module = run_module(repo_root, "collect", "--help")

    assert repo_local.returncode == 0, repo_local.stderr
    assert module.returncode == 0, module.stderr
    for flag in REQUIRED_FLAGS:
        assert flag in repo_local.stdout
        assert flag in module.stdout
```

Copy this style for new command-contract tests and JSON envelope verification.

---

### `tests/test_reporting_queries.py` (test, CRUD)

**Analog:** `tests/test_db_schema.py`

**Direct sqlite introspection style** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:15)):
```python
def test_snapshot_lifecycle_fields(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    columns = {
        row["name"]: row["type"]
        for row in connection.execute("PRAGMA table_info('snapshots')")
    }
```

**Schema/index assertion pattern** ([tests/test_db_schema.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_db_schema.py:36)):
```python
def test_schema_user_version_and_indexes(repo_root: Path, tmp_path: Path) -> None:
    ...
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    index_names = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='directory_sizes'"
        )
    }

    assert user_version == migrations_module.SCHEMA_VERSION
```

Use this style for diff-query fixtures, classification columns, and `snapshot_mounts` persistence checks.

---

### `tests/test_frontier.py` (test, transform)

**Analog:** `tests/test_scanner_semantics.py`

**Helper-driven semantic tests** ([tests/test_scanner_semantics.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_scanner_semantics.py:16)):
```python
def _scan_result(import_watchdirs_module, root: Path, **option_overrides):
    models = import_watchdirs_module("watchdirs.models")
    scanner = import_watchdirs_module("watchdirs.collect.scanner")
    options = models.ScannerOptions(
        root=root,
        exclude_paths=tuple(option_overrides.pop("exclude_paths", ())),
        mount_policy=option_overrides.pop("mount_policy", ()),
        record_skipped=option_overrides.pop("record_skipped", False),
        hardlink_dedup_max_entries=option_overrides.pop("hardlink_dedup_max_entries", 500000),
        **option_overrides,
    )
    return scanner.scan_root(options)
```

**Tree-shape assertions** ([tests/test_scanner_semantics.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_scanner_semantics.py:52)):
```python
def test_recursive_rows_persisted(import_watchdirs_module, tmp_path: Path) -> None:
    ...
    scan_result = _scan_result(import_watchdirs_module, root)
    rows = _rows_by_path(scan_result.rows)

    assert tuple(row.depth for row in scan_result.rows) == (2, 1, 0)
    assert rows[os.fsencode(root)].parent_path is None
    ...
```

Use the same pattern for frontier pruning tests: build compact fixtures, compute result rows, then assert exact retained/suppressed paths and ordering.

---

### `tests/test_grouping.py` (test, transform)

**Analog:** `tests/test_mount_policy.py`

**Mount fixture builders** ([tests/test_mount_policy.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_mount_policy.py:26)):
```python
def _escape_mount_path(path: Path | str) -> str:
    value = str(path)
    return (
        value.replace("\\", "\\134")
        .replace(" ", "\\040")
        .replace("\n", "\\012")
        .replace("\t", "\\011")
    )


def _mountinfo_line(
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: Path | str,
    mount_point: Path | str,
    filesystem_type: str,
    mount_source: str,
    options: str = "rw",
    super_options: str = "rw",
) -> str:
    return (
        f"{mount_id} {parent_id} {major_minor} {_escape_mount_path(root)} "
        f"{_escape_mount_path(mount_point)} {options} - "
        f"{filesystem_type} {mount_source} {super_options}"
    )
```

**Mount parsing + grouping assertion style** ([tests/test_mount_policy.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_mount_policy.py:95)):
```python
def test_parse_mountinfo_extracts_filesystem_type_and_mountpoint(import_watchdirs_module) -> None:
    mounts = import_watchdirs_module("watchdirs.collect.mounts")

    parsed = mounts.parse_mountinfo(
        _mountinfo_line(
            mount_id=29,
            parent_id=24,
            major_minor="0:42",
            root="/",
            mount_point="/tmp/with space",
            filesystem_type="tmpfs",
            mount_source="tmpfs",
            options="rw,nosuid,nodev",
            super_options="rw,size=1024k,inode64",
        )
        + "\n"
    )
```

Use this for filesystem/storage-domain grouping tests and snapshot-time mount metadata round-trips.

## Shared Patterns

### Connection Setup
**Source:** [src/watchdirs/db/connection.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/connection.py:7)
**Apply to:** All new query helpers and CLI handlers that open SQLite
```python
def open_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection
```

### Byte-Path Boundary
**Source:** [src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:25), [src/watchdirs/db/migrations.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/db/migrations.py:118)
**Apply to:** Reporting queries, explain-path filters, deleted-path output
```python
@dataclass(frozen=True, slots=True)
class DirectoryAggregate:
    snapshot_id: int
    path: bytes
    parent_path: bytes | None
    name: bytes
    ...
```

```python
return (
    row.snapshot_id,
    sqlite3.Binary(row.path),
    sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
    sqlite3.Binary(row.name),
    ...
)
```

Keep raw path values as bytes in storage/query layers and decode only when rendering.

### Mount Grouping Lookup
**Source:** [src/watchdirs/collect/mounts.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/mounts.py:48)
**Apply to:** Filesystem/storage-domain grouping and explain-path mount labeling
```python
def find_mount_for_path(path_value: str | bytes | Path, mounts: tuple[MountInfo, ...]) -> MountInfo | None:
    path_raw = _normalize_path_bytes(path_value)
    best_match: MountInfo | None = None
    best_length = -1

    for mount in mounts:
        mount_point = _normalize_mount_point(mount.mount_point)
        if _path_matches_mount(path_raw, mount_point) and len(mount_point) > best_length:
            best_match = mount
            best_length = len(mount_point)
    return best_match
```

If historical grouping is persisted, keep the same longest-prefix mount matching semantics.

### Error and Status Surfacing
**Source:** [src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:222), [src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:8)
**Apply to:** All report envelopes
```python
class SnapshotStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
```

```python
def _snapshot_payload(snapshot: SnapshotRecord, row_count: int) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_path": str(snapshot.root_path),
        "status": snapshot.status.value,
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "notes": snapshot.notes,
        "error": snapshot.error,
        "row_count": row_count,
    }
```

Phase 2 output should carry snapshot ids, timestamps, statuses, and partial/failure evidence in the same explicit style.

## No Analog Found

None. The repo has no existing reporting package, but every planned file has a usable role-match analog inside the current CLI, DB, scanner, or mount-policy code.

## Metadata

**Analog search scope:** `src/watchdirs/`, `src/watchdirs/collect/`, `src/watchdirs/db/`, `tests/`
**Files scanned:** 14
**Pattern extraction date:** 2026-06-13
