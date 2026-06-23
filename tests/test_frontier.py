# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import sys
from pathlib import Path


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _diff_row(
    models_module,
    *,
    root_path: str,
    baseline_id: int,
    current_id: int,
    path: bytes,
    parent_path: bytes | None,
    depth: int,
    classification: str,
    previous_disk_bytes: int,
    current_disk_bytes: int,
    previous_apparent_bytes: int,
    current_apparent_bytes: int,
):
    return models_module.DiffRow(
        root_path=Path(root_path),
        baseline_snapshot_id=baseline_id,
        current_snapshot_id=current_id,
        path=path,
        parent_path=parent_path,
        depth=depth,
        classification=classification,
        previous_apparent_bytes=previous_apparent_bytes,
        current_apparent_bytes=current_apparent_bytes,
        apparent_bytes_delta=current_apparent_bytes - previous_apparent_bytes,
        previous_disk_bytes=previous_disk_bytes,
        current_disk_bytes=current_disk_bytes,
        disk_bytes_delta=current_disk_bytes - previous_disk_bytes,
        error=None,
        group=None,
    )


def test_prune_growth_frontier_prefers_descendants_that_explain_ninety_five_percent_of_ancestor_growth(
    repo_root: Path,
) -> None:
    frontier = import_module(repo_root, "watchdirs.reporting.frontier")
    models_module = import_module(repo_root, "watchdirs.models")

    rows = (
        _diff_row(
            models_module,
            root_path="/",
            baseline_id=1,
            current_id=2,
            path=b"/",
            parent_path=None,
            depth=0,
            classification="grown",
            previous_disk_bytes=100,
            current_disk_bytes=200,
            previous_apparent_bytes=100,
            current_apparent_bytes=200,
        ),
        _diff_row(
            models_module,
            root_path="/",
            baseline_id=1,
            current_id=2,
            path=b"/var",
            parent_path=b"/",
            depth=1,
            classification="grown",
            previous_disk_bytes=50,
            current_disk_bytes=146,
            previous_apparent_bytes=50,
            current_apparent_bytes=146,
        ),
        _diff_row(
            models_module,
            root_path="/",
            baseline_id=1,
            current_id=2,
            path=b"/var/lib/containerd",
            parent_path=b"/var/lib",
            depth=3,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=40,
            previous_apparent_bytes=20,
            current_apparent_bytes=40,
        ),
        _diff_row(
            models_module,
            root_path="/",
            baseline_id=1,
            current_id=2,
            path=b"/var/log",
            parent_path=b"/var",
            depth=2,
            classification="shrunk",
            previous_disk_bytes=40,
            current_disk_bytes=30,
            previous_apparent_bytes=40,
            current_apparent_bytes=30,
        ),
        _diff_row(
            models_module,
            root_path="/",
            baseline_id=1,
            current_id=2,
            path=b"/tmp",
            parent_path=b"/",
            depth=1,
            classification="grown",
            previous_disk_bytes=10,
            current_disk_bytes=70,
            previous_apparent_bytes=10,
            current_apparent_bytes=70,
        ),
    )

    pruned = frontier.prune_growth_frontier(rows)

    assert frontier.FRONTIER_DOMINANCE_RATIO == 0.95
    assert [entry.row.path for entry in pruned] == [b"/var", b"/tmp"]
    assert pruned[0].suppressed_ancestor_count == 1
    assert pruned[0].suppressed_descendant_count == 1
    assert pruned[0].reason
    assert pruned[1].suppressed_ancestor_count == 0
    assert pruned[1].suppressed_descendant_count == 0


def test_prune_growth_frontier_only_compares_positive_candidates_within_same_root_and_snapshot_pair(
    repo_root: Path,
) -> None:
    frontier = import_module(repo_root, "watchdirs.reporting.frontier")
    models_module = import_module(repo_root, "watchdirs.models")

    rows = (
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv",
            parent_path=None,
            depth=0,
            classification="grown",
            previous_disk_bytes=100,
            current_disk_bytes=200,
            previous_apparent_bytes=100,
            current_apparent_bytes=200,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=12,
            path=b"/srv/cache",
            parent_path=b"/srv",
            depth=1,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=140,
            previous_apparent_bytes=20,
            current_apparent_bytes=140,
        ),
        _diff_row(
            models_module,
            root_path="/var",
            baseline_id=10,
            current_id=11,
            path=b"/var",
            parent_path=None,
            depth=0,
            classification="grown",
            previous_disk_bytes=90,
            current_disk_bytes=210,
            previous_apparent_bytes=90,
            current_apparent_bytes=210,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/unchanged",
            parent_path=b"/srv",
            depth=1,
            classification="unchanged",
            previous_disk_bytes=50,
            current_disk_bytes=50,
            previous_apparent_bytes=50,
            current_apparent_bytes=50,
        ),
    )

    pruned = frontier.prune_growth_frontier(rows)

    assert [entry.row.path for entry in pruned] == [b"/srv/cache", b"/var", b"/srv"]
    assert all(entry.row.classification == "grown" for entry in pruned)


def test_explain_path_breakdown_subtracts_only_shown_immediate_children_once_even_when_grandchildren_are_visible(
    repo_root: Path,
) -> None:
    frontier = import_module(repo_root, "watchdirs.reporting.frontier")
    models_module = import_module(repo_root, "watchdirs.models")

    rows = (
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache",
            parent_path=b"/srv",
            depth=1,
            classification="grown",
            previous_disk_bytes=100,
            current_disk_bytes=260,
            previous_apparent_bytes=100,
            current_apparent_bytes=260,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/a",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=120,
            previous_apparent_bytes=20,
            current_apparent_bytes=120,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/a/leaf",
            parent_path=b"/srv/cache/a",
            depth=3,
            classification="grown",
            previous_disk_bytes=10,
            current_disk_bytes=110,
            previous_apparent_bytes=10,
            current_apparent_bytes=110,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/b",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=60,
            previous_apparent_bytes=20,
            current_apparent_bytes=60,
        ),
    )

    result = frontier.explain_path_breakdown(rows, target_path=b"/srv/cache", limit=1, depth=2)

    assert result.target.path == b"/srv/cache"
    assert [row.path for row in result.children] == [b"/srv/cache/a"]
    assert result.unshown_or_direct_disk_bytes_delta == 60
    assert result.unshown_or_direct_apparent_bytes_delta == 60


def test_explain_path_breakdown_limit_caps_total_rendered_children(repo_root: Path) -> None:
    frontier = import_module(repo_root, "watchdirs.reporting.frontier")
    models_module = import_module(repo_root, "watchdirs.models")

    rows = (
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache",
            parent_path=b"/srv",
            depth=1,
            classification="grown",
            previous_disk_bytes=100,
            current_disk_bytes=340,
            previous_apparent_bytes=100,
            current_apparent_bytes=340,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/a",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=140,
            previous_apparent_bytes=20,
            current_apparent_bytes=140,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/a/leaf",
            parent_path=b"/srv/cache/a",
            depth=3,
            classification="grown",
            previous_disk_bytes=10,
            current_disk_bytes=130,
            previous_apparent_bytes=10,
            current_apparent_bytes=130,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/b",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=100,
            previous_apparent_bytes=20,
            current_apparent_bytes=100,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/c",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=20,
            current_disk_bytes=60,
            previous_apparent_bytes=20,
            current_apparent_bytes=60,
        ),
    )

    result = frontier.explain_path_breakdown(rows, target_path=b"/srv/cache", limit=2, depth=2)

    assert [row.path for row in result.children] == [b"/srv/cache/a", b"/srv/cache/a/leaf"]
    assert result.unshown_or_direct_disk_bytes_delta == 120
    assert result.unshown_or_direct_apparent_bytes_delta == 120


def test_explain_path_breakdown_depth_zero_shows_only_target_and_leaves_all_growth_in_remainder(
    repo_root: Path,
) -> None:
    frontier = import_module(repo_root, "watchdirs.reporting.frontier")
    models_module = import_module(repo_root, "watchdirs.models")

    rows = (
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache",
            parent_path=b"/srv",
            depth=1,
            classification="grown",
            previous_disk_bytes=50,
            current_disk_bytes=150,
            previous_apparent_bytes=50,
            current_apparent_bytes=150,
        ),
        _diff_row(
            models_module,
            root_path="/srv",
            baseline_id=10,
            current_id=11,
            path=b"/srv/cache/a",
            parent_path=b"/srv/cache",
            depth=2,
            classification="grown",
            previous_disk_bytes=10,
            current_disk_bytes=60,
            previous_apparent_bytes=10,
            current_apparent_bytes=60,
        ),
    )

    result = frontier.explain_path_breakdown(rows, target_path=b"/srv/cache", limit=5, depth=0)

    assert result.target.path == b"/srv/cache"
    assert result.children == ()
    assert result.unshown_or_direct_disk_bytes_delta == 100
    assert result.unshown_or_direct_apparent_bytes_delta == 100
