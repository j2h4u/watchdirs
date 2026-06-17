from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from watchdirs.models import (
    DfIndexDiagnostic,
    DfIndexSection,
    FilesystemUsage,
    IndexedStorageDomainTotal,
    ReportWarning,
)
from watchdirs.reporting.pairs import parse_finished_at_utc
from watchdirs.reporting.queries import query_indexed_storage_domain_totals

# A mismatch between filesystem used bytes and indexed visible bytes is only
# material when both the absolute byte floor and the ratio threshold are met.
MISMATCH_MIN_BYTES = 1 * 1024**3
MISMATCH_MIN_RATIO = 0.05

# Verification-only next checks. These are read-only diagnostics: no destructive
# cleanup, process-control, or Docker mutation commands per D-07.
_DELETED_OPEN_COMMANDS = (
    "watchdirs deleted-open-files --json",
    "lsof +L1 -nP",
)
_GENERAL_COMMANDS = (
    "df -h",
    "watchdirs docker-enrichment --json",
)


StatProvider = Callable[[bytes], "os.statvfs_result"]
ScopeProvider = Callable[[IndexedStorageDomainTotal], bool]
TimeProvider = Callable[[], str]


def default_stat_provider(path: bytes) -> os.statvfs_result:
    return os.statvfs(path)


def _default_generated_at() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class DfIndexProviders:
    stat_provider: StatProvider = default_stat_provider
    generated_at_provider: TimeProvider = _default_generated_at
    filesystem_scope_provider: ScopeProvider | None = None


DEFAULT_DF_INDEX_PROVIDERS = DfIndexProviders()


def build_df_index_diagnostic(
    connection: sqlite3.Connection,
    *,
    snapshot_selector: str = "latest",
    limit: int,
    providers: DfIndexProviders = DEFAULT_DF_INDEX_PROVIDERS,
    **legacy_kwargs,
) -> DfIndexDiagnostic:
    """Reconcile persisted indexed storage-domain totals against live df totals.

    The stat provider is invoked only for storage domains returned by
    ``query_indexed_storage_domain_totals`` (never every live mount). Each
    per-domain stat call is isolated: an ``OSError`` for one domain marks only
    that domain unavailable and the command keeps reconciling the rest.
    """

    if legacy_kwargs:
        stat_provider = legacy_kwargs.pop("stat_provider", providers.stat_provider)
        generated_at_provider = legacy_kwargs.pop("generated_at_provider", providers.generated_at_provider)
        filesystem_scope_provider = legacy_kwargs.pop("filesystem_scope_provider", providers.filesystem_scope_provider)
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            raise TypeError(f"unexpected keyword argument(s): {unexpected}")
        providers = DfIndexProviders(
            stat_provider=stat_provider,
            generated_at_provider=generated_at_provider,
            filesystem_scope_provider=filesystem_scope_provider,
        )

    generated_at = providers.generated_at_provider()
    generated_dt = _safe_parse(generated_at)

    domains = query_indexed_storage_domain_totals(connection, snapshot_selector=snapshot_selector)

    sections: list[DfIndexSection] = []
    warnings: list[ReportWarning] = []
    for domain in domains:
        section = _build_section(
            domain,
            generated_dt=generated_dt,
            stat_provider=providers.stat_provider,
            filesystem_scope_provider=providers.filesystem_scope_provider,
            warnings=warnings,
        )
        sections.append(section)

    # Order by the most actionable remainder first; unavailable domains sort last.
    # Stable secondary order is storage-domain key ascending.
    sections.sort(key=lambda section: section.storage_domain.key)
    sections.sort(
        key=lambda section: (
            1 if section.filesystem_stat_available else 0,
            section.unattributed_bytes or 0,
        ),
        reverse=True,
    )

    total_filesystem_count = len(sections)
    truncated = total_filesystem_count > limit
    visible_sections = tuple(sections[:limit])

    return DfIndexDiagnostic(
        ok=True,
        snapshot_selector=snapshot_selector,
        limit=limit,
        effective_limit=limit,
        generated_at=generated_at,
        filesystems=visible_sections,
        truncated=truncated,
        total_filesystem_count=total_filesystem_count,
        warnings=tuple(warnings),
    )


def _build_section(
    domain: IndexedStorageDomainTotal,
    *,
    generated_dt: datetime | None,
    stat_provider: StatProvider,
    filesystem_scope_provider: ScopeProvider | None,
    warnings: list[ReportWarning],
) -> DfIndexSection:
    storage_domain = domain.storage_domain
    probe_path = _probe_path(domain)

    coverage_reason_codes: list[str] = []
    max_age = _max_snapshot_age_seconds(domain, generated_dt)

    is_partial = domain.partial_snapshot_count > 0
    if is_partial:
        coverage_reason_codes.append("partial_snapshot_evidence")
        warnings.append(
            ReportWarning(
                code="partial_snapshot_evidence",
                message=(
                    f"storage-domain {storage_domain.key} has {domain.partial_snapshot_count} non-complete snapshot(s)"
                ),
                path=storage_domain.mount_point,
            )
        )
    if domain.unknown_mount_count > 0:
        warnings.append(
            ReportWarning(
                code="unknown_mount",
                message=(
                    f"storage-domain {storage_domain.key} has "
                    f"{domain.unknown_mount_count} directory row(s) without a persisted mount prefix"
                ),
                path=storage_domain.mount_point,
            )
        )
    if domain.negative_total_clamped:
        coverage_reason_codes.append("indexed_total_clamped_negative")
        warnings.append(
            ReportWarning(
                code="indexed_total_clamped_negative",
                message=(
                    f"storage-domain {storage_domain.key} indexed total was "
                    "negative (inconsistent nested-submount aggregates) and was "
                    "clamped to zero"
                ),
                path=storage_domain.mount_point,
            )
        )

    if filesystem_scope_provider is not None:
        scope_extends = filesystem_scope_provider(domain)
    else:
        scope_extends = _default_scope_extends(domain)
    if scope_extends:
        coverage_reason_codes.append("indexed_roots_are_subtrees_of_filesystem")

    # Per-domain stat isolation: a failure marks only this domain unavailable.
    try:
        stat = stat_provider(probe_path)
    except OSError as exc:
        coverage_reason_codes.append("filesystem_stat_unavailable")
        warnings.append(
            ReportWarning(
                code="filesystem_stat_unavailable",
                message=f"statvfs failed for {os.fsdecode(probe_path)}: {exc}",
                path=probe_path,
            )
        )
        return DfIndexSection(
            storage_domain=storage_domain,
            snapshot_ids=domain.snapshot_ids,
            snapshot_statuses=domain.snapshot_statuses,
            finished_at_min=domain.finished_at_min,
            finished_at_max=domain.finished_at_max,
            max_snapshot_age_seconds=max_age,
            filesystem_stat_available=False,
            filesystem_status="stat_unavailable",
            df_usage=None,
            df_used_bytes=None,
            indexed_visible_disk_bytes=domain.indexed_visible_disk_bytes,
            indexed_visible_apparent_bytes=domain.indexed_visible_apparent_bytes,
            indexed_visible_path_count=domain.indexed_visible_path_count,
            indexed_root_paths=domain.indexed_root_paths,
            indexed_mount_points=domain.indexed_mount_points,
            partial_snapshot_count=domain.partial_snapshot_count,
            unknown_mount_count=domain.unknown_mount_count,
            filesystem_scope_extends_beyond_indexed_roots=scope_extends,
            coverage_reason_codes=tuple(coverage_reason_codes),
            unattributed_bytes=None,
            unattributed_ratio=None,
            over_indexed_bytes=None,
            over_indexed_ratio=None,
            likely_reasons=(),
            verification_commands=(),
        )

    usage = _filesystem_usage(stat)
    unattributed = max(usage.used_bytes - domain.indexed_visible_disk_bytes, 0)
    over_indexed = max(domain.indexed_visible_disk_bytes - usage.used_bytes, 0)
    denominator = max(0, usage.used_bytes)
    unattributed_ratio = (unattributed / denominator) if denominator > 0 else None
    over_indexed_ratio = (over_indexed / denominator) if denominator > 0 else None

    likely_reasons, verification_commands = _classify_mismatch(
        unattributed_bytes=unattributed,
        unattributed_ratio=unattributed_ratio,
        scope_extends=scope_extends,
        is_partial=is_partial,
        unknown_mount_count=domain.unknown_mount_count,
    )

    return DfIndexSection(
        storage_domain=storage_domain,
        snapshot_ids=domain.snapshot_ids,
        snapshot_statuses=domain.snapshot_statuses,
        finished_at_min=domain.finished_at_min,
        finished_at_max=domain.finished_at_max,
        max_snapshot_age_seconds=max_age,
        filesystem_stat_available=True,
        filesystem_status="ok",
        df_usage=usage,
        df_used_bytes=usage.used_bytes,
        indexed_visible_disk_bytes=domain.indexed_visible_disk_bytes,
        indexed_visible_apparent_bytes=domain.indexed_visible_apparent_bytes,
        indexed_visible_path_count=domain.indexed_visible_path_count,
        indexed_root_paths=domain.indexed_root_paths,
        indexed_mount_points=domain.indexed_mount_points,
        partial_snapshot_count=domain.partial_snapshot_count,
        unknown_mount_count=domain.unknown_mount_count,
        filesystem_scope_extends_beyond_indexed_roots=scope_extends,
        coverage_reason_codes=tuple(coverage_reason_codes),
        unattributed_bytes=unattributed,
        unattributed_ratio=unattributed_ratio,
        over_indexed_bytes=over_indexed,
        over_indexed_ratio=over_indexed_ratio,
        likely_reasons=likely_reasons,
        verification_commands=verification_commands,
    )


def _classify_mismatch(
    *,
    unattributed_bytes: int,
    unattributed_ratio: float | None,
    scope_extends: bool,
    is_partial: bool,
    unknown_mount_count: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    material = (
        unattributed_bytes >= MISMATCH_MIN_BYTES
        and unattributed_ratio is not None
        and unattributed_ratio >= MISMATCH_MIN_RATIO
    )
    if not material:
        return (), ()

    reasons: list[str] = []
    commands: list[str] = list(_GENERAL_COMMANDS)

    # Deleted-open suspicion requires complete coverage and complete snapshot
    # evidence for this storage-domain. Partial coverage or partial snapshots make
    # the remainder a coverage fact, not a deleted-open conclusion (D-03/D-04).
    deleted_open_allowed = not scope_extends and not is_partial
    if deleted_open_allowed:
        reasons.append("deleted_open_file_suspected")
        commands.extend(_DELETED_OPEN_COMMANDS)
    else:
        if scope_extends:
            reasons.append("filesystem_scope_beyond_indexed_roots")
        if is_partial:
            reasons.append("skipped_or_partial_scan_evidence")
    if unknown_mount_count > 0 and "skipped_or_partial_scan_evidence" not in reasons:
        reasons.extend(("skipped_or_partial_scan_evidence",))

    # Always-applicable bounded reasons for a material remainder.
    reasons.extend(("docker_or_containerd_storage", "reserved_or_metadata_accounting"))

    return tuple(reasons), tuple(commands)


def _filesystem_usage(stat: os.statvfs_result) -> FilesystemUsage:
    frsize = stat.f_frsize
    size = stat.f_blocks * frsize
    free_total = stat.f_bfree * frsize
    avail_unprivileged = stat.f_bavail * frsize
    used = size - free_total
    return FilesystemUsage(
        size_bytes=size,
        used_bytes=used,
        free_total_bytes=free_total,
        avail_unprivileged_bytes=avail_unprivileged,
    )


def _probe_path(domain: IndexedStorageDomainTotal) -> bytes:
    mount_point = domain.storage_domain.mount_point
    if mount_point is not None:
        return mount_point
    if domain.indexed_mount_points:
        return domain.indexed_mount_points[0]
    if domain.indexed_root_paths:
        return domain.indexed_root_paths[0]
    raise ValueError(f"storage-domain {domain.storage_domain.key} has no probe path")


def _default_scope_extends(domain: IndexedStorageDomainTotal) -> bool:
    mount_point = domain.storage_domain.mount_point
    if mount_point is None:
        return False
    # Filesystem scope extends beyond indexed roots when every indexed root is a
    # strict subtree of the live filesystem mount point.
    for root_path in domain.indexed_root_paths:
        if root_path == mount_point or not _is_subtree(root_path, mount_point):
            return False
    return bool(domain.indexed_root_paths)


def _is_subtree(path: bytes, ancestor: bytes) -> bool:
    if ancestor == b"/":
        return path.startswith(b"/") and path != b"/"
    return path.startswith(ancestor + b"/")


def _max_snapshot_age_seconds(domain: IndexedStorageDomainTotal, generated_dt: datetime | None) -> int | None:
    if generated_dt is None or domain.finished_at_min is None:
        return None
    finished = _safe_parse(domain.finished_at_min)
    if finished is None:
        return None
    return max(int((generated_dt - finished).total_seconds()), 0)


def _safe_parse(raw_value: str | None) -> datetime | None:
    try:
        return parse_finished_at_utc(raw_value)
    except ValueError:
        return None
