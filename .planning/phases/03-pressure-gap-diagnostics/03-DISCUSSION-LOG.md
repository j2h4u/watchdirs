# Phase 3: Pressure Gap Diagnostics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-14
**Phase:** 03-pressure-gap-diagnostics
**Areas discussed:** df vs index mismatch, deleted-open files, Docker/containerd evidence, final summary compactness

---

## `df` vs Indexed Evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Fact only | Show filesystem usage, indexed usage, and unattributed remainder. | |
| Fact + likely reasons | Add likely causes such as deleted-open files, skipped mounts, Docker/containerd, filesystem metadata. | |
| Fact + likely reasons + check commands | Add concrete verification commands without cleanup actions. | ✓ |

**User's choice:** Fact + likely reasons + commands.
**Notes:** The user wanted a simple explanation of why `df` can diverge from directory indexing. The captured decision is that `df` is filesystem-level accounting and does not provide per-directory attribution; `watchdirs` should use it as a control total and report unattributed remainder plainly.

---

## Deleted-Open Files

| Option | Description | Selected |
|--------|-------------|----------|
| Brief count | Show total size and top process only. | |
| Culprit list | Show PID/process/size/path/filesystem entries. | |
| Culprit list + cautious action hint | Add likely service restart/close action as a check, not an automatic operation. | ✓ |

**User's choice:** Culprit list + cautious action hint.
**Notes:** Action wording must be careful: recommend checking/restarting a service when appropriate, not killing processes automatically.

---

## Docker and Containerd Evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Brief total | Show Docker total and reclaimable totals only. | |
| Category breakdown | Show build cache, images, containers, volumes, containerd when available. | |
| Category breakdown + verification commands | Add commands such as `docker system df -v` and `docker builder du`. | ✓ |

**User's choice:** Category breakdown + verification commands.
**Notes:** Docker cache is still files, usually under Docker/containerd storage paths. Enrichment exists to distinguish reclaimable vs active and to avoid agents guessing cleanup safety.

---

## Final Summary Compactness

| Option | Description | Selected |
|--------|-------------|----------|
| Short summary | Main growth and unattributed remainder. | |
| Summary + next checks | Add 3 prioritized next checks. | ✓ |
| Summary + next checks + cautious recommendation | Add an operational recommendation such as likely safe cleanup or disk upgrade hint. | |

**User's choice:** Summary + next checks.
**Notes:** The user explicitly warned not to show hundreds of lines of recommendations because the agent will get lost. Planner should enforce compact defaults, top-N limits, and truncation metadata.

---

## the agent's Discretion

- Technical details of Linux `df` reproduction, deleted-open-file collection method, Docker CLI parsing, and threshold defaults are delegated to research/planning.
- Downstream agents should use expert review or primary documentation for deep Linux/filesystem choices.

## Deferred Ideas

- Automatic cleanup actions.
- Service restarts performed by `watchdirs`.
- Long, exhaustive diagnostic recommendation lists.
