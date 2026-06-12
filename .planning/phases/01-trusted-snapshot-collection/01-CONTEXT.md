# Phase 1: Trusted Snapshot Collection - Context

**Gathered:** 2026-06-12
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the first trustworthy collection path for `watchdirs`: a CLI command that scans configured roots, records recursive directory aggregate snapshots in SQLite, applies filesystem-safety rules, and preserves enough status/error metadata for later reports to be believable.

It does not deliver growth reports, deleted-open-file diagnostics, Docker enrichment, scheduling, pruning, or operational installation. Those are later phases.

</domain>

<decisions>
## Implementation Decisions

### Scanner Engine
- **D-01:** Use a native Python scanner built around `os.scandir()`/`DirEntry`/`stat(follow_symlinks=False)` as the primary collection engine.
- **D-02:** Treat `du` as a verification oracle and troubleshooting comparison, not as the primary data source. Tests and manual diagnostics should compare selected subtrees against `du -x`-style semantics where practical.
- **D-03:** The scanner must compute both `apparent_bytes` from logical size and `disk_bytes` from allocated blocks. `disk_bytes` is the primary disk-pressure signal.
- **D-04:** Deduplicate physical bytes by `(st_dev, st_ino)` within a snapshot for hardlinked files. Attribute the counted bytes to the first path encountered and document that hardlink attribution is traversal-order dependent.

### Root and Mount Policy
- **D-05:** Use README.md as the bootstrap/canonical design note for root and mount policy. The README already captures the pain point and open design questions.
- **D-06:** `collect` should operate from configured roots, not from an implicit broad host scan hidden in code.
- **D-07:** Provide a sensible local sample/default for the target host: scan `/` as one filesystem, and allow explicit additional roots when the operator wants separate mount coverage. Avoid overlapping roots by default.
- **D-08:** Read live mount information from `/proc/self/mountinfo` or `findmnt` and classify every mountpoint explicitly.
- **D-09:** Skip virtual and transient filesystems by default, including procfs, sysfs, devfs/devtmpfs, devpts, tmpfs unless explicitly included, cgroup2, pstore, securityfs, debugfs, tracefs, configfs, fusectl, nsfs, and container overlay namespace views.
- **D-10:** Do not follow symlinks by default. Record enough metadata/error context to explain skipped paths, but do not traverse through symlinks.

### Snapshot State and Errors
- **D-11:** A snapshot is `complete` only when all configured roots were scanned without fatal root-level failure and without unhandled traversal exceptions.
- **D-12:** A snapshot is `partial` when at least one path/subtree failed but collection still produced useful rows for one or more roots.
- **D-13:** A snapshot is `failed` when no trustworthy directory aggregate data was produced for the requested collection.
- **D-14:** Store fatal snapshot errors on the `snapshots` row and per-path/subtree errors on `directory_sizes.error`.
- **D-15:** Per-path errors must not silently disappear. Later reporting can decide whether to show warnings, but collection must preserve them.

### Storage and Config Locations
- **D-16:** For user-run local usage, default persistent state to `${XDG_STATE_HOME:-~/.local/state}/watchdirs/watchdirs.sqlite3`.
- **D-17:** Use `${XDG_CACHE_HOME:-~/.cache}/watchdirs/` only for rebuildable cache or temporary collection artifacts, not as the primary SQLite state path.
- **D-18:** For future systemd/system service installation, use systemd-managed persistent state/cache directories: `StateDirectory=watchdirs` for `/var/lib/watchdirs` and `CacheDirectory=watchdirs` for `/var/cache/watchdirs`.
- **D-19:** Do not put the main SQLite database in `/var/tmp`; that location is appropriate only for large persistent temporary files.
- **D-20:** Configuration should be explicit and file-based, with roots/excludes/mount-policy stored outside code. Planning can choose the exact format, but the collector must not hide host-specific roots in implementation constants.

### Code Shape
- **D-21:** Keep implementation clean, DRY, and KISS. Avoid a single spaghetti collector function that mixes CLI parsing, mount policy, traversal, aggregation, and SQLite writes.
- **D-22:** Prefer small typed data structures, especially Python `@dataclass` models, for snapshot metadata, directory aggregate rows, mount policy decisions, scanner options, and scan results.
- **D-23:** Add abstractions only when they separate real responsibilities: CLI/config loading, mount classification, traversal/aggregation, and SQLite persistence are legitimate boundaries.
- **D-24:** Keep Phase 1 stdlib-first unless a dependency removes substantial complexity; do not add packages just to make the code look architectural.

### the agent's Discretion

The user deferred low-level implementation choices to the agent when performance/correctness tradeoffs are technical. Downstream agents should prefer correctness and debuggability over shaving initial implementation time, and may use expert-panel or Exa-backed research for deep Linux/filesystem choices.

Phase 1 implementation should avoid design choices that prevent later low-priority scheduling. The actual strong `nice`/`ionice` service behavior belongs to Phase 4, but the collector should remain callable in a way that systemd can wrap with CPU/I/O priority controls.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Intent
- `README.md` - Bootstrap/design note for the original disk-growth incident, tool goals, non-goals, storage decision, mount policy, hardlink semantics, deleted-open-file caveat, and open questions.
- `.planning/PROJECT.md` - Project boundary, core value, constraints, and key decisions.
- `.planning/REQUIREMENTS.md` - Phase 1 requirements `COLL-01` through `COLL-05` and `FSEM-01` through `FSEM-05`.
- `.planning/ROADMAP.md` - Phase 1 goal, dependencies, requirements, and success criteria.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None yet. This is a greenfield repo with planning docs and README only.

### Established Patterns
- Planning artifacts are GSD-managed. Follow `AGENTS.md` and keep future changes inside GSD workflows unless the user explicitly bypasses them.
- The project is Python-oriented by decision, but no package scaffold exists yet.

### Integration Points
- Phase 1 should create the first CLI/package/storage modules and tests.
- Later phases will consume the SQLite schema and collection semantics created here, so avoid temporary schema shortcuts that would make diff/report phases rewrite collection.

</code_context>

<specifics>
## Specific Ideas

- The user confirmed README.md is the intended bootstrap document.
- The original pain point is not "what is large right now"; it is "what changed between yesterday and now, with evidence".
- The user does not care whether native traversal or `du` is used internally as long as the result is fast, efficient, and trustworthy. Expert/research-backed recommendation is native Python scanner with `du` comparison tests.
- The user suggested possible state/cache locations around `~/.cache`, `/srv`, and `/var/tmp`; context resolution is to separate persistent state from cache/temp and reserve system paths for the later systemd install path.
- The user explicitly requested clean code: DRY, KISS, no spaghetti, and preferably dataclass-based internal models.

</specifics>

<deferred>
## Deferred Ideas

- Store Docker enrichment in SQLite vs report-time evidence remains deferred to Phase 3.
- Systemd timer install details, retention TTL enforcement, and vacuum scheduling remain deferred to Phase 4.
- Strong `nice`/`ionice` priority reduction for scheduled scans is deferred to Phase 4, but must not be forgotten. The user explicitly wants watchdirs to avoid interfering with other host workloads.
- File-level inventory remains v2 unless directory aggregate snapshots prove insufficient.

</deferred>

---

*Phase: 1-Trusted Snapshot Collection*
*Context gathered: 2026-06-12*
