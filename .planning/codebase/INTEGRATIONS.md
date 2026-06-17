# External Integrations

**Analysis Date:** 2026-06-17

## APIs & External Services

**Host diagnostics:**
- `docker` CLI - Read-only enrichment via `src/watchdirs/diagnostics/docker.py`
  - SDK/Client: none; direct `subprocess.run()`
  - Auth: none
- `lsof` - Deleted-open-file inventory via `src/watchdirs/diagnostics/deleted_open.py`
  - SDK/Client: none; direct `subprocess.run()`
  - Auth: none

**Host filesystem and kernel interfaces:**
- `/proc/self/mountinfo` - Mount discovery via `src/watchdirs/collect/mounts.py`
- `statvfs()` - Filesystem usage sampling in `src/watchdirs/diagnostics/df_index.py`
- `readlink`-style procfs paths - Verification hints in diagnostics modules

## Data Storage

**Databases:**
- SQLite 3 - Primary persistent store
  - Connection: file path defaults to `~/.local/state/watchdirs/watchdirs.sqlite3` or `XDG_STATE_HOME/watchdirs/watchdirs.sqlite3` from `src/watchdirs/config.py`
  - Client: stdlib `sqlite3` via `src/watchdirs/db/connection.py`
  - Journal mode: WAL
  - Application ID/page size configured in `src/watchdirs/db/connection.py`

**File Storage:**
- Local filesystem only
  - Snapshot roots come from absolute paths in the TOML config
  - Systemd units write under `/var/lib/watchdirs` and `/run/watchdirs`

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- Custom/local only
  - No external identity provider detected
  - `ops/systemd/watchdirs-query.socket` uses Unix socket permissions (`SocketUser`, `SocketGroup`, `SocketMode`)

## Monitoring & Observability

**Error Tracking:**
- None detected

**Logs:**
- stderr logging from `src/watchdirs/cli.py`
- systemd journal for unit output
- JSON payloads remain stdout-first for CLI commands

## CI/CD & Deployment

**Hosting:**
- Local Linux host with systemd units in `ops/systemd/`

**CI Pipeline:**
- GitHub Actions workflow validation only is detected in `justfile` via `actionlint`

## Environment Configuration

**Required env vars:**
- `XDG_STATE_HOME` - Optional override for the SQLite state directory
- `XDG_CACHE_HOME` - Optional override for the cache directory
- No secret-bearing environment variables detected in the runtime surface

**Secrets location:**
- Not applicable

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- `docker` and `lsof` subprocess calls only
- No HTTP callbacks or webhook endpoints detected

---

*Integration audit: 2026-06-17*
