from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

from watchdirs.db.migrations import load_snapshot_mounts
from watchdirs.models import (
    DiffRow,
    FastGrowthRow,
    FrontierRow,
    GroupLabel,
    IndexedStorageDomainTotal,
    ReportGroupSummary,
    ReportSummary,
    ReportWarning,
    SnapshotMount,
    SnapshotPair,
    SnapshotRecord,
    SnapshotStatus,
    SnapshotSummary,
    TimelinePoint,
    TopRow,
    snapshot_status_from_storage,
)
from watchdirs.reporting.errors import ReportError
from watchdirs.reporting.pairs import parse_finished_at_utc, parse_since
from watchdirs.reporting.trends import FilesystemPressureTrend, PathTrend, TrendSample, analyze_trend


@dataclass(frozen=True, slots=True)
class _ReportQueryLimits:
    default_limit: int = 20
    max_limit: int = 1000


@dataclass(frozen=True, slots=True)
class _ReportQueryGrouping:
    top_choices: frozenset[str] = frozenset({"root", "top-level-subtree", "mount", "storage-domain"})


@dataclass(frozen=True, slots=True)
class _ReportQueryConfig:
    limits: _ReportQueryLimits = field(default_factory=_ReportQueryLimits)
    grouping: _ReportQueryGrouping = field(default_factory=_ReportQueryGrouping)


REPORT_QUERY_CONFIG = _ReportQueryConfig()


def _snapshot_state_cte() -> str:
    """Return the v7 snapshot-state relation used by every report query.

    Complete snapshots are represented only by interval versions after the v7
    cutover.  Full rows remain deliberately available for diagnostic snapshots
    that are not complete.  Keeping this relation in one place prevents a
    report from accidentally reintroducing a complete-snapshot full-row path.
    """

    return """
        snapshot_state AS (
            SELECT
                s.id AS snapshot_id,
                s.root_path AS root_path,
                i.path_id AS path_id,
                i.parent_id AS parent_id,
                i.depth AS depth,
                i.apparent_bytes AS apparent_bytes,
                i.disk_bytes AS disk_bytes,
                i.file_count AS file_count,
                i.dir_count AS dir_count,
                i.error AS error,
                i.hardlink_file_count AS hardlink_file_count,
                i.hardlink_duplicate_count AS hardlink_duplicate_count,
                i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                i.collapsed AS collapsed,
                i.collapse_reason AS collapse_reason,
                i.collapsed_dirs AS collapsed_dirs,
                i.top_child_id AS top_child_id,
                i.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_intervals i
            JOIN snapshots s
              ON s.status = 'complete'
             AND i.root_path = s.root_path
             AND i.valid_from_snapshot_id <= s.id
             AND (i.valid_to_snapshot_id IS NULL OR s.id < i.valid_to_snapshot_id)
            UNION ALL
            SELECT
                s.id AS snapshot_id,
                s.root_path AS root_path,
                d.path_id AS path_id,
                d.parent_id AS parent_id,
                d.depth AS depth,
                d.apparent_bytes AS apparent_bytes,
                d.disk_bytes AS disk_bytes,
                d.file_count AS file_count,
                d.dir_count AS dir_count,
                d.error AS error,
                d.hardlink_file_count AS hardlink_file_count,
                d.hardlink_duplicate_count AS hardlink_duplicate_count,
                d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                d.collapsed AS collapsed,
                d.collapse_reason AS collapse_reason,
                d.collapsed_dirs AS collapsed_dirs,
                d.top_child_id AS top_child_id,
                d.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_diagnostics d
            JOIN snapshots s ON s.id = d.snapshot_id
            WHERE s.status <> 'complete'
        )
    """


@dataclass(slots=True)
class _GroupAccumulator:
    group: GroupLabel | None
    path_count: int = 0
    disk_bytes_delta: int = 0
    apparent_bytes_delta: int = 0


def _row_bytes(row: sqlite3.Row, key: str) -> bytes:
    return cast(bytes, row[key])


def _row_str(row: sqlite3.Row, key: str) -> str:
    return cast(str, row[key])


def _row_int(row: sqlite3.Row, key: str) -> int:
    return int(cast(int | str, row[key]))


def _row_optional_int(row: sqlite3.Row, key: str) -> int | None:
    value = cast(object, row[key])
    if value is None:
        return None
    return int(cast(int | str, value))


def _row_optional_float(row: sqlite3.Row, key: str) -> float | None:
    value = cast(object, row[key])
    if value is None:
        return None
    return float(cast(float | int | str, value))


def parse_report_limit(raw_value: str | None) -> int:
    if raw_value is None:
        return REPORT_QUERY_CONFIG.limits.default_limit

    try:
        limit = int(raw_value)
    except ValueError as exc:
        raise ReportError("invalid_limit", f"limit must be an integer, got {raw_value!r}", limit=raw_value) from exc

    if limit < 1:
        raise ReportError("invalid_limit", f"limit must be at least 1, got {limit}", limit=raw_value)
    if limit > REPORT_QUERY_CONFIG.limits.max_limit:
        raise ReportError(
            "limit_too_large",
            f"limit must be at most {REPORT_QUERY_CONFIG.limits.max_limit}, got {limit}",
            limit=raw_value,
            max_limit=REPORT_QUERY_CONFIG.limits.max_limit,
        )
    return limit


def resolve_top_snapshot_selection(connection: sqlite3.Connection, selector: str) -> tuple[SnapshotRecord, ...]:
    if selector == "latest":
        rows = cast(
            list[sqlite3.Row],
            connection.execute(
                """
            SELECT id, started_at, finished_at, root_path, status, notes, error
            FROM (
                SELECT
                    id,
                    started_at,
                    finished_at,
                    root_path,
                    status,
                    notes,
                    error,
                    ROW_NUMBER() OVER (
                        PARTITION BY root_path
                        ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
                    ) AS row_num
                FROM snapshots
                WHERE status IN (?, ?)
            )
            WHERE row_num = 1
            ORDER BY root_path ASC, id ASC
            """,
                (SnapshotStatus.COMPLETE.value, SnapshotStatus.PARTIAL.value),
            ).fetchall(),
        )
        if not rows:
            raise ReportError("no_usable_snapshots", "no complete or partial snapshots are available")
        return tuple(_snapshot_record_from_row(row) for row in rows)

    try:
        snapshot_id = int(selector)
    except ValueError as exc:
        raise ReportError(
            "invalid_snapshot_id",
            f"snapshot selector must be 'latest' or a numeric id, got {selector!r}",
            snapshot_selector=selector,
        ) from exc

    row = cast(
        sqlite3.Row | None,
        connection.execute(
            """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
            (snapshot_id,),
        ).fetchone(),
    )
    if row is None:
        raise ReportError("snapshot_not_found", f"snapshot id {snapshot_id} was not found", snapshot_id=snapshot_id)
    return (_snapshot_record_from_row(row),)


def query_snapshot_summaries(connection: sqlite3.Connection, *, limit: int) -> tuple[SnapshotSummary, ...]:
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
        WITH selected_snapshots AS MATERIALIZED (
            SELECT
                id,
                started_at,
                finished_at,
                root_path,
                status,
                notes,
                error
            FROM snapshots
            ORDER BY COALESCE(finished_at, started_at) DESC, id DESC
            LIMIT ?
        ),
        snapshot_state AS (
            SELECT
                s.id AS snapshot_id,
                i.path_id AS path_id,
                i.parent_id AS parent_id,
                i.depth AS depth,
                i.apparent_bytes AS apparent_bytes,
                i.disk_bytes AS disk_bytes,
                i.file_count AS file_count,
                i.dir_count AS dir_count,
                i.error AS error,
                i.hardlink_file_count AS hardlink_file_count,
                i.hardlink_duplicate_count AS hardlink_duplicate_count,
                i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                i.collapsed AS collapsed
            FROM selected_snapshots s
            JOIN directory_size_intervals i
              ON s.status = 'complete'
             AND i.root_path = s.root_path
             AND i.valid_from_snapshot_id <= s.id
             AND (i.valid_to_snapshot_id IS NULL OR s.id < i.valid_to_snapshot_id)
            UNION ALL
            SELECT
                s.id AS snapshot_id,
                d.path_id AS path_id,
                d.parent_id AS parent_id,
                d.depth AS depth,
                d.apparent_bytes AS apparent_bytes,
                d.disk_bytes AS disk_bytes,
                d.file_count AS file_count,
                d.dir_count AS dir_count,
                d.error AS error,
                d.hardlink_file_count AS hardlink_file_count,
                d.hardlink_duplicate_count AS hardlink_duplicate_count,
                d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                d.collapsed AS collapsed
            FROM selected_snapshots s
            JOIN directory_size_diagnostics d
              ON s.status <> 'complete'
             AND d.snapshot_id = s.id
        )
        SELECT
            s.id AS id,
            s.started_at AS started_at,
            s.finished_at AS finished_at,
            s.root_path AS root_path,
            s.status AS status,
            s.notes AS notes,
            s.error AS error,
            ROUND((julianday(s.finished_at) - julianday(s.started_at)) * 86400, 1) AS processing_seconds,
            COUNT(ds.path_id) AS row_count,
            COALESCE(SUM(CASE WHEN ds.collapsed = 1 THEN 1 ELSE 0 END), 0) AS collapsed_row_count,
            COALESCE(SUM(CASE WHEN ds.error IS NOT NULL THEN 1 ELSE 0 END), 0) AS error_row_count,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.apparent_bytes END) AS indexed_apparent_bytes,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.disk_bytes END) AS indexed_disk_bytes,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.file_count END) AS file_count,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.dir_count END) AS dir_count,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.hardlink_file_count END) AS hardlink_file_count,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.hardlink_duplicate_count END)
                AS hardlink_duplicate_count,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.hardlink_duplicate_disk_bytes END)
                AS hardlink_duplicate_disk_bytes,
            MAX(CASE WHEN ds.depth = 0 AND ds.parent_id IS NULL THEN ds.hardlink_first_seen_disk_bytes END)
                AS hardlink_first_seen_disk_bytes
        FROM selected_snapshots s
        LEFT JOIN snapshot_state ds ON ds.snapshot_id = s.id
        GROUP BY s.id
        ORDER BY COALESCE(s.finished_at, s.started_at) DESC, s.id DESC
        """,
            (limit,),
        ).fetchall(),
    )
    return tuple(_snapshot_summary_from_row(row) for row in rows)


def query_timeline_points(connection: sqlite3.Connection, *, since: str) -> tuple[TimelinePoint, ...]:
    snapshots = _select_trend_snapshots(connection, since=since)
    if not snapshots:
        raise ReportError("no_usable_snapshots", f"no complete or partial snapshots are available for since={since!r}")

    points: list[TimelinePoint] = []
    for snapshot in snapshots:
        row = _query_root_total_for_snapshot(connection, snapshot)
        points.append(
            TimelinePoint(
                snapshot=snapshot,
                indexed_apparent_bytes=_row_optional_int(row, "apparent_bytes") if row is not None else None,
                indexed_disk_bytes=_row_optional_int(row, "disk_bytes") if row is not None else None,
                file_count=_row_optional_int(row, "file_count") if row is not None else None,
                dir_count=_row_optional_int(row, "dir_count") if row is not None else None,
            )
        )
    return tuple(points)


def _query_root_total_for_snapshot(connection: sqlite3.Connection, snapshot: SnapshotRecord) -> sqlite3.Row | None:
    if snapshot.status is SnapshotStatus.COMPLETE:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                """
                SELECT apparent_bytes, disk_bytes, file_count, dir_count
                FROM directory_size_intervals
                WHERE root_path = ?
                  AND depth = 0
                  AND valid_from_snapshot_id <= ?
                  AND (valid_to_snapshot_id IS NULL OR ? < valid_to_snapshot_id)
                ORDER BY valid_from_snapshot_id DESC
                LIMIT 1
                """,
                (str(snapshot.root_path), snapshot.id, snapshot.id),
            ).fetchone(),
        )
    return cast(
        sqlite3.Row | None,
        connection.execute(
            """
            SELECT apparent_bytes, disk_bytes, file_count, dir_count
            FROM directory_size_diagnostics
            WHERE snapshot_id = ?
              AND depth = 0
            LIMIT 1
            """,
            (snapshot.id,),
        ).fetchone(),
    )


def query_indexed_storage_domain_totals(
    connection: sqlite3.Connection,
    *,
    snapshot_selector: str = "latest",
) -> tuple[IndexedStorageDomainTotal, ...]:
    """Aggregate persisted directory rows into non-overlapping storage-domain totals.

    Selects one latest usable snapshot per configured root via
    ``resolve_top_snapshot_selection`` then, for each selected snapshot, resolves
    every directory row to a storage-domain using persisted ``snapshot_mounts``
    longest mount-prefix evidence. Recursive aggregate rows are collapsed to
    domain-boundary rows so that each ``disk_bytes`` aggregate contributes to at
    most one storage-domain total: a row is a boundary row when its resolved
    storage-domain differs from its parent row's resolved storage-domain (or it is
    the snapshot root). The boundary aggregate of a nested submount domain is
    subtracted from its enclosing ancestor domain.
    """

    accumulators: dict[str, _DomainAccumulator] = {}
    for snapshot in resolve_top_snapshot_selection(connection, snapshot_selector):
        _accumulate_storage_domain_totals(connection, snapshot, accumulators)

    return tuple(
        accumulator.to_total()
        for accumulator in sorted(
            accumulators.values(),
            key=lambda acc: (-acc.disk_bytes, _domain_key(acc.match)),
        )
    )


def query_path_trends(
    connection: sqlite3.Connection,
    *,
    since: str,
    limit: int,
    candidate_limit: int | None = None,
) -> tuple[PathTrend, ...]:
    if limit < 1:
        raise ReportError("invalid_limit", f"limit must be at least 1, got {limit}", limit=str(limit))
    if candidate_limit is not None and candidate_limit < limit:
        raise ReportError(
            "invalid_limit",
            f"candidate_limit must be at least limit ({limit}), got {candidate_limit}",
            limit=str(limit),
            candidate_limit=str(candidate_limit),
        )
    selected_snapshots = _select_trend_snapshots(connection, since=since)
    if not selected_snapshots:
        raise ReportError("no_usable_snapshots", f"no complete or partial snapshots are available for since={since!r}")

    candidate_paths = (
        _query_current_size_candidate_paths(
            connection,
            selected_snapshots,
            limit=candidate_limit,
        )
        if candidate_limit is not None
        else None
    )
    rows = _query_trend_sample_rows(connection, selected_snapshots, candidate_paths=candidate_paths)
    trends = _path_trends_from_sample_rows(rows, selected_snapshots)
    return tuple(
        sorted(
            trends,
            key=lambda trend: (
                -trend.metrics.gross_positive_disk_bytes_delta,
                -trend.metrics.net_disk_bytes_delta,
                str(trend.root_path),
                trend.path,
            ),
        )[:limit]
    )


def query_path_trends_for_paths(
    connection: sqlite3.Connection,
    *,
    since: str,
    paths: Sequence[tuple[str, bytes]],
) -> tuple[PathTrend, ...]:
    selected_snapshots = _select_trend_snapshots(connection, since=since)
    if not selected_snapshots:
        raise ReportError("no_usable_snapshots", f"no complete or partial snapshots are available for since={since!r}")
    candidate_paths = tuple(dict.fromkeys(paths))
    rows = _query_trend_sample_rows(connection, selected_snapshots, candidate_paths=candidate_paths)
    trends = _path_trends_from_sample_rows(rows, selected_snapshots)
    trend_by_key = {(str(trend.root_path), trend.path): trend for trend in trends}
    return tuple(trend_by_key[key] for key in candidate_paths if key in trend_by_key)


def _path_trends_from_sample_rows(
    rows: tuple[sqlite3.Row, ...],
    selected_snapshots: tuple[SnapshotRecord, ...],
) -> tuple[PathTrend, ...]:
    expected_counts = _expected_sample_counts_by_root(selected_snapshots)
    accumulators: dict[tuple[str, bytes], _PathTrendAccumulator] = {}
    for row in rows:
        root_path_text = _row_str(row, "root_path")
        path = _row_bytes(row, "path")
        key = (root_path_text, path)
        accumulator = accumulators.setdefault(
            key,
            _PathTrendAccumulator(
                root_path=Path(root_path_text),
                path=path,
                expected_sample_count=expected_counts[root_path_text],
            ),
        )
        accumulator.add(row)

    return tuple(accumulator.to_trend() for accumulator in accumulators.values())


def query_filesystem_pressure_trends(
    connection: sqlite3.Connection,
    *,
    since: str,
    limit: int,
) -> tuple[FilesystemPressureTrend, ...]:
    if limit < 1:
        raise ReportError("invalid_limit", f"limit must be at least 1, got {limit}", limit=str(limit))
    selected_snapshots = _select_trend_snapshots(connection, since=since)
    if not selected_snapshots:
        raise ReportError("no_usable_snapshots", f"no complete or partial snapshots are available for since={since!r}")

    expected_counts = _expected_sample_counts_by_root(selected_snapshots)
    rows = _query_filesystem_pressure_rows(connection, selected_snapshots)
    accumulators: dict[str, _FilesystemPressureAccumulator] = {}
    for row in rows:
        key = _filesystem_pressure_key(row)
        accumulator = accumulators.setdefault(
            key,
            _FilesystemPressureAccumulator(
                storage_domain_key=key,
                expected_sample_count=expected_counts[_row_str(row, "root_path")],
            ),
        )
        accumulator.add(row)

    trends = tuple(accumulator.to_trend() for accumulator in accumulators.values())
    return tuple(
        sorted(
            trends,
            key=lambda trend: (
                -(trend.used_bytes_delta or 0),
                trend.storage_domain_key,
                trend.mount_point,
            ),
        )[:limit]
    )


def _select_trend_snapshots(connection: sqlite3.Connection, *, since: str) -> tuple[SnapshotRecord, ...]:
    since_delta = parse_since(since)
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
            SELECT id, started_at, finished_at, root_path, status, notes, error
            FROM snapshots
            WHERE status IN (?, ?) AND finished_at IS NOT NULL
            ORDER BY root_path ASC, finished_at ASC, id ASC
            """,
            (SnapshotStatus.COMPLETE.value, SnapshotStatus.PARTIAL.value),
        ).fetchall(),
    )
    grouped: dict[str, list[tuple[SnapshotRecord, datetime]]] = {}
    for row in rows:
        snapshot = _snapshot_record_from_row(row)
        try:
            finished_at = parse_finished_at_utc(snapshot.finished_at)
        except ValueError:
            continue
        grouped.setdefault(str(snapshot.root_path), []).append((snapshot, finished_at))

    selected: list[SnapshotRecord] = []
    for snapshot_rows in grouped.values():
        if not snapshot_rows:
            continue
        latest_finished_at = snapshot_rows[-1][1]
        cutoff = latest_finished_at - since_delta
        before_or_at_cutoff = [item for item in snapshot_rows if item[1] <= cutoff]
        window = [item for item in snapshot_rows if item[1] >= cutoff]
        root_selection: list[tuple[SnapshotRecord, datetime]] = []
        if before_or_at_cutoff:
            root_selection.append(before_or_at_cutoff[-1])
        root_selection.extend(item for item in window if item not in root_selection)
        selected.extend(snapshot for snapshot, _finished_at in root_selection)
    return tuple(selected)


def _expected_sample_counts_by_root(snapshots: tuple[SnapshotRecord, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for snapshot in snapshots:
        counts[str(snapshot.root_path)] = counts.get(str(snapshot.root_path), 0) + 1
    return counts


def _query_current_size_candidate_paths(
    connection: sqlite3.Connection,
    snapshots: tuple[SnapshotRecord, ...],
    *,
    limit: int,
) -> tuple[tuple[str, bytes], ...]:
    candidates: list[tuple[str, bytes]] = []
    for root_snapshots in _trend_snapshots_by_root(snapshots).values():
        current = root_snapshots[-1]
        candidates.extend(_query_current_size_candidate_paths_for_snapshot(connection, current, limit=limit))
    return tuple(dict.fromkeys(candidates))


def _trend_snapshots_by_root(snapshots: tuple[SnapshotRecord, ...]) -> dict[str, tuple[SnapshotRecord, ...]]:
    grouped: dict[str, list[SnapshotRecord]] = {}
    for snapshot in snapshots:
        grouped.setdefault(str(snapshot.root_path), []).append(snapshot)
    return {root_path: tuple(root_snapshots) for root_path, root_snapshots in grouped.items()}


def _query_current_size_candidate_paths_for_snapshot(
    connection: sqlite3.Connection,
    snapshot: SnapshotRecord,
    *,
    limit: int,
) -> tuple[tuple[str, bytes], ...]:
    if snapshot.status is SnapshotStatus.COMPLETE:
        return _query_complete_current_size_candidate_paths_for_snapshot(
            connection,
            snapshot,
            limit=limit,
        )
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            f"""
            WITH {_snapshot_state_cte()}
            SELECT p.path AS path
            FROM snapshot_state state
            JOIN paths p ON p.id = state.path_id
            WHERE state.snapshot_id = :snapshot_id
              AND state.depth > 0
              AND (state.disk_bytes > 0 OR state.apparent_bytes > 0)
            ORDER BY state.disk_bytes DESC, state.apparent_bytes DESC, state.depth DESC, p.path ASC
            LIMIT :limit
            """,
            {
                "snapshot_id": snapshot.id,
                "limit": limit,
            },
        ).fetchall(),
    )
    root_path_text = str(snapshot.root_path)
    return tuple((root_path_text, _row_bytes(row, "path")) for row in rows)


def _query_complete_current_size_candidate_paths_for_snapshot(
    connection: sqlite3.Connection,
    snapshot: SnapshotRecord,
    *,
    limit: int,
) -> tuple[tuple[str, bytes], ...]:
    root_path_text = str(snapshot.root_path)
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
            SELECT p.path AS path
            FROM directory_size_intervals interval
            JOIN paths p ON p.id = interval.path_id
            WHERE interval.root_path = :root_path
              AND interval.valid_from_snapshot_id <= :snapshot_id
              AND (interval.valid_to_snapshot_id IS NULL OR :snapshot_id < interval.valid_to_snapshot_id)
              AND interval.depth > 0
              AND (interval.disk_bytes > 0 OR interval.apparent_bytes > 0)
            ORDER BY interval.disk_bytes DESC, interval.apparent_bytes DESC, interval.depth DESC, p.path ASC
            LIMIT :limit
            """,
            {
                "root_path": root_path_text,
                "snapshot_id": snapshot.id,
                "limit": limit,
            },
        ).fetchall(),
    )
    return tuple((root_path_text, _row_bytes(row, "path")) for row in rows)


def _query_trend_sample_rows(
    connection: sqlite3.Connection,
    snapshots: tuple[SnapshotRecord, ...],
    *,
    candidate_paths: tuple[tuple[str, bytes], ...] | None = None,
) -> tuple[sqlite3.Row, ...]:
    if candidate_paths is not None:
        return _query_candidate_trend_sample_rows(connection, snapshots, candidate_paths=candidate_paths)
    snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
    placeholders = ",".join("?" for _ in snapshot_ids)
    return tuple(
        cast(
            list[sqlite3.Row],
            connection.execute(
                f"""
                WITH {_snapshot_state_cte()}
                SELECT
                    s.id AS snapshot_id,
                    s.finished_at AS finished_at,
                    s.root_path AS root_path,
                    s.status AS status,
                    p.path AS path,
                    pp.path AS parent_path,
                    ds.depth AS depth,
                    ds.apparent_bytes AS apparent_bytes,
                    ds.disk_bytes AS disk_bytes
                FROM snapshot_state ds
                JOIN snapshots s ON s.id = ds.snapshot_id
                JOIN paths p ON p.id = ds.path_id
                LEFT JOIN paths pp ON pp.id = ds.parent_id
                WHERE ds.snapshot_id IN ({placeholders})
                ORDER BY s.root_path ASC, p.path ASC, s.finished_at ASC, s.id ASC
                """,
                snapshot_ids,
            ).fetchall(),
        )
    )


def _query_candidate_trend_sample_rows(
    connection: sqlite3.Connection,
    snapshots: tuple[SnapshotRecord, ...],
    *,
    candidate_paths: tuple[tuple[str, bytes], ...],
) -> tuple[sqlite3.Row, ...]:
    if not candidate_paths:
        return ()
    snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
    snapshot_placeholders = ",".join("?" for _ in snapshot_ids)
    candidate_placeholders = ",".join("(?, ?)" for _ in candidate_paths)
    candidate_params: list[object] = []
    for root_path, path in candidate_paths:
        candidate_params.extend((root_path, sqlite3.Binary(path)))
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            f"""
            WITH candidate_paths(root_path, path) AS (
                VALUES {candidate_placeholders}
            ), candidate_ids AS (
                SELECT candidate.root_path AS root_path, paths.id AS path_id, paths.path AS path
                FROM candidate_paths candidate
                JOIN paths ON paths.path = candidate.path
            )
            SELECT
                s.id AS snapshot_id,
                s.finished_at AS finished_at,
                s.root_path AS root_path,
                s.status AS status,
                candidate.path AS path,
                pp.path AS parent_path,
                interval.depth AS depth,
                interval.apparent_bytes AS apparent_bytes,
                interval.disk_bytes AS disk_bytes
            FROM snapshots s
            JOIN candidate_ids candidate ON candidate.root_path = s.root_path
            JOIN directory_size_intervals interval
              ON interval.root_path = s.root_path
             AND interval.path_id = candidate.path_id
             AND interval.valid_from_snapshot_id <= s.id
             AND (interval.valid_to_snapshot_id IS NULL OR s.id < interval.valid_to_snapshot_id)
            LEFT JOIN paths pp ON pp.id = interval.parent_id
            WHERE s.status = 'complete'
              AND s.id IN ({snapshot_placeholders})
            UNION ALL
            SELECT
                s.id AS snapshot_id,
                s.finished_at AS finished_at,
                s.root_path AS root_path,
                s.status AS status,
                candidate.path AS path,
                pp.path AS parent_path,
                diagnostic.depth AS depth,
                diagnostic.apparent_bytes AS apparent_bytes,
                diagnostic.disk_bytes AS disk_bytes
            FROM snapshots s
            JOIN candidate_ids candidate ON candidate.root_path = s.root_path
            JOIN directory_size_diagnostics diagnostic
              ON diagnostic.snapshot_id = s.id
             AND diagnostic.path_id = candidate.path_id
            LEFT JOIN paths pp ON pp.id = diagnostic.parent_id
            WHERE s.status <> 'complete'
              AND s.id IN ({snapshot_placeholders})
            ORDER BY root_path ASC, path ASC, finished_at ASC, snapshot_id ASC
            """,
            (*candidate_params, *snapshot_ids, *snapshot_ids),
        ).fetchall(),
    )
    return tuple(rows)


def _query_filesystem_pressure_rows(
    connection: sqlite3.Connection,
    snapshots: tuple[SnapshotRecord, ...],
) -> tuple[sqlite3.Row, ...]:
    snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
    placeholders = ",".join("?" for _ in snapshot_ids)
    return tuple(
        cast(
            list[sqlite3.Row],
            connection.execute(
                f"""
                SELECT
                    sf.snapshot_id AS snapshot_id,
                    s.finished_at AS finished_at,
                    s.root_path AS root_path,
                    sf.major_minor AS major_minor,
                    sf.root AS root,
                    sf.mount_point AS mount_point,
                    sf.filesystem_type AS filesystem_type,
                    sf.mount_source AS mount_source,
                    sf.used_bytes AS used_bytes,
                    sf.available_bytes AS available_bytes,
                    sf.capture_error AS capture_error
                FROM snapshot_filesystems sf
                JOIN snapshots s ON s.id = sf.snapshot_id
                WHERE sf.snapshot_id IN ({placeholders})
                ORDER BY s.root_path ASC, sf.major_minor ASC, sf.root ASC, sf.filesystem_type ASC,
                         sf.mount_source ASC, s.finished_at ASC, s.id ASC
                """,
                snapshot_ids,
            ).fetchall(),
        )
    )


def _filesystem_pressure_key(row: sqlite3.Row) -> str:
    root_text = os.fsdecode(_row_bytes(row, "root"))
    return "|".join((
        _row_str(row, "major_minor"),
        root_text,
        _row_str(row, "filesystem_type"),
        _row_str(row, "mount_source"),
    ))


def _accumulate_storage_domain_totals(
    connection: sqlite3.Connection,
    snapshot: SnapshotRecord,
    accumulators: dict[str, _DomainAccumulator],
) -> None:
    snapshot_mounts = load_snapshot_mounts(connection, snapshot.id)
    mount_resolver = _MountPrefixResolver(snapshot_mounts)
    rows = connection.execute(
        f"""
        WITH {_snapshot_state_cte()}
        SELECT p.path AS path, pp.path AS parent_path, ds.depth AS depth,
               ds.apparent_bytes AS apparent_bytes, ds.disk_bytes AS disk_bytes
        FROM snapshot_state ds
        JOIN paths p ON p.id = ds.path_id
        LEFT JOIN paths pp ON pp.id = ds.parent_id
        WHERE ds.snapshot_id = ?
        """,
        (snapshot.id,),
    ).fetchall()

    rows_by_path: dict[bytes, sqlite3.Row] = {_row_bytes(row, "path"): row for row in cast(list[sqlite3.Row], rows)}
    domain_by_path: dict[bytes, SnapshotMount | None] = {
        path: mount_resolver.longest_prefix(path) for path in rows_by_path
    }

    _accumulate_storage_domain_boundary_rows(
        snapshot=snapshot,
        rows_by_path=rows_by_path,
        domain_by_path=domain_by_path,
        accumulators=accumulators,
    )
    _accumulate_storage_domain_visible_paths(
        snapshot=snapshot,
        domain_by_path=domain_by_path,
        mount_resolver=mount_resolver,
        accumulators=accumulators,
    )


def _accumulate_storage_domain_boundary_rows(
    *,
    snapshot: SnapshotRecord,
    rows_by_path: dict[bytes, sqlite3.Row],
    domain_by_path: dict[bytes, SnapshotMount | None],
    accumulators: dict[str, _DomainAccumulator],
) -> None:
    is_partial = snapshot.status is not SnapshotStatus.COMPLETE
    for path, row in rows_by_path.items():
        match = domain_by_path[path]
        if match is None:
            continue

        parent_path = _row_bytes(row, "parent_path") if row["parent_path"] is not None else None
        domain_key = _domain_key(match)
        ancestor_match = _nearest_indexed_ancestor_match(parent_path, rows_by_path, domain_by_path)
        if ancestor_match is not None and _domain_key(ancestor_match) == domain_key:
            continue

        row_disk = _row_int(row, "disk_bytes")
        row_apparent = _row_int(row, "apparent_bytes")
        accumulator = accumulators.setdefault(domain_key, _DomainAccumulator(match))
        accumulator.disk_bytes += row_disk
        accumulator.apparent_bytes += row_apparent
        accumulator.indexed_mount_points.add(match.mount_point)
        accumulator.indexed_root_paths.add(os.fsencode(str(snapshot.root_path)))
        accumulator.snapshot_ids.add(snapshot.id)
        accumulator.snapshot_statuses.add(snapshot.status.value)
        accumulator.finished_at_values.add(snapshot.finished_at)
        if is_partial:
            accumulator.partial_snapshot_ids.add(snapshot.id)

        if ancestor_match is not None:
            ancestor_key = _domain_key(ancestor_match)
            ancestor = accumulators.setdefault(ancestor_key, _DomainAccumulator(ancestor_match))
            ancestor.disk_bytes -= row_disk
            ancestor.apparent_bytes -= row_apparent


def _accumulate_storage_domain_visible_paths(
    *,
    snapshot: SnapshotRecord,
    domain_by_path: dict[bytes, SnapshotMount | None],
    mount_resolver: _MountPrefixResolver,
    accumulators: dict[str, _DomainAccumulator],
) -> None:
    unknown_mount_count = 0
    for match in domain_by_path.values():
        if match is None:
            unknown_mount_count += 1
            continue

        domain_key = _domain_key(match)
        accumulator = accumulators.setdefault(domain_key, _DomainAccumulator(match))
        accumulator.indexed_visible_path_count += 1

    if unknown_mount_count == 0:
        return

    root_path_bytes = os.fsencode(str(snapshot.root_path))
    root_match = domain_by_path.get(root_path_bytes)
    if root_match is None:
        root_match = mount_resolver.longest_prefix(root_path_bytes)
    if root_match is not None:
        target = accumulators.setdefault(_domain_key(root_match), _DomainAccumulator(root_match))
    else:
        resolved_keys = sorted(_domain_key(match) for match in domain_by_path.values() if match is not None)
        target = accumulators[resolved_keys[0]] if resolved_keys else None
    if target is not None:
        target.unknown_mount_count += unknown_mount_count


def _nearest_indexed_ancestor_match(
    parent_path: bytes | None,
    rows_by_path: dict[bytes, sqlite3.Row],
    domain_by_path: dict[bytes, SnapshotMount | None],
) -> SnapshotMount | None:
    ancestor_path = parent_path
    while ancestor_path is not None:
        if ancestor_path in rows_by_path:
            return domain_by_path.get(ancestor_path)
        ancestor_path = _parent_of(ancestor_path)
    return None


def _domain_key(mount: SnapshotMount) -> str:
    root_text = os.fsdecode(mount.root)
    return f"{mount.major_minor}|{root_text}|{mount.filesystem_type}|{mount.mount_source}"


def _storage_domain_label(mount: SnapshotMount) -> GroupLabel:
    return GroupLabel(
        kind="storage-domain",
        key=_domain_key(mount),
        mount_point=mount.mount_point,
        filesystem_type=mount.filesystem_type,
        mount_source=mount.mount_source,
        major_minor=mount.major_minor,
        root=mount.root,
    )


class _DomainAccumulator:
    __slots__ = (
        "apparent_bytes",
        "disk_bytes",
        "finished_at_values",
        "indexed_mount_points",
        "indexed_root_paths",
        "indexed_visible_path_count",
        "match",
        "partial_snapshot_ids",
        "snapshot_ids",
        "snapshot_statuses",
        "unknown_mount_count",
    )

    def __init__(self, match: SnapshotMount) -> None:
        self.match = match
        self.disk_bytes = 0
        self.apparent_bytes = 0
        self.indexed_visible_path_count = 0
        self.indexed_root_paths: set[bytes] = set()
        self.indexed_mount_points: set[bytes] = set()
        self.snapshot_ids: set[int] = set()
        self.snapshot_statuses: set[str] = set()
        self.finished_at_values: set[str | None] = set()
        self.partial_snapshot_ids: set[int] = set()
        self.unknown_mount_count = 0

    def to_total(self) -> IndexedStorageDomainTotal:
        finished = sorted(value for value in self.finished_at_values if value is not None)
        # The nested-submount subtraction is unbounded: inconsistent indexed
        # aggregates (partial/stale snapshots, or a submount aggregate larger
        # than what an ancestor recorded for that subtree) can drive an
        # accumulator negative. A negative indexed total would over-report
        # ``unattributed`` downstream, so clamp at zero and flag the
        # inconsistency rather than silently masking it.
        disk_clamped = max(self.disk_bytes, 0)
        apparent_clamped = max(self.apparent_bytes, 0)
        negative_total_clamped = self.disk_bytes < 0 or self.apparent_bytes < 0
        return IndexedStorageDomainTotal(
            storage_domain=_storage_domain_label(self.match),
            indexed_visible_disk_bytes=disk_clamped,
            indexed_visible_apparent_bytes=apparent_clamped,
            indexed_visible_path_count=self.indexed_visible_path_count,
            indexed_root_paths=tuple(sorted(self.indexed_root_paths)),
            indexed_mount_points=tuple(sorted(self.indexed_mount_points)),
            snapshot_ids=tuple(sorted(self.snapshot_ids)),
            snapshot_statuses=tuple(sorted(self.snapshot_statuses)),
            finished_at_min=finished[0] if finished else None,
            finished_at_max=finished[-1] if finished else None,
            partial_snapshot_count=len(self.partial_snapshot_ids),
            unknown_mount_count=self.unknown_mount_count,
            negative_total_clamped=negative_total_clamped,
        )


class _PathTrendAccumulator:
    __slots__ = (
        "depth",
        "expected_sample_count",
        "parent_path",
        "path",
        "root_path",
        "samples",
        "snapshot_ids",
        "snapshot_statuses",
    )

    def __init__(self, *, root_path: Path, path: bytes, expected_sample_count: int) -> None:
        self.root_path = root_path
        self.path = path
        self.expected_sample_count = expected_sample_count
        self.parent_path: bytes | None = None
        self.depth = 0
        self.samples: list[TrendSample] = []
        self.snapshot_ids: list[int] = []
        self.snapshot_statuses: set[str] = set()

    def add(self, row: sqlite3.Row) -> None:
        finished_at = parse_finished_at_utc(cast(str | None, row["finished_at"]))
        self.parent_path = _row_bytes(row, "parent_path") if row["parent_path"] is not None else None
        self.depth = _row_int(row, "depth")
        self.snapshot_ids.append(_row_int(row, "snapshot_id"))
        self.snapshot_statuses.add(_row_str(row, "status"))
        self.samples.append(
            TrendSample(
                snapshot_id=_row_int(row, "snapshot_id"),
                finished_at=finished_at,
                disk_bytes=_row_int(row, "disk_bytes"),
                apparent_bytes=_row_int(row, "apparent_bytes"),
            )
        )

    def to_trend(self) -> PathTrend:
        return PathTrend(
            root_path=self.root_path,
            path=self.path,
            path_bytes_hex=self.path.hex(),
            parent_path=self.parent_path,
            depth=self.depth,
            snapshot_ids=tuple(sorted(self.snapshot_ids)),
            snapshot_statuses=tuple(sorted(self.snapshot_statuses)),
            metrics=analyze_trend(self.samples, expected_sample_count=self.expected_sample_count),
        )


class _FilesystemPressureAccumulator:
    __slots__ = (
        "available_samples",
        "capture_errors",
        "expected_sample_count",
        "filesystem_type",
        "mount_point",
        "mount_source",
        "snapshot_ids",
        "storage_domain_key",
        "used_samples",
    )

    def __init__(self, *, storage_domain_key: str, expected_sample_count: int) -> None:
        self.storage_domain_key = storage_domain_key
        self.expected_sample_count = expected_sample_count
        self.mount_point = b""
        self.filesystem_type = ""
        self.mount_source = ""
        self.snapshot_ids: list[int] = []
        self.used_samples: list[int] = []
        self.available_samples: list[int] = []
        self.capture_errors: list[str] = []

    def add(self, row: sqlite3.Row) -> None:
        self.mount_point = _row_bytes(row, "mount_point")
        self.filesystem_type = _row_str(row, "filesystem_type")
        self.mount_source = _row_str(row, "mount_source")
        self.snapshot_ids.append(_row_int(row, "snapshot_id"))
        used_bytes = _row_optional_int(row, "used_bytes")
        available_bytes = _row_optional_int(row, "available_bytes")
        capture_error = cast(str | None, row["capture_error"])
        if used_bytes is not None:
            self.used_samples.append(used_bytes)
        if available_bytes is not None:
            self.available_samples.append(available_bytes)
        if capture_error is not None:
            self.capture_errors.append(capture_error)

    def to_trend(self) -> FilesystemPressureTrend:
        start_used = self.used_samples[0] if self.used_samples else None
        end_used = self.used_samples[-1] if self.used_samples else None
        start_available = self.available_samples[0] if self.available_samples else None
        end_available = self.available_samples[-1] if self.available_samples else None
        return FilesystemPressureTrend(
            storage_domain_key=self.storage_domain_key,
            mount_point=self.mount_point,
            filesystem_type=self.filesystem_type,
            mount_source=self.mount_source,
            snapshot_ids=tuple(sorted(self.snapshot_ids)),
            sample_count=len(self.snapshot_ids),
            missing_sample_count=max(0, self.expected_sample_count - len(self.snapshot_ids)),
            start_used_bytes=start_used,
            end_used_bytes=end_used,
            used_bytes_delta=None if start_used is None or end_used is None else end_used - start_used,
            start_available_bytes=start_available,
            end_available_bytes=end_available,
            available_bytes_delta=(
                None if start_available is None or end_available is None else end_available - start_available
            ),
            capture_error_count=len(self.capture_errors),
            latest_capture_error=self.capture_errors[-1] if self.capture_errors else None,
        )


def query_top_rows(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    limit: int,
    group_by: str,
) -> tuple[tuple[TopRow, ...], tuple[ReportWarning, ...]]:
    if group_by not in REPORT_QUERY_CONFIG.grouping.top_choices:
        raise ReportError("invalid_group_by", f"unsupported group_by value: {group_by!r}", group_by=group_by)

    snapshot = _load_snapshot(connection, snapshot_id)
    snapshot_mounts = load_snapshot_mounts(connection, snapshot_id) if group_by in {"mount", "storage-domain"} else ()
    query_rows = cast(
        list[sqlite3.Row],
        connection.execute(
            f"""
        WITH {_snapshot_state_cte()}
        SELECT
            p.path AS path,
            ds.depth AS depth,
            ds.apparent_bytes AS apparent_bytes,
            ds.disk_bytes AS disk_bytes,
            ds.file_count AS file_count,
            ds.dir_count AS dir_count,
            ds.hardlink_file_count AS hardlink_file_count,
            ds.hardlink_duplicate_count AS hardlink_duplicate_count,
            ds.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
            ds.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
            ds.error AS error,
            ds.collapsed AS collapsed,
            ds.collapse_reason AS collapse_reason,
            ds.collapsed_dirs AS collapsed_dirs,
            tcp.path AS top_child_path,
            ds.top_child_disk_bytes AS top_child_disk_bytes
        FROM snapshot_state ds
        JOIN paths p ON p.id = ds.path_id
        LEFT JOIN paths tcp ON tcp.id = ds.top_child_id
        WHERE ds.snapshot_id = ?
        ORDER BY ds.disk_bytes DESC, p.path ASC
        LIMIT ?
        """,
            (snapshot_id, limit),
        ).fetchall(),
    )

    warnings_by_code_path: dict[tuple[str, bytes | None], ReportWarning] = {}
    rows: list[TopRow] = []
    root_path_bytes = os.fsencode(str(snapshot.root_path))
    for row in query_rows:
        path = _row_bytes(row, "path")
        group, warning = resolve_group_for_path(
            path,
            root_path_bytes=root_path_bytes,
            group_by=group_by,
            snapshot_mounts=snapshot_mounts,
        )
        if warning is not None:
            warnings_by_code_path[warning.code, warning.path] = warning
        rows.append(
            TopRow(
                snapshot_id=snapshot_id,
                root_path=snapshot.root_path,
                path=path,
                path_bytes_hex=path.hex(),
                depth=_row_int(row, "depth"),
                current_apparent_bytes=_row_int(row, "apparent_bytes"),
                current_disk_bytes=_row_int(row, "disk_bytes"),
                file_count=_row_int(row, "file_count"),
                dir_count=_row_int(row, "dir_count"),
                hardlink_file_count=_row_int(row, "hardlink_file_count"),
                hardlink_duplicate_count=_row_int(row, "hardlink_duplicate_count"),
                hardlink_duplicate_disk_bytes=_row_int(row, "hardlink_duplicate_disk_bytes"),
                hardlink_first_seen_disk_bytes=_row_int(row, "hardlink_first_seen_disk_bytes"),
                error=cast(str | None, row["error"]),
                collapsed=bool(cast(int, row["collapsed"])),
                collapse_reason=cast(str | None, row["collapse_reason"]),
                collapsed_dirs=_row_optional_int(row, "collapsed_dirs"),
                top_child_path=_row_bytes(row, "top_child_path") if row["top_child_path"] is not None else None,
                top_child_disk_bytes=_row_optional_int(row, "top_child_disk_bytes"),
                group=group,
            )
        )

    return tuple(rows), tuple(warnings_by_code_path.values())


def query_diff_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    group_by: str,
    order_rows: bool = True,
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    return _query_diff_rows(connection, pair=pair, group_by=group_by, order_rows=order_rows, target_path=None)


def _query_diff_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    group_by: str,
    order_rows: bool,
    target_path: bytes | None,
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    if group_by not in REPORT_QUERY_CONFIG.grouping.top_choices:
        raise ReportError("invalid_group_by", f"unsupported group_by value: {group_by!r}", group_by=group_by)

    root_path_bytes = os.fsencode(str(pair.root_path))
    snapshot_mounts = (
        load_snapshot_mounts(connection, pair.current.id) if group_by in {"mount", "storage-domain"} else ()
    )
    query_rows = _fetch_diff_query_rows(connection, pair=pair, order_rows=order_rows, target_path=target_path)

    warnings_by_code_path: dict[tuple[str, bytes | None], ReportWarning] = {}
    rows: list[DiffRow] = []
    current_collapsed_paths = _current_collapsed_paths(query_rows)
    for query_row in query_rows:
        path = _row_bytes(query_row, "path")
        group, warning = resolve_group_for_path(
            path,
            root_path_bytes=root_path_bytes,
            group_by=group_by,
            snapshot_mounts=snapshot_mounts,
        )
        if warning is not None:
            warnings_by_code_path[warning.code, warning.path] = warning
        rows.append(
            DiffRow(
                root_path=pair.root_path,
                baseline_snapshot_id=pair.baseline.id,
                current_snapshot_id=pair.current.id,
                path=path,
                parent_path=_row_bytes(query_row, "parent_path") if query_row["parent_path"] is not None else None,
                depth=_row_int(query_row, "depth"),
                classification=_classification_from_row(query_row, current_collapsed_paths),
                previous_apparent_bytes=_row_int(query_row, "previous_apparent_bytes"),
                current_apparent_bytes=_row_int(query_row, "current_apparent_bytes"),
                apparent_bytes_delta=_row_int(query_row, "apparent_bytes_delta"),
                previous_disk_bytes=_row_int(query_row, "previous_disk_bytes"),
                current_disk_bytes=_row_int(query_row, "current_disk_bytes"),
                disk_bytes_delta=_row_int(query_row, "disk_bytes_delta"),
                previous_hardlink_file_count=_row_int(query_row, "previous_hardlink_file_count"),
                current_hardlink_file_count=_row_int(query_row, "current_hardlink_file_count"),
                hardlink_file_count_delta=_row_int(query_row, "hardlink_file_count_delta"),
                previous_hardlink_duplicate_count=_row_int(query_row, "previous_hardlink_duplicate_count"),
                current_hardlink_duplicate_count=_row_int(query_row, "current_hardlink_duplicate_count"),
                hardlink_duplicate_count_delta=_row_int(query_row, "hardlink_duplicate_count_delta"),
                previous_hardlink_duplicate_disk_bytes=_row_int(query_row, "previous_hardlink_duplicate_disk_bytes"),
                current_hardlink_duplicate_disk_bytes=_row_int(query_row, "current_hardlink_duplicate_disk_bytes"),
                hardlink_duplicate_disk_bytes_delta=_row_int(query_row, "hardlink_duplicate_disk_bytes_delta"),
                previous_hardlink_first_seen_disk_bytes=_row_int(query_row, "previous_hardlink_first_seen_disk_bytes"),
                current_hardlink_first_seen_disk_bytes=_row_int(query_row, "current_hardlink_first_seen_disk_bytes"),
                hardlink_first_seen_disk_bytes_delta=_row_int(query_row, "hardlink_first_seen_disk_bytes_delta"),
                error=cast(str | None, query_row["error"]),
                collapsed=bool(cast(int, query_row["collapsed"])),
                collapse_reason=cast(str | None, query_row["collapse_reason"]),
                collapsed_dirs=_row_optional_int(query_row, "collapsed_dirs"),
                top_child_path=_row_bytes(query_row, "top_child_path")
                if query_row["top_child_path"] is not None
                else None,
                top_child_disk_bytes=_row_optional_int(query_row, "top_child_disk_bytes"),
                group=group,
            )
        )

    return tuple(rows), tuple(warnings_by_code_path.values())


def _fetch_diff_query_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    order_rows: bool,
    target_path: bytes | None,
) -> list[sqlite3.Row]:
    path_filter, params = _path_scope_filter(target_path)
    query = f"""
        WITH baseline_state AS (
            SELECT
                i.path_id AS path_id,
                i.parent_id AS parent_id,
                i.depth AS depth,
                i.apparent_bytes AS apparent_bytes,
                i.disk_bytes AS disk_bytes,
                i.file_count AS file_count,
                i.dir_count AS dir_count,
                i.error AS error,
                i.hardlink_file_count AS hardlink_file_count,
                i.hardlink_duplicate_count AS hardlink_duplicate_count,
                i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                i.collapsed AS collapsed,
                i.collapse_reason AS collapse_reason,
                i.collapsed_dirs AS collapsed_dirs,
                i.top_child_id AS top_child_id,
                i.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_intervals i
            JOIN snapshots s
              ON s.id = :baseline_id
             AND s.status = 'complete'
             AND i.root_path = s.root_path
             AND i.valid_from_snapshot_id <= s.id
             AND (i.valid_to_snapshot_id IS NULL OR s.id < i.valid_to_snapshot_id)
            UNION ALL
            SELECT
                d.path_id AS path_id,
                d.parent_id AS parent_id,
                d.depth AS depth,
                d.apparent_bytes AS apparent_bytes,
                d.disk_bytes AS disk_bytes,
                d.file_count AS file_count,
                d.dir_count AS dir_count,
                d.error AS error,
                d.hardlink_file_count AS hardlink_file_count,
                d.hardlink_duplicate_count AS hardlink_duplicate_count,
                d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                d.collapsed AS collapsed,
                d.collapse_reason AS collapse_reason,
                d.collapsed_dirs AS collapsed_dirs,
                d.top_child_id AS top_child_id,
                d.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_diagnostics d
            JOIN snapshots s
              ON s.id = d.snapshot_id
             AND s.status <> 'complete'
            WHERE d.snapshot_id = :baseline_id
        ),
        current_state AS (
            SELECT
                i.path_id AS path_id,
                i.parent_id AS parent_id,
                i.depth AS depth,
                i.apparent_bytes AS apparent_bytes,
                i.disk_bytes AS disk_bytes,
                i.file_count AS file_count,
                i.dir_count AS dir_count,
                i.error AS error,
                i.hardlink_file_count AS hardlink_file_count,
                i.hardlink_duplicate_count AS hardlink_duplicate_count,
                i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                i.collapsed AS collapsed,
                i.collapse_reason AS collapse_reason,
                i.collapsed_dirs AS collapsed_dirs,
                i.top_child_id AS top_child_id,
                i.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_intervals i
            JOIN snapshots s
              ON s.id = :current_id
             AND s.status = 'complete'
             AND i.root_path = s.root_path
             AND i.valid_from_snapshot_id <= s.id
             AND (i.valid_to_snapshot_id IS NULL OR s.id < i.valid_to_snapshot_id)
            UNION ALL
            SELECT
                d.path_id AS path_id,
                d.parent_id AS parent_id,
                d.depth AS depth,
                d.apparent_bytes AS apparent_bytes,
                d.disk_bytes AS disk_bytes,
                d.file_count AS file_count,
                d.dir_count AS dir_count,
                d.error AS error,
                d.hardlink_file_count AS hardlink_file_count,
                d.hardlink_duplicate_count AS hardlink_duplicate_count,
                d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes,
                d.collapsed AS collapsed,
                d.collapse_reason AS collapse_reason,
                d.collapsed_dirs AS collapsed_dirs,
                d.top_child_id AS top_child_id,
                d.top_child_disk_bytes AS top_child_disk_bytes
            FROM directory_size_diagnostics d
            JOIN snapshots s
              ON s.id = d.snapshot_id
             AND s.status <> 'complete'
            WHERE d.snapshot_id = :current_id
        ),
        all_ids AS (
            SELECT prev.path_id
            FROM baseline_state prev
            JOIN paths p ON p.id = prev.path_id
            WHERE 1 = 1
              {path_filter}
            UNION
            SELECT curr.path_id
            FROM current_state curr
            JOIN paths p ON p.id = curr.path_id
            WHERE 1 = 1
              {path_filter}
        )
        SELECT
            p.path AS path,
            COALESCE(cp.path, pp.path) AS parent_path,
            COALESCE(curr.depth, prev.depth) AS depth,
            COALESCE(prev.apparent_bytes, 0) AS previous_apparent_bytes,
            COALESCE(curr.apparent_bytes, 0) AS current_apparent_bytes,
            COALESCE(curr.apparent_bytes, 0) - COALESCE(prev.apparent_bytes, 0) AS apparent_bytes_delta,
            COALESCE(prev.disk_bytes, 0) AS previous_disk_bytes,
            COALESCE(curr.disk_bytes, 0) AS current_disk_bytes,
            COALESCE(curr.disk_bytes, 0) - COALESCE(prev.disk_bytes, 0) AS disk_bytes_delta,
            COALESCE(prev.hardlink_file_count, 0) AS previous_hardlink_file_count,
            COALESCE(curr.hardlink_file_count, 0) AS current_hardlink_file_count,
            COALESCE(curr.hardlink_file_count, 0) - COALESCE(prev.hardlink_file_count, 0)
                AS hardlink_file_count_delta,
            COALESCE(prev.hardlink_duplicate_count, 0) AS previous_hardlink_duplicate_count,
            COALESCE(curr.hardlink_duplicate_count, 0) AS current_hardlink_duplicate_count,
            COALESCE(curr.hardlink_duplicate_count, 0) - COALESCE(prev.hardlink_duplicate_count, 0)
                AS hardlink_duplicate_count_delta,
            COALESCE(prev.hardlink_duplicate_disk_bytes, 0) AS previous_hardlink_duplicate_disk_bytes,
            COALESCE(curr.hardlink_duplicate_disk_bytes, 0) AS current_hardlink_duplicate_disk_bytes,
            COALESCE(curr.hardlink_duplicate_disk_bytes, 0) - COALESCE(prev.hardlink_duplicate_disk_bytes, 0)
                AS hardlink_duplicate_disk_bytes_delta,
            COALESCE(prev.hardlink_first_seen_disk_bytes, 0) AS previous_hardlink_first_seen_disk_bytes,
            COALESCE(curr.hardlink_first_seen_disk_bytes, 0) AS current_hardlink_first_seen_disk_bytes,
            COALESCE(curr.hardlink_first_seen_disk_bytes, 0) - COALESCE(prev.hardlink_first_seen_disk_bytes, 0)
                AS hardlink_first_seen_disk_bytes_delta,
            COALESCE(curr.error, prev.error) AS error,
            CASE
                WHEN curr.path_id IS NOT NULL THEN curr.collapsed
                ELSE COALESCE(prev.collapsed, 0)
            END AS collapsed,
            CASE
                WHEN curr.path_id IS NOT NULL THEN curr.collapse_reason
                ELSE prev.collapse_reason
            END AS collapse_reason,
            CASE
                WHEN curr.path_id IS NOT NULL THEN curr.collapsed_dirs
                ELSE prev.collapsed_dirs
            END AS collapsed_dirs,
            CASE
                WHEN curr.path_id IS NOT NULL THEN ctp.path
                ELSE ptp.path
            END AS top_child_path,
            CASE
                WHEN curr.path_id IS NOT NULL THEN curr.top_child_disk_bytes
                ELSE prev.top_child_disk_bytes
            END AS top_child_disk_bytes,
            CASE
                WHEN prev.path_id IS NULL THEN 'created'
                WHEN curr.path_id IS NULL THEN 'deleted'
                WHEN COALESCE(curr.disk_bytes, 0) > COALESCE(prev.disk_bytes, 0) THEN 'grown'
                WHEN COALESCE(curr.disk_bytes, 0) < COALESCE(prev.disk_bytes, 0) THEN 'shrunk'
                WHEN COALESCE(curr.apparent_bytes, 0) > COALESCE(prev.apparent_bytes, 0) THEN 'grown'
                WHEN COALESCE(curr.apparent_bytes, 0) < COALESCE(prev.apparent_bytes, 0) THEN 'shrunk'
                ELSE 'unchanged'
            END AS classification,
            curr.path_id IS NOT NULL AS current_exists
        FROM all_ids a
        JOIN paths p ON p.id = a.path_id
        LEFT JOIN baseline_state AS prev ON prev.path_id = a.path_id
        LEFT JOIN current_state AS curr ON curr.path_id = a.path_id
        LEFT JOIN paths pp ON pp.id = prev.parent_id
        LEFT JOIN paths cp ON cp.id = curr.parent_id
        LEFT JOIN paths ptp ON ptp.id = prev.top_child_id
        LEFT JOIN paths ctp ON ctp.id = curr.top_child_id
        """
    if order_rows:
        query += "ORDER BY disk_bytes_delta DESC, depth DESC, path ASC"

    return cast(
        list[sqlite3.Row],
        connection.execute(
            query,
            {
                "baseline_id": pair.baseline.id,
                "current_id": pair.current.id,
                **params,
            },
        ).fetchall(),
    )


def _path_scope_filter(target_path: bytes | None) -> tuple[str, dict[str, object]]:
    if target_path is None or target_path == b"/":
        return "", {}
    prefix = target_path.rstrip(b"/") + b"/"
    return (
        "AND (p.path = :target_path OR substr(p.path, 1, :target_prefix_len) = :target_prefix)",
        {
            "target_path": sqlite3.Binary(target_path),
            "target_prefix": sqlite3.Binary(prefix),
            "target_prefix_len": len(prefix),
        },
    )


def query_fast_growth_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    limit: int,
    max_depth: int,
) -> tuple[FastGrowthRow, ...]:
    query_rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
            WITH baseline_state AS (
                SELECT
                    i.path_id AS path_id,
                    i.depth AS depth,
                    i.apparent_bytes AS apparent_bytes,
                    i.disk_bytes AS disk_bytes,
                    i.hardlink_file_count AS hardlink_file_count,
                    i.hardlink_duplicate_count AS hardlink_duplicate_count,
                    i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                    i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes
                FROM directory_size_intervals i
                WHERE :baseline_complete = 1
                  AND i.root_path = :root_path
                  AND i.depth BETWEEN 1 AND 3
                  AND i.depth <= :max_depth
                  AND i.valid_from_snapshot_id <= :baseline_id
                  AND (i.valid_to_snapshot_id IS NULL OR :baseline_id < i.valid_to_snapshot_id)
                UNION ALL
                SELECT
                    d.path_id AS path_id,
                    d.depth AS depth,
                    d.apparent_bytes AS apparent_bytes,
                    d.disk_bytes AS disk_bytes,
                    d.hardlink_file_count AS hardlink_file_count,
                    d.hardlink_duplicate_count AS hardlink_duplicate_count,
                    d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                    d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes
                FROM directory_size_diagnostics d
                WHERE d.snapshot_id = :baseline_id
                  AND d.depth BETWEEN 1 AND 3
                  AND d.depth <= :max_depth
            ),
            current_state AS (
                SELECT
                    i.path_id AS path_id,
                    i.depth AS depth,
                    i.apparent_bytes AS apparent_bytes,
                    i.disk_bytes AS disk_bytes,
                    i.hardlink_file_count AS hardlink_file_count,
                    i.hardlink_duplicate_count AS hardlink_duplicate_count,
                    i.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                    i.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes
                FROM directory_size_intervals i
                WHERE :current_complete = 1
                  AND i.root_path = :root_path
                  AND i.depth BETWEEN 1 AND 3
                  AND i.depth <= :max_depth
                  AND i.valid_from_snapshot_id <= :current_id
                  AND (i.valid_to_snapshot_id IS NULL OR :current_id < i.valid_to_snapshot_id)
                UNION ALL
                SELECT
                    d.path_id AS path_id,
                    d.depth AS depth,
                    d.apparent_bytes AS apparent_bytes,
                    d.disk_bytes AS disk_bytes,
                    d.hardlink_file_count AS hardlink_file_count,
                    d.hardlink_duplicate_count AS hardlink_duplicate_count,
                    d.hardlink_duplicate_disk_bytes AS hardlink_duplicate_disk_bytes,
                    d.hardlink_first_seen_disk_bytes AS hardlink_first_seen_disk_bytes
                FROM directory_size_diagnostics d
                WHERE d.snapshot_id = :current_id
                  AND d.depth BETWEEN 1 AND 3
                  AND d.depth <= :max_depth
            ),
            all_ids AS (
                SELECT path_id FROM baseline_state
                UNION
                SELECT path_id FROM current_state
            )
            SELECT
                p.path AS path,
                COALESCE(curr.depth, prev.depth) AS depth,
                COALESCE(prev.disk_bytes, 0) AS previous_disk_bytes,
                COALESCE(curr.disk_bytes, 0) AS current_disk_bytes,
                COALESCE(curr.disk_bytes, 0) - COALESCE(prev.disk_bytes, 0) AS disk_bytes_delta,
                COALESCE(prev.apparent_bytes, 0) AS previous_apparent_bytes,
                COALESCE(curr.apparent_bytes, 0) AS current_apparent_bytes,
                COALESCE(curr.apparent_bytes, 0) - COALESCE(prev.apparent_bytes, 0) AS apparent_bytes_delta,
                COALESCE(prev.hardlink_file_count, 0) AS previous_hardlink_file_count,
                COALESCE(curr.hardlink_file_count, 0) AS current_hardlink_file_count,
                COALESCE(curr.hardlink_file_count, 0) - COALESCE(prev.hardlink_file_count, 0)
                    AS hardlink_file_count_delta,
                COALESCE(prev.hardlink_duplicate_count, 0) AS previous_hardlink_duplicate_count,
                COALESCE(curr.hardlink_duplicate_count, 0) AS current_hardlink_duplicate_count,
                COALESCE(curr.hardlink_duplicate_count, 0) - COALESCE(prev.hardlink_duplicate_count, 0)
                    AS hardlink_duplicate_count_delta,
                COALESCE(prev.hardlink_duplicate_disk_bytes, 0) AS previous_hardlink_duplicate_disk_bytes,
                COALESCE(curr.hardlink_duplicate_disk_bytes, 0) AS current_hardlink_duplicate_disk_bytes,
                COALESCE(curr.hardlink_duplicate_disk_bytes, 0) - COALESCE(prev.hardlink_duplicate_disk_bytes, 0)
                    AS hardlink_duplicate_disk_bytes_delta,
                COALESCE(prev.hardlink_first_seen_disk_bytes, 0) AS previous_hardlink_first_seen_disk_bytes,
                COALESCE(curr.hardlink_first_seen_disk_bytes, 0) AS current_hardlink_first_seen_disk_bytes,
                COALESCE(curr.hardlink_first_seen_disk_bytes, 0) - COALESCE(prev.hardlink_first_seen_disk_bytes, 0)
                    AS hardlink_first_seen_disk_bytes_delta,
                CASE
                    WHEN prev.path_id IS NULL THEN 'created'
                    WHEN curr.path_id IS NULL THEN 'deleted'
                    WHEN COALESCE(curr.disk_bytes, 0) > COALESCE(prev.disk_bytes, 0) THEN 'grown'
                    WHEN COALESCE(curr.disk_bytes, 0) < COALESCE(prev.disk_bytes, 0) THEN 'shrunk'
                    WHEN COALESCE(curr.apparent_bytes, 0) > COALESCE(prev.apparent_bytes, 0) THEN 'grown'
                    WHEN COALESCE(curr.apparent_bytes, 0) < COALESCE(prev.apparent_bytes, 0) THEN 'shrunk'
                    ELSE 'unchanged'
                END AS classification
            FROM all_ids a
            JOIN paths p ON p.id = a.path_id
            LEFT JOIN baseline_state prev ON prev.path_id = a.path_id
            LEFT JOIN current_state curr ON curr.path_id = a.path_id
            WHERE COALESCE(curr.disk_bytes, 0) > COALESCE(prev.disk_bytes, 0)
               OR COALESCE(curr.apparent_bytes, 0) > COALESCE(prev.apparent_bytes, 0)
            ORDER BY disk_bytes_delta DESC, apparent_bytes_delta DESC, depth ASC, path ASC
            LIMIT :limit
            """,
            {
                "root_path": str(pair.root_path),
                "baseline_id": pair.baseline.id,
                "current_id": pair.current.id,
                "baseline_complete": int(pair.baseline.status is SnapshotStatus.COMPLETE),
                "current_complete": int(pair.current.status is SnapshotStatus.COMPLETE),
                "max_depth": max_depth,
                "limit": limit,
            },
        ).fetchall(),
    )
    return tuple(
        FastGrowthRow(
            root_path=pair.root_path,
            baseline_snapshot_id=pair.baseline.id,
            current_snapshot_id=pair.current.id,
            path=_row_bytes(row, "path"),
            depth=_row_int(row, "depth"),
            classification=_row_str(row, "classification"),
            previous_disk_bytes=_row_int(row, "previous_disk_bytes"),
            current_disk_bytes=_row_int(row, "current_disk_bytes"),
            disk_bytes_delta=_row_int(row, "disk_bytes_delta"),
            previous_apparent_bytes=_row_int(row, "previous_apparent_bytes"),
            current_apparent_bytes=_row_int(row, "current_apparent_bytes"),
            apparent_bytes_delta=_row_int(row, "apparent_bytes_delta"),
            previous_hardlink_file_count=_row_int(row, "previous_hardlink_file_count"),
            current_hardlink_file_count=_row_int(row, "current_hardlink_file_count"),
            hardlink_file_count_delta=_row_int(row, "hardlink_file_count_delta"),
            previous_hardlink_duplicate_count=_row_int(row, "previous_hardlink_duplicate_count"),
            current_hardlink_duplicate_count=_row_int(row, "current_hardlink_duplicate_count"),
            hardlink_duplicate_count_delta=_row_int(row, "hardlink_duplicate_count_delta"),
            previous_hardlink_duplicate_disk_bytes=_row_int(row, "previous_hardlink_duplicate_disk_bytes"),
            current_hardlink_duplicate_disk_bytes=_row_int(row, "current_hardlink_duplicate_disk_bytes"),
            hardlink_duplicate_disk_bytes_delta=_row_int(row, "hardlink_duplicate_disk_bytes_delta"),
            previous_hardlink_first_seen_disk_bytes=_row_int(row, "previous_hardlink_first_seen_disk_bytes"),
            current_hardlink_first_seen_disk_bytes=_row_int(row, "current_hardlink_first_seen_disk_bytes"),
            hardlink_first_seen_disk_bytes_delta=_row_int(row, "hardlink_first_seen_disk_bytes_delta"),
        )
        for row in query_rows
    )


def _current_collapsed_paths(query_rows: list[sqlite3.Row]) -> frozenset[bytes]:
    return frozenset(
        _row_bytes(row, "path")
        for row in query_rows
        if bool(cast(int, row["current_exists"])) and bool(cast(int, row["collapsed"]))
    )


def _classification_from_row(query_row: sqlite3.Row, current_collapsed_paths: frozenset[bytes]) -> str:
    classification = _row_str(query_row, "classification")
    if classification != "deleted":
        return classification
    if _has_current_collapsed_ancestor(_row_bytes(query_row, "path"), current_collapsed_paths):
        return "hidden_by_collapse"
    return classification


def _has_current_collapsed_ancestor(path_bytes: bytes, current_collapsed_paths: frozenset[bytes]) -> bool:
    ancestor = _parent_of(path_bytes)
    while ancestor is not None:
        if ancestor in current_collapsed_paths:
            return True
        ancestor = _parent_of(ancestor)
    return False


def query_deleted_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    limit: int,
    group_by: str = "root",
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    diff_rows, warnings = query_diff_rows(connection, pair=pair, group_by=group_by, order_rows=False)
    deleted_rows = sorted(
        (row for row in diff_rows if row.classification == "deleted"),
        key=lambda row: (-row.previous_disk_bytes, row.path),
    )
    return tuple(deleted_rows[:limit]), warnings


def query_explain_path_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    target_path: bytes,
    group_by: str,
) -> tuple[tuple[DiffRow, ...], bytes, tuple[ReportWarning, ...]]:
    diff_rows, warnings = _query_diff_rows(
        connection,
        pair=pair,
        group_by=group_by,
        order_rows=False,
        target_path=target_path,
    )
    rows_by_path = {row.path: row for row in diff_rows}
    target = rows_by_path.get(target_path)
    if target is None:
        collapsed_ancestor_path = _query_deepest_collapsed_ancestor_path(
            connection,
            baseline_snapshot_id=pair.baseline.id,
            current_snapshot_id=pair.current.id,
            target_path=target_path,
        )
        if collapsed_ancestor_path is not None:
            diff_rows, warnings = _query_diff_rows(
                connection,
                pair=pair,
                group_by=group_by,
                order_rows=False,
                target_path=collapsed_ancestor_path,
            )
            rows_by_path = {row.path: row for row in diff_rows}
            collapsed_ancestor = rows_by_path.get(collapsed_ancestor_path)
            if collapsed_ancestor is not None:
                return (collapsed_ancestor,), collapsed_ancestor_path, warnings
        raise ReportError(
            "path_not_indexed",
            f"path {os.fsdecode(target_path)!r} is under the selected root but not indexed",
            path=os.fsdecode(target_path),
            root_path=str(pair.root_path),
        )

    subtree_rows = [row for row in diff_rows if row.path == target_path or _matches_path_prefix(row.path, target_path)]
    subtree_rows.sort(key=lambda row: (row.depth, row.path))
    return tuple(subtree_rows), target_path, warnings


def _query_deepest_collapsed_ancestor_path(
    connection: sqlite3.Connection,
    *,
    baseline_snapshot_id: int,
    current_snapshot_id: int,
    target_path: bytes,
) -> bytes | None:
    candidate_rows = cast(
        list[sqlite3.Row],
        connection.execute(
            f"""
        WITH {_snapshot_state_cte()}, all_ids AS (
            SELECT path_id
            FROM snapshot_state
            WHERE snapshot_id = :baseline_id
            UNION
            SELECT path_id
            FROM snapshot_state
            WHERE snapshot_id = :current_id
        )
        SELECT
            p.path AS path,
            COALESCE(curr.depth, prev.depth) AS depth
        FROM all_ids a
        JOIN paths p ON p.id = a.path_id
        LEFT JOIN snapshot_state AS prev
            ON prev.snapshot_id = :baseline_id
           AND prev.path_id = a.path_id
        LEFT JOIN snapshot_state AS curr
            ON curr.snapshot_id = :current_id
           AND curr.path_id = a.path_id
        WHERE
            (curr.path_id IS NOT NULL AND curr.collapsed = 1)
            OR (curr.path_id IS NULL AND COALESCE(prev.collapsed, 0) = 1)
        ORDER BY COALESCE(curr.depth, prev.depth) DESC, p.path DESC
        """,
            {"baseline_id": baseline_snapshot_id, "current_id": current_snapshot_id},
        ).fetchall(),
    )

    for row in candidate_rows:
        candidate_path = _row_bytes(row, "path")
        if _matches_path_prefix(target_path, candidate_path):
            return candidate_path
    return None


def summarize_diff_rows(
    *,
    snapshot_pairs: tuple[SnapshotPair, ...],
    diff_rows: tuple[DiffRow, ...] | list[DiffRow],
    frontier_rows: tuple[FrontierRow, ...] | list[FrontierRow],
    deleted_rows: tuple[DiffRow, ...] | list[DiffRow],
    warnings: tuple[ReportWarning, ...] | list[ReportWarning],
) -> ReportSummary:
    classification_counts: dict[str, int] = {}
    for row in diff_rows:
        classification_counts[row.classification] = classification_counts.get(row.classification, 0) + 1

    disk_totals: dict[str, int] = {}
    apparent_totals: dict[str, int] = {}
    grouped: dict[tuple[str | None, str | None], _GroupAccumulator] = {}
    for frontier_row in frontier_rows:
        row = frontier_row.row
        disk_totals[row.classification] = disk_totals.get(row.classification, 0) + row.disk_bytes_delta
        apparent_totals[row.classification] = apparent_totals.get(row.classification, 0) + row.apparent_bytes_delta
        group_key = (row.group.kind, row.group.key) if row.group is not None else (None, None)
        bucket = grouped.setdefault(group_key, _GroupAccumulator(row.group))
        bucket.path_count += 1
        bucket.disk_bytes_delta += row.disk_bytes_delta
        bucket.apparent_bytes_delta += row.apparent_bytes_delta

    group_summaries = tuple(
        sorted(
            (
                ReportGroupSummary(
                    group=bucket.group,
                    path_count=bucket.path_count,
                    disk_bytes_delta=bucket.disk_bytes_delta,
                    apparent_bytes_delta=bucket.apparent_bytes_delta,
                )
                for bucket in grouped.values()
            ),
            key=lambda entry: (
                -entry.disk_bytes_delta,
                -entry.apparent_bytes_delta,
                entry.group.kind if entry.group is not None else "",
                entry.group.key if entry.group is not None else "",
            ),
        )
    )

    return ReportSummary(
        snapshot_pairs=snapshot_pairs,
        classification_counts=dict(sorted(classification_counts.items())),
        disk_bytes_delta_by_classification=dict(sorted(disk_totals.items())),
        apparent_bytes_delta_by_classification=dict(sorted(apparent_totals.items())),
        frontier=tuple(frontier_rows),
        groups=group_summaries,
        deleted_preview=tuple(deleted_rows),
        warnings=tuple(warnings),
    )


def resolve_group_for_path(
    path_bytes: bytes,
    *,
    root_path_bytes: bytes,
    group_by: str,
    snapshot_mounts: tuple[SnapshotMount, ...] = (),
) -> tuple[GroupLabel | None, ReportWarning | None]:
    if not _matches_path_prefix(path_bytes, root_path_bytes):
        return None, ReportWarning(
            code="path_outside_root",
            message=f"path {os.fsdecode(path_bytes)!r} is not under snapshot root {os.fsdecode(root_path_bytes)!r}",
            path=path_bytes,
        )
    if group_by == "root":
        return GroupLabel(kind="root", key=os.fsdecode(root_path_bytes)), None
    if group_by == "top-level-subtree":
        return resolve_top_level_subtree_group(path_bytes, root_path_bytes), None
    if group_by not in {"mount", "storage-domain"}:
        raise ReportError("invalid_group_by", f"unsupported group_by value: {group_by!r}", group_by=group_by)

    match = _longest_mount_prefix(path_bytes, snapshot_mounts)
    if match is None:
        return None, ReportWarning(
            code="unknown_mount",
            message=f"no persisted mount prefix matched {os.fsdecode(path_bytes)!r}",
            path=path_bytes,
        )

    mount_point_text = os.fsdecode(match.mount_point)
    if group_by == "mount":
        return GroupLabel(kind="mount", key=mount_point_text, mount_point=match.mount_point), None

    root_text = os.fsdecode(match.root)
    return (
        GroupLabel(
            kind="storage-domain",
            key=f"{match.major_minor}|{root_text}|{match.filesystem_type}|{match.mount_source}",
            mount_point=match.mount_point,
            filesystem_type=match.filesystem_type,
            mount_source=match.mount_source,
            major_minor=match.major_minor,
            root=match.root,
        ),
        None,
    )


def resolve_top_level_subtree_group(path_bytes: bytes, root_path_bytes: bytes) -> GroupLabel:
    if path_bytes == root_path_bytes:
        return GroupLabel(kind="top-level-subtree", key=".")

    relative_path = _root_relative_bytes(path_bytes, root_path_bytes)
    if relative_path == b"":
        return GroupLabel(kind="top-level-subtree", key=".")
    segment = relative_path.split(b"/", 1)[0]
    return GroupLabel(kind="top-level-subtree", key=os.fsdecode(segment))


def _load_snapshot(connection: sqlite3.Connection, snapshot_id: int) -> SnapshotRecord:
    row = cast(
        sqlite3.Row | None,
        connection.execute(
            """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
            (snapshot_id,),
        ).fetchone(),
    )
    if row is None:
        raise ReportError("snapshot_not_found", f"snapshot id {snapshot_id} was not found", snapshot_id=snapshot_id)
    return _snapshot_record_from_row(row)


def _snapshot_record_from_row(row: sqlite3.Row) -> SnapshotRecord:
    finished_at = cast(str | None, row["finished_at"])
    return SnapshotRecord(
        id=_row_int(row, "id"),
        started_at=_row_str(row, "started_at"),
        finished_at=finished_at,
        root_path=Path(_row_str(row, "root_path")),
        status=snapshot_status_from_storage(_row_str(row, "status"), finished_at=finished_at),
        notes=cast(str | None, row["notes"]),
        error=cast(str | None, row["error"]),
    )


def _snapshot_summary_from_row(row: sqlite3.Row) -> SnapshotSummary:
    return SnapshotSummary(
        snapshot=_snapshot_record_from_row(row),
        processing_seconds=_row_optional_float(row, "processing_seconds"),
        row_count=_row_int(row, "row_count"),
        collapsed_row_count=_row_int(row, "collapsed_row_count"),
        error_row_count=_row_int(row, "error_row_count"),
        indexed_apparent_bytes=_row_optional_int(row, "indexed_apparent_bytes"),
        indexed_disk_bytes=_row_optional_int(row, "indexed_disk_bytes"),
        file_count=_row_optional_int(row, "file_count"),
        dir_count=_row_optional_int(row, "dir_count"),
        hardlink_file_count=_row_optional_int(row, "hardlink_file_count"),
        hardlink_duplicate_count=_row_optional_int(row, "hardlink_duplicate_count"),
        hardlink_duplicate_disk_bytes=_row_optional_int(row, "hardlink_duplicate_disk_bytes"),
        hardlink_first_seen_disk_bytes=_row_optional_int(row, "hardlink_first_seen_disk_bytes"),
    )


def _root_relative_bytes(path_bytes: bytes, root_path_bytes: bytes) -> bytes:
    if path_bytes == root_path_bytes:
        return b""
    if root_path_bytes == b"/":
        return path_bytes[1:] if path_bytes.startswith(b"/") else path_bytes
    prefix = root_path_bytes + b"/"
    if path_bytes.startswith(prefix):
        return path_bytes[len(prefix) :]
    return path_bytes


def _longest_mount_prefix(path_bytes: bytes, snapshot_mounts: tuple[SnapshotMount, ...]) -> SnapshotMount | None:
    return _MountPrefixResolver(snapshot_mounts).longest_prefix(path_bytes)


class _MountPrefixResolver:
    __slots__ = ("_mount_by_point",)

    def __init__(self, snapshot_mounts: tuple[SnapshotMount, ...]) -> None:
        mount_by_point: dict[bytes, SnapshotMount] = {}
        for mount in snapshot_mounts:
            if mount.mount_point not in mount_by_point:
                mount_by_point[mount.mount_point] = mount
        self._mount_by_point = mount_by_point

    def longest_prefix(self, path_bytes: bytes) -> SnapshotMount | None:
        current: bytes | None = path_bytes
        while current is not None:
            match = self._mount_by_point.get(current)
            if match is not None:
                return match
            current = _parent_of(current)
        return None


def _parent_of(path_bytes: bytes) -> bytes | None:
    """Return the parent of a byte path, or ``None`` once the root is reached.

    Operates on raw bytes (paths are not guaranteed to be valid UTF-8) and
    mirrors ``os.path.dirname`` semantics for absolute POSIX paths: the parent
    of ``/a/b/c`` is ``/a/b``, the parent of ``/a`` is ``/``, and ``/`` has no
    parent.
    """

    if path_bytes in (b"", b"/"):
        return None
    stripped = path_bytes.rstrip(b"/")
    head, sep, _tail = stripped.rpartition(b"/")
    if sep == b"":
        return None
    return head if head != b"" else b"/"


def _matches_path_prefix(path_bytes: bytes, prefix: bytes) -> bool:
    if prefix == b"/":
        return path_bytes.startswith(b"/")
    return path_bytes == prefix or path_bytes.startswith(prefix + b"/")
