---
phase: 01-trusted-snapshot-collection
verified: 2026-06-12T23:08:28Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed:
    - "Scanner does not follow symlinks by default."
  gaps_remaining: []
  regressions: []
---

# Phase 01: Trusted Snapshot Collection Verification Report

**Phase Goal:** Agents can create trustworthy directory snapshot evidence for configured roots
**Verified:** 2026-06-12T23:08:28Z
**Status:** passed
**Re-verification:** Yes - after scanner symlink-root fix `eb92359`

> MVP note: ROADMAP still marks Phase 01 as `mode: mvp`, but the phase-level roadmap goal is not written as a canonical user story. User-flow coverage below is therefore anchored to the established Phase 01 must-have contract from the prior verification plus the live roadmap success criteria.

## Goal Achievement

### User Flow Coverage

| # | User flow step | Expected | Evidence | Status |
| --- | --- | --- | --- | --- |
| 1 | Run `./watchdirs collect` or `PYTHONPATH=src python3 -m watchdirs collect` with an explicit config | Command succeeds without install and emits JSON snapshot evidence | Repo-local and module probes both exited `0`, returned snapshot status `complete`, `row_count=2`, and persisted one snapshot plus two directory rows | ✓ VERIFIED |
| 2 | Persist snapshot metadata for each configured root | Snapshot row includes timestamps, status, root path, notes, and fatal error metadata | `src/watchdirs/db/schema.sql`, `src/watchdirs/db/migrations.py`, and `src/watchdirs/cli.py` still create/finalize snapshot rows; schema/index drift sentinel stayed green | ✓ VERIFIED |
| 3 | Persist recursive directory aggregate evidence for later diffing | Directory rows include hierarchy, counts, apparent bytes, disk bytes, and per-path error storage | `scan_root()` still emits post-order `DirectoryAggregate` rows and the live probes stored nested rows with depths `[1, 0]` | ✓ VERIFIED |
| 4 | Reject unsafe configured roots before collection mutates state | A configured root that is itself a symlink is rejected with a JSON config error and direct scanner use does not follow the target | `src/watchdirs/config.py` rejects configured symlink roots, and `src/watchdirs/collect/scanner.py:44-80` now `lstat`s the root with `follow_symlinks=False` and returns `failed symlink_root` with no rows | ✓ VERIFIED |

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Agent can run repo-local `./watchdirs collect` and `PYTHONPATH=src python3 -m watchdirs collect` for configured roots and get timestamped JSON snapshot metadata | ✓ VERIFIED | Repo-local and module probes both exited `0`; each returned `status=complete`, `row_count=2`, and persisted one snapshot plus two directory rows |
| 2 | Collection persists snapshot lifecycle fields with SQLite initialization, WAL/foreign keys/busy-timeout, and interrupt-safe finalization | ✓ VERIFIED | `src/watchdirs/db/connection.py`, `src/watchdirs/db/migrations.py`, and `src/watchdirs/cli.py` remain wired; `pytest tests/test_db_schema.py::test_schema_user_version_and_indexes -q` passed |
| 3 | Snapshot data exposes recursive directory aggregates with path relationships, counts, apparent bytes, disk bytes, and per-path errors | ✓ VERIFIED | `src/watchdirs/models.py`, `src/watchdirs/collect/scanner.py`, and `src/watchdirs/db/schema.sql` still match; live collection probes persisted nested rows and the full suite stayed green |
| 4 | Snapshot totals follow `du`-compatible physical-byte semantics without hardlink double-counting | ✓ VERIFIED | `pytest -q` passed all `51` tests, including the `du` oracle, hardlink dedup, and scanner semantics coverage in `tests/test_scanner_semantics.py` |
| 5 | Collection skips virtual, transient, overlay, and namespace mount views by default and prunes cross-device/bind cycles | ✓ VERIFIED | `src/watchdirs/collect/mounts.py`, `src/watchdirs/collect/classify.py`, and `src/watchdirs/collect/scanner.py` remain wired; `tests/test_mount_policy.py` remains covered in the full suite |
| 6 | Scanner does not follow symlinks by default | ✓ VERIFIED | `src/watchdirs/collect/scanner.py:44-80` preserves the lexical absolute root path, calls `os.stat(..., follow_symlinks=False)`, rejects `stat.S_ISLNK(root_stat.st_mode)`, and returns `failed` with no rows; `pytest tests/test_scanner_semantics.py::test_symlink_root_is_rejected_without_following_target -q` passed; direct scanner probe returned `{\"status\":\"failed\",\"row_count\":0,\"error_kinds\":[\"symlink_root\"]}` |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `watchdirs` | Repo-local executable dispatch for `./watchdirs collect` | ✓ VERIFIED | Repo-local probe succeeded and produced persisted snapshot evidence |
| `src/watchdirs/__main__.py` | `python -m watchdirs` entrypoint | ✓ VERIFIED | Module probe succeeded and produced persisted snapshot evidence |
| `src/watchdirs/cli.py` | Collect CLI, JSON envelope, DB/scanner orchestration, interrupt handling | ✓ VERIFIED | Still loads config before DB/scanner work and emits JSON success/config/runtime errors |
| `src/watchdirs/config.py` | Explicit TOML loading, root validation, XDG defaults | ✓ VERIFIED | Continues to preserve configured-root identity and reject symlink roots before collection |
| `src/watchdirs/db/schema.sql` | Snapshot and directory aggregate schema | ✓ VERIFIED | Schema file still provides snapshot and aggregate tables plus indexes |
| `src/watchdirs/db/migrations.py` | Schema init, snapshot lifecycle, batched inserts | ✓ VERIFIED | Schema/version/index sentinel passed and live probes inserted snapshot plus directory rows |
| `src/watchdirs/collect/scanner.py` | Iterative scanner with aggregate semantics and no-follow symlink semantics | ✓ VERIFIED | `scan_root()` no longer resolves the root through its symlink target and fails cleanly on symlink roots |
| `src/watchdirs/collect/mounts.py` | `/proc/self/mountinfo` parser and path lookup | ✓ VERIFIED | Artifact and key-link verification both passed |
| `src/watchdirs/collect/classify.py` | Default filesystem skip policy | ✓ VERIFIED | Artifact and key-link verification both passed |
| `tests/test_db_schema.py` | Schema/version/index regression coverage | ✓ VERIFIED | `test_schema_user_version_and_indexes` passed in re-verification |
| `tests/test_cli_collect.py` | CLI command, persistence, error, and interrupt contracts | ✓ VERIFIED | CLI symlink-root regression remains present and full suite passed |
| `tests/test_scanner_semantics.py` | Recursive aggregate and filesystem-semantic scanner contracts | ✓ VERIFIED | Root-symlink regression now exists at `tests/test_scanner_semantics.py:217-230` and passed |
| `tests/test_mount_policy.py` | Mount parsing and skip-policy coverage | ✓ VERIFIED | Full suite passed, preserving FSEM-03 and FSEM-04 coverage |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `watchdirs` | `src/watchdirs/__main__.py` | repo-local executable bootstraps `src/` then imports module main | ✓ WIRED | Repo-local probe exited `0` and persisted snapshot evidence |
| `src/watchdirs/__main__.py` | `src/watchdirs/cli.py` | module entrypoint imports and runs CLI main | ✓ WIRED | Module probe exited `0` and persisted snapshot evidence |
| `src/watchdirs/cli.py` | `src/watchdirs/config.py` | `run_collect()` loads config and returns config JSON errors before DB/scanner work | ✓ WIRED | CLI regression still rejects symlink configured roots with `config_error.kind=symlink_root` |
| `src/watchdirs/cli.py` | `src/watchdirs/db/connection.py` + `src/watchdirs/db/migrations.py` | collect opens DB, initializes schema, creates/finalizes snapshots, inserts rows | ✓ WIRED | Repo-local and module probes both wrote one snapshot and two directory rows |
| `src/watchdirs/cli.py` | `src/watchdirs/collect/scanner.py` | validated configured roots flow into `ScannerOptions` and `scan_root()` | ✓ WIRED | Runtime probes produced complete snapshots; direct scanner probe produced `failed symlink_root` without rows |
| `src/watchdirs/db/migrations.py` | `src/watchdirs/models.py` | persistence inserts `DirectoryAggregate` fields by name | ✓ WIRED | `gsd-tools` key-link verification passed for Plan 01-03 |
| `src/watchdirs/collect/scanner.py` | `src/watchdirs/collect/classify.py` + `src/watchdirs/collect/mounts.py` | scanner consults mount classification before descent | ✓ WIRED | `gsd-tools` key-link verification passed for Plan 01-04 |

### Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
| --- | --- | --- | --- | --- |
| `src/watchdirs/cli.py` | `config.roots` | `load_config()` -> `_parse_roots()` -> `validate_roots()` | Yes - valid roots flowed into live collection probes and symlink roots are rejected before mutation | ✓ FLOWING |
| `src/watchdirs/cli.py` | `snapshot_payloads` | `create_snapshot()` + `scan_root()` + `insert_directory_rows()` + `finalize_snapshot()` | Yes - repo-local and module probes created persisted snapshot rows matching the JSON payloads | ✓ FLOWING |
| `src/watchdirs/db/migrations.py` | `directory_sizes` inserts | `DirectoryAggregate` rows from `scan_root()` | Yes - both live probes persisted two nested directory rows | ✓ FLOWING |
| `src/watchdirs/collect/scanner.py` | `root_path`, `root_stat`, and `errors` | `Path(options.root).expanduser()/absolute` + `os.stat(..., follow_symlinks=False)` + `stat.S_ISLNK` guard | Yes - direct scanner probe returned `failed`, preserved the symlink root path, emitted `symlink_root`, and returned zero rows | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full Phase 01 suite | `pytest -q` | `51 passed in 2.65s` | ✓ PASS |
| Scanner root-symlink regression | `pytest tests/test_scanner_semantics.py::test_symlink_root_is_rejected_without_following_target -q` | `1 passed in 0.06s` | ✓ PASS |
| Schema/version/index drift sentinel | `pytest tests/test_db_schema.py::test_schema_user_version_and_indexes -q` | `1 passed in 0.02s` | ✓ PASS |
| Repo-local collect command writes snapshot evidence | `./watchdirs collect --config <tmp> --db <tmp> --json --notes repo-probe` | exit `0`; snapshot `complete`; JSON `row_count=2`; SQLite stored `1` snapshot and `2` directory rows | ✓ PASS |
| Module entrypoint writes snapshot evidence | `PYTHONPATH=<repo>/src python3 -m watchdirs collect --config <tmp> --db <tmp> --json --notes module-probe` | exit `0`; snapshot `complete`; JSON `row_count=2`; SQLite stored `1` snapshot and `2` directory rows | ✓ PASS |
| Direct scanner no-follow semantics | `PYTHONPATH=src python3 - <<'PY' ... scan_root(ScannerOptions(root=link, record_skipped=True)) ... PY` | returned `status=failed`, `row_count=0`, `error_kinds=[\"symlink_root\"]`, `error_paths=[\"/tmp/.../link-root\"]` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Phase probe scripts | `find scripts -path '*/tests/probe-*.sh' -type f` | No declared or conventional probe scripts found for Phase 01 | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `COLL-01` | `01-01`, `01-02` | Run `watchdirs collect` to create a timestamped snapshot for configured roots | ✓ SATISFIED | Repo-local and module probes both succeeded and persisted snapshots |
| `COLL-02` | `01-02` | Record snapshot status, timing, root path, notes, and fatal error | ✓ SATISFIED | Schema/lifecycle code remains wired and the schema/index sentinel passed |
| `COLL-03` | `01-03` | Record recursive directory aggregate rows with path, parent path, name, depth, counts, bytes, and per-path error | ✓ SATISFIED | Live probes stored nested rows and the scanner/schema contracts remain green |
| `COLL-04` | `01-03` | Store disk bytes using physical allocation semantics compatible with `st_blocks * 512` or `du` | ✓ SATISFIED | Full suite passed the `du` oracle and hardlink-dedup cases |
| `COLL-05` | `01-03` | Store apparent bytes using logical size semantics compatible with `st_size` | ✓ SATISFIED | Apparent-byte semantics remain covered in `tests/test_scanner_semantics.py` and the full suite passed |
| `FSEM-01` | `01-03` | Scanner does not follow symlinks by default | ✓ SATISFIED | `scan_root()` now rejects a symlink root before traversal and the dedicated regression plus direct probe both passed |
| `FSEM-02` | `01-03` | Scanner avoids double-counting physical bytes for hardlinked files within one snapshot | ✓ SATISFIED | Hardlink-dedup tests remained green in the full suite |
| `FSEM-03` | `01-04` | Scanner reads mount information and skips virtual/transient filesystems by default | ✓ SATISFIED | Mount parser/classifier artifacts and links verified; full suite stayed green |
| `FSEM-04` | `01-04` | Scanner avoids descending into container overlay mount views and namespace mounts by default | ✓ SATISFIED | Mount-policy coverage remains present and full suite passed |
| `FSEM-05` | `01-03` | Scanner records partial path-level errors instead of silently dropping inaccessible subtrees | ✓ SATISFIED | Existing scanner error-path coverage remains green in the full suite |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| reviewed phase files | — | No `TODO`/`FIXME`/`XXX`, placeholder returns, or console-log stubs found in production phase files | ℹ️ Info | No blocker-level anti-patterns detected |

---

_Verified: 2026-06-12T23:08:28Z_
_Verifier: the agent (gsd-verifier)_
