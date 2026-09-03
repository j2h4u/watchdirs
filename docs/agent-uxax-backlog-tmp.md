# Agent UX/AX backlog for disk-growth investigations

Temporary working document. Keep this as an agent handoff/backlog while the
current investigation is in progress. Sanitize before treating it as public
documentation.

## Current scenario

An agent needs to answer: disk usage rose and stayed high over the last 1-3
days despite routine cleanup. The useful answer is not a raw dump. The useful
answer is a compact evidence packet:

- what changed;
- over which snapshot window;
- how much of `df` is explained by the index;
- what is probably persistent vs reclaimable;
- what exact read-only drill-down command should run next.

## Observed live friction

- [x] `report --since 24h --limit 12 --json --group-by storage-domain` took
      about 53s before returning useful data during the initial investigation.
      After the report-query optimizations and removal of the hidden pressure
      pass, the same production smoke completed in about 3.8-4.7s.
- [x] `report --since 48h --limit 12 --json --group-by storage-domain` took
      about 54s before returning useful data during the initial investigation.
      After the report-query optimizations and removal of the hidden pressure
      pass, the same production smoke completed in about 4.8-5.3s.
- [ ] A multi-command socket investigation batched several expensive commands
      behind one request stream and gave no progress until interrupted.
- [ ] `snapshots --limit 100 --json` took about 71s, even though the desired
      output was only a compact time-series summary.
- [ ] `snapshots --limit 1000 --json` took about 82s for 135 snapshots.
- [ ] `snapshots --limit 100000 --json` correctly returned `limit_too_large`,
      but the max-limit contract is discoverable only after failing or reading
      code/output.
- [x] Query socket responses wrap CLI JSON inside `stdout`; agent clients must
      parse a nested JSON envelope instead of receiving one typed result object.
      Implemented compatibly by retaining `stdout` while adding parsed
      `payload` and `elapsed_seconds`.
- [ ] Long-running read-only socket requests do not stream phase/progress/timing
      information, so an agent cannot distinguish "still healthy" from "stuck".
- [ ] Existing `report` output includes useful data, but also enough nested
      detail that agents need custom post-processing to avoid context bloat.
- [ ] `report` can collapse an entire 72h window to `/` with many suppressed
      descendants, which proves root growth but is not immediately actionable.
- [x] `report` can also overstate actionability for hardlinked generation
      directories: a newly visible path can show multi-GiB `disk_bytes_delta`
      even when the parent directory's unique block usage barely changed.
      Scanner now persists aggregate hardlink counters, and read-only JSON rows
      expose `hardlinks.sensitive` plus duplicate/first-seen counters.
- [x] `watchdirs stats` does not exist; a natural agent expectation for DB /
      snapshot count currently falls through to a CLI error.
- [x] Snapshot history/time-series requires the expensive `snapshots` command;
      there is no cheap `timeline` / `history` / `totals` command.
- [x] There is no single "agent digest" command that combines top growth,
      blind spots, and next read-only drill-downs in a bounded payload.
- [x] Fast digest currently does not inline pressure reconciliation; it emits
      read-only `df-vs-index` and `deleted-open-files` next actions instead.
      Fast digest now includes compact latest `df-vs-index` pressure
      reconciliation and still suggests deleted-open-files as a follow-up when
      useful.
- [x] Diagnostic JSON section names were not fully consistent while `report`
      carried an automatic pressure summary with a different shape from
      `df-vs-index`. The hidden report pressure pass was removed; pressure
      reconciliation now lives in `investigate` and explicit `df-vs-index`
      output instead of adding parser branching to `report`.
- [x] `investigate` contributor fields are MiB-first, but `explain-path`
      previously used byte fields such as `disk_bytes_delta`.
      `explain-path` now emits MiB-first target, child, hardlink, and residual
      fields in its JSON output, so drill-down summaries no longer need byte
      conversion glue. Low-level `diff` remains an advanced exact-byte
      diagnostic.
- [x] `docker-enrichment` was text-by-default and required `--json`.
      It now emits machine-readable JSON by default and no longer exposes
      `--json` in the command surface.
- [x] `explain-path` is now fast enough for live drill-downs, but its JSON
      reported byte fields while `investigate` reports integer MiB fields.
      `explain-path` now reports operator-facing deltas and sizes as integer
      MiB fields.
- [x] `timeline` can reveal the exact snapshot interval where a spike happened,
      but `investigate`, `diff`, `report`, and `explain-path` only accept
      relative `--since` windows. Agent-operators need a read-only way to drill
      into a specific baseline/current snapshot pair without knowing the DB
      path or using privileged internal APIs. Partially addressed by adding the
      largest per-path growth interval to each `investigate` burst payload, so
      the digest can say both when and where the largest observed path spike
      happened. `explain-path` now accepts exact `--from-snapshot` /
      `--to-snapshot` ids, and burst next actions use them automatically.
- [x] `investigate` verdict/top_path can over-prioritize high burst-ratio
      `grow_then_clean` paths over the largest persistent net growth. In the
      2026-09-02 24h smoke it recommended `<home>/.cache` (`+178 MiB` net)
      ahead of `/var/lib/containerd` (`+4466 MiB` net). Agents need either
      separate "bursty anomaly" and "persistent growth" sections or a verdict
      that prefers material net growth when the operator asks why disk remains
      full. Addressed by schema v3: `contributors` /
      `persistent_contributors` are net-growth ordered, `burst_anomalies` is
      burst-signal ordered, and verdict top_path follows persistent growth.
- [x] Large same-parent directory moves can look like new disk growth because
      path-based diffs see the new path as `created` and the old path as
      `deleted`. Addressed by schema v4: `investigate` emits
      `relocation_suspicions` and excludes strict same-parent relocation matches
      and their subtrees from primary persistent/burst rankings.
- [x] Operator-facing command examples and help leaked the production database
      mental model. Read-only `--db` remains accepted for development and
      legacy copy-paste compatibility, but is hidden from read-only help; no-arg
      `watchdirs` now prints help, and `stats` reports `storage` rather than a
      `database` object.
- [x] Fresh 2026-09-03 live smoke: `report` and `explain-path` could show large
      positive path deltas for same-filesystem moves/regenerations even when
      the explained root/path did not grow. Addressed by adding
      `disk_pressure_interpretation` to `report` and `explain-path`; it labels
      `local_growth_offset_by_shrink`, `mixed_growth_and_cleanup`,
      `net_indexed_growth`, and `net_path_growth` so agents do not confuse path
      churn with lost free space.
- [x] `docker-enrichment` does not attribute Docker's active containerd
      snapshotter paths such as `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/<id>`
      back to image/container/build-cache ownership. Fresh 2026-09-03 operator
      drill-down found Playwright/Chromium-heavy snapshot IDs, but
      `docker-enrichment` still reported `containerd_available=false`.
      Addressed by read-only Docker container/image listing plus bounded
      `docker inspect --type ... <id>` owner hints that map containerd snapshot
      IDs and docker overlay IDs back to containers/images when Docker exposes
      those paths.
- [x] `deleted-open-files` can surface large `/dev/zero` mappings on `devtmpfs`
      as if they were disk-space culprits. Fresh 2026-09-03 operator output
      reported multi-GiB PostgreSQL `/dev/zero` entries, while direct evidence
      did not indicate a multi-GiB ext4 deleted-open-file leak. Addressed by
      `disk_pressure_relevance=non_disk_mapping` and separate totals for
      disk-pressure-relevant bytes vs non-disk mappings.
- [x] Docker build-cache reclaimability is inconsistent between compact
      category totals and detailed Buildx cache rows. Fresh 2026-09-03 operator
      report saw category-level reclaimable space much lower than detailed
      Buildx reclaimable cache, making cleanup judgment ambiguous. Addressed by
      explicit JSON fields for `system_df_reclaimable_bytes`,
      detailed `reclaimable_bytes`, and `effective_reclaimable_bytes`, plus a
      mismatch warning when the numbers materially disagree.
- [x] `stats` should expose installed watchdirs unit/timer/socket provenance or
      exact verification commands. A fresh agent-operator checked generic
      `watchdirs.service` / `watchdirs.timer` names and incorrectly concluded
      the service was inactive; the real installed units are
      `watchdirs-collect.timer`, `watchdirs-prune.timer`,
      `watchdirs-vacuum.timer`, and `watchdirs-query.socket`. Addressed by a
      `service_surface` block in `stats --json` with unit names and exact
      verification commands.
- [x] JSON flag behavior is still inconsistent across read-only commands:
      `report` requires `--json`, `explain-path` accepts hidden `--json` as a
      no-op, and `df-vs-index`, `deleted-open-files`, and `docker-enrichment`
      emit JSON by default but do not all advertise/accept the same flag shape.
      Addressed by accepting hidden `--json` as a no-op on JSON-default
      diagnostics while preserving their default JSON behavior.
- [ ] Independent auditor must verify that these fixes are actually implemented
      in code, covered by tests, and visible in operator-facing JSON.

## Product gaps to consider

- [x] Add a compact agent-facing digest as the default investigation path,
      e.g. `watchdirs investigate`.
- [x] Digest output should include only bounded contributors, blind spots,
      confidence, and next actions.
- [x] Consider whether fast digest should inline compact pressure
      reconciliation now that `df-vs-index` is fast enough in the observed DB.
- [x] Digest should avoid full snapshot lists, full sample arrays, verbose
      per-filesystem facts, raw Docker payloads, and duplicate humanized byte
      fields unless explicitly requested.
- [x] Add a cheap time-series command for per-snapshot or per-day root totals,
      e.g. `watchdirs timeline --since 14d`.
- [x] Add a cheap metadata/status command, `watchdirs stats --json`, with DB
      page size/count/bytes, snapshot count, status counts, latest snapshot,
      and schema version.
- [ ] Consider extending `stats` with configured retention policy once config
      discovery is part of the read-only diagnostic path.
- [x] Query socket should ideally return a typed JSON envelope with parsed
      payload, command runtime, return code, and stderr, rather than requiring
      nested `stdout` JSON parsing.
- [ ] Long socket commands should expose timing/progress events or at least
      command start/finish/running-state observability for agents.
- [x] `investigate` / digest should emit exact safe drill-down argv arrays, not
      only prose hints.
- [x] Digest should report whether the indexed total matches current `df`, and
      the unexplained delta, before recommending cleanup hypotheses.
- [x] Digest should be hardlink-aware: distinguish path-level growth from
      unique block growth, and label low-confidence contributors when a path's
      files have multiple links.
      Current fast digest exposes aggregate hardlink evidence per contributor.
      It does not store per-inode hardlink groups; that remains intentionally
      deferred until aggregate evidence proves insufficient.

## Performance gaps to consider

- [ ] `query_snapshot_summaries()` reconstructs interval state for selected
      snapshots; cost grows with snapshots times full interval state.
- [x] Fresh 2026-09-02 smoke: `timeline --since 7d --json` took about `29s`
      for 99 points. It answered the question, but it is too slow for an
      operator's normal first-pass loop. Fixed by reading root totals in one
      bounded batch and adding a narrow `depth = 0` interval index; fresh
      2026-09-03 smoke: `timeline --since 7d --limit 100` took about `1.15s`
      for 91 points before the production DB even had the new index applied.
- [x] `report` reconstructed full baseline/current states and created Python
      `DiffRow` objects for all paths before frontier pruning; `LIMIT` applies
      after expensive work. Fixed for the operator report path by omitting
      unchanged rows from `DiffRow` materialization and keeping frontier/deleted
      evidence identical. Fresh 2026-09-03 smoke: `report --since 24h --limit 12
      --json --group-by storage-domain` improved from about `10.06s` to `4.67s`;
      `48h` improved from about `9.53s` to `5.24s`.
- [x] `_build_report_pressure_summary()` added another full-state pass via
      indexed storage-domain totals. Fixed by removing automatic pressure
      reconciliation from `report`; current pressure evidence remains available
      through explicit `df-vs-index` and `investigate` flows. Fresh 2026-09-03
      smoke: `df-vs-index` alone took about `2.19s`, and removing the hidden pass
      reduces `report` first-pass latency further.
- [x] Add a bounded SQL path for digest/top-growth that filters to root or
      depth-limited rows before materializing full trees.
- [ ] Consider persisted per-snapshot summaries populated during collection
      finalization so `snapshots --limit N` and timeline are metadata reads.
- [ ] Consider persisted depth-1 snapshot aggregates for fast first-level
      growth digest.
- [x] Consider a narrow partial index for depth-limited digest, e.g. interval
      rows where `depth <= 3`; avoid broad indexes that do not remove validity
      reconstruction cost.
- [x] Add query-step/progress-handler regression tests proving fast commands do
      not materialize the whole tree.

## Current investigation notes, sanitized

- [ ] Current root filesystem usage observed as about `164G used / 202G total`
      with about `28-29G available`.
- [ ] Watchdirs latest indexed root total was about `162.9 GiB`, close to `df`;
      index gap was about `0.5 GiB`, so the latest snapshot largely explains
      visible disk usage.
- [ ] Over 24h, report showed about `+12.1 GB` indexed disk growth.
- [ ] Over 48h, report showed about `+15.9 GB` indexed disk growth.
- [ ] Over 72h, one collapsed frontier row showed root growth of about
      `+10.1 GiB`; useful for pressure confirmation but too coarse for action.
- [ ] Top 24-48h contributors included:
      - `<home>/.ctx/search/lexical/index-generations/<generation>` around
        `+6.7 GiB`;
      - `<home>/.codex` around `+1-1.6 GiB`;
      - container overlay/containerd snapshot paths around several `~1 GiB`
        contributors;
      - `/srv` around `+1 GiB`;
      - `<home>/backups/restic-repo/data` around `+0.7 GiB`.
- [ ] Deleted-open-files check found only about `64 MiB`, not enough to explain
      the persistent growth.
- [ ] Current Docker `system df` showed low reclaimable space in ordinary
      cleanup terms: images around `430 MB` reclaimable and build cache around
      `515 MB` reclaimable, so daily Docker cleanup is probably not missing a
      large obvious reclaimable bucket.
- [ ] Live filesystem mtime sampling over the last 3 days showed apparent
      changed-file volume on the same order as the reported persistent growth:
      `<home>/.codex` around `7.9 GiB`, `<home>/backups/restic-repo/data`
      around `9.9 GiB`, and `/srv` around `2.3 GiB`. This is investigative
      evidence, not deletion guidance.
- [ ] Recent Docker images are persistent/active rather than obviously
      reclaimable: examples included application/worker images created in the
      last 1-2 days. Digest should separate "active persistent footprint" from
      "safe reclaimable cleanup".
- [ ] `<home>/.ctx` contained two lexical index generation directories with
      hardlinked large files. Apparent duplicate path listings can be
      misleading; link count and disk blocks must be checked before calling it
      duplicated disk usage.
- [ ] Later observation found three lexical index generation directories. Each
      individual generation appeared around `6.68 GiB`, but all generations
      together were still around `6.68 GiB` unique blocks because most large
      files were hardlinked. This likely explains a misleading top contributor,
      not a real multi-generation disk leak.
- [ ] Ordinary unprivileged `du -x /` underreported total `df` usage; rely on
      watchdirs `df-vs-index`, Docker accounting, and privileged checks where
      necessary.
- [ ] Fresh 2026-09-02 smoke: `investigate` completed in about `2.2s`,
      `df-vs-index` in about `2.2s`, `deleted-open-files` in about `0.9s`,
      and `explain-path` in about `2-4s` for current top suspects.
- [ ] Fresh 2026-09-02 24h window: current material growth was led by
      `/var/lib/containerd` at about `+4.4 GiB`, split roughly into
      `io.containerd.snapshotter.v1.overlayfs` at about `+3.4 GiB` and
      `io.containerd.content.v1.content` at about `+1.0 GiB`.
- [ ] Fresh 2026-09-02 24h window: `/home/<user>/.codex` was about
      `+0.9 GiB`, mostly `packages` and `sessions`; this is visible growth but
      smaller than the containerd increase.
- [ ] Fresh 2026-09-02 7d timeline: largest root growth intervals were around
      `+8.3 GiB` from `2026-08-31T18:00Z` to `19:00Z`, around `+5.6 GiB` from
      `2026-08-31T19:00Z` to `20:00Z`, and around `+7.4 GiB` from
      `2026-09-02T08:00Z` to `09:00Z`. `timeline` now returns these as
      bounded `largest_growth_intervals` entries instead of requiring manual
      point-to-point subtraction.
- [ ] Fresh 2026-09-02 7d `investigate` took about `73s`. It eventually showed
      the week-level persistent contributors, led by `<home>/.hermes`,
      `/srv`, `<home>/.codex`, `<home>/backups`, and knowledgebase
      transcripts, but this is too slow for the intended bounded digest path.

## Candidate compact JSON shape

```json
{
  "ok": true,
  "schema_version": 1,
  "command": "investigate",
  "mode": "fast",
  "window": {
    "since": "48h",
    "snapshot_count": 8,
    "baseline_snapshot_id": 1175,
    "latest_snapshot_id": 1223,
    "coverage": "complete"
  },
  "verdict": {
    "status": "persistent_growth",
    "confidence": "medium",
    "summary": "Root usage grew and the index explains current df closely."
  },
  "pressure": {
    "latest_df_used_bytes": 175414591488,
    "latest_indexed_visible_disk_bytes": 174937051136,
    "unattributed_bytes": 477540352,
    "recent_growth_disk_bytes": 15912685568
  },
  "contributors": [
    {
      "rank": 1,
      "path": "<home>/.ctx/search/lexical/index-generations/<generation>",
      "classification": "created",
      "current_disk_bytes": 7173849088,
      "disk_bytes_delta": 7173849088,
      "confidence": "high",
      "reason": "highest-signal growth target"
    }
  ],
  "blind_spots": [],
  "next_actions": [
    {
      "kind": "explain_path",
      "read_only": true,
      "argv": [
        "explain-path",
        "<path>",
        "--since",
        "48h",
        "--depth",
        "3"
      ],
      "reason": "Drill into the largest persistent contributor."
    }
  ],
  "timings": {
    "total_seconds": 2.5
  }
}
```
