# Phase 3: Pressure Gap Diagnostics - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase explains the gap between indexed directory growth and real filesystem pressure. Phase 2 already answers "which visible directory trees grew?" Phase 3 adds a compact diagnostic layer for cases where that answer does not fully explain `df`: filesystem totals, deleted-open files, skipped/unindexed evidence, Docker/containerd evidence, and a short prioritized next-check list.

This phase does not perform cleanup, restart services, install timers, change retention policy, or build a dashboard. It gives an agent enough evidence and next commands to continue the investigation without spending tokens rediscovering the standard checks.

</domain>

<decisions>
## Implementation Decisions

### `df` vs Indexed Evidence
- **D-01:** Treat `df` as a filesystem-level control total, not as a source of per-directory attribution. `df` can be reproduced with filesystem stats, but it cannot say which directory grew.
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

Technical implementation details are delegated to research/planning. Downstream agents should use primary docs or expert review for Linux accounting details (`statvfs`, deleted-open files via `/proc`/`lsof`, Docker CLI output stability) and choose conservative, testable approaches.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Intent
- `README.md` - Original disk-growth incident, `df`/`du` mismatch motivation, deleted-open-file caveat, Docker/containerd enrichment notes, and intended command examples.
- `.planning/PROJECT.md` - Current project boundary, validated Phase 1-2 requirements, active Phase 3 diagnostics, and key decisions.
- `.planning/REQUIREMENTS.md` - Phase 3 requirements `DIAG-01` through `DIAG-05`.
- `.planning/ROADMAP.md` - Phase 3 goal, success criteria, dependency on Phase 2, and phase boundary.

### Prior Phases
- `.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md` - Snapshot collection semantics, mount policy, byte semantics, persistent state locations, and deferred deleted-open/Docker work.
- `.planning/phases/02-growth-frontier-reporting/02-CONTEXT.md` - Agent-facing report contract, compact output decisions, grouping choices, and deferred Phase 3 diagnostics.
- `.planning/phases/02-growth-frontier-reporting/02-VERIFICATION.md` - Verified reporting commands and existing data-flow evidence to build on.
- `.planning/phases/02-growth-frontier-reporting/02-SECURITY.md` - Security constraints around text spoofing, live rescan avoidance, and accepted local-path disclosure.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/watchdirs/cli.py` - Existing command registration, JSON/text error envelopes, database opening, and report handler patterns. New commands should extend this surface.
- `src/watchdirs/models.py` - Dataclass-based report models, warnings, snapshot/mount identities, and scanner records. Continue the dataclass pattern for diagnostic models.
- `src/watchdirs/reporting/queries.py` - Existing SQLite query layer for snapshot, diff, deleted, explain, grouping, and warnings. `df-vs-index` should reuse persisted `directory_sizes` and `snapshot_mounts` rather than rescanning directory trees.
- `src/watchdirs/reporting/render.py` - JSON/text rendering helpers with escaped text fields. New diagnostic text output should use the same escaping and compact labeled style.
- `src/watchdirs/reporting/pairs.py` - Same-root snapshot pair selection for `--since`, useful when diagnostics compare current filesystem state against indexed current snapshots.
- `src/watchdirs/collect/mounts.py` and `src/watchdirs/collect/classify.py` - Mountinfo parsing and filesystem policy helpers that can support filesystem/storage-domain mapping.
- `tests/test_cli_report_commands.py`, `tests/test_reporting_queries.py`, `tests/test_grouping.py`, and `tests/test_mount_policy.py` - Existing test styles and fixtures for CLI JSON contracts, SQLite fixtures, persisted mount grouping, and mount parsing.

### Established Patterns
- Python stdlib-first unless a dependency removes real complexity.
- Keep CLI/config, query logic, render logic, and filesystem/process/Docker probing separated.
- JSON is the stable contract; terse text is secondary but still agent-friendly.
- Reports must not hide partial scan evidence or fabricate attribution.
- Raw filesystem path bytes stay as bytes internally and are decoded/escaped only at render boundaries.
- `disk_bytes` is the primary disk-pressure signal; `apparent_bytes` remains explicitly labeled.

### Integration Points
- Add new command handlers under `src/watchdirs/cli.py`.
- Add reusable diagnostics/query modules under `src/watchdirs/reporting/` or a focused diagnostics package if the planner finds the scope too broad for reporting.
- Use persisted `snapshot_mounts` to associate indexed rows with filesystems/storage domains.
- Use OS-level filesystem stats for `df` comparison and process/Docker evidence only as bounded auxiliary diagnostics.

</code_context>

<specifics>
## Specific Ideas

- The user originally wanted the tool to answer "where did the space go?" without repeatedly spending agent tokens on manual filesystem searches.
- The user was surprised that `df` and visible directory-tree indexing can diverge; the Phase 3 UX should explain this plainly, not assume deep filesystem knowledge.
- `df`-level accounting is useful as a checksum/control total, but it does not identify paths.
- Docker cache should usually be visible as files under Docker/containerd storage paths if those paths are scanned. Docker enrichment adds meaning: reclaimable vs active, category breakdown, and verification commands.
- The final diagnostic should prefer a few prioritized next checks over long recommendations.

</specifics>

<deferred>
## Deferred Ideas

- Automatic cleanup commands such as Docker prune or service restarts are out of Phase 3.
- Scheduled collection, retention, pruning, vacuum, and strong `nice`/`ionice` behavior remain Phase 4.
- Long-term trend forecasting, broad capacity-planning dashboard behavior, and BI-style reports remain out of scope for v1 unless a later phase explicitly adds them.

</deferred>

---

*Phase: 3-Pressure Gap Diagnostics*
*Context gathered: 2026-06-14*
