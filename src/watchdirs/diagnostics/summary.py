from __future__ import annotations

from watchdirs.diagnostics.df_index import MISMATCH_MIN_BYTES, MISMATCH_MIN_RATIO
from watchdirs.models import (
    DfIndexDiagnostic,
    DfIndexSection,
    DiagnosticHint,
    DockerEnrichment,
    DeletedOpenDiagnostic,
    PressureSummary,
    PressureSummarySection,
    ReportGroupSummary,
    ReportWarning,
)


# Compactness limits per D-14 (max sections) and D-15 (max facts/next checks per
# section). D-16 requires these limits and truncation metadata to be explicit in
# the envelope.
DEFAULT_MAX_SECTIONS = 4
DEFAULT_MAX_ITEMS_PER_SECTION = 5

# Global cap on prioritized verification-only next checks.
MAX_GLOBAL_NEXT_CHECKS = 5

# Verification-only commands (read-only). No destructive cleanup, process-control,
# or Docker mutation commands are ever emitted (D-17 / T-03-20).
_DELETED_OPEN_CHECK = "watchdirs deleted-open-files --json"
_DF_INDEX_CHECK = "watchdirs df-vs-index --json"
_DOCKER_CHECK = "watchdirs docker-enrichment --json"
_DF_CHECK = "df -h"


def build_compact_pressure_summary(
    *,
    df_index: DfIndexDiagnostic,
    report_groups: tuple[ReportGroupSummary, ...] = (),
    deleted_open: DeletedOpenDiagnostic | None = None,
    docker: DockerEnrichment | None = None,
    max_sections: int = DEFAULT_MAX_SECTIONS,
    max_items_per_section: int = DEFAULT_MAX_ITEMS_PER_SECTION,
) -> PressureSummary:
    """Combine df/index, report growth groups, deleted-open totals, and Docker
    enrichment into a bounded, prioritized pressure summary.

    Pure transformation: deterministic, side-effect free, no live probes. All
    full deleted-open and Docker evidence stays behind the explicit commands; this
    builder only references them as next checks or compact context.
    """

    growth_by_domain = _growth_by_domain(report_groups)

    docker_facts = _docker_category_facts(docker)
    docker_checks = (_DOCKER_CHECK,) if docker is not None and docker.docker_available else ()

    ranked = sorted(
        df_index.filesystems,
        key=_section_rank_key,
        reverse=True,
    )

    truncated_sections = len(ranked) > max_sections
    visible = ranked[:max_sections]

    sections: list[PressureSummarySection] = []
    hints: list[DiagnosticHint] = []
    for section in visible:
        growth = growth_by_domain.get(section.storage_domain.key, 0)
        summary_section, section_hints = _build_section(
            section,
            recent_growth=growth,
            docker_facts=docker_facts,
            docker_checks=docker_checks,
            deleted_open=deleted_open,
            max_items_per_section=max_items_per_section,
        )
        sections.append(summary_section)
        hints.extend(section_hints)

    warnings: list[ReportWarning] = list(df_index.warnings)
    if docker is not None:
        # Propagate containerd-unavailable and other docker warnings honestly.
        warnings.extend(docker.warnings)

    next_checks = _global_next_checks(sections)

    return PressureSummary(
        sections=tuple(sections),
        diagnostic_hints=tuple(hints),
        next_checks=next_checks,
        limits={
            "max_sections": max_sections,
            "max_items_per_section": max_items_per_section,
        },
        truncated_sections=truncated_sections,
        warnings=tuple(_dedupe_warnings(warnings)),
    )


def _section_rank_key(section: DfIndexSection) -> tuple[int, int, float, int]:
    # Rank by material unattributed bytes first, then over_indexed skew, then high
    # filesystem usage ratio, then recent growth is handled via the report groups
    # join below (kept stable here for unavailable domains that sort last).
    unattributed = section.unattributed_bytes or 0
    over_indexed = section.over_indexed_bytes or 0
    ratio = _usage_ratio(section) or 0.0
    available = 1 if section.filesystem_stat_available else 0
    return (available, unattributed, ratio, over_indexed)


def _build_section(
    section: DfIndexSection,
    *,
    recent_growth: int,
    docker_facts: tuple[str, ...],
    docker_checks: tuple[str, ...],
    deleted_open: DeletedOpenDiagnostic | None,
    max_items_per_section: int,
) -> tuple[PressureSummarySection, list[DiagnosticHint]]:
    key = section.storage_domain.key
    facts: list[str] = []
    next_checks: list[str] = []
    hints: list[DiagnosticHint] = []

    ratio = _usage_ratio(section)

    if not section.filesystem_stat_available:
        facts.append(
            f"evidence: live filesystem stat unavailable ({section.filesystem_status}); "
            "indexed totals shown without a df comparison"
        )
        next_checks.append(_DF_CHECK)
        next_checks.append(_DF_INDEX_CHECK)
        hints.append(
            DiagnosticHint(
                code="filesystem_stat_unavailable",
                message=(
                    f"storage-domain {key} could not be statted; the mountpoint may be "
                    "stale or absent"
                ),
                next_checks=(_DF_CHECK, _DF_INDEX_CHECK),
                storage_domain_key=key,
            )
        )
    else:
        if section.df_used_bytes is not None:
            facts.append(
                f"evidence: df used {section.df_used_bytes} bytes vs indexed visible "
                f"{section.indexed_visible_disk_bytes} bytes"
            )
        if ratio is not None:
            facts.append(f"evidence: filesystem usage ratio {ratio:.3f}")

        unattributed = section.unattributed_bytes or 0
        over_indexed = section.over_indexed_bytes or 0
        material = "deleted_open_file_suspected" in section.likely_reasons or _is_material(section)

        if unattributed > 0 and material:
            scope_extends = section.filesystem_scope_extends_beyond_indexed_roots
            is_partial = section.partial_snapshot_count > 0 or any(
                status != "complete" for status in section.snapshot_statuses
            )
            deleted_open_independent = (
                deleted_open is not None and deleted_open.totals.total_size_bytes > 0
            )

            facts.append(
                f"likely reason: {unattributed} bytes of filesystem usage are not "
                "attributed to indexed directories"
            )
            hints.append(
                DiagnosticHint(
                    code="unattributed_usage",
                    message=(
                        f"storage-domain {key} has {unattributed} unattributed bytes; "
                        "investigate evidence gaps before any action"
                    ),
                    next_checks=(_DF_INDEX_CHECK, _DOCKER_CHECK),
                    storage_domain_key=key,
                )
            )
            next_checks.append(_DF_INDEX_CHECK)

            if scope_extends:
                facts.append(
                    "likely reason: indexed roots cover only part of the filesystem; "
                    "the remainder may be outside scanned scope"
                )
                hints.append(
                    DiagnosticHint(
                        code="filesystem_scope_extends_beyond_indexed_roots",
                        message=(
                            f"storage-domain {key} remainder is explained by partial "
                            "filesystem coverage, not necessarily deleted-open files"
                        ),
                        next_checks=(_DF_INDEX_CHECK,),
                        storage_domain_key=key,
                    )
                )
            if is_partial:
                facts.append(
                    "likely reason: selected snapshot evidence is non-complete; "
                    "remainder cannot confirm deleted-open files alone"
                )
                hints.append(
                    DiagnosticHint(
                        code="partial_snapshot_evidence",
                        message=(
                            f"storage-domain {key} has partial snapshot evidence; "
                            "deleted-open suspicion needs an independent probe"
                        ),
                        next_checks=(_DELETED_OPEN_CHECK,),
                        storage_domain_key=key,
                    )
                )

            # Deleted-open suspicion requires full coverage AND complete snapshot
            # evidence, OR independent deleted-open evidence supplied to the builder.
            deleted_open_allowed = (
                (not scope_extends and not is_partial) or deleted_open_independent
            )
            if deleted_open_allowed:
                facts.append(
                    "likely reason: deleted-but-open files may still hold the missing space"
                )
                hints.append(
                    DiagnosticHint(
                        code="deleted_open_file_suspected",
                        message=(
                            f"storage-domain {key} remainder may be held by deleted-open "
                            "files; verify with a live probe"
                        ),
                        next_checks=(_DELETED_OPEN_CHECK,),
                        storage_domain_key=key,
                    )
                )
                next_checks.append(_DELETED_OPEN_CHECK)

        elif over_indexed > 0:
            facts.append(
                f"evidence: indexed totals exceed df used by {over_indexed} bytes "
                "(snapshot skew or stale index)"
            )
            hints.append(
                DiagnosticHint(
                    code="over_indexed_skew",
                    message=(
                        f"storage-domain {key} indexed totals exceed live df by "
                        f"{over_indexed} bytes; re-collect to refresh the index"
                    ),
                    next_checks=(_DF_INDEX_CHECK,),
                    storage_domain_key=key,
                )
            )
            next_checks.append(_DF_INDEX_CHECK)
        elif ratio is not None and ratio >= 0.85:
            # Capacity case: little unattributed remainder but the filesystem is nearly
            # full. Guidance is cautious evaluation only, never an action (D-17).
            facts.append(
                "next check: filesystem is near capacity; consider evaluating an upgrade, "
                "data migration, or older-disk repurposing"
            )
            hints.append(
                DiagnosticHint(
                    code="capacity_pressure",
                    message=(
                        f"storage-domain {key} is near capacity with little unexplained "
                        "usage; evaluate capacity options"
                    ),
                    next_checks=(_DF_INDEX_CHECK,),
                    storage_domain_key=key,
                )
            )

    if recent_growth > 0:
        facts.append(f"evidence: recent growth {recent_growth} bytes from report frontier")

    if docker_facts:
        facts.extend(docker_facts)
        next_checks.extend(docker_checks)

    # Enforce D-15 caps with truncation flags.
    truncated = len(facts) > max_items_per_section or len(next_checks) > max_items_per_section
    facts_capped = tuple(facts[:max_items_per_section])
    next_checks_capped = tuple(_dedupe_preserve(next_checks)[:max_items_per_section])

    summary_section = PressureSummarySection(
        storage_domain_key=key,
        mount_point=section.storage_domain.mount_point,
        filesystem_stat_available=section.filesystem_stat_available,
        filesystem_status=section.filesystem_status,
        df_used_bytes=section.df_used_bytes,
        indexed_visible_disk_bytes=section.indexed_visible_disk_bytes,
        unattributed_bytes=section.unattributed_bytes,
        over_indexed_bytes=section.over_indexed_bytes,
        filesystem_usage_ratio=ratio,
        recent_growth_disk_bytes=recent_growth,
        coverage_reason_codes=section.coverage_reason_codes,
        snapshot_statuses=section.snapshot_statuses,
        facts=facts_capped,
        next_checks=next_checks_capped,
        truncated=truncated,
    )
    return summary_section, hints


def _docker_category_facts(docker: DockerEnrichment | None) -> tuple[str, ...]:
    if docker is None or not docker.docker_available:
        return ()
    facts: list[str] = []
    for category in docker.categories:
        if category.reclaimable_bytes:
            facts.append(
                f"evidence: docker {category.kind} reclaimable {category.reclaimable_bytes} bytes"
            )
    return tuple(facts[:1])  # keep compact; one category fact at section level


def _growth_by_domain(report_groups: tuple[ReportGroupSummary, ...]) -> dict[str, int]:
    growth: dict[str, int] = {}
    for group in report_groups:
        if group.group is None:
            continue
        growth[group.group.key] = growth.get(group.group.key, 0) + group.disk_bytes_delta
    return growth


def _global_next_checks(sections: list[PressureSummarySection]) -> tuple[str, ...]:
    ordered: list[str] = []
    for section in sections:
        for check in section.next_checks:
            ordered.append(check)
    return tuple(_dedupe_preserve(ordered)[:MAX_GLOBAL_NEXT_CHECKS])


def _usage_ratio(section: DfIndexSection) -> float | None:
    if not section.filesystem_stat_available or section.df_usage is None:
        return None
    if section.df_usage.size_bytes <= 0:
        return None
    return section.df_usage.used_bytes / section.df_usage.size_bytes


def _is_material(section: DfIndexSection) -> bool:
    # A material remainder is one the df/index builder already flagged via likely
    # reasons, or a positive unattributed remainder with a meaningful ratio. The
    # df/index builder is the source of truth for thresholds, so prefer its signal.
    if section.likely_reasons:
        return True
    unattributed = section.unattributed_bytes or 0
    ratio = section.unattributed_ratio or 0.0
    return unattributed >= MISMATCH_MIN_BYTES and ratio >= MISMATCH_MIN_RATIO


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _dedupe_warnings(warnings: list[ReportWarning]) -> list[ReportWarning]:
    seen: set[tuple[str, bytes | None]] = set()
    out: list[ReportWarning] = []
    for warning in warnings:
        key = (warning.code, warning.path)
        if key in seen:
            continue
        seen.add(key)
        out.append(warning)
    return out
