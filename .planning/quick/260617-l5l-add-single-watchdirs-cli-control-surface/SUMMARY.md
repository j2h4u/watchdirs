# Quick Task 260617-l5l Summary

## Result

Implemented a single-CLI control surface for root-collected watchdirs data.

Main implementation commit: `5a5eb85`.

## Behavior

- Root timers continue to run `collect`, `prune`, and `vacuum` directly against `/var/lib/watchdirs/watchdirs.sqlite3`.
- Ordinary users run the same `watchdirs` command for read-only reports.
- When a non-root user runs an allowed read command without an explicit alternate `--db`, the CLI proxies to `/run/watchdirs/query.sock`.
- The root query service forces `/var/lib/watchdirs/watchdirs.sqlite3` and rejects arbitrary `--db`.
- The query service allowlist is limited to `top`, `diff`, `report`, `deleted`, `explain-path`, and `df-vs-index`.

## Files

- `src/watchdirs/cli.py`: proxy client, hidden `query-server`, fixed allowlist, forced host DB.
- `src/watchdirs/db/connection.py`: explicit `open_readonly_connection`.
- `ops/systemd/watchdirs-query.socket`: Unix socket at `/run/watchdirs/query.sock`.
- `ops/systemd/watchdirs-query@.service`: one-request root query service.
- `README.md`: documented the single-CLI socket control surface.
- `/tmp/watchdirs-host-rollout.sh`: updated root rollout script to install query socket assets and create the `watchdirs` group.

## Verification

- `pytest -q` passed: `257 passed`.
- `systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer ops/systemd/*.socket` passed for watchdirs assets.

The `systemd-analyze` run also emitted unrelated host warnings for existing `nut-exporter` and `alloy` units outside this repo.

