---
phase: 02
reviewers: [codex, opencode]
reviewed_at: 2026-06-13T15:54:26.226587+05:00
plans_reviewed:
  - .planning/phases/02-growth-frontier-reporting/02-01-PLAN.md
  - .planning/phases/02-growth-frontier-reporting/02-02-PLAN.md
  - .planning/phases/02-growth-frontier-reporting/02-03-PLAN.md
  - .planning/phases/02-growth-frontier-reporting/02-04-PLAN.md
---

# Cross-AI Plan Review - Phase 02

## Codex Review

## Summary

The four-plan sequence is coherent and mostly well-scoped: it builds the durable grouping foundation first, proves `top`, then adds the core `diff` frontier, then finishes `report`, `deleted`, and `explain-path`. The strongest part is the consistent insistence on JSON-first contracts, explicit snapshot metadata, same-root pairing, BLOB path identity, and deferred Phase 3/4 boundaries. The main risks are around underspecified multi-root semantics, mount/storage-domain identity details, frontier pruning edge cases, and the amount of behavior concentrated into the final wave.

## 02-01-PLAN.md

### Strengths

- Correctly prioritizes persisted snapshot-time mount metadata before report grouping.
- Explicitly rejects live-only mount inference and durable reliance on `mount_id`.
- Keeps scope tight: schema, persistence helpers, collect wiring, and grouping tests only.
- Good TDD shape, including reused `mount_id` cases and BLOB path assertions.

### Concerns

- **MEDIUM:** Migration behavior is underspecified for existing v1 databases. “Execute idempotent schema script” may be fine, but the plan should explicitly preserve old rows and update `PRAGMA user_version` only after successful migration.
- **MEDIUM:** Cascade delete depends on SQLite foreign keys being enabled on the connection. If existing connection setup does not enable `PRAGMA foreign_keys=ON`, the FK declaration alone will not enforce cleanup.
- **MEDIUM:** “Storage-domain” identity is implied but not actually defined. The fields are present, but the plan does not define the durable domain key shape that later reports should use.
- **LOW:** SQLite type affinity makes “BLOB column” tests easy to overtrust. Tests should verify stored values round-trip as `bytes`, not only schema text.
- **LOW:** Fatal or failed collection behavior is unclear. If a snapshot is marked failed after partial setup, should mount rows still be persisted?

### Suggestions

- Add explicit migration tests for fresh DB, v1 DB with existing snapshots/directory rows, and repeat initialization.
- Verify `PRAGMA foreign_keys` behavior or avoid relying on cascade in tests without confirming it.
- Define a `storage_domain_key` convention now, even if computed later, such as `major_minor + root + filesystem_type + mount_source`.
- Require mount rows to persist for any snapshot id that exists, including partial/failed snapshots when collection reached snapshot creation.

### Risk Assessment

**MEDIUM.** The design direction is right, but migration and grouping-key details could create subtle historical-report bugs later.

## 02-02-PLAN.md

### Strengths

- Good incremental slice: `top` exercises rendering, snapshot selection, grouping, and CLI behavior before diff complexity.
- Explicit `current_disk_bytes` / `current_apparent_bytes` naming addresses ambiguity risk.
- Whitelisted `--group-by` prevents SQL selector injection.
- Includes text output expectations without letting human output dominate the JSON contract.

### Concerns

- **HIGH:** `--snapshot latest` is defined as one newest non-failed snapshot. Since Phase 1 appears to store one snapshot per configured root, this may omit other roots on multi-root configurations. For current usage, “latest” may need to mean latest per root, or the CLI needs a clear `--root`/single-snapshot contract.
- **MEDIUM:** `top-level-subtree` grouping needs byte-prefix boundary rules. Longest prefix without segment boundaries can misgroup paths like `/var` and `/varlib`.
- **MEDIUM:** `storage-domain` grouping is listed but not specified beyond mount grouping. It needs a distinct key and label contract.
- **MEDIUM:** Empty DB, missing numeric snapshot id, failed selected snapshot id, and invalid/huge limits are not clearly tested.
- **LOW:** `path_bytes_hex` on every row is useful but can bloat output; acceptable for agent evidence, but defaults should still keep row limits tight.

### Suggestions

- Decide whether `top --snapshot latest` is global-single-snapshot, latest-per-root, or requires explicit root selection. This should be resolved before implementation.
- Add tests for mount prefix boundaries and trailing slash/root edge cases.
- Add validation for `--limit`: positive integer, compact default, maximum cap, structured JSON error.
- Define `storage-domain` output separately from `mount`, even if both initially share fields.

### Risk Assessment

**MEDIUM-HIGH.** The slice is well chosen, but unresolved “latest” semantics can compromise REPT-03 on real multi-root use.

## 02-03-PLAN.md

### Strengths

- Directly targets the most important phase value: compact growth frontier from stored evidence.
- Same-root pair selection is well handled, including partial snapshots, failed exclusion, fallback baseline warning, and no-pair errors.
- Classification coverage is complete for REPT-06.
- Correctly separates raw SQL diff from Python frontier pruning.

### Concerns

- **HIGH:** Global `--limit` semantics after multiple root pairs are not specified. If each pair is limited independently before merge, the final ranking may miss the true top growth across roots.
- **HIGH:** Frontier pruning is underdefined. “Near-duplicate” and “effectively tied” need concrete thresholds; otherwise tests may encode arbitrary behavior and future changes become risky.
- **MEDIUM:** Deleted and shrunk rows are classified but default frontier focuses positive growth. That is correct, but JSON should expose whether omitted classifications exist or point users to `report`/`deleted`.
- **MEDIUM:** `--since` parsing accepts compact durations, but time basis should be explicit: likely compare against current snapshot `finished_at`, not wall-clock now.
- **MEDIUM:** Pairing by identical `root_path` must preserve BLOB identity. If comparison decodes paths, non-UTF-8 roots can break.
- **LOW:** Sorting tie-breaks by depth and path can be surprising unless the desired depth preference is fixed and documented.

### Suggestions

- Apply raw diff per valid pair, merge all candidate rows, then apply global frontier pruning and global `--limit`.
- Define frontier suppression precisely, for example: suppress ancestor if a descendant has >= X% of its positive delta, or prefer deepest row for identical deltas.
- Include counts of omitted `deleted`, `shrunk`, and `unchanged` rows in metadata or warnings.
- Test `--since` against snapshot timestamps, not current wall time.
- Add non-UTF-8 root/path pair-selection tests if Phase 1 supports raw BLOB roots.

### Risk Assessment

**HIGH.** This is the core behavior, and the current plan’s frontier and global-limit semantics need sharper definitions to avoid misleading reports.

## 02-04-PLAN.md

### Strengths

- Reuses the diff/pair/classification pipeline rather than inventing separate behavior.
- Covers the remaining required commands and explicitly keeps Phase 3/4 diagnostics out.
- Good attention to `deleted` as first-class baseline-only evidence.
- `explain-path` residual deltas are valuable and aligned with the “where to drill down next” workflow.

### Concerns

- **HIGH:** This wave is large. It adds three commands, summary aggregation, deleted rows, explain-path subtree logic, residual math, text renderers, grouping, caps, and final verification. The blast radius is high.
- **HIGH:** `explain-path PATH` matching semantics are not sufficiently defined. Exact path vs subtree, path normalization, relative paths, symlinks in user input, trailing slashes, and paths outside tracked roots need explicit behavior.
- **MEDIUM:** Residual delta math can be wrong if child rows are recursive aggregates. The plan should specify whether residual means target delta minus immediate child deltas, and how files directly under the target are represented.
- **MEDIUM:** `report` grouping summaries can double-count recursive aggregates unless they aggregate only selected frontier rows or a well-defined depth/group slice.
- **MEDIUM:** `deleted --since` sorting by previous disk bytes is good, but deleted parent/child duplicate noise may be severe. The plan should decide whether deleted defaults are raw deleted rows or a deleted frontier.
- **LOW:** Text output requirements are subjective. Tests should assert key labels and absence of obvious noise, not brittle formatting.

### Suggestions

- Split 02-04 into two implementation passes if possible: `deleted` + `report` first, `explain-path` second.
- Define `explain-path` path resolution: encode with `os.fsencode`, require it to be within a selected root, exact target row preferred, structured error if not indexed.
- Add tests proving report group summaries do not double-count recursive parent/child aggregates.
- Define deleted output pruning behavior. If raw deleted rows are allowed, default limits must be strict and metadata should say it is not frontier-pruned.
- Add explicit structured errors for no pair, path not found, path outside indexed roots, invalid depth, and invalid limit.

### Risk Assessment

**HIGH.** The goals are right, but this plan carries the most complexity and the most risk of subtle misleading output.

## Overall Risk Assessment

**MEDIUM-HIGH.** The sequence achieves the phase goals on paper and respects the project’s core constraints. The biggest issues are not scope creep into deferred diagnostics, which the plans handle well; they are semantic precision problems inside the required reporting layer. Before implementation, I would tighten: multi-root `latest` behavior, storage-domain key definition, global limit behavior, frontier suppression thresholds, `explain-path` path matching, and aggregation rules that avoid recursive double-counting.

---

## OpenCode Review

Let me read the key source files to ground the review in reality.
Now I have a thorough understanding of the codebase and plans. Here is my review:

---

# Cross-AI Plan Review: Phase 02 — Growth Frontier Reporting

## 02-01-PLAN.md — Persist Snapshot-Time Mount Metadata

### Summary

A clean, minimal schema extension that adds `snapshot_mounts` persistence to the existing `collect` pipeline. The scope is appropriately narrow: add one table, wire it during collection, and provide load helpers. This correctly lays the foundation for REPT-07 before any reporting code is written.

### Strengths

- **Correct domain-key choice** — explicitly avoids `mount_id` as durable identity, using `major_minor`, `root`, `mount_point`, `filesystem_type`, and `mount_source` instead, matching Linux mountinfo semantics.
- **BLOB-consistent storage** — `root` and `mount_point` use `sqlite3.Binary`, matching the existing Phase 1 path identity contract.
- **Idempotent migration strategy** — `SCHEMA_VERSION` bump from 1 to 2 re-runs `schema.sql` with `CREATE TABLE IF NOT EXISTS`, which correctly handles both fresh DBs and v1 upgrades without a separate migration script.
- **Cascade delete** — `REFERENCES snapshots(id) ON DELETE CASCADE` ensures cleanup when whole snapshot pruning arrives in Phase 4.

### Concerns

- **[MEDIUM]** The `options` and `super_options` tuples from `MountInfo` are silently omitted from `SnapshotMount`. This is reasonable (they're not needed for grouping), but the omission should be explicit in the plan with a brief justification so future readers don't think it was an oversight.
- **[MEDIUM]** Wire-up in `cli.py` happens inside the per-root loop after `scan_root()` and `insert_directory_rows()` but before `finalize_snapshot()`. If `insert_snapshot_mounts()` fails, the snapshot was already created and directory rows inserted. The error path should call `connection.rollback()` to preserve the "all-or-nothing" semantics that Phase 1 established (see line 72 in `cli.py`).
- **[LOW]** The plan uses `resources.files("watchdirs.db").joinpath("schema.sql").read_text()` for schema loading. This works because migrations is inside `src/watchdirs/db/` and the `resources` api resolves relative to the package. No issue, just confirming the pattern.

### Suggestions

- Add error handling in the collect loop: wrap `insert_snapshot_mounts()` + `finalize_snapshot()` in a single try/finally block so a mount-insert failure rolls back the entire snapshot.
- Document in the plan that `options` and `super_options` are intentionally excluded from `SnapshotMount`.
- Consider adding a `finished_at_epoch` column to the `snapshots` table or computing it from `finished_at` in queries. The pair-selection logic in later plans relies on time arithmetic that is simpler with an epoch integer than ISO timestamp parsing.

### Risk Assessment: **LOW**

The schema change is well-understood, the migration path is trivially testable, and the wire-up point is clear. The main risk is a missing rollback on mount-insert failure.

---

## 02-02-PLAN.md — Top Latest Current-Usage Report

### Summary

Implements `watchdirs top --snapshot latest --limit N --json` as the first report slice, exercising the grouping infrastructure before cross-snapshot diff is added. Good sequencing: validates the reporting package skeleton and render patterns on the simpler single-snapshot case.

### Strengths

- **Whitelist-only `--group-by`** — `root`, `top-level-subtree`, `mount`, `storage-domain` choices through argparse; no raw SQL injection surface.
- **Good use of existing indexes** — `directory_sizes_snapshot_size_idx ON directory_sizes(snapshot_id, disk_bytes)` directly supports the primary sort.
- **Consistent field naming** — `current_disk_bytes` and `current_apparent_bytes` avoid ambiguity between absolute and delta values (D-08).
- **Includes BOTH `path_bytes_hex`** and decoded path in output, preserving lossless identity and agent readability.

### Concerns

- **[HIGH]** `resolve_top_level_subtree_group()` needs the snapshot's `root_path` to compute "first path segment below root". The plan does not specify how this root path reaches the grouping function. It must be either passed as a parameter or derived from the snapshot record. The function signature in the artifacts table doesn't include a root path parameter.
- **[MEDIUM]** No error path for invalid numeric snapshot IDs passed to `resolve_snapshot_selector()`. If the user passes `--snapshot 99999` and no such snapshot exists, what happens? Should return a structured error, not a SQL `None` that silently produces empty output.
- **[MEDIUM]** Longest-prefix mount matching in Python: for N paths and M mounts per snapshot, this is O(N\*M) with byte-level comparison. For a root with 50,000 directories and 30 mounts, that's 1.5M comparisons. Acceptable for a local CLI tool, but worth a comment in the code.
- **[LOW]** `resolve_snapshot_selector(connection, "latest")` selects the newest non-failed snapshot. If there are NO non-failed snapshots (all failed), the behavior is undefined. Should return a structured error.

### Suggestions

- Make `resolve_top_level_subtree_group(path_bytes, root_path_bytes)` explicitly receive the root path as a parameter.
- Add error codes `snapshot_not_found` and `no_usable_snapshots` to `resolve_snapshot_selector()`.
- Consider adding the compact "why this may not match df" note (from CONTEXT.md specifics) to `top` output when disk_bytes vs apparent_bytes diverge significantly — but only as a small inline note, not a full reconciliation.

### Risk Assessment: **LOW-MEDIUM**

The single-snapshot case is simpler than cross-snapshot diff. The main gaps are unspecified error paths and unclear function signatures.

---

## 02-03-PLAN.md — Diff Pairing, Classifications, and Growth Frontier

### Summary

The core of Phase 2. Implements `watchdirs diff --since 24h --limit N --json` with per-root snapshot pairing, SQL-based classification, and Python-based frontier pruning. This is the most complex plan and the one that delivers the primary incident workflow (D-01).

### Strengths

- **Thorough pair selection** — handles exact-boundary baseline, fallback with `baseline_before_since_unavailable` warning, no-pair error, partial snapshot inclusion, and failed snapshot exclusion. The four resolved research questions are directly encoded.
- **Two-stage pipeline is correct** — SQL for normalized diff rows (what changed), Python for frontier pruning (what to show). This avoids the documented SQLite limitation that recursive CTEs can't use aggregate/window functions.
- **Good classification in SQL** — `created`, `deleted`, `grown`, `shrunk`, `unchanged` from a single CTE over `path UNION` baseline/current paths with `LEFT JOIN` on each.
- **Threat model covers the right surface** — T-02-12 (cross-root pairing spoofing) is correctly identified and mitigated.

### Concerns

- **[HIGH] Frontier pruning is underspecified.** The plan says "suppresses near-duplicate ancestor/descendant rows" but does not define the pruning algorithm. What makes two rows "near-duplicate"? Is it when `|parent_delta - child_delta| < threshold`? Is it when the child accounts for >90% of the parent's growth? Without a concrete algorithm, the tests in Task 1 can't meaningfully assert correct behavior, and the implementation in Task 2 will be ambiguous. Suggestion: define it as: "when a path P has a descendant D such that `|disk_bytes_delta(D) - disk_bytes_delta(P)| / max(disk_bytes_delta(D), 1) < 0.05` (i.e., deltas are within 5%), keep only the deepest one and record `suppressed_descendant_count`."
- **[HIGH] `parse_since()` duration grammar is unspecified.** What units are supported? `h`, `d`, `m`, `s`? Combinations like `1h30m`? Negative values? Zero? The plan only mentions examples. Suggestion: define the grammar as `integer + unit` where unit is one of `s|m|h|d`, reject combinations and negative values, minimum 1 second.
- **[MEDIUM] Multi-root output merging.** The diff command merges per-root pairs. But rows from different roots have different baseline/current snapshots. Should the JSON output separate them by root? The plan says "merges valid same-root pair outputs only after pair selection" — this could mean interleaving rows from different roots into one flat list, which is confusing when each row references different pair metadata. Suggestion: include per-root pair metadata separately, and include `root_path` in each row so the agent can correlate.
- **[MEDIUM] The `forever` delta problem.** A path that exists in the baseline as 0 bytes and in the current as 0 bytes is correctly classified as `unchanged`. But a path absent from baseline with 0 bytes in current is `created` with delta=0. Should `created` with 0 delta be shown? The plan says the default frontier includes "`created` and `grown` rows with positive `disk_bytes_delta`", which correctly excludes zero-delta created rows.
- **[LOW] SQL CTE performance.** The `path UNION` + two `LEFT JOIN` pattern on `directory_sizes` where `path` is BLOB needs the query planner to use `directory_sizes_path_snapshot_idx(path, snapshot_id)`. With WAL mode and the existing index, this should be efficient for typical snapshot sizes (tens of thousands of rows).

### Suggestions

- Specify the frontier pruning algorithm concretely: percentage-of-parent threshold, tie-breaking by depth, suppression count recording.
- Specify the `--since` duration grammar: `INTEGER{s|m|h|d}`, no combinations, no negatives, minimum 1s.
- Structure diff JSON output as `{"pairs": [{root, baseline, current, warnings}], "rows": [...]}` with `root_path` in each row rather than a flat merge.
- Consider adding a `--include-shrunk` flag (default off) for when the agent wants to see what got smaller.

### Risk Assessment: **MEDIUM**

The pair selection is well-specified, the SQL classification pattern is correct, but the frontier algorithm is underspecified and that's the product-differentiating feature (D-10, D-11). Fixing the spec before implementation eliminates the main risk.

---

## 02-04-PLAN.md — Report, Deleted, Explain-Path, and Final Verification

### Summary

Completes the Phase 2 command surface. `report` composes the earlier diff/frontier pipeline into a structured summary, `deleted` filters to baseline-only paths, and `explain-path` provides focused subtree drill-down. Task 3 runs final verification.

### Strengths

- **Good reuse of earlier work** — `report` uses `resolve_snapshot_pairs()` from 02-03 and `prune_growth_frontier()` from 02-03, avoiding duplication.
- **`explain-path` residual delta concept** — computing growth not explained by shown children is exactly the right signal for "keep drilling here."
- **`deleted` is first-class** — uses baseline-only `LEFT JOIN` rather than inferring from negative deltas, matching the research recommendation.
- **Consistent BLOB path handling** — all query boundaries preserve raw bytes, decode only at render.

### Concerns

- **[HIGH] `explain-path` residual computation needs clarification.** The parent row's `disk_bytes_delta` includes all descendants (recursive aggregation). If all children are shown, the residual is zero. If children are capped (by `--limit` or `--depth`), the residual is `parent_delta - sum(shown_child_deltas)`. But child deltas are also recursively aggregated. If a child `A` has children `A/B` and `A/C`, and only `A` is shown, the residual might look like `A` accounts for all the growth. This is correct behavior but must be documented so agents interpret residuals correctly.
- **[MEDIUM] `report` command overlaps with `diff`.** The plan says `report` returns "top frontier, classification summary, group summary, deleted preview" — much of which mirrors `diff`, `deleted`, and group-by summaries. The added value is the aggregation (classification counts/sums, group summaries). This is reasonable but the plan should justify why this isn't just `diff` with a `--summary` flag.
- **[MEDIUM] `--depth` for `explain-path`.** The plan says it "caps child output" but doesn't specify what `--depth` means. Is it maximum descendant depth relative to the target? Or maximum tree depth from root? The plan should specify: `--depth N` means show descendants up to N levels below the target path.
- **[LOW] Text output for `report`.** The plan says text should be "terse and labeled" but `report` has many sections. A verbose text output that lists all sections could be longer than useful. Consider making text output show only the top frontier + warnings by default, with `--verbose` for the full breakdown.

### Suggestions

- Specify `explain-path --depth N` as: show descendants up to N levels below the target (target = depth 0).
- Document residual semantics: residuals are meaningful only when children are capped; when all children are shown, residual = 0.
- Consider consolidating `report` as `diff --summary` rather than a separate command, unless there's a clear UX reason. Or keep both but make `report` output the summary head with `diff` available for details.
- For text output, default to top 5 frontier rows + classification counts; use `--verbose` for full sections.

### Risk Assessment: **MEDIUM**

The residual delta semantics ambiguity is the main risk. The commands otherwise correctly compose the pipeline from earlier plans. The `report`/`diff` overlap is a product decision, not a technical risk.

---

## Cross-Cutting Concerns

### Missing Across All Plans

1. **[MEDIUM] No sample JSON output schemas.** The plans list field names but don't show example payloads. A concrete example for `diff`, `top`, and `report` would help validate completeness. For instance, does `diff` output include `snapshot_pair` per row or once at top level? Both approaches are valid but the choice affects the JSON contract.

2. **[MEDIUM] No integration test for the end-to-end incident workflow.** The plans test individual commands but don't specify a test that simulates the actual incident: create snapshot at T-24h, grow some directories, create snapshot at T, run `diff --since 24h`, verify the growth is detected. This E2E test would be the strongest validation that Phase 2 achieves its goal.

3. **[LOW] The `collect` --mountinfo test in 02-01 Task 1 Test 3** specifies `./watchdirs collect --mountinfo <fixture> --json`. The existing collect tests use `run_module()` and `run_repo_local()` helpers. The plan should reference these existing helpers rather than assuming a raw shell invocation.

4. **[LOW] `path_bytes_hex` field.** All plans include this field but it's never explained in the output contract. It's the hex representation of the raw BLOB path, useful for non-UTF-8 paths. Worth documenting once.

### Dependency Order Assessment

The strict wave ordering (01 → 02 → 03 → 04) is mostly justified:

- Wave 1 (mount persistence) must precede all others because grouping requires the `snapshot_mounts` table.
- Wave 2 (top command) is a good stepping stone before the more complex diff — it validates the reporting package, renderer, and grouping.
- **However**, Wave 2 and Wave 3's task 1 (test writing) could potentially run in parallel, since the tests only need the schema from Wave 1 and can use synthetic data. The wave dependency is conservative but not harmful for a 4-plan phase.

### Scope Discipline Assessment

The plans correctly avoid:
- No Phase 3 diagnostics (deleted-open files, df reconciliation, Docker enrichment)
- No Phase 4 operations (systemd timers, retention, pruning)
- No trend analysis, forecasting, or BI summaries
- No new external package dependencies

One grey area: the `--group-by storage-domain` selector is mentioned throughout but there's no plan for how a "storage domain" differs from a "mount" in the v1 data model. The plans should either define it or defer it.

---

## Overall Risk Assessment: **MEDIUM**

**Justification:** The architecture is sound — per-root pair selection, SQL classification, Python frontier pruning, persisted mount metadata, and BLOB-safe path handling are all correct decisions grounded in the existing codebase. The phase goal is achievable with these plans. The main risks are:

1. **Underspecified frontier algorithm** in 02-03 — this is the product's differentiating feature and needs concrete rules before implementation.
2. **Underspecified `parse_since()` grammar** — a small but user-facing detail that breaks the CLI contract if inconsistent.
3. **Ambiguous `explain-path` residual semantics** in 02-04 — easy to clarify in the plan, misleading if implemented wrong.

If these three items are clarified before execution, the overall risk drops to **LOW**. The plans otherwise demonstrate good understanding of the codebase, correct reuse of Phase 1 seams, and disciplined scope management.

---

## Consensus Summary

Both reviewers found the Phase 02 sequence directionally sound: persist snapshot-time mount metadata first, prove a simpler `top` command, implement same-root diff/classification/frontier behavior, then compose `report`, `deleted`, and `explain-path` from the same pipeline. They agreed the plans preserve the important project boundaries: JSON-first output, disk-byte-primary semantics, BLOB-safe paths, persisted grouping evidence, no Phase 3 df/Docker diagnostics, and no Phase 4 operations work.

### Agreed Strengths

- Wave ordering is coherent: grouping persistence precedes current-usage reporting, and `top` precedes cross-snapshot diff complexity.
- Same-root snapshot pairing, partial/failure warnings, failed-snapshot exclusion, and explicit snapshot metadata are well represented.
- The SQL classification plus Python frontier-pruning split is a good fit for SQLite and keeps the product logic testable.
- The plans consistently preserve path bytes until render time and expose `path_bytes_hex` for lossless agent evidence.
- Scope discipline is strong: diagnostics, Docker enrichment, retention, scheduling, forecasting, and BI output remain deferred.

### Agreed Concerns

- **HIGH:** The frontier pruning contract is not concrete enough. PLAN.md should define the suppression threshold, tie-break rule, and suppression-count semantics before implementation.
- **HIGH:** `explain-path` semantics need tighter detail around path matching and residual math over recursive aggregates, especially when children are capped by `--limit` or `--depth`.
- **HIGH:** `top --snapshot latest` has unresolved multi-root semantics. PLAN.md should state whether `latest` means one newest snapshot globally, latest per root, or requires/accepts a root selector.
- **MEDIUM:** `storage-domain` is available as a grouping selector, but PLAN.md should define its key and label contract distinctly from raw mount labels.
- **MEDIUM:** CLI error and validation contracts should be made explicit for missing snapshot ids, no usable snapshots, invalid/huge limits, and `--since` grammar.
- **MEDIUM:** Concrete sample JSON payloads for `top`, `diff`, `report`, and `explain-path` would make the command contracts easier to validate.

### Divergent Views

- Codex rated 02-03 and 02-04 as higher risk than OpenCode, mainly because it saw global multi-root limit behavior, deleted-row pruning, report double-counting, and final-wave size as possible sources of misleading output.
- OpenCode was more positive on 02-01 migration and top-level grouping, but raised implementation-shaped concerns such as rollback behavior around `insert_snapshot_mounts()` and explicit function signatures for root-relative grouping.
- Codex pushed for potentially splitting 02-04; OpenCode viewed the wave as acceptable if residual semantics and command overlap are clarified.

### Convergence Contract

- `current_high=4`
- `current_actionable=11`

#### Current HIGH Concerns

1. Define the exact `prune_growth_frontier()` algorithm in `02-03-PLAN.md`: threshold, ancestor/descendant comparison, tie-breaks, and `suppressed_descendant_count` semantics.
2. Clarify `explain-path` path matching in `02-04-PLAN.md`: exact vs subtree behavior, `os.fsencode()` boundary, trailing slashes/normalization, outside-root errors, and not-indexed errors.
3. Clarify `explain-path` residual math in `02-04-PLAN.md`: recursive aggregate interpretation, immediate-child subtraction, and behavior when child output is capped.
4. Resolve `top --snapshot latest` multi-root semantics in `02-02-PLAN.md`: one global snapshot, latest per root, or explicit root selection.

#### Current Actionable Non-HIGH Concerns

1. Add explicit schema migration assertions in `02-01-PLAN.md` for preserving existing v1 rows and updating `PRAGMA user_version` only after successful migration.
2. Add explicit foreign-key enforcement/cleanup verification in `02-01-PLAN.md` for `ON DELETE CASCADE` on `snapshot_mounts`.
3. Define the `storage-domain` key and label contract in `02-01-PLAN.md` or `02-02-PLAN.md`, distinct from raw `mount` labels.
4. Document why `MountInfo.options` and `super_options` are intentionally omitted from persisted `SnapshotMount` rows in `02-01-PLAN.md`.
5. Add rollback/all-or-nothing behavior for `insert_snapshot_mounts()` failure inside collection in `02-01-PLAN.md`.
6. Add structured errors in `02-02-PLAN.md` for invalid numeric snapshot id and no usable non-failed snapshots.
7. Specify `--limit` validation and cap behavior in `02-02-PLAN.md`/`02-03-PLAN.md`: positive integer, compact default, maximum cap, JSON error.
8. Specify `--since` grammar in `02-03-PLAN.md`: accepted units, invalid combinations, zero/negative handling, and timestamp basis.
9. Clarify global merge/limit behavior for multi-root `diff` in `02-03-PLAN.md`: merge all valid pair candidates before frontier pruning and applying the final global limit.
10. Add sample JSON payloads or schema sketches for `top`, `diff`, `report`, `deleted`, and `explain-path` to the relevant PLAN.md files.
11. Add one end-to-end incident workflow test to `02-04-PLAN.md`: baseline snapshot, directory growth, current snapshot, `diff --since 24h`, and verification of detected growth.

---

# Cross-AI Plan Review - Phase 02 - Cycle 2

Reviewed at: 2026-06-13T16:13:45+05:00

Reviewed current checkout: `ad4ab86 docs(02): incorporate review feedback into plans`

Reviewers: Codex, OpenCode

## Cycle 2 Codex Review

### Summary

Reviewed the checked-out Phase 02 plans at `ad4ab86`. The revision is substantially stronger than the first cycle: multi-root `latest`, strict `--since` grammar, storage-domain keying, frontier thresholding, exact `explain-path` matching, cascade/migration tests, and deferred-scope boundaries are now represented in the plan content. Overall the phase is achievable and well sequenced. The remaining risks are mostly implementation feasibility and scale: transaction semantics in the existing DB helpers, potentially quadratic frontier pruning, and the large final wave.

### Strengths

- The wave order is sound: persisted mount metadata, then `top`, then `diff`, then composed workflows.
- JSON contracts are explicit and agent-friendly, with clear `current_*`, `previous_*`, and `*_delta` naming.
- The revised plans correctly avoid live-only mount inference and durable `mount_id` identity.
- Same-root pair selection, partial snapshot visibility, failed snapshot exclusion, and fallback baseline warnings are now well specified.
- Scope control is good: no Docker enrichment, deleted-open-file diagnostics, df reconciliation, scheduling, retention, or capacity planning creep.
- Tests are planned before implementation and cover important edge cases: BLOB paths, segment boundaries, multi-root ranking, limit validation, and exact path errors.

### Concerns

- **HIGH:** `02-01-PLAN.md` requires directory rows plus mount rows to be all-or-nothing, but current helpers commit inside `create_snapshot`, `insert_directory_rows`, and `finalize_snapshot`. The plan should explicitly include refactoring commit ownership or adding no-commit persistence helpers; otherwise rollback tests may be hard to satisfy cleanly.
- **MEDIUM:** `02-03-PLAN.md` says merge all raw candidates before frontier pruning. Correct behaviorally, but a naive ancestor/descendant scan can become O(n^2) on large root snapshots. This is acceptable for v1 only if implemented with sorted path bytes, parent maps, or bounded candidate filtering after classification.
- **MEDIUM:** `02-04-PLAN.md` is still a large final wave: three commands, summaries, deleted rows, explain-path, residual math, path normalization, grouping, text renderers, and final verification. It is planned well, but it has the highest integration risk.
- **MEDIUM:** Path normalization rules for `explain-path` are precise, but they need to align with collection-time root/path encoding. The implementation should share a helper or tests may pass while real CLI paths miss indexed rows.
- **LOW:** `top` and diff grouping load persisted mounts and perform longest-prefix matching. Fine for small mount tables, but tests should include rows outside any persisted mount and define the fallback group/error shape.
- **LOW:** The end-to-end `diff --since 24h` test in `02-04-PLAN.md` will likely exercise the fallback baseline path if snapshots are seconds apart. The expected warning should be asserted explicitly.

### Suggestions

- Add a small explicit subtask in 02-01: make snapshot creation, directory row insert, mount row insert, and finalization transaction-compatible, with tests proving committed directory rows are not left behind after mount insert failure.
- For frontier pruning, implement around path ordering or parent maps rather than pairwise descendant checks over all candidates.
- Consider splitting 02-04 execution internally: first `deleted` + `report`, then `explain-path`, while keeping the same plan file if the workflow requires four waves.
- Add one shared path-normalization helper used by scanner-adjacent tests and `explain-path`, covering trailing slash, `.` segments, relative paths, and non-UTF-8/surrogate paths.
- Add fallback behavior for grouping when no `snapshot_mounts` row matches a path, such as `group: null` plus a warning or `kind="unknown"`.

### Risk Assessment

**MEDIUM.** The plans now cover the phase goals and most previously ambiguous semantics. The main remaining risk is not product scope or missing requirements; it is implementation complexity against the current transaction model and the cost of pruning/reporting over full recursive aggregate snapshots. Tightening those two points before execution should make the phase low-to-medium risk.

## Cycle 2 OpenCode Review

### Summary

OpenCode reviewed the current plans at `ad4ab86` after the convergence revision cycle and found the previous review's 4 HIGH and 11 actionable concerns systematically addressed across all four plans. It assessed the phase as execution-ready with low overall risk, while identifying a few remaining implementation details to clarify before execution.

### 02-01-PLAN.md

**Summary:** A tight schema extension that now explicitly covers migration, FK cascade, all-or-nothing rollback, storage-domain identity, and options omission justification. Ready to execute.

**Strengths:**

- Storage-domain contract defines `mount` vs `storage-domain`, durable key fields, and omission of `options`/`super_options`.
- Migration coverage preserves v1 rows, checks idempotence, and constrains `PRAGMA user_version` timing.
- FK cleanup coverage requires `PRAGMA foreign_keys=ON`; current `open_connection()` already enables it.
- All-or-nothing persistence is represented by tests and implementation actions.

**Concerns:**

- **LOW:** `run_collect()` persists the same mount table passed to `scan_root()`, which means all mounts are stored per snapshot, not just root-relevant mounts. This is correct for full storage-domain context but increases row volume.

**Suggestions:**

- Add an optional mount-row count to snapshot payload/debug output.
- Consider later plans using `snapshot_mounts_snapshot_domain_idx` explicitly for `storage-domain` grouping queries.

**Risk Assessment:** **LOW**

### 02-02-PLAN.md

**Summary:** Well revised. `latest` semantics are now per-root with sections, function signatures include `root_path_bytes`, selector and limit errors are defined, and the JSON contract anchors the output shape.

**Strengths:**

- `resolve_top_snapshot_selection()` is precise: `latest` returns one section per root, numeric IDs return one section, and selector errors are enumerated.
- `parse_report_limit()` is explicit: default 20, accepted 1..1000, distinct error codes.
- BLOB-safe grouping uses root-relative segment boundaries and stable root labels.
- `storage-domain` label is distinct from `mount` and includes the required identifying fields.

**Concerns:**

- **MEDIUM:** `finished_at` is stored as ISO text; `top` avoids this, but later `diff` pair selection needs epoch arithmetic.
- **LOW:** Test coverage should define behavior when no mount point matches a path, even if `/` usually exists.

**Suggestions:**

- Test the edge case where a path is not covered by any persisted mount besides `/`.
- Consider whether `root` and `top-level-subtree` grouping produce distinct output when the tracked root is `/`.

**Risk Assessment:** **LOW**

### 02-03-PLAN.md

**Summary:** The biggest transformation from the previous review. The frontier algorithm is fully specified with a concrete dominance ratio, deterministic tie-breaks, suppression counts, and the multi-root merge-before-limit contract.

**Strengths:**

- Frontier algorithm is concrete: `FRONTIER_DOMINANCE_RATIO = 0.95`, deterministic suppression, sorting, and counts.
- Suppression counts are well-defined and exclude deleted/shrunk/unchanged/zero-delta rows.
- `parse_since()` grammar is strict and explicit.
- Multi-root merge-before-limit prevents one root from hiding a larger row from another root.
- `--since` uses selected current snapshot `finished_at`, not wall-clock time.

**Concerns:**

- **MEDIUM:** The `snapshots.finished_at` field is ISO text, while `--since` requires epoch arithmetic. The plan should decide whether to parse ISO in Python, add a numeric `finished_at_epoch`, or use SQLite conversion, and tests should verify UTC handling.
- **LOW:** Frontier pruning must annotate each candidate with root/pair metadata so suppression never crosses root or pair boundaries.
- **LOW:** The strict regex rejects leading zeros such as `01h`; this is acceptable if intentional.
- **LOW:** Existing indexes may be enough initially, but large snapshots may expose query cost in the BLOB path union and joins.

**Suggestions:**

- Decide and document the `finished_at` text-to-epoch conversion path; adding `finished_at_epoch INTEGER` in schema v2 is the cleanest option if chosen now.
- Include explicit epoch or parsed datetime in pair-selection metadata.

**Risk Assessment:** **LOW**

### 02-04-PLAN.md

**Summary:** The most complex plan now has detailed path matching, residual math, depth caps, structured errors, and an end-to-end workflow test.

**Strengths:**

- `explain-path` normalization covers `~`, relative paths, trailing slash removal, `.` normalization, `os.fsencode()`, segment-boundary root matching, and exact target rows.
- Residual math is clearly defined: target delta minus shown immediate-child deltas only.
- `deleted` is first-class baseline-only evidence, sorted and limited, not frontier-pruned.
- `report` group summary avoids recursive double-counting by using frontier rows or another one-row-per-group slice.
- End-to-end incident workflow test is planned.

**Concerns:**

- **MEDIUM:** `classification_summary` sums disk/apparent deltas across all raw diff rows. Because directory aggregates are recursive, these sums can double-count parent/child overlap. The plan should either document that overlap or compute classification totals from frontier rows too.
- **MEDIUM:** `report` output includes many sections. The plan says reports should be compact, so text output should stay terse by default.
- **LOW:** `explain-path` should include depth in output so agents can interpret residual math when `--depth` is greater than 1.
- **LOW:** Multi-root `explain-path` ambiguity appears intentional but should remain a structured `ambiguous_root` error.
- **LOW:** Deleted paths should be valid `explain-path` targets because the plan says the target row can come from the current/baseline union; this should remain explicit during execution.

**Suggestions:**

- Document whether `classification_summary` raw sums may exceed actual disk change because of recursive aggregates, or compute them from a non-overlapping slice.
- Add a `depth` field to `explain-path` output.
- Clarify that deleted paths are valid explain targets.

**Risk Assessment:** **LOW-MEDIUM**

### Overall Risk Assessment

**LOW.** Every HIGH concern from the first review cycle has a concrete specification in the plan text. The one remaining MEDIUM concern OpenCode considered material is `finished_at` epoch conversion, which should be decided before writing code.

## Cycle 2 Consensus Summary

The second cycle shows strong convergence. Both reviewers agree that the first cycle's major semantic gaps are now represented in the current `PLAN.md` files: multi-root `latest`, global diff merge/limit, concrete frontier suppression, exact `explain-path` matching, residual math, migration/cascade tests, storage-domain identity, JSON contracts, and deferred Phase 3/4 boundaries.

Under the requested counting rules, old cycle 1 concerns are excluded when the revised plans now cover them. Suggestions that are already present in the current plans are also excluded, including path normalization, deleted output as first-class baseline evidence, `explain-path` depth in the JSON contract, and root/pair boundaries in frontier pruning.

### Current HIGH Concerns

1. **02-01 transaction-compatible persistence remains under-specified against current helper behavior.** The current plan requires all-or-nothing directory plus mount persistence, but the existing persistence helpers commit inside `create_snapshot()`, `insert_directory_rows()`, and `finalize_snapshot()`. Add an explicit PLAN.md task to refactor commit ownership or introduce no-commit helper variants so the rollback/failure-state requirement is mechanically executable.

### Current Actionable Non-HIGH Concerns

1. **02-03 frontier pruning performance strategy.** Add a PLAN.md instruction to avoid naive O(n^2) ancestor/descendant pruning over full snapshots by using sorted path bytes, parent maps, or bounded positive candidates after classification.
2. **02-03 `finished_at` arithmetic.** Add a PLAN.md decision for converting ISO `finished_at` text to the cutoff basis used by `--since` pair selection, including UTC handling tests; options are Python parsing, SQLite conversion, or a schema v2 `finished_at_epoch` column.
3. **02-02/02-03 mount grouping fallback.** Add a PLAN.md test/contract for rows with no matching persisted mount row, such as `group: null`, `kind="unknown"`, or a warning, so mount/storage-domain grouping cannot silently mislabel unmatched rows.
4. **02-04 `classification_summary` recursive aggregate semantics.** Add a PLAN.md note deciding whether classification delta sums are raw recursive-row sums that may overlap, or are computed from a non-overlapping/frontier slice.

### Convergence Contract

- `current_high=1`
- `current_actionable=4`
