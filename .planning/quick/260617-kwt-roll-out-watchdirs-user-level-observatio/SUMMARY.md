# Quick Task 260617-kwt Summary

## Result

User-level passive observation is running under `systemd --user`.

Installed local runtime surface:

- Launcher: `/home/j2h4u/.local/bin/watchdirs`
- Config: `/home/j2h4u/.config/watchdirs/watchdirs.toml`
- Database: `/home/j2h4u/.local/state/watchdirs/watchdirs-v4.sqlite3`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-collect.service`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-collect.timer`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-prune.service`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-prune.timer`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-vacuum.service`
- Units: `/home/j2h4u/.config/systemd/user/watchdirs-vacuum.timer`

## Verification

- `systemd-analyze --user verify ~/.config/systemd/user/watchdirs-*.service ~/.config/systemd/user/watchdirs-*.timer` passed.
- `watchdirs-collect.timer`, `watchdirs-prune.timer`, and `watchdirs-vacuum.timer` are enabled and active.
- `systemctl --user --failed --no-pager` reports `0 loaded units listed`.
- SQLite schema is version `4`.
- Database size after seed collection is `7.7M`.

Seed snapshots:

| Snapshot | Root | Status | Rows | Collapsed rows |
|----------|------|--------|------|----------------|
| 1 | `/` | partial | 27039 | 771 |
| 2 | `/home/j2h4u` | complete | 19417 | 544 |

The first `/` user-scope seed was intentionally abandoned as the recurring target because user permissions produce a partial snapshot and a failed collect unit. The active recurring config now scans `/home/j2h4u`, which completed successfully:

- Duration: `18.47s`
- Row count: `19417`
- Peak memory: `85.8M`

## Remaining Gap

The documented system-wide host deployment is still blocked by non-interactive `sudo`:

- `/usr/local/bin/watchdirs`
- `/etc/watchdirs/watchdirs.toml`
- `/var/lib/watchdirs/watchdirs.sqlite3`
- `/etc/systemd/system/watchdirs-*`

Until the privileged install is run, passive observation covers `/home/j2h4u`, not the whole host root `/`.

