from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def run_module(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["WATCHDIRS_REPO_ROOT"] = str(repo_root)
    src_path = str(repo_root / "src")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"
    return subprocess.run(
        ["python3", "-m", "watchdirs", *args],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, f"expected JSON on stdout, got stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    return db_path, connection, migrations_module, models_module


def _directory_row(models_module, snapshot_id: int, path: bytes, *, disk_bytes: int, apparent_bytes: int, depth: int,
                   parent_path: bytes | None, file_count: int = 0, dir_count: int = 0, error: str | None = None):
    stripped = path.rstrip(b"/")
    name = b"/" if stripped == b"" else stripped.split(b"/")[-1]
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=parent_path,
        name=name,
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
    )


def _mount(
    models_module,
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: bytes,
    mount_point: bytes,
    filesystem_type: str,
    mount_source: str,
):
    return models_module.MountInfo(
        mount_id=mount_id,
        parent_id=parent_id,
        major_minor=major_minor,
        root=root,
        mount_point=mount_point,
        options=("rw",),
        filesystem_type=filesystem_type,
        mount_source=mount_source,
        super_options=("rw",),
    )


def _seed_snapshot(
    connection,
    migrations_module,
    models_module,
    *,
    root_path: Path,
    status: str,
    started_at: str,
    finished_at: str,
    rows: list[object],
    mounts: list[object] | None = None,
    notes: str | None = None,
    error: str | None = None,
) -> int:
    snapshot = migrations_module.create_snapshot(connection, root_path, notes=notes)
    persisted_rows = [
        models_module.DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=row.path,
            parent_path=row.parent_path,
            name=row.name,
            depth=row.depth,
            apparent_bytes=row.apparent_bytes,
            disk_bytes=row.disk_bytes,
            file_count=row.file_count,
            dir_count=row.dir_count,
            error=row.error,
        )
        for row in rows
    ]
    if persisted_rows:
        migrations_module.insert_directory_rows(connection, persisted_rows, commit=False)
    if mounts:
        migrations_module.insert_snapshot_mounts(connection, snapshot.id, mounts, commit=False)
    migrations_module.finalize_snapshot(
        connection,
        snapshot.id,
        status=models_module.SnapshotStatus(status),
        notes=notes,
        error=error,
        commit=False,
    )
    connection.execute(
        "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
        (started_at, finished_at, snapshot.id),
    )
    connection.commit()
    return snapshot.id


def _section_by_root(payload: dict[str, object], root_path: str) -> dict[str, object]:
    sections = payload["sections"]
    assert isinstance(sections, list)
    return next(section for section in sections if section["snapshot"]["root_path"] == root_path)


def test_top_json_envelope_and_top_level_subtree_grouping(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=900,
                apparent_bytes=700,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/log",
                disk_bytes=600,
                apparent_bytes=590,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "2",
        "--group-by",
        "top-level-subtree",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "top"
    assert payload["snapshot_selector"] == "latest"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert payload["group_by"] == "top-level-subtree"
    assert payload["warnings"] == []
    assert len(payload["sections"]) == 1

    section = payload["sections"][0]
    assert section["snapshot"]["id"] == snapshot_id
    assert section["snapshot"]["root_path"] == "/srv"
    assert section["snapshot"]["status"] == "complete"
    assert section["snapshot"]["started_at"] == "2026-06-13T18:20:00Z"
    assert section["snapshot"]["finished_at"] == "2026-06-13T18:21:00Z"
    assert section["warnings"] == []
    assert [row["path"] for row in section["rows"]] == ["/srv", "/srv/cache"]
    assert section["rows"][0]["path_bytes_hex"] == b"/srv".hex()
    assert section["rows"][0]["current_disk_bytes"] == 1500
    assert section["rows"][0]["current_apparent_bytes"] == 1200
    assert section["rows"][0]["group"] == {"kind": "top-level-subtree", "key": "."}
    assert section["rows"][1]["group"] == {"kind": "top-level-subtree", "key": "cache"}


def test_top_text_output_is_terse_and_labels_snapshot_status_and_current_sizes(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:22:00Z",
        finished_at="2026-06-13T18:23:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=900,
                apparent_bytes=700,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
        error="permission denied",
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "2",
    )

    assert result.returncode == 0, result.stderr
    assert "snapshot=" in result.stdout
    assert "status=partial" in result.stdout
    assert "current_disk_bytes=" in result.stdout
    assert "current_apparent_bytes=" in result.stdout
    assert "permission denied" in result.stdout
    assert "rows:" not in result.stdout
    assert "children:" not in result.stdout


def test_top_latest_returns_latest_usable_snapshot_per_root_with_partial_warnings(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=1000, apparent_bytes=900, depth=0, parent_path=None)],
    )
    failed_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T18:05:00Z",
        finished_at="2026-06-13T18:06:00Z",
        rows=[],
        error="scan crashed",
    )
    partial_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=1200, apparent_bytes=950, depth=0, parent_path=None)],
        error="permission denied",
    )
    latest_var = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T18:12:00Z",
        finished_at="2026-06-13T18:13:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=600, apparent_bytes=600, depth=0, parent_path=None)],
    )

    result = run_module(repo_root, "top", "--db", str(db_path), "--snapshot", "latest", "--json")

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert len(payload["sections"]) == 2
    assert failed_id not in [section["snapshot"]["id"] for section in payload["sections"]]

    srv_section = _section_by_root(payload, "/srv")
    var_section = _section_by_root(payload, "/var")
    assert srv_section["snapshot"]["id"] == partial_id
    assert srv_section["snapshot"]["status"] == "partial"
    assert srv_section["snapshot"]["error"] == "permission denied"
    assert srv_section["warnings"]
    assert "partial" in srv_section["warnings"][0]["message"].lower()
    assert var_section["snapshot"]["id"] == latest_var
    assert var_section["snapshot"]["status"] == "complete"
    assert var_section["warnings"] == []


def test_top_numeric_snapshot_selector_returns_exact_snapshot_section(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    requested_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:30:00Z",
        finished_at="2026-06-13T18:31:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=500, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:32:00Z",
        finished_at="2026-06-13T18:33:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=900, apparent_bytes=800, depth=0, parent_path=None)],
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        str(requested_id),
        "--limit",
        "5",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert len(payload["sections"]) == 1
    assert payload["sections"][0]["snapshot"]["id"] == requested_id
    assert payload["sections"][0]["snapshot"]["root_path"] == "/srv"


@pytest.mark.parametrize(
    ("snapshot_selector", "limit_value", "seed_mode", "error_code"),
    [
        ("abc", "2", "usable", "invalid_snapshot_id"),
        ("999", "2", "usable", "snapshot_not_found"),
        ("latest", "2", "failed-only", "no_usable_snapshots"),
        ("latest", "0", "usable", "invalid_limit"),
        ("latest", "-1", "usable", "invalid_limit"),
        ("latest", "banana", "usable", "invalid_limit"),
        ("latest", "1001", "usable", "limit_too_large"),
    ],
)
def test_top_json_errors_for_invalid_snapshot_selectors_and_limits(
    repo_root: Path,
    tmp_path: Path,
    snapshot_selector: str,
    limit_value: str,
    seed_mode: str,
    error_code: str,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    if seed_mode == "usable":
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:40:00Z",
            finished_at="2026-06-13T18:41:00Z",
            rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=500, depth=0, parent_path=None)],
        )
    else:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="failed",
            started_at="2026-06-13T18:42:00Z",
            finished_at="2026-06-13T18:43:00Z",
            rows=[],
            error="scan crashed",
        )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        snapshot_selector,
        "--limit",
        limit_value,
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 1, result.stderr
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code
    assert payload["error"]["message"]


def test_top_storage_domain_grouping_and_unknown_mount_contract(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:50:00Z",
        finished_at="2026-06-13T18:51:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/archive",
                disk_bytes=900,
                apparent_bytes=800,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=800,
                apparent_bytes=790,
                depth=1,
                parent_path=b"/",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/srv/archive",
                filesystem_type="xfs",
                mount_source="/dev/archive",
            ),
        ],
        error="permission denied",
    )

    mount_result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "5",
        "--group-by",
        "mount",
        "--json",
    )
    domain_result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "5",
        "--group-by",
        "storage-domain",
        "--json",
    )

    mount_payload = parse_json_output(mount_result)
    domain_payload = parse_json_output(domain_result)
    mount_rows = mount_payload["sections"][0]["rows"]
    domain_rows = domain_payload["sections"][0]["rows"]
    archive_mount = next(row for row in mount_rows if row["path"] == "/srv/archive")
    archive_domain = next(row for row in domain_rows if row["path"] == "/srv/archive")
    mystery_mount = next(row for row in mount_rows if row["path"] == "/mystery")
    mystery_domain = next(row for row in domain_rows if row["path"] == "/mystery")

    assert archive_mount["group"] == {
        "kind": "mount",
        "key": "/srv/archive",
        "mount_point": "/srv/archive",
    }
    assert archive_domain["group"] == {
        "kind": "storage-domain",
        "key": "8:17|/|xfs|/dev/archive",
        "mount_point": "/srv/archive",
        "filesystem_type": "xfs",
        "mount_source": "/dev/archive",
        "major_minor": "8:17",
        "root": "/",
    }
    assert mystery_mount["group"] is None
    assert mystery_domain["group"] is None
    mount_warning_codes = [warning["code"] for warning in mount_payload["sections"][0]["warnings"]]
    domain_warning_codes = [warning["code"] for warning in domain_payload["sections"][0]["warnings"]]
    assert "unknown_mount" in mount_warning_codes
    assert "unknown_mount" in domain_warning_codes


def test_diff_json_returns_global_growth_frontier_pair_metadata_and_warnings(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/srv/cache", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/log", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T16:00:00Z",
        finished_at="2026-06-13T16:01:00Z",
        rows=[],
        error="scan crashed",
    )
    srv_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/srv/cache", disk_bytes=116, apparent_bytes=110, depth=1, parent_path=b"/srv"),
            _directory_row(models_module, 1, b"/srv/log", disk_bytes=15, apparent_bytes=15, depth=1, parent_path=b"/srv"),
        ],
        error="permission denied",
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-12T17:00:00Z",
        finished_at="2026-06-12T17:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/var", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var/tmp", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/var"),
        ],
    )
    var_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T20:00:00Z",
        finished_at="2026-06-13T20:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/var", disk_bytes=220, apparent_bytes=200, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var/tmp", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/var"),
        ],
    )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "2",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "diff"
    assert payload["since"] == "24h"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert payload["group_by"] == "root"
    assert len(payload["pairs"]) == 2
    assert {pair["root_path"] for pair in payload["pairs"]} == {"/srv", "/var"}
    srv_pair = next(pair for pair in payload["pairs"] if pair["root_path"] == "/srv")
    assert srv_pair["current"]["id"] == srv_current
    assert srv_pair["current"]["status"] == "partial"
    assert "partial_snapshot" in srv_pair["warning_codes"]
    assert [row["path"] for row in payload["rows"]] == ["/var", "/srv/cache"]
    assert payload["rows"][0]["disk_bytes_delta"] == 120
    assert payload["rows"][1]["disk_bytes_delta"] == 96
    assert payload["rows"][1]["suppressed_ancestor_count"] == 1
    assert payload["rows"][1]["snapshot_pair"] == {"baseline_id": srv_pair["baseline"]["id"], "current_id": srv_current}
    assert payload["classification_counts"]["grown"] >= 3
    warning_codes = {warning["code"] for warning in payload["warnings"]}
    assert {"failed_snapshot_excluded", "partial_snapshot"} <= warning_codes
    assert all("group" in row for row in payload["rows"])
    assert var_current in [pair["current"]["id"] for pair in payload["pairs"]]


def test_diff_json_top_level_subtree_grouping_uses_root_label_and_first_segment(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/"),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var", disk_bytes=120, apparent_bytes=120, depth=1, parent_path=b"/"),
            _directory_row(models_module, 1, b"/var/log", disk_bytes=118, apparent_bytes=118, depth=2, parent_path=b"/var"),
        ],
    )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "2",
        "--group-by",
        "top-level-subtree",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["group_by"] == "top-level-subtree"
    assert payload["rows"][0]["group"] == {"kind": "top-level-subtree", "key": "var"}
    assert any(row["group"] == {"kind": "top-level-subtree", "key": "."} for row in payload["rows"])


@pytest.mark.parametrize(
    ("since_value", "limit_value", "seed_snapshots", "error_code"),
    [
        ("24 h", "2", True, "invalid_since"),
        ("1h30m", "2", True, "invalid_since"),
        ("24h", "0", True, "invalid_limit"),
        ("24h", "1001", True, "limit_too_large"),
        ("24h", "2", False, "no_snapshot_pairs"),
    ],
)
def test_diff_json_errors_for_invalid_since_limit_and_missing_pairs(
    repo_root: Path,
    tmp_path: Path,
    since_value: str,
    limit_value: str,
    seed_snapshots: bool,
    error_code: str,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    if seed_snapshots:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-12T18:00:00Z",
            finished_at="2026-06-12T18:00:00Z",
            rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
        )
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=200, depth=0, parent_path=None)],
        )
    else:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=200, depth=0, parent_path=None)],
        )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        since_value,
        "--limit",
        limit_value,
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 1, result.stderr
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code
    assert payload["error"]["message"]
