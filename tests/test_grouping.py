# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import JsonDict


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def run_module(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    command_env["PYTHONDONTWRITEBYTECODE"] = "1"
    command_env["WATCHDIRS_REPO_ROOT"] = str(repo_root)
    src_path = str(repo_root / "src")
    existing_pythonpath = command_env.get("PYTHONPATH")
    command_env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"
    if env:
        command_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "watchdirs", *args],
        cwd=repo_root,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )


def create_sample_tree(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "nested" / "beta.txt").write_text("beta-data", encoding="utf-8")


def _mountinfo_line(
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: bytes | str | Path,
    mount_point: bytes | str | Path,
    filesystem_type: str,
    mount_source: str,
) -> str:
    def _text(value: bytes | str | Path) -> str:
        if isinstance(value, bytes):
            value = os.fsdecode(value)
        elif isinstance(value, Path):
            value = str(value)
        return value.replace("\\", "\\134").replace(" ", "\\040").replace("\n", "\\012").replace("\t", "\\011")

    return (
        f"{mount_id} {parent_id} {major_minor} {_text(root)} {_text(mount_point)} rw - "
        f"{filesystem_type} {mount_source} rw"
    )


def _write_mountinfo(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _fetch_rows(db_path: Path, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return list(connection.execute(sql, params))
    finally:
        connection.close()


def _parse_snapshot_payload(result) -> JsonDict:
    assert result.stdout, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_initialize_database_creates_snapshot_mounts_with_blob_paths(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)

    columns = {row["name"]: row["type"] for row in connection.execute("PRAGMA table_info('snapshot_mounts')")}
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert columns["root"] == "BLOB"
    assert columns["mount_point"] == "BLOB"
    assert user_version == migrations_module.SCHEMA_VERSION


def test_insert_snapshot_mounts_round_trips_required_rept07_fields(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    snapshot = migrations_module.create_snapshot(connection, tmp_path / "root")

    mounts = (
        models_module.MountInfo(
            mount_id=17,
            parent_id=9,
            major_minor="8:1",
            root=b"/",
            mount_point=b"/root",
            options=("rw",),
            filesystem_type="ext4",
            mount_source="/dev/nvme0n1p1",
            super_options=("rw",),
        ),
    )

    migrations_module.insert_snapshot_mounts(connection, snapshot.id, mounts)
    persisted = migrations_module.load_snapshot_mounts(connection, snapshot.id)

    assert len(persisted) == 1
    mount = persisted[0]
    assert isinstance(mount, models_module.SnapshotMount)
    assert mount.snapshot_id == snapshot.id
    assert mount.mount_id == 17
    assert mount.parent_id == 9
    assert mount.major_minor == "8:1"
    assert mount.root == b"/"
    assert mount.mount_point == b"/root"
    assert mount.filesystem_type == "ext4"
    assert mount.mount_source == "/dev/nvme0n1p1"
    assert isinstance(mount.root, bytes)
    assert isinstance(mount.mount_point, bytes)


def test_collect_persists_mount_rows_for_created_snapshot(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    db_path = tmp_path / "watchdirs.sqlite3"
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    mountinfo_path = _write_mountinfo(
        tmp_path / "mountinfo.txt",
        _mountinfo_line(
            mount_id=41,
            parent_id=24,
            major_minor="8:1",
            root="/",
            mount_point=root,
            filesystem_type="ext4",
            mount_source="/dev/root",
        ),
    )

    result = run_module(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
        "--mountinfo",
        str(mountinfo_path),
    )

    payload = _parse_snapshot_payload(result)
    snapshot_id = payload["snapshots"][0]["id"]
    mount_rows = _fetch_rows(
        db_path,
        """
        SELECT snapshot_id, mount_id, major_minor, root, mount_point, filesystem_type, mount_source
        FROM snapshot_mounts
        WHERE snapshot_id = ?
        """,
        (snapshot_id,),
    )

    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert len(mount_rows) == 1
    assert mount_rows[0]["snapshot_id"] == snapshot_id
    assert mount_rows[0]["mount_id"] == 41
    assert mount_rows[0]["root"] == b"/"
    assert mount_rows[0]["mount_point"] == os.fsencode(root)


def test_reused_mount_id_does_not_collapse_storage_domain_identity(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    first = migrations_module.create_snapshot(connection, tmp_path / "first")
    second = migrations_module.create_snapshot(connection, tmp_path / "second")

    shared_mount_id = 55
    migrations_module.insert_snapshot_mounts(
        connection,
        first.id,
        (
            models_module.MountInfo(
                mount_id=shared_mount_id,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/",
                options=("rw",),
                filesystem_type="ext4",
                mount_source="/dev/nvme0n1p1",
                super_options=("rw",),
            ),
        ),
    )
    migrations_module.insert_snapshot_mounts(
        connection,
        second.id,
        (
            models_module.MountInfo(
                mount_id=shared_mount_id,
                parent_id=1,
                major_minor="8:2",
                root=b"/data",
                mount_point=b"/mnt/data",
                options=("rw",),
                filesystem_type="xfs",
                mount_source="/dev/nvme1n1p1",
                super_options=("rw",),
            ),
        ),
    )

    first_mount = migrations_module.load_snapshot_mounts(connection, first.id)[0]
    second_mount = migrations_module.load_snapshot_mounts(connection, second.id)[0]

    assert first_mount.mount_id == second_mount.mount_id == shared_mount_id
    assert (
        first_mount.major_minor,
        first_mount.root,
        first_mount.filesystem_type,
        first_mount.mount_source,
    ) != (
        second_mount.major_minor,
        second_mount.root,
        second_mount.filesystem_type,
        second_mount.mount_source,
    )
    assert first_mount.mount_point == b"/"
    assert second_mount.mount_point == b"/mnt/data"


def test_initialize_database_is_idempotent_and_rolls_back_on_schema_failure(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)

    assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'snapshot_mounts'").fetchone()[0] == 1
    assert connection.execute("PRAGMA user_version").fetchone()[0] == migrations_module.SCHEMA_VERSION

    # Re-running on an already-current DB is a no-op (idempotent).
    migrations_module.initialize_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == migrations_module.SCHEMA_VERSION

    failed_connection = connection_module.open_connection(tmp_path / "failed.sqlite3")

    class FailingSchemaConnection:
        def __init__(self, delegate: sqlite3.Connection) -> None:
            self.delegate = delegate

        def execute(self, sql: str, params: tuple[object, ...] = ()):
            return self.delegate.execute(sql, params)

        def executescript(self, _script: str):
            raise sqlite3.OperationalError("schema explosion")

        def commit(self) -> None:
            self.delegate.commit()

        def rollback(self) -> None:
            self.delegate.rollback()

    with pytest.raises(sqlite3.OperationalError, match="schema explosion"):
        migrations_module.initialize_database(FailingSchemaConnection(failed_connection))

    assert failed_connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert (
        failed_connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'snapshot_mounts'").fetchone()[0]
        == 0
    )


def test_deleting_snapshot_cascades_snapshot_mount_rows(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations_module.initialize_database(connection)
    snapshot = migrations_module.create_snapshot(connection, tmp_path / "root")
    migrations_module.insert_snapshot_mounts(
        connection,
        snapshot.id,
        (
            models_module.MountInfo(
                mount_id=5,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/root",
                options=("rw",),
                filesystem_type="ext4",
                mount_source="/dev/root",
                super_options=("rw",),
            ),
        ),
    )

    assert connection.execute("SELECT COUNT(*) FROM snapshot_mounts").fetchone()[0] == 1

    connection.execute("DELETE FROM snapshots WHERE id = ?", (snapshot.id,))
    connection.commit()

    assert connection.execute("SELECT COUNT(*) FROM snapshot_mounts").fetchone()[0] == 0


def test_collect_rolls_back_directory_rows_when_mount_persistence_fails(
    repo_root: Path, write_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    root = tmp_path / "root"
    create_sample_tree(root)
    db_path = tmp_path / "watchdirs.sqlite3"
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    mountinfo_path = _write_mountinfo(
        tmp_path / "mountinfo.txt",
        _mountinfo_line(
            mount_id=41,
            parent_id=24,
            major_minor="8:1",
            root="/",
            mount_point=root,
            filesystem_type="ext4",
            mount_source="/dev/root",
        ),
    )

    def fail_mount_insert(connection, snapshot_id, mounts, *, commit=True):
        raise RuntimeError(f"forced mount insert failure for {snapshot_id} ({len(mounts)})")

    monkeypatch.setattr(cli_module, "insert_snapshot_mounts", fail_mount_insert)

    result = cli_module.main([
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
        "--mountinfo",
        str(mountinfo_path),
    ])

    snapshots = _fetch_rows(db_path, "SELECT id, status, error FROM snapshots ORDER BY id")
    directory_rows = _fetch_rows(db_path, "SELECT * FROM directory_sizes")
    mount_rows = _fetch_rows(db_path, "SELECT * FROM snapshot_mounts")

    assert result == 1
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert "forced mount insert failure" in snapshots[0]["error"]
    assert directory_rows == []
    assert mount_rows == []
    assert _fetch_rows(db_path, "SELECT * FROM snapshots WHERE status = 'complete'") == []
