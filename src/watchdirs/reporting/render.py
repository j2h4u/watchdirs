from __future__ import annotations

import os

from watchdirs.models import GroupLabel, ReportWarning, SnapshotRecord, SnapshotStatus, TopRow


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


def _snapshot_payload(snapshot: SnapshotRecord) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_path": str(snapshot.root_path),
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "status": snapshot.status.value,
        "error": snapshot.error,
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
