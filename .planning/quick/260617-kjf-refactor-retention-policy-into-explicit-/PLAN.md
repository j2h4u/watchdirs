---
quick_id: 260617-kjf
slug: refactor-retention-policy-into-explicit-
status: planned
created: 2026-06-17T09:47:18Z
---

# Refactor Retention Policy Into Explicit Tiers

Goal: make the current hourly/daily/monthly retention policy explicit in code without changing prune behavior, CLI flags, or JSON output.

Plan:

- Add typed retention tier metadata for current policy semantics.
- Keep `RetentionPolicy(hourly_days, daily_days)` and CLI payload compatible.
- Add focused tests for the tier shape.
- Run targeted ops tests and full suite.
- Apply Kaizen to decide what follow-up options should remain on the table.
