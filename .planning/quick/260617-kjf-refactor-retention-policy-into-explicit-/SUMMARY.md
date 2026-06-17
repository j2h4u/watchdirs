---
quick_id: 260617-kjf
slug: refactor-retention-policy-into-explicit-
status: complete
completed: 2026-06-17T09:55:00Z
---

# Summary

Implemented an explicit tier model for retention policy without changing behavior.

Changes:

- Added `RetentionTierMode` for the three current behaviors: keep all statuses in the hourly window, keep latest COMPLETE per UTC day, and keep latest COMPLETE per UTC month.
- Added `RetentionTier` dataclass and `RetentionPolicy.tiers`/`RetentionPolicy.tier(...)` so hourly/daily/monthly semantics are visible from the policy object.
- Kept existing `RetentionPolicy(hourly_days=14, daily_days=90)`, CLI flags, validation messages, and prune JSON payload shape unchanged.
- Added a regression test pinning the explicit hourly/daily/monthly tier shape.

Subagent input:

- Cheap planning subagent recommended explicit tier dataclasses while preserving UTC cutoff semantics, unfinished snapshot handling, latest representative tie-breaks, and JSON contract.
- Cheap risk-review subagent flagged API/JSON drift and deletion accounting as the main risks; implementation avoided those changes.

Verification:

- `uv run pytest tests/test_ops_retention.py -q -x` -> 9 passed.
- `uv run pytest tests/test_ops_retention.py tests/test_ops_vacuum.py tests/test_systemd_units.py -q -x` -> 20 passed.
- `uv run pytest -q` -> 254 passed.

Kaizen follow-up decision:

- Keep: tune numeric retention windows after real timer data exists.
- Keep: tune collapse policy next, because it is measured and already produced about 4.37x footprint reduction on the prod-root sample.
- Keep: add `prune --dry-run`/size preview before any more destructive automation, because it is small and error-proofing.
- Defer: weekly retention tier, because the user explicitly rejected it and hourly/daily/monthly is enough.
- Defer: delta snapshots, because it is a large storage-model rewrite with higher correctness risk and no current need after collapse gains.
- Defer: cold-history archive/export, because it solves a longer-retention problem we have not measured yet.
- Defer until measured: index/schema tuning, because it needs query-latency benchmarks to avoid trading space for slow reports.
