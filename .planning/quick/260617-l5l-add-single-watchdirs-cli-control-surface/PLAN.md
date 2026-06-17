# Quick Task 260617-l5l: Single CLI root query control surface

## Goal

Keep `watchdirs` as the only public CLI while allowing an unprivileged local agent to run read-only reports against the root-owned host database.

## Expert Panel

- Linux/systemd architect: use `/run/watchdirs/query.sock`, socket activation, one request per root service process, dedicated `watchdirs` group, no direct user access to SQLite.
- Security reviewer: keep the command allowlist fixed, reject arbitrary `--db`, avoid sudoers and group-writable SQLite, treat `watchdirs` group membership as full read authorization for indexed host history.
- Pragmatic operator: keep the UX as one command, but keep the privilege boundary visible and thin; avoid a second public `watchdirsctl` or a generic RPC layer.

## Kaizen Gate

Kept:

- One public `watchdirs` CLI.
- Root-only collect/prune/vacuum.
- Socket-backed read-only reports for ordinary users.
- Fixed allowlist: `top`, `diff`, `report`, `deleted`, `explain-path`, `df-vs-index`.

Cut:

- Separate public client command.
- Direct group-readable SQLite as the primary interface.
- sudoers command delegation.
- Generic argv forwarding or arbitrary database paths.
- Per-user policy and peer credential authorization until there is real need.

## Plan

1. Add a read-only SQLite connection helper.
2. Switch reporting/read commands to the read-only helper.
3. Add a hidden `query-server` mode inside the existing CLI.
4. Make non-root read commands proxy to `/run/watchdirs/query.sock` when using the host default database.
5. Add `watchdirs-query.socket` and `watchdirs-query@.service`.
6. Cover the boundary with CLI, DB, and systemd tests.

