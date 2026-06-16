from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from .models import CollapsePolicy, MountPolicy


APP_NAME = "watchdirs"
DEFAULT_DB_NAME = "watchdirs.sqlite3"
DEFAULT_COLLAPSE_NAMES = frozenset(
    {
        "node_modules",
        ".venv",
        ".git",
        "site-packages",
        "__pycache__",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".npm",
        ".gradle",
        ".cargo",
        ".rustup",
    }
)


@dataclass(frozen=True)
class ConfiguredRoot:
    path: Path


@dataclass(frozen=True)
class WatchConfig:
    roots: tuple[ConfiguredRoot, ...]
    exclude_paths: tuple[Path, ...]
    mount_policy: MountPolicy
    collapse_policy: CollapsePolicy


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
    mount_policy = _parse_mount_policy(data, config_path)
    collapse_policy = _parse_collapse_policy(data, config_path)
    validate_roots(roots)
    return WatchConfig(
        roots=roots,
        exclude_paths=exclude_paths,
        mount_policy=mount_policy,
        collapse_policy=collapse_policy,
    )


def validate_roots(roots: tuple[ConfiguredRoot, ...]) -> None:
    if not roots:
        raise ConfigError("no_roots", "", "configuration must declare at least one root")

    resolved_roots: list[Path] = []
    for root in roots:
        path = root.path
        if _has_symlink_component(path):
            raise ConfigError(
                "symlink_root",
                str(path),
                "configured root must not traverse a symlinked path component",
            )
        if not path.exists():
            raise ConfigError("missing_root", str(path), "configured root does not exist")
        if not path.is_dir():
            raise ConfigError("file_root", str(path), "configured root must be a directory")

        for existing in resolved_roots:
            if path == existing or existing in path.parents or path in existing.parents:
                raise ConfigError("overlapping_roots", str(path), "configured roots must not overlap")
        resolved_roots.append(path)


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
    return False


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


def _parse_mount_policy(data: dict[str, object], config_path: Path) -> MountPolicy:
    raw_policy = data.get("mount_policy", {})
    if raw_policy is None:
        return MountPolicy()
    if not isinstance(raw_policy, dict):
        raise ConfigError("malformed_config", str(config_path), "mount_policy must be a TOML table")

    included_filesystems = _parse_filesystem_list(
        raw_policy,
        config_path,
        field_name="included_filesystems",
    )
    skipped_filesystems = _parse_filesystem_list(
        raw_policy,
        config_path,
        field_name="skipped_filesystems",
    )
    skip_overlay = _parse_bool(raw_policy, config_path, field_name="skip_overlay", default=True)
    skip_namespace = _parse_bool(raw_policy, config_path, field_name="skip_namespace", default=True)
    one_filesystem = _parse_bool(raw_policy, config_path, field_name="one_filesystem", default=True)

    return MountPolicy(
        skipped_filesystems=skipped_filesystems,
        included_filesystems=included_filesystems,
        skip_overlay=skip_overlay,
        skip_namespace=skip_namespace,
        one_filesystem=one_filesystem,
    )


def _parse_collapse_policy(data: dict[str, object], config_path: Path) -> CollapsePolicy:
    raw_policy = data.get("collapse", {})
    if raw_policy is None:
        return CollapsePolicy(
            names=DEFAULT_COLLAPSE_NAMES,
            fan_out=500,
            descendants=10000,
            never=(),
        )
    if not isinstance(raw_policy, dict):
        raise ConfigError("malformed_config", str(config_path), "collapse must be a TOML table")

    allowed_fields = {"names", "fan_out", "descendants", "never"}
    extra_fields = set(raw_policy) - allowed_fields
    if extra_fields:
        extra_field = sorted(extra_fields)[0]
        raise ConfigError("malformed_config", str(config_path), f"collapse.{extra_field} is not supported")

    names = _parse_collapse_names(raw_policy, config_path)
    fan_out = _parse_positive_int(raw_policy, config_path, field_name="fan_out", default=500)
    descendants = _parse_positive_int(raw_policy, config_path, field_name="descendants", default=10000)
    never = _parse_collapse_never(raw_policy, config_path)
    return CollapsePolicy(
        names=names,
        fan_out=fan_out,
        descendants=descendants,
        never=never,
    )


def _parse_filesystem_list(
    raw_policy: dict[str, object],
    config_path: Path,
    *,
    field_name: str,
) -> frozenset[str]:
    raw_values = raw_policy.get(field_name, [])
    if raw_values is None:
        return frozenset()
    if not isinstance(raw_values, list):
        raise ConfigError("malformed_config", str(config_path), f"mount_policy.{field_name} must be an array")

    values: list[str] = []
    for raw_value in raw_values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ConfigError(
                "malformed_config",
                str(config_path),
                f"mount_policy.{field_name} entries must be non-empty strings",
            )
        values.append(raw_value.strip())
    return frozenset(values)


def _parse_bool(
    raw_policy: dict[str, object],
    config_path: Path,
    *,
    field_name: str,
    default: bool,
) -> bool:
    raw_value = raw_policy.get(field_name, default)
    if not isinstance(raw_value, bool):
        raise ConfigError("malformed_config", str(config_path), f"mount_policy.{field_name} must be a boolean")
    return raw_value


def _parse_collapse_names(raw_policy: dict[str, object], config_path: Path) -> frozenset[str]:
    raw_names = raw_policy.get("names")
    if raw_names is None:
        return DEFAULT_COLLAPSE_NAMES
    if not isinstance(raw_names, list):
        raise ConfigError("malformed_config", str(config_path), "collapse.names must be an array")

    names: list[str] = []
    for raw_name in raw_names:
        if not isinstance(raw_name, str):
            raise ConfigError("malformed_config", str(config_path), "collapse.names entries must be strings")
        name = raw_name.strip()
        if not name:
            raise ConfigError("malformed_config", str(config_path), "collapse.names entries must be non-empty")
        names.append(name)
    return frozenset(names)


def _parse_positive_int(
    raw_policy: dict[str, object],
    config_path: Path,
    *,
    field_name: str,
    default: int,
) -> int:
    raw_value = raw_policy.get(field_name, default)
    if not isinstance(raw_value, int) or isinstance(raw_value, bool) or raw_value < 1:
        raise ConfigError("malformed_config", str(config_path), f"collapse.{field_name} must be an integer >= 1")
    return raw_value


def _parse_collapse_never(raw_policy: dict[str, object], config_path: Path) -> tuple[Path, ...]:
    raw_paths = raw_policy.get("never", [])
    if raw_paths is None:
        return ()
    if not isinstance(raw_paths, list):
        raise ConfigError("malformed_config", str(config_path), "collapse.never must be an array")

    normalized_paths: list[Path] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigError("malformed_config", str(config_path), "collapse.never entries must be path strings")
        normalized_paths.append(_normalize_absolute_path(raw_path, "invalid_collapse_never"))
    return tuple(normalized_paths)


def _normalize_absolute_path(raw_path: str, error_kind: str) -> Path:
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute():
        raise ConfigError(error_kind, raw_path, "configured paths must be absolute")
    return expanded.absolute()
