# Quick Task 260617-kwt: Roll out user-level observation timers

## Goal

Start passive watchdirs observation now, using the best available non-interactive route, and document any remaining privileged rollout step.

## Scope

- Install a user-level launcher and systemd user units.
- Seed one collection and verify timer health.
- Keep the privileged system-wide `/` deployment out of scope if `sudo` cannot run non-interactively.

## Plan

1. Check whether the documented system install paths already exist.
2. Attempt system-wide install only if non-interactive privilege is available.
3. Fall back to user-level systemd units because lingering is enabled for the user.
4. Seed collection, verify database/schema/timers/journals, and record the remaining operational gap.

