from __future__ import annotations

from pathlib import Path


def test_trusted_pr_automerge_is_scoped_to_trusted_pull_requests(repo_root: Path) -> None:
    workflow = (repo_root / ".github" / "workflows" / "trusted-pr-automerge.yml").read_text(encoding="utf-8")

    assert "pull_request_target:" in workflow
    assert "branches: [main]" in workflow
    assert "pull-requests: write" in workflow
    assert "contents: write" in workflow
    assert "gh pr merge --auto --squash" in workflow

    # The privileged pull_request_target workflow must not run PR code.
    assert "actions/checkout" not in workflow
    assert "pull_request.head.sha" not in workflow

    # Trusted scope: same-repository PRs or Dependabot, not arbitrary forks.
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in workflow
    assert "github.event.pull_request.base.repo.full_name == github.repository" in workflow

    # Release PRs stay out of generic auto-merge policy.
    assert "!startsWith(github.event.pull_request.head.ref, 'release-please--')" in workflow
