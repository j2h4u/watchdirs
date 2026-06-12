from __future__ import annotations

import importlib
import json
import os
import signal
import shlex
import sqlite3
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest


REQUIRED_FLAGS = ("--config", "--db", "--json", "--notes", "--mountinfo")


def run_repo_local(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command = shlex.join(["./watchdirs", *args])
    return subprocess.run(
        ["bash", "-lc", command],
        cwd=repo_root,
        env=_command_env(repo_root, env),
        text=True,
        capture_output=True,
        check=False,
    )


def run_module(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = _command_env(repo_root, env)
    src_path = str(repo_root / "src")
    existing_pythonpath = command_env.get("PYTHONPATH")
    command_env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"
    return subprocess.run(
        ["python3", "-m", "watchdirs", *args],
        cwd=repo_root,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_config_error(result: subprocess.CompletedProcess[str], expected_kind: str) -> dict[str, object]:
    assert result.returncode != 0, result
    payload = parse_json_output(result)
    assert payload["ok"] is False
    assert set(payload) == {"error", "ok"}

    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == "config_error"
    assert error["kind"] == expected_kind
    assert isinstance(error["message"], str)
    assert error["message"]
    return payload


def import_config_module(repo_root: Path):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return importlib.import_module("watchdirs.config")


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return importlib.import_module(module_name)


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stdout, f"expected JSON on stdout, got stderr={result.stderr!r}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            "stdout was not valid JSON\n"
            f"returncode={result.returncode}\n"
            f"stdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}\n"
            f"error={exc}"
        )
    assert isinstance(payload, dict)
    return payload


def _command_env(repo_root: Path, extra_env: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["WATCHDIRS_REPO_ROOT"] = str(repo_root)
    if extra_env:
        env.update(extra_env)
    return env


def create_sample_tree(root: Path) -> None:
    (root / "nested").mkdir(parents=True)
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "nested" / "beta.txt").write_text("beta-data", encoding="utf-8")


def escape_mountinfo_path(path: Path | str) -> str:
    value = str(path)
    return (
        value.replace("\\", "\\134")
        .replace(" ", "\\040")
        .replace("\n", "\\012")
        .replace("\t", "\\011")
    )


def fetch_snapshot_rows(db_path: Path) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        snapshots = list(connection.execute("SELECT * FROM snapshots ORDER BY id"))
        directory_rows = list(connection.execute("SELECT * FROM directory_sizes ORDER BY id"))
    finally:
        connection.close()
    return snapshots, directory_rows


def test_repo_local_collect_help_matches_module_help(repo_root: Path) -> None:
    repo_local = run_repo_local(repo_root, "collect", "--help")
    module = run_module(repo_root, "collect", "--help")

    assert repo_local.returncode == 0, repo_local.stderr
    assert module.returncode == 0, module.stderr
    for flag in REQUIRED_FLAGS:
        assert flag in repo_local.stdout
        assert flag in module.stdout


def test_collect_requires_configured_roots_json(repo_root: Path, write_config) -> None:
    config_path = write_config(raw="exclude_paths = [\"/tmp\"]\n")

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "no_roots")
    assert payload["error"]["path"] == str(config_path)


def test_collect_reports_missing_config_json(repo_root: Path, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.toml"

    result = run_module(repo_root, "collect", "--config", str(missing_path), "--json")

    payload = assert_config_error(result, "missing_config")
    assert payload["error"]["path"] == str(missing_path)


def test_collect_reports_malformed_toml_json(repo_root: Path, write_config) -> None:
    config_path = write_config(raw="[[roots]\npath = \"/\"\n")

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "malformed_config")
    assert payload["error"]["path"] == str(config_path)


def test_collect_reports_unreadable_config_json(repo_root: Path, write_config) -> None:
    config_path = write_config(raw="[[roots]]\npath = \"/\"\n")
    config_path.chmod(0)
    try:
        if os.geteuid() == 0 or os.access(config_path, os.R_OK):
            pytest.skip("platform/user can still read chmod 000 files")

        result = run_module(repo_root, "collect", "--config", str(config_path), "--json")
    finally:
        config_path.chmod(0o600)

    payload = assert_config_error(result, "unreadable_config")
    assert payload["error"]["path"] == str(config_path)


def test_collect_rejects_nonexistent_root_json(repo_root: Path, write_config, tmp_path: Path) -> None:
    config_path = write_config(roots=[tmp_path / "missing-root"])

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "missing_root")
    assert payload["error"]["path"] == str(tmp_path / "missing-root")


def test_collect_rejects_file_root_json(repo_root: Path, write_config, tmp_path: Path) -> None:
    file_root = tmp_path / "not-a-directory"
    file_root.write_text("x", encoding="utf-8")
    config_path = write_config(roots=[file_root])

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "file_root")
    assert payload["error"]["path"] == str(file_root)


def test_collect_rejects_overlapping_roots_json(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    config_path = write_config(roots=[root, child])

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "overlapping_roots")
    assert payload["error"]["path"] == str(child)


def test_user_db_default_uses_xdg_state(repo_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_module = import_config_module(repo_root)
    state_home = tmp_path / "state-home"
    cache_home = tmp_path / "cache-home"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))

    db_path = config_module.default_db_path()

    assert db_path == state_home / "watchdirs" / "watchdirs.sqlite3"
    assert str(cache_home) not in str(db_path)
    assert "/var/tmp" not in str(db_path)


def test_user_db_default_falls_back_to_dot_local_state(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_module = import_config_module(repo_root)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(home))

    db_path = config_module.default_db_path()

    assert db_path == home / ".local" / "state" / "watchdirs" / "watchdirs.sqlite3"


def test_sample_config_uses_explicit_root_policy(sample_config_path: Path) -> None:
    payload = tomllib.loads(sample_config_path.read_text(encoding="utf-8"))
    roots = [entry["path"] for entry in payload["roots"]]

    assert "/" in roots
    assert "/tmp" not in roots
    assert "/dev/shm" not in roots


def test_config_loads_exclude_paths(repo_root: Path, write_config, tmp_path: Path) -> None:
    config_module = import_config_module(repo_root)
    root = tmp_path / "root"
    root.mkdir()
    excluded = tmp_path / "root" / "skip-me"
    config_path = write_config(roots=[root], exclude_paths=[excluded])

    config = config_module.load_config(config_path)

    assert config.exclude_paths == (excluded.resolve(),)


def test_repo_local_collect_creates_snapshot(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    result = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
        "--notes",
        "repo-local test",
    )

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["ok"] is True
    assert payload["command"] == "collect"

    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert len(snapshots) == 1
    assert snapshots[0]["root_path"] == str(root)
    assert snapshots[0]["notes"] == "repo-local test"
    assert snapshots[0]["status"] == "complete"
    assert snapshots[0]["finished_at"] is not None
    assert len(directory_rows) >= 1


def test_module_collect_creates_snapshot(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    result = run_module(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["ok"] is True

    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert len(snapshots) == 1
    assert snapshots[0]["root_path"] == str(root)
    assert len(directory_rows) >= 1


def test_collect_accepts_mountinfo_override(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root])
    db_path = tmp_path / "watchdirs.sqlite3"
    mountinfo_path = tmp_path / "mountinfo.txt"
    mountinfo_path.write_text(
        (
            "41 24 0:41 / "
            f"{escape_mountinfo_path(root)} "
            "rw,nosuid,nodev - tmpfs tmpfs rw,size=1024k\n"
        ),
        encoding="utf-8",
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

    payload = parse_json_output(result)
    snapshots, directory_rows = fetch_snapshot_rows(db_path)

    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["mountinfo"] == str(mountinfo_path)
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert snapshots[0]["error"] is not None
    assert "tmpfs" in snapshots[0]["error"]
    assert directory_rows == []


def test_collect_json_row_count_matches_inserted_rows(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    result = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    snapshot_payload = payload["snapshots"][0]
    snapshots, directory_rows = fetch_snapshot_rows(db_path)

    assert len(snapshots) == 1
    assert snapshot_payload["row_count"] == len(directory_rows)


def test_failed_snapshot_records_fatal_error(
    repo_root: Path, write_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root])
    db_path = tmp_path / "watchdirs.sqlite3"

    def blow_up(_root_path):
        raise RuntimeError("fatal scan failure")

    monkeypatch.setattr(cli_module, "scan_root", blow_up)

    result = cli_module.main(
        [
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        ]
    )

    assert result == 1
    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert directory_rows == []
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert snapshots[0]["error"] == "fatal scan failure"
    assert snapshots[0]["finished_at"] is not None


def test_partial_snapshot_returns_nonzero_and_not_ok(
    repo_root: Path, write_config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    models = import_module(repo_root, "watchdirs.models")
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    def partial_scan(options):
        return models.ScanResult(
            root_path=options.root,
            rows=(
                models.DirectoryAggregate(
                    snapshot_id=0,
                    path=os.fsencode(options.root),
                    parent_path=None,
                    name=Path(options.root).name.encode(),
                    depth=0,
                    apparent_bytes=0,
                    disk_bytes=0,
                    file_count=0,
                    dir_count=0,
                    error="partial test error",
                ),
            ),
            row_count=1,
            status=models.SnapshotStatus.PARTIAL,
            fatal_error=None,
            errors=(),
            hardlink_count=0,
        )

    monkeypatch.setattr(cli_module, "scan_root", partial_scan)

    result = cli_module.main(
        [
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    snapshots, directory_rows = fetch_snapshot_rows(db_path)

    assert result == 1
    assert payload["ok"] is False
    assert payload["snapshots"][0]["status"] == "partial"
    assert snapshots[0]["status"] == "partial"
    assert len(directory_rows) == 1


def test_collect_reports_database_open_error_json(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("not a dir", encoding="utf-8")
    db_path = parent_file / "watchdirs.sqlite3"

    result = run_module(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "database_error"
    assert payload["error"]["db_path"] == str(db_path)
    assert "Traceback" not in result.stderr


def test_collect_reports_database_initialization_error_json(
    repo_root: Path,
    write_config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    def fail_initialize(_connection):
        raise sqlite3.OperationalError("schema init failed")

    monkeypatch.setattr(cli_module, "initialize_database", fail_initialize)

    result = cli_module.main(
        [
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "database_error"
    assert payload["error"]["db_path"] == str(db_path)
    assert "schema init failed" in payload["error"]["message"]
    assert "Traceback" not in captured.err


def test_collect_reports_snapshot_creation_error_json(
    repo_root: Path,
    write_config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    def fail_create_snapshot(_connection, _root_path, *, notes=None):
        raise sqlite3.OperationalError("snapshot insert failed")

    monkeypatch.setattr(cli_module, "create_snapshot", fail_create_snapshot)

    result = cli_module.main(
        [
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert result == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "database_error"
    assert payload["error"]["db_path"] == str(db_path)
    assert payload["error"]["root_path"] == str(root)
    assert "snapshot insert failed" in payload["error"]["message"]
    assert "Traceback" not in captured.err


def test_collect_rolls_back_partial_directory_insert_on_failure(
    repo_root: Path,
    write_config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli_module = import_module(repo_root, "watchdirs.cli")
    root = tmp_path / "root"
    root.mkdir()
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    def fail_after_one_insert(connection, rows):
        row = rows[0]
        connection.execute(
            """
            INSERT INTO directory_sizes (
                snapshot_id,
                path,
                parent_path,
                name,
                depth,
                apparent_bytes,
                disk_bytes,
                file_count,
                dir_count,
                error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.snapshot_id,
                sqlite3.Binary(row.path),
                sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
                sqlite3.Binary(row.name),
                row.depth,
                row.apparent_bytes,
                row.disk_bytes,
                row.file_count,
                row.dir_count,
                row.error,
            ),
        )
        raise sqlite3.OperationalError("mid-batch insert failed")

    monkeypatch.setattr(cli_module, "insert_directory_rows", fail_after_one_insert)

    result = cli_module.main(
        [
            "collect",
            "--config",
            str(config_path),
            "--db",
            str(db_path),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert result == 1
    assert payload["ok"] is False
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert "mid-batch insert failed" in snapshots[0]["error"]
    assert directory_rows == []


def test_collect_finalizes_snapshot_on_sigterm(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    config_path = write_config(roots=[root])
    db_path = tmp_path / "watchdirs.sqlite3"
    driver = textwrap.dedent(
        f"""
        import signal
        import sys
        import time
        from pathlib import Path
        sys.path.insert(0, {str(repo_root / "src")!r})
        from watchdirs import cli
        from watchdirs.models import DirectoryAggregate, ScanResult, SnapshotStatus

        def slow_scan_root(root_path):
            time.sleep(30)
            return ScanResult(
                root_path=Path(root_path),
                rows=[
                    DirectoryAggregate(
                        snapshot_id=0,
                        path=str(root_path).encode(),
                        parent_path=None,
                        name=Path(root_path).name.encode(),
                        depth=0,
                        apparent_bytes=0,
                        disk_bytes=0,
                        file_count=0,
                        dir_count=0,
                        error=None,
                    )
                ],
                row_count=1,
                status=SnapshotStatus.COMPLETE,
                fatal_error=None,
            )

        cli.scan_root = slow_scan_root
        raise SystemExit(
            cli.main(
                [
                    "collect",
                    "--config",
                    {str(config_path)!r},
                    "--db",
                    {str(db_path)!r},
                    "--json",
                ]
            )
        )
        """
    )

    process = subprocess.Popen(
        ["python3", "-c", driver],
        cwd=repo_root,
        env=_command_env(repo_root, None),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        db_created = False
        for _ in range(200):
            if db_path.exists():
                db_created = True
                break
            process.poll()
            if process.returncode is not None:
                break
            import time

            time.sleep(0.05)
        assert db_created, process.stderr.read() if process.stderr else ""

        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode != 0, (stdout, stderr)
    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert directory_rows == []
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert snapshots[0]["finished_at"] is not None
    assert "interrupt" in snapshots[0]["error"].lower()


def test_collect_rolls_back_partial_directory_insert_on_sigterm(repo_root: Path, write_config, tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"
    driver = textwrap.dedent(
        f"""
        import os
        import signal
        import sqlite3
        import sys
        sys.path.insert(0, {str(repo_root / "src")!r})
        from watchdirs import cli

        def interrupt_after_one_insert(connection, rows):
            row = rows[0]
            connection.execute(
                '''
                INSERT INTO directory_sizes (
                    snapshot_id,
                    path,
                    parent_path,
                    name,
                    depth,
                    apparent_bytes,
                    disk_bytes,
                    file_count,
                    dir_count,
                    error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    row.snapshot_id,
                    sqlite3.Binary(row.path),
                    sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
                    sqlite3.Binary(row.name),
                    row.depth,
                    row.apparent_bytes,
                    row.disk_bytes,
                    row.file_count,
                    row.dir_count,
                    row.error,
                ),
            )
            os.kill(os.getpid(), signal.SIGTERM)

        cli.insert_directory_rows = interrupt_after_one_insert
        raise SystemExit(
            cli.main(
                [
                    "collect",
                    "--config",
                    {str(config_path)!r},
                    "--db",
                    {str(db_path)!r},
                    "--json",
                ]
            )
        )
        """
    )

    result = subprocess.run(
        ["python3", "-c", driver],
        cwd=repo_root,
        env=_command_env(repo_root, None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 128 + signal.SIGTERM, result
    snapshots, directory_rows = fetch_snapshot_rows(db_path)
    assert directory_rows == []
    assert len(snapshots) == 1
    assert snapshots[0]["status"] == "failed"
    assert snapshots[0]["finished_at"] is not None
    assert "interrupt" in snapshots[0]["error"].lower()
