from __future__ import annotations

import importlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

JsonObject = dict[str, object]
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class SweepModule(Protocol):
    def main(self, argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int: ...

    def sweep(self, *, runner: Runner | None = None) -> object: ...

    def _human(self, payload: object, *, now: datetime | None = None) -> str: ...


github_sweep = cast(SweepModule, importlib.import_module("scripts.github_sweep"))


def _result(payload: object, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["gh"], returncode, json.dumps(payload), stderr)


def _object(value: object) -> JsonObject:
    assert isinstance(value, dict)
    return cast(JsonObject, value)


def test_sweep_collects_complete_response_uses_paginated_code_scanning_and_groups_enji_prs() -> None:
    commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:3] == ["gh", "repo", "view"]:
            return _result({"nameWithOwner": "acme/widgets"})
        path = command[2]
        if path == "repos/acme/widgets" and len(command) == 3:
            return _result({"default_branch": "main", "security_and_analysis": {}})
        if "branches/main/protection" in path:
            return _result({"required_status_checks": {}})
        responses: tuple[tuple[str, object], ...] = (
            (
                "pulls?state=open",
                [
                    [
                        {
                            "number": 7,
                            "title": "Update",
                            "user": {"login": "EnJi-bot", "type": "Bot"},
                            "head": {"sha": "abc"},
                        }
                    ]
                ],
            ),
            ("/reviews?", [[]]),
            ("check-runs", [{"check_runs": []}]),
        )
        for match, response in responses:
            if match in path:
                return _result(response)
        return _result([])

    payload = github_sweep.sweep(runner=runner)
    sections = _object(_object(payload)["sections"])

    assert _object(payload)["repo"] == "acme/widgets"
    assert set(sections) == {
        "repository",
        "security_and_analysis",
        "automated_security_fixes",
        "pull_requests",
        "workflows",
        "workflow_runs",
        "code_scanning_alerts",
        "dependabot_alerts",
        "secret_scanning_alerts",
        "rulesets",
        "default_branch_protection",
        "releases",
        "deployments",
    }
    assert any("code-scanning/alerts" in command[2] for command in commands if len(command) > 2 and command[1] == "api")
    paginated = [
        command
        for command in commands
        if len(command) > 2 and command[1] == "api" and "code-scanning/alerts" in command[2]
    ]
    assert paginated == [
        [
            "gh",
            "api",
            "repos/acme/widgets/code-scanning/alerts?per_page=100",
            "--paginate",
            "--slurp",
        ]
    ]
    pull_request_data = _object(_object(sections["pull_requests"])["data"])
    pull_request_items = cast(list[object], pull_request_data["items"])
    assert pull_request_data["groups"] == {
        "bot_authored": [pull_request_items[0]],
        "enji_authored": [pull_request_items[0]],
    }
    assert all(_object(section)["available"] is True for section in sections.values())


def test_sweep_labels_one_failed_endpoint_and_continues() -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "view"]:
            return _result({"nameWithOwner": "acme/widgets"})
        if "dependabot/alerts" in command[2]:
            return _result({}, 1, "Resource not accessible by integration")
        if "repos/acme/widgets" in command[2] and "branches" not in command[2]:
            return _result({"default_branch": "main"})
        return _result([])

    payload = github_sweep.sweep(runner=runner)
    sections = _object(_object(payload)["sections"])

    assert sections["dependabot_alerts"] == {
        "available": False,
        "error": "Resource not accessible by integration",
    }
    assert _object(sections["releases"])["available"] is True


def test_main_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "view"]:
            return _result({"nameWithOwner": "acme/widgets"})
        if "repos/acme/widgets" in command[2] and "branches" not in command[2]:
            return _result({"default_branch": "main"})
        return _result([])

    assert github_sweep.main(["--json"], runner=runner) == 0
    json_output = cast(object, json.loads(capsys.readouterr().out))
    assert _object(json_output)["repo"] == "acme/widgets"


def test_sweep_redacts_and_truncates_endpoint_error() -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "view"]:
            return _result({"nameWithOwner": "acme/widgets"})
        if "dependabot/alerts" in command[2]:
            return _result({}, 1, f"Authorization: Bearer opaque-secret token={secret} " + "x" * 600)
        if "repos/acme/widgets" in command[2] and "branches" not in command[2]:
            return _result({"default_branch": "main"})
        return _result([])

    payload = github_sweep.sweep(runner=runner)
    sections = _object(_object(payload)["sections"])
    error = _object(sections["dependabot_alerts"])["error"]
    assert isinstance(error, str)

    assert secret not in error
    assert "opaque-secret" not in error
    assert "[REDACTED]" in error
    assert len(error) == 500


def test_branch_not_protected_is_a_known_disabled_setting() -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["gh", "repo", "view"]:
            return _result({"nameWithOwner": "acme/widgets"})
        if "branches/main/protection" in command[2]:
            return _result({}, 1, "gh: Branch not protected (HTTP 404)")
        if command[2] == "repos/acme/widgets":
            return _result({"default_branch": "main", "security_and_analysis": {}})
        return _result([])

    payload = github_sweep.sweep(runner=runner)
    sections = _object(_object(payload)["sections"])
    protection = _object(sections["default_branch_protection"])

    assert protection == {"available": True, "data": {"protected": False}}
    human = github_sweep._human(_object(payload), now=datetime(2026, 7, 13, tzinfo=UTC))
    assert "Default branch protection: disabled" in human
    assert "default_branch_protection" not in human.partition("Open PRs:")[0]


def test_human_summary_separates_recent_and_historical_failures() -> None:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    payload: dict[str, object] = {
        "repo": "acme/widgets",
        "sections": {
            "workflow_runs": {
                "available": True,
                "data": {
                    "workflow_runs": [
                        {"conclusion": "failure", "updated_at": "2026-07-12T00:00:00Z"},
                        {"conclusion": "failure", "created_at": "2026-06-01T00:00:00Z"},
                    ]
                },
            },
            "workflows": {"available": True, "data": {"workflows": []}},
            "default_branch_protection": {"available": True, "data": {"protected": False}},
        },
    }

    human = github_sweep._human(payload, now=now)

    assert "1 recent failed runs, 1 historical failed runs" in human
    assert "Action: inspect failed/in-progress runs" in human

    historical_only = _object(payload)
    historical_sections = _object(historical_only["sections"])
    historical_runs = _object(_object(historical_sections["workflow_runs"])["data"])["workflow_runs"]
    assert isinstance(historical_runs, list)
    historical_runs.pop(0)
    assert "Action: inspect failed/in-progress runs" not in github_sweep._human(historical_only, now=now)
