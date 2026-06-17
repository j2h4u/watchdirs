# Quick Task 260617-lo2 Summary

## Result

Added practical defaults for common read-only CLI use.

Main implementation commit: `bae8cbc`.

## Behavior

- `watchdirs` is shorthand for `watchdirs top --snapshot latest`.
- `watchdirs report`, `watchdirs diff`, `watchdirs deleted`, and `watchdirs explain-path PATH` default to `--since 24h`.
- Unprivileged host use still proxies through `/run/watchdirs/query.sock` when no explicit `--db` is supplied.
- Mutating commands still require explicit subcommands and keep their existing arguments.

## Verification

- `pytest -q` passed: `259 passed`.
- Installed host CLI smoke test passed through the query socket:
  - `sg watchdirs -c '/usr/local/bin/watchdirs'`
- `watchdirs report --json` now uses the `24h` default, but currently returns `no_snapshot_pairs` until a second host snapshot exists.

