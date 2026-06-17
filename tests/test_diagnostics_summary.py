from __future__ import annotations

import sys
from pathlib import Path


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


GIB = 1024**3


# ---------------------------------------------------------------------------
# Synthetic builders. These avoid any host-dependent state so the compact
# pressure summary contract is asserted deterministically.
# ---------------------------------------------------------------------------


def _storage_domain(models_module, *, key: str, mount_point: bytes):
    return models_module.GroupLabel(
        kind="storage-domain",
        key=key,
        mount_point=mount_point,
        filesystem_type="ext4",
        mount_source="/dev/" + key.split("|", 1)[0].replace(":", "_"),
        major_minor=key.split("|", 1)[0],
        root=b"/",
    )


def _df_section(
    models_module,
    *,
    key: str,
    mount_point: bytes,
    df_used_bytes: int | None,
    indexed_visible_disk_bytes: int,
    unattributed_bytes: int | None,
    over_indexed_bytes: int | None = 0,
    filesystem_stat_available: bool = True,
    filesystem_status: str = "ok",
    scope_extends: bool = False,
    coverage_reason_codes: tuple[str, ...] = (),
    partial_snapshot_count: int = 0,
    likely_reasons: tuple[str, ...] = (),
    snapshot_statuses: tuple[str, ...] = ("complete",),
):
    used = df_used_bytes or 0
    denom = max(0, used)
    df_usage = None
    if filesystem_stat_available and df_used_bytes is not None:
        # Synthetic filesystem sized so the used ratio is meaningful: total is used
        # plus a small free remainder.
        size = used + (10 * GIB)
        df_usage = models_module.FilesystemUsage(
            size_bytes=size,
            used_bytes=used,
            free_total_bytes=size - used,
            avail_unprivileged_bytes=size - used,
        )
    return models_module.DfIndexSection(
        storage_domain=_storage_domain(models_module, key=key, mount_point=mount_point),
        snapshot_ids=(1,),
        snapshot_statuses=snapshot_statuses,
        finished_at_min="2026-06-13T18:00:00Z",
        finished_at_max="2026-06-13T18:00:00Z",
        max_snapshot_age_seconds=300,
        filesystem_stat_available=filesystem_stat_available,
        filesystem_status=filesystem_status,
        df_usage=df_usage,
        df_used_bytes=df_used_bytes,
        indexed_visible_disk_bytes=indexed_visible_disk_bytes,
        indexed_visible_apparent_bytes=indexed_visible_disk_bytes,
        indexed_visible_path_count=10,
        indexed_root_paths=(mount_point,),
        indexed_mount_points=(mount_point,),
        partial_snapshot_count=partial_snapshot_count,
        unknown_mount_count=0,
        filesystem_scope_extends_beyond_indexed_roots=scope_extends,
        coverage_reason_codes=coverage_reason_codes,
        unattributed_bytes=unattributed_bytes,
        unattributed_ratio=(unattributed_bytes / denom) if (unattributed_bytes and denom) else None,
        over_indexed_bytes=over_indexed_bytes,
        over_indexed_ratio=(over_indexed_bytes / denom) if (over_indexed_bytes and denom) else None,
        likely_reasons=likely_reasons,
        verification_commands=(),
    )


def _df_diagnostic(models_module, sections):
    return models_module.DfIndexDiagnostic(
        ok=True,
        snapshot_selector="latest",
        limit=20,
        effective_limit=20,
        generated_at="2026-06-13T18:05:00Z",
        filesystems=tuple(sections),
        truncated=False,
        total_filesystem_count=len(sections),
        warnings=(),
    )


def _report_group(models_module, *, key: str, mount_point: bytes, disk_bytes_delta: int):
    return models_module.ReportGroupSummary(
        group=_storage_domain(models_module, key=key, mount_point=mount_point),
        path_count=3,
        disk_bytes_delta=disk_bytes_delta,
        apparent_bytes_delta=disk_bytes_delta,
    )


def _docker_enrichment(models_module, *, available: bool, containerd_available: bool, containerd_warning: bool = False):
    categories = (
        (
            models_module.DockerCategory(
                kind="Build Cache",
                total_count=52,
                active_count=0,
                size_text="7.451GB",
                size_bytes=7 * GIB,
                reclaimable_text="7.451GB",
                reclaimable_bytes=7 * GIB,
                source_command="docker system df --format json",
            ),
        )
        if available
        else ()
    )
    warnings = ()
    if containerd_warning:
        warnings = (
            models_module.ReportWarning(
                code="containerd_enrichment_unavailable",
                message="containerd path hints present but no containerd probe exists",
            ),
        )
    return models_module.DockerEnrichment(
        ok=True,
        limit=20,
        effective_limit=20,
        generated_at="2026-06-13T18:05:00Z",
        docker_available=available,
        containerd_available=containerd_available,
        categories=categories,
        build_cache_entries=(),
        build_cache_totals=models_module.DockerBuildCacheTotals(
            entry_count=0, shown_count=0, total_bytes=0, reclaimable_bytes=0
        ),
        build_cache_truncated=False,
        docker_path_hints=(),
        containerd_path_hints=(b"/var/lib/containerd",) if containerd_warning else (),
        verification_commands=("docker system df --format json",),
        warnings=warnings,
    )


def _deleted_open(models_module, *, total_size_bytes: int, culprit_count: int):
    return models_module.DeletedOpenDiagnostic(
        ok=True,
        limit=20,
        effective_limit=20,
        generated_at="2026-06-13T18:05:00Z",
        evidence_source="lsof",
        culprits=(),
        totals=models_module.DeletedOpenTotals(
            culprit_count=culprit_count,
            shown_count=culprit_count,
            total_size_bytes=total_size_bytes,
            shown_size_bytes=total_size_bytes,
            permission_denied_count=0,
        ),
        truncated=False,
        verification_commands=("lsof +L1 -nP",),
        warnings=(),
    )


# ---------------------------------------------------------------------------
# Compact pressure summary contract (DIAG-05, D-14..D-17).
# ---------------------------------------------------------------------------


def test_summary_ranks_top_n_domains_by_pressure_evidence(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=200 * GIB,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=190 * GIB,
            likely_reasons=("deleted_open_file_suspected",),
        ),
        _df_section(
            models_module,
            key="8:33|/|ext4|/dev/data",
            mount_point=b"/data",
            df_used_bytes=50 * GIB,
            indexed_visible_disk_bytes=48 * GIB,
            unattributed_bytes=2 * GIB,
        ),
    ]
    df = _df_diagnostic(models_module, sections)
    groups = (
        _report_group(models_module, key="8:33|/|ext4|/dev/data", mount_point=b"/data", disk_bytes_delta=5 * GIB),
    )

    result = summary_module.build_compact_pressure_summary(
        df_index=df,
        report_groups=groups,
    )

    assert len(result.sections) >= 1
    # The domain with the largest unattributed remainder is ranked first.
    assert result.sections[0].storage_domain_key == "8:1|/|ext4|/dev/root"
    first = result.sections[0]
    assert first.unattributed_bytes == 190 * GIB
    # Usage ratio is surfaced when stat data is available.
    assert first.filesystem_usage_ratio is not None
    # Recent growth evidence from report grouping is wired to the data domain.
    data_section = next(s for s in result.sections if s.storage_domain_key == "8:33|/|ext4|/dev/data")
    assert data_section.recent_growth_disk_bytes == 5 * GIB


def test_summary_caps_sections_and_items_with_truncation_metadata(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    # Six domains -> default max_sections=4 must truncate to four sections.
    sections = [
        _df_section(
            models_module,
            key=f"8:{n}|/|ext4|/dev/d{n}",
            mount_point=f"/d{n}".encode(),
            df_used_bytes=(100 - n) * GIB,
            indexed_visible_disk_bytes=1 * GIB,
            unattributed_bytes=(100 - n) * GIB - 1 * GIB,
        )
        for n in range(1, 7)
    ]
    df = _df_diagnostic(models_module, sections)

    result = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())

    # D-14: no more than 4 sections by default.
    assert len(result.sections) <= 4
    assert result.truncated_sections is True
    # D-16: the envelope carries explicit limits.
    assert result.limits["max_sections"] == 4
    assert result.limits["max_items_per_section"] == 5
    # D-15: no section carries more than 5 facts or next checks.
    for section in result.sections:
        assert len(section.facts) <= 5
        assert len(section.next_checks) <= 5
        # D-16: per-section truncation flag exists.
        assert isinstance(section.truncated, bool)


def test_summary_next_checks_are_prioritized_verification_only_and_capped(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=200 * GIB,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=190 * GIB,
            likely_reasons=("deleted_open_file_suspected",),
        ),
    ]
    df = _df_diagnostic(models_module, sections)

    result = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())

    assert len(result.next_checks) <= 5
    blob = " ".join(result.next_checks)
    # Verification-only: reference the explicit read-only commands.
    assert "deleted-open-files" in blob or "df-vs-index" in blob
    # D-17: no destructive / mutation guidance anywhere.
    forbidden = (
        "rm -rf",
        "kill ",
        "docker builder prune",
        "docker image prune",
        "prune -af",
        "docker rmi",
        "systemctl stop",
        "is safe",
    )
    full_blob = (
        blob
        + " ".join(fact for section in result.sections for fact in section.facts)
        + " ".join(check for section in result.sections for check in section.next_checks)
    )
    for token in forbidden:
        assert token not in full_blob


def test_summary_capacity_guidance_is_cautious_evidence_not_prescription(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    # A nearly-full filesystem with little unattributed remainder is a capacity case:
    # guidance may mention upgrade/migration/repurposing as evaluation, not action.
    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=190 * GIB,
            indexed_visible_disk_bytes=188 * GIB,
            unattributed_bytes=2 * GIB,
        ),
    ]
    df = _df_diagnostic(models_module, sections)

    result = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())

    full_text = (
        " ".join(result.next_checks)
        + " ".join(check for section in result.sections for check in section.next_checks)
        + " ".join(fact for section in result.sections for fact in section.facts)
    )
    # D-17: never asserts an action is safe.
    assert "is safe" not in full_text
    assert "safe to delete" not in full_text
    # Capacity wording is evaluation-only.
    assert "evaluate" in full_text.lower() or "consider" in full_text.lower() or "next check" in full_text.lower()


def test_summary_includes_docker_category_context_only_when_available(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=200 * GIB,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=190 * GIB,
        ),
    ]
    df = _df_diagnostic(models_module, sections)
    docker = _docker_enrichment(models_module, available=True, containerd_available=False)

    result = summary_module.build_compact_pressure_summary(
        df_index=df,
        report_groups=(),
        docker=docker,
    )
    blob = " ".join(result.next_checks) + " ".join(fact for section in result.sections for fact in section.facts)
    assert "Build Cache" in blob or "reclaimable" in blob.lower() or "docker" in blob.lower()

    # No docker supplied -> no docker category facts fabricated.
    result_none = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())
    blob_none = " ".join(fact for section in result_none.sections for fact in section.facts)
    assert "Build Cache" not in blob_none


def test_summary_surfaces_containerd_unavailable_without_category_totals(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=200 * GIB,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=190 * GIB,
        ),
    ]
    df = _df_diagnostic(models_module, sections)
    docker = _docker_enrichment(models_module, available=True, containerd_available=False, containerd_warning=True)

    result = summary_module.build_compact_pressure_summary(
        df_index=df,
        report_groups=(),
        docker=docker,
    )
    warning_codes = {warning.code for warning in result.warnings}
    assert "containerd_enrichment_unavailable" in warning_codes
    # No fabricated containerd category total appears.
    blob = " ".join(fact for section in result.sections for fact in section.facts)
    assert "containerd" not in blob.lower() or "unavailable" in blob.lower()


def test_summary_carries_partial_snapshot_and_unavailable_evidence(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=None,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=None,
            filesystem_stat_available=False,
            filesystem_status="stat_unavailable",
            coverage_reason_codes=("filesystem_stat_unavailable",),
        ),
        _df_section(
            models_module,
            key="8:33|/|ext4|/dev/data",
            mount_point=b"/data",
            df_used_bytes=200 * GIB,
            indexed_visible_disk_bytes=10 * GIB,
            unattributed_bytes=190 * GIB,
            partial_snapshot_count=1,
            coverage_reason_codes=("partial_snapshot_evidence",),
            snapshot_statuses=("partial",),
        ),
    ]
    df = _df_diagnostic(models_module, sections)

    result = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())

    by_key = {section.storage_domain_key: section for section in result.sections}
    unavailable = by_key["8:1|/|ext4|/dev/root"]
    assert unavailable.filesystem_stat_available is False
    partial = by_key["8:33|/|ext4|/dev/data"]
    assert "partial_snapshot_evidence" in partial.coverage_reason_codes


def test_summary_over_indexed_skew_is_ranked_evidence(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    summary_module = import_module(repo_root, "watchdirs.diagnostics.summary")

    # No material unattributed remainder but a large over_indexed skew should still
    # produce a ranked section (snapshot-skew evidence).
    sections = [
        _df_section(
            models_module,
            key="8:1|/|ext4|/dev/root",
            mount_point=b"/",
            df_used_bytes=30 * GIB,
            indexed_visible_disk_bytes=40 * GIB,
            unattributed_bytes=0,
            over_indexed_bytes=10 * GIB,
        ),
    ]
    df = _df_diagnostic(models_module, sections)

    result = summary_module.build_compact_pressure_summary(df_index=df, report_groups=())

    assert len(result.sections) >= 1
    section = result.sections[0]
    assert section.over_indexed_bytes == 10 * GIB
