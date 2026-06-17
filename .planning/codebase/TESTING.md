# Testing Patterns

**Analysis Date:** 2026-06-17

## Test Framework

**Runner:**
- `pytest` 9.x, configured through `pyproject.toml` and run via `just unit` / `just coverage` / `just check` in `justfile`.

**Assertion Library:**
- Native `assert` statements with `pytest.raises` for exceptional paths.

**Run Commands:**
```bash
just unit
just coverage
just check
```

## Test File Organization

**Location:**
- Main tests live in `tests/` and are co-located by behavior area, not by source package layout.
- Benchmark-style checks live under `tests/bench/`.

**Naming:**
- Files start with `test_` and functions start with `test_`.

**Structure:**
```text
tests/
├── conftest.py
├── test_cli_collect.py
├── test_cli_report_commands.py
├── test_db_schema.py
├── test_ops_locking.py
└── ...
```

## Test Structure

**Suite Organization:**
```python
def test_collect_requires_configured_roots_json(repo_root: Path, write_config) -> None:
    config_path = write_config(raw='exclude_paths = ["/tmp"]\n')

    result = run_module(repo_root, "collect", "--config", str(config_path), "--json")

    payload = assert_config_error(result, "no_roots")
    assert payload["error"]["path"] == str(config_path)
```

**Patterns:**
- Arrange/act/assert is the dominant shape.
- Helpers build synthetic DB rows, mount tables, and filesystem trees instead of duplicating setup.
- Many tests verify exact JSON payloads, exit codes, and SQLite state.

## Mocking

**Framework:** `pytest.monkeypatch`, local fakes, and lightweight `SimpleNamespace`/socket/thread scaffolding.

**Patterns:**
```python
monkeypatch.setenv("WATCHDIRS_QUERY_SOCKET", str(socket_path))
monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
```

**What to Mock:**
- OS identity, environment variables, sockets, and small protocol objects.

**What NOT to Mock:**
- Do not mock the SQLite layer or CLI JSON contracts unless the test is specifically about an isolated branch.
- Prefer real files, real temporary directories, and real SQLite connections.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def write_config(tmp_path: Path):
    def _write_config(*, roots=None, exclude_paths=None, included_filesystems=None, collapse=None, raw=None) -> Path:
        ...
```

**Location:**
- Shared fixtures and protocol types live in `tests/conftest.py`.
- Module-local factory helpers live beside the tests that use them, for example `tests/test_reporting_queries.py` and `tests/test_cli_report_commands.py`.

## Coverage

**Requirements:** `fail_under = 77` in `pyproject.toml`.

**View Coverage:**
```bash
just coverage
```

## Test Types

**Unit Tests:**
- Most tests are unit-style with targeted filesystem, DB, and command-path setup.

**Integration Tests:**
- CLI subprocess tests exercise `python3 -m watchdirs` and repo-local entrypoints in `tests/test_cli_collect.py`, `tests/test_cli_report_commands.py`, and `tests/test_ops_locking.py`.

**E2E Tests:**
- Not detected.

## Common Patterns

**Async Testing:**
- Not used broadly. Concurrency appears through threads and subprocesses, not async test frameworks.

**Error Testing:**
```python
with pytest.raises(ValueError, match="not allowed"):
    cli._validated_query_argv({"argv": ["collect", "--config", "/etc/watchdirs/watchdirs.toml"]})
```

---

*Testing analysis: 2026-06-17*
