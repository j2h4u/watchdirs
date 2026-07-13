"""Contract tests for the standalone interval-storage conversion spike.

The fixture uses the script's SQLite helper API directly. Interval bounds are
half-open: ``valid_from_snapshot_id <= N < valid_to_snapshot_id``.
"""

# pyright: reportMissingParameterType=false, reportAny=false, reportExplicitAny=false
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any


def import_module(repo_root: Path, module_name: str):
    """Import a standalone script from the repository root."""
    root = str(repo_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    return __import__(module_name, fromlist=["__name__"])


def _connections(spike: Any, snapshots: dict[int, dict[int, dict[str, int | None]]]) -> tuple[Any, Any]:
    source = sqlite3.connect(":memory:")
    source.row_factory = sqlite3.Row
    source.executescript(
        """
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE directory_sizes (
            snapshot_id INTEGER NOT NULL,
            path_id INTEGER NOT NULL,
            parent_id INTEGER,
            depth INTEGER NOT NULL,
            apparent_bytes INTEGER NOT NULL,
            disk_bytes INTEGER NOT NULL,
            file_count INTEGER NOT NULL,
            dir_count INTEGER NOT NULL,
            error TEXT,
            collapsed INTEGER NOT NULL,
            collapse_reason TEXT,
            collapsed_dirs INTEGER,
            top_child_id INTEGER,
            top_child_disk_bytes INTEGER
        );
        """
    )
    candidate = sqlite3.connect(":memory:")
    candidate.row_factory = sqlite3.Row
    spike.create_candidate(candidate)

    path_ids = sorted({path_id for rows in snapshots.values() for path_id in rows})
    snapshot_ids = sorted(snapshots)
    source.executemany(
        "INSERT INTO snapshots (id, root_path, status) VALUES (?, ?, ?)",
        ((snapshot_id, "/", "complete") for snapshot_id in snapshot_ids),
    )
    candidate.executemany(
        "INSERT INTO snapshots (id, started_at, root_path, status) VALUES (?, ?, ?, ?)",
        ((snapshot_id, f"t{snapshot_id}", "/", "complete") for snapshot_id in snapshot_ids),
    )
    source_rows = []
    for snapshot_id, rows in snapshots.items():
        for path_id, state in rows.items():
            source_rows.append((
                snapshot_id,
                path_id,
                state["parent_id"],
                state["depth"],
                state["apparent_bytes"],
                state["disk_bytes"],
                state["file_count"],
                state["dir_count"],
                state["error"],
                state["collapsed"],
                state["collapse_reason"],
                state["collapsed_dirs"],
                state["top_child_id"],
                state["top_child_disk_bytes"],
            ))
    source.executemany(
        """
        INSERT INTO directory_sizes
        (snapshot_id, path_id, parent_id, depth, apparent_bytes, disk_bytes,
         file_count, dir_count, error, collapsed, collapse_reason,
         collapsed_dirs, top_child_id, top_child_disk_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        source_rows,
    )
    candidate.executemany(
        "INSERT INTO paths (id, path) VALUES (?, ?)", ((path_id, f"/path/{path_id}") for path_id in path_ids)
    )
    source.commit()
    candidate.commit()
    return source, candidate


def _state(apparent_bytes: int, disk_bytes: int, *, file_count: int = 1) -> dict[str, int | None]:
    return {
        "parent_id": None,
        "depth": 1,
        "apparent_bytes": apparent_bytes,
        "disk_bytes": disk_bytes,
        "file_count": file_count,
        "dir_count": 0,
        "error": None,
        "collapsed": 0,
        "collapse_reason": None,
        "collapsed_dirs": None,
        "top_child_id": None,
        "top_child_disk_bytes": None,
    }


def _build(repo_root: Path, snapshots: dict[int, dict[int, dict[str, int | None]]]) -> tuple[Any, Any, Any]:
    spike = import_module(repo_root, "scripts.interval_storage_spike")
    source, candidate = _connections(spike, snapshots)
    spike.build_intervals(source, candidate)
    candidate.commit()
    return spike, source, candidate


def _interval_bounds(candidate: Any, path_id: int) -> list[tuple[int, int | None]]:
    rows = candidate.execute(
        """
        SELECT valid_from_snapshot_id, valid_to_snapshot_id
        FROM directory_size_intervals
        WHERE path_id = ?
        ORDER BY valid_from_snapshot_id
        """,
        (path_id,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def test_unchanged_aggregate_keeps_one_open_version(repo_root: Path) -> None:
    aggregate = _state(100, 128)
    spike, source, candidate = _build(repo_root, {1: {7: aggregate}, 2: {7: aggregate}})

    assert _interval_bounds(candidate, 7) == [(1, None)]
    assert [tuple(row) for row in spike.state_at(candidate, 2, True)] == [
        tuple(row) for row in spike.state_at(source, 2, False)
    ]


def test_changed_aggregate_closes_at_change_and_opens_new_version(repo_root: Path) -> None:
    before = _state(100, 128)
    after = _state(200, 256, file_count=2)
    spike, source, candidate = _build(repo_root, {1: {7: before}, 2: {7: after}})

    assert _interval_bounds(candidate, 7) == [(1, 2), (2, None)]
    assert [row["apparent_bytes"] for row in spike.state_at(candidate, 1, True)] == [100]
    assert [row["apparent_bytes"] for row in spike.state_at(candidate, 2, True)] == [200]
    assert [tuple(row) for row in spike.state_at(candidate, 2, True)] == [
        tuple(row) for row in spike.state_at(source, 2, False)
    ]


def test_deleted_version_closes_at_deletion_and_reappearance_opens_new(repo_root: Path) -> None:
    aggregate = _state(100, 128)
    spike, _source, candidate = _build(repo_root, {1: {7: aggregate}, 2: {}, 3: {7: aggregate}})

    assert _interval_bounds(candidate, 7) == [(1, 2), (3, None)]
    assert spike.state_at(candidate, 1, True)
    assert spike.state_at(candidate, 2, True) == []
    assert spike.state_at(candidate, 3, True)


def test_as_of_and_two_snapshot_diff_match_full_snapshot_reference(repo_root: Path) -> None:
    snapshots = {
        1: {7: _state(10, 16), 8: _state(20, 32)},
        2: {7: _state(10, 16), 9: _state(30, 32, file_count=3)},
    }
    spike, source, candidate = _build(repo_root, snapshots)

    for snapshot_id in snapshots:
        assert [tuple(row) for row in spike.state_at(candidate, snapshot_id, True)] == [
            tuple(row) for row in spike.state_at(source, snapshot_id, False)
        ]
    assert spike.diff_rows(spike.state_at(candidate, 1, True), spike.state_at(candidate, 2, True)) == spike.diff_rows(
        spike.state_at(source, 1, False), spike.state_at(source, 2, False)
    )
