# Phase 2: Growth Frontier Reporting - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase turns trusted snapshots into simple agent-facing reports for the first real job to be done: when free disk space unexpectedly drops, an agent can quickly identify which directory trees grew, which filesystem/root owns the pressure, and where to drill down next.

The phase delivers snapshot comparison, current-top, deleted-path, and path-explanation CLI workflows. It does not deliver deleted-open-file diagnostics, Docker/containerd reclaimability, long-term trend forecasting, scheduled collection, retention, or capacity-planning dashboards.

</domain>

<decisions>
## Implementation Decisions

### Product Job
- **D-01:** Optimize Phase 2 for the concrete incident workflow: "Yesterday there was enough free space; today there is not; what grew and where should the agent inspect next?"
- **D-02:** The primary user is an LLM agent, not a human operator and not a deterministic script. Outputs must be easy for an agent to scan, quote, and parse.
- **D-03:** Keep reports intentionally small. The default output should identify the highest-value next inspection targets rather than dumping full recursive trees.
- **D-04:** Do not add trend analysis, forecasting, or BI-style summaries in Phase 2 unless required to answer the immediate disk-growth incident.

### Report Contract
- **D-05:** JSON remains the stable contract, but human-readable output should also be terse and scan-friendly because the consumer is an LLM agent that may reason more reliably from labeled text plus JSON than from JSON alone.
- **D-06:** Default growth output should answer three questions fast: what grew, by how much, and what should be inspected next.
- **D-07:** Essential report fields are path, disk-byte delta, apparent-byte delta, current size, previous size, snapshot time range, scan status or partial-failure flags, and filesystem/mount identity when available.
- **D-08:** Reports must avoid ambiguous mixing of absolute size and delta values. Field names and table labels should make current, previous, and delta values explicit.
- **D-09:** Repetitive zero-change rows, verbose scanner internals, full recursive child lists, and decorative summaries are distracting by default and should be omitted unless a command explicitly asks for them.

### Growth Frontier
- **D-10:** The default `diff` experience should be a ranked growth frontier, not a raw list of every changed descendant.
- **D-11:** The frontier should help the agent pick a next subtree to inspect while avoiding near-duplicate parent/child noise.
- **D-12:** `explain-path` should provide focused drill-down for one suspicious subtree after `diff` identifies it.

### Snapshot Comparison
- **D-13:** All comparison commands must make the selected baseline and current snapshots explicit in output, including timestamps and snapshot ids.
- **D-14:** Reports should surface partial or failed scan evidence so an agent does not trust incomplete deltas blindly.
- **D-15:** Created, deleted, grown, shrunk, and unchanged classifications are required, but unchanged entries should not dominate default output.

### Grouping and Storage Domains
- **D-16:** Reports should let the agent group evidence by the level useful for the investigation: configured root, top-level subtree, mount point, or mounted storage domain where known.
- **D-17:** Phase 2 should support the multi-SSD product direction without building a full capacity-planning model. The immediate need is to show which filesystem/storage area owns current pressure and recent growth.
- **D-18:** Because Phase 1 persists root/path aggregates but not a dedicated mount/device table, planning must decide the minimal schema/query extension needed for reliable grouping instead of hiding an unreliable live-only inference.

### the agent's Discretion

The user explicitly delegated deep technical choices to expert-panel or best-practice research after product intent was clarified. Downstream planning should resolve snapshot-pairing semantics, exact frontier algorithm, JSON schema, and grouping persistence technically, but must keep the product job above as the deciding constraint.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Intent
- `README.md` - Bootstrap/design note for the original disk-growth incident and tool goals.
- `.planning/PROJECT.md` - Project boundary, core value, constraints, and key decisions.
- `.planning/REQUIREMENTS.md` - Phase 2 requirements `REPT-01` through `REPT-07`.
- `.planning/ROADMAP.md` - Phase 2 goal, dependencies, success criteria, and phase boundary.

### Previous Phase
- `.planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md` - Locked collection semantics, snapshot states, path identity, byte semantics, storage locations, and deferred items.
- `.planning/phases/01-trusted-snapshot-collection/01-VERIFICATION.md` - Evidence that Phase 1 collection behavior passed acceptance verification.
- `.planning/phases/01-trusted-snapshot-collection/01-SECURITY.md` - Filesystem-safety constraints that reports must preserve when interpreting scan evidence.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/watchdirs/cli.py` - Existing `collect` CLI surface and JSON envelope style; Phase 2 commands should extend this command tree.
- `src/watchdirs/config.py` - Existing config loader and default state path behavior.
- `src/watchdirs/models.py` - Dataclass models for snapshots, directory aggregates, scanner options, and mount policy data.
- `src/watchdirs/db/connection.py` - SQLite connection helper.
- `src/watchdirs/db/migrations.py` - Snapshot lifecycle and row insertion helpers; likely home for query helpers or migration entry points.
- `src/watchdirs/db/schema.sql` - Current persisted tables: `snapshots` and `directory_sizes`.
- `src/watchdirs/collect/mounts.py` - Mountinfo parsing and path-to-mount helper that may inform grouping.
- `src/watchdirs/collect/classify.py` - Mount classification policy used during collection.

### Established Patterns
- Code is Python stdlib-first, split by responsibility, and dataclass-oriented.
- Path identity is stored as raw SQLite BLOB values and decoded only at display/report boundaries.
- `disk_bytes` is the primary disk-pressure signal; `apparent_bytes` is still stored and should be reportable.
- Snapshot rows can be `complete`, `partial`, or `failed`; reports must not hide partial evidence.
- Skipped mounts and excluded subtrees are represented as rows with error context rather than silently disappearing.

### Integration Points
- New reporting commands should read the existing SQLite database rather than rescanning live filesystem state.
- Current indexes support lookup by path/snapshot, size within snapshot, and parent path within snapshot; Phase 2 planning should validate whether diff/frontier queries need additional indexes.
- Current schema does not persist a first-class filesystem/storage-domain identity per aggregate row. REPT-07 requires either a minimal persistence extension or a clearly documented reliable grouping derivation.

</code_context>

<specifics>
## Specific Ideas

- The product focus is the "wtf where did free space go?" incident, not speculative future reporting.
- The user wants agents to spend fewer tokens discovering which directories grew before deciding whether to clean Docker, clear caches, move data, or inspect service-owned paths.
- The user is comfortable letting an agent choose grouping if the command surface exposes enough grouping controls.
- A simulated downstream agent requested a default report that shows ranked deltas with path, apparent-byte delta, disk-byte delta, snapshot timestamps, partial scan flags, and filesystem/mount identity.
- Useful grouping controls from the simulated agent perspective: top-level subtree, depth limit, service/unit or mount point when available, changed-only vs all tracked, and growth threshold.
- Hardlink/apparent-vs-disk differences should be available and clearly labeled, but not shown as a wall of inode details by default.
- Reports should include a compact "why this may not match df" note only when there is a mismatch signal; deeper reconciliation belongs to Phase 3.

</specifics>

<deferred>
## Deferred Ideas

- Deleted-open-file diagnostics and `df` vs indexed-total reconciliation remain Phase 3.
- Docker/containerd reclaimability and service-specific enrichment remain Phase 3.
- Disk-subsystem capacity planning, migration recommendations, and old-disk repurposing remain later diagnostic/capacity work unless Phase 2 grouping needs a minimal storage-domain foundation.
- Scheduled collection, retention, pruning, SQLite vacuum, and strong `nice`/`ionice` behavior remain Phase 4.
- Long-term trend forecasting and BI-style reports are out of current scope.

</deferred>

---

*Phase: 2-Growth Frontier Reporting*
*Context gathered: 2026-06-13*
