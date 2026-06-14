---
phase: 03-pressure-gap-diagnostics
plan: 03
subsystem: diagnostics
status: complete
tags: [diagnostics, docker, buildx, containerd, enrichment, read-only, df-gap]
requires:
  - reporting/queries.resolve_top_snapshot_selection
  - reporting/render._dedupe_rendered_warnings
provides:
  - diagnostics/docker.collect_docker_enrichment
  - diagnostics/docker.parse_docker_system_df
  - diagnostics/docker.parse_docker_buildx_du
  - reporting/render.render_docker_enrichment_payload
  - reporting/render.render_docker_enrichment_text
  - cli.run_docker_enrichment (watchdirs docker-enrichment)
affects:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/diagnostics/__init__.py
  - src/watchdirs/diagnostics/docker.py
  - src/watchdirs/reporting/render.py
  - src/watchdirs/reporting/__init__.py
tech-stack:
  added: []
  patterns:
    - injectable docker_runner / generated_at_provider seams for deterministic tests
    - fixed-argv subprocess (shell=False) with no user interpolation, read-only only
    - NDJSON (line-delimited JSON) parser tolerant of blank/malformed/non-object lines
    - dual Size parsing (raw byte int OR human string like 8.192kB / 7.451GB)
    - containerd path hints surfaced as path context only, never category totals (D-11)
key-files:
  created:
    - src/watchdirs/diagnostics/docker.py
    - tests/test_diagnostics_docker.py
  modified:
    - src/watchdirs/models.py
    - src/watchdirs/diagnostics/__init__.py
    - src/watchdirs/reporting/render.py
    - src/watchdirs/reporting/__init__.py
    - src/watchdirs/cli.py
decisions:
  - Docker enrichment is auxiliary, bounded, read-only evidence; it never mutates Docker/containerd and never replaces filesystem indexing (D-12/D-13).
  - "/var/lib/containerd" indexed/path-hint evidence emits containerd_available=false plus a containerd_enrichment_unavailable warning; the module has no containerd-native probe and never fabricates containerd reclaimable/active/category totals (D-11).
  - The single docker_runner host seam defaults to the live Docker CLI inside the collector; the CLI handler injects nothing at runtime except optional --db indexed path-hint discovery (WATCHDIRS_TEST_NO_DOCKER forces absent-Docker only for the deterministic CLI envelope test).
  - Verification next checks are read-only ("docker system df --format json", "docker buildx du --format json", "watchdirs df-vs-index --json"); no prune/rm/stop/down/reload command is emitted anywhere (argv, render, text, JSON, tests, source).
  - "docker buildx du --format json" Size is a human string on current Docker clients, so the parser accepts both raw byte ints and human sizes; otherwise live build-cache totals collapse to 0.
metrics:
  duration: 6min
  completed: 2026-06-14
  tasks: 2
  files: 7
  tests_added: 16
  tests_total: 147
---

# Phase 3 Plan 3: docker-enrichment Diagnostic Summary

`watchdirs docker-enrichment --json` enriches container-storage pressure with
auxiliary, read-only Docker CLI category evidence (images, containers, local
volumes, build cache) and bounded build-cache detail, plus honest
`/var/lib/containerd` path hints that are explicitly marked
`containerd_available=false` rather than presented as containerd category
totals. Docker absence, daemon errors, empty output, and malformed lines all
degrade to warnings without breaking other diagnostics, and the command never
emits or executes a Docker/containerd mutation command (D-11/D-12/D-13).

## What Was Built

- **`parse_docker_system_df()`** (diagnostics/docker.py): parses
  `docker system df --format json` NDJSON into `DockerCategory` rows per D-11
  (Type/TotalCount/Active/Size/Reclaimable). `Active`/`TotalCount` arrive as JSON
  strings on the live host and are coerced to ints; `Size`/`Reclaimable` keep the
  raw human label and also resolve to bytes via `_parse_size_text` (handles
  `12GB (60%)` reclaimable suffixes). Blank/malformed/non-object lines surface as
  `docker_malformed_output` warnings, never crashes.
- **`parse_docker_buildx_du()`**: parses `docker buildx du --format json` NDJSON
  into `DockerBuildCacheEntry` rows plus `DockerBuildCacheTotals` separating
  reclaimable bytes from total bytes. Blank output is a valid empty result.
- **`collect_docker_enrichment()`**: orchestrates both fixed read-only probes via
  an injectable `docker_runner`; classifies absent-CLI (FileNotFoundError →
  `docker_unavailable`), daemon errors (`docker_daemon_error`), nonzero/exec
  failures (`docker_command_failed`), and stderr warnings (`docker_stderr`);
  sorts build-cache by size desc and caps by `--limit` with truncation metadata.
  Splits supplied `indexed_path_hints` into `docker_path_hints` and
  `containerd_path_hints`; containerd hints add an explicit
  `containerd_enrichment_unavailable` warning and keep `containerd_available=false`.
- **Renderers** `render_docker_enrichment_payload` / `render_docker_enrichment_text`
  reusing existing escaping (`_text_field`, `_text_path`, `_escape_text_field`)
  and warning de-duplication, with a compact build-cache block carrying entry/total
  counts and `truncated`.
- **CLI** `docker-enrichment` (`--db`, `--limit`, `--json`); a thin handler whose
  optional `--db` discovers persisted indexed paths under `/var/lib/docker` and
  `/var/lib/containerd` from the latest snapshots via parameterized `GLOB`
  matching (path context only, no reclaimability inference).
- New frozen/slotted dataclasses: `DockerCategory`, `DockerBuildCacheEntry`,
  `DockerBuildCacheTotals`, `DockerEnrichment`.

## Verification

- `python3 -m pytest -q tests/test_diagnostics_docker.py` — 16 passed (RED→GREEN).
- `python3 -m pytest -q tests/test_diagnostics_df_index.py tests/test_diagnostics_deleted_open.py` — 23 passed (prior diagnostics unaffected).
- `python3 -m pytest -q` — 147 passed (131 prior + 16 new).
- Live smoke: `watchdirs docker-enrichment --json` on the host returned real
  category bytes (Images 25.06GB, Build Cache 7.451GB total/reclaimable matching
  `docker system df`), 52 build-cache entries with non-zero totals after the Size
  fix, `docker_available=true`, `containerd_available=false`, and only read-only
  verification commands. `WATCHDIRS_TEST_NO_DOCKER=1 ... docker-enrichment` text
  mode produced the stable absent-Docker envelope with `docker_unavailable`.

## Threat Model Coverage

All `mitigate` dispositions are satisfied: fixed read-only argv + `shell=False`,
no command interpolation (T-03-11); source command, docker/containerd
availability fields, path hints, exit/daemon/stderr/malformed warnings
(T-03-12); top-N build-cache limiting + truncation metadata (T-03-13);
verification-only next checks, no mutation command in argv/render/text/JSON/tests/
source (T-03-14); local Docker paths/images intentionally surfaced to the
operator/agent (T-03-15, accept); no package installs — stdlib + installed Docker
CLI only (T-03-SC).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] buildx du Size is a human string, not raw bytes**
- **Found during:** Task 2 (GREEN) live smoke test, which showed every
  build-cache `size_bytes=0` and `build_cache_total_bytes=0`.
- **Issue:** Current Docker clients emit `docker buildx du --format json` with
  `"Size":"8.192kB"` / `"7.451GB"` (human string), not a raw byte integer as the
  initial RED fixture assumed. `_coerce_int` returned None and the size fell back
  to 0, so live build-cache totals were always zero.
- **Fix:** Try integer coercion first, then `_parse_size_text` human-size parsing.
- **Files modified:** src/watchdirs/diagnostics/docker.py
- **Test:** Added `test_parse_docker_buildx_du_accepts_human_string_sizes`
  mirroring the host output shape (`7.451GB`, `8.192kB`).
- **Commit:** ceb1a2e

## TDD Gate Compliance

- RED: `test(03-03)` commit `3caf9ee` added 15 failing tests (module/command/
  renderers absent).
- GREEN: `feat(03-03)` commit `ceb1a2e` made all pass (16 after the Size
  regression test); full suite stayed green.
- REFACTOR: not required; implementation was clean on first GREEN apart from the
  Size-parsing bug fixed inline under Rule 1.

## Self-Check: PASSED

All created files exist on disk and both per-task commits (`3caf9ee`, `ceb1a2e`)
are present in git history.
