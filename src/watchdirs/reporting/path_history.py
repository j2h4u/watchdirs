from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast

from watchdirs.db.migrations import load_snapshot_mounts
from watchdirs.models import DiffRow, GroupLabel, ReportWarning, SnapshotPair, SnapshotRecord, SnapshotStatus
from watchdirs.reporting.errors import ReportError
from watchdirs.reporting.pairs import parse_finished_at_utc, parse_since
from watchdirs.reporting.queries import (
    _snapshot_record_from_row,
    _snapshot_state_cte,
    query_explain_path_rows,
    resolve_group_for_path,
)


def has_path_history(connection: sqlite3.Connection, path: bytes) -> bool:
    return bool(_history_observations(connection, path, path))


def query_path_history(
    connection: sqlite3.Connection,
    *,
    requested_path: bytes,
    current_path: bytes,
    since: str,
    group_by: str,
) -> tuple[SnapshotPair, tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    pair, warnings = _select_history_pair(connection, requested_path, current_path, since)
    baseline, current = pair.baseline, pair.current
    assert pair.baseline_path is not None
    baseline_path = pair.baseline_path
    previous, previous_warnings = _endpoint_rows(connection, baseline, baseline_path, group_by)
    latest, current_warnings = _endpoint_rows(connection, current, current_path, group_by)
    warnings.extend(previous_warnings + current_warnings)
    if baseline.status is SnapshotStatus.PARTIAL or current.status is SnapshotStatus.PARTIAL:
        warnings.append(
            ReportWarning(
                "partial_snapshot",
                "Path history includes a partial snapshot; missing detail may be unavailable rather than deleted",
                requested_path,
            )
        )
    if baseline_path != current_path:
        warnings.append(
            ReportWarning(
                "path_relocated",
                "Comparing the requested path's stored history with today's symlink target by relative pathname; individual file identity is not inferred",
                requested_path,
            )
        )
    if (
        pair.baseline_storage_domain is not None
        and pair.current_storage_domain is not None
        and pair.baseline_storage_domain.major_minor is not None
        and pair.current_storage_domain.major_minor is not None
        and pair.baseline_storage_domain.key != pair.current_storage_domain.key
    ):
        warnings.append(
            ReportWarning(
                "storage_domain_changed",
                "Allocated-byte differences across the move include allocation, compression and hardlink/reflink effects; they do not measure physical disk growth or reclaimed space",
                requested_path,
            )
        )
    pair = replace(pair, warning_codes=tuple(warning.code for warning in warnings))
    return pair, _merge_endpoint_rows(pair, previous, latest), tuple(warnings)


def _select_history_pair(
    connection: sqlite3.Connection, requested_path: bytes, current_path: bytes, since: str
) -> tuple[SnapshotPair, list[ReportWarning]]:
    observations = _history_observations(connection, requested_path, current_path)
    current_candidates = [item for item in observations if item[1] == current_path]
    if not current_candidates:
        raise ReportError(
            "path_not_indexed",
            "The symlink target has no usable indexed observation; check watchdirs stats --json",
            path=os.fsdecode(current_path),
        )
    current, _ = current_candidates[-1]
    current_time = parse_finished_at_utc(current.finished_at)
    cutoff = current_time - parse_since(since)
    earlier = [
        item
        for item in observations
        if (parse_finished_at_utc(item[0].finished_at), item[0].id) < (current_time, current.id)
    ]
    if not earlier:
        raise ReportError(
            "insufficient_same_root_snapshots",
            "Path history needs an earlier usable observation; check watchdirs stats --json",
            path=os.fsdecode(requested_path),
        )
    before_cutoff = [item for item in earlier if parse_finished_at_utc(item[0].finished_at) <= cutoff]
    baseline, baseline_path = before_cutoff[-1] if before_cutoff else earlier[0]
    pair = SnapshotPair(
        current.root_path,
        baseline,
        current,
        baseline_path=baseline_path,
        current_path=current_path,
        requested_path=requested_path,
        baseline_storage_domain=_history_domain(connection, baseline, baseline_path),
        current_storage_domain=_history_domain(connection, current, current_path),
    )
    warnings: list[ReportWarning] = []
    if not before_cutoff:
        warnings.append(
            ReportWarning(
                "baseline_before_since_unavailable",
                "No path observation at the requested cutoff; using the oldest earlier observation",
                requested_path,
            )
        )
    return pair, warnings


def _history_domain(connection: sqlite3.Connection, snapshot: SnapshotRecord, path: bytes) -> GroupLabel | None:
    group, _ = resolve_group_for_path(
        path,
        root_path_bytes=os.fsencode(snapshot.root_path),
        group_by="storage-domain",
        snapshot_mounts=load_snapshot_mounts(connection, snapshot.id),
    )
    return group


def _history_observations(
    connection: sqlite3.Connection, requested_path: bytes, current_path: bytes
) -> list[tuple[SnapshotRecord, bytes]]:
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            f"""WITH {_snapshot_state_cte()}
        SELECT s.*, p.path AS observed_path
        FROM snapshot_state ds JOIN snapshots s ON s.id = ds.snapshot_id
        JOIN paths p ON p.id = ds.path_id
        WHERE p.path IN (?, ?) AND ds.error IS NULL
          AND s.status IN ('complete', 'partial') AND s.finished_at IS NOT NULL
        ORDER BY s.finished_at, s.id, (p.path = ?) ASC
        """,
            (requested_path, current_path, current_path),
        ).fetchall(),
    )
    return [(_snapshot_record_from_row(row), cast(bytes, row["observed_path"])) for row in rows]


def _endpoint_rows(
    connection: sqlite3.Connection, snapshot: SnapshotRecord, path: bytes, group_by: str
) -> tuple[dict[bytes, DiffRow], tuple[ReportWarning, ...]]:
    rows, effective_path, warnings = query_explain_path_rows(
        connection, pair=SnapshotPair(snapshot.root_path, snapshot, snapshot), target_path=path, group_by=group_by
    )
    if effective_path != path:
        raise ReportError(
            "path_history_detail_unavailable",
            "Historical detail is folded into an ancestor; compare the indexed ancestor instead",
            path=os.fsdecode(path),
            indexed_ancestor=os.fsdecode(effective_path),
        )
    return {row.path[len(path) :]: row for row in rows}, warnings


def _merge_endpoint_rows(
    pair: SnapshotPair, previous: dict[bytes, DiffRow], current: dict[bytes, DiffRow]
) -> tuple[DiffRow, ...]:
    assert pair.requested_path is not None
    rows: list[DiffRow] = []
    for suffix in sorted(previous.keys() | current.keys()):
        old, new = previous.get(suffix), current.get(suffix)
        template = new if new is not None else old
        assert template is not None
        changes: dict[str, object] = {}
        for metric in (
            "apparent_bytes",
            "disk_bytes",
            "hardlink_file_count",
            "hardlink_duplicate_count",
            "hardlink_duplicate_disk_bytes",
            "hardlink_first_seen_disk_bytes",
        ):
            before = cast(int, getattr(old, "current_" + metric)) if old is not None else 0
            after = cast(int, getattr(new, "current_" + metric)) if new is not None else 0
            changes["previous_" + metric] = before
            changes["current_" + metric] = after
            delta_field = (
                metric.replace("_bytes", "_bytes_delta")
                if metric in {"apparent_bytes", "disk_bytes"}
                else metric + "_delta"
            )
            changes[delta_field] = after - before
        path = pair.requested_path + suffix
        source_prefix = pair.current_path if new is not None else pair.baseline_path
        top_child = template.top_child_path
        if top_child is not None and source_prefix is not None:
            top_child = pair.requested_path + top_child[len(source_prefix) :]
        rows.append(
            replace(
                template,
                root_path=pair.root_path,
                baseline_snapshot_id=pair.baseline.id,
                current_snapshot_id=pair.current.id,
                path=path,
                parent_path=os.fsencode(Path(os.fsdecode(path)).parent) if suffix else None,
                top_child_path=top_child,
                depth=suffix.count(b"/"),
                classification=_history_classification(suffix, old, new, previous, current),
                **changes,
            )
        )
    return tuple(rows)


def _history_classification(
    suffix: bytes,
    old: DiffRow | None,
    new: DiffRow | None,
    previous: dict[bytes, DiffRow],
    current: dict[bytes, DiffRow],
) -> str:
    missing_side = previous if old is None else current
    if old is None or new is None:
        if any(row.collapsed and suffix.startswith(prefix + b"/") for prefix, row in missing_side.items()):
            return "hidden_by_collapse"
        return "created" if old is None else "deleted"
    delta = new.current_apparent_bytes - old.current_apparent_bytes
    if delta == 0:
        return "unchanged"
    return "grown" if delta > 0 else "shrunk"
