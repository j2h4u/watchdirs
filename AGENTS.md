<!-- GSD:project-start source:PROJECT.md -->

## Project

**watchdirs**

`watchdirs` is a local forensic CLI for explaining disk space growth on `senbonzakura`. It periodically records directory aggregate snapshots so an agent can quickly answer what directory trees grew since a prior point in time, whether the growth matches real disk pressure, and where to drill down next without broad manual `du` sweeps.

The first version is an internal operations tool, not a UI-first disk visualizer. Its primary user is an agent investigating host disk pressure with evidence.

**Core Value:** When disk usage changes unexpectedly, an agent can identify the largest growing directory trees and the evidence gaps behind `df`/`du` disagreements quickly and reproducibly.

### Constraints

- **Host scope**: Target `senbonzakura` first - the tool exists because of a concrete local disk-pressure incident.
- **Storage**: Use SQLite for v1 - one local file, no service, snapshot diff queries are straightforward SQL.
- **Data model**: Store recursive directory aggregate rows - this keeps persistent state small while preserving the growth frontier.
- **Filesystem safety**: Do not follow symlinks and do not silently descend into virtual, transient, or container overlay filesystems.
- **Correctness**: Track both apparent bytes and disk bytes, and make hardlink semantics explicit.
- **Operations**: Use systemd timers, `nice`/idle I/O, locking, partial-failure recording, and retention by whole snapshots.
- **Interface**: JSON output is first-class - human-readable output is useful but secondary.

<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
