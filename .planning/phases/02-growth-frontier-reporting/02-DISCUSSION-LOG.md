# Phase 2: Growth Frontier Reporting - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 2-Growth Frontier Reporting
**Areas discussed:** Product job, Agent-facing output, Growth frontier, Grouping, Technical panel convergence

---

## Product Job

| Option | Description | Selected |
|--------|-------------|----------|
| Disk-growth incident triage | Help an agent answer why free disk space dropped since the last useful snapshot. | ✓ |
| Capacity-planning dashboard | Build broader disk upgrade, migration, and trend analysis views. | |
| General disk visualizer | Build a human-oriented tool for manual browsing. | |

**User's choice:** Focus only on the original pain: free space unexpectedly drops and the agent wastes tokens figuring out which folders grew.
**Notes:** The user explicitly asked not to invent phantom pains. Phase 2 should keep scope tight around "what grew, by how much, where should I inspect next?"

---

## Agent-Facing Output

| Option | Description | Selected |
|--------|-------------|----------|
| JSON-only contract | Stable machine-readable output for scripts and agents. | |
| Terse human-readable plus stable JSON | Labeled scan-friendly text for LLM reasoning, with JSON for exact parsing. | ✓ |
| Human-pretty report | Rich prose/formatting optimized for a person reading manually. | |

**User's choice:** The primary user is exclusively an agent, but the user noted that an agent is a language model, not a deterministic script, so pure JSON may not be the only ergonomic surface.
**Notes:** Default output should be simple and compact. The agent needs enough evidence to go inspect suspicious folders and decide whether to clean Docker, caches, temp files, or service data.

---

## Growth Frontier

| Option | Description | Selected |
|--------|-------------|----------|
| Raw changed paths | List every changed path sorted by growth. | |
| Ranked growth frontier | Show a compact set of high-value changed subtrees without near-duplicate parent/child spam. | ✓ |
| Full recursive tree diff | Show all changed descendants under every changed parent. | |

**User's choice:** User wants simple reports that show which folders increased and let the agent inspect those folders independently.
**Notes:** Simulated agent feedback strongly preferred one clear "top growth frontier" view over piles of near-duplicate summaries.

---

## Grouping

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed configured-root grouping only | Always group by configured collection roots. | |
| Agent-selectable grouping | Let the report choose or expose grouping by root, subtree, mount point, or storage domain where available. | ✓ |
| Full disk-subsystem model now | Persist rich hardware/device topology and capacity planning data in Phase 2. | |

**User's choice:** The agent should understand grouping and maybe choose the grouping itself. Multi-SSD usefulness matters, but Phase 2 should not overbuild future capacity planning.
**Notes:** Current Phase 1 storage has root/path aggregates but no first-class mount/device/domain table. Technical planning must resolve the minimal reliable implementation for REPT-07.

---

## Technical Panel Convergence

| Option | Description | Selected |
|--------|-------------|----------|
| Build richer diagnostics now | Fold `df` reconciliation, deleted-open files, Docker reclaimability, and trends into Phase 2. | |
| Keep Phase 2 as comparison/frontier/reporting | Implement snapshot-pair selection, frontier diffing, top/deleted/explain, status flags, and grouping hooks. | ✓ |
| Defer grouping entirely | Avoid schema/query complications by leaving filesystem grouping for later. | |

**User's choice:** Deep technical choices should be handled by expert panel or research after product intent is clear.
**Notes:** Panel-style convergence: Product and Kaizen prioritize the narrow "where did space go?" job; Architect flags persisted grouping identity as the main schema risk; QA requires explicit baseline/current snapshot metadata and partial-scan flags; Sysadmin/SRE prefer disk-byte deltas as primary with apparent bytes available; Security wants reports to avoid live filesystem traversal beyond already collected evidence.

---

## Simulated Agent Feedback

The simulated downstream agent said the easiest default report would answer:

- what grew;
- by how much;
- what to inspect next.

Essential fields from that perspective:

- path;
- delta bytes;
- current size;
- previous size;
- snapshot time range;
- scan status or partial failure flags;
- filesystem or mount identity.

Main frustrations to avoid:

- mixing absolute size and delta without labels;
- no clean baseline/current comparison;
- too many default columns;
- hidden exclusion rules;
- no indication that a tree was partially scanned;
- human-pretty reports that are hard for an agent to parse.

## the agent's Discretion

- Snapshot-pair semantics for `--since 24h` should be resolved technically in planning.
- Exact JSON schema should be resolved technically in planning, using the product job and essential fields above.
- Exact frontier algorithm should be resolved technically in planning and tested against parent/child duplication cases.
- Minimal reliable filesystem/storage-domain grouping implementation should be resolved technically in planning.

## Deferred Ideas

- Trend forecasting is not needed for the current job.
- Deleted-open-file mismatch analysis belongs to Phase 3.
- Docker/containerd enrichment belongs to Phase 3.
- Scheduling, retention, and low-priority `nice`/`ionice` operation belong to Phase 4.
