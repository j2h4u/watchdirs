from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def sample_config_path(repo_root: Path) -> Path:
    return repo_root / "examples" / "senbonzakura.watchdirs.toml"


@pytest.fixture
def write_config(tmp_path: Path):
    def _write_config(
        *,
        roots: list[Path] | None = None,
        exclude_paths: list[Path] | None = None,
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
                lines.extend(
                    [
                        "[[roots]]",
                        f'path = "{root}"',
                    ]
                )

        config_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return config_path

    return _write_config
