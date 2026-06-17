# Coding Conventions

**Analysis Date:** 2026-06-17

## Naming Patterns

**Files:**
- Python modules use snake_case under `src/watchdirs/`, for example `src/watchdirs/collect/scanner.py`, `src/watchdirs/reporting/render.py`, and `src/watchdirs/db/connection.py`.
- Test files use `test_*.py` under `tests/`, for example `tests/test_cli_collect.py` and `tests/test_ops_retention.py`.

**Functions:**
- Public helpers and internal helpers use snake_case.
- Leading underscores mark module-private helpers and internal dataclasses, for example `_ScanState` in `src/watchdirs/collect/scanner.py` and `_directory_row` in `tests/test_cli_report_commands.py`.

**Variables:**
- Constants are UPPER_SNAKE_CASE, for example `WATCHDIRS_APPLICATION_ID` in `src/watchdirs/db/connection.py` and `REQUIRED_FLAGS` in `tests/test_cli_collect.py`.
- Small config holders are dataclasses with underscore-prefixed names, for example `_CliConfig` in `src/watchdirs/cli.py`.

**Types:**
- Domain types live in `src/watchdirs/models.py` and are imported into feature modules instead of redefined.
- Protocols in `tests/conftest.py` model the subset of fields tests need without binding to implementation objects.

## Code Style

**Formatting:**
- Ruff formatting is the repo standard, with 120-character lines and double-quoted strings in `pyproject.toml`.
- `from __future__ import annotations` is used consistently in runtime and test modules.

**Linting:**
- Ruff is the primary style gate, with import sorting, pyupgrade, bugbear, performance, simplification, pathlib, and logging rules enabled in `pyproject.toml`.
- Basedpyright checks production code from `src/watchdirs` and tests separately from `tests` via `justfile`.
- Import boundaries are enforced with import-linter contracts in `pyproject.toml`.

## Import Organization

**Order:**
1. Standard library imports.
2. Third-party imports.
3. Local `watchdirs` imports.

**Path Aliases:**
- Not detected. Imports use package-relative imports inside `src/watchdirs/` and explicit `src` path injection in tests.

## Error Handling

**Patterns:**
- Raise specific exceptions for programmer and environment failures, for example `FileNotFoundError` in `src/watchdirs/db/connection.py` and `ValueError` in CLI validation helpers in `src/watchdirs/cli.py`.
- Return structured result objects for user-facing failures instead of raising generic exceptions, especially in collection and reporting flows.
- Preserve JSON error contracts in the CLI; `tests/test_cli_collect.py` asserts `{ok: false, error: ...}` payloads for config and root failures.

## Logging

**Framework:** `logging`

**Patterns:**
- CLI collection logs to stderr only so stdout remains valid JSON, as documented in `src/watchdirs/cli.py`.
- Keep operational progress and diagnostics separate from machine-readable output.

## Comments

**When to Comment:**
- Use comments for invariants, host/runtime constraints, and why a branch exists, especially around SQLite pragmas, symlink handling, and JSON-output contracts.
- Avoid narrating obvious code.

**JSDoc/TSDoc:**
- Not used as a general style. Module docstrings are also not a dominant pattern.

## Function Design

**Size:**
- Keep public functions narrow and move branching into private helpers when the implementation grows, as seen in `src/watchdirs/cli.py`, `src/watchdirs/collect/scanner.py`, and `src/watchdirs/reporting/render.py`.

**Parameters:**
- Prefer keyword-heavy APIs for fixtures and synthetic builders, as seen in `tests/conftest.py` and `tests/test_reporting_queries.py`.
- Use dataclasses or tuples for structured inputs rather than loose dicts.

**Return Values:**
- Return typed dataclasses, tuples, or JSON-serializable dicts depending on the layer.
- Keep render/query helpers pure where possible; `src/watchdirs/reporting/render.py` is organized around deterministic transforms.

## Module Design

**Exports:**
- Feature packages expose a small public surface from `__init__.py`, while implementation details stay in leaf modules.
- Internal helpers remain module-local unless reused across feature boundaries.

**Barrel Files:**
- Minimal usage. `__init__.py` files exist, but most direct imports reference concrete modules such as `watchdirs.reporting.queries` or `watchdirs.db.migrations`.

---

*Convention analysis: 2026-06-17*
