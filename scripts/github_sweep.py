#!/usr/bin/env python3
"""Read-only GitHub control-plane sweep using the GitHub CLI."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
JsonValue = Any
_MAX_ERROR_LENGTH = 500
_TOKEN_PATTERN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,})\b")
_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)\b(authorization|access_token|token|client_secret)\b([=:]\s*)((?:Bearer\s+)?[^\s,;]+)"
)


def _subprocess_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _unavailable(error: str) -> dict[str, JsonValue]:
    redacted = _TOKEN_PATTERN.sub("[REDACTED]", error)
    redacted = _SECRET_VALUE_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    if len(redacted) > _MAX_ERROR_LENGTH:
        redacted = f"{redacted[: _MAX_ERROR_LENGTH - 3]}..."
    return {"available": False, "error": redacted}


def _run_json(command: list[str], runner: Runner) -> dict[str, JsonValue]:
    try:
        result = runner(command)
    except OSError as exc:
        return _unavailable(str(exc))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"gh exited with status {result.returncode}"
        return _unavailable(detail)
    try:
        return {"available": True, "data": json.loads(result.stdout)}
    except json.JSONDecodeError as exc:
        return _unavailable(f"invalid JSON from gh: {exc.msg}")


def _normalize_pages(data: JsonValue) -> JsonValue:
    if not isinstance(data, list) or not data:
        return data
    if all(isinstance(page, list) for page in data):
        return [item for page in data for item in page]
    if not all(isinstance(page, dict) for page in data):
        return data
    merged: dict[str, JsonValue] = {}
    for page in data:
        for key, value in page.items():
            if isinstance(value, list):
                merged.setdefault(key, [])
                if isinstance(merged[key], list):
                    merged[key].extend(value)
            else:
                merged[key] = value
    return merged


def _api(path: str, repo: str, runner: Runner, *, paginate: bool = False) -> dict[str, JsonValue]:
    command = ["gh", "api", path]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    result = _run_json(command, runner)
    if paginate and result["available"]:
        result["data"] = _normalize_pages(result["data"])
    return result


def _repo_selector(runner: Runner) -> tuple[str | None, dict[str, JsonValue] | None]:
    result = _run_json(["gh", "repo", "view", "--json", "nameWithOwner"], runner)
    if not result["available"]:
        return None, result
    payload = result["data"]
    if not isinstance(payload, dict) or not isinstance(payload.get("nameWithOwner"), str):
        return None, _unavailable("gh repo view returned no nameWithOwner")
    return payload["nameWithOwner"], None


def _pull_requests(repo: str, runner: Runner) -> dict[str, JsonValue]:
    result = _api(f"repos/{repo}/pulls?state=open&per_page=100", repo, runner, paginate=True)
    if not result["available"] or not isinstance(result["data"], list):
        return result

    pull_requests: list[dict[str, JsonValue]] = []
    for pull_request in result["data"]:
        if not isinstance(pull_request, dict):
            continue
        number = pull_request.get("number")
        head = pull_request.get("head")
        sha = head.get("sha") if isinstance(head, dict) else None
        reviews = (
            _api(f"repos/{repo}/pulls/{number}/reviews?per_page=100", repo, runner, paginate=True)
            if isinstance(number, int)
            else _unavailable("pull request number unavailable")
        )
        checks = (
            _api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100", repo, runner, paginate=True)
            if isinstance(sha, str)
            else _unavailable("pull request head SHA unavailable")
        )
        pull_requests.append({
            **pull_request,
            "reviews": reviews,
            "checks": checks,
            "review_state": _review_state(reviews),
            "check_state": _check_state(checks),
        })

    bots = [pull_request for pull_request in pull_requests if _is_bot(pull_request)]
    enji = [pull_request for pull_request in pull_requests if _author_login(pull_request).lower().find("enji") >= 0]
    return {
        "available": True,
        "data": {
            "items": pull_requests,
            "groups": {"bot_authored": bots, "enji_authored": enji},
        },
    }


def _author_login(pull_request: dict[str, JsonValue]) -> str:
    author = pull_request.get("user")
    return author.get("login", "") if isinstance(author, dict) and isinstance(author.get("login"), str) else ""


def _is_bot(pull_request: dict[str, JsonValue]) -> bool:
    author = pull_request.get("user")
    return isinstance(author, dict) and (
        author.get("type") == "Bot" or _author_login(pull_request).lower().endswith("[bot]")
    )


def _review_state(reviews: dict[str, JsonValue]) -> str:
    review_items = _items(reviews)
    states = {review.get("state") for review in review_items}
    if "CHANGES_REQUESTED" in states:
        return "changes_requested"
    if "APPROVED" in states:
        return "approved"
    return "review_required"


def _check_state(checks: dict[str, JsonValue]) -> str:
    check_items = _items(checks)
    if not checks["available"]:
        return "unavailable"
    if any(
        check.get("conclusion") in {"failure", "timed_out", "cancelled", "action_required"} for check in check_items
    ):
        return "failed"
    if any(check.get("status") != "completed" for check in check_items):
        return "in_progress"
    return "passed"


def _default_branch_protection(repo: str, branch: str, runner: Runner) -> dict[str, JsonValue]:
    protection = _api(f"repos/{repo}/branches/{branch}/protection", repo, runner)
    if protection["available"]:
        return {"available": True, "data": {"protected": True, "rules": protection["data"]}}
    if "Branch not protected" in str(protection.get("error", "")):
        return {"available": True, "data": {"protected": False}}
    return protection


def sweep(repo: str | None = None, *, runner: Runner | None = None) -> dict[str, JsonValue]:
    """Collect all GitHub sections independently, without mutating GitHub."""
    run = runner or _subprocess_runner
    selector_error: dict[str, JsonValue] | None = None
    if repo is None:
        repo, selector_error = _repo_selector(run)
        if repo is None:
            return {"repo": None, "sections": {}, "errors": {"repository": selector_error}}

    repository = _api(f"repos/{repo}", repo, run)
    repository_data = repository.get("data")
    security_data = repository_data.get("security_and_analysis") if isinstance(repository_data, dict) else None
    security_and_analysis = (
        {"available": True, "data": security_data}
        if isinstance(security_data, dict)
        else _unavailable("security_and_analysis missing from repository response")
    )
    sections: dict[str, dict[str, JsonValue]] = {
        "repository": repository,
        "security_and_analysis": security_and_analysis,
        "automated_security_fixes": _api(f"repos/{repo}/automated-security-fixes", repo, run),
        "pull_requests": _pull_requests(repo, run),
        "workflows": _api(f"repos/{repo}/actions/workflows?per_page=100", repo, run, paginate=True),
        "workflow_runs": _api(f"repos/{repo}/actions/runs?per_page=100", repo, run, paginate=True),
        "code_scanning_alerts": _api(f"repos/{repo}/code-scanning/alerts?per_page=100", repo, run, paginate=True),
        "dependabot_alerts": _api(f"repos/{repo}/dependabot/alerts?per_page=100", repo, run, paginate=True),
        "secret_scanning_alerts": _api(f"repos/{repo}/secret-scanning/alerts?per_page=100", repo, run, paginate=True),
        "rulesets": _api(f"repos/{repo}/rulesets?per_page=100", repo, run, paginate=True),
        "releases": _api(f"repos/{repo}/releases?per_page=100", repo, run, paginate=True),
        "deployments": _api(f"repos/{repo}/deployments?per_page=100", repo, run, paginate=True),
    }

    default_branch = repository_data.get("default_branch") if isinstance(repository_data, dict) else None
    branch_key = "default_branch_protection"
    if isinstance(default_branch, str) and default_branch:
        sections[branch_key] = _default_branch_protection(repo, default_branch, run)
    else:
        sections[branch_key] = _unavailable("default branch unavailable")

    return {
        "repo": repo,
        "sections": sections,
        "errors": {} if selector_error is None else {"repository": selector_error},
    }


def _items(section: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    data = section.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("items", "workflows", "workflow_runs", "alerts", "rulesets", "releases", "deployments"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def main(argv: Sequence[str] | None = None, *, runner: Runner | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", help="OWNER/REPO; defaults to gh repo view")
    parser.add_argument("--json", action="store_true", help="emit the complete JSON envelope (default)")
    args = parser.parse_args(argv)
    payload = sweep(args.repo, runner=runner)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
