---
phase: 01-trusted-snapshot-collection
plan: 04
subsystem: filesystem
tags: [python, pytest, mountinfo, tmpfs, overlay, nsfs]
requires:
  - phase: 01-03
    provides: byte-safe scanner traversal, hardlink semantics, and persisted directory aggregate contracts
provides:
  - direct `/proc/self/mountinfo` parsing and longest-prefix mount lookup
  - default skip policy for pseudo, tmpfs, overlay, and namespace mounts with explicit include overrides
  - scanner-side one-filesystem `st_dev` pruning and bind-mount cycle protection with skip evidence
affects: [phase-02-reporting, collect, filesystem-policy]
tech-stack:
  added: [python-stdlib]
  patterns: [mount-parser-boundary, mount-classification-boundary, one-filesystem-pruning]
key-files:
  created:
    - src/watchdirs/collect/mounts.py
    - src/watchdirs/collect/classify.py
    - tests/test_mount_policy.py
  modified:
    - src/watchdirs/config.py
    - src/watchdirs/models.py
    - src/watchdirs/cli.py
    - src/watchdirs/collect/scanner.py
    - tests/conftest.py
    - tests/test_cli_collect.py
key-decisions:
  - "Production collection now parses `/proc/self/mountinfo` directly and never shells out to `findmnt`."
  - "Tmpfs, pseudo filesystems, overlay views, and namespace mounts are skipped by default unless config explicitly includes their filesystem types."
  - "Skipped child mounts and one-filesystem boundaries emit zero-byte directory rows with error context instead of silently disappearing."
patterns-established:
  - "Mount policy boundary: `collect/mounts.py` parses mountinfo, `collect/classify.py` explains inclusion, and `scanner.py` only applies pre-descent decisions."
  - "One-filesystem guard: capture the root `st_dev` once and prune child directories whose `st_dev` changes unless they are scanned as explicit additional roots."
requirements-completed: [FSEM-03, FSEM-04]
duration: 7min
completed: 2026-06-12
status: complete
---

# Phase 1 Plan 04: Mountinfo parsing, skip policy, scanner pruning, and phase verification Summary

**Collection now reads live mountinfo, skips pseudo/tmpfs/overlay/namespace mount views by default, and prunes cross-device subtrees with recorded evidence before traversal enters them.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-12T22:06:03Z
- **Completed:** 2026-06-12T22:12:40Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- Added RED coverage for mountinfo parsing, octal path unescaping, pseudo/tmpfs/overlay/nsfs classification, one-filesystem pruning, explicit additional-root scans, bind-mount cycle handling, and CLI `--mountinfo` overrides.
- Implemented `MountInfo`, `MountDecision`, and `MountPolicy` plus direct `/proc/self/mountinfo` loading, classifier defaults, config-driven include overrides, and scanner-side mount/device/cycle pruning.
- Verified the full Phase 1 suite, the controlled `du -x` oracle, and a live mount classification sanity check without scanning broad host roots.

## Verification

- `pytest tests/test_mount_policy.py -q` -> `8 passed`
- `pytest tests/test_scanner_semantics.py -q` -> `10 passed`
- `pytest tests/test_cli_collect.py -q` -> `18 passed`
- `pytest -q` -> `41 passed`
- `pytest tests/test_scanner_semantics.py::test_disk_bytes_match_du_for_fixture -q` -> `1 passed`
- `PYTHONPATH=src python3 -c ...load_mountinfo('/proc/self/mountinfo')...` -> `mount_count=65`, `skipped_count=57`, skipped types included `tmpfs`, `overlay`, and `nsfs`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create failing mount policy tests** - `c955670` (`test`)
2. **Task 2: Implement mountinfo parsing, classification, and scanner pruning** - `1b53c1a` (`feat`)

## Files Created/Modified

- `src/watchdirs/collect/mounts.py` - Parses mountinfo rows, unescapes mount paths, and resolves the longest matching mountpoint for scanner lookups.
- `src/watchdirs/collect/classify.py` - Centralizes default filesystem skip/include rules for pseudo, tmpfs, overlay, and namespace mounts.
- `src/watchdirs/models.py` - Adds typed mount dataclasses and extends scanner options with mount table and policy input.
- `src/watchdirs/config.py` - Parses optional `mount_policy` config so operators can explicitly include filesystems such as `tmpfs`.
- `src/watchdirs/cli.py` - Loads live mountinfo or a test override before each root scan and passes the resulting policy context into the scanner.
- `src/watchdirs/collect/scanner.py` - Applies mount classification, one-filesystem `st_dev` pruning, bind-mount cycle guards, and skip-row recording before descent.
- `tests/test_mount_policy.py` - Covers FSEM-03 and FSEM-04 with synthetic mountinfo and targeted pruning checks.
- `tests/conftest.py` and `tests/test_cli_collect.py` - Let older temp-root success fixtures opt into `tmpfs` explicitly while keeping the new default-skip override test red/green.

## Decisions Made

- Root scans fail closed when the configured root resolves to a skipped mount type under the active policy, which keeps tmpfs and namespace views out of trusted history unless the operator opted in.
- Explicit filesystem includes are global config policy for now; separate mount coverage still comes from configuring additional roots, not from bypassing one-filesystem pruning beneath `/`.
- Skip evidence is preserved as path-level rows plus scan errors instead of downgrading the whole snapshot to partial when the skip was intentional policy rather than traversal failure.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Harness] Updated legacy CLI success fixtures to opt into tmpfs explicitly**
- **Found during:** Task 2
- **Issue:** The new live mount-policy default correctly rejects `tmpfs` roots, which caused older happy-path collect tests using `tmp_path` under `/tmp` to fail even though the production behavior was correct.
- **Fix:** Extended the shared test config writer to emit `[mount_policy] included_filesystems = ["tmpfs"]` for the existing success-path CLI tests, while keeping the new `--mountinfo` override regression test on the default skip path.
- **Files modified:** `tests/conftest.py`, `tests/test_cli_collect.py`
- **Verification:** `pytest tests/test_cli_collect.py -q`, `pytest -q`
- **Committed in:** `1b53c1a`

---

**Total deviations:** 1 auto-fixed (`Rule 1: 1`)
**Impact on plan:** Kept the older CLI fixtures aligned with the intended host safety contract. No production scope creep.

## Issues Encountered

- The live test environment mounts `/tmp` as `tmpfs`, so pre-01-04 success fixtures needed explicit include policy once runtime collection began honoring live mount classification by default.

## Authentication Gates

None.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 1 is complete: collection now has CLI/config, SQLite persistence, byte-safe scanner semantics, and mount safety hardening for trustworthy snapshots.
- Phase 2 can build diff/reporting flows on top of stable directory rows, explicit skip evidence, and `du -x`-style root boundaries.
- No Phase 2, Phase 3, or Phase 4 features were implemented in this plan; reporting, diagnostics, scheduling, locking, and retention remain deferred.

## Self-Check: PASSED

- Verified `.planning/phases/01-trusted-snapshot-collection/01-04-SUMMARY.md` exists on disk.
- Verified commit `c955670` exists in git history.
- Verified commit `1b53c1a` exists in git history.
