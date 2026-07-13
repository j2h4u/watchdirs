## Project

**watchdirs** is a local forensic CLI for explaining disk space growth on a
Linux host. It periodically records recursive directory aggregate snapshots so
an agent can answer what directory trees grew, whether growth matches real disk
pressure, and where to drill down next without broad manual `du` sweeps.

The first version is an operations tool, not a UI-first disk visualizer. Its
primary user is an agent investigating host disk pressure with evidence.

## Constraints

- Target a single local Linux host first.
- Use SQLite for v1.
- Store recursive directory aggregate rows rather than per-file history.
- Do not follow symlinks.
- Do not silently descend into virtual, transient, or container overlay
  filesystems.
- Track both apparent bytes and disk bytes.
- Make hardlink semantics explicit.
- Use systemd timers, idle CPU/I/O priority, locking, partial-failure recording,
  and whole-snapshot retention for unattended operation.
- Keep JSON output first-class; human-readable output is useful but secondary.

## Development

- Follow existing code patterns before introducing new abstractions.
- Prefer focused tests that lock the behavior being changed.
- Run `just check` for the static quality gate.
- Run `just unit` for the full test suite.
- Run `just coverage` when changes affect covered behavior or coverage-sensitive
  code paths.
