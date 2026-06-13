from __future__ import annotations

from pathlib import Path
import sys


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _diff_row(models_module, *, root_path: str, baseline_id: int, current_id: int, path: bytes, parent_path: bytes | None,
              depth: int, classification: str, previous_disk_bytes: int, current_disk_bytes: int,
              previous_apparent_bytes: int, current_apparent_bytes: int):
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

    assert [entry.row.path for entry in pruned] == [b"/var", b"/srv/cache", b"/srv"]
    assert all(entry.row.classification == "grown" for entry in pruned)
