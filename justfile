set shell := ["bash", "-uc"]
export UV_LINK_MODE := "hardlink"

# Show available repo commands.
default:
    @just --list

# Compile Python sources for syntax errors.
_compile:
    uv run python -m compileall -q src scripts tests

# Verify uv.lock is synchronized with pyproject.toml.
_lock-check:
    uv lock --check

# Lint with ruff across the whole repo.
_lint:
    uv run ruff check .

# Check preview-only complexity/refactor rules explicitly.
_preview-complexity-lint:
    uv run ruff check --preview --select PLR0914,PLR0916,PLR0917 src scripts tests

# Check formatting without writing.
_fmt-check:
    uv run ruff format --check .

# Check GitHub Actions workflow syntax and expressions.
_actionlint:
    uv run actionlint

# Guard obvious supply-chain drift in workflows and container image references.
_supply-chain-pins:
    uv run python scripts/check_supply_chain_pins.py

# Enforce the repo's suppression budget.
_suppressions:
    uv run python -m watchdirs.quality_suppressions

# Run the canonical static type checker on production code.
_typecheck:
    uv run basedpyright src/watchdirs scripts

# Type-check tests separately so production and fixture issues stay easy to read.
typecheck-tests:
    uv run basedpyright tests --warnings

# Check import boundaries.
_import-contracts:
    uv run lint-imports

# Check the exact module dependency graph.
_module-boundaries:
    uv run tach check

# Check declared Python dependencies against imports.
_deptry:
    uv run deptry src scripts tests

# Audit the locked dependency set for known vulnerabilities.
deps-audit:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' EXIT
    uv export --locked --all-groups --no-emit-project --no-emit-workspace --no-emit-local --no-header --no-annotate --no-editable > "$tmp"
    uv run pip-audit -r "$tmp" --strict --no-deps

# Verify SQLite schema/integrity gates cheaply in the quick static check.
_sqlite-integrity:
    uv run pytest -q tests/test_db_integrity_gate.py

# Build, install, and smoke-test the packaged wheel in an isolated venv.
_packaging-smoke:
    uv run python scripts/check_packaging_smoke.py

# Scan for dead code with vulture.
_dead-code:
    uv run vulture

# Verify repo-owned systemd units.
_systemd:
    tmp="$(mktemp -d)"; \
    trap 'rm -rf "$tmp"' EXIT; \
    mkdir -p "$tmp/etc/systemd/system" "$tmp/usr/local/bin"; \
    cp ops/systemd/* "$tmp/etc/systemd/system/"; \
    for target in sysinit.target timers.target sockets.target multi-user.target basic.target; do \
        printf '[Unit]\nDescription=%s\n' "$target" > "$tmp/etc/systemd/system/$target"; \
    done; \
    printf '#!/bin/sh\n' > "$tmp/usr/local/bin/watchdirs"; \
    chmod +x "$tmp/usr/local/bin/watchdirs"; \
    systemd-analyze verify --root "$tmp" "$tmp"/etc/systemd/system/*.service "$tmp"/etc/systemd/system/*.timer "$tmp"/etc/systemd/system/*.socket

# Auto-fix ruff findings and formatting.
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Remove local Python bytecode caches from the source checkout.
clean-pycache:
    find src/watchdirs tests -type d -name __pycache__ -prune -exec rm -r -- {} +

# Static quality gate.
check: _fmt-check _lint _preview-complexity-lint _lock-check _suppressions _typecheck typecheck-tests _import-contracts _module-boundaries _deptry _sqlite-integrity _actionlint _supply-chain-pins _compile _packaging-smoke _dead-code _systemd

# Unit tests.
unit:
    uv run pytest -q

# Full local gate for agents before claiming completion.
verify: check coverage deps-audit

# Coverage gate.
coverage:
    uv run pytest --cov=src/watchdirs --cov-report=term-missing
    uv run python scripts/check_crap_gate.py --threshold 30

# Run pytest with CRAP reporting over the full suite.
crap:
    uv run pytest --cov=src/watchdirs --cov-report=term-missing --crap --crap-threshold=30 --crap-top-n=30
    uv run python scripts/check_crap_gate.py --threshold 30
