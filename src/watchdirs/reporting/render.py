from __future__ import annotations

import os

from watchdirs.models import DiffRow, FrontierRow, GroupLabel, ReportWarning, SnapshotPair, SnapshotRecord, SnapshotStatus, TopRow


def decode_path(path_bytes: bytes) -> str:
    return os.fsdecode(path_bytes)


def path_payload(path_bytes: bytes) -> dict[str, str]:
    return {
        "path": decode_path(path_bytes),
        "path_bytes_hex": path_bytes.hex(),
    }


def render_top_payload(
    *,
    snapshot_selector: str,
    limit: int,
    effective_limit: int,
    group_by: str,
    sections: list[dict[str, object]],
) -> dict[str, object]:
    warnings = _dedupe_rendered_warnings(
        warning
        for section in sections
        for warning in section["warnings"]
    )
    return {
        "ok": True,
        "command": "top",
        "snapshot_selector": snapshot_selector,
        "limit": limit,
        "effective_limit": effective_limit,
        "group_by": group_by,
        "sections": [
            {
                "snapshot": _snapshot_payload(section["snapshot"]),
                "warnings": [_warning_payload(warning) for warning in section["warnings"]],
                "rows": [_top_row_payload(row) for row in section["rows"]],
            }
            for section in sections
        ],
        "warnings": warnings,
    }


def render_top_text(
    *,
    snapshot_selector: str,
    limit: int,
    effective_limit: int,
    group_by: str,
    sections: list[dict[str, object]],
) -> str:
    lines = [
        f"command=top snapshot_selector={snapshot_selector} limit={limit} effective_limit={effective_limit} group_by={group_by}"
    ]
    for section in sections:
        snapshot = section["snapshot"]
        lines.append(
            " ".join(
                (
                    f"snapshot={snapshot.id}",
                    f"root_path={snapshot.root_path}",
                    f"started_at={snapshot.started_at}",
                    f"finished_at={snapshot.finished_at}",
                    f"status={snapshot.status.value}",
                    f"error={snapshot.error}",
                )
            )
        )
        for warning in section["warnings"]:
            path_suffix = f" path={decode_path(warning.path)}" if warning.path is not None else ""
            lines.append(f"warning code={warning.code}{path_suffix} message={warning.message}")
        for row in section["rows"]:
            parts = [
                f"path={decode_path(row.path)}",
                f"current_disk_bytes={row.current_disk_bytes}",
                f"current_apparent_bytes={row.current_apparent_bytes}",
                f"depth={row.depth}",
                f"file_count={row.file_count}",
                f"dir_count={row.dir_count}",
            ]
            if row.group is not None:
                parts.append(f"group={row.group.kind}:{row.group.key}")
            if row.error is not None:
                parts.append(f"error={row.error}")
            lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def render_diff_payload(
    *,
    since: str,
    limit: int,
    effective_limit: int,
    group_by: str,
    pairs: tuple[SnapshotPair, ...],
    rows: tuple[FrontierRow, ...],
    classification_counts: dict[str, int],
    warnings: tuple[ReportWarning, ...],
) -> dict[str, object]:
    return {
        "ok": True,
        "command": "diff",
        "since": since,
        "limit": limit,
        "effective_limit": effective_limit,
        "group_by": group_by,
        "pairs": [_pair_payload(pair) for pair in pairs],
        "rows": [_frontier_row_payload(row) for row in rows],
        "classification_counts": dict(sorted(classification_counts.items())),
        "warnings": _dedupe_rendered_warnings(warnings),
    }


def render_diff_text(
    *,
    since: str,
    limit: int,
    effective_limit: int,
    group_by: str,
    pairs: tuple[SnapshotPair, ...],
    rows: tuple[FrontierRow, ...],
    warnings: tuple[ReportWarning, ...],
) -> str:
    lines = [
        f"command=diff since={since} limit={limit} effective_limit={effective_limit} group_by={group_by}"
    ]
    for pair in pairs:
        lines.append(
            " ".join(
                (
                    f"root_path={pair.root_path}",
                    f"baseline={pair.baseline.id}",
                    f"current={pair.current.id}",
                    f"baseline_finished_at={pair.baseline.finished_at}",
                    f"current_finished_at={pair.current.finished_at}",
                    f"baseline_status={pair.baseline.status.value}",
                    f"current_status={pair.current.status.value}",
                    f"warning_codes={','.join(pair.warning_codes) if pair.warning_codes else '-'}",
                )
            )
        )
    for warning in warnings:
        path_suffix = f" path={decode_path(warning.path)}" if warning.path is not None else ""
        lines.append(f"warning code={warning.code}{path_suffix} message={warning.message}")
    for frontier_row in rows:
        row = frontier_row.row
        parts = [
            f"path={decode_path(row.path)}",
            f"classification={row.classification}",
            f"previous_disk_bytes={row.previous_disk_bytes}",
            f"current_disk_bytes={row.current_disk_bytes}",
            f"disk_bytes_delta={row.disk_bytes_delta}",
            f"previous_apparent_bytes={row.previous_apparent_bytes}",
            f"current_apparent_bytes={row.current_apparent_bytes}",
            f"apparent_bytes_delta={row.apparent_bytes_delta}",
            f"suppressed_descendant_count={frontier_row.suppressed_descendant_count}",
            f"suppressed_ancestor_count={frontier_row.suppressed_ancestor_count}",
        ]
        if row.group is not None:
            parts.append(f"group={row.group.kind}:{row.group.key}")
        if row.error is not None:
            parts.append(f"error={row.error}")
        lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def _snapshot_payload(snapshot: SnapshotRecord) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_path": str(snapshot.root_path),
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "status": snapshot.status.value,
        "error": snapshot.error,
    }


def _pair_payload(pair: SnapshotPair) -> dict[str, object]:
    return {
        "root_path": str(pair.root_path),
        "baseline": _snapshot_payload(pair.baseline),
        "current": _snapshot_payload(pair.current),
        "warning_codes": list(pair.warning_codes),
    }


def _top_row_payload(row: TopRow) -> dict[str, object]:
    payload: dict[str, object] = {
        "snapshot_id": row.snapshot_id,
        "root_path": str(row.root_path),
        **path_payload(row.path),
        "depth": row.depth,
        "current_disk_bytes": row.current_disk_bytes,
        "current_apparent_bytes": row.current_apparent_bytes,
        "file_count": row.file_count,
        "dir_count": row.dir_count,
        "error": row.error,
        "group": _group_payload(row.group),
    }
    return payload


def _frontier_row_payload(frontier_row: FrontierRow) -> dict[str, object]:
    row = frontier_row.row
    payload: dict[str, object] = {
        "root_path": str(row.root_path),
        **path_payload(row.path),
        "snapshot_pair": {
            "baseline_id": row.baseline_snapshot_id,
            "current_id": row.current_snapshot_id,
        },
        "depth": row.depth,
        "classification": row.classification,
        "previous_disk_bytes": row.previous_disk_bytes,
        "current_disk_bytes": row.current_disk_bytes,
        "disk_bytes_delta": row.disk_bytes_delta,
        "previous_apparent_bytes": row.previous_apparent_bytes,
        "current_apparent_bytes": row.current_apparent_bytes,
        "apparent_bytes_delta": row.apparent_bytes_delta,
        "suppressed_descendant_count": frontier_row.suppressed_descendant_count,
        "suppressed_ancestor_count": frontier_row.suppressed_ancestor_count,
        "reason": frontier_row.reason,
        "group": _group_payload(row.group),
        "error": row.error,
    }
    return payload


def _group_payload(group: GroupLabel | None) -> dict[str, object] | None:
    if group is None:
        return None
    payload: dict[str, object] = {
        "kind": group.kind,
        "key": group.key,
    }
    if group.mount_point is not None:
        payload["mount_point"] = decode_path(group.mount_point)
    if group.filesystem_type is not None:
        payload["filesystem_type"] = group.filesystem_type
    if group.mount_source is not None:
        payload["mount_source"] = group.mount_source
    if group.major_minor is not None:
        payload["major_minor"] = group.major_minor
    if group.root is not None:
        payload["root"] = decode_path(group.root)
    return payload


def _warning_payload(warning: ReportWarning) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": warning.code,
        "message": warning.message,
    }
    if warning.path is not None:
        payload["path"] = decode_path(warning.path)
    return payload


def _dedupe_rendered_warnings(warnings: object) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str | None]] = set()
    for warning in warnings:
        key = (warning.code, decode_path(warning.path) if warning.path is not None else None)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(_warning_payload(warning))
    return deduped
