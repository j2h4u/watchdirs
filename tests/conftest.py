# pyright: reportExplicitAny=false, reportAny=false
from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Any, Protocol

import pytest


@pytest.fixture(autouse=True)
def sqlite_connection_ownership(monkeypatch: pytest.MonkeyPatch):
    """Own and close every SQLite connection created during a test."""
    connections: list[sqlite3.Connection] = []
    connect = sqlite3.connect

    def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    yield

    for connection in connections:
        connection.close()


class DirectoryAggregateLike(Protocol):
    snapshot_id: int
    path: bytes
    parent_path: bytes | None
    depth: int
    apparent_bytes: int
    disk_bytes: int
    file_count: int
    dir_count: int
    error: str | None
    collapsed: bool
    collapse_reason: str | None
    collapsed_dirs: int | None
    top_child_path: bytes | None
    top_child_disk_bytes: int | None


class MountInfoLike(Protocol):
    mount_id: int
    parent_id: int
    major_minor: str
    root: bytes
    mount_point: bytes
    options: tuple[str, ...]
    filesystem_type: str
    mount_source: str
    super_options: tuple[str, ...]


class ScanErrorLike(Protocol):
    path: bytes
    path_bytes_hex: str
    message: str
    kind: str


class SnapshotStatusLike(Protocol):
    value: str


class ScanResultLike(Protocol):
    root_path: Path
    rows: tuple[DirectoryAggregateLike, ...]
    row_count: int
    status: SnapshotStatusLike
    fatal_error: str | None
    errors: tuple[ScanErrorLike, ...]
    hardlink_count: int


class TopRowLike(Protocol):
    snapshot_id: int
    root_path: Path
    path: bytes
    path_bytes_hex: str
    depth: int
    current_apparent_bytes: int
    current_disk_bytes: int
    file_count: int
    dir_count: int
    error: str | None
    collapsed: bool
    collapse_reason: str | None
    collapsed_dirs: int | None
    top_child_path: bytes | None
    top_child_disk_bytes: int | None
    group: object | None


class DiffRowLike(Protocol):
    root_path: Path
    baseline_snapshot_id: int
    current_snapshot_id: int
    path: bytes
    parent_path: bytes | None
    depth: int
    classification: str
    previous_apparent_bytes: int
    current_apparent_bytes: int
    apparent_bytes_delta: int
    previous_disk_bytes: int
    current_disk_bytes: int
    disk_bytes_delta: int
    error: str | None
    collapsed: bool
    collapse_reason: str | None
    collapsed_dirs: int | None
    top_child_path: bytes | None
    top_child_disk_bytes: int | None
    group: object | None


JsonDict = dict[str, Any]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def sample_config_path(repo_root: Path) -> Path:
    return repo_root / "examples" / "host.watchdirs.toml"


@pytest.fixture
def import_watchdirs_module(repo_root: Path):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    def _import(module_name: str):
        return importlib.import_module(module_name)

    return _import


@pytest.fixture
def write_config(tmp_path: Path):
    def _write_config(
        *,
        roots: list[Path] | None = None,
        exclude_paths: list[Path] | None = None,
        included_filesystems: list[str] | None = None,
        collapse: dict[str, Any] | None = None,
        raw: str | None = None,
    ) -> Path:
        config_path = tmp_path / "watchdirs.toml"
        if raw is not None:
            config_path.write_text(raw, encoding="utf-8")
            return config_path

        lines: list[str] = []
        if exclude_paths is not None:
            values = ", ".join(f'"{path}"' for path in exclude_paths)
            lines.append(f"exclude_paths = [{values}]")

        if roots is not None:
            for root in roots:
                if lines:
                    lines.append("")
                lines.extend([
                    "[[roots]]",
                    f'path = "{root}"',
                ])

        if included_filesystems is not None:
            if lines:
                lines.append("")
            values = ", ".join(f'"{filesystem}"' for filesystem in included_filesystems)
            lines.extend([
                "[mount_policy]",
                f"included_filesystems = [{values}]",
            ])

        if collapse is not None:
            if lines:
                lines.append("")
            lines.append("[collapse]")
            for key, value in collapse.items():
                if isinstance(value, list):
                    rendered = ", ".join(f'"{item}"' for item in value)
                    lines.append(f"{key} = [{rendered}]")
                elif isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")

        config_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return config_path

    return _write_config
