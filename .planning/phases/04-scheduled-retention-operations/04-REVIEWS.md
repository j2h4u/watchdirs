---
phase: 04
reviewers: [opencode]
reviewed_at: 2026-06-16T23:21:44.708447+00:00
plans_reviewed: [04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md, 04-04-PLAN.md]
---

# Cross-AI Plan Review - Phase 04

## OpenCode Review

Now I have complete context. Here is the cross-AI plan review:

---

# Cross-AI Plan Review: Phase 4 — Scheduled Retention Operations

## 1. Summary

The four plans form a well-researched, coherent execution pipeline. The wave ordering (lock → prune → vacuum → systemd/docs) correctly establishes the concurrency foundation first, then layers retained mutation, then the slower maintenance path, and finally the operational wrapping. Every OPER requirement and every locked decision is traced in the source-coverage audit. Threat models per plan are specific and actionable. The research is deeply integrated — orphan-path GC, WAL-safety, and the `auto_vacuum`-vs-`VACUUM` distinction are all correctly called out and addressed. The plans achieve the phase goal. The remaining concerns are medium-severity edge conditions around WAL checkpoint timing, timer collision probability, and the installed-command assumption in unit files.

## 2. Strengths

- **Correct dependency ordering**: Lock (04-01) must exist before prune (04-02) and vacuum (04-03) can reuse it; systemd units (04-04) depend on all CLI surfaces existing. No circularity.
- **Orphan-path GC is explicitly planned**: The `paths` table leak is the single most common silent DB growth pattern for dictionary-encoded schemas, and every plan (research, 04-02 tasks, acceptance criteria) addresses it.
- **Fail-fast semantics throughout**: `LOCK_EX | LOCK_NB` + `operation_locked` error envelope + non-zero exit. No silent blocking, no retry loops, PID-file staleness avoided.
- **Separation of cadences**: Hourly collect, daily prune, weekly vacuum. No `VACUUM` on the hot collect path. This protects hourly boundedness (D-10) and makes each failure independently journal-visible.
- **Threat models per plan**: Each plan has its own STRIDE register with disposition and mitigation plans. Trust boundaries are correctly drawn at CLI args, concurrent processes, and snapshot-delete cascades.
- **Validation architecture is concrete**: Requirement-to-test map with specific selectors, wave-level verification accumulation, `systemd-analyze verify` integration. Nyquist-compliant.
- **Whole-snapshot deletion boundary respected**: All four plans consistently reference `DELETE FROM snapshots` + FK cascades, never direct child-table deletes (D-04).
- **Research-backed constraint handling**: WAL-reset race (SQLite < 3.47.0 on the host) → lock serialises writers. `auto_vacuum=FULL` docs → explicit `VACUUM` still needed. All four common pitfalls from research are mitigated.

## 3. Concerns

| # | Concern | Severity | Plans Affected | Actionable? |
|---|---------|----------|----------------|-------------|
| C1 | **WAL checkpoint during VACUUM may contend with unlocked readers.** The plan runs `PRAGMA wal_checkpoint(TRUNCATE)` after `VACUUM` under the writer lock. But read-only commands (report, diff, top, etc.) are explicitly unlocked (Pattern 1). If a report holds an open WAL reader when vacuum hits checkpoint, `wal_checkpoint(TRUNCATE)` can block behind the reader for up to `busy_timeout=5000` ms, then fail silently or partially. The VACUUM result payload has no field for a checkpoint warning. An operator might see before/after counters but miss that WAL sidecars were not truncated. | MEDIUM | 04-03 | Yes |
| C2 | **Prune timer collision with collect timer is probabilistic, not prevented by scheduling.** The research says prune runs daily "off the hourly boundary," but 04-04 does not specify a concrete `OnCalendar` offset. Systemd timers can drift and catch up (`Persistent=true`). Without a randomized delay or an explicit offset minute, daily prune and the :00 hourly collect will eventually coincide. The lock handles this correctly (fail-fast), but chronic collision produces noise in journal logs with no operational benefit. | MEDIUM | 04-04 | Yes |
| C3 | **Systemd units assume `watchdirs` is on the service PATH.** `ExecStart=/usr/bin/env PYTHONUNBUFFERED=1 watchdirs collect ...` requires `watchdirs` to be a global command. The project uses `uv` and has no setuptools console-script entry point. If installed via `uv tool install` or a venv, the unit files will fail with `command not found`. The plans do not address installation path resolution (absolute `ExecStart` or a wrapper script). | MEDIUM | 04-04 | Yes |
| C4 | **VACUUM on a disk-pressure host may fail from insufficient free space.** Research correctly notes VACUUM can need ~2× DB size. The plan documents this as `T-04-03-01` (mitigate: explicit command + off-peak timer). But there is no pre-VACUUM free-space check or error specialization — `VACUUM` failure surfaces as a generic `database_error` with the SQLite message. An operator may not immediately recognize the root cause. | MEDIUM | 04-03 | Partial |
| C5 | **Task verification commands use `uv run --with pytest pytest` rather than the project-standard pattern.** The existing project config (`pyproject.toml` `[tool.pytest.ini_options]`) suggests `pytest` is run via `uv run pytest`. The plan commands append `--with pytest` repeatedly, which is atypical for `uv` and may fail on some versions. The conftest fixtures use `python3 -m watchdirs` and `bash -lc` patterns that already work. | LOW | All plans | Yes |
| C6 | **PARTIAL/FAILED snapshot fate in the retention boundary is implicit.** Plan 04-02 says "keep all snapshots newer than `hourly_days`" — this includes PARTIAL/FAILED, which is correct for D-09. Daily/monthly tiers keep COMPLETE only, which is correct for D-03. But the plan does not explicitly state that PARTIAL/FAILED snapshots beyond the hourly window are deleted (no representative promotion). This follows from the design but could surprise an operator who expects partial evidence to survive longer. | LOW | 04-02 | Yes |
| C7 | **Orphan-path GC query uses three NOT EXISTS clauses but does not guard against `top_child_id` NULL semantics.** SQL `NOT EXISTS (SELECT 1 FROM ... WHERE top_child_id = paths.id)` behaves correctly: if `top_child_id` is NULL, the subquery returns false (NULL = paths.id is NULL, not true), so NOT EXISTS is true — meaning a NULL reference incorrectly marks the path as orphan-safe. In practice, if a row has `top_child_id = NULL` but the path is still referenced via `path_id` or `parent_id`, the AND-clause structure still protects it. The three-clause conjunction is defensive and correct. | LOW | 04-02 | No (already correct) |
| C8 | **No explicit test for prune idempotency or double-prune safety.** Running prune, then running prune again before any new collect, should be a no-op. The JSON counters would show 0 changes. This is worth a test assertion to prevent future regressions where keep-set computation mutates snapshot state. | LOW | 04-02 | Yes |

## 4. Suggestions

1. **Add a checkpoint result field to `VacuumResult`.** After `wal_checkpoint(TRUNCATE)`, capture the return tuple `(busy, log, checkpointed)`. If `busy != 0` or `checkpointed == -1`, include a `wal_checkpoint_warning` in the result. This makes the WAL-reader contention case visible rather than silent.

2. **Add a `RandomizedDelaySec=300` to the prune timer** (or an explicit `OnCalendar=daily` with a specific minute offset from the hour boundary). This spreads the prune window and reduces chronic collision with the hourly collect timer without requiring lock retry logic.

3. **Resolve the `watchdirs` command path in unit files.** Either:
   - Use an absolute venv path (`/usr/local/bin/watchdirs` or `/home/user/.local/bin/watchdirs`), or
   - Ship a small wrapper script at a fixed path that execs `uv run watchdirs`, or
   - Document the installation requirement explicitly in README Task 2.
   The README update in 04-04 should include the command used to verify `which watchdirs` works from the service context.

4. **Add a pre-VACUUM disk-space advisory.** Before executing `VACUUM`, query `PRAGMA page_count` × `page_size` for the current DB size, check `os.statvfs` for available bytes, and if available < 3× DB size, emit a warning field in the result. This is informational (not blocking) and keeps VACUUM explicit. Solves the disk-pressure visibility gap from C4.

5. **Fix `uv` invocation in verification commands.** Replace `uv run --with pytest pytest` with `uv run pytest` throughout the plan verify blocks, matching the project's `pyproject.toml` configuration.

6. **Add a note to 04-02 clarifying PARTIAL/FAILED snapshot retention semantics**: "Hourly window keeps snapshots of ALL statuses (including PARTIAL and FAILED, per D-09). Daily and monthly tiers select only COMPLETE snapshots. PARTIAL/FAILED snapshots that age out of the hourly window are deleted and are not promoted to daily/monthly representatives."

7. **Add an idempotency test to `test_ops_retention.py`**: Populate snapshots, run prune, capture result counts, run prune again, assert `deleted_snapshot_count == 0` and `retained_snapshot_count` is unchanged.

8. **Verify subprocess test infrastructure**: The 04-01 plan describes "holding the derived lock ... and then running `./watchdirs collect`" which suggests using the shell wrapper. Confirm that `run_module` (Python `-m watchdirs`) can also be used for lock tests — it would be more deterministic by avoiding bash subshells.

## 5. Risk Assessment

**Overall risk: LOW**

The architecture is well-grounded in research, the schema already supports whole-snapshot deletes via FK cascades, and the concurrency model (one non-blocking `fcntl.flock`, fail-fast, no retry) is provably correct for the three-writer problem. The main execution risks are non-functional: WAL checkpoint timing with concurrent readers, timer collision noise, and the systemd unit file `ExecStart` PATH assumption. None of these prevent the phase from working correctly; they affect observability and deployment ergonomics. The plan's verification strategy is comprehensive — requirement-to-test mapping, wave accumulation, and `systemd-analyze verify` — so regressions will be caught.

**Key judgment:** The plans achieve the phase goal. All suggestions above are improvements, not blockers. Phase 4 can proceed to execution with the noted medium-concern items addressed during implementation.


---

## Consensus Summary

Single-reviewer cycle using OpenCode.

### Agreed Strengths

- The plan dependency order is coherent: lock, prune, vacuum, then systemd/docs.
- Whole-snapshot pruning and orphan-path garbage collection are explicitly planned.
- Fail-fast operation-lock semantics are consistently carried through the mutating commands.
- Validation architecture and requirement coverage are concrete.

### Agreed Concerns

- MEDIUM: `VacuumResult` should make WAL checkpoint busy/partial outcomes visible.
- MEDIUM: prune timer should avoid predictable collision with hourly collect using a concrete offset or randomized delay.
- MEDIUM: systemd units and docs should resolve the installed `watchdirs` command path assumption.
- MEDIUM: vacuum should provide an explicit free-space advisory before running on a disk-pressure host.
- LOW: plan verify commands should use the project-standard `uv run pytest` form.
- LOW: retention semantics for aged-out PARTIAL/FAILED snapshots should be explicit.
- LOW: retention tests should include double-prune idempotency.

### Divergent Views

None. Only OpenCode was requested for this convergence run.
