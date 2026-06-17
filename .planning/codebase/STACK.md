# Technology Stack

**Analysis Date:** 2026-06-17

## Languages

**Primary:**
- Python 3.11+ - Runtime code under `src/watchdirs/`, tests under `tests/`, helper scripts under `scripts/`

**Secondary:**
- TOML - Repo configuration in `pyproject.toml` and host config example in `examples/host.watchdirs.toml`
- POSIX shell/systemd unit syntax - Service and timer definitions in `ops/systemd/`

## Runtime

**Environment:**
- Python 3.11 or newer
- Linux host with `systemd`, SQLite, `/proc`, `mountinfo`, `lsof`, and `docker` available for the optional diagnostics surface

**Package Manager:**
- `uv` - Used by `just` targets for checks, tests, and packaging smoke verification
- Lockfile: present (`uv.lock`)

## Frameworks

**Core:**
- None detected - The application is a stdlib-based CLI package without a web or application framework

**Testing:**
- `pytest` - Test runner for `tests/` and `tests/bench/`
- `pytest-cov` - Coverage reporting
- `pytest-xdist` - Parallel test execution support

**Build/Dev:**
- `setuptools` - Build backend in `pyproject.toml`
- `ruff` - Formatting and linting
- `basedpyright` - Static type checking
- `import-linter` - Import boundary enforcement
- `vulture` - Dead-code scanning
- `actionlint-py` - GitHub Actions workflow validation
- `just` - Task runner in `justfile`

## Key Dependencies

**Critical:**
- None detected - Runtime dependencies are intentionally empty in `pyproject.toml`
- Standard library modules do the work: `sqlite3`, `tomllib`, `argparse`, `subprocess`, `fcntl`, `os`, `pathlib`, `json`

**Infrastructure:**
- `sqlite3` - Persistent storage and query engine
- `fcntl` - File locking in `src/watchdirs/ops_lock.py`
- `subprocess` - Read-only host probes for `docker` and `lsof`
- `tomllib` - Configuration parsing in `src/watchdirs/config.py`

## Configuration

**Environment:**
- Config file is TOML, loaded by `src/watchdirs/config.py`
- Default state directory comes from `XDG_STATE_HOME` or `~/.local/state/watchdirs`
- Default cache directory comes from `XDG_CACHE_HOME` or `~/.cache/watchdirs`
- Root paths, excludes, and collapse rules are absolute-path TOML entries

**Build:**
- `pyproject.toml`
- `justfile`
- `uv.lock`
- `ops/systemd/watchdirs-*.service`
- `ops/systemd/watchdirs-*.timer`
- `ops/systemd/watchdirs-query.socket`

## Platform Requirements

**Development:**
- Linux
- Python 3.11+
- `uv`, `pytest`, `ruff`, `basedpyright`, `import-linter`, `vulture`, `actionlint`

**Production:**
- Linux with `systemd`
- SQLite database stored under `/var/lib/watchdirs/watchdirs.sqlite3`
- Query socket at `/run/watchdirs/query.sock`

---

*Stack analysis: 2026-06-17*
