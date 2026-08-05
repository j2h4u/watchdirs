# Persistent Growth Investigation Plan

Status: in progress
Source report: [Persistent Disk Growth Investigation: Product Feedback Report](persistent-disk-growth-investigation-report-2026-08-05.md)

## Goal

Make `watchdirs` answer the operator question:

> What is persistently consuming disk space over the last N days, and what
> read-only evidence should I inspect next?

The target interface is:

```bash
watchdirs investigate --since 14d --json
```

The command should be safe for unattended, agent-driven diagnostics. It must not
delete data, stop services, prune Docker, or mutate application state.

## Problem to solve

Current `watchdirs` reports are good at endpoint comparison: they explain what
changed between a baseline snapshot and a later snapshot. That is not enough for
persistent disk-pressure incidents.

Endpoint deltas cannot reliably distinguish:

- steady daily growth;
- one-time imports;
- bursty build or indexing activity;
- grow-then-clean churn;
- large stable directories that are not currently growing;
- live writes that happened after the latest retained snapshot.

The next increment should add a trend-oriented analysis layer over retained
snapshots and filesystem-capacity history.

## Non-goals

- No destructive cleanup operations.
- No permanent per-file history.
- No daemon or external job queue.
- No cross-filesystem descent beyond existing `watchdirs` collection rules.
- No attempt to fully replace specialist tools such as `docker`, `lsof`, or
  package-manager cache commands.

## Product contract

`watchdirs investigate --since DURATION --json` returns:

- a short verdict;
- evidence window metadata;
- filesystem pressure over the same window;
- ranked growth contributors;
- deterministic growth-shape labels;
- confidence and blind spots;
- read-only next-check commands.

The query socket should expose the same read-only result once the CLI behavior
is stable.

## Data model work

Add filesystem-capacity history captured with each successful snapshot.

Candidate table:

```sql
CREATE TABLE snapshot_filesystems (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    mount_id INTEGER NOT NULL,
    major_minor TEXT NOT NULL,
    root BLOB NOT NULL,
    mount_point BLOB NOT NULL,
    filesystem_type TEXT NOT NULL,
    mount_source TEXT NOT NULL,
    total_bytes INTEGER,
    used_bytes INTEGER,
    free_bytes INTEGER,
    available_bytes INTEGER,
    capture_error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX snapshot_filesystems_snapshot_idx
ON snapshot_filesystems(snapshot_id);
```

Implementation notes:

- Capture filesystem usage before or after directory collection, but attach it
  to the snapshot record and preserve capture errors.
- Use the same filesystem-boundary semantics as collection.
- Store values as bytes, not human-readable strings.
- Keep schema migration compatible with existing SQLite databases.

## Trend-analysis work

For a requested window, load retained snapshots across the window instead of
only baseline and endpoint.

For each candidate path or frontier category compute:

- start size;
- end size;
- net delta;
- gross positive delta;
- gross negative delta;
- first observed sample;
- first non-zero or first appearance;
- last growth sample;
- peak size;
- daily slope;
- volatility;
- sample count;
- missing-sample count.

Initial growth-shape labels:

| Label | Meaning |
|---|---|
| `steady_growth` | Size increases across several samples with low reversal. |
| `one_time_jump` | Most growth happened in one early interval and then stabilized. |
| `bursty_growth` | Growth happened in a small number of separated bursts. |
| `grow_then_clean` | Size grew materially and later shrank materially. |
| `current_burst_after_latest_snapshot` | Live filesystem pressure is worse than the latest indexed snapshot can explain. |
| `stable_large` | Directory is large but not materially growing in the selected window. |
| `unknown_insufficient_samples` | Too few samples or too many errors to classify. |

Thresholds should be deterministic constants in code with focused tests. Avoid
model- or prompt-dependent classification.

## CLI output shape

The JSON result should be stable enough for agents to consume. A first version
can use this shape:

```json
{
  "ok": true,
  "schema_version": 1,
  "command": "investigate",
  "window": {
    "since": "14d",
    "snapshot_count": 42,
    "started_at": "...",
    "ended_at": "..."
  },
  "verdict": {
    "summary": "Persistent growth is dominated by local index state and development worktrees.",
    "confidence": "medium"
  },
  "filesystem_pressure": {
    "mount_point": "/",
    "used_delta_bytes": 123,
    "available_delta_bytes": -123,
    "latest_index_gap_bytes": 0
  },
  "contributors": [
    {
      "path": "/example",
      "rank": 1,
      "chain": {
        "role": "standalone",
        "nested_under_rank": null,
        "nested_under_path": null,
        "has_nested_contributors": false
      },
      "category": "local_index_state",
      "shape": "steady_growth",
      "net_delta_bytes": 123,
      "current_bytes": 456,
      "daily_slope_bytes": 789,
      "confidence": "high",
      "evidence": {
        "sample_count": 42,
        "last_growth_at": "..."
      },
      "next_checks": [
        "watchdirs explain-path /example --since 14d --depth 3 --json"
      ],
      "next_actions": [
        {
          "kind": "explain_path",
          "read_only": true,
          "command": "explain-path",
          "argv": ["explain-path", "/example", "--since", "14d", "--depth", "3", "--json"],
          "path": "/example",
          "path_bytes_hex": "2f6578616d706c65",
          "reason": "drill down into this contributor using retained snapshot evidence"
        }
      ]
    }
  ],
  "blind_spots": [],
  "next_actions": []
}
```

No human-readable `investigate` renderer is planned. The command is an
agent-facing investigation primitive; stable JSON is the product contract.
`next_checks` remains as string compatibility output; `next_actions` is the
preferred machine-action contract.
Contributor `chain` metadata prevents agents from double-counting nested rows
such as `/var`, `/var/lib`, and `/var/lib/containerd`; the verdict's
`actionable_path` points at the deepest contributor in the top nested chain.

## Implementation sequence

1. Add schema migration and collection of filesystem-capacity history. Done in
   the first implementation increment.
   - Tests: migration, collection success, collection error preservation.
   - Gate: `just unit` for migration/collection tests.

2. Add internal trend metrics over retained snapshots. Done for pure time-series
   metrics and deterministic growth-shape classification.
   - Keep this as library code first.
   - Tests: steady growth, one-time jump, bursty growth, grow-then-clean,
     insufficient samples.

3. Add query assembly for retained snapshot time series. Done for per-path
   trend rows over selected retained snapshots.
   - Load path samples across a requested window.
   - Feed samples into the trend metrics library.
   - Tests: sample ordering, missing paths, interval-backed complete snapshots,
     diagnostic partial snapshots.

4. Add `watchdirs investigate --since --json`. Done for the initial JSON-only
   CLI contract.
   - Start with JSON only.
   - Reuse existing report/diff/path aggregation code where practical.
   - Tests: CLI schema, contributor ordering, error handling.
   - Runtime note: live 14-day investigations are rare and may take roughly
     1-2 minutes on the current host-scale database. The query socket is
     bounded by a SQLite progress deadline rather than an unbounded Python
     signal-only timeout.

5. Add filesystem-pressure reconciliation. Done for the initial JSON payload.
   - Compare directory growth against recorded filesystem usage.
   - Surface current-vs-index drift using existing live diagnostics where safe.
   - Tests: filesystem usage deltas, capture-error accounting, and
     `investigate` live/index blind-spot surfacing.

6. Add query-socket support. Done for the initial read-only `investigate`
   JSON contract.
   - Read-only only.
   - Tests: socket command authorization and JSON response parity.

7. Do not add human-readable `investigate` rendering.
   - Keep `investigate` JSON-only.
   - Spend follow-up work on agent-consumable evidence quality, not terminal
     prose formatting.

## Validation gates

For implementation changes:

```bash
just check
just unit
```

Run targeted tests for:

- schema migration;
- snapshot collection;
- retention interactions;
- query socket;
- CLI JSON output;
- deterministic growth-shape classification.

Run `just coverage` when the implementation materially changes covered behavior
or lowers meaningful coverage.

## Open decisions

1. Whether category labels should be purely path-pattern based at first, or
   inferred only from existing `watchdirs` data.
2. How aggressive frontier pruning should be for nested contributors.
3. Whether filesystem history should include only the root filesystem in v1 or
   every collected mount point.
