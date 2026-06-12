---
phase: 01-trusted-snapshot-collection
verified: 2026-06-12T23:00:44Z
status: gaps_found
score: 5/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed:
    - "Configured roots are no longer normalized through symlink targets during config parsing."
    - "Collect now rejects symlink configured roots with config_error.kind=symlink_root before any database or scan work starts."
  gaps_remaining:
    - "Scanner does not follow symlinks by default."
  regressions: []
gaps:
  - truth: "Scanner does not follow symlinks by default."
    status: failed
    reason: "Configured-root collection is now guarded in config validation, but scan_root() still resolves a symlink root to its target via Path(options.root).resolve(strict=False), so FSEM-01 remains false at the scanner primitive."
    artifacts:
      - path: "src/watchdirs/collect/scanner.py"
        issue: "scan_root() resolves options.root before any follow_symlinks=False boundary check, so a symlink root is followed."
      - path: "tests/test_scanner_semantics.py"
        issue: "Symlink coverage still only proves descendant symlinks are skipped; it has no scanner-level root-symlink regression."
    missing:
      - "Reject symlink roots inside scan_root() or preserve the original root path and stat it with follow_symlinks=False before any resolve step."
      - "Add a scanner-level regression that calls scan_root() with a symlink root and proves the target is not followed."
---

# Phase 01: Trusted Snapshot Collection Verification Report

**Phase Goal:** Agents can create trustworthy directory snapshot evidence for configured roots
**Verified:** 2026-06-12T23:00:44Z
**Status:** gaps_found
**Re-verification:** Yes - after gap closure attempt

> MVP note: ROADMAP marks Phase 01 as `mode: mvp`, but the goal is still an outcome statement rather than a canonical user story. User-flow coverage below is therefore derived from the live success criteria and requirements.

## Goal Achievement

### User Flow Coverage

| # | User flow step | Expected | Evidence | Status |
|---|---|---|---|---|
| 1 | Run `./watchdirs collect` or `PYTHONPATH=src python3 -m watchdirs collect` with an explicit config | Command succeeds without install and emits JSON snapshot evidence | `watchdirs` bootstraps `src/`; `src/watchdirs/__main__.py` dispatches to `src/watchdirs/cli.py`; live repo-local and module probes both exited `0` and persisted snapshot rows when `tmpfs` was explicitly included for the temp root | ✓ VERIFIED |
| 2 | Persist snapshot metadata for each configured root | Snapshot row includes timestamps, status, root path, notes, and fatal error metadata | `src/watchdirs/db/schema.sql`, `src/watchdirs/db/migrations.py`, and `src/watchdirs/cli.py` create/finalize snapshots; live repo-local and module probes wrote snapshot rows matching the JSON payloads | ✓ VERIFIED |
| 3 | Persist recursive directory aggregate evidence for later diffing | Directory rows include hierarchy, counts, apparent bytes, disk bytes, and per-path error storage | `DirectoryAggregate` uses raw-byte path fields, `scan_root()` builds post-order rows, and live probes stored depth `[1, 0]` rows for a nested tree | ✓ VERIFIED |
| 4 | Reject unsafe configured roots before collection mutates state | A configured root that is itself a symlink is rejected with a JSON config error and does not create state | `src/watchdirs/config.py:73-90`, `src/watchdirs/cli.py:44-48`; live repo-local symlink-root probe exited `2`, emitted `config_error.kind=symlink_root`, and created no SQLite file | ✓ VERIFIED |

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Agent can run repo-local `./watchdirs collect` and `PYTHONPATH=src python3 -m watchdirs collect` for configured roots and get timestamped JSON snapshot metadata | ✓ VERIFIED | `watchdirs`, `src/watchdirs/__main__.py:3-9`, `src/watchdirs/cli.py:20-41`, `tests/test_cli_collect.py:105-116`; live repo-local and module probes both exited `0` and persisted one complete snapshot with `row_count=2` |
| 2 | Collection persists snapshot lifecycle fields with SQLite initialization, WAL/foreign keys/busy-timeout, and interrupt-safe finalization | ✓ VERIFIED | `src/watchdirs/db/connection.py`, `src/watchdirs/db/migrations.py:15-89`, `src/watchdirs/cli.py:50-165`; `pytest tests/test_db_schema.py::test_schema_user_version_and_indexes -q` passed and full suite stayed green |
| 3 | Snapshot data exposes recursive directory aggregates with path relationships, counts, apparent bytes, disk bytes, and per-path errors | ✓ VERIFIED | `src/watchdirs/models.py`, `src/watchdirs/collect/scanner.py`, `src/watchdirs/db/schema.sql`; live repo-local and module probes stored depth `[1, 0]` directory rows and matching snapshot metadata |
| 4 | Snapshot totals follow `du`-compatible physical-byte semantics without hardlink double-counting | ✓ VERIFIED | `tests/test_scanner_semantics.py:133-170`, `:214-239`, `:242-263`; `pytest -q` passed all 50 tests including the `du` oracle and hardlink-dedup coverage |
| 5 | Collection skips virtual, transient, overlay, and namespace mount views by default and prunes cross-device/bind cycles | ✓ VERIFIED | `src/watchdirs/collect/mounts.py`, `src/watchdirs/collect/classify.py`, `src/watchdirs/collect/scanner.py`; `tests/test_mount_policy.py:95-238` and later mount-pruning cases passed in the full suite |
| 6 | Scanner does not follow symlinks by default | ✗ FAILED | The collect entrypoint now rejects symlink configured roots via `src/watchdirs/config.py:82-83` and `tests/test_cli_collect.py:202-212`, but `src/watchdirs/collect/scanner.py:44-47` still calls `Path(options.root).resolve(strict=False)`. Direct probe: `python3 - <<'PY' ... scan_root(ScannerOptions(root=link, record_skipped=True)) ...` returned `root_path=/tmp/.../real`, `status=complete`, `row_count=1`, proving the scanner still follows a symlink root. |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `watchdirs` | Repo-local executable dispatch for `./watchdirs collect` | ✓ VERIFIED | Boots `src/` and invokes module main |
| `src/watchdirs/__main__.py` | `python -m watchdirs` entrypoint | ✓ VERIFIED | Imports and runs CLI main |
| `src/watchdirs/cli.py` | Collect CLI, JSON envelope, DB/scanner orchestration, interrupt handling | ✓ VERIFIED | Loads config before DB/scanner work; emits JSON success and config/runtime errors |
| `src/watchdirs/config.py` | Explicit TOML loading, root validation, XDG defaults | ✓ VERIFIED | `_normalize_absolute_path()` now preserves path identity and `validate_roots()` rejects symlink roots |
| `src/watchdirs/db/schema.sql` | Snapshot and directory aggregate schema | ✓ VERIFIED | Snapshot and aggregate tables plus indexes exist |
| `src/watchdirs/db/migrations.py` | Schema init, snapshot lifecycle, batched inserts | ✓ VERIFIED | Versioned init and batched directory inserts are exercised by tests |
| `src/watchdirs/collect/scanner.py` | Iterative scanner with aggregate semantics and no-follow symlink semantics | ⚠️ HOLLOW | Substantive and wired, but root handling still resolves through symlink targets at `scan_root()` entry |
| `src/watchdirs/collect/mounts.py` | `/proc/self/mountinfo` parser and path lookup | ✓ VERIFIED | Substantive parser and longest-prefix lookup |
| `src/watchdirs/collect/classify.py` | Default filesystem skip policy | ✓ VERIFIED | Covers pseudo/tmpfs/overlay/nsfs defaults and explicit includes |
| `tests/test_db_schema.py` | Schema/version/index regression coverage | ✓ VERIFIED | `test_schema_user_version_and_indexes` passed in re-verification |
| `tests/test_cli_collect.py` | CLI command, persistence, error, and interrupt contracts | ✓ VERIFIED | New symlink-root CLI regression exists at `:202-212`; live repo-local probe confirms the wrapper surface too |
| `tests/test_scanner_semantics.py` | Recursive aggregate and filesystem-semantic scanner contracts | ⚠️ PARTIAL | Descendant symlink coverage exists, but no root-symlink scanner regression is present |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `watchdirs` | `src/watchdirs/__main__.py` | repo-local executable bootstraps `src/` then imports module main | ✓ WIRED | Wrapper surface worked in both success and symlink-root probes |
| `src/watchdirs/__main__.py` | `src/watchdirs/cli.py` | module entrypoint imports and runs CLI main | ✓ WIRED | Module probe persisted a complete snapshot |
| `src/watchdirs/cli.py` | `src/watchdirs/config.py` | `run_collect()` loads config and returns config JSON errors before DB/scanner work | ✓ WIRED | Symlink-root CLI probe exited `2` with `config_error.kind=symlink_root` |
| `src/watchdirs/cli.py` | `src/watchdirs/db/connection.py` + `src/watchdirs/db/migrations.py` | collect opens DB, initializes schema, creates/finalizes snapshots, inserts rows | ✓ WIRED | Success probes wrote snapshot and directory rows; symlink-root probe created no DB |
| `src/watchdirs/cli.py` | `src/watchdirs/collect/scanner.py` | validated configured roots flow into `ScannerOptions` and `scan_root()` | ✓ WIRED | Success probes produced complete snapshot payloads with `row_count=2` |
| `src/watchdirs/db/migrations.py` | `src/watchdirs/db/schema.sql` | packaged SQL drives schema initialization | ✓ WIRED | Schema version/index test passed |
| `src/watchdirs/collect/scanner.py` | `src/watchdirs/collect/classify.py` + `src/watchdirs/collect/mounts.py` | scanner consults mount classification before descent | ✓ WIRED | Mount-policy suite passed in full |

### Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| `src/watchdirs/cli.py` | `config.roots` | `load_config()` -> `_parse_roots()` -> `validate_roots()` | Yes - valid roots flowed into both live collection probes; symlink roots were blocked before scan | ✓ FLOWING |
| `src/watchdirs/cli.py` | `snapshot_payloads` | `create_snapshot()` + `scan_root()` + `insert_directory_rows()` + `finalize_snapshot()` | Yes - repo-local and module probes created persisted snapshot rows matching JSON output | ✓ FLOWING |
| `src/watchdirs/db/migrations.py` | `directory_sizes` inserts | `DirectoryAggregate` rows from `scan_root()` | Yes - both live probes persisted two nested directory rows | ✓ FLOWING |
| `src/watchdirs/collect/scanner.py` | `root_path` | `Path(options.root).resolve(strict=False)` | No - direct scanner probe rewrote a symlink root to its target path and completed successfully | ⚠️ HOLLOW |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full Phase 01 suite | `pytest -q` | `50 passed in 2.55s` | ✓ PASS |
| Schema/version/index drift sentinel | `pytest tests/test_db_schema.py::test_schema_user_version_and_indexes -q` | `1 passed in 0.02s` | ✓ PASS |
| Repo-local collect command writes snapshot evidence | `./watchdirs collect --config <tmp-with-included-tmpfs> --db <tmp> --json --notes repo-probe` | exit `0`; snapshot status `complete`; `row_count=2`; SQLite stored one snapshot and two directory rows | ✓ PASS |
| Module entrypoint writes snapshot evidence | `PYTHONPATH=src python3 -m watchdirs collect --config <tmp-with-included-tmpfs> --db <tmp> --json --notes module-probe` | exit `0`; snapshot status `complete`; `row_count=2`; SQLite stored one snapshot and two directory rows | ✓ PASS |
| Collect rejects symlink configured roots before mutating state | `./watchdirs collect --config <symlink-root-config> --db <tmp> --json` | exit `2`; JSON `config_error.kind=symlink_root`; database file not created | ✓ PASS |
| Scanner root no-follow semantics | `python3 - <<'PY' ... scan_root(ScannerOptions(root=link, record_skipped=True)) ...` | returned `root_path=/tmp/.../real`, `status=complete`, `row_count=1` for a symlink root | ✗ FAIL |

### Probe Execution

| Probe | Command | Result | Status |
|---|---|---|---|
| Phase probe scripts | `find scripts -path '*/tests/probe-*.sh' -type f` | No declared or conventional probe scripts found for Phase 01 | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| `COLL-01` | `01-01`, `01-02` | Run `watchdirs collect` to create a timestamped snapshot for configured roots | ✓ SATISFIED | Repo-local and module probes both succeeded and persisted snapshots |
| `COLL-02` | `01-02` | Record snapshot status, timing, root path, notes, and fatal error | ✓ SATISFIED | Schema/lifecycle code plus passing schema/index and CLI lifecycle tests |
| `COLL-03` | `01-03` | Record recursive directory aggregate rows with path, parent path, name, depth, counts, bytes, and per-path error | ✓ SATISFIED | Live probes stored nested rows; scanner/schema tests remain green |
| `COLL-04` | `01-03` | Store disk bytes using physical allocation semantics compatible with `du` | ✓ SATISFIED | Full suite passed the `du` oracle and hardlink-dedup cases |
| `COLL-05` | `01-03` | Store apparent bytes using logical size semantics compatible with `st_size` | ✓ SATISFIED | Apparent-byte semantics remain covered in `tests/test_scanner_semantics.py` |
| `FSEM-01` | `01-03` | Scanner does not follow symlinks by default | ✗ BLOCKED | CLI/config guard is fixed, but direct `scan_root()` use still follows a symlink root at `src/watchdirs/collect/scanner.py:44-47` |
| `FSEM-02` | `01-03` | Scanner avoids double-counting physical bytes for hardlinked files within one snapshot | ✓ SATISFIED | Hardlink-dedup tests remained green in the full suite |
| `FSEM-03` | `01-04` | Scanner reads mount information and skips virtual/transient filesystems by default | ✓ SATISFIED | Mount parser/classifier tests passed; temp-root probes required explicit `tmpfs` opt-in, matching policy |
| `FSEM-04` | `01-04` | Scanner avoids descending into container overlay mount views and namespace mounts by default | ✓ SATISFIED | Mount-policy suite covers overlay/nsfs skips and passed |
| `FSEM-05` | `01-03` | Scanner records partial path-level errors instead of silently dropping inaccessible subtrees | ✓ SATISFIED | Existing scanner error-path coverage remained green in the full suite |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| reviewed phase files | — | No `TODO`/`FIXME`/`XXX`, placeholder returns, or console-log stubs found | ℹ️ Info | Remaining failure is a real semantic gap, not a placeholder implementation |

### Gaps Summary

The re-verification closed the original collect-path symptom but not the full requirement. The good news is real: config parsing no longer resolves configured roots through symlinks, `collect` now rejects a symlink root with `config_error.kind=symlink_root`, and the repo-local and module success paths still work end-to-end with persisted SQLite evidence.

Phase 01 still cannot pass because `FSEM-01` is stated at scanner level and `scan_root()` itself still follows a symlink root. The new regression test proves the CLI/config guard, not the scanner primitive. That means the phase goal is mostly achieved for configured-root collection, but the must-have scanner contract is still false in the codebase today.

No later roadmap phase explicitly defers this semantics fix, so it remains an actionable blocker for Phase 01 rather than a deferred item.

### Residual Risks

- The CLI surface is now safe for configured roots, but any future caller that invokes `scan_root()` directly can still violate `FSEM-01`.
- Because there is still no scanner-level root-symlink regression, the suite can stay green while this contract remains broken.

---

_Verified: 2026-06-12T23:00:44Z_
_Verifier: the agent (gsd-verifier)_
