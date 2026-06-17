from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from watchdirs.models import (
    DockerBuildCacheEntry,
    DockerBuildCacheTotals,
    DockerCategory,
    DockerEnrichment,
    ReportWarning,
)

# Fixed, read-only Docker argv. ``--format json`` requests structured output so
# the parser never depends on pretty-table layout. The argv is constant: no user
# input is ever interpolated and ``shell=False`` is always used (T-03-11/D-13).
_SYSTEM_DF_ARGV: tuple[str, ...] = ("docker", "system", "df", "--format", "json")
_BUILDX_DU_ARGV: tuple[str, ...] = ("docker", "buildx", "du", "--format", "json")

_SYSTEM_DF_COMMAND = "docker system df --format json"
_BUILDX_DU_COMMAND = "docker buildx du --format json"

# Path prefix that signals containerd-native storage may matter. We surface it as
# a path hint only: this module has no containerd-native probe, so it must never
# present containerd category totals (D-11 review resolution).
_CONTAINERD_PREFIX = b"/var/lib/containerd"
_DOCKER_PREFIX = b"/var/lib/docker"

# Read-only verification next checks (D-12/D-13): no cleanup, prune, stop, rm, or
# any daemon-mutating command is ever suggested.
_VERIFICATION_COMMANDS: tuple[str, ...] = (
    _SYSTEM_DF_COMMAND,
    _BUILDX_DU_COMMAND,
    "watchdirs df-vs-index --json",
)

# A runner returns ``(stdout, stderr, returncode)`` for a fixed argv. It is the
# sole host seam for Docker execution so tests inject deterministic results
# without spawning the live binary.
DockerRunner = Callable[[list[str]], tuple[bytes, bytes, int]]
TimeProvider = Callable[[], str]


@dataclass(slots=True)
class DockerCollectionState:
    categories: list[DockerCategory]
    build_cache_entries: list[DockerBuildCacheEntry]
    warnings: list[ReportWarning]
    docker_available: bool


_UNIT_FACTORS: dict[str, int] = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "PB": 1000**5,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
    "PIB": 1024**5,
}


def default_docker_runner(argv: list[str]) -> tuple[bytes, bytes, int]:
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        check=False,
    )
    return completed.stdout, completed.stderr, completed.returncode


def _default_generated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_size_text(text: object) -> str | None:
    if text is None:
        return None
    value = str(text).strip()
    if not value:
        return None
    return value.split("(", 1)[0].strip()


def _parse_size_text(text: object) -> int | None:
    """Parse a Docker human size such as ``20GB`` / ``9.5GiB`` into bytes.

    Returns ``None`` when the value is missing, ``0`` for a bare ``0``, or
    unparseable so the caller keeps the raw text label without guessing.
    """

    result: int | None = None
    value = _normalize_size_text(text)
    if value is None:
        return None
    # Reclaimable strings can carry a trailing percentage like ``12GB (60%)``.
    if value in ("0", "0B"):
        return 0
    number = ""
    unit = ""
    for char in value:
        if char.isdigit() or char in ".,":
            number += char
        else:
            unit += char
    number = number.replace(",", "")
    unit = unit.strip().upper()
    if number:
        try:
            magnitude = float(number)
        except ValueError:
            pass
        else:
            if not unit:
                result = int(magnitude)
            else:
                factor = _UNIT_FACTORS.get(unit)
                if factor is not None:
                    result = int(magnitude * factor)
    return result


def _iter_json_lines(stdout: bytes) -> tuple[list[dict[str, object]], list[ReportWarning]]:
    records: list[dict[str, object]] = []
    warnings: list[ReportWarning] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line == b"":
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(
                ReportWarning(
                    code="docker_malformed_output",
                    message="skipped a malformed Docker JSON line",
                )
            )
            continue
        if isinstance(decoded, list):
            # Some Docker clients emit a single JSON array instead of NDJSON.
            # Accept each object element rather than discarding the whole payload.
            for item in decoded:
                if isinstance(item, dict):
                    records.append(item)
                else:
                    warnings.append(
                        ReportWarning(
                            code="docker_malformed_output",
                            message="skipped a non-object Docker JSON element",
                        )
                    )
            continue
        if not isinstance(decoded, dict):
            warnings.append(
                ReportWarning(
                    code="docker_malformed_output",
                    message="skipped a non-object Docker JSON line",
                )
            )
            continue
        records.append(decoded)
    return records, warnings


def parse_docker_system_df(stdout: bytes) -> tuple[list[DockerCategory], list[ReportWarning]]:
    """Normalize ``docker system df --format json`` NDJSON into category rows.

    Each line is a JSON object with ``Type`` (Images / Containers / Local
    Volumes / Build Cache), ``TotalCount``, ``Active``, ``Size`` and
    ``Reclaimable``. Blank and malformed lines are tolerated as warnings.
    """

    records, warnings = _iter_json_lines(stdout)
    categories: list[DockerCategory] = []
    for record in records:
        kind = record.get("Type")
        if kind is None:
            warnings.append(
                ReportWarning(
                    code="docker_malformed_output",
                    message="docker system df row had no Type field",
                )
            )
            continue
        size_text = record.get("Size")
        reclaimable_text = record.get("Reclaimable")
        categories.append(
            DockerCategory(
                kind=str(kind),
                total_count=_coerce_int(record.get("TotalCount")),
                active_count=_coerce_int(record.get("Active")),
                size_text=str(size_text) if size_text is not None else None,
                size_bytes=_parse_size_text(size_text),
                reclaimable_text=str(reclaimable_text) if reclaimable_text is not None else None,
                reclaimable_bytes=_parse_size_text(reclaimable_text),
                source_command=_SYSTEM_DF_COMMAND,
            )
        )
    return categories, warnings


def parse_docker_buildx_du(
    stdout: bytes,
) -> tuple[list[DockerBuildCacheEntry], DockerBuildCacheTotals, list[ReportWarning]]:
    """Normalize ``docker buildx du --format json`` NDJSON into build-cache rows.

    Each line is a JSON object with ``ID``, ``Size`` (bytes) and ``Reclaimable``.
    Blank output is a valid empty result, not an error.
    """

    records, warnings = _iter_json_lines(stdout)
    entries: list[DockerBuildCacheEntry] = []
    total_bytes = 0
    reclaimable_bytes = 0
    for record in records:
        cache_id = record.get("ID")
        # `docker buildx du --format json` emits Size as either a raw byte int
        # (older clients) or a human string such as "8.192kB" (current clients),
        # so accept both: try integer coercion first, then human-size parsing.
        raw_size = record.get("Size")
        size = _coerce_int(raw_size)
        if size is None:
            size = _parse_size_text(raw_size)
        if size is None:
            size = 0
            warnings.append(
                ReportWarning(
                    code="docker_malformed_output",
                    message="buildx du row had no parseable Size; counted as 0 bytes",
                )
            )
        reclaimable = bool(record.get("Reclaimable", False))
        last_used = record.get("LastUsedAt")
        entries.append(
            DockerBuildCacheEntry(
                cache_id=str(cache_id) if cache_id is not None else "?",
                size_bytes=size,
                reclaimable=reclaimable,
                last_used_at=str(last_used) if last_used is not None else None,
                source_command=_BUILDX_DU_COMMAND,
            )
        )
        total_bytes += size
        if reclaimable:
            reclaimable_bytes += size
    totals = DockerBuildCacheTotals(
        entry_count=len(entries),
        shown_count=len(entries),
        total_bytes=total_bytes,
        reclaimable_bytes=reclaimable_bytes,
    )
    return entries, totals, warnings


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _collect_docker_state(
    runner: DockerRunner,
    generated_at_provider: TimeProvider,
) -> tuple[str, DockerCollectionState]:
    generated_at = generated_at_provider()
    categories: list[DockerCategory] = []
    build_cache_entries: list[DockerBuildCacheEntry] = []
    warnings: list[ReportWarning] = []
    docker_available = False

    df_stdout, df_ok = _run_probe(runner, _SYSTEM_DF_ARGV, _SYSTEM_DF_COMMAND, warnings)
    if df_ok is True:
        docker_available = True
        parsed_categories, parse_warnings = parse_docker_system_df(df_stdout)
        categories.extend(parsed_categories)
        warnings.extend(parse_warnings)

    du_stdout, du_ok = _run_probe(runner, _BUILDX_DU_ARGV, _BUILDX_DU_COMMAND, warnings)
    if du_ok is True:
        docker_available = True
        parsed_entries, _totals, parse_warnings = parse_docker_buildx_du(du_stdout)
        build_cache_entries.extend(parsed_entries)
        warnings.extend(parse_warnings)

    if df_ok is None and du_ok is None:
        warnings.append(
            ReportWarning(
                code="docker_unavailable",
                message="docker CLI not found; Docker enrichment is unavailable",
            )
        )

    return generated_at, DockerCollectionState(
        categories=categories,
        build_cache_entries=build_cache_entries,
        warnings=warnings,
        docker_available=docker_available,
    )


def collect_docker_enrichment(
    *,
    indexed_path_hints: tuple[bytes, ...] = (),
    limit: int = 20,
    docker_runner: DockerRunner | None = None,
    generated_at_provider: TimeProvider = _default_generated_at,
) -> DockerEnrichment:
    """Collect auxiliary Docker category and build-cache evidence (read-only).

    The ``docker_runner`` host seam defaults to the live Docker CLI; tests inject
    deterministic substitutes. Docker absence, daemon errors, empty output and
    malformed lines all degrade to warnings rather than crashing, so non-Docker
    diagnostics are never broken (D-12).

    ``/var/lib/containerd`` path hints are surfaced as evidence that containerd
    storage may matter, but because this module has no containerd-native probe it
    emits ``containerd_available=false`` and a ``containerd_enrichment_unavailable``
    warning instead of fabricating containerd category totals (D-11).
    """

    runner = docker_runner if docker_runner is not None else default_docker_runner
    generated_at, state = _collect_docker_state(runner, generated_at_provider)
    warnings = state.warnings

    build_cache_entries = state.build_cache_entries
    build_cache_entries.sort(key=lambda entry: entry.size_bytes, reverse=True)
    entry_count = len(build_cache_entries)
    shown_entries = build_cache_entries[:limit]
    build_cache_truncated = entry_count > limit
    build_cache_totals = DockerBuildCacheTotals(
        entry_count=entry_count,
        shown_count=len(shown_entries),
        total_bytes=sum(entry.size_bytes for entry in build_cache_entries),
        reclaimable_bytes=sum(entry.size_bytes for entry in build_cache_entries if entry.reclaimable),
    )

    docker_path_hints = tuple(hint for hint in indexed_path_hints if _has_prefix(hint, _DOCKER_PREFIX))
    containerd_path_hints = tuple(hint for hint in indexed_path_hints if _has_prefix(hint, _CONTAINERD_PREFIX))

    containerd_available = False
    if containerd_path_hints:
        warnings.append(
            ReportWarning(
                code="containerd_enrichment_unavailable",
                message=(
                    "containerd path hints detected but no containerd-native probe is "
                    "implemented; these are path context only, not reclaimable/active "
                    "category totals"
                ),
            )
        )

    return DockerEnrichment(
        ok=True,
        limit=limit,
        effective_limit=limit,
        generated_at=generated_at,
        docker_available=state.docker_available,
        containerd_available=containerd_available,
        categories=tuple(state.categories),
        build_cache_entries=tuple(shown_entries),
        build_cache_totals=build_cache_totals,
        build_cache_truncated=build_cache_truncated,
        docker_path_hints=docker_path_hints,
        containerd_path_hints=containerd_path_hints,
        verification_commands=_VERIFICATION_COMMANDS,
        warnings=tuple(warnings),
    )


def _run_probe(
    runner: DockerRunner,
    argv: tuple[str, ...],
    command_label: str,
    warnings: list[ReportWarning],
) -> tuple[bytes, bool | None]:
    """Run one read-only Docker probe.

    Returns ``(stdout, ok)`` where ``ok`` is ``True`` on a usable success,
    ``False`` on a daemon/command failure, and ``None`` when the CLI is absent
    (FileNotFoundError). Failures only append warnings; they never raise.
    """

    try:
        stdout, stderr, returncode = runner(list(argv))
    except FileNotFoundError:
        return b"", None
    except OSError as exc:
        warnings.append(
            ReportWarning(
                code="docker_command_failed",
                message=f"{command_label} could not be executed ({exc})",
            )
        )
        return b"", False

    if returncode != 0:
        detail = _summarize_stderr(stderr)
        if _looks_like_daemon_error(stderr):
            warnings.append(
                ReportWarning(
                    code="docker_daemon_error",
                    message=f"{command_label} reported a daemon error: {detail}",
                )
            )
        else:
            warnings.append(
                ReportWarning(
                    code="docker_command_failed",
                    message=f"{command_label} exited {returncode}: {detail}",
                )
            )
        return stdout, False

    if stderr:
        warnings.append(
            ReportWarning(
                code="docker_stderr",
                message=f"{command_label} emitted warnings: {_summarize_stderr(stderr)}",
            )
        )
    return stdout, True


def _looks_like_daemon_error(stderr: bytes) -> bool:
    text = stderr.decode("utf-8", errors="replace").lower()
    return "cannot connect to the docker daemon" in text or "is the docker daemon running" in text


def _has_prefix(path_bytes: bytes, prefix: bytes) -> bool:
    return path_bytes == prefix or path_bytes.startswith(prefix + b"/")


def _summarize_stderr(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "; ".join(lines[:5]) if lines else "(empty)"
