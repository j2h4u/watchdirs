# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

from pathlib import Path

from test_cli_collect import import_module


def test_quality_suppression_gate_matches_repo_baseline(repo_root: Path) -> None:
    gate = import_module(repo_root, "watchdirs.quality_suppressions")
    policy = gate.load_policy(repo_root)
    report = gate.scan_policy(policy)

    assert report.findings == []
    assert report.counts == {
        "noqa": 6,
        "type_ignore": 0,
        "pyright": 0,
        "pylint": 0,
        "ruff": 0,
    }


def test_quality_suppression_gate_flags_malformed_and_budget_overrun(repo_root: Path, tmp_path: Path) -> None:
    gate = import_module(repo_root, "watchdirs.quality_suppressions")
    target = tmp_path / "sample.py"
    target.write_text(
        "value = 1  # noqa F401 - missing colon\nother = 2  # type: ignore\nthird = 3  # pyright: reportAny false\n",
        encoding="utf-8",
    )
    policy = gate.SuppressionPolicy(
        roots=(tmp_path,),
        baseline={
            "noqa": 0,
            "type_ignore": 0,
            "pyright": 0,
            "pylint": 0,
            "ruff": 0,
        },
    )

    report = gate.scan_policy(policy)
    problems = gate.report_problems(policy, report, repo_root)

    assert report.counts["noqa"] == 1
    assert report.counts["type_ignore"] == 1
    assert report.counts["pyright"] == 1
    assert len(report.findings) == 3
    assert any("expected `# noqa: CODE - reason`" in problem for problem in problems)
    assert any("expected `# type: ignore[code]`" in problem for problem in problems)
    assert any("expected `# pyright: name=value[, ...]`" in problem for problem in problems)
    assert any(problem.startswith("noqa: 1 > baseline 0") for problem in problems)
    assert any(problem.startswith("type_ignore: 1 > baseline 0") for problem in problems)
    assert any(problem.startswith("pyright: 1 > baseline 0") for problem in problems)
