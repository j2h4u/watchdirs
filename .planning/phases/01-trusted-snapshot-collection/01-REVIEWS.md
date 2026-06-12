---
phase: 1
reviewers: [opencode]
reviewed_at: "2026-06-12T22:35:53+05:00"
plans_reviewed: [01-01-PLAN.md, 01-02-PLAN.md, 01-03-PLAN.md, 01-04-PLAN.md]
---

I'll review all four plans systematically. Let me first verify the referenced source files exist and read key context documents.
I have now read the key supporting documents (README, PATTERNS, VALIDATION, STATE). Here is the structured review:

---

# Cross-AI Plan Review: Phase 1 — Trusted Snapshot Collection

**Reviewer:** cross-AI reviewer
**Reviewed plans:** 01-01, 01-02, 01-03, 01-04
**Date:** 2026-06-12

---

## Executive Summary

The plans are **well-structured and traceable**. Each plan maps cleanly to specific requirements, decisions from CONTEXT.md are consistently cited, and the TDD wave-based dependency ordering is sound. The threat models, verification commands, and source coverage audit are unusually thorough for pre-execution planning.

However, there are **several HIGH-severity gaps** in filesystem-edge-case handling, memory/stack scaling, and cross-plan interface contracts that will cause real-world failures on `senbonzakura` or make later phases harder than expected. These should be fixed before Wave 1 execution begins.

---

## 1. Coverage Gaps

### 1.1 [HIGH] Non-UTF-8 / byte-encoded paths are unaddressed — Plan 01-03

Linux filesystems can contain arbitrary bytes in filenames except `/` and `\0`. Python's `os.scandir()` returns `bytes` objects for `DirEntry.name` and `DirEntry.path` when the filename is not valid UTF-8. The plans assume clean string paths throughout.

**What will break:**
- `DirectoryAggregate.path` is presumably `str`, but `os.scandir()` can return `bytes`
- `parent_path` construction and `path`-based SQL queries will fail or mangle data
- `insert_directory_rows` will crash on byte paths if the schema expects `TEXT`

**Action:** Add explicit byte-path handling to 01-03 scanner plans. Decide: (a) use surrogatescape encoding/decoding for storage and restore for display, or (b) store raw bytes and decode only for JSON output. Test with `tmp_path` fixtures containing `os.fsencode()` non-UTF-8 filenames.

---

### 1.2 [HIGH] No signal handling during collection — Cross-plan

If `./watchdirs collect` is interrupted mid-scan by SIGINT/SIGTERM (operator cancels, systemd timeout, system shutdown), the snapshot will be left with `status='failed'` (the provisional value) and no `finished_at`. The plans mention inserting with provisional `'failed'` then updating on completion, but never explicitly handle the interrupt case.

**What will break:**
- Interrupted collections leave zombie rows with indefinite `started_at` and `status='failed'` but no `error` message
- Phase 2 diff queries have no way to distinguish "interrupted scan" from "root is genuinely unscannable"
- `finished_at` remains `NULL`

**Action:** Add to 01-02: register a `atexit` or signal handler in `run_collect` that catches SIGINT/SIGTERM, calls `finalize_snapshot` with `status='failed'` and `error='collection interrupted by signal'`, commits, and re-raises. The existing `finally`/finalize pattern in the research example should be made explicit in the plan.

---

### 1.3 [HIGH] Hardlink dedup set memory consumption — Plan 01-03

The dedup set uses `(st_dev, st_ino)` keys. On `senbonzakura` with millions of inodes on `/`, this Python `set` will consume ~88 bytes per inode (`tuple(2 ints)` + set entry overhead). For 10M inodes: **~880 MB RAM** plus Python process overhead. The plans declare this acceptable ("deduplicate at snapshot scope") without analysis.

**What will break:**
- OOM-kill on the configured root `/` with large file counts
- Systemd-constrained memory cgroups in Phase 4

**Action options (add to 01-03 or 01-04):**
- (Minimal) Document that `senbonzakura` should be scanned per-filesystem rather than `/` as a broad root when inode count is high, and add a config option `dedup_scope` defaulting to `per-root` instead of `per-snapshot`
- (Better) Use a Bloom filter or probabilistic dedup for large sets, falling back to exact dedup for small trees
- (Simple) Add an optional `--no-hardlink-dedup` flag and document the trade-off

At minimum, add a note in the plan threat model about DOS/Resource Exhaustion for inode-heavy roots.

---

### 1.4 [HIGH] Recursive DFS stack depth — Plan 01-03

The plan describes "post-order DFS" and the research example shows a "stack" but the implementation may use recursion. Directory trees on Linux can legally be deeper than Python's default recursion limit (1000 frames). A deeply nested directory structure (e.g., `senbonzakura` has `overlayfs` snapshots with deep nesting under `/var/lib/containerd`) will crash with `RecursionError`.

**Action:** Explicitly require an **iterative** post-order traversal (explicit `list` stack, not function recursion) in the 01-03 plan behavior section. Add a test creating a fixture tree of depth 1500 and asserting completion.

---

### 1.5 [HIGH] Mount policy doesn't implement `-x` one-filesystem semantics — Plan 01-04

D-07 says "scan `/` as one filesystem" and the research specifies `du -x`-style semantics. The mount policy plans define `find_mount_for_path` and `should_descend`, but the relationship between the **configured root** and its **child mountpoints** is underspecified.

**Critical scenario:** Root is `/` (ext4). `/home` is a separate ext4 mount. `/var/lib/docker` is an overlay mount. Should the scanner:
- (a) stop at `/home` and `/var/lib/docker` mount boundaries (implied by D-07 and `du -x`)?
- (b) descend into all non-skipped mounts underneath the root (implied by the mount classifier's "skip list")?

The skip list only excludes virtual FS types (proc, sysfs, tmpfs, etc.) — ext4 and xfs are never skipped. So the scanner would descend into `/home` even though it's a separate filesystem. This contradicts D-07's "as one filesystem" intent and `du -x` semantics.

**Action:** Clarify 01-04: either (a) add `one_filesystem` mode that checks `st_dev` at each directory entry and prunes when the device changes (simpler, matches `du -x`), or (b) explicitly state that the skip list is the only pruning mechanism and change D-07 to acknowledge multi-filesystem traversal under `/`. Option (a) is closer to the documented intent. Add `test_scanner_stops_at_mount_boundary` to 01-04.

---

### 1.6 [MEDIUM] Config file error handling incomplete — Plan 01-01

Tests cover "config with no roots" but not:
- Missing config file (ENOENT)
- Malformed TOML syntax
- Config file permissions (EACCES)
- Root paths that don't exist on disk
- Root paths that are files, not directories

**Action:** Add to 01-01 Task 1 behavior section: `test_collect_reports_missing_config_json`, `test_collect_reports_malformed_toml_json`, `test_collect_rejects_nonexistent_root`. The `--json` flag should produce a consistent error envelope for all config failures.

---

## 2. Integration / Cross-Plan Risks

### 2.1 [HIGH] `du` comparison tolerance undefined — Plan 01-03

`test_disk_bytes_match_du_for_fixture` compares scanner `disk_bytes` to `du -skx <fixture> * 1024`. But:
- `du` may round up in 1024-byte blocks (e.g., a 1-byte file reports as 1K = 1024)
- Hardlink dedup order differences between scanner and `du` can shift bytes
- `du` version differences may change rounding behavior

The test as specified requires exact equality (`==`), which is fragile.

**Action:** Define an acceptable tolerance (e.g., `abs(scanner - du) <= 1024 * dir_count_in_fixture` or `abs(scanner - du) / max(scanner, 1) < 0.01`). Document the tolerance rationale.

---

### 2.2 [MEDIUM] `models.py` ownership split across three plans — Plans 01-02, 01-03, 01-04

`models.py` is modified by 01-02 (SnapshotRecord, DirectoryAggregate, ScanResult), 01-03 (ScannerOptions, ScanError additions), and 01-04 (MountInfo, MountDecision, MountPolicy). Each plan creates fields in the same file. If executed by different agents or sessions, merge conflicts are inevitable.

**Action:** Document the plan ordering contract explicitly: 01-03 reads 01-02's `models.py`, 01-04 reads 01-03's. Any field added in a later plan must be appended, not inserted. Or: split into `models/snapshots.py`, `models/scanner.py`, `models/mounts.py` with a re-export `__init__`.

---

### 2.3 [MEDIUM] `ScannerOptions.exclude_paths` defined but unused — Plan 01-03

`ScannerOptions.exclude_paths` is listed in the plan 01-03 artifact table but no test exercises it and no behavior describes it. It doesn't map to any Phase 1 requirement. Either implement it or remove it — leaving it as dead interface is scope creep.

**Action:** Remove from 01-03 artifact list, or add a minimal test and behavior for excluding specific subdirectories by path prefix.

---

### 2.4 [MEDIUM] `row_count` in JSON output not traced to `ScanResult` — Plan 01-02

The plan 01-02 behavior section says JSON output includes `row_count`, but the `ScanResult` dataclass field list does not include `row_count`. Either `ScanResult` needs this field, or the JSON emitter computes it from `len(ScanResult.rows)`.

**Action:** Add `row_count` to `ScanResult` fields, or explicitly state it's computed in `emit_json` from `len(rows)`.

---

### 2.5 [LOW] `--mountinfo` flag: early CLI registration, late implementation — Plans 01-01 → 01-04

01-01 registers `--mountinfo` as a CLI flag. 01-04 implements the parser. In between (01-02, 01-03), the flag is accepted but silently ignored. This is safe but should have a one-line note in 01-01 or 01-02 acknowledging the deferred flag.

**Action:** Add note to 01-01 plan: "`--mountinfo` flag is accepted but ignored until 01-04."

---

## 3. Performance & Scaling

### 3.1 [HIGH] SQLite insert strategy not specified — Plan 01-02

`insert_directory_rows` is called for each `DirectoryAggregate` row. For a root with 500,000 directories, 500,000 individual `INSERT` statements in auto-commit or explicit-transaction mode will be **unacceptably slow** (~minutes). The plans don't specify batching.

**Action:** In 01-02 Task 2 behavior, require `executemany()` with batch size (e.g., 10,000 rows per call) within a single transaction. Research section already mentions `executemany` indirectly, but the plan must make it explicit.

---

### 3.2 [MEDIUM] SQLite pragma defaults insufficient — Plan 01-02

The plan mentions `PRAGMA user_version` but not:
- `PRAGMA journal_mode=WAL` — needed for Phase 4 concurrent reads during collection and crash resilience
- `PRAGMA foreign_keys=ON` — needed for `directory_sizes.snapshot_id` FK integrity
- `PRAGMA busy_timeout=5000` — prevents "database is locked" errors if Phase 4 reads overlap with collection
- `PRAGMA mmap_size` — large scans benefit from memory-mapped I/O

**Action:** Add to 01-02 schema.sql or connection.py: set WAL mode, foreign keys, and busy timeout on connection open. Document the choices.

---

### 3.3 [LOW] No progress indication for long scans — Cross-plan

Scanning `/` on `senbonzakura` could take minutes. The plans provide no mechanism for the operator to know if collection is progressing or stuck. Not a correctness issue but a significant UX gap for a forensic tool whose operator may be investigating under time pressure.

**Action (optional):** Add `--verbose` flag to `collect` (or use stderr for progress) that prints current directory being scanned and aggregate byte count so far. Deferred to 01-03 or 01-04 as low-priority.

---

## 4. Test Quality

### 4.1 [MEDIUM] Monkeypatch-based error tests are fragile — Plan 01-03

`test_permission_error_marks_partial_row` suggests monkeypatching `os.scandir()` or `DirEntry.stat()`. Mocking at this level:
- Couples tests to internal scanner implementation
- Won't catch real `PermissionError` from `scandir()` (which is different from `stat()` failure)
- May miss `NotADirectoryError`, `FileNotFoundError`, and other real OS error types

**Action:** Instead of monkeypatching, create fixture subdirectories with `chmod 000` and restore with `chmod 755`. This exercises real permission errors end-to-end. The test helper should use `tmp_path` and `path.chmod(0o000)`.

---

### 4.2 [MEDIUM] Missing test for snapshot-scope dedup correctness across roots — Plan 01-03

The hardlink dedup tests use a single root. But the research says dedup is "snapshot-wide" and D-07 allows "explicit additional roots." If two roots share a device, a hardlink across root boundaries should be deduped. The current test plan doesn't cover this.

**Action:** Add `test_hardlinks_dedup_across_roots` with two configured roots that share the same `tmp_path`-backed device, each containing a hardlink to the same inode.

---

### 4.3 [LOW] XDG fallback path not tested — Plan 01-01

`test_user_db_default_uses_xdg_state` tests when `XDG_STATE_HOME` is set. The more common case (XDG unset, fallback to `~/.local/state`) is not tested. `os.path.expanduser("~")` behavior in CI/test environments can differ from production.

**Action:** Add `test_user_db_default_falls_back_to_dot_local_state` with `XDG_STATE_HOME` explicitly unset in the subprocess environment.

---

## 5. Threat Model Gaps

### 5.1 [MEDIUM] Infinite symlink loop through mount points — Plan 01-04

The plans correctly handle symlinks (FSEM-01: never follow). But a **bind mount loop** (e.g., `mount --bind /A /A/B` creating a cycle visible through mount entry, not symlink) is not addressed. `find_mount_for_path` with longest-prefix matching could traverse infinitely.

**Action:** Add cycle detection to `find_mount_for_path` or `should_descend`: track visited `(maj:min)` pairs or `mount_id`s and reject re-entry. This is low-probability on `senbonzakura` but high-impact if it occurs.

---

### 5.2 [LOW] Path injection through config — Plan 01-01

If the TOML config file is writable by a non-root user and the timer runs as root (Phase 4), an attacker could add `/etc/shadow` as a root path and collect metadata about protected files. This is deferred to Phase 4 but should be noted.

**Action:** Add a note to 01-01 threat model: in Phase 4, ensure config file ownership/permissions match the service user.

---

## 6. Scope Discipline

All four plans stay within Phase 1 boundaries. No Phase 2-4 features are in scope. The `exclude_paths` field (Section 2.3) is the only marginal case.

---

## 7. Missing Edge Cases Summary

| # | Severity | Plan | Issue | Action |
|---|----------|------|-------|--------|
| 1 | HIGH | 01-03 | Byte-encoded filenames crash the scanner | Add surrogatescape decode, test with `os.fsencode()` fixtures |
| 2 | HIGH | 01-02 | SIGINT leaves zombie snapshot rows | Add signal handler + finalize-on-interrupt |
| 3 | HIGH | 01-03 | Hardlink dedup set: ~880 MB RAM for 10M inodes | Add `dedup_scope` config or Bloom filter option |
| 4 | HIGH | 01-03 | Recursive DFS blows Python stack on deep trees | Require iterative traversal, test with depth 1500 |
| 5 | HIGH | 01-04 | Mount classifier doesn't enforce `du -x` one-filesystem | Add `st_dev` boundary check or clarify D-07 |
| 6 | HIGH | 01-03 | `du` comparison uses exact equality instead of tolerance | Define tolerance threshold |
| 7 | HIGH | 01-02 | Individual INSERT per directory row is too slow | Require `executemany()` with batch size |
| 8 | MEDIUM | 01-01 | Config errors (missing, malformed, EACCES) not tested | Add config-error test cases |
| 9 | MEDIUM | 01-02 | WAL mode, foreign keys, busy timeout not set | Add pragmas to connection setup |
| 10 | MEDIUM | 01-02 | `models.py` shared across 3 plans, merge risk | Document append-only rule or split into submodules |
| 11 | MEDIUM | 01-04 | Mount path unescaping edge cases (`\134`, `\n`) | Add unescape tests for backslash, newline, tab |
| 12 | MEDIUM | 01-03 | `apparent_bytes` for non-regular files is vague | Specify FIFO/socket/device = 0 apparent bytes |
| 13 | MEDIUM | 01-03 | Error tests use monkeypatch instead of real chmod | Use `chmod 000` fixture for real OS errors |
| 14 | LOW | 01-01 | Shebang not specified for `./watchdirs` | Specify `#!/usr/bin/env python3` |
| 15 | LOW | 01-01 | XDG unset fallback not tested | Add fallback test case |
| 16 | LOW | 01-04 | Bind-mount loop not detected | Add mount-id cycle detection |

---

## 8. Overall Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Requirement coverage | **Strong** | All 10 Phase 1 requirements mapped to plans with traceable tests |
| Decision compliance | **Strong** | Every D-xx decision cited and honored in relevant plans |
| Test strategy (TDD) | **Good** | RED → GREEN pattern explicit; some tests need real fixtures instead of mocks |
| Error handling | **Weak** | Several HIGH gaps: signals, byte paths, non-existent roots, permission errors |
| Performance planning | **Weak** | Memory (dedup set), insert throughput, and stack depth not addressed |
| Integration clarity | **Good** | Dependencies and wave ordering are sound; `models.py` ownership needs clarification |
| Security / threat model | **Good** | STRIDE per plan with appropriate dispositions; bind-mount cycle and config-injection are missed |
| Scope discipline | **Strong** | No Phase 2-4 creep detected |

**Verdict:** The plans are **close to executable** but the 7 HIGH-severity issues must be resolved before Wave 1 begins. Fixes are small additions to plan text, not fundamental redesigns. I recommend adding these as explicit plan amendments before first commit.


---

# OpenCode Review Cycle 2

# Convergence Review: Phase 1 Amended Plans

**Reviewer:** cross-AI reviewer (second pass)
**Reviewed plans:** 01-01, 01-02, 01-03, 01-04 (amended)
**Date:** 2026-06-12

---

CYCLE_SUMMARY: current_high=0 current_actionable=2

---

## Current HIGH Concerns

None.

All 7 HIGH-severity issues from the prior review are materially resolved:

| # | Original HIGH Concern | Amendment Evidence |
|---|---|---|
| 1 | Byte-encoded paths crash scanner | 01-02: BLOB path columns; 01-03: `path_bytes`, `display_path`, `test_non_utf8_paths_round_trip_through_scanner_and_sqlite` |
| 2 | SIGINT leaves zombie snapshots | 01-02: `test_collect_finalizes_snapshot_on_sigterm`, explicit signal handler wrapping active snapshot IDs |
| 3 | Hardlink dedup set unbounded memory | 01-03: `ScannerOptions.hardlink_dedup_max_entries`, `test_hardlink_dedup_resource_limit_records_error`, T-01-09 |
| 4 | Recursive DFS blows Python stack | 01-03: iterative post-order traversal requirement, `test_iterative_postorder_handles_deep_tree_depth_1500` |
| 5 | Mount classifier ignores `du -x` semantics | 01-04: `MountPolicy.one_filesystem` default true, `test_scanner_stops_at_st_dev_boundary_in_one_filesystem_mode`, explicit additional root coverage test |
| 6 | `du` comparison uses exact equality | 01-03: `abs <= 1024 * max(1, directory_count)` tolerance, documented rationale |
| 7 | Individual INSERT per row too slow | 01-02: `executemany()` batches of 10000 rows, `test_insert_directory_rows_uses_executemany_batches` |

---

## Current Actionable Non-HIGH Concerns

### 1. [MEDIUM] `hardlink_dedup_max_entries` default value unspecified — Plan 01-03

The mechanism exists and is tested, but the plan does not state what the production default value should be. If it defaults to `None` (unlimited), the OOM vulnerability on large filesystems is deferred to operator configuration rather than prevented by default.

**Action:** Pick a reasonable default (e.g., 500,000 entries = ~44 MB) and document it in the plan, or state that the default is intentionally unlimited with the operator responsible for tuning.

### 2. [MEDIUM] `DirectoryAggregate.path` BLOB storage detail mismatch — Plans 01-02 vs 01-03

01-02 declares `path`, `parent_path`, and `name` as BLOB columns. 01-03 says these are "raw filesystem bytes derived with `os.fsencode()`". However, `os.fsencode()` is a no-op on bytes and only encodes `str` to bytes — the actual scanner must handle the `os.scandir()` behavior where `DirEntry.path` is `str` for valid-UTF-8 paths and `bytes` for non-UTF-8 paths. The plan text is slightly imprecise about this dual-type handling.

**Action:** Clarify in 01-03 implementation that `os.scandir()` delivers mixed `str`/`bytes` paths and the scanner must normalize to `bytes` in both cases (encoding `str` paths with `os.fsencode()` and keeping `bytes` paths as-is).

---

## Assessment

All 7 HIGH blockers from the prior review have been addressed with explicit tests, behaviors, and threat model entries. The `models.py` ownership contract, `exclude_paths` activation, config error JSON envelope, `row_count` field, permission-test realism, XDG fallback, mountinfo-flag acknowledgment, bind-mount cycle protection, and `--mountinfo` ownership note — all previously MEDIUM items — are likewise resolved in the amended text.

The two remaining actionable items are MEDIUM: a missing default value specification and a minor precision gap in byte-path normalization. Neither should block Wave 1 execution.

**Verdict:** Plans can proceed to execution.


---

# OpenCode Review Cycle 3

CYCLE_SUMMARY: current_high=0 current_actionable=0

**Rationale:**
1. **hardlink_dedup_max_entries default** — Resolved. The plan now states the default is `500000` in three places: the `ScannerOptions` field declaration, the behavior spec, the threat model, and the success criteria.
2. **BLOB storage/path encoding** — Resolved. The plan now explicitly describes the dual-type `os.scandir()` handling: preserve `bytes` paths unchanged, encode `str` paths with `os.fsencode()`, decode only at display boundaries with a raw hex fallback for non-UTF-8 paths.
