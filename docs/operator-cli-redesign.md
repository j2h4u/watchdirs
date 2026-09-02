# Operator CLI redesign

This document defines the agent-operator surface after removing compatibility
and implementation-detail concerns from the primary disk-growth investigation
workflow.

## Goals

- Let an agent start a useful investigation with one command.
- Make defaults strong enough that arguments are used only for unusual windows
  or output bounds.
- Keep low-level diagnostics available as implementation building blocks until
  the high-level commands fully cover their signals.
- Do not expose database paths, socket wiring, fast/slow internals, or writer
  implementation details to the operator-agent.

## Command movement table

| Current surface | Operator task | Target surface | First change | Later cleanup |
|---|---|---|---|---|
| `investigate --fast --json` | Compact first-pass disk-growth triage | `investigate` | Make compact JSON the default shape; remove `--fast`, `--depth`, and required `--json` from operator help. | Fold richer trend details back only when they affect the next action. |
| `investigate --json` | Full trend analysis | `investigate` | Keep one investigation command; no public fast/full split. | Add burst metrics based on multiple snapshots, not baseline/current only. |
| `explain-path PATH` | Drill into a suspicious tree | `explain PATH` | Make JSON the default and make `investigate` recommend it with minimal argv. | Rename after `investigate` hard cut is proven. |
| `stats --json` | Service/index freshness and health | `status` | Keep current command for now. | Rename once README/help have one stable operator flow. |
| `df-vs-index` | Reconcile current filesystem pressure with indexed usage | `pressure` | Make JSON the default, keep diagnostic command, and surface a compact pressure summary from `investigate`. | Rename/simplify after pressure summary contract stabilizes. |
| `deleted-open-files` | Explain `df` usage not visible in directory entries | `open-deleted` | Make JSON the default; `investigate` should recommend it only when pressure has unexplained usage. | Rename after signal routing is stable. |
| `docker-enrichment --json` | Attribute Docker/containerd/BuildKit storage | `containers` | Keep diagnostic command; `investigate` should mention it only when top paths are under container storage. | Rename after enrichment signal is compact enough. |
| `timeline --json` | Show root/path size over time | `timeline` | Keep as a supporting drill-down command. | Add optional path argument if needed. |
| `report`, `diff` | Low-level historical comparisons | Advanced diagnostics | Stop advertising as the starting workflow. | Hide from main help or move under an advanced/admin namespace. |
| `top`, `snapshots`, `deleted` | Raw inspection/debugging | Advanced diagnostics | Stop advertising as normal investigation steps. | Keep only if a clear operator task remains. |
| `collect`, `prune`, `vacuum` | Maintenance writers | systemd/admin | Keep writer commands, but docs should prefer `systemctl start watchdirs-*.service` for installed hosts. | Consider admin namespace if operator help stays noisy. |

## Defaults

| Command | Default behavior |
|---|---|
| `watchdirs investigate` | JSON output, `since=14d`, bounded contributor count, burst-aware ranking, compact next actions. |
| `watchdirs explain-path PATH` | JSON output, `since=14d`, depth `3`, bounded rows. |
| `watchdirs timeline` | JSON output, `since=14d`, bounded points. |
| `watchdirs stats` | JSON output. |
| `watchdirs df-vs-index` | JSON output over latest indexed state. |
| `watchdirs deleted-open-files` | JSON output over current `/proc` evidence. |

Arguments should override defaults only when the agent has a concrete reason:
shorter/longer history, more rows, or deeper drill-down after an initial result
shows truncation.

## First implementation cut

- Make `watchdirs investigate` run successfully without arguments.
- Remove public `--fast`, `--depth`, and `--json` from `investigate`.
- Use one `investigate` JSON contract rather than separate fast/full payloads.
- Keep the output bounded by default.
- Emit next actions with only non-default arguments.
- Rank contributors with a compact burst signal so sudden material growth can
  outrank larger steady growth.
- Update README and tests around the new starting command.

## Deferred implementation

- Tune burst thresholds against more live incidents if the default ranking
  proves noisy.
- Rename `explain-path` to `explain`, `stats` to `status`,
  `df-vs-index` to `pressure`, `deleted-open-files` to `open-deleted`, and
  `docker-enrichment` to `containers`.
- Hide or move raw commands after the high-level replacements prove sufficient.
