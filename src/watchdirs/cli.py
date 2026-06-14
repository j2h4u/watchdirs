from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
from typing import Sequence

from .collect.mounts import load_mountinfo
from .collect.scanner import scan_root
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
from .models import (
    GroupLabel,
    ReportWarning,
    ScanResult,
    ScannerOptions,
    SnapshotMount,
    SnapshotRecord,
    SnapshotStatus,
)
from .diagnostics import (
    build_compact_pressure_summary,
    build_df_index_diagnostic,
    collect_deleted_open_files,
    collect_docker_enrichment,
)
from .reporting import (
    ReportError,
    explain_path_breakdown,
    parse_report_limit,
    query_deleted_rows,
    prune_growth_frontier,
    query_diff_rows,
    query_explain_path_rows,
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
    render_top_payload,
    render_top_text,
    resolve_snapshot_pairs,
    resolve_top_snapshot_selection,
    summarize_diff_rows,
)


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

    diff = subparsers.add_parser("diff", allow_abbrev=False)
    diff.add_argument("--db", help="Override the SQLite database path")
    diff.add_argument("--since", required=True, help="Relative baseline selector such as 24h or 7d")
    diff.add_argument("--limit", help="Maximum frontier rows to show after global pruning (default: 20)")
    diff.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    diff.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for diff rows",
    )
    diff.set_defaults(handler=run_diff)

    report = subparsers.add_parser("report", allow_abbrev=False)
    report.add_argument("--db", help="Override the SQLite database path")
    report.add_argument("--since", required=True, help="Relative baseline selector such as 24h or 7d")
    report.add_argument("--limit", help="Maximum frontier and preview rows to show (default: 20)")
    report.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    report.add_argument(
        "--group-by",
        default="root",
        choices=("root", "top-level-subtree", "mount", "storage-domain"),
        help="Grouping label mode for report rows",
    )
    report.set_defaults(handler=run_report)

    deleted = subparsers.add_parser("deleted", allow_abbrev=False)
    deleted.add_argument("--db", help="Override the SQLite database path")
    deleted.add_argument("--since", required=True, help="Relative baseline selector such as 24h or 7d")
    deleted.add_argument("--limit", help="Maximum deleted rows to show (default: 20)")
    deleted.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    deleted.set_defaults(handler=run_deleted)

    explain = subparsers.add_parser("explain-path", allow_abbrev=False)
    explain.add_argument("path", help="Exact indexed path to explain")
    explain.add_argument("--db", help="Override the SQLite database path")
    explain.add_argument("--since", required=True, help="Relative baseline selector such as 24h or 7d")
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

    df_vs_index = subparsers.add_parser("df-vs-index", allow_abbrev=False)
    df_vs_index.add_argument("--db", help="Override the SQLite database path")
    df_vs_index.add_argument("--snapshot", default="latest", help="Snapshot selector: latest or numeric snapshot id")
    df_vs_index.add_argument("--limit", help="Maximum filesystem sections to show (default: 20)")
    df_vs_index.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    df_vs_index.set_defaults(handler=run_df_vs_index)

    deleted_open = subparsers.add_parser("deleted-open-files", allow_abbrev=False)
    deleted_open.add_argument(
        "--db",
        help="Optional SQLite database used to resolve deleted paths to a storage-domain",
    )
    deleted_open.add_argument("--limit", help="Maximum culprit rows to show (default: 20)")
    deleted_open.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    deleted_open.set_defaults(handler=run_deleted_open_files)

    docker_enrichment = subparsers.add_parser("docker-enrichment", allow_abbrev=False)
    docker_enrichment.add_argument(
        "--db",
        help="Optional SQLite database used to surface indexed Docker/containerd path hints",
    )
    docker_enrichment.add_argument("--limit", help="Maximum build-cache entries to show (default: 20)")
    docker_enrichment.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    docker_enrichment.set_defaults(handler=run_docker_enrichment)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("no command selected")
    return handler(args)


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

    active_snapshot_ids: set[int] = set()
    original_handlers: dict[int, signal.Handlers] = {}
    exit_code = 0
    snapshot_payloads: list[dict[str, object]] = []

    def _handle_interrupt(signum: int, _frame) -> None:
        error = f"collection interrupted by signal {signal.Signals(signum).name}"
        connection.rollback()
        for snapshot_id in list(active_snapshot_ids):
            finalize_snapshot(
                connection,
                snapshot_id,
                status=SnapshotStatus.FAILED,
                error=error,
            )
        raise CollectionInterrupted(signum, error)

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            original_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_interrupt)

        for configured_root in config.roots:
            try:
                snapshot = create_snapshot(connection, configured_root.path, notes=args.notes)
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
            active_snapshot_ids.add(snapshot.id)
            try:
                mounts = load_mountinfo(args.mountinfo or "/proc/self/mountinfo")
                scan_result = scan_root(
                    ScannerOptions(
                        root=configured_root.path,
                        exclude_paths=config.exclude_paths,
                        mounts=mounts,
                        mount_policy=config.mount_policy,
                        record_skipped=True,
                    )
                )
                persisted_rows = [
                    replace(row, snapshot_id=snapshot.id)
                    for row in scan_result.rows
                ]
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
                snapshot_payloads.append(_snapshot_payload(finalized, scan_result.row_count))
                if finalized.status is not SnapshotStatus.COMPLETE:
                    exit_code = 1
            except CollectionInterrupted:
                raise
            except Exception as exc:
                connection.rollback()
                exit_code = 1
                finalized = finalize_snapshot(
                    connection,
                    snapshot.id,
                    status=SnapshotStatus.FAILED,
                    notes=args.notes,
                    error=str(exc),
                )
                snapshot_payloads.append(_snapshot_payload(finalized, 0))
            finally:
                active_snapshot_ids.discard(snapshot.id)
    except CollectionInterrupted as exc:
        exit_code = 128 + exc.signum
        if args.json:
            emit_json(
                {
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
                }
            )
        return exit_code
    finally:
        for signum, handler in original_handlers.items():
            signal.signal(signum, handler)
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


def run_top(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        snapshots = resolve_top_snapshot_selection(connection, args.snapshot)

        sections: list[dict[str, object]] = []
        for snapshot in snapshots:
            row_warnings = list(_snapshot_status_warnings(snapshot))
            rows, query_warnings = query_top_rows(
                connection,
                snapshot_id=snapshot.id,
                limit=effective_limit,
                group_by=args.group_by,
            )
            row_warnings.extend(query_warnings)
            sections.append(
                {
                    "snapshot": snapshot,
                    "warnings": tuple(_dedupe_warnings(row_warnings)),
                    "rows": rows,
                }
            )

        if args.json:
            emit_json(
                render_top_payload(
                    snapshot_selector=args.snapshot,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
                    sections=sections,
                )
            )
        else:
            sys.stdout.write(
                render_top_text(
                    snapshot_selector=args.snapshot,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
                    sections=sections,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_diff(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=args.since)

        diff_rows = []
        warnings = list(pair_warnings)
        classification_counts: dict[str, int] = {}
        for pair in pairs:
            rows, query_warnings = query_diff_rows(connection, pair=pair, group_by=args.group_by)
            diff_rows.extend(rows)
            warnings.extend(query_warnings)
            for row in rows:
                classification_counts[row.classification] = classification_counts.get(row.classification, 0) + 1

        frontier_rows = prune_growth_frontier(diff_rows)[:effective_limit]

        if args.json:
            emit_json(
                render_diff_payload(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
                    pairs=pairs,
                    rows=frontier_rows,
                    classification_counts=classification_counts,
                    warnings=tuple(_dedupe_warnings(warnings)),
                )
            )
        else:
            sys.stdout.write(
                render_diff_text(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
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
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_report(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=args.since)

        diff_rows = []
        deleted_rows = []
        warnings = list(pair_warnings)
        for pair in pairs:
            rows, query_warnings = query_diff_rows(connection, pair=pair, group_by=args.group_by)
            diff_rows.extend(rows)
            warnings.extend(query_warnings)
            deleted_for_pair, deleted_warnings = query_deleted_rows(
                connection,
                pair=pair,
                limit=1000,
                group_by=args.group_by,
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
        pressure_summary = _build_report_pressure_summary(connection, limit=effective_limit)

        if args.json:
            emit_json(
                render_report_payload(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
                    summary=summary,
                    pressure_summary=pressure_summary,
                )
            )
        else:
            sys.stdout.write(
                render_report_text(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    group_by=args.group_by,
                    summary=summary,
                    pressure_summary=pressure_summary,
                )
            )
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def _build_report_pressure_summary(connection: sqlite3.Connection, *, limit: int):
    """Build the compact pressure summary for the report command.

    Runs only the cheap df/index reconciliation (statvfs scoped to indexed
    storage-domains) plus pure summary transformation. No lsof or Docker probes
    run here; deleted-open and Docker evidence stay behind their explicit commands.
    """

    stat_provider = _report_stat_provider()
    stat_kwargs = {} if stat_provider is None else {"stat_provider": stat_provider}
    try:
        df_index = build_df_index_diagnostic(
            connection,
            snapshot_selector="latest",
            limit=limit,
            **stat_kwargs,
        )
    except ReportError:
        # No usable snapshots means there is nothing to reconcile; the report still
        # renders its Phase 2 sections without diagnostic hints.
        return None

    # Recent storage-domain growth evidence: re-grouping report rows by
    # storage-domain is out of scope for the cheap report path, so growth is wired
    # only when the df/index domains coincide with persisted group keys.
    return build_compact_pressure_summary(df_index=df_index, report_groups=())


def _report_stat_provider():
    """Return the statvfs provider for the report df/index reconciliation.

    Defaults to the live host. The WATCHDIRS_TEST_DF_STAT_JSON env var exists only
    so deterministic tests can pin per-mountpoint df totals (or force an OSError for
    a stale/absent mountpoint) without touching the live filesystem.
    """

    raw = os.environ.get("WATCHDIRS_TEST_DF_STAT_JSON")
    if raw is None:
        return None  # build_df_index_diagnostic uses its live default.

    mapping = json.loads(raw)
    record_path = os.environ.get("WATCHDIRS_TEST_DF_STAT_RECORD")

    def provider(path_bytes: bytes) -> "os.statvfs_result":
        text = os.fsdecode(path_bytes)
        if record_path:
            with open(record_path, "a", encoding="ascii") as handle:
                handle.write(text + "\n")
        spec = mapping.get(text)
        if spec is None or spec.get("error"):
            raise OSError(f"injected statvfs failure for {text}")
        return _FakeStatvfs(size=int(spec["size"]), free=int(spec["free"]))

    return provider


class _FakeStatvfs:
    """Minimal statvfs-result stand-in for the deterministic report test seam."""

    __slots__ = ("f_frsize", "f_blocks", "f_bfree", "f_bavail")

    def __init__(self, *, size: int, free: int) -> None:
        self.f_frsize = 1
        self.f_blocks = size
        self.f_bfree = free
        self.f_bavail = free


def run_deleted(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=args.since)

        deleted_rows = []
        warnings = list(pair_warnings)
        for pair in pairs:
            rows, query_warnings = query_deleted_rows(connection, pair=pair, limit=1000)
            deleted_rows.extend(rows)
            warnings.extend(query_warnings)
        deleted_rows = tuple(sorted(deleted_rows, key=lambda row: (-row.previous_disk_bytes, row.path))[:effective_limit])

        if args.json:
            emit_json(
                render_deleted_payload(
                    since=args.since,
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
                    since=args.since,
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
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_explain_path(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        effective_depth = _parse_explain_depth(args.depth)
        pairs, pair_warnings = resolve_snapshot_pairs(connection, since=args.since)
        target_path = _normalize_cli_path_bytes(args.path)
        selected_pair = _select_pair_for_target(pairs, target_path)
        scoped_warnings = _pair_scoped_warnings(pair_warnings, selected_pair)
        rows, query_warnings = query_explain_path_rows(
            connection,
            pair=selected_pair,
            target_path=target_path,
            group_by=args.group_by,
        )
        warnings = tuple(_dedupe_warnings(list(scoped_warnings) + list(query_warnings)))
        breakdown = explain_path_breakdown(rows, target_path=target_path, limit=effective_limit, depth=effective_depth)

        if args.json:
            emit_json(
                render_explain_path_payload(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    depth=effective_depth,
                    group_by=args.group_by,
                    pairs=(selected_pair,),
                    result=breakdown,
                    warnings=warnings,
                )
            )
        else:
            sys.stdout.write(
                render_explain_path_text(
                    since=args.since,
                    limit=effective_limit,
                    effective_limit=effective_limit,
                    depth=effective_depth,
                    group_by=args.group_by,
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
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_df_vs_index(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser() if args.db else default_db_path()
    connection = None
    try:
        connection = open_connection(db_path)
        initialize_database(connection)
        effective_limit = parse_report_limit(args.limit)
        diagnostic = build_df_index_diagnostic(
            connection,
            snapshot_selector=args.snapshot,
            limit=effective_limit,
        )

        if args.json:
            emit_json(render_df_index_payload(diagnostic))
        else:
            sys.stdout.write(render_df_index_text(diagnostic))
        return 0
    except ReportError as exc:
        return _emit_runtime_error(
            code=exc.code,
            message=exc.message,
            as_json=args.json,
            context=exc.context,
        )
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(db_path)},
        )
    finally:
        if connection is not None:
            connection.close()


def run_deleted_open_files(args: argparse.Namespace) -> int:
    effective_limit = parse_report_limit(args.limit)

    # Host seams default to the live host; env vars exist only so deterministic
    # tests can pin the proc root and disable lsof without spawning the binary.
    proc_root = Path(os.environ.get("WATCHDIRS_TEST_PROC_ROOT", "/proc"))
    lsof_runner = None
    if os.environ.get("WATCHDIRS_TEST_NO_LSOF") == "1":
        def lsof_runner(_argv: list[str]) -> tuple[bytes, bytes, int]:
            raise FileNotFoundError("lsof")

    connection = None
    domain_resolver = None
    try:
        if args.db:
            db_path = Path(args.db).expanduser()
            connection = open_connection(db_path)
            initialize_database(connection)
            domain_resolver = _build_storage_domain_resolver(connection)

        diagnostic = collect_deleted_open_files(
            limit=effective_limit,
            proc_root=proc_root,
            lsof_runner=lsof_runner,
            domain_resolver=domain_resolver,
        )

        if args.json:
            emit_json(render_deleted_open_payload(diagnostic))
        else:
            sys.stdout.write(render_deleted_open_text(diagnostic))
        return 0
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(args.db)} if args.db else None,
        )
    finally:
        if connection is not None:
            connection.close()


def run_docker_enrichment(args: argparse.Namespace) -> int:
    effective_limit = parse_report_limit(args.limit)

    # Host seam defaults to the live Docker CLI; the env var exists only so a
    # deterministic test can force the absent-Docker path without a daemon.
    docker_runner = None
    if os.environ.get("WATCHDIRS_TEST_NO_DOCKER") == "1":
        def docker_runner(_argv: list[str]) -> tuple[bytes, bytes, int]:
            raise FileNotFoundError("docker")

    connection = None
    indexed_path_hints: tuple[bytes, ...] = ()
    try:
        if args.db:
            db_path = Path(args.db).expanduser()
            connection = open_connection(db_path)
            initialize_database(connection)
            indexed_path_hints = _collect_indexed_docker_path_hints(connection)

        enrichment = collect_docker_enrichment(
            indexed_path_hints=indexed_path_hints,
            limit=effective_limit,
            docker_runner=docker_runner,
        )

        if args.json:
            emit_json(render_docker_enrichment_payload(enrichment))
        else:
            sys.stdout.write(render_docker_enrichment_text(enrichment))
        return 0
    except (OSError, sqlite3.Error) as exc:
        return _emit_runtime_error(
            code="database_error",
            message=str(exc),
            as_json=args.json,
            context={"db_path": str(args.db)} if args.db else None,
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
            rows = connection.execute(
                """
                SELECT path
                FROM directory_sizes
                WHERE snapshot_id = ? AND (path = ? OR path GLOB ?)
                """,
                (snapshot.id, prefix, prefix + b"/*"),
            ).fetchall()
            for row in rows:
                path = bytes(row["path"])
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


def _call_with_optional_commit(function, *args, commit: bool) -> object:
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
    if depth < 0 or depth > 20:
        raise ReportError("invalid_depth", f"depth must be between 0 and 20, got {depth}", depth=raw_value)
    return depth


def _normalize_cli_path_bytes(raw_path: str) -> bytes:
    expanded = os.path.expanduser(raw_path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.getcwd(), expanded)
    normalized = os.path.normpath(expanded)
    return os.fsencode(normalized)


def _select_pair_for_target(pairs: tuple[SnapshotPair, ...], target_path: bytes) -> SnapshotPair:
    matching_pairs = [
        pair
        for pair in pairs
        if _matches_path_prefix(target_path, os.fsencode(str(pair.root_path)))
    ]
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
    return tuple(
        warning
        for warning in warnings
        if warning.path == root_bytes
    )


def _matches_path_prefix(path_bytes: bytes, prefix: bytes) -> bool:
    if prefix == b"/":
        return path_bytes.startswith(b"/")
    return path_bytes == prefix or path_bytes.startswith(prefix + b"/")


class CollectionInterrupted(Exception):
    def __init__(self, signum: int, message: str) -> None:
        super().__init__(message)
        self.signum = signum
        self.message = message
