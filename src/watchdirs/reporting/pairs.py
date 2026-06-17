from __future__ import annotations

import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from watchdirs.models import ReportWarning, SnapshotPair, SnapshotRecord, SnapshotStatus
from watchdirs.reporting.errors import ReportError

SINCE_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)(?P<unit>[smhd])$")
MIN_USABLE_SNAPSHOTS = 2

_SINCE_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
}


def parse_since(raw_value: str) -> timedelta:
    match = SINCE_PATTERN.fullmatch(raw_value)
    if match is None:
        raise ReportError(
            "invalid_since",
            f"since must match INTEGER plus one unit s|m|h|d, got {raw_value!r}",
            since=raw_value,
        )

    count = int(match.group("count"))
    unit = match.group("unit")
    return timedelta(seconds=count * _SINCE_SECONDS[unit])


def parse_finished_at_utc(raw_value: str | None) -> datetime:
    if raw_value is None:
        raise ValueError("missing finished_at timestamp")

    candidate = raw_value
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"unparseable finished_at timestamp {raw_value!r}") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"naive finished_at timestamp {raw_value!r}")
    return parsed.astimezone(UTC)


def resolve_snapshot_pairs(
    connection: sqlite3.Connection,
    *,
    since: str,
) -> tuple[tuple[SnapshotPair, ...], tuple[ReportWarning, ...]]:
    since_delta = parse_since(since)
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
            """
            SELECT id, started_at, finished_at, root_path, status, notes, error
            FROM snapshots
            ORDER BY root_path ASC, id ASC
            """
        ).fetchall(),
    )

    warnings: list[ReportWarning] = []
    grouped_rows: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped_rows.setdefault(cast(str, row["root_path"]), []).append(row)

    resolved_pairs: list[SnapshotPair] = []
    for root_path_text, snapshot_rows in grouped_rows.items():
        usable: list[tuple[SnapshotRecord, datetime]] = []
        for row in snapshot_rows:
            snapshot = _snapshot_record_from_row(row)
            if snapshot.status is SnapshotStatus.FAILED:
                warnings.append(
                    ReportWarning(
                        code="failed_snapshot_excluded",
                        message=f"snapshot {snapshot.id} for {root_path_text} was excluded because it failed",
                        path=os.fsencode(root_path_text),
                    )
                )
                continue
            try:
                finished_at = parse_finished_at_utc(snapshot.finished_at)
            except ValueError as exc:
                warnings.append(
                    ReportWarning(
                        code="invalid_snapshot_timestamp",
                        message=f"snapshot {snapshot.id} for {root_path_text} has invalid finished_at: {exc}",
                        path=os.fsencode(root_path_text),
                    )
                )
                continue
            usable.append((snapshot, finished_at))

        if len(usable) < MIN_USABLE_SNAPSHOTS:
            warnings.append(
                ReportWarning(
                    code="insufficient_same_root_snapshots",
                    message=f"root {root_path_text} has fewer than two usable snapshots for diff",
                    path=os.fsencode(root_path_text),
                )
            )
            continue

        usable.sort(key=lambda item: (item[1], item[0].id))
        current, current_finished_at = usable[-1]
        cutoff = current_finished_at - since_delta

        at_or_before_cutoff = [item for item in usable[:-1] if item[1] <= cutoff]
        warning_codes: list[str] = []
        if at_or_before_cutoff:
            baseline = at_or_before_cutoff[-1][0]
        else:
            baseline = usable[0][0]
            warning_codes.append("baseline_before_since_unavailable")
            warnings.append(
                ReportWarning(
                    code="baseline_before_since_unavailable",
                    message=(
                        f"root {root_path_text} has no snapshot at or before cutoff {cutoff.isoformat()}; "
                        f"using oldest earlier snapshot {baseline.id}"
                    ),
                    path=os.fsencode(root_path_text),
                )
            )

        if current.status is SnapshotStatus.PARTIAL or baseline.status is SnapshotStatus.PARTIAL:
            warning_codes.append("partial_snapshot")
            warnings.append(
                ReportWarning(
                    code="partial_snapshot",
                    message=f"root {root_path_text} uses a partial snapshot in the selected pair",
                    path=os.fsencode(root_path_text),
                )
            )

        resolved_pairs.append(
            SnapshotPair(
                root_path=Path(root_path_text),
                baseline=baseline,
                current=current,
                warning_codes=tuple(warning_codes),
            )
        )

    if not resolved_pairs:
        raise ReportError(
            "no_snapshot_pairs",
            f"no same-root snapshot pairs are available for since={since!r}",
            since=since,
            warnings=[_warning_payload(warning) for warning in _dedupe_warnings(warnings)],
        )

    return tuple(resolved_pairs), tuple(_dedupe_warnings(warnings))


def _snapshot_record_from_row(row: sqlite3.Row) -> SnapshotRecord:
    return SnapshotRecord(
        id=int(cast(int | str, row["id"])),
        started_at=cast(str, row["started_at"]),
        finished_at=cast(str | None, row["finished_at"]),
        root_path=Path(cast(str, row["root_path"])),
        status=SnapshotStatus(cast(str, row["status"])),
        notes=cast(str | None, row["notes"]),
        error=cast(str | None, row["error"]),
    )


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


def _warning_payload(warning: ReportWarning) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": warning.code,
        "message": warning.message,
    }
    if warning.path is not None:
        payload["path"] = os.fsdecode(warning.path)
    return payload
