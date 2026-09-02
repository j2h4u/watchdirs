# Best Practices

This document holds reusable engineering rationale for `watchdirs`. Keep
`AGENTS.md` short and operational; put longer explanations here.

## Delivery model

- Work through pull requests by default. Direct pushes to `main` are reserved
  for an explicit user request or an emergency fix with follow-up cleanup.
- Local and CI verification must share the same command surface. CI should call
  `just` recipes instead of reimplementing project checks in workflow YAML.
- Keep Docker-specific template practices out of this repository unless
  `watchdirs` actually grows a Docker packaging/runtime surface.

## Python QA gates

- `just check` is the static gate: formatting, Ruff, preview
  complexity/refactor checks, lockfile sync, suppression budgets, production
  and script type checks, import-linter contracts, Tach module boundaries,
  Deptry dependency hygiene, SQLite integrity smoke, GitHub Actions lint,
  supply-chain pin checks, compile checks, packaging smoke, dead-code checks,
  and systemd unit validation.
- `just unit` is the behavior gate.
- `just coverage` is the coverage and hard CRAP threshold gate.
- `just deps-audit` audits the locked dependency set for known
  vulnerabilities.
- `just verify` is the full local gate before claiming release-candidate
  confidence.

Do not weaken, skip, or locally suppress gates to make a change pass. If a gate
is wrong for this project, change the gate deliberately and explain why in the
same change.

## Import boundaries and module graph

Use import-linter and Tach together:

- import-linter keeps named semantic contracts readable, such as “collection
  must not import reporting”;
- Tach keeps the whole module dependency graph explicit and catches stale or
  implicit dependency drift with `exact = true`.

The current Tach graph intentionally describes the existing module shape. It is
not a demand to refactor public `__init__.py` re-exports or split `cli.py`
inside this hardening pass.

## Dependencies and supply chain

- Use `uv` only and keep `uv.lock` current.
- Run `uv lock --check` in local and CI gates.
- Keep GitHub Actions pinned to a full version or commit SHA; major-only tags
  such as `@v2` are treated as floating by `scripts/check_supply_chain_pins.py`.
- Use `persist-credentials: false` for checkout steps unless a job
  intentionally writes to the repository.
- Keep Dependency Submission enabled so GitHub’s dependency graph follows
  `uv.lock`.
- Use Dependency Review on pull requests and OSV Scanner on a scheduled/manual
  lane as additional supply-chain signals.

## Pull request release contract

PR titles and ordinary commit subjects should be valid Conventional Commits so
release automation can produce useful changelog entries. Multi-commit PRs need
a `BEGIN_COMMIT_OVERRIDE` / `END_COMMIT_OVERRIDE` block in the PR body when the
individual commits would squash into an unhelpful single release note.
