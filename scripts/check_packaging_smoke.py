from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from venv import EnvBuilder


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory(prefix="watchdirs-packaging-") as tmp:
        workdir = Path(tmp)
        dist_dir = workdir / "dist"
        venv_dir = workdir / "venv"

        _run(["uv", "build", "--wheel", "--out-dir", str(dist_dir), "--no-build-logs", str(repo_root)])

        wheel_files = sorted(dist_dir.glob("*.whl"))
        if len(wheel_files) != 1:
            raise RuntimeError(f"expected exactly one wheel, found {len(wheel_files)} in {dist_dir}")
        wheel_path = wheel_files[0]

        EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        if not venv_python.is_file():
            raise RuntimeError(f"venv python not found: {venv_python}")

        install_env = {**os.environ, "UV_LINK_MODE": "copy"}
        _run(["uv", "pip", "install", "--python", str(venv_python), str(wheel_path)], env=install_env)
        _run([str(venv_python), "-m", "watchdirs", "--help"])

        smoke_script = """
from __future__ import annotations

import sqlite3
import tempfile
from importlib import resources
from pathlib import Path

from watchdirs.db.migrations import SCHEMA_VERSION, initialize_database

schema = resources.files("watchdirs.db").joinpath("schema.sql")
if not schema.is_file():
    raise SystemExit(f"schema.sql missing from installed wheel: {schema}")

with tempfile.TemporaryDirectory(prefix="watchdirs-db-") as tmp:
    db_path = Path(tmp) / "watchdirs.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        initialize_database(connection)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    if version != SCHEMA_VERSION:
        raise SystemExit(f"unexpected schema version after initialization: {version}")
"""
        _run([str(venv_python), "-c", smoke_script])

    print("packaging smoke passed: wheel built, installed, CLI help ran, schema.sql initialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
