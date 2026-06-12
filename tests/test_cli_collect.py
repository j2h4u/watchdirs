from __future__ import annotations

import importlib
import json
import os
import shlex
import subprocess
import sys
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
