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

# Type-check tests separately so production and fixture issues stay easy to read.
typecheck-tests:
    uv run basedpyright tests --warnings

# Check import boundaries.
_import-contracts:
    uv run lint-imports

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

# Static quality gate.
check: _fmt-check _lint _typecheck typecheck-tests _import-contracts _actionlint _compile _dead-code _systemd

# Unit tests.
unit:
    uv run pytest -q

# Full local gate for agents before claiming completion.
verify: check unit

# Coverage gate.
coverage:
    uv run pytest --cov=watchdirs --cov-report=term-missing
