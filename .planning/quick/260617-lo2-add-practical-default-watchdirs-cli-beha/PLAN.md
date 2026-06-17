# Quick Task 260617-lo2: Practical read-only CLI defaults

## Goal

Reduce the number of flags an agent or operator must remember for common read-only watchdirs use.

## Kaizen Scope

Keep defaults simple and predictable:

- no adaptive command selection;
- no hidden cleanup or mutation;
- no changes to root write commands;
- no extra client command.

## Plan

1. Make `watchdirs` without arguments show the latest `top` report.
2. Default growth-window commands to `--since 24h`.
3. Keep `--db` implicit only for the host query socket path.
4. Document the short forms.
5. Add tests for no-arg dispatch and `--since` defaults.

