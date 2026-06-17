"""D-11 observability: collect logs progress/ETA/summary to stderr.

The agent-facing contract is that ``collect --json`` writes PURE JSON to stdout.
Observability (INFO progress lines + one structured end-summary record) must land
on stderr ONLY, where it is captured by the systemd journal under Phase 4's root
unit. These tests pin both halves of that contract:

  1. stdout stays valid JSON (purity) even with progress/summary enabled.
  2. the structured summary (dirs / duration / db_bytes) and at least one progress
     line appear on stderr.
  3. nothing observability-related leaks into stdout.

A deterministic unit test of the ETA computation (injected monotonic clock, no
sleeps) pins the rate-based formula and the "no estimate -> no ETA" rule.
"""

# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import re
from pathlib import Path

from test_cli_collect import (
    create_sample_tree,
    import_module,
    parse_json_output,
    run_repo_local,
)


def test_collect_verbose_keeps_stdout_pure_json_and_logs_to_stderr(
    repo_root: Path, write_config, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    result = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
        "--verbose",
    )

    assert result.returncode == 0, result.stderr

    # (a) stdout purity: the collect JSON payload is unchanged and parses cleanly.
    payload = parse_json_output(result)
    assert payload["command"] == "collect"
    assert payload["ok"] is True
    snapshot_payload = payload["snapshots"][0]
    inserted = snapshot_payload["row_count"]
    assert inserted > 0

    # (c) NO progress/summary text leaked into stdout.
    assert "collect summary" not in result.stdout
    assert "dirs/s" not in result.stdout
    assert "ETA" not in result.stdout

    # (b) the structured summary record lands on stderr with dirs/duration/db_bytes,
    # and dirs matches the inserted row_count.
    stderr = result.stderr
    assert "collect summary" in stderr
    summary_match = re.search(r"collect summary dirs=(\d+) duration_s=([\d.]+) db_bytes=(\d+)", stderr)
    assert summary_match is not None, f"no structured summary on stderr:\n{stderr}"
    assert int(summary_match.group(1)) == inserted
    assert float(summary_match.group(2)) >= 0.0
    assert int(summary_match.group(3)) > 0

    # at least one progress/INFO line.
    assert "dirs/s" in stderr


def test_collect_default_keeps_stdout_pure_json(repo_root: Path, write_config, tmp_path: Path) -> None:
    """Without --verbose stdout is still pure JSON (the contract never depends on a flag)."""
    root = tmp_path / "root"
    create_sample_tree(root)
    config_path = write_config(roots=[root], included_filesystems=["tmpfs"])
    db_path = tmp_path / "watchdirs.sqlite3"

    result = run_repo_local(
        repo_root,
        "collect",
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "--json",
    )

    assert result.returncode == 0, result.stderr
    payload = parse_json_output(result)
    assert payload["command"] == "collect"
    assert "collect summary" not in result.stdout


def test_compute_eta_uses_rate_with_injected_clock(repo_root: Path) -> None:
    """ETA is rate-based and deterministic under an injected monotonic clock (no sleeps)."""
    cli = import_module(repo_root, "watchdirs.cli")

    # 40 dirs scanned over a 10s elapsed interval -> 4 dirs/s.
    # 100 total estimate -> 60 remaining -> 60 / 4 = 15.0s ETA.
    rate, eta = cli.compute_eta(dirs_done=40, dirs_total_estimate=100, elapsed=10.0)
    assert rate == 4.0
    assert eta == 15.0

    # No estimate -> rate only, ETA omitted.
    rate, eta = cli.compute_eta(dirs_done=40, dirs_total_estimate=None, elapsed=10.0)
    assert rate == 4.0
    assert eta is None

    # Zero elapsed -> rate 0, no ETA (no division by zero).
    rate, eta = cli.compute_eta(dirs_done=40, dirs_total_estimate=100, elapsed=0.0)
    assert rate == 0.0
    assert eta is None


def test_configure_collect_logging_binds_stderr_only(repo_root: Path) -> None:
    """The collect logger handler must target sys.stderr, never sys.stdout."""
    import logging
    import sys

    cli = import_module(repo_root, "watchdirs.cli")
    logger = logging.getLogger("watchdirs.collect")
    # Clear any handlers from a prior call so the assertion is deterministic.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    cli.configure_collect_logging(verbose=True)

    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert stream_handlers, "expected a StreamHandler on the collect logger"
    assert all(h.stream is sys.stderr for h in stream_handlers)
    assert not any(h.stream is sys.stdout for h in stream_handlers)
    assert logger.level == logging.INFO
