from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib


APP_NAME = "watchdirs"
DEFAULT_DB_NAME = "watchdirs.sqlite3"


@dataclass(frozen=True)
class ConfiguredRoot:
    path: Path


@dataclass(frozen=True)
class WatchConfig:
    roots: tuple[ConfiguredRoot, ...]
    exclude_paths: tuple[Path, ...]


@dataclass(frozen=True)
class ConfigError(Exception):
    kind: str
    path: str
    message: str

    def to_payload(self) -> dict[str, object]:
        return {
            "ok": False,
            "error": {
                "code": "config_error",
                "kind": self.kind,
                "message": self.message,
                "path": self.path,
            },
        }


def default_state_dir() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home).expanduser() / APP_NAME
    return Path.home() / ".local" / "state" / APP_NAME


def default_cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home).expanduser() / APP_NAME
    return Path.home() / ".cache" / APP_NAME


def default_db_path() -> Path:
    return default_state_dir() / DEFAULT_DB_NAME


def load_config(path: Path) -> WatchConfig:
    config_path = Path(path).expanduser()
    data = _read_toml(config_path)
    roots = _parse_roots(data, config_path)
    exclude_paths = _parse_exclude_paths(data, config_path)
    validate_roots(roots)
    return WatchConfig(roots=roots, exclude_paths=exclude_paths)


def validate_roots(roots: tuple[ConfiguredRoot, ...]) -> None:
    if not roots:
        raise ConfigError("no_roots", "", "configuration must declare at least one root")

    resolved_roots: list[Path] = []
    for root in roots:
        path = root.path
        if not path.exists():
            raise ConfigError("missing_root", str(path), "configured root does not exist")
        if not path.is_dir():
            raise ConfigError("file_root", str(path), "configured root must be a directory")

        for existing in resolved_roots:
            if path == existing or existing in path.parents or path in existing.parents:
                raise ConfigError("overlapping_roots", str(path), "configured roots must not overlap")
        resolved_roots.append(path)


def _read_toml(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        raise ConfigError("missing_config", str(config_path), "config file does not exist")
    if not config_path.is_file():
        raise ConfigError("missing_config", str(config_path), "config path must be a file")

    try:
        raw_bytes = config_path.read_bytes()
    except PermissionError as exc:
        raise ConfigError("unreadable_config", str(config_path), f"config file is not readable: {exc.strerror}") from exc
    except OSError as exc:
        raise ConfigError("unreadable_config", str(config_path), f"config file is not readable: {exc.strerror}") from exc

    try:
        loaded = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError("malformed_config", str(config_path), f"config is not valid UTF-8: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("malformed_config", str(config_path), f"config is not valid TOML: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError("malformed_config", str(config_path), "config root must be a TOML table")
    return loaded


def _parse_roots(data: dict[str, object], config_path: Path) -> tuple[ConfiguredRoot, ...]:
    root_entries = data.get("roots")
    if root_entries is None:
        raise ConfigError("no_roots", str(config_path), "configuration must declare at least one root")
    if not isinstance(root_entries, list):
        raise ConfigError("malformed_config", str(config_path), "roots must be an array of tables")

    roots: list[ConfiguredRoot] = []
    for entry in root_entries:
        if not isinstance(entry, dict):
            raise ConfigError("malformed_config", str(config_path), "each root must be a TOML table")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigError("malformed_config", str(config_path), "each root must include a path string")
        path = _normalize_absolute_path(raw_path, "invalid_root")
        roots.append(ConfiguredRoot(path=path))

    return tuple(roots)


def _parse_exclude_paths(data: dict[str, object], config_path: Path) -> tuple[Path, ...]:
    raw_excludes = data.get("exclude_paths", [])
    if raw_excludes is None:
        return ()
    if not isinstance(raw_excludes, list):
        raise ConfigError("malformed_config", str(config_path), "exclude_paths must be an array")

    exclude_paths: list[Path] = []
    for raw_path in raw_excludes:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigError("malformed_config", str(config_path), "exclude_paths entries must be path strings")
        exclude_paths.append(_normalize_absolute_path(raw_path, "invalid_exclude_path"))
    return tuple(exclude_paths)


def _normalize_absolute_path(raw_path: str, error_kind: str) -> Path:
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        raise ConfigError(error_kind, raw_path, "configured paths must be absolute")
    return expanded.resolve(strict=False)
