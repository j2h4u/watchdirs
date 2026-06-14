# Phase 03 Plan Reviews

**Reviewed:** 2026-06-14
**Cycle:** 1
**Reviewers:** opencode, claude
**Verdict:** CHANGES_REQUESTED

## CYCLE_SUMMARY

External review found the phase direction sound, but not yet converged. The blocking issue is the `df-vs-index` aggregation model in `03-01-PLAN.md`: using only a snapshot root aggregate row and comparing it to whole-filesystem `statvfs()` can misattribute bytes across nested mounts and produce false deleted-open suspicion on partially indexed filesystems.

Counts:
- HIGH: 1
- MEDIUM: 3
- LOW: 3
- Blocking/actionable before execution: 4

Required replan:
- Fix `df-vs-index` indexed totals to aggregate per storage-domain using persisted mount-point evidence and nested-mount subtraction, not one root aggregate per snapshot.
- Add explicit partial-filesystem-coverage evidence so unattributed bytes from unindexed filesystem scope do not automatically become deleted-open suspicion.
- Add deterministic procfs injection for deleted-open fallback tests.
- Make containerd output honest: path hints and explicit unavailable warning unless a real containerd category probe is implemented.

## Reviewer: claude

### Verdict

CHANGES_REQUESTED

### Findings

#### HIGH - `df-vs-index` per-domain attribution is computed from the single root aggregate row and compared to whole-filesystem `statvfs`

**References:** `03-01-PLAN.md` Task 1 and Task 2; propagated to `03-04-PLAN.md` report hints.

The plan tells executors to identify the root aggregate row and sum only one root aggregate per selected snapshot into a storage-domain total. This breaks the multi-filesystem case because one indexed root can span several mounted storage domains, while Phase 2 persisted `snapshot_mounts` specifically to group rows by longest mount prefix. A root aggregate can include nested mount bytes and then be attributed wholly to the root mount.

The plan also compares indexed scope against whole-filesystem `statvfs()` scope. If the configured indexed root is only a subtree of the filesystem, the remainder mostly means "outside indexed scope", not deleted-open/Docker/reserved bytes. If `03-04` fires `deleted_open_file_suspected` on that remainder, it will create systematic false positives.

**Required fix:** Before RED tests, revise `03-01` so indexed bytes are computed per storage-domain from persisted mount-point evidence with nested-submount subtraction or an equivalent non-overlapping aggregation. Call `statvfs()` per storage-domain mount point. Add explicit partial-filesystem-coverage fields/likely reason, and gate deleted-open suspicion so partial filesystem coverage does not masquerade as deleted-open usage.

#### MEDIUM - deleted-open procfs fallback needs an injection seam

**References:** `03-02-PLAN.md` Task 1 and Task 2.

The plan promises synthetic procfs fixtures, but the implementation action describes iterating real `/proc/<pid>/fd` through `Path.readlink()`/`os.readlink()` without a proc-root parameter. Without injectable procfs root and lsof runner seams, fallback tests become host-coupled or incomplete.

**Required fix:** Add an injectable proc-root and lsof runner to the deleted-open collector/parser contract, matching the existing fake-provider style in other plans.

#### LOW - containerd category evidence is overpromised relative to Docker-only tooling

**References:** `03-03-PLAN.md` must-haves and Task 2.

The plan claims detectable containerd categories, but the chosen probes are Docker CLI output plus persisted path hints. That can explain Docker-owned data, not standalone containerd usage under `/var/lib/containerd`.

**Required fix:** Soften the must-have to containerd path hints only unless a real containerd probe is implemented. Emit explicit `containerd_enrichment_unavailable` when containerd paths are present but no containerd category probe exists.

## Reviewer: opencode

### Verdict

APPROVE with actionable clarifications

### Findings

#### MEDIUM - `over_indexed_bytes` must be explicit in dataclass/render/tests

**References:** `03-01-PLAN.md` contract.

The plan adds `over_indexed_bytes`, while the research JSON sample omitted it. This field is useful for snapshot skew or indexed-greater-than-filesystem cases but can be missed by implementers.

**Required fix:** Explicitly require `over_indexed_bytes` in dataclasses, renderers, and tests, including an indexed-greater-than-df case.

#### MEDIUM - containerd path hints need an explicit unavailable warning

**References:** `03-03-PLAN.md`.

If `/var/lib/containerd` appears in indexed paths but the tool only has Docker CLI evidence, the output should say that containerd category enrichment is unavailable instead of being silent.

**Required fix:** Add `containerd_available: false` or equivalent plus `containerd_enrichment_unavailable` warning when containerd paths are detected without a containerd probe.

#### LOW - clarify same-root snapshot aggregation

**References:** `03-01-PLAN.md`.

The plan should clarify that `df-vs-index` selects one current snapshot per root under `latest`, and the multi-domain test should use distinct roots or distinct mount domains rather than accidental double-counting across multiple snapshots of the same root.

**Required fix:** Clarify one selected current snapshot per configured root; test distinct roots/domains instead of multiple same-root current snapshots.

#### LOW - report-time `statvfs()` should be scoped to indexed storage domains

**References:** `03-04-PLAN.md`.

The plan says report runs cheap `statvfs()` reconciliation but should explicitly prevent iterating every live mount on the host.

**Required fix:** Specify report context only calls `statvfs()` for storage domains returned by the indexed-total query.

## Convergence Decision

Replan required. The next plan revision must address the HIGH finding and the actionable MEDIUM items before another external review cycle.

---

# Cycle 2 Review

**Reviewed:** 2026-06-14
**Reviewers:** opencode, claude
**Verdict:** CHANGES_REQUESTED

## CYCLE_SUMMARY

Cycle 2 confirmed the Cycle 1 blockers were resolved: nested-mount attribution, partial filesystem coverage gating, indexed-only `statvfs()` calls, explicit `over_indexed_bytes`, injectable deleted-open probes, honest containerd path-hint behavior, and compact read-only output all passed reviewer checks.

One new actionable MEDIUM gap remains: per-domain `statvfs()` failure handling is unspecified. Because snapshots can outlive mount paths, one stale persisted mount point could currently abort `df-vs-index` or `report` instead of producing partial diagnostic evidence.

Counts:
- HIGH: 0
- MEDIUM: 1
- LOW: 1
- Blocking/actionable before execution: 1

Required replan:
- Add a `statvfs()` failure contract and RED test: per-domain `OSError` becomes a warning/coverage reason such as `filesystem_stat_unavailable`, and the command continues without aborting the whole diagnostic.
- Optionally clarify partial snapshot behavior in deleted-open suspicion gating.

## Reviewer: opencode

### Verdict

APPROVE

### Findings

No actionable findings.

## Reviewer: claude

### Verdict

APPROVE with one actionable MEDIUM

### Findings

#### MEDIUM - `statvfs()` failure on stale or absent persisted mount points is unspecified

**References:** `03-01-PLAN.md` Contract and Task 2; inherited by `03-04-PLAN.md` report-time df/index hints.

The diagnostic resolves each storage-domain to a live path and calls `statvfs()`. A persisted mount point may no longer exist or may now refer to a different filesystem. The plans specify graceful degradation for `lsof` and Docker probes but not for per-domain `statvfs()` failure. One stale storage-domain could crash an otherwise useful command.

**Required fix:** Add contract text and a RED test: a per-domain `statvfs()` `OSError` degrades that domain to a warning plus coverage reason code, for example `filesystem_stat_unavailable`, and does not abort `df-vs-index` or `report`.

#### LOW - deleted-open gating keys on scope geometry, not partial snapshot status

**References:** `03-01-PLAN.md` Contract; `03-04-PLAN.md` Task 2.

The revised plan gates deleted-open suspicion on filesystem coverage geometry, but a full-root snapshot with `status=partial` can still omit subtrees because of scan errors. The plans already carry partial snapshot counters and skipped/partial scan evidence, so this is not blocking.

**Optional fix:** Clarify whether non-complete snapshots count as non-full coverage for suspicion, or assert that partial snapshot evidence appears alongside any suspicion.

## Convergence Decision

Replan required for the actionable MEDIUM `statvfs()` degradation gap before another review cycle.
