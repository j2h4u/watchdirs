import sqlite3
from pathlib import Path
from typing import cast

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import create_snapshot, finalize_snapshot, initialize_database, insert_directory_rows
from watchdirs.models import DirectoryAggregate, SnapshotStatus
from watchdirs.reporting.path_history import _history_observations


def test_history_filters_paths_before_expanding_intervals(tmp_path: Path) -> None:
    connection = open_connection(tmp_path / "history.sqlite3")
    try:
        initialize_database(connection)
        snapshot_ids = []
        for status in (SnapshotStatus.COMPLETE, SnapshotStatus.COMPLETE, SnapshotStatus.PARTIAL):
            snapshot = create_snapshot(connection, Path("/root"))
            insert_directory_rows(
                connection,
                [
                    DirectoryAggregate(snapshot.id, path, None, 0, 10, 10, 1, 0, None)
                    for path in (b"/root/wanted", b"/root/unrelated")
                ],
            )
            finalize_snapshot(connection, snapshot.id, status=status)
            snapshot_ids.append(snapshot.id)
        traced = []
        connection.set_trace_callback(traced.append)
        observations = _history_observations(connection, b"/root/wanted", b"/root/wanted")
        connection.set_trace_callback(None)
        assert [snapshot.id for snapshot, _ in observations] == snapshot_ids
        assert all(path == b"/root/wanted" for _, path in observations)
        plan = cast(list[sqlite3.Row], connection.execute("EXPLAIN QUERY PLAN " + traced[-1]).fetchall())
        details = [cast(str, row[3]) for row in plan]
        assert any(
            "SEARCH i USING INDEX directory_size_intervals_path_id_idx (path_id=?)" in detail for detail in details
        )
        assert any(
            "SEARCH d USING INDEX directory_size_diagnostics_path_id_idx (path_id=?)" in detail for detail in details
        )
        assert not any(detail.startswith(("SCAN i", "SCAN d")) for detail in details)
    finally:
        connection.close()
