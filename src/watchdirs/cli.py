from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from io import StringIO
from pathlib import Path
from typing import TypedDict, cast

from .collect.mounts import load_mountinfo
from .collect.scanner import scan_root
from .config import ConfigError, ConfiguredRoot, WatchConfig, default_db_path, load_config
from .db.connection import open_connection, open_existing_connection, open_readonly_connection
from .db.migrations import (
    create_snapshot,
    finalize_snapshot,
    initialize_database,
    insert_directory_rows,
    insert_snapshot_mounts,
    load_snapshot_mounts,
)
from .db.retention import PruneResult, RetentionPolicy, VacuumResult, prune_snapshots, vacuum_database
from .diagnostics import (
    build_compact_pressure_summary,
    build_df_index_diagnostic,
    collect_deleted_open_files,
    collect_docker_enrichment,
)
from .diagnostics.df_index import DfIndexProviders
from .models import (
    GroupLabel,
    ReportGroupSummary,
    ReportWarning,
    ScannerOptions,
    SnapshotMount,
    SnapshotPair,
    SnapshotRecord,
    SnapshotStatus,
)
from .ops_lock import OperationLock, OperationLockedError, acquire_operation_lock, operation_lock_path_for_db
from .reporting import (
    ReportError,
    explain_path_breakdown,
    parse_report_limit,
    prune_growth_frontier,
    query_deleted_rows,
    query_diff_rows,
    query_explain_path_rows,
    query_snapshot_summaries,
    query_top_rows,
    render_deleted_open_payload,
    render_deleted_open_text,
    render_deleted_payload,
    render_deleted_text,
    render_df_index_payload,
    render_df_index_text,
    render_diff_payload,
    render_diff_text,
    render_docker_enrichment_payload,
    render_docker_enrichment_text,
    render_explain_path_payload,
    render_explain_path_text,
    render_report_payload,
    render_report_text,
    render_snapshots_payload,
    render_snapshots_text,
    render_top_payload,
    render_top_text,
    resolve_snapshot_pairs,
    resolve_top_snapshot_selection,
    summarize_diff_rows,
)

# D-11 observability: collect logs progress/ETA/summary to stderr ONLY so the
# stdout JSON contract stays pure. These lines land in the systemd journal for
# free under Phase 4's root unit.
_collect_logger = logging.getLogger("watchdirs.collect")


@dataclass(frozen=True, slots=True)
class _CliPaths:
    host_db: Path = Path("/var/lib/watchdirs/watchdirs.sqlite3")
    query_socket: Path = Path("/run/watchdirs/query.sock")


@dataclass(frozen=True, slots=True)
class _CliDefaults:
    command: str = "top"
    since: str = "24h"
    snapshots_limit: str = "10"


@dataclass(frozen=True, slots=True)
class _CliLimits:
    max_explain_depth: int = 20


@dataclass(frozen=True, slots=True)
class _CliQuerySurface:
    allowed_commands: frozenset[str] = frozenset({
        "top",
        "snapshots",
        "diff",
        "report",
        "deleted",
        "explain-path",
        "df-vs-index",
    })


@dataclass(frozen=True, slots=True)
class _CliConfig:
    paths: _CliPaths = field(default_factory=_CliPaths)
    defaults: _CliDefaults = field(default_factory=_CliDefaults)
    limits: _CliLimits = field(default_factory=_CliLimits)
    query: _CliQuerySurface = field(default_factory=_CliQuerySurface)


CLI_CONFIG = _CliConfig()


@dataclass(slots=True)
class _CollectArgs:
    json: bool
    notes: str | None
    mountinfo: str | None
    verbose: bool


@dataclass(slots=True)
class _RetentionArgs:
    db: str | None
    json: bool
    hourly_days: int
    daily_days: int


@dataclass(slots=True)
class _ReportArgs:
    db: str | None
    json: bool
    limit: str | None
    snapshot: str
    since: str
    group_by: str
    depth: str | None
    path: str | None


class _QueryRequest(TypedDict):
    argv: list[str]


class _QueryResponse(TypedDict, total=False):
    stdout: str
    stderr: str
    returncode: int


class _DfStatSpec(TypedDict, total=False):
    size: int
    free: int
    error: bool


def _collect_args(args: argparse.Namespace) -> _CollectArgs:
    return _CollectArgs(
        json=cast(bool, args.json),
        notes=cast(str | None, args.notes),
        mountinfo=cast(str | None, args.mountinfo),
        verbose=cast(bool, args.verbose),
    )


def _retention_args(args: argparse.Namespace) -> _RetentionArgs:
    return _RetentionArgs(
        db=cast(str | None, args.db),
        json=cast(bool, args.json),
        hourly_days=cast(int, args.hourly_days),
        daily_days=cast(int, args.daily_days),
    )


def _report_args(args: argparse.Namespace) -> _ReportArgs:
    return _ReportArgs(
        db=cast(str | None, getattr(args, "db", None)),
        json=cast(bool, getattr(args, "json", False)),
        limit=cast(str | None, getattr(args, "limit", None)),
        snapshot=cast(str, getattr(args, "snapshot", "latest")),
        since=cast(str, getattr(args, "since", CLI_CONFIG.defaults.since)),
        group_by=cast(str, getattr(args, "group_by", "root")),
        depth=cast(str | None, getattr(args, "depth", None)),
        path=cast(str | None, getattr(args, "path", None)),
    )


def configure_collect_logging(verbose: bool) -> None:
    """Bind a stderr StreamHandler to the collect logger (NEVER sys.stdout).

    INFO level when ``verbose`` so progress/summary lines emit; WARNING otherwise
    (errors only). Idempotent: a second call does not stack duplicate handlers.
    """

    for existing in _collect_logger.handlers:
        if isinstance(existing, logging.StreamHandler) and existing.stream is sys.stderr:
            _collect_logger.setLevel(logging.INFO if verbose else logging.WARNING)
            return
    handler = logging.StreamHandler(sys.stderr)  # NEVER sys.stdout — keeps the JSON contract pure.
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _collect_logger.addHandler(handler)
    _collect_logger.setLevel(logging.INFO if verbose else logging.WARNING)


def compute_eta(
    *,
    dirs_done: int,
    dirs_total_estimate: int | None,
    elapsed: float,
) -> tuple[float, float | None]:
    """Return ``(rate, eta)`` from the dirs-scanned rate over ``elapsed`` seconds.

    ``rate`` is dirs/second (0.0 when no time has elapsed). ``eta`` is the
    remaining-seconds estimate, derived purely from the rate, and is ``None`` when
    there is no total estimate or no measurable rate (A4: rate-only on first scan).
    Caller supplies ``elapsed`` from a monotonic clock so this stays deterministic
    and testable without sleeps.
    """

    rate = dirs_done / elapsed if elapsed > 0 else 0.0
    eta = (dirs_total_estimate - dirs_done) / rate if dirs_total_estimate and rate else None
    return rate, eta


def log_progress(
    dirs_done: int,
    dirs_total_estimate: int | None,
    *,
    elapsed: float,
) -> None:
    """Emit one INFO progress line (dirs scanned, rate, ETA) to stderr."""

    rate, eta = compute_eta(
        dirs_done=dirs_done,
        dirs_total_estimate=dirs_total_estimate,
        elapsed=elapsed,
    )
    _collect_logger.info(
        "scanned %d dirs, %.0f dirs/s%s",
        dirs_done,
        rate,
        f", ETA {eta:.0f}s" if eta is not None else "",
    )


def log_summary(dirs: int, duration_s: float, db_bytes: int) -> None:
    """Emit one structured end-summary record (dirs/duration/db_bytes) to stderr."""

    _collect_logger.info(
        "collect summary dirs=%d duration_s=%.2f db_bytes=%d",
        dirs,
        duration_s,
        db_bytes,
    )


def _database_byte_size(connection: sqlite3.Connection) -> int:
    """Live on-disk DB size via ``page_count`` x ``page_size`` (WAL-mode, not VACUUMed)."""

    page_count_row = cast(tuple[int, ...], connection.execute("PRAGMA page_count").fetchone())
    page_size_row = cast(tuple[int, ...], connection.execute("PRAGMA page_size").fetchone())
    assert page_count_row is not None
    assert page_size_row is not None
    page_count = int(page_count_row[0])
    page_size = int(page_size_row[0])
    return page_count * page_size


def _previous_row_count_for_root(connection: sqlite3.Connection, root_path: Path) -> int | None:
    """ETA seed (A4): directory_sizes count of the latest COMPLETE snapshot for this root.

    Returns ``None`` on the first scan for a root (rate-only ETA). Best-effort: any
    DB error degrades to no estimate rather than failing the collect.
    """

    try:
        row = cast(
            sqlite3.Row | None,
            connection.execute(
                """
            SELECT COUNT(*) AS row_count
            FROM directory_sizes ds
            WHERE ds.snapshot_id = (
                SELECT id FROM snapshots
                WHERE root_path = ? AND status = ?
                ORDER BY id DESC
                LIMIT 1
            )
            """,
                (str(root_path), SnapshotStatus.COMPLETE.value),
            ).fetchone(),
        )
    except sqlite3.Error:
        return None
    if row is None:
        return None
    count = int(cast(int, row["row_count"]))
    return count or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="watchdirs", allow_abbrev=False)
    subparsers = parser.add_subparsers(dest="command")
    _add_collect_parser(subparsers)
    _add_prune_parser(subparsers)
    _add_vacuum_parser(subparsers)
    _add_top_parser(subparsers)
    _add_snapshots_parser(subparsers)
    _add_diff_parser(subparsers)
    _add_report_parser(subparsers)
    _add_deleted_parser(subparsers)
    _add_explain_path_parser(subparsers)
    _add_df_vs_index_parser(subparsers)
    _add_deleted_open_parser(subparsers)
    _add_docker_enrichment_parser(subparsers)
    _add_query_server_parser(subparsers)

    return parser


def _add_collect_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    collect = subparsers.add_parser("collect", allow_abbrev=False)
    collect.add_argument("--config", required=True, help="Path to the TOML watchdirs config file")
    collect.add_argument("--db", help="Override the SQLite database path")
    collect.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    collect.add_argument("--notes", help="Attach free-form notes to the collection run")
    collect.add_argument("--mountinfo", help="Optional mountinfo path accepted for the Phase 01-04 mount policy work")
    collect.add_argument(
        "--verbose",
        action="store_true",
        help="Emit INFO progress (dirs/rate/ETA) and a summary record to stderr (stdout stays pure JSON)",
    )
    collect.set_defaults(handler=run_collect)


def _add_prune_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    prune = subparsers.add_parser("prune", allow_abbrev=False)
    prune.add_argument("--db", help="Override the SQLite database path")
    prune.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    prune.add_argument(
        "--hourly-days",
        type=int,
        default=14,
        help="Keep all snapshot statuses newer than this many days (default: 14)",
    )
    prune.add_argument(
        "--daily-days",
        type=int,
        default=90,
        help="Keep one COMPLETE snapshot per UTC day through this many days (default: 90)",
    )
    prune.set_defaults(handler=run_prune)


def _add_vacuum_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    vacuum = subparsers.add_parser("vacuum", allow_abbrev=False)
    vacuum.add_argument("--db", help="Override the SQLite database path")
    vacuum.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    vacuum.set_defaults(handler=run_vacuum)


def _add_top_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    top = subparsers.add_parser("top", allow_abbrev=False)
    top.add_argument("--db", help="Override the SQLite database path")
    top.add_argument("--snapshot", default="latest", help="Snapshot selector: latest or numeric snapshot id")
    top.add_argument("--limit", help="Maximum rows to show per selected snapshot (default: 20)")
    top.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    top.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for top rows",
    )
    top.set_defaults(handler=run_top)


def _add_snapshots_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    snapshots = subparsers.add_parser("snapshots", allow_abbrev=False)
    snapshots.add_argument("--db", help="Override the SQLite database path")
    snapshots.add_argument(
        "--limit",
        default=CLI_CONFIG.defaults.snapshots_limit,
        help=f"Maximum snapshots to show (default: {CLI_CONFIG.defaults.snapshots_limit})",
    )
    snapshots.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    snapshots.set_defaults(handler=run_snapshots)


def _add_diff_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    diff = subparsers.add_parser("diff", allow_abbrev=False)
    diff.add_argument("--db", help="Override the SQLite database path")
    diff.add_argument(
        "--since",
        default=CLI_CONFIG.defaults.since,
        help=f"Relative baseline selector such as 24h or 7d (default: {CLI_CONFIG.defaults.since})",
    )
    diff.add_argument("--limit", help="Maximum frontier rows to show after global pruning (default: 20)")
    diff.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    diff.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for diff rows",
    )
    diff.set_defaults(handler=run_diff)


def _add_report_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    report = subparsers.add_parser("report", allow_abbrev=False)
    report.add_argument("--db", help="Override the SQLite database path")
    report.add_argument(
        "--since",
        default=CLI_CONFIG.defaults.since,
        help=f"Relative baseline selector such as 24h or 7d (default: {CLI_CONFIG.defaults.since})",
    )
    report.add_argument("--limit", help="Maximum frontier and preview rows to show (default: 20)")
    report.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    report.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for report rows",
    )
    report.set_defaults(handler=run_report)


def _add_deleted_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    deleted = subparsers.add_parser("deleted", allow_abbrev=False)
    deleted.add_argument("--db", help="Override the SQLite database path")
    deleted.add_argument(
        "--since",
        default=CLI_CONFIG.defaults.since,
        help=f"Relative baseline selector such as 24h or 7d (default: {CLI_CONFIG.defaults.since})",
    )
    deleted.add_argument("--limit", help="Maximum deleted rows to show (default: 20)")
    deleted.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    deleted.set_defaults(handler=run_deleted)


def _add_explain_path_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    explain = subparsers.add_parser("explain-path", allow_abbrev=False)
    explain.add_argument("path", help="Exact indexed path to explain")
    explain.add_argument("--db", help="Override the SQLite database path")
    explain.add_argument(
        "--since",
        default=CLI_CONFIG.defaults.since,
        help=f"Relative baseline selector such as 24h or 7d (default: {CLI_CONFIG.defaults.since})",
    )
    explain.add_argument("--limit", help="Maximum immediate children to show (default: 20)")
    explain.add_argument("--depth", help="Descendant depth to show below the target (default: 1)")
    explain.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    explain.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for explain-path rows",
    )
    explain.set_defaults(handler=run_explain_path)


def _add_df_vs_index_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    df_vs_index = subparsers.add_parser("df-vs-index", allow_abbrev=False)
    df_vs_index.add_argument("--db", help="Override the SQLite database path")
    df_vs_index.add_argument("--snapshot", default="latest", help="Snapshot selector: latest or numeric snapshot id")
    df_vs_index.add_argument("--limit", help="Maximum filesystem sections to show (default: 20)")
    df_vs_index.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    df_vs_index.set_defaults(handler=run_df_vs_index)


def _add_deleted_open_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    deleted_open = subparsers.add_parser("deleted-open-files", allow_abbrev=False)
    deleted_open.add_argument(
        "--db",
        help="Optional SQLite database used to resolve deleted paths to a storage-domain",
    )
    deleted_open.add_argument("--limit", help="Maximum culprit rows to show (default: 20)")
    deleted_open.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    deleted_open.set_defaults(handler=run_deleted_open_files)


def _add_docker_enrichment_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    docker_enrichment = subparsers.add_parser("docker-enrichment", allow_abbrev=False)
    docker_enrichment.add_argument(
        "--db",
        help="Optional SQLite database used to surface indexed Docker/containerd path hints",
    )
    docker_enrichment.add_argument("--limit", help="Maximum build-cache entries to show (default: 20)")
    docker_enrichment.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    docker_enrichment.set_defaults(handler=run_docker_enrichment)


def _add_query_server_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    query_server = subparsers.add_parser("query-server", allow_abbrev=False, help=argparse.SUPPRESS)
    query_server.set_defaults(handler=run_query_server)


def main(argv: Sequence[str] | None = None, *, allow_proxy: bool = True) -> int:
    effective_argv = tuple(sys.argv[1:] if argv is None else argv)
    if not effective_argv:
        effective_argv = (CLI_CONFIG.defaults.command,)
    parser = build_parser()
    args = cast(argparse.Namespace, parser.parse_args(effective_argv))
    if allow_proxy and _should_proxy_query(args):
        return _proxy_query(effective_argv)
    handler = cast(Callable[[argparse.Namespace], int] | None, args.handler)
    if handler is None:
        parser.error("no command selected")
    return handler(args)


def _query_socket_path() -> Path:
    configured = os.environ.get("WATCHDIRS_QUERY_SOCKET")
    if configured:
        return Path(configured).expanduser()
    return CLI_CONFIG.paths.query_socket


def _should_proxy_query(args: argparse.Namespace) -> bool:
    if os.geteuid() == 0:
        return False
    if cast(str | None, args.command) not in CLI_CONFIG.query.allowed_commands:
        return False
    db_arg = cast(str | None, args.db)
    return db_arg is None or Path(db_arg).expanduser() == CLI_CONFIG.paths.host_db


def _proxy_query(argv: Sequence[str]) -> int:
    socket_path = _query_socket_path()
    request = json.dumps({"argv": list(argv)}, separators=(",", ":")).encode("utf-8") + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(socket_path))
            client.sendall(request)
            client.shutdown(socket.SHUT_WR)
            response_bytes = _read_all(client)
    except OSError as exc:
        sys.stderr.write(f"watchdirs query service unavailable: {exc}\n")
        return 1

    try:
        response = _validated_query_response(cast(object, json.loads(response_bytes.decode("utf-8"))))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"watchdirs query service returned invalid response: {exc}\n")
        return 1

    stdout = response.get("stdout")
    stderr = response.get("stderr")
    returncode = response.get("returncode")
    if isinstance(stdout, str):
        sys.stdout.write(stdout)
    if isinstance(stderr, str):
        sys.stderr.write(stderr)
    if isinstance(returncode, int):
        return returncode
    sys.stderr.write("watchdirs query service returned invalid status\n")
    return 1


def _read_all(client: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _validated_query_response(response: object) -> _QueryResponse:
    if not isinstance(response, dict):
        raise ValueError("response must be a JSON object")

    validated: _QueryResponse = {}
    stdout = response.get("stdout")
    if stdout is not None:
        if not isinstance(stdout, str):
            raise ValueError("response stdout must be a string")
        validated["stdout"] = stdout

    stderr = response.get("stderr")
    if stderr is not None:
        if not isinstance(stderr, str):
            raise ValueError("response stderr must be a string")
        validated["stderr"] = stderr

    returncode = response.get("returncode")
    if returncode is not None:
        if not isinstance(returncode, int):
            raise ValueError("response returncode must be an integer")
        validated["returncode"] = returncode

    return validated


def run_query_server(_args: argparse.Namespace) -> int:
    try:
        request = _validated_query_request(cast(object, json.loads(sys.stdin.buffer.readline().decode("utf-8"))))
        argv = _validated_query_argv(request)
        argv = _with_forced_host_db(argv)
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            returncode = main(argv, allow_proxy=False)
        response = {
            "returncode": returncode,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
        }
    except Exception as exc:  # noqa: BLE001 - query server must return JSON errors, not crash socket activation.
        response = {
            "returncode": 1,
            "stdout": "",
            "stderr": f"watchdirs query error: {exc}\n",
        }
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    return 0


def _validated_query_request(request: object) -> _QueryRequest:
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    raw_argv = request.get("argv")
    if not isinstance(raw_argv, list) or not raw_argv:
        raise ValueError("request argv must be a non-empty list")
    if not all(isinstance(item, str) for item in raw_argv):
        raise ValueError("request argv items must be strings")
    return {"argv": [cast(str, item) for item in raw_argv]}


def _validated_query_argv(request: _QueryRequest) -> tuple[str, ...]:
    argv = tuple(request["argv"])
    command = argv[0]
    if command not in CLI_CONFIG.query.allowed_commands:
        raise ValueError(f"command is not allowed through query service: {command}")
    if "--db" in argv:
        raise ValueError("query service always uses the host watchdirs database")
    return argv


def _with_forced_host_db(argv: tuple[str, ...]) -> tuple[str, ...]:
    return (argv[0], "--db", str(CLI_CONFIG.paths.host_db), *argv[1:])


@dataclass(slots=True)
class CollectRootContext:
    config: WatchConfig
    args: _CollectArgs
    collect_start: float
    active_snapshot_ids: set[int]


def _collect_single_root(
    connection: sqlite3.Connection,
    configured_root: ConfiguredRoot,
    context: CollectRootContext,
) -> tuple[SnapshotRecord, int]:
    snapshot = create_snapshot(connection, configured_root.path, notes=context.args.notes)
    context.active_snapshot_ids.add(snapshot.id)
    try:
        # A4: seed the ETA estimate from the previous COMPLETE snapshot for this
        # root (rate-only on the first scan). Read before inserting the new rows.
        eta_estimate = _previous_row_count_for_root(connection, configured_root.path)
        mounts = load_mountinfo(context.args.mountinfo or "/proc/self/mountinfo")
        scan_result = scan_root(
            ScannerOptions(
                root=configured_root.path,
                exclude_paths=context.config.exclude_paths,
                mounts=mounts,
                mount_policy=context.config.mount_policy,
                collapse_policy=context.config.collapse_policy,
                record_skipped=True,
            )
        )
        persisted_rows = [replace(row, snapshot_id=snapshot.id) for row in scan_result.rows]
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
                notes=context.args.notes,
                error=scan_result.fatal_error,
                commit=False,
            )
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        # Bounded progress cadence: one line per scanned root (the single-pass
        # os.scandir walk yields no mid-walk hook), never per-row (T-03.1-05-03).
        log_progress(
            scan_result.row_count,
            eta_estimate,
            elapsed=time.monotonic() - context.collect_start,
        )
        return finalized, scan_result.row_count
    except CollectionInterruptedError:
        raise
    except Exception as exc:  # noqa: BLE001 - collection records partial failure evidence.
        connection.rollback()
        finalized = finalize_snapshot(
            connection,
            snapshot.id,
            status=SnapshotStatus.FAILED,
            notes=context.args.notes,
            error=str(exc),
        )
        return finalized, 0
    finally:
        context.active_snapshot_ids.discard(snapshot.id)


def _make_collect_interrupt_handler(
    connection: sqlite3.Connection,
    active_snapshot_ids: set[int],
):
    def _handle_interrupt(signum: int, _frame: object | None) -> None:
        error = f"collection interrupted by signal {signal.Signals(signum).name}"
        connection.rollback()
        for snapshot_id in list(active_snapshot_ids):
            finalize_snapshot(
                connection,
                snapshot_id,
                status=SnapshotStatus.FAILED,
                error=error,
            )
        raise CollectionInterruptedError(signum, error)

    return _handle_interrupt


def _install_collect_signal_handlers(
    connection: sqlite3.Connection,
    active_snapshot_ids: set[int],
) -> dict[int, object]:
    original_handlers: dict[int, object] = {}
    handler = _make_collect_interrupt_handler(connection, active_snapshot_ids)
    for signum in (signal.SIGINT, signal.SIGTERM):
        original_handlers[signum] = signal.getsignal(signum)
        signal.signal(signum, cast(signal.Handlers, handler))
    return original_handlers


def _restore_collect_signal_handlers(original_handlers: dict[int, object]) -> None:
    for signum, handler in original_handlers.items():
        signal.signal(signum, cast(signal.Handlers, handler))


def _emit_collect_interrupt(
    *,
    args: _CollectArgs,
    db_path: Path,
    config: WatchConfig,
    snapshot_payloads: list[dict[str, object]],
    exc: CollectionInterruptedError,
) -> int:
    if args.json:
        emit_json({
            "ok": False,
            "command": "collect",
            "db_path": str(db_path),
            "notes": args.notes,
            "mountinfo": args.mountinfo,
            "roots": [str(root.path) for root in config.roots],
            "exclude_paths": [str(path) for path in config.exclude_paths],
            "error": {
                "code": "collection_interrupted",
                "message": exc.message,
            },
            "snapshots": snapshot_payloads,
        })
    return 128 + exc.signum


def _run_collect_operation(
    connection: sqlite3.Connection,
    config: WatchConfig,
    args: _CollectArgs,
    db_path: Path,
    collect_start: float,
) -> int:
    active_snapshot_ids: set[int] = set()
    original_handlers: dict[int, object] = {}
    exit_code = 0
    total_dirs = 0
    snapshot_payloads: list[dict[str, object]] = []
    root_context = CollectRootContext(
        config=config,
        args=args,
        collect_start=collect_start,
        active_snapshot_ids=active_snapshot_ids,
    )

    try:
        original_handlers = _install_collect_signal_handlers(connection, active_snapshot_ids)

        for configured_root in config.roots:
            try:
                finalized, row_count = _collect_single_root(connection, configured_root, root_context)
            except (OSError, sqlite3.Error) as error:
                return _emit_runtime_error(
                    code="database_error",
                    message=str(error),
                    as_json=args.json,
                    context={
                        "db_path": str(db_path),
                        "root_path": str(configured_root.path),
                    },
                )
            snapshot_payloads.append(_snapshot_payload(finalized, row_count))
            total_dirs += row_count
            if finalized.status is not SnapshotStatus.COMPLETE:
                exit_code = 1
    except CollectionInterruptedError as exc:
        return _emit_collect_interrupt(
            args=args,
            db_path=db_path,
            config=config,
            snapshot_payloads=snapshot_payloads,
            exc=exc,
        )
    finally:
        _restore_collect_signal_handlers(original_handlers)
        try:
            db_bytes = _database_byte_size(connection)
        except sqlite3.Error:
            db_bytes = 0
        log_summary(total_dirs, time.monotonic() - collect_start, db_bytes)
        connection.close()

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
    return exit_code


def run_collect(args: argparse.Namespace) -> int:
    collect_args = _collect_args(args)
    configure_collect_logging(collect_args.verbose)
    collect_start = time.monotonic()

    try:
        config: WatchConfig = load_config(Path(cast(str, args.config)))
    except ConfigError as exc:
        return _emit_config_error(exc, as_json=collect_args.json)

    db_arg = cast(str | None, args.db)
    db_path = Path(db_arg).expanduser() if db_arg else default_db_path()
    lock_path = operation_lock_path_for_db(db_path)
    try:
        operation_lock = acquire_operation_lock(lock_path)
    except OperationLockedError as exc:
        return _emit_runtime_error(
            code="operation_locked",
            message=str(exc),
            as_json=collect_args.json,
            context={
                "db_path": str(db_path),
                "lock_path": str(exc.lock_path),
            },
        )
    except OSError as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=collect_args.json,
            context={
                "db_path": str(db_path),
                "lock_path": str(lock_path),
            },
        )

    return _run_locked_collect_operation(
        operation_lock=operation_lock,
        db_path=db_path,
        config=config,
        args=collect_args,
        collect_start=collect_start,
    )


def _run_locked_collect_operation(
    *,
    operation_lock: OperationLock,
    db_path: Path,
    config: WatchConfig,
    args: _CollectArgs,
    collect_start: float,
) -> int:
    connection = None
    result: int | None = None
    with operation_lock:
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
        result = _run_collect_operation(connection, config, args, db_path, collect_start)
    assert result is not None
    return result


def run_prune(args: argparse.Namespace) -> int:
    prune_args = _retention_args(args)
    db_path = Path(prune_args.db).expanduser() if prune_args.db else default_db_path()
    try:
        policy = RetentionPolicy(
            hourly_days=prune_args.hourly_days,
            daily_days=prune_args.daily_days,
        )
    except ValueError as exc:
        return _emit_runtime_error(
            code="invalid_retention_policy",
            message=str(exc),
            as_json=prune_args.json,
            context={
                "hourly_days": prune_args.hourly_days,
                "daily_days": prune_args.daily_days,
            },
        )

    if not db_path.is_file():
        return _emit_runtime_error(
            code="database_error",
            message=f"watchdirs database does not exist: {db_path}",
            as_json=prune_args.json,
            context={"db_path": str(db_path)},
        )

    lock_path = operation_lock_path_for_db(db_path)
    connection = None
    try:
        operation_lock = acquire_operation_lock(lock_path)
    except OperationLockedError as exc:
        return _emit_runtime_error(
            code="operation_locked",
            message=str(exc),
            as_json=prune_args.json,
            context={
                "db_path": str(db_path),
                "lock_path": str(exc.lock_path),
            },
        )
    except OSError as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=prune_args.json,
            context={
                "db_path": str(db_path),
                "lock_path": str(lock_path),
            },
        )

    result: PruneResult | None = None
    with operation_lock:
        try:
            connection = open_existing_connection(db_path)
            initialize_database(connection)
            result = prune_snapshots(connection, policy)
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            return _emit_runtime_error(
                code="database_error",
                message=str(exc),
                as_json=prune_args.json,
                context={"db_path": str(db_path)},
            )
        finally:
            if connection is not None:
                connection.close()

    assert result is not None
    payload = _prune_payload(result, db_path, policy)
    if prune_args.json:
        emit_json(payload)
    else:
        print(
            f"watchdirs pruned {result.deleted_snapshot_count} snapshot(s), retained {result.retained_snapshot_count}"
        )
    return 0


def run_vacuum(args: argparse.Namespace) -> int:
    vacuum_json = cast(bool, args.json)
    db_arg = cast(str | None, args.db)
    db_path = Path(db_arg).expanduser() if db_arg else default_db_path()
    if not db_path.is_file():
        return _emit_runtime_error(
            code="database_error",
            message=f"watchdirs database does not exist: {db_path}",
            as_json=vacuum_json,
            context={"db_path": str(db_path)},
        )

    lock_path = operation_lock_path_for_db(db_path)
    connection = None
    try:
        operation_lock = acquire_operation_lock(lock_path)
    except OperationLockedError as exc:
        return _emit_runtime_error(
            code="operation_locked",
            message=str(exc),
            as_json=vacuum_json,
            context={
                "db_path": str(db_path),
                "lock_path": str(exc.lock_path),
            },
        )
    except OSError as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=vacuum_json,
            context={
                "db_path": str(db_path),
                "lock_path": str(lock_path),
            },
        )

    result: VacuumResult | None = None
    with operation_lock:
        try:
            connection = open_existing_connection(db_path)
            initialize_database(connection)
            result = vacuum_database(connection, db_path)
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            return _emit_runtime_error(
                code="database_error",
                message=str(exc),
                as_json=vacuum_json,
                context={"db_path": str(db_path)},
            )
        finally:
            if connection is not None:
                connection.close()

    assert result is not None
    payload = _vacuum_payload(result, db_path)
    if vacuum_json:
        emit_json(payload)
    else:
        print(f"watchdirs vacuumed database {result.db_bytes_before} -> {result.db_bytes_after} bytes")
    return 0


def run_top(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        snapshots = resolve_top_snapshot_selection(connection, report_args.snapshot)

        sections: list[dict[str, object]] = []
        for snapshot in snapshots:
            row_warnings = list(_snapshot_status_warnings(snapshot))
            rows, query_warnings = query_top_rows(
                connection,
                snapshot_id=snapshot.id,
                limit=effective_limit,
                group_by=report_args.group_by,
            )
            row_warnings.extend(query_warnings)
            sections.append({
                "snapshot": snapshot,
                "warnings": tuple(_dedupe_warnings(row_warnings)),
                "rows": rows,
            })

        if report_args.json:
            emit_json(
                render_top_payload(
                    snapshot_selector=report_args.snapshot,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    sections=sections,
                )
            )
        else:
            sys.stdout.write(
                render_top_text(
                    snapshot_selector=report_args.snapshot,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    sections=sections,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_snapshots(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        snapshots = query_snapshot_summaries(connection, limit=effective_limit)

        if report_args.json:
            emit_json(render_snapshots_payload(limit=effective_limit, snapshots=snapshots))
        else:
            sys.stdout.write(render_snapshots_text(limit=effective_limit, snapshots=snapshots))
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_diff(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=report_args.since)

        diff_rows = []
        warnings = list(pair_warnings)
        classification_counts: dict[str, int] = {}
        for pair in pairs:
            rows, query_warnings = query_diff_rows(connection, pair=pair, group_by=report_args.group_by)
            diff_rows.extend(rows)
            warnings.extend(query_warnings)
            for row in rows:
                classification_counts[row.classification] = classification_counts.get(row.classification, 0) + 1

        frontier_rows = prune_growth_frontier(diff_rows)[:effective_limit]

        if report_args.json:
            emit_json(
                render_diff_payload(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    pairs=pairs,
                    rows=frontier_rows,
                    classification_counts=classification_counts,
                    warnings=tuple(_dedupe_warnings(warnings)),
                )
            )
        else:
            sys.stdout.write(
                render_diff_text(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    pairs=pairs,
                    rows=frontier_rows,
                    warnings=tuple(_dedupe_warnings(warnings)),
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_report(args: argparse.Namespace) -> int:  # noqa: PLR0914 - report assembly is intentionally large.
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=report_args.since)

        diff_rows = []
        deleted_rows = []
        warnings = list(pair_warnings)
        for pair in pairs:
            rows, query_warnings = query_diff_rows(connection, pair=pair, group_by=report_args.group_by)
            diff_rows.extend(rows)
            warnings.extend(query_warnings)
            deleted_for_pair, deleted_warnings = query_deleted_rows(
                connection,
                pair=pair,
                limit=1000,
                group_by=report_args.group_by,
            )
            deleted_rows.extend(deleted_for_pair)
            warnings.extend(deleted_warnings)

        frontier_rows = prune_growth_frontier(diff_rows)[:effective_limit]
        deleted_rows = sorted(deleted_rows, key=lambda row: (-row.previous_disk_bytes, row.path))[:effective_limit]
        summary = summarize_diff_rows(
            snapshot_pairs=pairs,
            diff_rows=tuple(diff_rows),
            frontier_rows=frontier_rows,
            deleted_rows=tuple(deleted_rows),
            warnings=tuple(_dedupe_warnings(warnings)),
        )

        # Cheap report-time df/index reconciliation: statvfs is probed only for the
        # indexed storage-domains (never every live mount), and no deleted-open or
        # Docker probes run automatically. Per-domain stat failures are isolated by
        # build_df_index_diagnostic so a stale mountpoint cannot crash the report.
        pressure_summary = _build_report_pressure_summary(
            connection,
            limit=effective_limit,
            report_groups=summary.groups if report_args.group_by == "storage-domain" else (),
        )

        if report_args.json:
            emit_json(
                render_report_payload(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    summary=summary,
                    pressure_summary=pressure_summary,
                )
            )
        else:
            sys.stdout.write(
                render_report_text(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=report_args.group_by,
                    summary=summary,
                    pressure_summary=pressure_summary,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def _build_report_pressure_summary(
    connection: sqlite3.Connection,
    *,
    limit: int,
    report_groups: tuple[ReportGroupSummary, ...] = (),
):
    """Build the compact pressure summary for the report command.

    Runs only the cheap df/index reconciliation (statvfs scoped to indexed
    storage-domains) plus pure summary transformation. No lsof or Docker probes
    run here; deleted-open and Docker evidence stay behind their explicit commands.

    ``report_groups`` carries the report's storage-domain ReportGroupSummary rows
    so recent-growth evidence can be joined onto the matching df/index domains.
    Callers must only pass storage-domain-keyed groups (the key formats must
    match); for other groupings they pass ``()``.
    """

    stat_provider = _report_stat_provider()
    providers = DfIndexProviders(stat_provider=stat_provider) if stat_provider is not None else DfIndexProviders()
    try:
        df_index = build_df_index_diagnostic(
            connection,
            snapshot_selector="latest",
            limit=limit,
            providers=providers,
        )
    except ReportError:
        # No usable snapshots means there is nothing to reconcile; the report still
        # renders its Phase 2 sections without diagnostic hints.
        return None

    return build_compact_pressure_summary(df_index=df_index, report_groups=report_groups)


def _report_stat_provider():
    """Return the statvfs provider for the report df/index reconciliation.

    Defaults to the live host. The WATCHDIRS_TEST_DF_STAT_JSON env var exists only
    so deterministic tests can pin per-mountpoint df totals (or force an OSError for
    a stale/absent mountpoint) without touching the live filesystem.
    """

    raw = os.environ.get("WATCHDIRS_TEST_DF_STAT_JSON")
    if raw is None:
        return None  # build_df_index_diagnostic uses its live default.

    mapping = cast(dict[str, _DfStatSpec], json.loads(raw))
    record_path = os.environ.get("WATCHDIRS_TEST_DF_STAT_RECORD")

    def provider(path_bytes: bytes) -> os.statvfs_result:
        text = os.fsdecode(path_bytes)
        if record_path:
            with Path(record_path).open("a", encoding="ascii") as handle:
                handle.write(text + "\n")
        spec = mapping.get(text)
        if spec is None or spec.get("error"):
            raise OSError(f"injected statvfs failure for {text}")
        size = spec.get("size")
        free = spec.get("free")
        if not isinstance(size, int) or not isinstance(free, int):
            raise ValueError("response size/free must be integers")
        return cast(os.statvfs_result, _FakeStatvfs(size=size, free=free))

    return provider


class _FakeStatvfs:
    """Minimal statvfs-result stand-in for the deterministic report test seam."""

    __slots__ = ("f_bavail", "f_bfree", "f_blocks", "f_frsize")

    def __init__(self, *, size: int, free: int) -> None:
        self.f_frsize = 1
        self.f_blocks = size
        self.f_bfree = free
        self.f_bavail = free


def run_deleted(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=report_args.since)

        deleted_rows = []
        warnings = list(pair_warnings)
        for pair in pairs:
            rows, query_warnings = query_deleted_rows(connection, pair=pair, limit=1000)
            deleted_rows.extend(rows)
            warnings.extend(query_warnings)
        deleted_rows = tuple(
            sorted(deleted_rows, key=lambda row: (-row.previous_disk_bytes, row.path))[:effective_limit]
        )

        if report_args.json:
            emit_json(
                render_deleted_payload(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    pairs=pairs,
                    warnings=tuple(_dedupe_warnings(warnings)),
                    rows=deleted_rows,
                )
            )
        else:
            sys.stdout.write(
                render_deleted_text(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    pairs=pairs,
                    warnings=tuple(_dedupe_warnings(warnings)),
                    rows=deleted_rows,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_explain_path(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        effective_depth = _parse_explain_depth(cast(str | None, report_args.depth))
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=report_args.since)
        target_path = _normalize_cli_path_bytes(cast(str, report_args.path))
        selected_pair = _select_pair_for_target(pairs, target_path)
        scoped_warnings = _pair_scoped_warnings(pair_warnings, selected_pair)
        rows, effective_target_path, query_warnings = query_explain_path_rows(
            connection,
            pair=selected_pair,
            target_path=target_path,
            group_by=report_args.group_by,
        )
        warnings = tuple(_dedupe_warnings(list(scoped_warnings) + list(query_warnings)))
        breakdown = explain_path_breakdown(
            rows,
            target_path=effective_target_path,
            limit=effective_limit,
            depth=effective_depth,
        )

        if report_args.json:
            emit_json(
                render_explain_path_payload(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    depth=effective_depth,
                    group_by=report_args.group_by,
                    pairs=(selected_pair,),
                    result=breakdown,
                    warnings=warnings,
                )
            )
        else:
            sys.stdout.write(
                render_explain_path_text(
                    since=report_args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    depth=effective_depth,
                    group_by=report_args.group_by,
                    pairs=(selected_pair,),
                    result=breakdown,
                    warnings=warnings,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_df_vs_index(args: argparse.Namespace) -> int:
    report_args = _report_args(args)
    db_path = Path(report_args.db).expanduser() if report_args.db else default_db_path()
    connection = None
    try:
        connection = open_readonly_connection(db_path)
        effective_limit = parse_report_limit(report_args.limit)
        diagnostic = build_df_index_diagnostic(
            connection,
            snapshot_selector=report_args.snapshot,
            limit=effective_limit,
        )

        if report_args.json:
            emit_json(render_df_index_payload(diagnostic))
        else:
            sys.stdout.write(render_df_index_text(diagnostic))
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=report_args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=report_args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_deleted_open_files(args: argparse.Namespace) -> int:
    effective_limit = parse_report_limit(cast(str, args.limit))
    db_arg = cast(str | None, args.db)
    as_json = cast(bool, args.json)

    # Host seams default to the live host; env vars exist only so deterministic
    # tests can pin the proc root and disable lsof without spawning the binary.
    proc_root = Path(os.environ.get("WATCHDIRS_TEST_PROC_ROOT", "/proc"))
    lsof_runner: Callable[[list[str]], tuple[bytes, bytes, int]] | None = None
    if os.environ.get("WATCHDIRS_TEST_NO_LSOF") == "1":

        def _raise_lsof(_argv: list[str]) -> tuple[bytes, bytes, int]:
            raise FileNotFoundError("lsof")

        lsof_runner = _raise_lsof

    connection = None
    domain_resolver = None
    try:
        if db_arg:
            db_path = Path(db_arg).expanduser()
            connection = open_readonly_connection(db_path)
            domain_resolver = _build_storage_domain_resolver(connection)

        diagnostic = collect_deleted_open_files(
            limit=effective_limit,
            proc_root=proc_root,
            lsof_runner=lsof_runner,
            domain_resolver=domain_resolver,
        )

        if as_json:
            emit_json(render_deleted_open_payload(diagnostic))
        else:
            sys.stdout.write(render_deleted_open_text(diagnostic))
        return 0
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=as_json,
            context={"db_path": str(db_arg)} if db_arg else None,
        )
    finally:
        if connection is not None:
            connection.close()


def run_docker_enrichment(args: argparse.Namespace) -> int:
    effective_limit = parse_report_limit(cast(str, args.limit))
    db_arg = cast(str | None, args.db)
    as_json = cast(bool, args.json)

    # Host seam defaults to the live Docker CLI; the env var exists only so a
    # deterministic test can force the absent-Docker path without a daemon.
    docker_runner: Callable[[list[str]], tuple[bytes, bytes, int]] | None = None
    if os.environ.get("WATCHDIRS_TEST_NO_DOCKER") == "1":

        def _raise_docker(_argv: list[str]) -> tuple[bytes, bytes, int]:
            raise FileNotFoundError("docker")

        docker_runner = _raise_docker

    connection = None
    indexed_path_hints: tuple[bytes, ...] = ()
    try:
        if db_arg:
            db_path = Path(db_arg).expanduser()
            connection = open_readonly_connection(db_path)
            indexed_path_hints = _collect_indexed_docker_path_hints(connection)

        enrichment = collect_docker_enrichment(
            indexed_path_hints=indexed_path_hints,
            limit=effective_limit,
            docker_runner=docker_runner,
        )

        if as_json:
            emit_json(render_docker_enrichment_payload(enrichment))
        else:
            sys.stdout.write(render_docker_enrichment_text(enrichment))
        return 0
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=as_json,
            context={"db_path": str(db_arg)} if db_arg else None,
        )
    finally:
        if connection is not None:
            connection.close()


# Path prefixes that, when present in persisted indexed evidence, indicate the
# Docker/containerd storage domains may matter. containerd hints are path context
# only; the docker module emits an explicit unavailable warning for them (D-11).
_DOCKER_HINT_PREFIXES: tuple[bytes, ...] = (b"/var/lib/docker", b"/var/lib/containerd")


def _collect_indexed_docker_path_hints(connection: sqlite3.Connection) -> tuple[bytes, ...]:
    """Surface persisted indexed directory paths under the Docker/containerd roots.

    Resolution reads only persisted ``directory_sizes`` rows from the latest
    snapshots via parameterized prefix matching; this is path context only and
    never infers reclaimability.
    """

    try:
        snapshots = resolve_top_snapshot_selection(connection, "latest")
    except ReportError:
        return ()

    hints: list[bytes] = []
    seen: set[bytes] = set()
    for snapshot in snapshots:
        for prefix in _DOCKER_HINT_PREFIXES:
            child_prefix = prefix + b"/"
            rows = connection.execute(
                """
                SELECT p.path AS path
                FROM directory_sizes ds
                JOIN paths p ON p.id = ds.path_id
                WHERE ds.snapshot_id = ?
                  AND (
                    p.path = ?
                    OR substr(p.path, 1, ?) = ?
                  )
                """,
                (snapshot.id, prefix, len(child_prefix), child_prefix),
            ).fetchall()
            rows = cast(list[sqlite3.Row], rows)
            for row in rows:
                path = bytes(cast(bytes, row["path"]))
                if path in seen:
                    continue
                seen.add(path)
                hints.append(path)
    return tuple(hints)


def _build_storage_domain_resolver(connection: sqlite3.Connection):
    """Aggregate persisted mounts across the latest snapshots into a resolver.

    Resolution uses longest mount-prefix matching over persisted ``snapshot_mounts``;
    paths with no matching mount return ``None`` so the caller records a warning.
    """

    try:
        snapshots = resolve_top_snapshot_selection(connection, "latest")
    except ReportError:
        # An empty or snapshot-less DB just means no enrichment is available;
        # deleted-open evidence is still emitted with storage_domain=null.
        return lambda _path_bytes: None
    mounts: list[SnapshotMount] = []
    seen: set[tuple[str, bytes]] = set()
    for snapshot in snapshots:
        for mount in load_snapshot_mounts(connection, snapshot.id):
            key = (mount.major_minor, mount.mount_point)
            if key in seen:
                continue
            seen.add(key)
            mounts.append(mount)
    mounts_tuple = tuple(mounts)

    def resolver(path_bytes: bytes) -> GroupLabel | None:
        best: SnapshotMount | None = None
        for mount in mounts_tuple:
            if not _matches_path_prefix(path_bytes, mount.mount_point):
                continue
            if best is None or len(mount.mount_point) > len(best.mount_point):
                best = mount
        if best is None:
            return None
        return GroupLabel(
            kind="storage-domain",
            key=f"{best.major_minor}|{os.fsdecode(best.root)}|{best.filesystem_type}|{best.mount_source}",
            mount_point=best.mount_point,
            filesystem_type=best.filesystem_type,
            mount_source=best.mount_source,
            major_minor=best.major_minor,
            root=best.root,
        )

    return resolver


def emit_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


def _emit_config_error(error: ConfigError, *, as_json: bool) -> int:
    if as_json:
        emit_json(error.to_payload())
    else:
        print(f"config error [{error.kind}] {error.message}: {error.path}", file=sys.stderr)
    return 2


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


def _prune_payload(result: PruneResult, db_path: Path, policy: RetentionPolicy) -> dict[str, object]:
    return {
        "ok": True,
        "command": "prune",
        "db_path": str(db_path),
        "policy": {
            "hourly_days": policy.hourly_days,
            "daily_days": policy.daily_days,
        },
        "deleted_snapshot_ids": result.deleted_snapshot_ids,
        "deleted_snapshot_count": result.deleted_snapshot_count,
        "retained_snapshot_count": result.retained_snapshot_count,
        "deleted_path_count": result.deleted_path_count,
        "snapshots_before": result.snapshots_before,
        "snapshots_after": result.snapshots_after,
    }


def _vacuum_payload(result: VacuumResult, db_path: Path) -> dict[str, object]:
    return {
        "ok": True,
        "command": "vacuum",
        "db_path": str(db_path),
        "db_bytes_before": result.db_bytes_before,
        "db_bytes_after": result.db_bytes_after,
        "page_count_before": result.page_count_before,
        "page_count_after": result.page_count_after,
        "freelist_count_before": result.freelist_count_before,
        "freelist_count_after": result.freelist_count_after,
        "available_free_bytes_before": result.available_free_bytes_before,
        "estimated_vacuum_required_free_bytes": result.estimated_vacuum_required_free_bytes,
        "free_space_warning": result.free_space_warning,
        "wal_checkpoint_busy": result.wal_checkpoint_busy,
        "wal_checkpoint_log_pages": result.wal_checkpoint_log_pages,
        "wal_checkpoint_checkpointed_pages": result.wal_checkpoint_checkpointed_pages,
        "wal_checkpoint_warning": result.wal_checkpoint_warning,
    }


def _call_with_optional_commit(function: Callable[..., object], *args: object, commit: bool) -> object:
    try:
        return function(*args, commit=commit)
    except TypeError as exc:
        if "unexpected keyword argument 'commit'" not in str(exc):
            raise
        return function(*args)


def _snapshot_status_warnings(snapshot: SnapshotRecord) -> tuple[ReportWarning, ...]:
    if snapshot.status is SnapshotStatus.PARTIAL:
        return (
            ReportWarning(
                code="partial_snapshot",
                message=f"snapshot {snapshot.id} is partial and may be incomplete",
            ),
        )
    if snapshot.status is SnapshotStatus.FAILED:
        return (
            ReportWarning(
                code="failed_snapshot",
                message=f"snapshot {snapshot.id} failed and should be treated as incomplete",
            ),
        )
    return ()


def _dedupe_warnings(warnings: list[ReportWarning]) -> list[ReportWarning]:
    deduped: list[ReportWarning] = []
    seen: set[tuple[str, bytes | None]] = set()
    for warning in warnings:
        key = (warning.code, warning.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


def _parse_explain_depth(raw_value: str | None) -> int:
    if raw_value is None:
        return 1
    try:
        depth = int(raw_value)
    except ValueError as exc:
        raise ReportError("invalid_depth", f"depth must be an integer, got {raw_value!r}", depth=raw_value) from exc
    if depth < 0 or depth > CLI_CONFIG.limits.max_explain_depth:
        raise ReportError(
            "invalid_depth",
            f"depth must be between 0 and {CLI_CONFIG.limits.max_explain_depth}, got {depth}",
            depth=raw_value,
        )
    return depth


def _normalize_cli_path_bytes(raw_path: str) -> bytes:
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    return os.fsencode(expanded.resolve(strict=False))


def _select_pair_for_target(pairs: tuple[SnapshotPair, ...], target_path: bytes) -> SnapshotPair:
    matching_pairs = [pair for pair in pairs if _matches_path_prefix(target_path, os.fsencode(str(pair.root_path)))]
    if not matching_pairs:
        raise ReportError(
            "path_outside_roots",
            f"path {os.fsdecode(target_path)!r} is outside all selected roots",
            path=os.fsdecode(target_path),
        )
    if len(matching_pairs) > 1:
        raise ReportError(
            "ambiguous_root",
            f"path {os.fsdecode(target_path)!r} matches more than one selected root",
            path=os.fsdecode(target_path),
            roots=[str(pair.root_path) for pair in matching_pairs],
        )
    return matching_pairs[0]


def _pair_scoped_warnings(
    warnings: tuple[ReportWarning, ...],
    pair: SnapshotPair,
) -> tuple[ReportWarning, ...]:
    root_bytes = os.fsencode(str(pair.root_path))
    return tuple(warning for warning in warnings if warning.path == root_bytes)


def _matches_path_prefix(path_bytes: bytes, prefix: bytes) -> bool:
    if prefix == b"/":
        return path_bytes.startswith(b"/")
    return path_bytes == prefix or path_bytes.startswith(prefix + b"/")


class CollectionInterruptedError(Exception):
    def __init__(self, signum: int, message: str) -> None:
        super().__init__(message)
        self.signum = signum
        self.message = message
