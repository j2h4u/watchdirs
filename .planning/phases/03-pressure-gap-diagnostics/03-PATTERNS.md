# Phase 03: Pressure Gap Diagnostics - Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 11
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/watchdirs/cli.py` | controller | request-response | `src/watchdirs/cli.py` | exact |
| `src/watchdirs/models.py` | model | transform | `src/watchdirs/models.py` | exact |
| `src/watchdirs/reporting/queries.py` | service | CRUD | `src/watchdirs/reporting/queries.py` | exact |
| `src/watchdirs/reporting/render.py` | utility | transform | `src/watchdirs/reporting/render.py` | exact |
| `src/watchdirs/diagnostics/df_index.py` | service | request-response | `src/watchdirs/reporting/queries.py` | role-match |
| `src/watchdirs/diagnostics/deleted_open.py` | service | file-I/O | `src/watchdirs/collect/mounts.py` | partial |
| `src/watchdirs/diagnostics/docker.py` | service | request-response | `src/watchdirs/collect/mounts.py` | partial |
| `src/watchdirs/diagnostics/summary.py` | utility | transform | `src/watchdirs/reporting/frontier.py` | partial |
| `tests/test_cli_diagnostics_commands.py` | test | request-response | `tests/test_cli_report_commands.py` | exact |
| `tests/test_diagnostics_queries.py` | test | CRUD | `tests/test_reporting_queries.py` | exact |
| `tests/test_deleted_open.py` / `tests/test_docker_enrichment.py` | test | file-I/O / request-response | `tests/test_mount_policy.py` | role-match |

## Pattern Assignments

### `src/watchdirs/models.py` additions

**Analog:** `src/watchdirs/models.py`

**Dataclass style** ([src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:14)):
```python
@dataclass(frozen=True, slots=True)
class ReportWarning:
    code: str
    message: str
    path: bytes | None = None
```

**Copy forward:**
- Keep Phase 3 models immutable, `slots=True`, and byte-oriented for raw paths.
- Follow the existing split between core records and render-derived helpers like `path_bytes_hex` ([src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:90)).
- Reuse `GroupLabel`, `SnapshotMount`, and `ReportWarning` instead of inventing parallel identity structs.

### `src/watchdirs/cli.py` changes

**Analog:** `src/watchdirs/cli.py`

**Parser registration pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:50)):
```python
report = subparsers.add_parser("report", allow_abbrev=False)
report.add_argument("--db", help="Override the SQLite database path")
report.add_argument("--since", required=True, help="Relative baseline selector such as 24h or 7d")
report.add_argument("--limit", help="Maximum frontier and preview rows to show (default: 20)")
report.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
report.set_defaults(handler=run_report)
```

**DB open + error envelope pattern** ([src/watchdirs/cli.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/cli.py:141)):
```python
db_path = Path(args.db).expanduser() if args.db else default_db_path()
try:
    connection = open_connection(db_path)
except (OSError, sqlite3.Error) as exc:
    return _emit_runtime_error(
        code="database_error",
        message=str(exc),
        as_json=args.json,
        context={"db_path": str(db_path)},
    )
```

**Copy forward:**
- Add `df-vs-index`, `deleted-open-files`, and `docker-enrichment` as sibling subcommands, not `report` flags.
- Keep handlers thin: parse args, open DB if needed, call query/probe helpers, render payload/text, return exit code.
- Reuse `_emit_runtime_error` / `ReportError` handling rather than ad hoc `print` branches.

### `src/watchdirs/reporting/queries.py` changes

**Analog:** `src/watchdirs/reporting/queries.py`

**Validation + typed error pattern** ([src/watchdirs/reporting/queries.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/queries.py:28)):
```python
class ReportError(ValueError):
    def __init__(self, code: str, message: str, **context: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context
```

**Persisted query pattern** ([src/watchdirs/reporting/queries.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/queries.py:171)):
```python
query_rows = connection.execute(
    """
    WITH all_paths AS (
        SELECT path FROM directory_sizes WHERE snapshot_id = :baseline_id
        UNION
        SELECT path FROM directory_sizes WHERE snapshot_id = :current_id
    )
    ...
    """,
    {"baseline_id": pair.baseline.id, "current_id": pair.current.id},
).fetchall()
```

**Mount/storage-domain grouping pattern** ([src/watchdirs/reporting/queries.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/queries.py:119)):
```python
snapshot_mounts = load_snapshot_mounts(connection, snapshot_id) if group_by in {"mount", "storage-domain"} else ()
root_path_bytes = os.fsencode(str(snapshot.root_path))
group, warning = resolve_group_for_path(...)
```

**Copy forward:**
- Keep `df-vs-index` indexed totals sourced from SQLite only; live filesystem totals belong in diagnostics adapters.
- Reuse persisted `snapshot_mounts` for storage-domain attribution.
- Continue explicit `disk_bytes` vs `apparent_bytes` fields; never collapse them into one “size”.

### `src/watchdirs/reporting/render.py` changes

**Analog:** `src/watchdirs/reporting/render.py`

**Path/text escaping boundary** ([src/watchdirs/reporting/render.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/render.py:20)):
```python
def decode_path(path_bytes: bytes) -> str:
    return os.fsdecode(path_bytes)

def _escape_text_field(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")
```

**JSON envelope pattern** ([src/watchdirs/reporting/render.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/render.py:204)):
```python
return {
    "ok": True,
    "command": "report",
    "since": since,
    "limit": limit,
    "effective_limit": effective_limit,
    ...
    "warnings": _dedupe_rendered_warnings(summary.warnings),
}
```

**Text style pattern** ([src/watchdirs/reporting/render.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/render.py:232)):
```python
lines = [
    f"command=report since={since} limit={limit} effective_limit={effective_limit} group_by={group_by}"
]
```

**Copy forward:**
- Decode bytes only in renderers/payload helpers.
- Keep top-level JSON envelope stable: `ok`, `command`, selector/limit fields, bounded arrays, `warnings`.
- Text output should stay terse `key=value`, suitable for agents and shell use.

### `src/watchdirs/diagnostics/df_index.py`

**Closest analog:** `src/watchdirs/reporting/queries.py` + `src/watchdirs/reporting/pairs.py`

**Snapshot selection/warning pattern** ([src/watchdirs/reporting/pairs.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/pairs.py:55)):
```python
warnings.append(
    ReportWarning(
        code="partial_snapshot",
        message=f"root {root_path_text} uses a partial snapshot in the selected pair",
        path=os.fsencode(root_path_text),
    )
)
```

**Implementation direction:**
- Aggregate indexed visible totals from persisted rows grouped through `snapshot_mounts`.
- Produce explicit `unattributed_bytes` and `unattributed_ratio`; do not fabricate directory attribution.
- Carry snapshot age / partial-scan evidence as warning codes or per-filesystem counters.

### `src/watchdirs/diagnostics/deleted_open.py`

**Closest analog:** `src/watchdirs/collect/mounts.py`

**Bytes-first parsing pattern** ([src/watchdirs/collect/mounts.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/mounts.py:12)):
```python
def parse_mountinfo(raw_mountinfo: str | bytes | Iterable[str] | Iterable[bytes]) -> tuple[MountInfo, ...]:
    ...
    left, separator, right = line.partition(b" - ")
```

**Path normalization pattern** ([src/watchdirs/collect/mounts.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/mounts.py:99)):
```python
def _normalize_path_bytes(path_value: str | bytes | Path) -> bytes:
    ...
    return normalized or PATH_SEPARATOR
```

**Copy forward:**
- Parse machine output deterministically with fixed argv and explicit fallbacks.
- Keep raw deleted paths and resolved storage-domain paths as bytes internally where possible.
- Return bounded culprit lists plus warnings/permission-denied counts; no side effects.

### `src/watchdirs/diagnostics/docker.py`

**Closest analog:** `src/watchdirs/collect/mounts.py`

**Pattern to copy:** same adapter style as `mounts.py`: parse external command output into typed records, keep logic separate from CLI/render.

**Implementation direction:**
- One module for subprocess invocation + normalization, not SQL.
- Treat Docker absence/inaccessibility as data, not fatal repo-wide failure.
- Output category totals and verification commands; never prune or mutate Docker state.

### `src/watchdirs/diagnostics/summary.py`

**Closest analog:** `src/watchdirs/reporting/frontier.py`

**Compact prioritization pattern** ([src/watchdirs/reporting/frontier.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/frontier.py:8)):
```python
FRONTIER_DOMINANCE_RATIO = 0.95
```

**Reason-string pattern** ([src/watchdirs/reporting/frontier.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/frontier.py:88)):
```python
return "highest-signal growth target"
```

**Copy forward:**
- Keep summary logic separate from raw probe/query collection.
- Prefer top-N prioritization and concise reason labels over exhaustive sections.
- Emit truncation flags explicitly.

### `tests/test_cli_diagnostics_commands.py`

**Analog:** `tests/test_cli_report_commands.py`

**CLI harness pattern** ([tests/test_cli_report_commands.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_report_commands.py:20)):
```python
def run_module(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    ...
    return subprocess.run(
        ["python3", "-m", "watchdirs", *args],
        ...
        capture_output=True,
        check=False,
    )
```

**SQLite seeding fixture pattern** ([tests/test_cli_report_commands.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_report_commands.py:48), [tests/test_cli_report_commands.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_cli_report_commands.py:101)):
```python
db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
snapshot_id = _seed_snapshot(...)
```

**Copy forward:**
- Reuse the same subprocess harness and JSON parsing helper.
- Seed snapshot rows/mounts directly for CLI contract tests instead of running full collection unless mount persistence itself is under test.

### `tests/test_diagnostics_queries.py`

**Analog:** `tests/test_reporting_queries.py`

**Helper style** ([tests/test_reporting_queries.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_reporting_queries.py:18), [tests/test_reporting_queries.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_reporting_queries.py:70)):
```python
connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
snapshot_id = _seed_snapshot(...)
```

**Assertion style** ([tests/test_reporting_queries.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_reporting_queries.py:153)):
```python
assert [row.current_disk_bytes for row in rows] == [1200, 700, 700, 400]
assert rows[1].current_apparent_bytes != rows[1].current_disk_bytes
```

**Copy forward:**
- Assert exact bytes, exact warning codes, and exact ordering.
- Test `disk_bytes` and `apparent_bytes` separately in diagnostics too.

### `tests/test_deleted_open.py` / `tests/test_docker_enrichment.py`

**Analog:** `tests/test_mount_policy.py`

**Synthetic input builder pattern** ([tests/test_mount_policy.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_mount_policy.py:26)):
```python
def _mountinfo_line(... ) -> str:
    return (
        f"{mount_id} {parent_id} {major_minor} {_escape_mount_path(root)} "
        f"{_escape_mount_path(mount_point)} {options} - "
        f"{filesystem_type} {mount_source} {super_options}"
    )
```

**Byte/path assertions** ([tests/test_mount_policy.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_mount_policy.py:95)):
```python
assert mount.root == b"/"
assert mount.mount_point == b"/tmp/with space"
```

**Copy forward:**
- Prefer synthetic command/procfs fixtures over host-dependent live assertions.
- Validate parsing edge cases, permission-denied cases, and truncation behavior with small deterministic fixtures.

## Shared Patterns

### Path Bytes Handling
**Sources:** [src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:25), [src/watchdirs/reporting/render.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/render.py:20), [src/watchdirs/collect/mounts.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/collect/mounts.py:61)
- Keep raw paths as `bytes` in models and parsers.
- Decode with `os.fsdecode()` only at JSON/text render boundaries.
- Preserve `path_bytes_hex` for exact identity when text decoding is ambiguous.

### Snapshot Mount / Storage-Domain Handling
**Sources:** [src/watchdirs/models.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/models.py:52), [src/watchdirs/reporting/queries.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/queries.py:119), [tests/test_grouping.py](/home/j2h4u/repos/j2h4u/watchdirs/tests/test_grouping.py:147)
- Use persisted `snapshot_mounts`, not live rescans, to explain indexed storage-domain attribution.
- Keep storage-domain identity tied to `major_minor`, `root`, `mount_point`, `filesystem_type`, and `mount_source`.
- Surface unknown/out-of-root mapping as warnings rather than forcing a group.

### Warning and Error Envelope Style
**Sources:** [src/watchdirs/reporting/queries.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/queries.py:28), [src/watchdirs/reporting/pairs.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/pairs.py:69), [src/watchdirs/reporting/render.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/reporting/render.py:57)
- Domain/query errors should be structured with `code`, `message`, and extra context.
- Non-fatal evidence gaps become `ReportWarning`s and are deduped in render output.
- JSON remains the stable contract; text is a terse secondary view.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| none | — | — | Existing Phase 1-2 seams are sufficient; Phase 3 mostly extends them with new diagnostics modules. |

## Metadata

**Analog search scope:** `src/watchdirs/`, `src/watchdirs/reporting/`, `src/watchdirs/collect/`, `tests/`
**Pattern extraction date:** 2026-06-14
