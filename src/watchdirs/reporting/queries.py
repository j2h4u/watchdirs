from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from watchdirs.db.migrations import load_snapshot_mounts
from watchdirs.models import (
    DiffRow,
    FrontierRow,
    GroupLabel,
    ReportGroupSummary,
    ReportSummary,
    ReportWarning,
    SnapshotMount,
    SnapshotPair,
    SnapshotRecord,
    SnapshotStatus,
    TopRow,
)


DEFAULT_REPORT_LIMIT = 20
MAX_REPORT_LIMIT = 1000
TOP_GROUP_BY_CHOICES = frozenset({"root", "top-level-subtree", "mount", "storage-domain"})


class ReportError(ValueError):
    def __init__(self, code: str, message: str, **context: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


def parse_report_limit(raw_value: str | None) -> int:
    if raw_value is None:
        return DEFAULT_REPORT_LIMIT

    try:
        limit = int(raw_value)
    except ValueError as exc:
        raise ReportError("invalid_limit", f"limit must be an integer, got {raw_value!r}", limit=raw_value) from exc

    if limit < 1:
        raise ReportError("invalid_limit", f"limit must be at least 1, got {limit}", limit=raw_value)
    if limit > MAX_REPORT_LIMIT:
        raise ReportError(
            "limit_too_large",
            f"limit must be at most {MAX_REPORT_LIMIT}, got {limit}",
            limit=raw_value,
            max_limit=MAX_REPORT_LIMIT,
        )
    return limit


def resolve_top_snapshot_selection(connection: sqlite3.Connection, selector: str) -> tuple[SnapshotRecord, ...]:
    if selector == "latest":
        rows = connection.execute(
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
        ).fetchall()
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

    row = connection.execute(
        """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ReportError("snapshot_not_found", f"snapshot id {snapshot_id} was not found", snapshot_id=snapshot_id)
    return (_snapshot_record_from_row(row),)


def query_top_rows(
    connection: sqlite3.Connection,
    *,
    snapshot_id: int,
    limit: int,
    group_by: str,
) -> tuple[tuple[TopRow, ...], tuple[ReportWarning, ...]]:
    if group_by not in TOP_GROUP_BY_CHOICES:
        raise ReportError("invalid_group_by", f"unsupported group_by value: {group_by!r}", group_by=group_by)

    snapshot = _load_snapshot(connection, snapshot_id)
    snapshot_mounts = load_snapshot_mounts(connection, snapshot_id) if group_by in {"mount", "storage-domain"} else ()
    query_rows = connection.execute(
        """
        SELECT
            path,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error
        FROM directory_sizes
        WHERE snapshot_id = ?
        ORDER BY disk_bytes DESC, path ASC
        LIMIT ?
        """,
        (snapshot_id, limit),
    ).fetchall()

    warnings_by_code_path: dict[tuple[str, bytes | None], ReportWarning] = {}
    rows: list[TopRow] = []
    root_path_bytes = os.fsencode(str(snapshot.root_path))
    for row in query_rows:
        path = bytes(row["path"])
        group, warning = resolve_group_for_path(
            path,
            root_path_bytes=root_path_bytes,
            group_by=group_by,
            snapshot_mounts=snapshot_mounts,
        )
        if warning is not None:
            warnings_by_code_path[(warning.code, warning.path)] = warning
        rows.append(
            TopRow(
                snapshot_id=snapshot_id,
                root_path=snapshot.root_path,
                path=path,
                path_bytes_hex=path.hex(),
                depth=int(row["depth"]),
                current_apparent_bytes=int(row["apparent_bytes"]),
                current_disk_bytes=int(row["disk_bytes"]),
                file_count=int(row["file_count"]),
                dir_count=int(row["dir_count"]),
                error=row["error"],
                group=group,
            )
        )

    return tuple(rows), tuple(warnings_by_code_path.values())


def query_diff_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    group_by: str,
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    if group_by not in TOP_GROUP_BY_CHOICES:
        raise ReportError("invalid_group_by", f"unsupported group_by value: {group_by!r}", group_by=group_by)

    root_path_bytes = os.fsencode(str(pair.root_path))
    snapshot_mounts = load_snapshot_mounts(connection, pair.current.id) if group_by in {"mount", "storage-domain"} else ()
    query_rows = connection.execute(
        """
        WITH all_paths AS (
            SELECT path
            FROM directory_sizes
            WHERE snapshot_id = :baseline_id
            UNION
            SELECT path
            FROM directory_sizes
            WHERE snapshot_id = :current_id
        )
        SELECT
            all_paths.path AS path,
            COALESCE(curr.parent_path, prev.parent_path) AS parent_path,
            COALESCE(curr.depth, prev.depth) AS depth,
            COALESCE(prev.apparent_bytes, 0) AS previous_apparent_bytes,
            COALESCE(curr.apparent_bytes, 0) AS current_apparent_bytes,
            COALESCE(curr.apparent_bytes, 0) - COALESCE(prev.apparent_bytes, 0) AS apparent_bytes_delta,
            COALESCE(prev.disk_bytes, 0) AS previous_disk_bytes,
            COALESCE(curr.disk_bytes, 0) AS current_disk_bytes,
            COALESCE(curr.disk_bytes, 0) - COALESCE(prev.disk_bytes, 0) AS disk_bytes_delta,
            COALESCE(curr.error, prev.error) AS error,
            CASE
                WHEN prev.path IS NULL THEN 'created'
                WHEN curr.path IS NULL THEN 'deleted'
                WHEN COALESCE(curr.disk_bytes, 0) > COALESCE(prev.disk_bytes, 0) THEN 'grown'
                WHEN COALESCE(curr.disk_bytes, 0) < COALESCE(prev.disk_bytes, 0) THEN 'shrunk'
                WHEN COALESCE(curr.apparent_bytes, 0) > COALESCE(prev.apparent_bytes, 0) THEN 'grown'
                WHEN COALESCE(curr.apparent_bytes, 0) < COALESCE(prev.apparent_bytes, 0) THEN 'shrunk'
                ELSE 'unchanged'
            END AS classification
        FROM all_paths
        LEFT JOIN directory_sizes AS prev
            ON prev.snapshot_id = :baseline_id
           AND prev.path = all_paths.path
        LEFT JOIN directory_sizes AS curr
            ON curr.snapshot_id = :current_id
           AND curr.path = all_paths.path
        ORDER BY disk_bytes_delta DESC, depth DESC, path ASC
        """,
        {"baseline_id": pair.baseline.id, "current_id": pair.current.id},
    ).fetchall()

    warnings_by_code_path: dict[tuple[str, bytes | None], ReportWarning] = {}
    rows: list[DiffRow] = []
    for query_row in query_rows:
        path = bytes(query_row["path"])
        group, warning = resolve_group_for_path(
            path,
            root_path_bytes=root_path_bytes,
            group_by=group_by,
            snapshot_mounts=snapshot_mounts,
        )
        if warning is not None:
            warnings_by_code_path[(warning.code, warning.path)] = warning
        rows.append(
            DiffRow(
                root_path=pair.root_path,
                baseline_snapshot_id=pair.baseline.id,
                current_snapshot_id=pair.current.id,
                path=path,
                parent_path=bytes(query_row["parent_path"]) if query_row["parent_path"] is not None else None,
                depth=int(query_row["depth"]),
                classification=str(query_row["classification"]),
                previous_apparent_bytes=int(query_row["previous_apparent_bytes"]),
                current_apparent_bytes=int(query_row["current_apparent_bytes"]),
                apparent_bytes_delta=int(query_row["apparent_bytes_delta"]),
                previous_disk_bytes=int(query_row["previous_disk_bytes"]),
                current_disk_bytes=int(query_row["current_disk_bytes"]),
                disk_bytes_delta=int(query_row["disk_bytes_delta"]),
                error=query_row["error"],
                group=group,
            )
        )

    return tuple(rows), tuple(warnings_by_code_path.values())


def query_deleted_rows(
    connection: sqlite3.Connection,
    *,
    pair: SnapshotPair,
    limit: int,
    group_by: str = "root",
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    diff_rows, warnings = query_diff_rows(connection, pair=pair, group_by=group_by)
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
) -> tuple[tuple[DiffRow, ...], tuple[ReportWarning, ...]]:
    diff_rows, warnings = query_diff_rows(connection, pair=pair, group_by=group_by)
    target = next((row for row in diff_rows if row.path == target_path), None)
    if target is None:
        raise ReportError(
            "path_not_indexed",
            f"path {os.fsdecode(target_path)!r} is under the selected root but not indexed",
            path=os.fsdecode(target_path),
            root_path=str(pair.root_path),
        )

    subtree_rows = [
        row
        for row in diff_rows
        if row.path == target_path or _matches_path_prefix(row.path, target_path)
    ]
    subtree_rows.sort(key=lambda row: (row.depth, row.path))
    return tuple(subtree_rows), warnings


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
    grouped: dict[tuple[str | None, str | None], dict[str, object]] = {}
    for frontier_row in frontier_rows:
        row = frontier_row.row
        disk_totals[row.classification] = disk_totals.get(row.classification, 0) + row.disk_bytes_delta
        apparent_totals[row.classification] = apparent_totals.get(row.classification, 0) + row.apparent_bytes_delta
        group_key = (row.group.kind, row.group.key) if row.group is not None else (None, None)
        bucket = grouped.setdefault(
            group_key,
            {
                "group": row.group,
                "path_count": 0,
                "disk_bytes_delta": 0,
                "apparent_bytes_delta": 0,
            },
        )
        bucket["path_count"] = int(bucket["path_count"]) + 1
        bucket["disk_bytes_delta"] = int(bucket["disk_bytes_delta"]) + row.disk_bytes_delta
        bucket["apparent_bytes_delta"] = int(bucket["apparent_bytes_delta"]) + row.apparent_bytes_delta

    group_summaries = tuple(
        sorted(
            (
                ReportGroupSummary(
                    group=bucket["group"],
                    path_count=int(bucket["path_count"]),
                    disk_bytes_delta=int(bucket["disk_bytes_delta"]),
                    apparent_bytes_delta=int(bucket["apparent_bytes_delta"]),
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
    row = connection.execute(
        """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    if row is None:
        raise ReportError("snapshot_not_found", f"snapshot id {snapshot_id} was not found", snapshot_id=snapshot_id)
    return _snapshot_record_from_row(row)


def _snapshot_record_from_row(row: sqlite3.Row) -> SnapshotRecord:
    return SnapshotRecord(
        id=int(row["id"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        root_path=Path(row["root_path"]),
        status=SnapshotStatus(row["status"]),
        notes=row["notes"],
        error=row["error"],
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
    best_match: SnapshotMount | None = None
    for mount in snapshot_mounts:
        if not _matches_path_prefix(path_bytes, mount.mount_point):
            continue
        if best_match is None or len(mount.mount_point) > len(best_match.mount_point):
            best_match = mount
    return best_match


def _matches_path_prefix(path_bytes: bytes, prefix: bytes) -> bool:
    if prefix == b"/":
        return path_bytes.startswith(b"/")
    return path_bytes == prefix or path_bytes.startswith(prefix + b"/")
