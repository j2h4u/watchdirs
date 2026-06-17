# Codebase Concerns

**Analysis Date:** 2026-06-17

## Tech Debt

**Broad exception masking in the CLI and collection path:**
- Issue: `src/watchdirs/cli.py` converts unexpected failures into generic JSON errors in the query server and into failed snapshots during collection, which makes programming bugs look like expected runtime failures.
- Files: `src/watchdirs/cli.py`, `src/watchdirs/collect/scanner.py`
- Impact: A regression in parsing, DB writes, or query dispatch can be recorded as a partial/failed run instead of surfacing clearly during validation.
- Fix approach: Narrow the exception handling around known operational failures and let unexpected exceptions fail loudly in test and local execution modes.

**Large, highly coupled rendering/query modules:**
- Issue: `src/watchdirs/reporting/queries.py` and `src/watchdirs/reporting/render.py` carry many responsibilities in single modules, including SQL, grouping, deduplication, payload shaping, and text formatting.
- Files: `src/watchdirs/reporting/queries.py`, `src/watchdirs/reporting/render.py`
- Impact: Small behavior changes can ripple across multiple output formats and query variants, making regressions easy to introduce and hard to isolate.
- Fix approach: Split shared helpers from command-specific logic and isolate repeated warning/grouping behavior into smaller units with focused tests.

## Performance Bottlenecks

**Scanner memory growth on large trees:**
- Problem: `src/watchdirs/collect/scanner.py` keeps an inode set for hardlink deduplication and buffers directory entries per frame, so scan memory scales with tree size and directory fan-out.
- Files: `src/watchdirs/collect/scanner.py`
- Cause: `_ScanState.seen_inodes` is unbounded, and each `_Frame` stores the full `os.scandir` result list until that directory finishes.
- Improvement path: Add clearer memory limits/telemetry for hardlink tracking and consider streaming or chunked directory processing for very large directories.

**Full-table retention and pruning work grows with snapshot count:**
- Problem: `src/watchdirs/db/retention.py` loads all snapshot rows, computes retention in Python, then deletes retained-orphaned rows in one transaction.
- Files: `src/watchdirs/db/retention.py`
- Cause: The retention policy is implemented as full scans over `snapshots` and `paths` rather than incremental or indexed retention passes.
- Improvement path: Keep the current policy but add guardrails for large databases, and consider incremental cleanup once snapshot volume becomes high.

## Fragile Areas

**Manual SQL and grouping logic for report totals:**
- Files: `src/watchdirs/reporting/queries.py`
- Why fragile: Boundary calculations, mount-prefix resolution, and negative-total clamping depend on several hand-built joins and accumulator rules; a small schema or grouping change can skew totals without obvious failure.
- Safe modification: Change SQL and accumulator behavior together and add regression tests that cover partial snapshots, unknown mounts, and submount subtraction.
- Test coverage: Good coverage exists, but the module is still sensitive because the behavior is distributed across many helper functions and output modes.

**Snapshot lifecycle and cleanup are tightly coupled to SQLite behavior:**
- Files: `src/watchdirs/db/connection.py`, `src/watchdirs/db/retention.py`
- Why fragile: WAL mode, page-size initialization, and retention cleanup assume SQLite semantics that must stay aligned with schema migrations and deployment timing.
- Safe modification: Keep connection pragmas, migrations, and retention changes in lockstep and verify against fresh databases plus migrated databases.
- Test coverage: `tests/test_db_schema.py` and `tests/test_ops_retention.py` cover the current shape, but any PR touching initialization or cleanup should also exercise a migrated database path.

## Security Considerations

**Query server executes only validated argv, but error text is echoed back:**
- Risk: `src/watchdirs/cli.py` returns exception text over the query socket, which can expose internal state if a caller can trigger malformed requests.
- Files: `src/watchdirs/cli.py`
- Current mitigation: The query surface validates command names and forces the host database path.
- Recommendations: Keep the allowed command list narrow and consider reducing the detail level of returned error strings for externally reachable deployments.

## Missing Critical Features

**No explicit backpressure or resource budgeting for giant scans:**
- Problem: There is no visible mechanism to cap scan memory or report expected scan resource use before traversal starts.
- Files: `src/watchdirs/collect/scanner.py`, `src/watchdirs/models.py`
- Blocks: Very large directory trees can consume substantial RAM before the tool can complete a forensic pass.

**No retry strategy for maintenance work:**
- Problem: `src/watchdirs/db/retention.py` reports busy/partial WAL checkpoint progress, but there is no retry/backoff policy.
- Files: `src/watchdirs/db/retention.py`
- Blocks: Maintenance can finish in a degraded state on busy systems and leave follow-up work to the operator.

---

*Concerns audit: 2026-06-17*
