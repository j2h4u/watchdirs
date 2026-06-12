# Phase 1: Trusted Snapshot Collection - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-06-12
**Phase:** 1-Trusted Snapshot Collection
**Areas discussed:** Scanner engine, Root and mount policy, Snapshot state model, Storage and config locations

---

## Scanner Engine

| Option | Description | Selected |
|--------|-------------|----------|
| Native Python scanner | Use `os.scandir()` and stat metadata directly; best control over rows, errors, mount policy, and SQLite writes. | ✓ |
| Wrap `du` output | Delegate disk semantics to GNU/POSIX `du`; simpler initial counting but weaker metadata and parsing/control. | |
| Hybrid primary `du` plus Python metadata pass | More complicated and risks two inconsistent traversals. | |

**User's choice:** User does not care which engine is used as long as it is faster and efficient.
**Notes:** Expert/research-backed resolution is native Python scanner as primary, with `du` used for comparison tests and troubleshooting. Evidence checked: Python `os.scandir()`/PEP 471 performance rationale, GNU `du` hardlink and one-file-system semantics, and POSIX `du` traversal semantics.

---

## Root and Mount Policy

| Option | Description | Selected |
|--------|-------------|----------|
| README-driven configured roots | Use README.md as bootstrap context; collect from configured roots and make mount decisions explicit. | ✓ |
| Hardcoded host-wide scan | Hide `/`, `/home`, `/var`, `/opt`, `/srv` in implementation defaults. | |
| User must always pass roots manually | Maximum explicitness but poor operational ergonomics. | |

**User's choice:** User noted this was already discussed in the Bootstrap document and clarified that the document is README.md.
**Notes:** Resolution: README.md is canonical. Default behavior should be explicit configured roots, with a practical local sample for `senbonzakura`. Scanner reads mountinfo/findmnt and skips virtual/transient/container overlay mount views by default.

---

## Snapshot State Model

| Option | Description | Selected |
|--------|-------------|----------|
| complete / partial / failed | Preserve useful rows while making incomplete evidence visible. | ✓ |
| fail whole snapshot on first path error | Strict but loses useful forensic evidence from accessible paths. | |
| always complete with warnings | Easier reporting but risks false confidence. | |

**User's choice:** User did not know and delegated the decision.
**Notes:** Resolution: use `complete`, `partial`, and `failed`. Fatal root-level errors live on `snapshots.error`; path/subtree errors live on `directory_sizes.error`.

---

## Storage and Config Locations

| Option | Description | Selected |
|--------|-------------|----------|
| XDG state for user-run DB | `${XDG_STATE_HOME:-~/.local/state}/watchdirs/watchdirs.sqlite3`; separates durable state from cache. | ✓ |
| `~/.cache` for everything | Convenient, but cache can be deleted without data loss and should not hold canonical history. | |
| `/var/tmp` for DB | Survives reboot but is still temporary and cleanup-managed. | |
| systemd StateDirectory/CacheDirectory for service install | Correct later system service path: `/var/lib/watchdirs` and `/var/cache/watchdirs`. | ✓ |

**User's choice:** User suggested `~/.cache`, `/srv`, or `/var/tmp` and recognized multiple viable options.
**Notes:** Resolution separates user-run and system-service modes. User-run default DB goes under XDG state; cache/temp under XDG cache; future systemd install uses `StateDirectory=watchdirs` and `CacheDirectory=watchdirs`. `/var/tmp` is only for temporary artifacts, not canonical SQLite state. Evidence checked: XDG Base Directory spec, FHS `/var/cache` and `/var/tmp`, and systemd file hierarchy/execution directory docs.

---

## Code Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Small dataclass-based modules | Separate CLI/config, mount policy, scanner/aggregation, and SQLite persistence with typed dataclass DTOs. | ✓ |
| Single procedural collector | Faster to sketch, but risks spaghetti and harder testing. | |
| Heavy framework/abstraction layer | Overkill for a small local CLI. | |

**User's choice:** User explicitly requested clean code: DRY, KISS, no spaghetti, preferably dataclasses.
**Notes:** Planner should encode this as implementation constraints and acceptance criteria, not as vague style preference.

---

## the agent's Discretion

- User asked that deep technical questions be resolved through expert panel or Exa best-practice research rather than pushed back as trivia.
- User delegated scanner engine details and snapshot state semantics to the agent.
- Plan-checker follow-up resolved the remaining technical questions: `file_count` is path-count while `disk_bytes` is hardlink-deduped; Phase 1 provides `./watchdirs collect` plus `python -m watchdirs` without requiring pip install; tmpfs stays explicit opt-in.

## Deferred Ideas

- Docker enrichment storage is deferred to Phase 3.
- Systemd timer, pruning, vacuum details, and strong `nice`/`ionice` priority reduction are deferred to Phase 4. User explicitly emphasized that scheduled scans must not interfere with other host workloads.
- Persistent file-level inventory is deferred to v2.
