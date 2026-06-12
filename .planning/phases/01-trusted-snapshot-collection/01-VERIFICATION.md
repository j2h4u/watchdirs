---
phase: 01-trusted-snapshot-collection
verified: 2026-06-12T22:52:04Z
status: gaps_found
score: 5/6 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Collection does not follow symlinks by default for configured roots or descendants."
    status: failed
    reason: "Configured roots are normalized with Path.resolve(strict=False) before validation and again before scanning, so a symlink root is followed and recorded as its target path."
    artifacts:
      - path: "src/watchdirs/config.py"
        issue: "_normalize_absolute_path() resolves configured root paths through symlinks."
      - path: "src/watchdirs/collect/scanner.py"
        issue: "scan_root() resolves the root path before os.stat(..., follow_symlinks=False), so the root symlink boundary is already lost."
      - path: "tests/test_scanner_semantics.py"
        issue: "Symlink coverage only tests child symlink targets, not configured-root symlinks."
    missing:
      - "Reject symlink configured roots or preserve the configured path and enforce no-follow semantics at the root boundary."
      - "Add regression coverage for symlink-root collection on both CLI command surfaces."
---

# Phase 01: Trusted Snapshot Collection Verification Report

**Phase Goal:** Agents can create trustworthy directory snapshot evidence for configured roots
**Verified:** 2026-06-12T22:52:04Z
**Status:** gaps_found
**Re-verification:** No - initial verification

> MVP note: ROADMAP marks Phase 01 as `mode: mvp`, but the phase goal is an outcome statement rather than a canonical user story. User-flow coverage below is derived from the Phase 01 success criteria and requirements.

## Goal Achievement

### User Flow Coverage

| # | User flow step | Expected | Evidence | Status |
|---|---|---|---|---|
| 1 | Run `./watchdirs collect` or `python3 -m watchdirs collect` with explicit config | Command succeeds without install and emits JSON snapshot evidence | `watchdirs` bootstraps `src/` and dispatches to module main; CLI parser exposes `collect` with `--config`, `--db`, `--json`, `--notes`, `--mountinfo`; `pytest -q` passed `test_repo_local_collect_help_matches_module_help`, `test_repo_local_collect_creates_snapshot`, `test_module_collect_creates_snapshot` | ✓ VERIFIED |
| 2 | Persist snapshot metadata for each configured root | Snapshot row includes timestamps, status, root path, notes, and fatal error metadata | `src/watchdirs/db/schema.sql`, `src/watchdirs/db/migrations.py`, and `src/watchdirs/cli.py` create/finalize snapshots; repo-local and module probes both wrote SQLite rows with JSON payloads matching persisted snapshot metadata | ✓ VERIFIED |
| 3 | Persist recursive directory aggregate evidence for later diffing | Directory rows include hierarchy, counts, apparent bytes, disk bytes, and per-path error storage | `DirectoryAggregate` uses raw-byte path fields, scanner builds post-order rows, migrations insert BLOB path columns, and the module probe persisted depth `[1, 0]` rows for a nested tree | ✓ VERIFIED |
| 4 | Respect trusted filesystem semantics while scanning | No descendant symlink traversal, no hardlink disk-byte double count, mount skips enforced by default | `tests/test_scanner_semantics.py` and `tests/test_mount_policy.py` passed, plus live CLI probes showed real snapshot insertion | ✓ VERIFIED |
| 5 | Treat configured roots with the same no-follow default | Symlink root should be rejected or scanned without following the symlink target | Symlink-root probe succeeded but recorded `/tmp/.../real-root` instead of the configured `/tmp/.../link-root`, proving root symlinks are followed by default | ✗ FAILED |

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Agent can run repo-local `./watchdirs collect` and `PYTHONPATH=src python3 -m watchdirs collect` for configured roots and get timestamped JSON snapshot metadata | ✓ VERIFIED | `watchdirs:1`, `src/watchdirs/__main__.py:3`, `src/watchdirs/cli.py:20`, `tests/test_cli_collect.py:129`, `:263`, `:295`; spot-checks below both exited `0` and persisted snapshot rows |
| 2 | Collection persists snapshot lifecycle fields with SQLite initialization, WAL/foreign keys/busy-timeout, and interrupt-safe finalization | ✓ VERIFIED | `src/watchdirs/db/connection.py:7`, `src/watchdirs/db/migrations.py:15`, `:30`, `:56`, `:81`, `src/watchdirs/cli.py:52`, `:70`, `:117`, `tests/test_db_schema.py:15`, `:36`, `:58`, `tests/test_cli_collect.py:583`, `:653`, `:745` |
| 3 | Snapshot data exposes recursive directory aggregates with path relationships, counts, apparent bytes, disk bytes, and per-path errors | ✓ VERIFIED | `src/watchdirs/models.py:25`, `:70`, `src/watchdirs/collect/scanner.py:94`, `:135`, `:355`, `src/watchdirs/db/schema.sql:11`, `tests/test_scanner_semantics.py:52`, `:77`, `:286`, `:312`; module probe stored nested rows with depths `[1, 0]` |
| 4 | Snapshot totals follow `du`-compatible physical-byte semantics without hardlink double-counting | ✓ VERIFIED | `src/watchdirs/collect/scanner.py:203`, `:261`, `:385`, `tests/test_scanner_semantics.py:145`, `:217`, `:234`, `:262`; full suite green and `du` oracle test included |
| 5 | Collection skips virtual, transient, overlay, and namespace mount views by default and prunes cross-device/bind cycles | ✓ VERIFIED | `src/watchdirs/collect/mounts.py:12`, `:44`, `:48`, `src/watchdirs/collect/classify.py:6`, `:26`, `src/watchdirs/collect/scanner.py:55`, `:161`, `:291`, `tests/test_mount_policy.py:95`, `:134`, `:173`, `:195`, `:241`, `:295`, `:366` |
| 6 | Collection does not follow symlinks by default | ✗ FAILED | Child symlink targets are covered by `tests/test_scanner_semantics.py:200`, but configured roots are resolved in `src/watchdirs/config.py:218` and `src/watchdirs/collect/scanner.py:45`. Symlink-root probe followed `/tmp/.../link-root` to `/tmp/.../real-root` and reported success. |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `watchdirs` | Repo-local executable dispatch for `./watchdirs collect` | ✓ VERIFIED | Env-based shebang and `src/` bootstrap before module dispatch |
| `src/watchdirs/cli.py` | Collect CLI, JSON envelope, DB/scanner orchestration, interrupt handling | ✓ VERIFIED | Real parser, config loading, SQLite wiring, mountinfo loading, payload emission |
| `src/watchdirs/config.py` | Explicit TOML loading, root validation, XDG defaults | ✓ VERIFIED | Strong config error envelope and XDG state/cache helpers; also contains the symlink-root gap |
| `src/watchdirs/db/schema.sql` | Snapshot and directory aggregate schema | ✓ VERIFIED | Tables and indexes exist; path identity stored as BLOB in `directory_sizes` |
| `src/watchdirs/db/migrations.py` | Schema init, snapshot lifecycle, batched inserts | ✓ VERIFIED | Uses packaged SQL, snapshot create/finalize helpers, batched `executemany` inserts |
| `src/watchdirs/collect/scanner.py` | Iterative scanner with aggregate semantics and mount/symlink handling | ✓ VERIFIED | Substantive 484-line implementation; descendant symlink logic is correct, root-symlink handling is not |
| `src/watchdirs/collect/mounts.py` | `/proc/self/mountinfo` parser and path lookup | ✓ VERIFIED | Parses, unescapes, and matches longest mount prefix |
| `src/watchdirs/collect/classify.py` | Default filesystem skip policy | ✓ VERIFIED | Covers pseudo/tmpfs/overlay/nsfs defaults and explicit includes |
| `tests/test_cli_collect.py` | CLI command, persistence, error, and interrupt contracts | ✓ VERIFIED | 15 focused tests, including rollback and signal paths |
| `tests/test_scanner_semantics.py` | Recursive aggregate and filesystem-semantic contracts | ⚠️ PARTIAL | Strong descendant-symlink coverage, but no configured-root symlink regression |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `watchdirs` | `src/watchdirs/__main__.py` | repo-local executable bootstraps `src/` then imports module main | ✓ WIRED | `watchdirs:8-19` |
| `src/watchdirs/__main__.py` | `src/watchdirs/cli.py` | module entrypoint imports and runs CLI main | ✓ WIRED | `src/watchdirs/__main__.py:3-9` |
| `src/watchdirs/cli.py` | `src/watchdirs/config.py` | collect loads config and resolves DB path | ✓ WIRED | `src/watchdirs/cli.py:45-50` |
| `src/watchdirs/cli.py` | `src/watchdirs/db/connection.py` + `db/migrations.py` | collect opens DB, initializes schema, creates/finalizes snapshots, inserts rows | ✓ WIRED | `src/watchdirs/cli.py:52-63`, `:87-139` |
| `src/watchdirs/cli.py` | `src/watchdirs/collect/mounts.py` + `collect/scanner.py` | collect loads mountinfo and scans each configured root | ✓ WIRED | `src/watchdirs/cli.py:102-116` |
| `src/watchdirs/db/migrations.py` | `src/watchdirs/db/schema.sql` | packaged SQL drives schema initialization | ✓ WIRED | `src/watchdirs/db/migrations.py:24-27` |
| `src/watchdirs/collect/scanner.py` | `src/watchdirs/collect/classify.py` + `collect/mounts.py` | scanner classifies mounts before descent and prunes boundaries/cycles | ✓ WIRED | `src/watchdirs/collect/scanner.py:8-9`, `:55-81`, `:161-202`, `:291-352` |

### Data-Flow Trace (Level 4)

| Artifact | Data variable | Source | Produces real data | Status |
|---|---|---|---|---|
| `src/watchdirs/cli.py` | `snapshot_payloads` | `create_snapshot()` + `scan_root()` + `insert_directory_rows()` + `finalize_snapshot()` | Yes - CLI probes created real SQLite rows and JSON payloads | ✓ FLOWING |
| `src/watchdirs/collect/scanner.py` | `rows`, `errors` | `os.stat`, `os.scandir`, mount lookup/classification, inode tracking | Yes - nested-tree probe persisted depth `[1, 0]` and row count `2` | ✓ FLOWING |
| `src/watchdirs/db/migrations.py` | `directory_sizes` inserts | `DirectoryAggregate` BLOB fields | Yes - repo-local probe persisted BLOB path/name values visible in SQLite | ✓ FLOWING |
| `src/watchdirs/collect/scanner.py` | `root_path` | `Path(options.root).resolve(strict=False)` | Yes, but wrong for symlink roots - configured symlink path is replaced by target path | ⚠️ HOLLOW SEMANTIC |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full Phase 01 suite | `pytest -q` | `49 passed in 2.33s` | ✓ PASS |
| Repo-local collect command writes snapshot evidence | `./watchdirs collect --config <tmp> --db <tmp> --json --notes probe` | exit `0`; 1 snapshot row; 1 directory row; JSON payload matched DB metadata | ✓ PASS |
| Module entrypoint writes snapshot evidence | `PYTHONPATH=src python3 -m watchdirs collect --config <tmp> --db <tmp> --json` | exit `0`; 1 snapshot row; 2 directory rows for nested tree | ✓ PASS |
| Default no-follow semantics for configured roots | `./watchdirs collect` against a config root that is a symlink | exit `0`, but `roots[0]` and `snapshots[0].root_path` were the symlink target (`real-root`), not the configured symlink path (`link-root`) | ✗ FAIL |

### Probe Execution

| Probe | Command | Result | Status |
|---|---|---|---|
| Phase probe scripts | `find scripts -path '*/tests/probe-*.sh' -type f` | No declared or conventional probe scripts found for Phase 01 | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| `COLL-01` | `01-01`, `01-02` | Run `watchdirs collect` to create a timestamped snapshot for configured roots | ✓ SATISFIED | CLI help/tests plus both live probes |
| `COLL-02` | `01-02` | Record snapshot status, timing, root path, notes, fatal error | ✓ SATISFIED | Schema + lifecycle helpers + interrupt/failure tests |
| `COLL-03` | `01-03` | Record recursive directory aggregate rows with hierarchy/count/bytes/error fields | ✓ SATISFIED | Scanner rows, BLOB schema, nested-tree probe |
| `COLL-04` | `01-03` | Store disk bytes using physical allocation semantics | ✓ SATISFIED | `du` oracle test, hardlink tests, `st_blocks * 512` implementation |
| `COLL-05` | `01-03` | Store apparent bytes using logical size semantics | ✓ SATISFIED | `apparent_bytes_from_stat()` and `test_apparent_bytes_use_st_size_rules` |
| `FSEM-01` | `01-03` | Scanner does not follow symlinks by default | ✗ BLOCKED | Descendant symlinks are skipped, but configured-root symlinks are followed via `resolve(strict=False)` |
| `FSEM-02` | `01-03` | Avoid double-counting hardlinked physical bytes | ✓ SATISFIED | `_disk_bytes_for_entry()` plus hardlink and limit tests |
| `FSEM-03` | `01-04` | Read mount information and skip virtual/transient filesystems by default | ✓ SATISFIED | mount parser/classifier plus mount-policy tests |
| `FSEM-04` | `01-04` | Avoid descending into overlay and namespace mount views by default | ✓ SATISFIED | classifier defaults and overlay/nsfs tests |
| `FSEM-05` | `01-03` | Record partial path-level errors instead of silently dropping subtrees | ✓ SATISFIED | permission-error and skipped-mount/error row handling |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| reviewed phase files | — | No `TODO`/`FIXME`/`XXX`, placeholder returns, or console-log stubs found | ℹ️ Info | The blocker is a real semantic gap, not placeholder code |

### Gaps Summary

Phase 01 is close, but not complete enough to pass. The implementation really does provide no-install collection, SQLite persistence, recursive aggregate rows, `du`-style disk-byte accounting, hardlink dedup, mount-policy skipping, and interrupt-safe rollback. The blocker is narrower and more important than a task checklist miss: configured-root symlinks are followed by default, so the filesystem-semantics promise in `FSEM-01` and roadmap success criterion 3 is not fully true.

`01-REVIEW.md` is still valid for the interrupt-rollback issue fixed in `f546dd1`; that review scope was clean. It did not cover the root-symlink boundary, and the current test suite also misses that case.

### Residual Risks

- Live mount-policy behavior was verified through unit coverage and local `/proc/self/mountinfo` parsing patterns, not on `senbonzakura` itself.
- Because the symlink-root regression is untested today, future refactors can keep the suite green while still violating `FSEM-01`.

---

_Verified: 2026-06-12T22:52:04Z_
_Verifier: the agent (gsd-verifier)_
