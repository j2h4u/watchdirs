set shell := ["bash", "-uc"]

# Show available repo commands.
default:
    @just --list

# Compile Python sources for syntax errors.
_compile:
    uv run python -m compileall -q watchdirs src tests

# Lint with ruff across the whole repo.
_lint:
    uv run ruff check .

# Check formatting without writing.
_fmt-check:
    uv run ruff format --check .

# Check GitHub Actions workflow syntax and expressions.
_actionlint:
    uv run actionlint

# Run the canonical static type checker on production code.
_typecheck:
    uv run basedpyright src/watchdirs

# Scan for dead code with vulture.
_dead-code:
    uv run vulture

# Verify repo-owned systemd units.
_systemd:
    systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer ops/systemd/*.socket

# Auto-fix ruff findings and formatting.
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Static quality gate.
check: _fmt-check _lint _typecheck _actionlint _compile _dead-code _systemd

# Unit tests.
unit:
    uv run pytest -q

# Full local gate for agents before claiming completion.
verify: check unit

# Coverage gate.
coverage:
    uv run pytest --cov=watchdirs --cov-report=term-missing
