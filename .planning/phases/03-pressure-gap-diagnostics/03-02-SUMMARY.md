---
phase: 03-pressure-gap-diagnostics
plan: 02
subsystem: diagnostics
status: complete
tags: [diagnostics, deleted-open, lsof, procfs, live-probe, df-gap]
requires:
  - reporting/queries.resolve_top_snapshot_selection
  - db/migrations.load_snapshot_mounts
provides:
  - diagnostics/deleted_open.collect_deleted_open_files
  - diagnostics/deleted_open.parse_lsof_field_output
  - diagnostics/deleted_open.scan_procfs_deleted_open
  - reporting/render.render_deleted_open_payload
  - reporting/render.render_deleted_open_text
  - cli.run_deleted_open_files (watchdirs deleted-open-files)
affects:
  - src/watchdirs/cli.py
  - src/watchdirs/models.py
  - src/watchdirs/diagnostics/__init__.py
  - src/watchdirs/diagnostics/deleted_open.py
  - src/watchdirs/reporting/render.py
  - src/watchdirs/reporting/__init__.py
tech-stack:
  added: []
  patterns:
    - injectable lsof_runner / proc_root / generated_at_provider / domain_resolver seams for deterministic tests
    - fixed-argv subprocess (shell=False) with no user interpolation
    - lsof-preferred probe with bounded procfs fallback (size None + evidence warning)
    - NUL-field parser that strips lsof -F0 per-line newline framing
key-files:
  created:
    - src/watchdirs/diagnostics/deleted_open.py
    - tests/test_diagnostics_deleted_open.py
  modified:
    - src/watchdirs/models.py
    - src/watchdirs/diagnostics/__init__.py
    - src/watchdirs/reporting/render.py
    - src/watchdirs/reporting/__init__.py
    - src/watchdirs/cli.py
decisions:
  - Deleted-open evidence is a live process/fd diagnostic only; it is never persisted as directory_sizes rows (D-10).
  - lsof is preferred because it carries sizes; the procfs fallback runs only when lsof is unavailable or produced no usable stdout, and it sets size to None with an evidence warning rather than guessing.
  - The two host seams (lsof_runner, proc_root) default to the live host only inside the collector; the CLI handler stays thin and injects nothing at runtime except optional --db storage-domain resolution.
  - Action hints are cautious non-command guidance; verification commands are read-only (lsof +L1 -nP, readlink /proc/<pid>/fd/<fd>) and never mutate workloads (D-07/T-03-05 analog).
  - Text/mmap segment descriptors (fd=txt) are kept as culprits because deleted mmap'd files still hold space.
metrics:
  duration: 7min
  completed: 2026-06-14
  tasks: 2
  files: 7
  tests_added: 13
  tests_total: 131
---

# Phase 3 Plan 2: deleted-open-files Diagnostic Summary

`watchdirs deleted-open-files --json` finds deleted-but-open files still consuming
disk through live process file descriptors, preferring fixed-argv `lsof -nP +L1 -F0`
and falling back to a bounded procfs scan, emitting typed culprit rows (PID, command,
fd, size, path, optional storage-domain, cautious action hint) in a stable envelope
with verification-only next checks — kept entirely separate from persisted directory
aggregates per D-10.

## What Was Built

- **`parse_lsof_field_output()`** (diagnostics/deleted_open.py): parses NUL-delimited
  `lsof -F0` output into `DeletedOpenFile` rows. Process-set fields (`p`/`c`) apply to
  the following file-set records until the next process line; file records begin at the
  `f` (fd) field and flush on the next `f`/`p`. Malformed records (file before process
  context, missing name) and missing sizes surface as warnings, never crashes.
- **`scan_procfs_deleted_open()`**: bounded fallback that reads only below the injected
  `proc_root`, iterates numeric pid dirs, `os.readlink`s each `fd/*` (never following the
  target for traversal), detects deleted targets by the ` (deleted)` suffix, and records
  permission gaps as `deleted_open_permission_denied` counters. Size is `None` here with
  an evidence warning.
- **`collect_deleted_open_files()`**: orchestrates lsof (via injectable `lsof_runner`)
  with a procfs fallback (via injectable `proc_root`); handles command-not-found, OSError,
  stderr warnings, and empty/nonzero output; sorts culprits by size descending, caps by
  `--limit`, and reports truncation + totals. Optional `domain_resolver` enriches each row
  with a storage-domain, degrading to `null` plus a warning when unresolved.
- **Renderers** `render_deleted_open_payload` / `render_deleted_open_text` reusing the
  existing escaping (`_text_field`, `_text_path`, `_text_group`) and JSON-envelope
  conventions and warning de-duplication.
- **CLI** `deleted-open-files` (`--db`, `--limit`, `--json`); thin handler with live host
  seams at runtime and an optional `--db` storage-domain resolver built from persisted
  `snapshot_mounts` via longest mount-prefix matching (degrades cleanly on snapshot-less DB).
- New frozen/slotted dataclasses: `DeletedOpenFile`, `DeletedOpenTotals`,
  `DeletedOpenDiagnostic`.

## Verification

- `python3 -m pytest -q tests/test_diagnostics_deleted_open.py` — 13 passed (RED→GREEN).
- `python3 -m pytest -q tests/test_diagnostics_df_index.py` — 10 passed (df-vs-index unaffected).
- `python3 -m pytest -q` — 131 passed (118 prior + 13 new).
- Live smoke: `watchdirs deleted-open-files --json` on the host used the lsof path, found
  real deleted-open culprits with correct sizes and fds, surfaced an `lsof_stderr` warning
  for unstattable pseudo/overlay filesystems, and emitted only read-only verification commands.

## Threat Model Coverage

All `mitigate` dispositions are satisfied: no privilege escalation, permission gaps as
warnings/counters (T-03-06); fixed argv + `shell=False`, no command interpolation
(T-03-07); escaped text output with explicit JSON fields (T-03-08); strict `--limit` and
truncation metadata (T-03-09); warnings for stderr, missing fields, permission-denied,
and fallback use (T-03-10); host seams (`lsof_runner`, `proc_root`) default to live host
in the CLI and are injection points only for tests (T-03-11); no package installs (T-03-SC).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] lsof -F0 per-line newline framing was misparsed**
- **Found during:** Task 2 (GREEN) live smoke test, which showed `fd=?`.
- **Issue:** Real `lsof -F0` NUL-terminates each field but *also* newline-terminates each
  logical line, so each line's first field token carries the previous line's trailing `\n`
  (e.g. `\nftxt`). The tag check then failed and fd fields were lost.
- **Fix:** Strip `\n` framing from each NUL-split field token before reading the tag.
- **Files modified:** src/watchdirs/diagnostics/deleted_open.py
- **Test:** Added `test_parse_lsof_handles_real_line_framing_with_trailing_newlines`
  mirroring the host output shape (process line ending `...\0\n` then file line).
- **Commit:** 2df9386

## TDD Gate Compliance

- RED: `test(03-02)` commit `07e3ff7` added 12 failing tests (module/command/renderers absent).
- GREEN: `feat(03-02)` commit `2df9386` made all pass (13 after the regression test); full
  suite stayed green.
- REFACTOR: not required; implementation was clean on first GREEN apart from the parser bug
  fixed inline under Rule 1.

## Self-Check: PASSED

All created files exist on disk and both per-task commits (`07e3ff7`, `2df9386`) are present
in git history.
