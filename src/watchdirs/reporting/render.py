from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

from watchdirs.models import (
    DeletedOpenDiagnostic,
    DeletedOpenFile,
    DfIndexDiagnostic,
    DfIndexSection,
    DiagnosticHint,
    DiffRow,
    DockerBuildCacheEntry,
    DockerCategory,
    DockerEnrichment,
    ExplainPathResult,
    FrontierRow,
    GroupLabel,
    PressureSummary,
    PressureSummarySection,
    ReportGroupSummary,
    ReportSummary,
    ReportWarning,
    SnapshotPair,
    SnapshotRecord,
    SnapshotStatus,
    SnapshotSummary,
    TopRow,
)


@dataclass(frozen=True, slots=True)
class _ByteFormatConfig:
    base: int = 1024
    units: tuple[str, ...] = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


@dataclass(frozen=True, slots=True)
class _DurationFormatConfig:
    fractional_cutoff_seconds: int = 60
    seconds_per_minute: int = 60
    seconds_per_hour: int = 3600


@dataclass(frozen=True, slots=True)
class _CountFormatConfig:
    base: int = 1000
    units: tuple[str, ...] = ("", "k", "M", "B", "T")


@dataclass(frozen=True, slots=True)
class _RenderConfig:
    bytes: _ByteFormatConfig = field(default_factory=_ByteFormatConfig)
    duration: _DurationFormatConfig = field(default_factory=_DurationFormatConfig)
    count: _CountFormatConfig = field(default_factory=_CountFormatConfig)


RENDER_CONFIG = _RenderConfig()


def decode_path(path_bytes: bytes) -> str:
    return os.fsdecode(path_bytes)


def _escape_text_field(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


def _text_field(value: object) -> str:
    return _escape_text_field(str(value))


def _text_path(path_bytes: bytes) -> str:
    return _escape_text_field(os.fsdecode(path_bytes))


def _text_group(group: GroupLabel | None) -> str:
    if group is None:
        return "none"
    return f"{group.kind}:{_escape_text_field(group.key)}"


def path_payload(path_bytes: bytes) -> dict[str, str]:
    return {
        "path": decode_path(path_bytes),
        "path_bytes_hex": path_bytes.hex(),
    }


def humanize_bytes(value: int | None) -> str | None:
    if value is None:
        return None

    sign = "-" if value < 0 else ""
    magnitude = float(abs(value))
    unit = RENDER_CONFIG.bytes.units[0]
    for unit in RENDER_CONFIG.bytes.units:
        if magnitude < RENDER_CONFIG.bytes.base or unit == RENDER_CONFIG.bytes.units[-1]:
            break
        magnitude /= RENDER_CONFIG.bytes.base
    if unit == "B":
        return f"{sign}{int(magnitude)} B"
    return f"{sign}{magnitude:.1f} {unit}"


def humanize_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < RENDER_CONFIG.duration.fractional_cutoff_seconds:
        return f"{seconds:.1f}s"

    remaining = max(round(seconds), 0)
    hours, remaining = divmod(remaining, RENDER_CONFIG.duration.seconds_per_hour)
    minutes, remaining = divmod(remaining, RENDER_CONFIG.duration.seconds_per_minute)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{remaining}s")
    return "".join(parts)


@dataclass(frozen=True, slots=True)
class _DiffRenderInput:
    since: str
    limit: int
    effective_limit: int
    group_by: str
    pairs: tuple[SnapshotPair, ...]
    rows: tuple[FrontierRow, ...]
    classification_counts: dict[str, int]
    warnings: tuple[ReportWarning, ...]


@dataclass(frozen=True, slots=True)
class _ReportRenderInput:
    since: str
    limit: int
    effective_limit: int
    group_by: str
    summary: ReportSummary
    pressure_summary: PressureSummary | None


@dataclass(frozen=True, slots=True)
class _DeletedRenderInput:
    since: str
    limit: int
    effective_limit: int
    pairs: tuple[SnapshotPair, ...]
    warnings: tuple[ReportWarning, ...]
    rows: tuple[DiffRow, ...]


@dataclass(frozen=True, slots=True)
class _ExplainPathRenderInput:
    since: str
    limit: int
    effective_limit: int
    depth: int
    group_by: str
    pairs: tuple[SnapshotPair, ...]
    result: ExplainPathResult
    warnings: tuple[ReportWarning, ...]


def _no_positional_arguments(function_name: str, args: tuple[object, ...]) -> None:
    if args:
        plural = "" if len(args) == 1 else "s"
        raise TypeError(f"{function_name}() takes 0 positional argument{plural} but {len(args)} were given")


def _required_str(function_name: str, kwargs: dict[str, object], name: str) -> str:
    try:
        return cast(str, kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_int(function_name: str, kwargs: dict[str, object], name: str) -> int:
    try:
        return int(cast(int | str, kwargs.pop(name)))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_snapshot_pairs(
    function_name: str,
    kwargs: dict[str, object],
    name: str,
) -> tuple[SnapshotPair, ...]:
    try:
        return cast(tuple[SnapshotPair, ...], kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_frontier_rows(
    function_name: str,
    kwargs: dict[str, object],
    name: str,
) -> tuple[FrontierRow, ...]:
    try:
        return cast(tuple[FrontierRow, ...], kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_diff_rows(
    function_name: str,
    kwargs: dict[str, object],
    name: str,
) -> tuple[DiffRow, ...]:
    try:
        return cast(tuple[DiffRow, ...], kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_report_summary(function_name: str, kwargs: dict[str, object], name: str) -> ReportSummary:
    try:
        return cast(ReportSummary, kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_explain_result(function_name: str, kwargs: dict[str, object], name: str) -> ExplainPathResult:
    try:
        return cast(ExplainPathResult, kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _optional_pressure_summary(kwargs: dict[str, object]) -> PressureSummary | None:
    return cast(PressureSummary | None, kwargs.pop("pressure_summary", None))


def _required_report_warnings(
    function_name: str,
    kwargs: dict[str, object],
    name: str,
) -> tuple[ReportWarning, ...]:
    try:
        return cast(tuple[ReportWarning, ...], kwargs.pop(name))
    except KeyError as exc:
        raise TypeError(f"{function_name}() missing required keyword argument: {name!r}") from exc


def _required_top_section_snapshot(section: Mapping[str, object]) -> SnapshotRecord:
    return cast(SnapshotRecord, section["snapshot"])


def _required_top_section_warnings(section: Mapping[str, object]) -> tuple[ReportWarning, ...]:
    return cast(tuple[ReportWarning, ...], section["warnings"])


def _required_top_section_rows(section: Mapping[str, object]) -> tuple[TopRow, ...]:
    return cast(tuple[TopRow, ...], section["rows"])


def render_top_payload(
    *,
    snapshot_selector: str,
    limit: int,
    effective_limit: int,
    group_by: str,
    sections: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    warnings = _dedupe_rendered_warnings(
        warning for section in sections for warning in _required_top_section_warnings(section)
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
                "snapshot": _snapshot_payload(_required_top_section_snapshot(section)),
                "warnings": [_warning_payload(warning) for warning in _required_top_section_warnings(section)],
                "rows": [_top_row_payload(row) for row in _required_top_section_rows(section)],
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
    sections: Sequence[Mapping[str, object]],
) -> str:
    lines = [
        f"command=top snapshot_selector={snapshot_selector} limit={limit} effective_limit={effective_limit} group_by={group_by}"
    ]
    for section in sections:
        snapshot = _required_top_section_snapshot(section)
        lines.append(
            " ".join((
                f"snapshot={snapshot.id}",
                f"root_path={_text_field(snapshot.root_path)}",
                f"started_at={snapshot.started_at}",
                f"finished_at={snapshot.finished_at}",
                f"status={snapshot.status.value}",
                f"error={_text_field(snapshot.error)}",
            ))
        )
        for warning in _required_top_section_warnings(section):
            path_suffix = f" path={_text_path(warning.path)}" if warning.path is not None else ""
            lines.append(f"warning code={warning.code}{path_suffix} message={_text_field(warning.message)}")
        for row in _required_top_section_rows(section):
            parts = [
                f"path={_text_path(row.path)}",
                f"current_disk_bytes={row.current_disk_bytes}",
                f"current_apparent_bytes={row.current_apparent_bytes}",
                f"depth={row.depth}",
                f"file_count={row.file_count}",
                f"dir_count={row.dir_count}",
            ]
            if row.group is not None:
                parts.append(f"group={_text_group(row.group)}")
            if row.error is not None:
                parts.append(f"error={_text_field(row.error)}")
            parts.extend(_collapse_text_parts(row))
            lines.append(" ".join(parts))
    return "\n".join(lines) + "\n"


def render_snapshots_payload(*, limit: int, snapshots: tuple[SnapshotSummary, ...]) -> dict[str, object]:
    return {
        "ok": True,
        "command": "snapshots",
        "limit": limit,
        "snapshots": [_snapshot_summary_payload(summary) for summary in snapshots],
    }


def render_snapshots_text(*, limit: int, snapshots: tuple[SnapshotSummary, ...]) -> str:
    rows = [_snapshot_summary_table_row(summary) for summary in snapshots]
    return (
        "\n".join((
            f"Snapshots: showing {len(snapshots)} of up to {limit}",
            _render_text_table(
                headers=(
                    "ID",
                    "Status",
                    "Root",
                    "Started",
                    "Time",
                    "Rows",
                    "Disk",
                    "Apparent",
                    "Files",
                    "Dirs",
                    "Collapsed",
                    "Errors",
                ),
                rows=tuple(rows),
                right_aligned_columns=frozenset({"ID", "Rows", "Files", "Dirs", "Collapsed", "Errors"}),
            ),
        ))
        + "\n"
    )


def _snapshot_summary_table_row(summary: SnapshotSummary) -> tuple[str, ...]:
    return (
        str(summary.snapshot.id),
        _snapshot_display_status(summary.snapshot),
        _text_field(summary.snapshot.root_path),
        summary.snapshot.started_at,
        humanize_duration(summary.processing_seconds) or "-",
        _human_count(summary.row_count),
        humanize_bytes(summary.indexed_disk_bytes) or "-",
        humanize_bytes(summary.indexed_apparent_bytes) or "-",
        _human_optional_count(summary.file_count),
        _human_optional_count(summary.dir_count),
        _human_count(summary.collapsed_row_count),
        _human_count(summary.error_row_count),
    )


def _snapshot_display_status(snapshot: SnapshotRecord) -> str:
    if snapshot.status is SnapshotStatus.FAILED and snapshot.finished_at is None:
        return "running"
    return snapshot.status.value


def _human_count(value: int) -> str:
    magnitude = float(value)
    unit = RENDER_CONFIG.count.units[0]
    for unit in RENDER_CONFIG.count.units:
        if abs(magnitude) < RENDER_CONFIG.count.base or unit == RENDER_CONFIG.count.units[-1]:
            break
        magnitude /= RENDER_CONFIG.count.base
    if unit == "":
        return str(value)
    return f"{magnitude:.1f}{unit}"


def _human_optional_count(value: int | None) -> str:
    if value is None:
        return "-"
    return _human_count(value)


def _render_text_table(
    *,
    headers: tuple[str, ...],
    rows: tuple[tuple[str, ...], ...],
    right_aligned_columns: frozenset[str],
) -> str:
    widths = tuple(max((len(header), *(len(row[index]) for row in rows))) for index, header in enumerate(headers))
    lines = [
        _render_table_line(headers, widths=widths, right_aligned_columns=right_aligned_columns, headers=headers),
        _render_table_separator(widths),
    ]
    lines.extend(
        _render_table_line(row, widths=widths, right_aligned_columns=right_aligned_columns, headers=headers)
        for row in rows
    )
    return "\n".join(lines)


def _render_table_line(
    values: tuple[str, ...],
    *,
    widths: tuple[int, ...],
    right_aligned_columns: frozenset[str],
    headers: tuple[str, ...],
) -> str:
    cells: list[str] = []
    for index, value in enumerate(values):
        if headers[index] in right_aligned_columns:
            cells.append(value.rjust(widths[index]))
        else:
            cells.append(value.ljust(widths[index]))
    return "  ".join(cells).rstrip()


def _render_table_separator(widths: tuple[int, ...]) -> str:
    return "  ".join("-" * width for width in widths)


def render_diff_payload(*args: object, **kwargs: object) -> dict[str, object]:
    options = _parse_diff_render_input("render_diff_payload", args, kwargs, require_classification_counts=True)
    return _render_diff_payload(options)


def render_diff_text(*args: object, **kwargs: object) -> str:
    options = _parse_diff_render_input("render_diff_text", args, kwargs, require_classification_counts=False)
    return _render_diff_text(options)


def _parse_diff_render_input(
    function_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    *,
    require_classification_counts: bool,
) -> _DiffRenderInput:
    _no_positional_arguments(function_name, args)
    classification_counts = (
        cast(dict[str, int], kwargs.pop("classification_counts", {}))
        if not require_classification_counts
        else cast(dict[str, int], kwargs.pop("classification_counts"))
    )
    options = _DiffRenderInput(
        since=_required_str(function_name, kwargs, "since"),
        limit=_required_int(function_name, kwargs, "limit"),
        effective_limit=_required_int(function_name, kwargs, "effective_limit"),
        group_by=_required_str(function_name, kwargs, "group_by"),
        pairs=_required_snapshot_pairs(function_name, kwargs, "pairs"),
        rows=_required_frontier_rows(function_name, kwargs, "rows"),
        classification_counts=dict(classification_counts),
        warnings=_required_report_warnings(function_name, kwargs, "warnings"),
    )
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"{function_name}() got unexpected keyword arguments: {unexpected}")
    return options


def _render_diff_payload(options: _DiffRenderInput) -> dict[str, object]:
    return {
        "ok": True,
        "command": "diff",
        "since": options.since,
        "limit": options.limit,
        "effective_limit": options.effective_limit,
        "group_by": options.group_by,
        "pairs": [_pair_payload(pair) for pair in options.pairs],
        "rows": [_frontier_row_payload(row) for row in options.rows],
        "classification_counts": dict(sorted(options.classification_counts.items())),
        "warnings": _dedupe_rendered_warnings(options.warnings),
    }


def _render_diff_text(options: _DiffRenderInput) -> str:
    lines = [
        f"command=diff since={options.since} limit={options.limit} effective_limit={options.effective_limit} group_by={options.group_by}"
    ]
    lines.extend(_diff_pair_lines(options.pairs))
    lines.extend(_report_warning_lines(options.warnings))
    lines.extend(_diff_frontier_lines(options.rows))
    return "\n".join(lines) + "\n"


def render_report_payload(*args: object, **kwargs: object) -> dict[str, object]:
    options = _parse_report_render_input("render_report_payload", args, kwargs)
    return _render_report_payload(options)


def render_report_text(*args: object, **kwargs: object) -> str:
    options = _parse_report_render_input("render_report_text", args, kwargs)
    return _render_report_text(options)


def _parse_report_render_input(
    function_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> _ReportRenderInput:
    _no_positional_arguments(function_name, args)
    options = _ReportRenderInput(
        since=_required_str(function_name, kwargs, "since"),
        limit=_required_int(function_name, kwargs, "limit"),
        effective_limit=_required_int(function_name, kwargs, "effective_limit"),
        group_by=_required_str(function_name, kwargs, "group_by"),
        summary=_required_report_summary(function_name, kwargs, "summary"),
        pressure_summary=_optional_pressure_summary(kwargs),
    )
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"{function_name}() got unexpected keyword arguments: {unexpected}")
    return options


def _render_report_payload(options: _ReportRenderInput) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": True,
        "command": "report",
        "since": options.since,
        "limit": options.limit,
        "effective_limit": options.effective_limit,
        "group_by": options.group_by,
        "pairs": [_pair_payload(pair) for pair in options.summary.snapshot_pairs],
        "warnings": _dedupe_rendered_warnings(options.summary.warnings),
        "classification_summary": {
            "counts": dict(sorted(options.summary.classification_counts.items())),
            "disk_bytes_delta_by_classification": dict(
                sorted(options.summary.disk_bytes_delta_by_classification.items())
            ),
            "apparent_bytes_delta_by_classification": dict(
                sorted(options.summary.apparent_bytes_delta_by_classification.items())
            ),
        },
        "group_summary": [_group_summary_payload(group) for group in options.summary.groups],
        "frontier": [_frontier_row_payload(row) for row in options.summary.frontier],
        "deleted_preview": [_diff_row_payload(row) for row in options.summary.deleted_preview],
    }
    if options.pressure_summary is not None:
        payload["diagnostic_hints"] = [
            _diagnostic_hint_payload(hint) for hint in options.pressure_summary.diagnostic_hints
        ]
        payload["pressure_summary"] = _pressure_summary_payload(options.pressure_summary)
    return payload


def _render_report_text(options: _ReportRenderInput) -> str:
    lines = [
        f"command=report since={options.since} limit={options.limit} effective_limit={options.effective_limit} group_by={options.group_by}"
    ]
    lines.extend(_report_pair_lines(options.summary.snapshot_pairs))
    lines.extend(_report_warning_lines(options.summary.warnings))
    lines.extend(_report_classification_lines(options.summary))
    lines.extend(_report_group_lines(options.summary.groups))
    lines.extend(_report_frontier_lines(options.summary.frontier))
    lines.extend(_report_deleted_lines(options.summary.deleted_preview))
    if options.pressure_summary is not None:
        lines.extend(_report_pressure_lines(options.pressure_summary))
    return "\n".join(lines) + "\n"


def _report_pair_lines(pairs: tuple[SnapshotPair, ...]) -> list[str]:
    return [_pair_text_line(pair) for pair in pairs]


def _diff_pair_lines(pairs: tuple[SnapshotPair, ...]) -> list[str]:
    return [_pair_text_line(pair) for pair in pairs]


def _report_warning_lines(warnings: tuple[ReportWarning, ...]) -> list[str]:
    return [_warning_text_line("warning", warning) for warning in warnings]


def _report_classification_lines(summary: ReportSummary) -> list[str]:
    return [
        " ".join((
            "classification_summary",
            f"classification={classification}",
            f"count={count}",
            f"disk_bytes_delta={summary.disk_bytes_delta_by_classification.get(classification, 0)}",
            f"apparent_bytes_delta={summary.apparent_bytes_delta_by_classification.get(classification, 0)}",
        ))
        for classification, count in summary.classification_counts.items()
    ]


def _report_group_lines(groups: tuple[ReportGroupSummary, ...]) -> list[str]:
    return [
        " ".join((
            "group_summary",
            f"group={_text_group(group.group)}",
            f"path_count={group.path_count}",
            f"disk_bytes_delta={group.disk_bytes_delta}",
            f"apparent_bytes_delta={group.apparent_bytes_delta}",
        ))
        for group in groups
    ]


def _report_frontier_lines(rows: tuple[FrontierRow, ...]) -> list[str]:
    return [_frontier_entry_text_line("frontier", frontier_row) for frontier_row in rows]


def _report_deleted_lines(rows: tuple[DiffRow, ...]) -> list[str]:
    return [_deleted_text_line(row) for row in rows]


def _report_pressure_lines(summary: PressureSummary) -> list[str]:
    lines: list[str] = []
    lines.extend([_warning_text_line("pressure_warning", warning) for warning in summary.warnings])
    lines.extend([_diagnostic_hint_text_line(hint) for hint in summary.diagnostic_hints])
    lines.extend([_pressure_section_text_line(section) for section in summary.sections])
    lines.extend(_pressure_fact_lines(summary.sections))
    lines.extend(_pressure_next_check_lines(summary.sections))
    return lines


def _diagnostic_hint_text_line(hint: DiagnosticHint) -> str:
    return " ".join((
        "diagnostic_hint",
        f"code={hint.code}",
        f"storage_domain={_text_field(hint.storage_domain_key)}",
        f"next_checks={','.join(_escape_text_field(check) for check in hint.next_checks) or '-'}",
        f"message={_text_field(hint.message)}",
    ))


def _pressure_section_text_line(section: PressureSummarySection) -> str:
    return " ".join((
        "pressure_section",
        f"storage_domain={_escape_text_field(section.storage_domain_key)}",
        f"filesystem_stat_available={str(section.filesystem_stat_available).lower()}",
        f"unattributed_bytes={section.unattributed_bytes}",
        f"over_indexed_bytes={section.over_indexed_bytes}",
        f"filesystem_usage_ratio={section.filesystem_usage_ratio}",
        f"recent_growth_disk_bytes={section.recent_growth_disk_bytes}",
        f"truncated={str(section.truncated).lower()}",
    ))


def _pressure_fact_lines(sections: tuple[PressureSummarySection, ...]) -> list[str]:
    return [f"pressure_fact={_escape_text_field(fact)}" for section in sections for fact in section.facts]


def _pressure_next_check_lines(sections: tuple[PressureSummarySection, ...]) -> list[str]:
    return [f"pressure_next_check={_escape_text_field(check)}" for section in sections for check in section.next_checks]


def _frontier_text_line(prefix: str, row: DiffRow) -> str:
    parts = [
        prefix,
        f"path={_text_path(row.path)}",
        f"classification={row.classification}",
        f"previous_disk_bytes={row.previous_disk_bytes}",
        f"current_disk_bytes={row.current_disk_bytes}",
        f"disk_bytes_delta={row.disk_bytes_delta}",
        f"previous_apparent_bytes={row.previous_apparent_bytes}",
        f"current_apparent_bytes={row.current_apparent_bytes}",
        f"apparent_bytes_delta={row.apparent_bytes_delta}",
    ]
    if row.group is not None:
        parts.append(f"group={_text_group(row.group)}")
    if row.error is not None:
        parts.append(f"error={_text_field(row.error)}")
    parts.extend(_collapse_text_parts(row))
    return " ".join(parts)


def _frontier_entry_text_line(prefix: str, frontier_row: FrontierRow) -> str:
    parts = [
        _frontier_text_line(prefix, frontier_row.row),
        f"suppressed_descendant_count={frontier_row.suppressed_descendant_count}",
        f"suppressed_ancestor_count={frontier_row.suppressed_ancestor_count}",
        f"reason={_text_field(frontier_row.reason)}",
    ]
    return " ".join(parts)


def _pair_text_line(pair: SnapshotPair) -> str:
    return " ".join((
        f"root_path={_text_field(pair.root_path)}",
        f"baseline={pair.baseline.id}",
        f"current={pair.current.id}",
        f"baseline_finished_at={pair.baseline.finished_at}",
        f"current_finished_at={pair.current.finished_at}",
        f"baseline_status={pair.baseline.status.value}",
        f"current_status={pair.current.status.value}",
        f"warning_codes={','.join(pair.warning_codes) if pair.warning_codes else '-'}",
    ))


def _warning_text_line(prefix: str, warning: ReportWarning) -> str:
    path_suffix = f" path={_text_path(warning.path)}" if warning.path is not None else ""
    return f"{prefix} code={warning.code}{path_suffix} message={_text_field(warning.message)}"


def _diff_frontier_lines(rows: tuple[FrontierRow, ...]) -> list[str]:
    return [_frontier_entry_text_line("frontier", frontier_row) for frontier_row in rows]


def _deleted_text_line(row: DiffRow) -> str:
    parts = [
        f"path={_text_path(row.path)}",
        f"classification={row.classification}",
        f"previous_disk_bytes={row.previous_disk_bytes}",
        f"current_disk_bytes={row.current_disk_bytes}",
        f"disk_bytes_delta={row.disk_bytes_delta}",
    ]
    if row.group is not None:
        parts.append(f"group={_text_group(row.group)}")
    if row.error is not None:
        parts.append(f"error={_text_field(row.error)}")
    parts.extend(_collapse_text_parts(row))
    return " ".join(parts)


def _explain_text_line(prefix: str, row: DiffRow) -> str:
    parts = [
        prefix,
        f"path={_text_path(row.path)}",
        f"classification={row.classification}",
        f"disk_bytes_delta={row.disk_bytes_delta}",
        f"apparent_bytes_delta={row.apparent_bytes_delta}",
    ]
    if row.group is not None:
        parts.append(f"group={_text_group(row.group)}")
    if row.error is not None:
        parts.append(f"error={_text_field(row.error)}")
    parts.extend(_collapse_text_parts(row))
    return " ".join(parts)


def _deleted_row_lines(rows: tuple[DiffRow, ...]) -> list[str]:
    return [_deleted_text_line(row) for row in rows]


def _diagnostic_hint_payload(hint: DiagnosticHint) -> dict[str, object]:
    return {
        "code": hint.code,
        "message": hint.message,
        "next_checks": list(hint.next_checks),
        "storage_domain_key": hint.storage_domain_key,
    }


def _pressure_summary_payload(summary: PressureSummary) -> dict[str, object]:
    return {
        "sections": [_pressure_section_payload(section) for section in summary.sections],
        "next_checks": list(summary.next_checks),
        "limits": dict(summary.limits),
        "truncated_sections": summary.truncated_sections,
        "warnings": _dedupe_rendered_warnings(summary.warnings),
    }


def _pressure_section_payload(section: PressureSummarySection) -> dict[str, object]:
    payload: dict[str, object] = {
        "storage_domain_key": section.storage_domain_key,
        "filesystem_stat_available": section.filesystem_stat_available,
        "filesystem_status": section.filesystem_status,
        "df_used_bytes": section.df_used_bytes,
        "indexed_visible_disk_bytes": section.indexed_visible_disk_bytes,
        "unattributed_bytes": section.unattributed_bytes,
        "over_indexed_bytes": section.over_indexed_bytes,
        "filesystem_usage_ratio": section.filesystem_usage_ratio,
        "recent_growth_disk_bytes": section.recent_growth_disk_bytes,
        "coverage_reason_codes": list(section.coverage_reason_codes),
        "snapshot_statuses": list(section.snapshot_statuses),
        "facts": list(section.facts),
        "next_checks": list(section.next_checks),
        "truncated": section.truncated,
    }
    if section.mount_point is not None:
        payload["mount_point"] = decode_path(section.mount_point)
    return payload


def render_deleted_payload(*args: object, **kwargs: object) -> dict[str, object]:
    options = _parse_deleted_render_input("render_deleted_payload", args, kwargs)
    return _render_deleted_payload(options)


def render_deleted_text(*args: object, **kwargs: object) -> str:
    options = _parse_deleted_render_input("render_deleted_text", args, kwargs)
    return _render_deleted_text(options)


def render_explain_path_payload(*args: object, **kwargs: object) -> dict[str, object]:
    options = _parse_explain_path_render_input("render_explain_path_payload", args, kwargs)
    return _render_explain_path_payload(options)


def render_explain_path_text(*args: object, **kwargs: object) -> str:
    options = _parse_explain_path_render_input("render_explain_path_text", args, kwargs)
    return _render_explain_path_text(options)


def _parse_deleted_render_input(
    function_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> _DeletedRenderInput:
    _no_positional_arguments(function_name, args)
    options = _DeletedRenderInput(
        since=_required_str(function_name, kwargs, "since"),
        limit=_required_int(function_name, kwargs, "limit"),
        effective_limit=_required_int(function_name, kwargs, "effective_limit"),
        pairs=_required_snapshot_pairs(function_name, kwargs, "pairs"),
        warnings=_required_report_warnings(function_name, kwargs, "warnings"),
        rows=_required_diff_rows(function_name, kwargs, "rows"),
    )
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"{function_name}() got unexpected keyword arguments: {unexpected}")
    return options


def _parse_explain_path_render_input(
    function_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> _ExplainPathRenderInput:
    _no_positional_arguments(function_name, args)
    options = _ExplainPathRenderInput(
        since=_required_str(function_name, kwargs, "since"),
        limit=_required_int(function_name, kwargs, "limit"),
        effective_limit=_required_int(function_name, kwargs, "effective_limit"),
        depth=_required_int(function_name, kwargs, "depth"),
        group_by=_required_str(function_name, kwargs, "group_by"),
        pairs=_required_snapshot_pairs(function_name, kwargs, "pairs"),
        result=_required_explain_result(function_name, kwargs, "result"),
        warnings=_required_report_warnings(function_name, kwargs, "warnings"),
    )
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"{function_name}() got unexpected keyword arguments: {unexpected}")
    return options


def _render_deleted_payload(options: _DeletedRenderInput) -> dict[str, object]:
    return {
        "ok": True,
        "command": "deleted",
        "since": options.since,
        "limit": options.limit,
        "effective_limit": options.effective_limit,
        "pairs": [_pair_payload(pair) for pair in options.pairs],
        "warnings": _dedupe_rendered_warnings(options.warnings),
        "rows": [_diff_row_payload(row) for row in options.rows],
    }


def _render_deleted_text(options: _DeletedRenderInput) -> str:
    lines = [f"command=deleted since={options.since} limit={options.limit} effective_limit={options.effective_limit}"]
    lines.extend(_report_pair_lines(options.pairs))
    lines.extend(_report_warning_lines(options.warnings))
    lines.extend(_deleted_row_lines(options.rows))
    return "\n".join(lines) + "\n"


def _render_explain_path_payload(options: _ExplainPathRenderInput) -> dict[str, object]:
    return {
        "ok": True,
        "command": "explain-path",
        "since": options.since,
        "limit": options.limit,
        "effective_limit": options.effective_limit,
        "depth": options.depth,
        "group_by": options.group_by,
        "pairs": [_pair_payload(pair) for pair in options.pairs],
        "target": _diff_row_payload(options.result.target),
        "children": [_diff_row_payload(row) for row in options.result.children],
        "unshown_or_direct_disk_bytes_delta": options.result.unshown_or_direct_disk_bytes_delta,
        "unshown_or_direct_apparent_bytes_delta": options.result.unshown_or_direct_apparent_bytes_delta,
        "warnings": _dedupe_rendered_warnings(options.warnings),
    }


def _render_explain_path_text(options: _ExplainPathRenderInput) -> str:
    lines = [
        f"command=explain-path since={options.since} limit={options.limit} effective_limit={options.effective_limit} depth={options.depth} group_by={options.group_by}"
    ]
    lines.extend(_report_pair_lines(options.pairs))
    lines.extend(_report_warning_lines(options.warnings))
    lines.append(_explain_text_line("target", options.result.target))
    lines.extend(_explain_text_line("child", row) for row in options.result.children)
    lines.append(
        " ".join((
            "remainder_after_shown_children",
            f"unshown_or_direct_disk_bytes_delta={options.result.unshown_or_direct_disk_bytes_delta}",
            f"unshown_or_direct_apparent_bytes_delta={options.result.unshown_or_direct_apparent_bytes_delta}",
        ))
    )
    return "\n".join(lines) + "\n"


def render_df_index_payload(diagnostic: DfIndexDiagnostic) -> dict[str, object]:
    return {
        "ok": diagnostic.ok,
        "command": "df-vs-index",
        "snapshot_selector": diagnostic.snapshot_selector,
        "limit": diagnostic.limit,
        "effective_limit": diagnostic.effective_limit,
        "generated_at": diagnostic.generated_at,
        "filesystems": [_df_index_section_payload(section) for section in diagnostic.filesystems],
        "summary": _df_index_summary_payload(diagnostic),
        "truncated": diagnostic.truncated,
        "total_filesystem_count": diagnostic.total_filesystem_count,
        "warnings": _dedupe_rendered_warnings(diagnostic.warnings),
    }


def render_df_index_text(diagnostic: DfIndexDiagnostic) -> str:
    lines = [
        " ".join((
            "command=df-vs-index",
            f"snapshot_selector={diagnostic.snapshot_selector}",
            f"limit={diagnostic.limit}",
            f"effective_limit={diagnostic.effective_limit}",
            f"generated_at={diagnostic.generated_at}",
            f"truncated={str(diagnostic.truncated).lower()}",
            f"total_filesystem_count={diagnostic.total_filesystem_count}",
        ))
    ]
    for warning in diagnostic.warnings:
        path_suffix = f" path={_text_path(warning.path)}" if warning.path is not None else ""
        lines.append(f"warning code={warning.code}{path_suffix} message={_text_field(warning.message)}")
    for section in diagnostic.filesystems:
        parts = [
            "filesystem",
            f"storage_domain={_escape_text_field(section.storage_domain.key)}",
            f"mount_point={_text_path(section.storage_domain.mount_point)}"
            if section.storage_domain.mount_point is not None
            else "mount_point=none",
            f"snapshot_ids={','.join(str(snapshot_id) for snapshot_id in section.snapshot_ids) or '-'}",
            f"finished_at_min={section.finished_at_min}",
            f"finished_at_max={section.finished_at_max}",
            f"max_snapshot_age_seconds={section.max_snapshot_age_seconds}",
            f"filesystem_stat_available={str(section.filesystem_stat_available).lower()}",
            f"filesystem_status={section.filesystem_status}",
            f"df_used_bytes={section.df_used_bytes}",
            f"indexed_visible_disk_bytes={section.indexed_visible_disk_bytes}",
            f"indexed_visible_apparent_bytes={section.indexed_visible_apparent_bytes}",
            f"indexed_visible_path_count={section.indexed_visible_path_count}",
            f"partial_snapshot_count={section.partial_snapshot_count}",
            f"unknown_mount_count={section.unknown_mount_count}",
            f"filesystem_scope_extends_beyond_indexed_roots={str(section.filesystem_scope_extends_beyond_indexed_roots).lower()}",
            f"unattributed_bytes={section.unattributed_bytes}",
            f"unattributed_ratio={section.unattributed_ratio}",
            f"over_indexed_bytes={section.over_indexed_bytes}",
            f"over_indexed_ratio={section.over_indexed_ratio}",
            f"coverage_reason_codes={','.join(section.coverage_reason_codes) or '-'}",
            f"likely_reasons={','.join(section.likely_reasons) or '-'}",
        ]
        lines.append(" ".join(parts))
        lines.extend([
            f"verification_command={_escape_text_field(command)}" for command in section.verification_commands
        ])
    return "\n".join(lines) + "\n"


def render_deleted_open_payload(diagnostic: DeletedOpenDiagnostic) -> dict[str, object]:
    return {
        "ok": diagnostic.ok,
        "command": "deleted-open-files",
        "limit": diagnostic.limit,
        "effective_limit": diagnostic.effective_limit,
        "generated_at": diagnostic.generated_at,
        "evidence_source": diagnostic.evidence_source,
        "culprits": [_deleted_open_culprit_payload(row) for row in diagnostic.culprits],
        "totals": {
            "culprit_count": diagnostic.totals.culprit_count,
            "shown_count": diagnostic.totals.shown_count,
            "total_size_bytes": diagnostic.totals.total_size_bytes,
            "shown_size_bytes": diagnostic.totals.shown_size_bytes,
            "permission_denied_count": diagnostic.totals.permission_denied_count,
        },
        "truncated": diagnostic.truncated,
        "verification_commands": list(diagnostic.verification_commands),
        "warnings": _dedupe_rendered_warnings(diagnostic.warnings),
    }


def render_deleted_open_text(diagnostic: DeletedOpenDiagnostic) -> str:
    lines = [
        " ".join((
            "command=deleted-open-files",
            f"limit={diagnostic.limit}",
            f"effective_limit={diagnostic.effective_limit}",
            f"generated_at={diagnostic.generated_at}",
            f"evidence_source={diagnostic.evidence_source}",
            f"truncated={str(diagnostic.truncated).lower()}",
            f"culprit_count={diagnostic.totals.culprit_count}",
            f"shown_count={diagnostic.totals.shown_count}",
            f"total_size_bytes={diagnostic.totals.total_size_bytes}",
            f"permission_denied_count={diagnostic.totals.permission_denied_count}",
        ))
    ]
    for warning in diagnostic.warnings:
        path_suffix = f" path={_text_path(warning.path)}" if warning.path is not None else ""
        lines.append(f"warning code={warning.code}{path_suffix} message={_text_field(warning.message)}")
    for row in diagnostic.culprits:
        parts = [
            "culprit",
            f"pid={row.pid}",
            f"command={_text_field(row.command)}",
            f"fd={_escape_text_field(row.fd)}",
            f"size_bytes={row.size_bytes}",
            f"path={_text_path(row.path)}",
            f"storage_domain={_text_group(row.storage_domain)}",
            f"source={row.source}",
            f"action_hint={_text_field(row.action_hint)}",
        ]
        lines.append(" ".join(parts))
    lines.extend([
        f"verification_command={_escape_text_field(command)}" for command in diagnostic.verification_commands
    ])
    return "\n".join(lines) + "\n"


def _deleted_open_culprit_payload(row: DeletedOpenFile) -> dict[str, object]:
    return {
        "pid": row.pid,
        "command": row.command,
        "fd": row.fd,
        "size_bytes": row.size_bytes,
        **path_payload(row.path),
        "storage_domain": _group_payload(row.storage_domain),
        "source": row.source,
        "action_hint": row.action_hint,
    }


def render_docker_enrichment_payload(enrichment: DockerEnrichment) -> dict[str, object]:
    return {
        "ok": enrichment.ok,
        "command": "docker-enrichment",
        "limit": enrichment.limit,
        "effective_limit": enrichment.effective_limit,
        "generated_at": enrichment.generated_at,
        "docker_available": enrichment.docker_available,
        "containerd_available": enrichment.containerd_available,
        "categories": [_docker_category_payload(category) for category in enrichment.categories],
        "build_cache": {
            "entries": [_docker_build_cache_payload(entry) for entry in enrichment.build_cache_entries],
            "entry_count": enrichment.build_cache_totals.entry_count,
            "shown_count": enrichment.build_cache_totals.shown_count,
            "total_bytes": enrichment.build_cache_totals.total_bytes,
            "reclaimable_bytes": enrichment.build_cache_totals.reclaimable_bytes,
            "truncated": enrichment.build_cache_truncated,
        },
        "docker_path_hints": [decode_path(path) for path in enrichment.docker_path_hints],
        "containerd_path_hints": [decode_path(path) for path in enrichment.containerd_path_hints],
        "verification_commands": list(enrichment.verification_commands),
        "warnings": _dedupe_rendered_warnings(enrichment.warnings),
    }


def render_docker_enrichment_text(enrichment: DockerEnrichment) -> str:
    lines = [
        " ".join((
            "command=docker-enrichment",
            f"limit={enrichment.limit}",
            f"effective_limit={enrichment.effective_limit}",
            f"generated_at={enrichment.generated_at}",
            f"docker_available={str(enrichment.docker_available).lower()}",
            f"containerd_available={str(enrichment.containerd_available).lower()}",
            f"build_cache_total_bytes={enrichment.build_cache_totals.total_bytes}",
            f"build_cache_reclaimable_bytes={enrichment.build_cache_totals.reclaimable_bytes}",
            f"build_cache_truncated={str(enrichment.build_cache_truncated).lower()}",
        ))
    ]
    for warning in enrichment.warnings:
        path_suffix = f" path={_text_path(warning.path)}" if warning.path is not None else ""
        lines.append(f"warning code={warning.code}{path_suffix} message={_text_field(warning.message)}")
    for category in enrichment.categories:
        lines.extend([
            " ".join((
                "category",
                f"kind={_escape_text_field(category.kind)}",
                f"total_count={category.total_count}",
                f"active_count={category.active_count}",
                f"size_text={_text_field(category.size_text)}",
                f"size_bytes={category.size_bytes}",
                f"reclaimable_text={_text_field(category.reclaimable_text)}",
                f"reclaimable_bytes={category.reclaimable_bytes}",
            ))
        ])
    lines.extend([
        " ".join((
            "build_cache",
            f"id={_escape_text_field(entry.cache_id)}",
            f"size_bytes={entry.size_bytes}",
            f"reclaimable={str(entry.reclaimable).lower()}",
            f"last_used_at={entry.last_used_at}",
        ))
        for entry in enrichment.build_cache_entries
    ])
    lines.extend([f"docker_path_hint={_text_path(path)}" for path in enrichment.docker_path_hints])
    lines.extend([f"containerd_path_hint={_text_path(path)}" for path in enrichment.containerd_path_hints])
    lines.extend([
        f"verification_command={_escape_text_field(command)}" for command in enrichment.verification_commands
    ])
    return "\n".join(lines) + "\n"


def _docker_category_payload(category: DockerCategory) -> dict[str, object]:
    return {
        "kind": category.kind,
        "total_count": category.total_count,
        "active_count": category.active_count,
        "size_text": category.size_text,
        "size_bytes": category.size_bytes,
        "reclaimable_text": category.reclaimable_text,
        "reclaimable_bytes": category.reclaimable_bytes,
        "source_command": category.source_command,
    }


def _docker_build_cache_payload(entry: DockerBuildCacheEntry) -> dict[str, object]:
    return {
        "id": entry.cache_id,
        "size_bytes": entry.size_bytes,
        "reclaimable": entry.reclaimable,
        "last_used_at": entry.last_used_at,
        "source_command": entry.source_command,
    }


def _df_index_section_payload(section: DfIndexSection) -> dict[str, object]:
    df_bytes: dict[str, object] | None
    if section.filesystem_stat_available and section.df_usage is not None:
        df_bytes = {
            "size": section.df_usage.size_bytes,
            "used": section.df_usage.used_bytes,
            "free_total": section.df_usage.free_total_bytes,
            "avail_unprivileged": section.df_usage.avail_unprivileged_bytes,
        }
    else:
        df_bytes = None
    return {
        "storage_domain": _group_payload(section.storage_domain),
        "snapshot_ids": list(section.snapshot_ids),
        "snapshot_statuses": list(section.snapshot_statuses),
        "finished_at_min": section.finished_at_min,
        "finished_at_max": section.finished_at_max,
        "max_snapshot_age_seconds": section.max_snapshot_age_seconds,
        "filesystem_stat_available": section.filesystem_stat_available,
        "filesystem_status": section.filesystem_status,
        "df_bytes": df_bytes,
        "df_used_bytes": section.df_used_bytes,
        "indexed_visible_disk_bytes": section.indexed_visible_disk_bytes,
        "indexed_visible_apparent_bytes": section.indexed_visible_apparent_bytes,
        "indexed_visible_path_count": section.indexed_visible_path_count,
        "indexed_root_paths": [decode_path(path) for path in section.indexed_root_paths],
        "indexed_mount_points": [decode_path(path) for path in section.indexed_mount_points],
        "partial_snapshot_count": section.partial_snapshot_count,
        "unknown_mount_count": section.unknown_mount_count,
        "filesystem_scope_extends_beyond_indexed_roots": section.filesystem_scope_extends_beyond_indexed_roots,
        "coverage_reason_codes": list(section.coverage_reason_codes),
        "unattributed_bytes": section.unattributed_bytes,
        "unattributed_ratio": section.unattributed_ratio,
        "over_indexed_bytes": section.over_indexed_bytes,
        "over_indexed_ratio": section.over_indexed_ratio,
        "likely_reasons": list(section.likely_reasons),
        "verification_commands": list(section.verification_commands),
    }


def _df_index_summary_payload(diagnostic: DfIndexDiagnostic) -> dict[str, object]:
    available = [section for section in diagnostic.filesystems if section.filesystem_stat_available]
    total_unattributed = sum(section.unattributed_bytes or 0 for section in available)
    total_over_indexed = sum(section.over_indexed_bytes or 0 for section in available)
    total_indexed = sum(section.indexed_visible_disk_bytes for section in diagnostic.filesystems)
    return {
        "filesystem_count": len(diagnostic.filesystems),
        "stat_available_count": len(available),
        "stat_unavailable_count": len(diagnostic.filesystems) - len(available),
        "total_indexed_visible_disk_bytes": total_indexed,
        "total_unattributed_bytes": total_unattributed,
        "total_over_indexed_bytes": total_over_indexed,
    }


def _snapshot_payload(snapshot: SnapshotRecord) -> dict[str, object]:
    return {
        "id": snapshot.id,
        "root_path": str(snapshot.root_path),
        "started_at": snapshot.started_at,
        "finished_at": snapshot.finished_at,
        "status": _snapshot_display_status(snapshot),
        "error": snapshot.error,
    }


def _pair_payload(pair: SnapshotPair) -> dict[str, object]:
    return {
        "root_path": str(pair.root_path),
        "baseline": _snapshot_payload(pair.baseline),
        "current": _snapshot_payload(pair.current),
        "warning_codes": list(pair.warning_codes),
    }


def _snapshot_summary_payload(summary: SnapshotSummary) -> dict[str, object]:
    return {
        "snapshot": _snapshot_payload(summary.snapshot),
        "display_status": _snapshot_display_status(summary.snapshot),
        "processing_seconds": summary.processing_seconds,
        "processing_human": humanize_duration(summary.processing_seconds),
        "row_count": summary.row_count,
        "collapsed_row_count": summary.collapsed_row_count,
        "error_row_count": summary.error_row_count,
        "indexed_apparent_bytes": summary.indexed_apparent_bytes,
        "indexed_apparent_bytes_human": humanize_bytes(summary.indexed_apparent_bytes),
        "indexed_disk_bytes": summary.indexed_disk_bytes,
        "indexed_disk_bytes_human": humanize_bytes(summary.indexed_disk_bytes),
        "file_count": summary.file_count,
        "dir_count": summary.dir_count,
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
    payload.update(_collapse_metadata_payload(row))
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
    payload.update(_collapse_metadata_payload(row))
    return payload


def _diff_row_payload(row: DiffRow) -> dict[str, object]:
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
        "group": _group_payload(row.group),
        "error": row.error,
    }
    payload.update(_collapse_metadata_payload(row))
    return payload


def _collapse_metadata_payload(row: TopRow | DiffRow) -> dict[str, object]:
    if not row.collapsed:
        return {}

    payload: dict[str, object] = {"collapsed": True}
    if row.collapse_reason is not None:
        payload["collapse_reason"] = row.collapse_reason
    if row.collapsed_dirs is not None:
        payload["collapsed_dirs"] = row.collapsed_dirs
    if row.top_child_path is not None:
        top_child: dict[str, object] = {**path_payload(row.top_child_path)}
        if row.top_child_disk_bytes is not None:
            top_child["disk_bytes"] = row.top_child_disk_bytes
        payload["top_child"] = top_child
    return payload


def _collapse_text_parts(row: TopRow | DiffRow) -> list[str]:
    if not row.collapsed:
        return []

    parts = ["collapsed=true"]
    if row.collapse_reason is not None:
        parts.append(f"reason={row.collapse_reason}")
    if row.collapsed_dirs is not None:
        parts.append(f"collapsed_dirs={row.collapsed_dirs}")
    if row.top_child_path is not None:
        parts.append(f"top_child={_text_path(row.top_child_path)}")
    if row.top_child_disk_bytes is not None:
        parts.append(f"top_child_disk_bytes={row.top_child_disk_bytes}")
    return parts


def _group_summary_payload(group: ReportGroupSummary) -> dict[str, object]:
    return {
        "group": _group_payload(group.group),
        "path_count": group.path_count,
        "disk_bytes_delta": group.disk_bytes_delta,
        "apparent_bytes_delta": group.apparent_bytes_delta,
    }


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


def _dedupe_rendered_warnings(warnings: Iterable[ReportWarning]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str | None]] = set()
    for warning in warnings:
        key = (warning.code, decode_path(warning.path) if warning.path is not None else None)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(_warning_payload(warning))
    return deduped
