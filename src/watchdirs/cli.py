from __future__ import annotations

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
                insert_directory_rows(connection, persisted_rows)
                finalized = finalize_snapshot(
                    connection,
                    snapshot.id,
                    status=scan_result.status,
                    notes=args.notes,
                    error=scan_result.fatal_error,
                )
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


class CollectionInterrupted(Exception):
    def __init__(self, signum: int, message: str) -> None:
        super().__init__(message)
        self.signum = signum
        self.message = message
