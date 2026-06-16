from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from watchdirs.db.migrations import load_snapshot_mounts
from watchdirs.models import (
    DiffRow,
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

    snapshots = resolve_top_snapshot_selection(connection, snapshot_selector)

    accumulators: dict[str, _DomainAccumulator] = {}
    for snapshot in snapshots:
        snapshot_mounts = load_snapshot_mounts(connection, snapshot.id)
        rows = connection.execute(
            """
            SELECT p.path AS path, pp.path AS parent_path, ds.depth AS depth,
                   ds.apparent_bytes AS apparent_bytes, ds.disk_bytes AS disk_bytes
            FROM directory_sizes ds
            JOIN paths p ON p.id = ds.path_id
            LEFT JOIN paths pp ON pp.id = ds.parent_id
            WHERE ds.snapshot_id = ?
            """,
            (snapshot.id,),
        ).fetchall()

        rows_by_path: dict[bytes, sqlite3.Row] = {bytes(row["path"]): row for row in rows}
        domain_by_path: dict[bytes, SnapshotMount | None] = {}
        for path, _row in rows_by_path.items():
            domain_by_path[path] = _longest_mount_prefix(path, snapshot_mounts)

        unknown_mount_count = sum(1 for match in domain_by_path.values() if match is None)
        is_partial = snapshot.status is not SnapshotStatus.COMPLETE

        for path, row in rows_by_path.items():
            match = domain_by_path[path]
            if match is None:
                continue
            parent_path = bytes(row["parent_path"]) if row["parent_path"] is not None else None
            domain_key = _domain_key(match)
            # Resolve this row relative to its NEAREST indexed ancestor, not only
            # its immediate parent row. When an intermediate directory is absent
            # from the indexed rows (a tree "gap"), the immediate parent path is
            # not in ``rows_by_path`` even though an indexed grandparent still
            # recursively counts this subtree. Walking upward finds that ancestor
            # so the boundary classification and the double-count subtraction both
            # use the enclosing domain rather than mis-treating the row as a fresh
            # top-level boundary.
            ancestor_path = parent_path
            ancestor_match: SnapshotMount | None = None
            while ancestor_path is not None:
                if ancestor_path in rows_by_path:
                    ancestor_match = domain_by_path.get(ancestor_path)
                    break
                ancestor_path = _parent_of(ancestor_path)
            # Boundary row: this row introduces a new storage-domain relative to
            # its nearest indexed ancestor (or has no indexed ancestor in this
            # snapshot).
            is_boundary = (
                ancestor_match is None or _domain_key(ancestor_match) != domain_key
            )
            if not is_boundary:
                continue

            row_disk = int(row["disk_bytes"])
            row_apparent = int(row["apparent_bytes"])
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

            # A boundary row whose recursive aggregate is contained inside an
            # indexed ancestor of a different storage-domain must be subtracted
            # from that ancestor's domain so nested submounts are not
            # double-counted. The ancestor is the nearest indexed one, which may
            # be above an absent intermediate directory.
            if ancestor_match is not None and _domain_key(ancestor_match) != domain_key:
                ancestor_key = _domain_key(ancestor_match)
                ancestor = accumulators.setdefault(ancestor_key, _DomainAccumulator(ancestor_match))
                ancestor.disk_bytes -= row_disk
                ancestor.apparent_bytes -= row_apparent

        # Path counts and unknown-mount counts are per snapshot, attributed to the
        # domain(s) that snapshot contributes to.
        for path, match in domain_by_path.items():
            if match is None:
                continue
            domain_key = _domain_key(match)
            accumulator = accumulators.setdefault(domain_key, _DomainAccumulator(match))
            accumulator.indexed_visible_path_count += 1
        if unknown_mount_count:
            # Attribute unknown-mount rows ONCE per snapshot, not fanned out to
            # every resolved domain. Fanning out both over-counted (N domains x
            # the same count) and mis-attributed incomplete coverage onto domains
            # that may be fully covered. The unknown rows live under the snapshot
            # root filesystem, so charge the count to the root's resolved domain.
            #
            # When the root path itself has no directory row (so it is absent from
            # ``domain_by_path``), resolve the root against the snapshot mounts
            # directly via longest mount-prefix: that is the enclosing root-filesystem
            # domain. Using the lexicographically lowest resolved key instead would
            # let a *nested submount* domain (which may have complete coverage) absorb
            # the incomplete-coverage signal while the actually-incomplete root-fs
            # domain looks clean (WR-02). Only if no mount prefixes the root do we
            # fall back to the lowest-keyed resolved domain so the count is surfaced
            # exactly once rather than dropped.
            root_path_bytes = os.fsencode(str(snapshot.root_path))
            root_match = domain_by_path.get(root_path_bytes)
            if root_match is None:
                root_match = _longest_mount_prefix(root_path_bytes, snapshot_mounts)
            if root_match is not None:
                # The enclosing root-filesystem domain may have contributed no
                # boundary/visible rows yet (e.g. the root row itself is absent),
                # so it may be new to ``accumulators`` -- create it on demand from
                # the resolved root mount.
                target_key = _domain_key(root_match)
                target = accumulators.setdefault(target_key, _DomainAccumulator(root_match))
            else:
                # No mount prefixes the snapshot root: charge the count to the
                # single lowest-keyed domain resolved *in this snapshot* so it is
                # surfaced exactly once. Each such key was already inserted above by
                # the visible-path-count loop, so it is present in ``accumulators``.
                resolved_keys = sorted(
                    _domain_key(match)
                    for match in domain_by_path.values()
                    if match is not None
                )
                target = accumulators[resolved_keys[0]] if resolved_keys else None
            if target is not None:
                target.unknown_mount_count += unknown_mount_count

    totals = tuple(
        accumulator.to_total()
        for accumulator in sorted(
            accumulators.values(),
            key=lambda acc: (-acc.disk_bytes, _domain_key(acc.match)),
        )
    )
    return totals


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
        "match",
        "disk_bytes",
        "apparent_bytes",
        "indexed_visible_path_count",
        "indexed_root_paths",
        "indexed_mount_points",
        "snapshot_ids",
        "snapshot_statuses",
        "finished_at_values",
        "partial_snapshot_ids",
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
            p.path AS path,
            ds.depth AS depth,
            ds.apparent_bytes AS apparent_bytes,
            ds.disk_bytes AS disk_bytes,
            ds.file_count AS file_count,
            ds.dir_count AS dir_count,
            ds.error AS error,
            ds.collapsed AS collapsed,
            ds.collapse_reason AS collapse_reason,
            ds.collapsed_dirs AS collapsed_dirs,
            tcp.path AS top_child_path,
            ds.top_child_disk_bytes AS top_child_disk_bytes
        FROM directory_sizes ds
        JOIN paths p ON p.id = ds.path_id
        LEFT JOIN paths tcp ON tcp.id = ds.top_child_id
        WHERE ds.snapshot_id = ?
        ORDER BY ds.disk_bytes DESC, p.path ASC
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
                collapsed=bool(row["collapsed"]),
                collapse_reason=row["collapse_reason"],
                collapsed_dirs=int(row["collapsed_dirs"]) if row["collapsed_dirs"] is not None else None,
                top_child_path=bytes(row["top_child_path"]) if row["top_child_path"] is not None else None,
                top_child_disk_bytes=int(row["top_child_disk_bytes"]) if row["top_child_disk_bytes"] is not None else None,
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
        WITH all_ids AS (
            SELECT path_id
            FROM directory_sizes
            WHERE snapshot_id = :baseline_id
            UNION
            SELECT path_id
            FROM directory_sizes
            WHERE snapshot_id = :current_id
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
            END AS classification
        FROM all_ids a
        JOIN paths p ON p.id = a.path_id
        LEFT JOIN directory_sizes AS prev
            ON prev.snapshot_id = :baseline_id
           AND prev.path_id = a.path_id
        LEFT JOIN directory_sizes AS curr
            ON curr.snapshot_id = :current_id
           AND curr.path_id = a.path_id
        LEFT JOIN paths pp ON pp.id = prev.parent_id
        LEFT JOIN paths cp ON cp.id = curr.parent_id
        LEFT JOIN paths ptp ON ptp.id = prev.top_child_id
        LEFT JOIN paths ctp ON ctp.id = curr.top_child_id
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
                collapsed=bool(query_row["collapsed"]),
                collapse_reason=query_row["collapse_reason"],
                collapsed_dirs=int(query_row["collapsed_dirs"]) if query_row["collapsed_dirs"] is not None else None,
                top_child_path=bytes(query_row["top_child_path"]) if query_row["top_child_path"] is not None else None,
                top_child_disk_bytes=(
                    int(query_row["top_child_disk_bytes"])
                    if query_row["top_child_disk_bytes"] is not None
                    else None
                ),
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
) -> tuple[tuple[DiffRow, ...], bytes, tuple[ReportWarning, ...]]:
    diff_rows, warnings = query_diff_rows(connection, pair=pair, group_by=group_by)
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
            collapsed_ancestor = rows_by_path.get(collapsed_ancestor_path)
            if collapsed_ancestor is not None:
                return (collapsed_ancestor,), collapsed_ancestor_path, warnings
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
    return tuple(subtree_rows), target_path, warnings


def _query_deepest_collapsed_ancestor_path(
    connection: sqlite3.Connection,
    *,
    baseline_snapshot_id: int,
    current_snapshot_id: int,
    target_path: bytes,
) -> bytes | None:
    candidate_rows = connection.execute(
        """
        WITH all_ids AS (
            SELECT path_id
            FROM directory_sizes
            WHERE snapshot_id = :baseline_id
            UNION
            SELECT path_id
            FROM directory_sizes
            WHERE snapshot_id = :current_id
        )
        SELECT
            p.path AS path,
            COALESCE(curr.depth, prev.depth) AS depth
        FROM all_ids a
        JOIN paths p ON p.id = a.path_id
        LEFT JOIN directory_sizes AS prev
            ON prev.snapshot_id = :baseline_id
           AND prev.path_id = a.path_id
        LEFT JOIN directory_sizes AS curr
            ON curr.snapshot_id = :current_id
           AND curr.path_id = a.path_id
        WHERE
            (curr.path_id IS NOT NULL AND curr.collapsed = 1)
            OR (curr.path_id IS NULL AND COALESCE(prev.collapsed, 0) = 1)
        ORDER BY COALESCE(curr.depth, prev.depth) DESC, p.path DESC
        """,
        {"baseline_id": baseline_snapshot_id, "current_id": current_snapshot_id},
    ).fetchall()

    for row in candidate_rows:
        candidate_path = bytes(row["path"])
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
