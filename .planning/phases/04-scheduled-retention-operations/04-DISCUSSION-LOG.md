# Phase 4: Scheduled Retention Operations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-17
**Phase:** 4-scheduled-retention-operations
**Areas discussed:** Product goal, failure posture, retention policy, cleanup-window snapshots, expert panel convergence

---

## Product Goal

| Option | Description | Selected |
|--------|-------------|----------|
| Fresh retained evidence | Guarantee a fixed recency/retention window exists. | |
| Fast disk-pressure explanation | Optimize for the agent quickly understanding why disk space is running out. | ✓ |
| Low-impact background operation | Optimize primarily for not disturbing the host. | |

**User's choice:** "I don't know. The main thing is that my agent can understand as quickly as possible why disk space is running out."
**Notes:** Captured as the primary product guarantee: fast explanation under disk pressure, with freshness/gap signals as supporting requirements.

---

## Failure Posture

| Option | Description | Selected |
|--------|-------------|----------|
| Fail fast | Missed or failed scheduled collection should be visible immediately through systemd/journal/verification. | ✓ |
| Warn later | Preserve previous history and surface warning only in later reports. | |
| Best effort | Skip failed runs quietly unless data corruption is possible. | |

**User's choice:** fail fast.
**Notes:** Existing history must be preserved, but evidence gaps should be obvious and operationally visible.

---

## Retention Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Hourly only | Simple single TTL window. | |
| Hourly + daily | README baseline without longer-term monthly retention. | |
| Hourly + daily + monthly | Hourly 14 days, daily 90 days, then monthly representative snapshots. | ✓ |

**User's choice:** "hourly 14 days + daily 90 days + the rest monthly."
**Notes:** Expert panel converged that monthly should mean representative full snapshots, not rollup summaries.

---

## Cleanup-Window Snapshots

| Option | Description | Selected |
|--------|-------------|----------|
| Include now | Automatically collect before/after cleanup windows. | |
| Defer | Treat cleanup-window snapshots as a future capability outside Phase 4. | ✓ |
| Planner discretion | Let planner decide if it falls out cheaply. | |

**User's choice:** User did not understand the concept; panel treated it as scope creep and deferred it.
**Notes:** Clarification: the idea was collecting a snapshot before and after cleanup commands so cleanup effects are explicit. Deferred because Phase 4 should first ship reliable regular evidence and retention.

---

## Expert Panel Convergence

| Panel Point | Resolution |
|-------------|------------|
| Primary guarantee | Fast disk-pressure explanation with visible freshness/gap status. |
| Failure mode | Fail fast; evidence gaps are product-visible. |
| Retention unit | Whole snapshots only; never prune individual historical path rows. |
| Monthly retention | Representative full snapshots, not rollup summaries. |
| Concurrency | Collection, pruning, and maintenance must share an operation-lock model. |
| Maintenance | Slower SQLite maintenance after pruning, guarded by the same lock. |
| Deferred scope | Cleanup orchestration and before/after cleanup snapshots. |

## the agent's Discretion

- Exact timer expression and service/unit filenames.
- Exact lock implementation.
- Exact pruning command shape and maintenance command naming.
- Exact SQLite maintenance strategy, as long as it is safe and tested.

## Deferred Ideas

- Automatic before/after cleanup snapshots.
- Cleanup/prune actions outside `watchdirs` evidence management.
- Rollup-summary tables or long-term top-delta analytics.
