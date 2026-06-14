# Phase 03: Pressure Gap Diagnostics - Research

**Researched:** 2026-06-14
**Domain:** Local Python CLI diagnostics that reconcile persisted SQLite directory snapshots with live Linux filesystem, process, and Docker evidence on `senbonzakura`. [VERIFIED: README.md + .planning/PROJECT.md + pyproject.toml + src/watchdirs/db/schema.sql + src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://docs.docker.com/reference/cli/docker/system/df/]
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
Verbatim from `03-CONTEXT.md`. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

### `df` vs Indexed Evidence
- **D-01:** Treat `df` as a filesystem-level control total, not as a source of per-directory attribution.
- **D-02:** `df-vs-index` should compare filesystem/storage-domain usage against what `watchdirs` indexed from visible directory entries and persisted snapshot metadata.
- **D-03:** If indexed directories do not explain the filesystem-level usage, report an unattributed remainder instead of pretending the directory index is complete.
- **D-04:** The report should keep the primary answer simple: "visible indexed directories explain X; filesystem usage shows Y; remainder Z is not attributed by the index."

### Unattributed Remainder Output
- **D-05:** When a mismatch is detected, output must include fact + likely reasons + verification commands.
- **D-06:** Likely reasons should stay concrete and bounded: deleted-open files, skipped mounts or partial scans, Docker/containerd storage, and filesystem metadata/reserved/accounting effects.
- **D-07:** Commands should be suggested as checks, not executed cleanup actions. Examples: `lsof +L1`, `docker system df -v`, `docker builder du`, and existing `watchdirs` grouping/drill-down commands.

### Deleted-Open Files
- **D-08:** Deleted-open diagnostics should report culprit entries and cautious action hints.
- **D-09:** Include process name, PID, size, path if available, filesystem/storage-domain if resolvable, and an action hint such as "likely restart service X after checking" rather than "kill this process."
- **D-10:** Deleted-open files remain separate diagnostics, not fake directory rows in the snapshot index.

### Docker and Containerd Evidence
- **D-11:** Docker/containerd evidence should be grouped by category with commands to verify: total/reclaimable, build cache, images, containers, volumes, and containerd-specific storage when detectable.
- **D-12:** Docker cache is still files, but `watchdirs` may only see it as growth under storage paths such as `/var/lib/docker` or `/var/lib/containerd`. Docker CLI enrichment is for reclaimable-vs-active meaning, not for replacing filesystem indexing.
- **D-13:** The tool must not automatically prune Docker or containerd data in Phase 3.

### Final Summary
- **D-14:** The final answer should be a compact summary plus prioritized next checks.
- **D-15:** Avoid hundreds of lines of recommendations. The output must be short enough that an LLM agent can scan it without getting lost.
- **D-16:** Prefer top-N sections and clear truncation fields over exhaustive listings. The planner should define strict defaults and JSON fields that say when output was truncated.
- **D-17:** Do not make confident operational recommendations such as "upgrade disk" or "safe to delete" from Phase 3 alone. Provide next checks; keep final cleanup/capacity judgment cautious.

### the agent's Discretion
Verbatim from `03-CONTEXT.md`. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

Technical implementation details are delegated to research/planning. Downstream agents should use primary docs or expert review for Linux accounting details (`statvfs`, deleted-open files via `/proc`/`lsof`, Docker CLI output stability) and choose conservative, testable approaches.

### Deferred Ideas (OUT OF SCOPE)
Verbatim from `03-CONTEXT.md`. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

- Automatic cleanup commands such as Docker prune or service restarts are out of Phase 3.
- Scheduled collection, retention, pruning, vacuum, and strong `nice`/`ionice` behavior remain Phase 4.
- Long-term trend forecasting, broad capacity-planning dashboard behavior, and BI-style reports remain out of scope for v1 unless a later phase explicitly adds them.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIAG-01 | Agent can run `watchdirs df-vs-index --json` to compare filesystem usage against indexed directory totals. [VERIFIED: .planning/REQUIREMENTS.md] | Reuse persisted `directory_sizes` plus `snapshot_mounts`, aggregate visible `disk_bytes` by storage-domain, and compare that to live `os.statvfs()`/`df`-style totals with explicit snapshot timestamps and an unattributed remainder. [VERIFIED: src/watchdirs/reporting/queries.py + src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md][CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://man7.org/linux/man-pages/man1/df.1.html] |
| DIAG-02 | Agent can run a deleted-open-files diagnostic that reports files still held open after deletion. [VERIFIED: .planning/REQUIREMENTS.md] | Use a dedicated live probe adapter that prefers machine-readable `lsof +L1 -F0 -nP` when available and falls back to `/proc/<pid>/fd` inspection when `lsof` is missing or too restricted. [VERIFIED: /usr/bin/lsof + man lsof | col -b | rg -n \"-F|\\+L1\" + /proc/self/fd-present][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html][CITED: https://man7.org/linux/man-pages/man2/unlink.2.html] |
| DIAG-03 | Reports call out deleted-open-file suspicion when `df` usage and indexed totals diverge materially. [VERIFIED: .planning/REQUIREMENTS.md] | Keep full deleted-open evidence in a separate command, but add a bounded `diagnostic_hints` section to `report`/`df-vs-index` when unattributed remainder exceeds a planner-chosen threshold. The exact threshold is not locked yet. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + src/watchdirs/reporting/render.py][ASSUMED] |
| DIAG-04 | Agent can collect Docker/containerd enrichment for relevant growth paths using Docker CLI evidence when available. [VERIFIED: .planning/REQUIREMENTS.md] | Use Docker CLI JSON/NDJSON output (`docker system df --format json` and `docker buildx du --format json`, with `docker builder du` alias detection) and normalize it into reclaimable-vs-active categories without scanning `/var/lib/docker` heuristically. [VERIFIED: docker --version + docker system df --format json + docker builder du --help + docker buildx du --verbose][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] |
| DIAG-05 | Agent can summarize pressure and growth by attached disk or disk subsystem well enough to support capacity decisions such as upgrade, data migration, or repurposing an older disk for swap, temp files, and caches. [VERIFIED: .planning/REQUIREMENTS.md] | Build a compact top-N storage-domain summary from persisted grouping plus live filesystem totals and optional Docker category totals, but keep recommendations at the level of evidence and next checks, not prescriptive cleanup or hardware action. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py][CITED: https://man7.org/linux/man-pages/man1/df.1.html][CITED: https://docs.docker.com/reference/cli/docker/system/df/] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Target `senbonzakura` first; the planner should optimize the concrete host incident workflow, not a generic storage dashboard. [VERIFIED: AGENTS.md]
- Keep SQLite as the v1 store and reuse persisted snapshot evidence instead of introducing a service or a second operational database. [VERIFIED: AGENTS.md + .planning/PROJECT.md]
- Preserve the directory-aggregate data model; deleted-open and Docker diagnostics must stay separate from `directory_sizes`. [VERIFIED: AGENTS.md + README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- Do not follow symlinks or descend into virtual, transient, or overlay filesystems during collection assumptions; Phase 3 must explain gaps created by those safety rules instead of hiding them. [VERIFIED: AGENTS.md + .planning/PROJECT.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- Keep `disk_bytes` primary and `apparent_bytes` explicitly labeled. [VERIFIED: AGENTS.md + README.md + src/watchdirs/models.py]
- Keep JSON first-class and text output terse. [VERIFIED: AGENTS.md + src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- Do not make direct repo edits outside the GSD workflow in later execution work. [VERIFIED: AGENTS.md]

## Summary

Phase 3 should remain stdlib-first and should not blur the line between persisted snapshot evidence and live host probes. The existing repo already has the right seams for this: CLI handlers in `src/watchdirs/cli.py`, dataclass contracts in `src/watchdirs/models.py`, persisted grouping/query logic in `src/watchdirs/reporting/queries.py`, and stable JSON/text renderers in `src/watchdirs/reporting/render.py`. The missing capability is a new diagnostics layer that consumes those seams without turning `report` into a broad live rescan. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/models.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

The core design choice is to make `df-vs-index` a reconciliation command, not another report flavor. `df` is only a filesystem control total, and the index only explains visible directory entries that were scanned and persisted. The planner should therefore implement explicit storage-domain aggregation, explicit snapshot-age fields, and explicit `unattributed_bytes`/`unattributed_ratio` fields rather than trying to force a full attribution story. That matches both the repo’s product intent and Linux accounting semantics. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + .planning/REQUIREMENTS.md][CITED: https://man7.org/linux/man-pages/man1/df.1.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://docs.python.org/3/library/os.html]

Deleted-open and Docker evidence should be independent, bounded probe adapters. Deleted-open files are not directory growth and should never be synthesized into snapshot rows. Docker growth is often visible under `/var/lib/docker` or `/var/lib/containerd`, but only the Docker CLI can tell the agent whether the bytes are active or reclaimable. Both adapters should return compact top-N evidence plus verification commands and truncation metadata, and `report` should only surface suspicion/hints, not full live probe output. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + docker system df --format json + docker buildx du --verbose + lsof +L1 -nP][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/]

**Primary recommendation:** Add a new `watchdirs.diagnostics` package with separate `df_index`, `deleted_open`, `docker`, and `summary` modules; keep SQLite aggregation in `reporting/queries.py`, keep rendering in `reporting/render.py`, and extend `report` only with compact suspicion hints and next-check commands. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

## Non-Goals / Out of Scope

- No automatic cleanup, prune, restart, or kill actions belong in Phase 3. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + README.md]
- No synthetic `directory_sizes` rows should be created for deleted-open files, Docker categories, or filesystem metadata. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- No broad live filesystem rescan should be added to existing report commands; Phase 2’s persisted-evidence boundary still applies. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-SECURITY.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- No block-device topology mapper, SMART parser, or long-horizon capacity dashboard belongs in this phase. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- No Docker dependency should be introduced for the core `df-vs-index` or deleted-open workflows; Docker enrichment must degrade cleanly when Docker is absent or inaccessible. [VERIFIED: .planning/REQUIREMENTS.md + docker --version][ASSUMED]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Filesystem control totals (`size`, `used`, `free`, `avail`) | Host / OS | Local CLI / Backend | `df`-style totals come from live filesystem state, not SQLite. The CLI only normalizes and labels them. [CITED: https://man7.org/linux/man-pages/man1/df.1.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://docs.python.org/3/library/os.html] |
| Indexed visible totals by storage-domain | Database / Storage | Local CLI / Backend | Visible totals should be aggregated from persisted `directory_sizes` plus `snapshot_mounts`, because Phase 2 already made grouping historical and durable. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/reporting/queries.py + .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] |
| Deleted-open culprit discovery | Host / OS | Local CLI / Backend | The evidence lives in process/file-descriptor state, so it must come from `lsof` or `/proc`, then be normalized into repo dataclasses. [VERIFIED: /usr/bin/lsof + /proc/self/fd-present][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html] |
| Docker reclaimable-vs-active enrichment | Host / OS | Local CLI / Backend | Docker category ownership and reclaimability come from the Docker daemon/CLI, not from directory traversal. [VERIFIED: docker info --format '{{.ServerVersion}}' + docker system df --format json][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] |
| Compact top-N summary and truncation | Local CLI / Backend | Database / Storage | Prioritization, truncation, and next-check text are product-layer concerns built on top of persisted rows and live probe results. [VERIFIED: src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`argparse`, `json`, `os`, `sqlite3`, `subprocess`) | `>=3.11` required, `3.13.5` on this host. [VERIFIED: pyproject.toml + python3 --version] | Command parsing, JSON envelopes, `statvfs`, SQLite access, and fixed-argv probe execution. [CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/os.html][CITED: https://docs.python.org/3/library/sqlite3.html][CITED: https://docs.python.org/3/library/subprocess.html] | Matches the current repo and avoids new runtime dependencies. [VERIFIED: pyproject.toml + src/watchdirs/cli.py] |
| Existing `watchdirs` SQLite schema and reporting seams | Current repo state. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py] | Historical snapshot selection, grouping, warnings, and stable render contracts. | Phase 3 should extend proven Phase 2 behavior instead of creating a parallel query/render stack. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] |
| SQLite runtime via stdlib | `3.46.1` in the current Python runtime. [VERIFIED: python3 -c 'import sqlite3; print(sqlite3.sqlite_version)' ] | Storage-domain aggregation over persisted snapshot rows. [CITED: https://docs.python.org/3/library/sqlite3.html] | Already the project’s v1 store; no new persistence technology is justified here. [VERIFIED: AGENTS.md + .planning/PROJECT.md + src/watchdirs/db/schema.sql] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `lsof` | `4.99.4` on this host. [VERIFIED: lsof -v | head -2] | Preferred deleted-open detection when available because it already understands unlinked-open semantics and field output for parsers. [VERIFIED: man lsof | col -b | rg -n \"-F|\\+L1\"][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html] | Use as the primary DIAG-02 collector; fall back to `/proc` only when unavailable or too restricted. [VERIFIED: /usr/bin/lsof][ASSUMED] |
| `/proc/<pid>/fd` | Linux procfs on this host. [VERIFIED: /proc/self/fd-present][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html] | Deleted-open fallback and verification path. | Use when `lsof` is missing, returns insufficient fields, or permission restrictions still allow direct procfs inspection. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html][ASSUMED] |
| Docker CLI and daemon | `29.5.3` on this host; daemon reachable. [VERIFIED: docker --version + docker info --format '{{.ServerVersion}}'] | Reclaimable-vs-active category evidence for images, containers, volumes, and build cache. [CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] | Use only for DIAG-04 and DIAG-05 when Docker paths matter or when the operator requests enrichment. [VERIFIED: .planning/REQUIREMENTS.md + README.md] |
| `pytest` | `8.3.5` on this host. [VERIFIED: pytest --version] | Unit and CLI contract coverage for new diagnostics modules. | Use for all Phase 3 automated validation; the existing repo already runs under pytest without extra setup. [VERIFIED: pyproject.toml + pytest -q --collect-only tests/test_cli_report_commands.py tests/test_reporting_queries.py tests/test_grouping.py] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `lsof +L1 -F0 -nP` as the primary deleted-open collector | Pure `/proc/*/fd` scanning | `/proc` is dependency-free and Linux-native, but `lsof` already handles unlinked-open selection and machine-readable fields. The host already has `lsof`, so `/proc` is better as fallback than as the first path. [VERIFIED: /usr/bin/lsof + man lsof | col -b | rg -n \"-F|\\+L1\" + /proc/self/fd-present][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html] |
| Docker CLI JSON/NDJSON output | Parsing `docker system df -v` or `docker buildx du --verbose` pretty tables | The pretty tables are useful for humans but brittle for parsers. Current docs and current host behavior support structured JSON output for both commands. [VERIFIED: docker system df --format json + docker buildx du --help][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] |
| Live `statvfs`/`df` totals plus persisted visible totals | Trying to derive filesystem truth from indexed directories alone | Summed directory rows cannot represent deleted-open files, reserved blocks, or metadata-only usage; `df` remains the control total by design. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + README.md][CITED: https://man7.org/linux/man-pages/man1/df.1.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html] |
| Separate diagnostics package (`watchdirs.diagnostics`) | Mixing live probe logic into `reporting/queries.py` and `render.py` directly | A separate package keeps persisted-SQL queries isolated from subprocess/procfs behavior and makes DIAG-02/04 easier to test with fakes. [VERIFIED: src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] |

**Installation:**
```bash
# No new runtime package installs are recommended for Phase 3.
./watchdirs --help
python3 -m pytest -q
```
[VERIFIED: pyproject.toml + ./watchdirs present + pytest --version]

**Version verification:** `python3`, `pytest`, `lsof`, `docker`, and `df` were verified on this host during research. [VERIFIED: python3 --version + pytest --version + lsof -v | head -2 + docker --version + df --version | head -1]

## Package Legitimacy Audit

Phase 3 does not require new external package installs on the recommended path, so the package-legitimacy gate is not triggered. [VERIFIED: pyproject.toml + src/watchdirs/cli.py + src/watchdirs/reporting/queries.py]

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| none | — | — | — | — | — | No new external packages recommended for this phase. [VERIFIED: pyproject.toml] |

**Packages removed due to [SLOP] verdict:** none. [VERIFIED: pyproject.toml]
**Packages flagged as suspicious [SUS]:** none. [VERIFIED: pyproject.toml]

## JSON Contract Ideas

The existing CLI already uses stable top-level `ok`/`command` envelopes and `warnings` arrays; Phase 3 should reuse that contract style instead of inventing a one-off diagnostics format. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/render.py]

### `df-vs-index`

```json
{
  "ok": true,
  "command": "df-vs-index",
  "snapshot_selector": "latest",
  "generated_at": "2026-06-14T08:00:00Z",
  "filesystems": [
    {
      "storage_domain": {
        "kind": "storage-domain",
        "key": "259:3|/|ext4|/dev/nvme0n1p2",
        "mount_point": "/",
        "filesystem_type": "ext4",
        "mount_source": "/dev/nvme0n1p2",
        "major_minor": "259:3",
        "root": "/"
      },
      "snapshot_ids": [101, 104],
      "snapshot_finished_at_min": "2026-06-14T06:00:01Z",
      "snapshot_finished_at_max": "2026-06-14T06:00:03Z",
      "snapshot_age_seconds_max": 7200,
      "df_bytes": {
        "size": 0,
        "used": 0,
        "free_total": 0,
        "avail_unprivileged": 0
      },
      "indexed_visible_disk_bytes": 0,
      "indexed_visible_path_count": 0,
      "partial_snapshot_count": 0,
      "unknown_mount_row_count": 0,
      "unattributed_bytes": 0,
      "unattributed_ratio": 0.0,
      "likely_reasons": [
        "deleted_open_files",
        "docker_or_containerd",
        "reserved_or_metadata"
      ],
      "verification_commands": [
        "watchdirs report --since 24h --group-by storage-domain --json",
        "watchdirs deleted-open-files --json",
        "watchdirs docker-enrichment --json"
      ],
      "truncated": false
    }
  ],
  "warnings": [],
  "summary": {
    "top_unattributed_storage_domains": [
      "259:3|/|ext4|/dev/nvme0n1p2"
    ],
    "truncated_sections": false
  }
}
```
[VERIFIED: src/watchdirs/reporting/render.py + src/watchdirs/reporting/queries.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md][CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://man7.org/linux/man-pages/man1/df.1.html]

### `deleted-open-files`

```json
{
  "ok": true,
  "command": "deleted-open-files",
  "generated_at": "2026-06-14T08:00:00Z",
  "totals": {
    "culprit_count": 3,
    "estimated_size_bytes": 0,
    "permission_denied_count": 0,
    "truncated": false
  },
  "culprits": [
    {
      "pid": 1234,
      "process_name": "python3",
      "fd": "7w",
      "deleted_path": "/opt/app/logs/current.jsonl (deleted)",
      "size_bytes": 0,
      "storage_domain": {
        "kind": "mount",
        "key": "/"
      },
      "action_hint": "check the owning service and confirm log rotation before restarting it"
    }
  ],
  "verification_commands": [
    "lsof +L1 -nP",
    "readlink /proc/1234/fd/7"
  ],
  "warnings": []
}
```
[VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + README.md + /usr/bin/lsof + /proc/self/fd-present][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html][CITED: https://man7.org/linux/man-pages/man2/unlink.2.html]

### `docker-enrichment`

```json
{
  "ok": true,
  "command": "docker-enrichment",
  "docker_available": true,
  "docker_server_version": "29.5.3",
  "relevant_index_paths": [
    "/var/lib/docker",
    "/var/lib/containerd"
  ],
  "system_df": {
    "rows": [
      {
        "type": "Images",
        "size": "19.23GB",
        "active": "18",
        "reclaimable": "0B (0%)"
      }
    ],
    "truncated": false
  },
  "build_cache": {
    "rows": [],
    "total_reclaimable_bytes": 0,
    "total_bytes": 0,
    "truncated": false
  },
  "verification_commands": [
    "docker system df --format json",
    "docker buildx du --format json"
  ],
  "warnings": []
}
```
[VERIFIED: docker system df --format json + docker buildx du --verbose + docker builder du --help][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/]

### Compact Summary Envelope

```json
{
  "sections": [
    {
      "kind": "filesystem-mismatch",
      "title": "root filesystem has 14.2GB unattributed usage",
      "priority": 1,
      "facts": [
        "indexed visible directories explain 132.0GB",
        "filesystem used is 146.2GB",
        "unattributed remainder is 14.2GB"
      ],
      "likely_reasons": [
        "deleted_open_files",
        "docker_or_containerd",
        "reserved_or_metadata"
      ],
      "next_checks": [
        "watchdirs deleted-open-files --json",
        "watchdirs docker-enrichment --json"
      ],
      "truncated": false
    }
  ],
  "limits": {
    "max_sections": 4,
    "max_items_per_section": 5
  },
  "truncated": false
}
```
[VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + src/watchdirs/reporting/render.py]

## Architecture Patterns

### System Architecture Diagram

```text
CLI command
  -> selector / scope parser
     -> latest usable snapshots per root from SQLite
     -> optional group-by or path scope
  -> persisted evidence layer
     -> directory_sizes aggregation by storage-domain
     -> snapshot_mounts lookup for domain labels
  -> live probe layer
     -> statvfs / df totals
     -> deleted-open collector (lsof primary, /proc fallback)
     -> Docker collector (system df + buildx du)
  -> diagnostic normalizer
     -> visible indexed totals
     -> filesystem totals
     -> unattributed remainder
     -> culprit / category summaries
  -> compact summary
     -> fact + likely reasons + verification commands
     -> top-N lists + truncation flags
  -> renderer
     -> JSON first
     -> terse labeled text second
```
[VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + src/watchdirs/db/schema.sql + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/os.html][CITED: https://docs.docker.com/reference/cli/docker/system/df/]

### Recommended Project Structure
```text
src/
└── watchdirs/
    ├── cli.py                         # add df-vs-index / deleted-open-files / docker-enrichment
    ├── models.py                      # add diagnostic dataclasses and summary rows
    ├── diagnostics/
    │   ├── df_index.py                # statvfs + indexed-total reconciliation
    │   ├── deleted_open.py            # lsof/procfs adapters and culprit normalization
    │   ├── docker.py                  # docker system df / buildx du adapters
    │   └── summary.py                 # top-N prioritization and truncation metadata
    ├── reporting/
    │   ├── queries.py                 # keep persisted SQLite aggregations here
    │   └── render.py                  # extend payload/text renderers for diagnostics
    └── db/
        └── schema.sql                 # no new table required on the recommended path

tests/
├── test_cli_report_commands.py        # extend report hints / compact output coverage
├── test_diagnostics_df_index.py       # new statvfs vs indexed-total fixtures
├── test_diagnostics_deleted_open.py   # new lsof/proc parser coverage
├── test_diagnostics_docker.py         # new Docker NDJSON normalization coverage
└── test_diagnostics_summary.py        # new top-N truncation and prioritization coverage
```
[VERIFIED: src/watchdirs/cli.py + src/watchdirs/models.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + src/watchdirs/db/schema.sql + tests]

### Pattern 1: Persisted Evidence First, Live Probes Second
**What:** Compute visible indexed totals from SQLite first, then attach live probe evidence as a second step. [VERIFIED: src/watchdirs/reporting/queries.py + src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-SECURITY.md]
**When to use:** `df-vs-index`, DIAG-05 summaries, and any `report` hint that references filesystem mismatch. [VERIFIED: .planning/REQUIREMENTS.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Example:**
```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class FilesystemGap:
    storage_domain_key: str
    indexed_visible_disk_bytes: int
    filesystem_used_bytes: int
    unattributed_bytes: int


def reconcile_domain(indexed_visible_disk_bytes: int, filesystem_used_bytes: int) -> FilesystemGap:
    return FilesystemGap(
        storage_domain_key="259:3|/|ext4|/dev/nvme0n1p2",
        indexed_visible_disk_bytes=indexed_visible_disk_bytes,
        filesystem_used_bytes=filesystem_used_bytes,
        unattributed_bytes=filesystem_used_bytes - indexed_visible_disk_bytes,
    )
```
```python
# Source: repo pattern adapted from existing dataclass-first report models and statvfs docs
# src/watchdirs/models.py
# https://docs.python.org/3/library/os.html
```

### Pattern 2: Fixed-Argv Probe Adapters
**What:** Wrap every host probe in a fixed argv list and return structured rows plus warnings, never raw shell strings. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/render.py][CITED: https://docs.python.org/3/library/subprocess.html]
**When to use:** `lsof`, Docker CLI, and any optional `df` verification command run by the program itself. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Example:**
```python
import json
import subprocess


def run_docker_system_df() -> list[dict[str, object]]:
    proc = subprocess.run(
        ["docker", "system", "df", "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return rows
```
```python
# Source: Python subprocess docs and Docker CLI format docs
# https://docs.python.org/3/library/subprocess.html
# https://docs.docker.com/reference/cli/docker/system/df/
```

### Pattern 3: Compact Diagnostic Hints, Not Full Inline Dumps
**What:** Keep the primary `report` payload small by embedding only suspicion hints and next checks, while full deleted-open/Docker evidence stays in dedicated commands. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md + src/watchdirs/reporting/render.py]
**When to use:** DIAG-03 and the final top-level agent-facing summary. [VERIFIED: .planning/REQUIREMENTS.md]
**Example:**
```json
{
  "diagnostic_hints": [
    {
      "code": "deleted_open_file_suspected",
      "storage_domain_key": "259:3|/|ext4|/dev/nvme0n1p2",
      "unattributed_bytes": 15204352000,
      "next_checks": [
        "watchdirs deleted-open-files --json",
        "lsof +L1 -nP"
      ]
    }
  ]
}
```
```json
// Source: phase context plus existing JSON-first render conventions
// .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md
// src/watchdirs/reporting/render.py
```

### Anti-Patterns to Avoid
- **Fake directory attribution:** Do not invent directory rows for deleted-open files or Docker categories. Show explicit remainder instead. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- **Live broad rescan during report:** Do not call the scanner from `report`/`df-vs-index`; only cheap live probes are acceptable. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-SECURITY.md]
- **Table-text-only Docker parsing:** Do not depend on human table spacing when current Docker CLI already exposes structured output. [VERIFIED: docker system df --format json + docker buildx du --help][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/]
- **Unbounded culprit dumps:** Do not stream every process, every mount, or every Docker record by default. Keep strict defaults and truncation metadata. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- **Operational advice that sounds final:** Do not say “safe to prune” or “upgrade disk now” from Phase 3 alone. Keep to evidence and cautious next checks. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Filesystem control totals | A custom recursive sum treated as a substitute for `df` | `os.statvfs()` and `df` semantics | Directory sums cannot account for reserved blocks, metadata, or deleted-open files. [CITED: https://docs.python.org/3/library/os.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://man7.org/linux/man-pages/man1/df.1.html] |
| Deleted-open detection | Heuristics based only on deleted snapshot rows or path absence | `lsof +L1` and `/proc/<pid>/fd` evidence | Deleted-open usage persists after unlink and is invisible to normal path traversal. [CITED: https://man7.org/linux/man-pages/man2/unlink.2.html][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html] |
| Docker reclaimability inference | Guessing from `/var/lib/docker` subtree names alone | `docker system df` and `docker buildx du` | The Docker CLI exposes active/reclaimable category semantics that the filesystem layout alone does not. [CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] |
| Machine parsing of host tools | `shell=True` string execution and brittle whitespace slicing | Fixed-argv subprocess calls and JSON/field output when available | This keeps probes safer, more testable, and easier to fake in unit tests. [CITED: https://docs.python.org/3/library/subprocess.html][VERIFIED: man lsof | col -b | rg -n \"-F\"] |

**Key insight:** The hard part of this phase is not finding more bytes; it is preserving evidentiary boundaries so the agent can say which bytes are indexed, which bytes are only known at filesystem/process/Docker scope, and which bytes remain unattributed. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]

## Exact Risk Points

| Risk | Failure Mode | Required Control | Test Hook |
|------|--------------|------------------|-----------|
| Snapshot age skew | Live `df` totals are compared to stale snapshots and produce a false remainder. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Emit snapshot ids, finished-at timestamps, and `snapshot_age_seconds_max` in every `df-vs-index` section. [VERIFIED: src/watchdirs/reporting/render.py][ASSUMED] | Fixture with old latest snapshot and current live totals must raise a staleness warning instead of a clean mismatch verdict. [ASSUMED] |
| Cross-root same-filesystem aggregation errors | Multiple roots on the same storage-domain are double-counted or kept separate incorrectly. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] | Aggregate by persisted storage-domain key, not by root path alone. [VERIFIED: src/watchdirs/reporting/queries.py + src/watchdirs/db/schema.sql] | Seed two roots on one storage-domain and assert one combined filesystem section. [ASSUMED] |
| Partial or unknown-mount evidence | Remainder is overstated because partial snapshots or unmatched mount prefixes are ignored. [VERIFIED: src/watchdirs/reporting/queries.py + src/watchdirs/cli.py] | Carry `partial_snapshot_count`, `unknown_mount_row_count`, and warnings into the diagnostic payload. [VERIFIED: src/watchdirs/reporting/render.py][ASSUMED] | Reuse partial/unknown-mount fixtures and assert the mismatch is downgraded with warnings. [ASSUMED] |
| `lsof` noisy stderr | Diagnostics fail because `lsof` warns about overlay or tracefs even when it exits successfully. [VERIFIED: lsof +L1 -nP] | Treat stderr warnings as warning records, not automatic hard errors. [VERIFIED: lsof +L1 -nP][ASSUMED] | Fake `lsof` stderr plus zero exit status must preserve results and warnings. [ASSUMED] |
| Docker output shape drift | Parser assumes one JSON document but current CLI emits one JSON object per line. [VERIFIED: docker system df --format json][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] | Normalize line-delimited JSON and accept empty output from `buildx du` as an empty record set when exit status is zero. [VERIFIED: docker system df --format json + docker buildx du --verbose][ASSUMED] | Unit tests with NDJSON, blank output, and one malformed line. [ASSUMED] |
| Output explosion | Hundreds of culprit rows or Docker records overwhelm the agent. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Hard defaults for top-N rows per section plus explicit `truncated` flags. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Summary tests must prove deterministic truncation metadata. [ASSUMED] |
| Unsafe operational tone | Tool output sounds like an action approval rather than a cautious diagnostic. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Restrict text to facts, likely reasons, and verification commands. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Snapshot golden-text tests should reject verbs like `kill`, `prune`, or `safe`. [ASSUMED] |

## Common Pitfalls

### Pitfall 1: Treating Indexed Directory Totals as Filesystem Truth
**What goes wrong:** The implementation reports “indexed totals match pressure” even when deleted-open files or reserved blocks still explain a gap. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Why it happens:** Indexed rows only represent visible directory entries that were scanned and persisted. `df` measures filesystem space, not path ownership. [CITED: https://man7.org/linux/man-pages/man1/df.1.html][CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html]
**How to avoid:** Always compute and display an explicit `unattributed_bytes` remainder instead of forcing attribution. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Warning signs:** Clean-looking totals with no remainder, no snapshot-age fields, and no next-check commands. [ASSUMED]

### Pitfall 2: Hiding Collection Incompleteness
**What goes wrong:** Partial snapshots, skipped mounts, or unmatched mount prefixes are silently ignored, making the remainder look more conclusive than it is. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/queries.py + .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md]
**Why it happens:** Phase 2 already proves warnings exist, but planners may forget to propagate them into new diagnostic payloads. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/render.py]
**How to avoid:** Promote partial/unknown-mount conditions into first-class counters and warnings in `df-vs-index`. [VERIFIED: src/watchdirs/reporting/render.py][ASSUMED]
**Warning signs:** A large remainder paired with zero warnings even when the selected snapshots are partial. [ASSUMED]

### Pitfall 3: Overtrusting `lsof` Output as Complete
**What goes wrong:** The tool treats `lsof` results as exhaustive even when permissions or mount warnings limited visibility. [VERIFIED: lsof +L1 -nP]
**Why it happens:** `lsof` can emit warnings on stderr while still returning usable rows. [VERIFIED: lsof +L1 -nP][CITED: https://man7.org/linux/man-pages/man8/lsof.8.html]
**How to avoid:** Capture stderr warnings, expose them in JSON, and keep `/proc` fallback available. [VERIFIED: /proc/self/fd-present + /usr/bin/lsof][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html]
**Warning signs:** Empty culprit list plus stderr warnings or permission-denied traces. [VERIFIED: lsof +L1 -nP][ASSUMED]

### Pitfall 4: Parsing Docker Pretty Output Instead of Structured Output
**What goes wrong:** Minor spacing or wording changes break the parser. [ASSUMED]
**Why it happens:** `docker system df -v` and `docker buildx du --verbose` are human-oriented views, while the CLI also exposes structured output. [VERIFIED: docker system df --format json + docker buildx du --help][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/]
**How to avoid:** Normalize JSON/NDJSON output first and keep pretty output only as a manual verification hint. [VERIFIED: docker system df --format json]
**Warning signs:** Regexes over aligned columns, or code that assumes one monolithic JSON array. [ASSUMED]

### Pitfall 5: Letting DIAG-05 Turn into a Capacity Dashboard
**What goes wrong:** The phase grows into hardware inventory, forecasting, or cleanup policy instead of compact pressure evidence. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Why it happens:** Capacity planning is adjacent to diagnostics, but the current roadmap only asks for enough summary to guide next checks. [VERIFIED: .planning/ROADMAP.md + .planning/REQUIREMENTS.md]
**How to avoid:** Limit DIAG-05 to top-N storage-domains, current usage, recent growth, and evidence gaps. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
**Warning signs:** Device topology trees, SMART stats, or forecast charts appearing in the phase plan. [ASSUMED]

## Code Examples

Verified patterns from official sources:

### Filesystem Totals from `statvfs`
```python
import os


def filesystem_totals(path: str) -> dict[str, int]:
    stat = os.statvfs(path)
    total_bytes = stat.f_frsize * stat.f_blocks
    free_total_bytes = stat.f_frsize * stat.f_bfree
    avail_unprivileged_bytes = stat.f_frsize * stat.f_bavail
    used_bytes = total_bytes - free_total_bytes
    return {
        "size": total_bytes,
        "used": used_bytes,
        "free_total": free_total_bytes,
        "avail_unprivileged": avail_unprivileged_bytes,
    }
```
```python
# Source: https://docs.python.org/3/library/os.html
# Field semantics cross-check: https://man7.org/linux/man-pages/man3/statvfs.3.html
# `used = total - free_total` is an implementation inference from those field definitions. [ASSUMED]
```

### Machine-Readable Deleted-Open Probe
```python
import subprocess


def run_deleted_open_probe() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["lsof", "-nP", "+L1", "-F0"],
        check=False,
        capture_output=True,
        text=True,
    )
```
```python
# Source: lsof field output and +L1 selection
# https://man7.org/linux/man-pages/man8/lsof.8.html
```

### Docker NDJSON Normalization
```python
import json
import subprocess


def run_ndjson_command(argv: list[str]) -> list[dict[str, object]]:
    proc = subprocess.run(argv, check=False, capture_output=True, text=True)
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


rows = run_ndjson_command(["docker", "system", "df", "--format", "json"])
```
```python
# Source: Docker CLI format docs
# https://docs.docker.com/reference/cli/docker/system/df/
# https://docs.docker.com/reference/cli/docker/buildx/du/
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual `df` + broad `du` sweeps + ad hoc Docker commands. [VERIFIED: README.md] | Persisted snapshot diffs for visible growth, then bounded live diagnostics for mismatch causes. [VERIFIED: README.md + .planning/ROADMAP.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Repo direction locked by README and Phase 3 context before 2026-06-14. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] | Agents can answer “what grew?” first and “what remains unexplained?” second without starting from scratch. [VERIFIED: README.md + .planning/PROJECT.md] |
| Parsing Docker pretty tables or inferring reclaimability from filesystem layout. [ASSUMED] | Use Docker structured output and normalize it into reclaimable-vs-active categories. [VERIFIED: docker system df --format json + docker buildx du --help][CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/] | Current docs and current host CLI as of 2026-06-14. [VERIFIED: docker --version + docker system df --format json][CITED: https://docs.docker.com/reference/cli/docker/system/df/] | The planner can rely on a parseable contract instead of table spacing. [VERIFIED: docker system df --format json] |
| Live-only mount inference for historical grouping. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] | Persist snapshot-time mount metadata and reuse it for storage-domain labels. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] | Changed in completed Phase 2 on 2026-06-13. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] | Phase 3 can aggregate by stable storage-domain keys without rescanning live mount state. [VERIFIED: src/watchdirs/reporting/queries.py + .planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md] |

**Deprecated/outdated:**
- Treating `df` as path attribution is outdated for this repo; it is now explicitly a control total only. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- Treating Docker reclaimability as equivalent to `/var/lib/docker` size is outdated for this repo; structured Docker evidence is required when Docker is relevant. [VERIFIED: README.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md][CITED: https://docs.docker.com/reference/cli/docker/system/df/]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | “Material divergence” should be implemented with both an absolute-byte floor and a percentage threshold, not just one or the other. [ASSUMED] | Phase Requirements / Common Pitfalls | The tool may over-trigger or under-trigger deleted-open suspicion. |
| A2 | DIAG-05 should stop at storage-domain summaries and not inspect block-device topology beyond existing mount/storage-domain labels. [ASSUMED] | Non-Goals / Architecture Patterns | The plan may under-scope or over-scope capacity evidence. |
| A3 | Zero-row `docker buildx du --format json` with exit status 0 should be treated as “no visible build-cache records” rather than a hard probe failure. [ASSUMED] | Exact Risk Points / Common Pitfalls | Docker enrichment may report false errors on healthy empty-cache systems. |

## Open Questions

1. **What exact mismatch threshold should trigger `deleted_open_file_suspected`?**
   - What we know: the context requires a material-divergence hint, but it does not lock the threshold. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
   - What's unclear: whether the default should be absolute bytes, ratio, or both. [ASSUMED]
   - Recommendation: planner should pick one explicit absolute floor plus one percentage threshold and make both testable constants. [ASSUMED]

2. **Should `report` run the cheap `df-vs-index` check by default?**
   - What we know: DIAG-03 requires reports to call out deleted-open suspicion, while Phase 2 forbids broad live rescans. [VERIFIED: .planning/REQUIREMENTS.md + .planning/phases/02-growth-frontier-reporting/02-SECURITY.md]
   - What's unclear: whether the user wants that hint inline on every `report` call or only through a separate command. [ASSUMED]
   - Recommendation: default to a cheap inline `df-vs-index` hint only, with full deleted-open and Docker evidence behind explicit subcommands. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python3` | Runtime and tests | ✓ [VERIFIED: command -v python3] | `3.13.5` [VERIFIED: python3 --version] | — |
| `pytest` | Validation Architecture | ✓ [VERIFIED: command -v pytest] | `8.3.5` [VERIFIED: pytest --version] | — |
| `lsof` | Preferred DIAG-02 collector | ✓ [VERIFIED: command -v lsof] | `4.99.4` [VERIFIED: lsof -v | head -2] | `/proc/<pid>/fd` fallback. [VERIFIED: /proc/self/fd-present] |
| `/proc` | Deleted-open fallback | ✓ [VERIFIED: /proc/self/fd-present] | Linux procfs current host. [VERIFIED: /proc/self/fd-present] | None if both `/proc` and `lsof` are unavailable. [ASSUMED] |
| Docker CLI + daemon | DIAG-04 / optional DIAG-05 enrichment | ✓ [VERIFIED: command -v docker + docker info --format '{{.ServerVersion}}'] | `29.5.3` [VERIFIED: docker --version + docker info --format '{{.ServerVersion}}'] | Degrade to filesystem-only diagnostics and emit `docker_unavailable` warning. [ASSUMED] |
| `df` | Manual verification command | ✓ [VERIFIED: command -v df] | `9.7` [VERIFIED: df --version | head -1] | In-program `os.statvfs()` for totals. [CITED: https://docs.python.org/3/library/os.html] |

**Missing dependencies with no fallback:**
- none during research. Core Phase 3 recommendations can run on this host. [VERIFIED: python3 --version + pytest --version + command -v lsof + command -v docker + command -v df]

**Missing dependencies with fallback:**
- none during research, but the planner should still design `docker_unavailable` and `lsof_unavailable` warning paths for other hosts. [VERIFIED: .planning/REQUIREMENTS.md][ASSUMED]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 8.3.5` [VERIFIED: pytest --version] |
| Config file | `pyproject.toml` [VERIFIED: pyproject.toml] |
| Quick run command | `python3 -m pytest -q tests/test_diagnostics_df_index.py tests/test_diagnostics_deleted_open.py tests/test_diagnostics_docker.py tests/test_diagnostics_summary.py` [ASSUMED] |
| Full suite command | `python3 -m pytest -q` [VERIFIED: pyproject.toml + existing repo test layout] |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIAG-01 | `df-vs-index` reports visible indexed totals, filesystem totals, and unattributed remainder per storage-domain. [VERIFIED: .planning/REQUIREMENTS.md] | unit + CLI contract | `python3 -m pytest -q tests/test_diagnostics_df_index.py` [ASSUMED] | ❌ Wave 0 |
| DIAG-02 | deleted-open diagnostic returns culprit rows, warnings, and cautious hints. [VERIFIED: .planning/REQUIREMENTS.md] | unit + parser | `python3 -m pytest -q tests/test_diagnostics_deleted_open.py` [ASSUMED] | ❌ Wave 0 |
| DIAG-03 | `report` or `df-vs-index` emits bounded suspicion hints when mismatch thresholds fire. [VERIFIED: .planning/REQUIREMENTS.md] | CLI contract | `python3 -m pytest -q tests/test_cli_report_commands.py -k diagnostics_hint` [ASSUMED] | ✅ existing file, new cases needed |
| DIAG-04 | Docker enrichment normalizes structured Docker rows and degrades cleanly when unavailable. [VERIFIED: .planning/REQUIREMENTS.md] | unit + CLI contract | `python3 -m pytest -q tests/test_diagnostics_docker.py` [ASSUMED] | ❌ Wave 0 |
| DIAG-05 | compact top-N storage-domain summary preserves truncation and next-check order. [VERIFIED: .planning/REQUIREMENTS.md] | unit + CLI contract | `python3 -m pytest -q tests/test_diagnostics_summary.py` [ASSUMED] | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest -q tests/test_diagnostics_df_index.py tests/test_diagnostics_deleted_open.py tests/test_diagnostics_docker.py tests/test_diagnostics_summary.py` [ASSUMED]
- **Per wave merge:** `python3 -m pytest -q tests/test_cli_report_commands.py tests/test_reporting_queries.py tests/test_grouping.py tests/test_diagnostics_df_index.py tests/test_diagnostics_deleted_open.py tests/test_diagnostics_docker.py tests/test_diagnostics_summary.py` [ASSUMED]
- **Phase gate:** Full suite green before `$gsd-verify-work`. [VERIFIED: .planning/config.json]

### Wave 0 Gaps
- [ ] `tests/test_diagnostics_df_index.py` — storage-domain aggregation, staleness, partial-snapshot, and unknown-mount remainder tests. [ASSUMED]
- [ ] `tests/test_diagnostics_deleted_open.py` — `lsof -F0` parser, `/proc` fallback, stderr-warning, and truncation tests. [ASSUMED]
- [ ] `tests/test_diagnostics_docker.py` — NDJSON normalization, alias detection, empty-output, and daemon-unavailable tests. [ASSUMED]
- [ ] `tests/test_diagnostics_summary.py` — top-N prioritization, truncation, and final-summary wording tests. [ASSUMED]
- [ ] Extend `tests/test_cli_report_commands.py` — add `diagnostic_hints` coverage without breaking existing Phase 2 payload contracts. [VERIFIED: tests/test_cli_report_commands.py][ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [VERIFIED: local CLI scope in README.md + .planning/PROJECT.md] | None; this phase does not introduce auth. [VERIFIED: README.md] |
| V3 Session Management | no [VERIFIED: local CLI scope in README.md + .planning/PROJECT.md] | None; there are no sessions. [VERIFIED: README.md] |
| V4 Access Control | yes [VERIFIED: local probe scope touches `/proc` and Docker daemon access] | Do not escalate privileges, honor OS permission failures, and surface incomplete diagnostics as warnings rather than pretending access succeeded. [VERIFIED: lsof +L1 -nP + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html] |
| V5 Input Validation | yes [VERIFIED: existing CLI already validates limits, selectors, and depth] | Reuse strict argparse parsers, whitelist command choices, fixed argv probes, and bounded limits/truncation. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/queries.py][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/subprocess.html] |
| V6 Cryptography | no [VERIFIED: no cryptographic feature in repo scope or phase requirements] | None; do not add crypto to this phase. [VERIFIED: .planning/REQUIREMENTS.md] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell/command injection through probe execution | Tampering / Elevation | Use fixed argv lists with `shell=False` and never interpolate user strings into command text. [CITED: https://docs.python.org/3/library/subprocess.html][VERIFIED: src/watchdirs/cli.py] |
| Path/process-name text spoofing in human-readable output | Spoofing | Reuse the existing escaped text renderers and JSON-first envelopes. [VERIFIED: src/watchdirs/reporting/render.py + .planning/phases/02-growth-frontier-reporting/02-SECURITY.md] |
| False certainty from stale or partial evidence | Repudiation / Tampering | Emit snapshot ids, timestamps, age, partial counts, and warnings in every diagnostic section. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/reporting/render.py][ASSUMED] |
| Unbounded output from `lsof` or Docker | Denial of Service | Default to top-N sections, strict limits, and truncation metadata. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] |
| Overly strong cleanup/restart wording | Tampering / Safety | Restrict output to verification hints and cautious action language. [VERIFIED: .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md] |

## Sources

### Primary (HIGH confidence)
- `README.md` - product intent, deleted-open scope, Docker enrichment intent, and Phase 3 command examples. [VERIFIED: README.md]
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md` - phase boundary, constraints, DIAG-01..DIAG-05, and locked decisions. [VERIFIED: .planning/PROJECT.md + .planning/REQUIREMENTS.md + .planning/ROADMAP.md + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- `src/watchdirs/cli.py`, `src/watchdirs/models.py`, `src/watchdirs/reporting/queries.py`, `src/watchdirs/reporting/render.py`, `src/watchdirs/reporting/pairs.py`, `src/watchdirs/collect/mounts.py`, `src/watchdirs/db/schema.sql` - current command seams, dataclasses, grouping logic, render contracts, and persisted evidence model. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/models.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + src/watchdirs/reporting/pairs.py + src/watchdirs/collect/mounts.py + src/watchdirs/db/schema.sql]
- Host command verification: `python3 --version`, `pytest --version`, `lsof -v`, `docker --version`, `docker info --format '{{.ServerVersion}}'`, `docker system df --format json`, `docker buildx du --verbose`, `df --version`, `lsof +L1 -nP`. [VERIFIED: command outputs captured during this research session]

### Secondary (MEDIUM confidence)
- Python `os.statvfs` docs - field mapping for `f_blocks`, `f_bfree`, and `f_bavail`. [CITED: https://docs.python.org/3/library/os.html]
- Linux `statvfs(3)` and `df(1)` man pages - filesystem accounting semantics and `df` scope. [CITED: https://man7.org/linux/man-pages/man3/statvfs.3.html][CITED: https://man7.org/linux/man-pages/man1/df.1.html]
- Linux `lsof(8)`, `proc_pid_fd(5)`, and `unlink(2)` man pages - deleted-open semantics, field output, and procfs descriptor behavior. [CITED: https://man7.org/linux/man-pages/man8/lsof.8.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html][CITED: https://man7.org/linux/man-pages/man2/unlink.2.html]
- Docker CLI docs for `docker system df` and `docker buildx du`. [CITED: https://docs.docker.com/reference/cli/docker/system/df/][CITED: https://docs.docker.com/reference/cli/docker/buildx/du/]

### Tertiary (LOW confidence)
- none. [VERIFIED: all external technical claims in this document are either cited or explicitly marked `[ASSUMED]`]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - almost entirely derived from the live repo and live host tool availability. [VERIFIED: pyproject.toml + host command checks]
- Architecture: HIGH - the recommended module boundaries follow current repo seams and locked Phase 3 decisions. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/models.py + src/watchdirs/reporting/queries.py + src/watchdirs/reporting/render.py + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md]
- Pitfalls: MEDIUM - the major failure modes are strongly grounded, but threshold defaults and some degraded-host behaviors still need planner choices and tests. [VERIFIED: host command checks + .planning/phases/03-pressure-gap-diagnostics/03-CONTEXT.md][ASSUMED]

**Research date:** 2026-06-14
**Valid until:** 2026-06-28 for host-tool and Docker-CLI details; repo-structure findings should remain stable until Phase 3 implementation changes them. [VERIFIED: docker --version][ASSUMED]
