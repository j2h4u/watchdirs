"""Wave-0 RED test pinning churn/cardinality SQL to RESEARCH-verified counts.

Runs against the CURRENT blob ``directory_sizes`` schema (path/parent_path/name
BLOBs), before the Plan 02 dictionary rewrite. The churn measurement reads the
``path`` column directly, never ``path_id``.
"""

from __future__ import annotations

from pathlib import Path
import sys


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    return connection, migrations_module, models_module


def _directory_row(models_module, snapshot_id: int, path: bytes, *, depth: int = 1):
    stripped = path.rstrip(b"/")
    name = b"/" if stripped == b"" else stripped.split(b"/")[-1]
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=b"/root",
        name=name,
        depth=depth,
        apparent_bytes=0,
        disk_bytes=0,
        file_count=0,
        dir_count=0,
        error=None,
    )


def _seed_snapshot(connection, migrations_module, models_module, paths: list[bytes]) -> int:
    snapshot = migrations_module.create_snapshot(connection, Path("/root"))
    rows = [_directory_row(models_module, snapshot.id, path) for path in paths]
    migrations_module.insert_directory_rows(connection, rows)
    return snapshot.id


def test_churn_and_cardinality_5pct(repo_root: Path, tmp_path: Path) -> None:
    """Two consecutive 1000-row snapshots, 5% churn (50 new + 50 deleted).

    Mirrors RESEARCH ## Code Examples verified example:
    rows_prev=1000 rows_curr=1000 new=50 deleted=50 distinct=1050 total=2000
    churn_rate=0.050 dedup_ratio=1.90x.
    """
    churn = import_module(repo_root, "watchdirs.bench.churn")
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)

    # Snapshot 1: paths 0..999.
    prev_paths = [b"/root/d%04d" % i for i in range(1000)]
    # Snapshot 2: drop the first 50, add 50 fresh ones (1000..1049) -> 5% churn.
    curr_paths = [b"/root/d%04d" % i for i in range(50, 1050)]

    prev_id = _seed_snapshot(connection, migrations_module, models_module, prev_paths)
    curr_id = _seed_snapshot(connection, migrations_module, models_module, curr_paths)

    result = churn.measure_churn(connection, prev_id, curr_id)
    assert result.rows_prev == 1000
    assert result.rows_curr == 1000
    assert result.new_paths == 50
    assert result.deleted_paths == 50
    assert abs(result.churn_rate - 0.050) < 1e-9

    card = churn.measure_cardinality(connection)
    assert card.distinct_paths == 1050
    assert card.total_rows == 2000
    assert abs(card.dedup_ratio - 1.90) < 1e-9


def test_cardinality_single_snapshot_no_duplication(repo_root: Path, tmp_path: Path) -> None:
    """A single-snapshot DB has no cross-snapshot duplication: dedup_ratio == 1.0."""
    churn = import_module(repo_root, "watchdirs.bench.churn")
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)

    paths = [b"/root/d%04d" % i for i in range(100)]
    _seed_snapshot(connection, migrations_module, models_module, paths)

    card = churn.measure_cardinality(connection)
    assert card.distinct_paths == 100
    assert card.total_rows == 100
    assert card.dedup_ratio == 1.0


def test_churn_zero_overlap_all_new(repo_root: Path, tmp_path: Path) -> None:
    """Disjoint snapshot pair: new_paths == rows_curr and deleted_paths == rows_prev."""
    churn = import_module(repo_root, "watchdirs.bench.churn")
    connection, migrations_module, models_module = _open_db(repo_root, tmp_path)

    prev_paths = [b"/root/a%03d" % i for i in range(40)]
    curr_paths = [b"/root/b%03d" % i for i in range(60)]

    prev_id = _seed_snapshot(connection, migrations_module, models_module, prev_paths)
    curr_id = _seed_snapshot(connection, migrations_module, models_module, curr_paths)

    result = churn.measure_churn(connection, prev_id, curr_id)
    assert result.rows_prev == 40
    assert result.rows_curr == 60
    assert result.new_paths == 60
    assert result.deleted_paths == 40
    assert result.new_paths == result.rows_curr
    assert result.deleted_paths == result.rows_prev
