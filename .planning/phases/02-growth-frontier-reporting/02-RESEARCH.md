# Phase 02: Growth Frontier Reporting - Research

**Researched:** 2026-06-13
**Domain:** Python CLI reporting over SQLite directory snapshot history on Linux [VERIFIED: python3 --version + sqlite3 --version + src/watchdirs/db/schema.sql + https://docs.python.org/3/library/sqlite3.html + https://www.sqlite.org/lang_with.html]
**Confidence:** MEDIUM

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
Verbatim from `02-CONTEXT.md`. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

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
Verbatim from `02-CONTEXT.md`. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

The user explicitly delegated deep technical choices to expert-panel or best-practice research after product intent was clarified. Downstream planning should resolve snapshot-pairing semantics, exact frontier algorithm, JSON schema, and grouping persistence technically, but must keep the product job above as the deciding constraint.

### Deferred Ideas (OUT OF SCOPE)
Verbatim from `02-CONTEXT.md`. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

- Deleted-open-file diagnostics and `df` vs indexed-total reconciliation remain Phase 3.
- Docker/containerd reclaimability and service-specific enrichment remain Phase 3.
- Disk-subsystem capacity planning, migration recommendations, and old-disk repurposing remain later diagnostic/capacity work unless Phase 2 grouping needs a minimal storage-domain foundation.
- Scheduled collection, retention, pruning, SQLite vacuum, and strong `nice`/`ionice` behavior remain Phase 4.
- Long-term trend forecasting and BI-style reports are out of current scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPT-01 | Agent can run `watchdirs diff --since 24h --limit N --json` to list paths sorted by disk-byte growth. [VERIFIED: .planning/REQUIREMENTS.md] | Use per-root snapshot-pair selection plus a raw diff CTE ordered by `disk_bytes_delta DESC`, then apply frontier pruning before final rendering. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html] |
| REPT-02 | Agent can run `watchdirs report --since 24h --json` to get a structured investigation summary. [VERIFIED: .planning/REQUIREMENTS.md] | Keep a stable JSON envelope with explicit snapshot selection, group summaries, frontier rows, deleted rows, and warning flags. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/cli.py][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/sqlite3.html] |
| REPT-03 | Agent can run `watchdirs top --snapshot latest --limit N --json` to list largest current directory trees. [VERIFIED: .planning/REQUIREMENTS.md] | Reuse current schema/indexes for size-ranked snapshot queries and keep the output contract identical to other report commands. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/db/connection.py][CITED: https://docs.python.org/3/library/sqlite3.html] |
| REPT-04 | Agent can run `watchdirs explain-path PATH --since 24h --json` to drill into one subtree's growth. [VERIFIED: .planning/REQUIREMENTS.md] | Use path-scoped child breakdowns plus direct-file residual deltas so the command explains one suspicious subtree without dumping full recursion. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/models.py][CITED: https://www.sqlite.org/lang_with.html] |
| REPT-05 | Agent can run `watchdirs deleted --since 24h --json` to list paths present in the earlier snapshot but absent in the later snapshot. [VERIFIED: .planning/REQUIREMENTS.md] | Compute classifications from the union of previous/current paths so deleted rows are first-class, not inferred from negative deltas alone. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/lang_with.html] |
| REPT-06 | Reports distinguish created, deleted, unchanged, grown, and shrunk paths. [VERIFIED: .planning/REQUIREMENTS.md] | Build one normalized diff row shape with explicit `classification`, `previous_*`, `current_*`, and `*_delta` fields. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://docs.python.org/3/library/sqlite3.html] |
| REPT-07 | Reports can group growth and current usage by filesystem or mounted storage domain so multi-SSD hosts show which filesystem owns the pressure. [VERIFIED: .planning/REQUIREMENTS.md] | Persist snapshot-time mount metadata because current directory rows do not store a durable grouping key and `mount_id` is not stable across snapshots. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/collect/mounts.py + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Target `senbonzakura` first; recommendations should optimize the real host incident workflow rather than a generic disk UI. [VERIFIED: AGENTS.md]
- Use SQLite for v1 storage. [VERIFIED: AGENTS.md]
- Store recursive directory aggregate rows rather than permanent file inventory. [VERIFIED: AGENTS.md]
- Do not follow symlinks and do not silently descend into virtual, transient, or container overlay filesystems. Reporting must preserve and expose those collection semantics. [VERIFIED: AGENTS.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- Track both apparent bytes and disk bytes, and make hardlink semantics explicit in reports. [VERIFIED: AGENTS.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
- Keep JSON output first-class. [VERIFIED: AGENTS.md]
- Respect GSD workflow boundaries for later implementation work. [VERIFIED: AGENTS.md]

## Summary

Phase 2 should stay stdlib-first and build on the Phase 1 seams that already exist: `argparse` subcommands in `cli.py`, `sqlite3.Row` connections in `db.connection`, BLOB-backed path identity in `directory_sizes`, and explicit snapshot status/error semantics in `snapshots`. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/connection.py + src/watchdirs/db/schema.sql + src/watchdirs/models.py][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/sqlite3.html]

The core planning decision is to separate reporting into two layers. First, resolve snapshot pairs and compute normalized diff rows per root in SQL with CTEs. Second, prune those rows into a compact growth frontier and render stable JSON plus terse text in Python. SQLite's docs support this split: CTEs are good for factoring path sets and hierarchy walks, but recursive SELECT arms cannot use aggregate or window functions, so ranking should happen after the recursive step rather than inside it. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html]

REPT-07 needs one minimal persistence addition. The current schema stores snapshot rows and directory aggregates only; it does not persist mount metadata that can survive later mount changes. The Linux mountinfo man page says `mount_id` may be reused after unmount, while `major:minor`, `root`, `mount point`, `filesystem type`, and `mount source` describe the mounted object. The plan should therefore add a small `snapshot_mounts` table captured at collection time and use it for grouping and labeling during reports rather than relying on live-only inference. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/collect/mounts.py + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

**Primary recommendation:** Use per-root snapshot-pair selection plus SQL classification for raw diff rows, then perform frontier pruning and rendering in Python, backed by a persisted `snapshot_mounts` table for durable filesystem/storage-domain grouping. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://www.sqlite.org/lang_with.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Snapshot-pair selection for `--since` / explicit ids | API / Backend | Database / Storage | Selection policy is application logic, but it depends on snapshot metadata persisted in SQLite. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql] |
| Raw path diff classification (`created`/`deleted`/`grown`/`shrunk`/`unchanged`) | Database / Storage | API / Backend | SQLite is best at joining two snapshots and producing normalized diff rows; the CLI layer should consume a stable row shape rather than reimplement joins in Python. [CITED: https://www.sqlite.org/lang_with.html][VERIFIED: src/watchdirs/db/schema.sql] |
| Frontier pruning and explain-path drill-down | API / Backend | Database / Storage | Compact next-step recommendations are product logic layered on top of raw diff rows and parent/child relationships. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/models.py] |
| Filesystem and storage-domain grouping | Database / Storage | API / Backend | Durable grouping requires persisted snapshot-time mount metadata plus application-side longest-prefix mapping and labels. [VERIFIED: src/watchdirs/collect/mounts.py + src/watchdirs/db/schema.sql][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| JSON/text report rendering | API / Backend | — | Output contract, labels, and omission of noise are CLI/report-layer concerns. [VERIFIED: AGENTS.md + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/cli.py] |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`argparse`, `json`, `sqlite3`) | 3.13.5 [VERIFIED: python3 --version] | CLI subcommands, JSON output, and SQLite query access. [CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/sqlite3.html] | Matches the existing Phase 1 implementation and keeps Phase 2 dependency-free. [VERIFIED: pyproject.toml + src/watchdirs/cli.py] |
| SQLite engine | 3.46.1 [VERIFIED: sqlite3 --version] | Snapshot diff queries, ranking precomputation, and persisted mount metadata. [CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html] | Already the project's v1 store and sufficient for path-diff joins plus limited hierarchy queries. [VERIFIED: AGENTS.md + src/watchdirs/db/schema.sql] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Existing `watchdirs` Phase 1 schema and models | current repo state [VERIFIED: src/watchdirs/models.py + src/watchdirs/db/schema.sql] | Reuse BLOB path identity, snapshot lifecycle fields, and indexes. | Always; Phase 2 should extend these seams instead of bypassing them. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] |
| `pytest` | 8.3.5 installed locally [VERIFIED: pytest --version] | Reporting query, CLI contract, and grouping regression tests. | Use for all new automated Phase 2 coverage; the existing test harness is already working. [VERIFIED: pytest --collect-only -q + pytest -q] |
| `/proc/self/mountinfo` semantics | Linux man-pages 6.18 page dated 2026-02-08 [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] | Define the persisted grouping fields for filesystem and storage-domain labels. | Use when designing the `snapshot_mounts` table and any grouping resolver. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Persisted `snapshot_mounts` metadata | Live `mountinfo` lookup during reports | Live-only inference can mislabel old snapshots after mount changes and cannot safely use `mount_id` across time. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| SQL raw diff + Python frontier pruning | Pure SQL frontier pruning | SQLite can do hierarchy traversal and ranking, but recursive SELECT arms cannot use aggregates/window functions, so a pure-SQL frontier becomes harder to reason about and test. [CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html] |
| Per-root pairing then merge | Arbitrary snapshot-id pairing across roots | Cross-root deltas are meaningless for this product and violate the incident workflow that asks what changed within the same tracked area over time. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://github.com/pratham15541/disktracker] |

**Installation:**
```bash
# No new runtime package installs are recommended for Phase 2.
# Use the existing repo-local entrypoint and local test tooling.
./watchdirs --help
pytest -q
```
[VERIFIED: ./watchdirs present + pytest -q + pyproject.toml]

**Version verification:** `python3`, `sqlite3`, `pytest`, and `du` were verified locally for this phase. [VERIFIED: python3 --version + sqlite3 --version + pytest --version + du --version]

## Package Legitimacy Audit

Phase 2 does not require new external package installs if the planner keeps reporting stdlib-first and reuses the already-present test framework. The package-legitimacy gate is therefore not triggered for the recommended implementation path. [VERIFIED: pyproject.toml + src/watchdirs/cli.py + pytest --version]

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| none | — | — | — | — | — | No new external packages recommended for this phase. [VERIFIED: pyproject.toml] |

**Packages removed due to [SLOP] verdict:** none. [VERIFIED: pyproject.toml]
**Packages flagged as suspicious [SUS]:** none. [VERIFIED: pyproject.toml]

## Architecture Patterns

### System Architecture Diagram

```text
CLI command (`diff` / `report` / `top` / `deleted` / `explain-path`)
  -> argparse subparser dispatch
  -> snapshot selector
     -> resolve current/baseline per root
     -> attach explicit selection metadata + status warnings
  -> query layer
     -> raw diff CTE / top query / deleted query
     -> optional subtree filter
     -> optional snapshot_mounts lookup
  -> reporting layer
     -> classify + group rows
     -> frontier prune default diff/report output
     -> explain-path child breakdown
  -> renderer
     -> stable JSON envelope
     -> terse labeled text
```
[VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://www.sqlite.org/lang_with.html]

### Recommended Project Structure
```text
src/
└── watchdirs/
    ├── cli.py                    # extend command tree with report commands
    ├── models.py                 # report row / selection dataclasses
    ├── reporting/
    │   ├── pairs.py              # resolve same-root snapshot pairs
    │   ├── queries.py            # raw diff/top/deleted SQL helpers
    │   ├── frontier.py           # compact frontier pruning logic
    │   └── render.py             # JSON + terse text renderers
    └── db/
        ├── connection.py         # existing sqlite Row connection
        ├── migrations.py         # schema v2 + snapshot_mounts migration
        ├── reporting.py          # mount metadata loaders if kept near DB
        └── schema.sql            # add snapshot_mounts table + any indexes

tests/
├── test_cli_report_commands.py   # diff/report/top/deleted/explain-path CLI contracts
├── test_reporting_queries.py     # classification and snapshot-pair SQL behavior
├── test_frontier.py              # parent-child pruning and explain-path drills
└── test_grouping.py              # filesystem/storage-domain grouping resolution
```
[VERIFIED: src/watchdirs/cli.py + src/watchdirs/db/schema.sql + tests][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/sqlite3.html]

### Pattern 1: Root-Isolated Snapshot Pairing
**What:** Resolve `current` and `baseline` snapshots within the same `root_path`, then merge per-root outputs only after each root has a valid pair. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql][CITED: https://github.com/pratham15541/disktracker]
**When to use:** `diff`, `report`, `deleted`, and `explain-path` whenever the user selects `--since` or uses implicit latest/previous behavior. [VERIFIED: .planning/REQUIREMENTS.md]
**Example:**
```python
def resolve_pair(snapshot_rows, *, target_root, since_seconds):
    rows = [row for row in snapshot_rows if row["root_path"] == target_root and row["status"] != "failed"]
    current = rows[-1]
    baseline_cutoff = current["finished_at_epoch"] - since_seconds
    baseline = max(
        (row for row in rows if row["finished_at_epoch"] <= baseline_cutoff),
        key=lambda row: row["finished_at_epoch"],
        default=None,
    )
    return current, baseline
```
```python
# Source: pattern inferred from Phase 2 root-scoped requirements and ecosystem examples
# https://github.com/pratham15541/disktracker
```

### Pattern 2: Two-Stage Diff Pipeline
**What:** Use SQL to produce one normalized diff row per path, then use Python to rank, prune, and render the compact frontier. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/db/connection.py][CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html]
**When to use:** All default report flows where the planner must avoid parent/child duplicate noise while keeping deleted and shrunk rows available. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
**Example:**
```sql
WITH paths AS (
  SELECT path FROM directory_sizes WHERE snapshot_id = :previous_snapshot_id
  UNION
  SELECT path FROM directory_sizes WHERE snapshot_id = :current_snapshot_id
),
diff AS (
  SELECT
    paths.path,
    prev.parent_path AS previous_parent_path,
    curr.parent_path AS current_parent_path,
    prev.disk_bytes AS previous_disk_bytes,
    curr.disk_bytes AS current_disk_bytes,
    COALESCE(curr.disk_bytes, 0) - COALESCE(prev.disk_bytes, 0) AS disk_bytes_delta,
    prev.apparent_bytes AS previous_apparent_bytes,
    curr.apparent_bytes AS current_apparent_bytes,
    COALESCE(curr.apparent_bytes, 0) - COALESCE(prev.apparent_bytes, 0) AS apparent_bytes_delta
  FROM paths
  LEFT JOIN directory_sizes AS prev
    ON prev.snapshot_id = :previous_snapshot_id
   AND prev.path = paths.path
  LEFT JOIN directory_sizes AS curr
    ON curr.snapshot_id = :current_snapshot_id
   AND curr.path = paths.path
)
SELECT *
FROM diff
ORDER BY disk_bytes_delta DESC, current_disk_bytes DESC
LIMIT :limit;
```
```sql
-- Source: adapted from SQLite WITH and window-function documentation
-- https://www.sqlite.org/lang_with.html
-- https://www.sqlite.org/windowfunctions.html
```

### Pattern 3: Persist Snapshot-Time Mount Metadata
**What:** Add a `snapshot_mounts` table keyed by `snapshot_id` that stores at least `mount_id`, `parent_id`, `major_minor`, `root`, `mount_point`, `filesystem_type`, and `mount_source`. [VERIFIED: src/watchdirs/collect/mounts.py + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
**When to use:** REPT-07 grouping and any output field that claims filesystem/mount identity for a historical snapshot. [VERIFIED: .planning/REQUIREMENTS.md]
**Example:**
```sql
CREATE TABLE snapshot_mounts (
  id INTEGER PRIMARY KEY,
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  mount_id INTEGER NOT NULL,
  parent_id INTEGER NOT NULL,
  major_minor TEXT NOT NULL,
  root BLOB NOT NULL,
  mount_point BLOB NOT NULL,
  filesystem_type TEXT NOT NULL,
  mount_source TEXT NOT NULL
);
```
```sql
-- Source: field set derived from Linux mountinfo documentation and current watchdirs mount parser
-- https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html
```

### Anti-Patterns to Avoid
- **Cross-root pairing:** never compare snapshot ids from different `root_path` values just because they are close in time. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
- **Live-only mount grouping:** do not label historical rows with today's mountinfo data. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
- **Parent/child dump by default:** a raw changed-descendant list burns tokens and violates the compact frontier requirement. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
- **UTF-8 decode in query logic:** keep path bytes lossless until render boundaries, matching Phase 1's storage contract. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/models.py + .planning/STATE.md]
- **Using `mount_id` as a cross-snapshot domain key:** the man page says it may be reused after unmount. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Path-diff classification | Python nested loops over all snapshot rows | A normalized SQL diff CTE over the union of previous/current paths. [CITED: https://www.sqlite.org/lang_with.html] | SQLite is already the durable store and can compute created/deleted/grown/shrunk rows directly. [VERIFIED: src/watchdirs/db/schema.sql] |
| CLI command dispatch | A custom command router | `argparse` subparsers plus `set_defaults(handler=...)`. [CITED: https://docs.python.org/3/library/argparse.html] | This matches the existing command surface and keeps new report commands consistent. [VERIFIED: src/watchdirs/cli.py] |
| Historical grouping identity | Recomputing filesystem/domain labels from live mounts | Persisted `snapshot_mounts` metadata captured with the snapshot. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] | Historical reports must explain the snapshot pair, not the current host state. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] |
| Non-UTF-8 path support | Early string coercion and lossy decode assumptions | Keep BLOB path identity in storage and decode only in render helpers. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/models.py] | Phase 1 already chose raw bytes for correctness, and Phase 2 should not undo that. [VERIFIED: .planning/STATE.md] |

**Key insight:** the hard parts in this phase are pair selection, duplicate-noise pruning, and durable grouping identity, not package selection. Keep the implementation small and explicit around those three decisions. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql][CITED: https://www.sqlite.org/lang_with.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

## Common Pitfalls

### Pitfall 1: Comparing the Wrong Snapshot Pair
**What goes wrong:** The report compares snapshots from different roots or picks an arbitrary baseline that does not match the requested incident window. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
**Why it happens:** Phase 1 stores one snapshot row per configured root, so "latest id" is not a valid global pairing rule. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/cli.py]
**How to avoid:** Resolve pairs per `root_path`, surface both ids and timestamps in output, and return a structured error when no same-root baseline exists. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
**Warning signs:** The report shows unrelated roots in one pair or cannot explain why a baseline was chosen. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

### Pitfall 2: Default Output Repeats the Same Growth at Every Ancestor
**What goes wrong:** `diff` shows `/`, `/var`, `/var/lib`, and `/var/lib/containerd` as separate top hits even when the useful next step is only the deepest dominant subtree. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
**Why it happens:** Recursive aggregate rows store parent totals by design, so a naive "all changed rows ordered by delta" query duplicates signal. [VERIFIED: src/watchdirs/models.py + src/watchdirs/db/schema.sql]
**How to avoid:** Keep a raw diff table for completeness, but prune the default frontier to the highest-value drill-down targets and move the full child breakdown to `explain-path`. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]
**Warning signs:** Test fixtures produce many ancestor rows with nearly identical deltas and the text output stops being scan-friendly. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

### Pitfall 3: Mislabeling Filesystem or Storage Domain
**What goes wrong:** Historical reports attribute a path to the wrong mount or treat `mount_id` as a durable identity across snapshots. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
**Why it happens:** The current schema does not persist mount metadata, and `mount_id` may be reused after unmount. [VERIFIED: src/watchdirs/db/schema.sql][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
**How to avoid:** Persist mount fields with each snapshot and derive durable group keys from `major_minor`, `root`, `mount_point`, `filesystem_type`, and `mount_source`. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
**Warning signs:** A later report's filesystem labels change after a host remount or a reboot even though the underlying snapshots are unchanged. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

### Pitfall 4: Hiding Partial Evidence
**What goes wrong:** Agents trust a delta as complete even when one or both snapshots were `partial` or contain path-level errors. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
**Why it happens:** The reporting layer focuses only on size deltas and drops `snapshots.status`, `snapshots.error`, or per-path `directory_sizes.error`. [VERIFIED: src/watchdirs/db/schema.sql]
**How to avoid:** Include snapshot status, fatal error, and path-warning counts in every pair selection and report payload. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql]
**Warning signs:** A report cannot explain why totals look suspicious or why a path disappeared from one snapshot. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

## Code Examples

Verified patterns from official sources:

### `argparse` Subcommand Dispatch
```python
import argparse


def run_diff(args):
    ...


parser = argparse.ArgumentParser(prog="watchdirs")
subparsers = parser.add_subparsers(required=True)
diff_parser = subparsers.add_parser("diff")
diff_parser.add_argument("--since", required=True)
diff_parser.set_defaults(handler=run_diff)

args = parser.parse_args()
args.handler(args)
```
```python
# Source: adapted from Python argparse documentation
# https://docs.python.org/3/library/argparse.html#sub-commands
```

### `sqlite3.Row` for Named Column Access
```python
import sqlite3

con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row

row = con.execute("SELECT 1 AS previous_disk_bytes, 2 AS current_disk_bytes").fetchone()
assert row["previous_disk_bytes"] == 1
assert row["CURRENT_DISK_BYTES"] == 2
```
```python
# Source: adapted from Python sqlite3 documentation
# https://docs.python.org/3/library/sqlite3.html#sqlite3.Row
```

### Recursive CTE for Hierarchy Walks
```sql
WITH RECURSIVE subtree(path) AS (
  VALUES(:root_path)
  UNION ALL
  SELECT child.path
  FROM directory_sizes AS child
  JOIN subtree ON child.parent_path = subtree.path
  WHERE child.snapshot_id = :snapshot_id
)
SELECT path
FROM subtree;
```
```sql
-- Source: adapted from SQLite WITH-clause documentation
-- https://www.sqlite.org/lang_with.html
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Broad live `df`/`du` spelunking during incidents. [VERIFIED: README.md] | Persist directory snapshots and answer growth questions from stored history. [VERIFIED: README.md + .planning/ROADMAP.md] | Project direction set 2026-06-12. [VERIFIED: README.md + .planning/ROADMAP.md] | Investigation starts from evidence instead of ad hoc rescans. [VERIFIED: README.md] |
| Raw recursive changed-path dumps. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] | Ranked growth frontier plus `explain-path` drill-down. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] | Phase 2 scope fixed 2026-06-13. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] | Default output stays compact enough for LLM agents. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] |
| Live-only mount inference for grouping. [VERIFIED: src/watchdirs/db/schema.sql] | Persist snapshot-time mount metadata and group by mount/domain from the snapshot itself. [VERIFIED: src/watchdirs/db/schema.sql][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] | Required by REPT-07 in Phase 2 planning. [VERIFIED: .planning/REQUIREMENTS.md + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] | Filesystem ownership and multi-SSD pressure reporting stay stable across time. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |

**Deprecated/outdated:**
- Treating `mount_id` as a durable cross-snapshot identity is outdated for this phase because the Linux docs say it may be reused after unmount. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
- Returning unlabeled `size` fields without explicit `previous` / `current` / `delta` names is outdated for this product because the Phase 2 contract explicitly forbids ambiguous size reporting. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md]

## Assumptions Log

All substantive claims in this research were verified against the current codebase, the Phase 2 context, or official documentation. No user-confirmation assumptions remain. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql + https://docs.python.org/3/library/sqlite3.html + https://www.sqlite.org/lang_with.html + https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| none | — | — | — |

## Open Questions (RESOLVED)

1. **How should `--since` behave when no same-root snapshot exists at or before the requested window boundary?**
   - What we know: the report must make the selected baseline/current snapshots explicit, and arbitrary cross-root pairing is unacceptable. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + src/watchdirs/db/schema.sql]
   - Resolution: pair selection first chooses the newest usable current snapshot for each root, then looks for the newest same-root baseline at or before `current.finished_at - --since`. If no snapshot exists at or before that cutoff but an older same-root snapshot exists before the current snapshot, use the oldest available earlier same-root snapshot and emit warning code `baseline_before_since_unavailable` in JSON/text selection metadata. If fewer than two usable same-root snapshots exist, return a structured no-pair error for that root and do not synthesize a cross-root pair. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + .planning/phases/02-growth-frontier-reporting/02-03-PLAN.md]
   - Planning effect: `pairs.resolve_snapshot_pairs()` and CLI tests must cover exact-boundary baseline, fallback baseline with warning, and no-pair behavior. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-03-PLAN.md]

2. **Should the default current snapshot prefer the newest `complete` snapshot over a newer `partial` snapshot?**
   - What we know: partial evidence must be surfaced, not hidden. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md]
   - Resolution: default current selection uses the newest non-failed snapshot for each root, including `partial` snapshots, because the incident workflow prioritizes current evidence over hiding newer partial data. Failed snapshots are excluded from usable pairs. Any pair containing a `partial` baseline or current snapshot must include snapshot `status`, `error`, and warning metadata so the agent knows the delta may be incomplete. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md + .planning/phases/01-trusted-snapshot-collection/01-CONTEXT.md + src/watchdirs/db/schema.sql]
   - Planning effect: `pairs.resolve_snapshot_pairs()` and renderers must expose partial/failure warnings; tests must cover newest partial current selection, failed snapshot exclusion, and explicit warning payloads. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-03-PLAN.md + .planning/phases/02-growth-frontier-reporting/02-04-PLAN.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime and CLI execution | yes | 3.13.5 [VERIFIED: python3 --version] | — |
| SQLite engine / `sqlite3` | Report query development and manual DB inspection | yes | 3.46.1 [VERIFIED: sqlite3 --version] | Python `sqlite3` module already available. [VERIFIED: python3 --version] |
| `pytest` | Validation architecture | yes | 8.3.5 [VERIFIED: pytest --version] | — |
| `du` | Optional cross-checks in future report verification | yes | 9.7 [VERIFIED: du --version] | Skip manual `du` comparison if not needed. |
| Repo-local `./watchdirs` | CLI smoke checks | yes | repo-local launcher present [VERIFIED: ./watchdirs present] | `PYTHONPATH=src python3 -m watchdirs` remains available. [VERIFIED: .planning/STATE.md + src/watchdirs/__main__.py] |

**Missing dependencies with no fallback:**
- none. [VERIFIED: python3 --version + sqlite3 --version + pytest --version]

**Missing dependencies with fallback:**
- none. [VERIFIED: python3 --version + sqlite3 --version + pytest --version]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 8.3.5` [VERIFIED: pytest --version] |
| Config file | [pyproject.toml](/home/j2h4u/repos/j2h4u/watchdirs/pyproject.toml:1) [VERIFIED: pyproject.toml] |
| Quick run command | `pytest -q` [VERIFIED: pytest -q] |
| Full suite command | `pytest -q` [VERIFIED: pytest -q] |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPT-01 | `diff --since` returns disk-growth-ranked rows | integration | `pytest tests/test_cli_report_commands.py::test_diff_since_json_sorted_by_disk_growth -q` | no - Wave 0 |
| REPT-02 | `report --since` returns structured summary with warnings and frontier rows | integration | `pytest tests/test_cli_report_commands.py::test_report_since_json_summary -q` | no - Wave 0 |
| REPT-03 | `top --snapshot latest` returns largest current trees | unit/integration | `pytest tests/test_reporting_queries.py::test_top_latest_sorted_by_current_disk_bytes -q` | no - Wave 0 |
| REPT-04 | `explain-path` drills into one subtree | integration | `pytest tests/test_frontier.py::test_explain_path_breaks_out_changed_children -q` | no - Wave 0 |
| REPT-05 | `deleted --since` returns earlier-only paths | unit/integration | `pytest tests/test_reporting_queries.py::test_deleted_since_returns_earlier_only_paths -q` | no - Wave 0 |
| REPT-06 | classifications distinguish created/deleted/unchanged/grown/shrunk | unit | `pytest tests/test_reporting_queries.py::test_diff_classifications_cover_all_states -q` | no - Wave 0 |
| REPT-07 | grouping by filesystem/storage domain is stable | integration | `pytest tests/test_grouping.py::test_grouping_uses_snapshot_mount_metadata -q` | no - Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest -q` until Wave 0 creates targeted Phase 2 files, then `pytest tests/test_reporting_queries.py tests/test_frontier.py -q`
- **Per wave merge:** `pytest -q`
- **Phase gate:** Full suite green before `$gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cli_report_commands.py` - CLI JSON/text contracts for `diff`, `report`, `top`, `deleted`, and `explain-path`
- [ ] `tests/test_reporting_queries.py` - snapshot-pair selection, classification, and top/deleted SQL behavior
- [ ] `tests/test_frontier.py` - parent/child pruning and explain-path residual logic
- [ ] `tests/test_grouping.py` - filesystem/storage-domain grouping via persisted mount metadata

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Local CLI only; no auth surface introduced in Phase 2. [VERIFIED: .planning/ROADMAP.md + src/watchdirs/cli.py] |
| V3 Session Management | no | Local CLI only; no session surface introduced in Phase 2. [VERIFIED: .planning/ROADMAP.md + src/watchdirs/cli.py] |
| V4 Access Control | no | Reports read the local SQLite file and do not add a new privilege boundary. [VERIFIED: src/watchdirs/db/connection.py + .planning/ROADMAP.md] |
| V5 Input Validation | yes | Strict argparse parsing, parameterized SQL, whitelist-only `group-by` / `snapshot` selector enums, and path normalization at render boundaries. [VERIFIED: src/watchdirs/cli.py + src/watchdirs/config.py][CITED: https://docs.python.org/3/library/argparse.html][CITED: https://docs.python.org/3/library/sqlite3.html] |
| V6 Cryptography | no | No cryptographic requirement in this phase. [VERIFIED: .planning/ROADMAP.md] |

### Known Threat Patterns for Python CLI + SQLite reporting

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dynamic SQL assembled from CLI sort/group fields | Tampering | Use parameter binding for values and whitelist symbolic sort/group names before mapping them to SQL fragments. [CITED: https://docs.python.org/3/library/sqlite3.html] |
| Misleading report due to dropped partial/failure status | Repudiation | Carry snapshot `status`, `error`, and row warning counts into every payload. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md] |
| Non-UTF-8 path corruption during report formatting | Tampering | Keep path bytes in SQLite and decode only at the final render boundary with the same surrogate-safe rules used elsewhere. [VERIFIED: src/watchdirs/db/schema.sql + src/watchdirs/models.py] |
| Cross-snapshot mount misattribution | Spoofing | Persist snapshot-time mount metadata and do not reuse live mountinfo or snapshot-local `mount_id` as a durable key. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html] |
| Unbounded result sets or explain recursion | Denial of Service | Require explicit limits/depth caps and keep default outputs compact. [VERIFIED: .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://www.sqlite.org/lang_with.html] |

## Sources

### Primary (HIGH confidence)
- Current repo code and planning docs - `src/watchdirs/{cli,models}.py`, `src/watchdirs/db/{connection,migrations,schema.sql}`, `.planning/{REQUIREMENTS,ROADMAP,STATE}.md`, and `.planning/phases/{01,02}-*.md` for actual product constraints and existing seams. [VERIFIED: local repo]
- Linux mountinfo manual page - fields and stability limits for mount grouping. [CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

### Secondary (MEDIUM confidence)
- Python `argparse` docs - subcommand dispatch pattern. [CITED: https://docs.python.org/3/library/argparse.html]
- Python `sqlite3` docs - `sqlite3.Row`, row factories, parameterized query surface. [CITED: https://docs.python.org/3/library/sqlite3.html]
- SQLite `WITH` and window-function docs - CTE and ranking constraints. [CITED: https://www.sqlite.org/lang_with.html][CITED: https://www.sqlite.org/windowfunctions.html]

### Tertiary (LOW confidence)
- `disktracker` GitHub README - same-root pairing and zero-delta pruning as ecosystem examples, used only as supporting inspiration and not as an implementation authority. [CITED: https://github.com/pratham15541/disktracker]

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - local runtime and existing codebase are verified, and no new package selection is required. [VERIFIED: python3 --version + sqlite3 --version + pyproject.toml]
- Architecture: MEDIUM - core seams are grounded in the current schema and official SQLite/mountinfo docs, but the exact frontier heuristic still needs plan-time codification. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://www.sqlite.org/lang_with.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]
- Pitfalls: MEDIUM - they are strongly implied by the current data model and official mount/SQLite constraints, but Phase 2 has not yet implemented the report layer. [VERIFIED: src/watchdirs/db/schema.sql + .planning/phases/02-growth-frontier-reporting/02-CONTEXT.md][CITED: https://www.sqlite.org/windowfunctions.html][CITED: https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html]

**Research date:** 2026-06-13
**Valid until:** 2026-07-13
