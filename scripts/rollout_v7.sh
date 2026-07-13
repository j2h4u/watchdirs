#!/usr/bin/env bash
set -euo pipefail

# One-time v7 cutover. The deployed watchdirs executable must already speak v7.
# This script deliberately has no v6 runtime fallback: a failed verification
# leaves the original database in place and preserves the cutover backup.

declare -r STATE_DIR='/var/lib/watchdirs'
declare -r DB_PATH="${STATE_DIR}/watchdirs.sqlite3"
declare -r CONFIG_PATH='/etc/watchdirs/watchdirs.toml'
declare -r WATCHDIRS_BIN='/usr/local/bin/watchdirs'
declare -r ROLLOUT_LOCK='/run/lock/watchdirs-v7-rollout.lock'
declare -r BACKUP_PREFIX="${DB_PATH}.v7-backup-"
declare -r UNITS=(
    'watchdirs-collect.timer'
    'watchdirs-collect.service'
    'watchdirs-prune.timer'
    'watchdirs-prune.service'
    'watchdirs-vacuum.timer'
    'watchdirs-vacuum.service'
    'watchdirs-query.socket'
)

declare backup_path=''
declare candidate_path=''
declare transformer_path=''
declare services_quiesced=0
declare cutover_done=0

function die {
    local -r message="${1:-}"
    local -ri code="${2:-1}"

    printf 'FATAL: %s\n' "$message" 1>&2
    exit "$code"
} 1>&2

function log {
    local -r message="$1"

    printf 'watchdirs-v7-rollout: %s\n' "$message"
}

function require_command {
    local -r command_name="$1"

    # assert: required command is installed
    command -v "$command_name" >/dev/null 2>&1 || die "required command is missing: ${command_name}"
}

function sqlite_scalar {
    local -r database_path="$1"
    local -r query="$2"
    local result

    result=$( sqlite3 -readonly "$database_path" "$query" ) || die "SQLite query failed: ${query}"
    printf '%s' "$result"
}

function assert_database_integrity {
    local -r database_path="$1"
    local integrity foreign_keys

    integrity=$( sqlite_scalar "$database_path" 'PRAGMA integrity_check;' )
    [[ "$integrity" == 'ok' ]] || die "integrity_check failed for ${database_path}: ${integrity}"
    foreign_keys=$( sqlite_scalar "$database_path" 'PRAGMA foreign_key_check;' )
    [[ -z "$foreign_keys" ]] || die "foreign_key_check returned rows for ${database_path}"
}

function database_version {
    sqlite_scalar "$1" 'PRAGMA user_version;'
}

function assert_v7_shape {
    local -r database_path="$1"
    local version interval_table diagnostic_table legacy_table

    version=$( database_version "$database_path" )
    [[ "$version" == '7' ]] || die "expected schema v7, got v${version} in ${database_path}"
    interval_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_size_intervals';" )
    [[ "$interval_table" == '1' ]] || die "v7 interval table is missing from ${database_path}"
    diagnostic_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_size_diagnostics';" )
    [[ "$diagnostic_table" == '1' ]] || die "v7 diagnostic table is missing from ${database_path}"
    legacy_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_sizes';" )
    [[ "$legacy_table" == '0' ]] || die "legacy directory_sizes table remains in ${database_path}"
    assert_database_integrity "$database_path"
}

function assert_free_space {
    local -r database_path="$1"
    local database_bytes required_bytes available_bytes

    database_bytes=$( stat --format='%s' "$database_path" )
    # assert: leave room for the source backup, candidate, and SQLite journal
    required_bytes=$(( database_bytes * 3 + 67108864 ))
    available_bytes=$( df --output=avail -B1 "$STATE_DIR" | tail -n 1 | tr -d ' ' )
    [[ "$available_bytes" =~ ^[0-9]+$ ]] || die "could not determine free space for ${STATE_DIR}"
    (( available_bytes >= required_bytes )) || die "insufficient free space: need ${required_bytes} bytes, have ${available_bytes}"
}

function unit_is_active {
    systemctl is-active --quiet "$1"
}

function stop_units {
    local unit

    log 'stopping watchdirs writers and query socket'
    for unit in "${UNITS[@]}"; do
        if unit_is_active "$unit"; then
            systemctl stop "$unit" || die "could not stop ${unit}"
        fi
    done
    services_quiesced=1
}

function restore_units {
    local unit

    (( services_quiesced )) || return 0
    for unit in \
        'watchdirs-collect.timer' \
        'watchdirs-prune.timer' \
        'watchdirs-vacuum.timer' \
        'watchdirs-query.socket'; do
        systemctl enable --now "$unit" || return 1
    done
}

function write_transformer {
    transformer_path=$( mktemp /run/watchdirs-v7-transformer.XXXXXX.py )
    chmod 0700 "$transformer_path"
    cat >"$transformer_path" <<'PYTHON'
import sqlite3
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
candidate_path = Path(sys.argv[2])
state_columns = (
    "parent_id", "depth", "apparent_bytes", "disk_bytes", "file_count",
    "dir_count", "error", "collapsed", "collapse_reason", "collapsed_dirs",
    "top_child_id", "top_child_disk_bytes",
)

def copy_database(source: sqlite3.Connection, candidate: sqlite3.Connection) -> None:
    candidate.executescript("""
        PRAGMA page_size=8192;
        PRAGMA auto_vacuum=FULL;
        PRAGMA application_id=0x57645273;
        PRAGMA foreign_keys=ON;
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
            root_path TEXT NOT NULL, status TEXT NOT NULL, notes TEXT, error TEXT
        );
        CREATE TABLE paths (id INTEGER PRIMARY KEY, path BLOB NOT NULL UNIQUE);
        CREATE TABLE snapshot_mounts (
            id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            mount_id INTEGER NOT NULL, parent_id INTEGER NOT NULL, major_minor TEXT NOT NULL,
            root BLOB NOT NULL, mount_point BLOB NOT NULL, filesystem_type TEXT NOT NULL, mount_source TEXT NOT NULL
        );
        CREATE TABLE directory_size_intervals (
            id INTEGER PRIMARY KEY, root_path TEXT NOT NULL,
            path_id INTEGER NOT NULL REFERENCES paths(id), valid_from_snapshot_id INTEGER NOT NULL,
            valid_to_snapshot_id INTEGER REFERENCES snapshots(id), parent_id INTEGER REFERENCES paths(id),
            depth INTEGER NOT NULL, apparent_bytes INTEGER NOT NULL, disk_bytes INTEGER NOT NULL,
            file_count INTEGER NOT NULL, dir_count INTEGER NOT NULL, error TEXT, collapsed INTEGER NOT NULL,
            collapse_reason TEXT, collapsed_dirs INTEGER, top_child_id INTEGER REFERENCES paths(id),
            top_child_disk_bytes INTEGER
        );
        CREATE TABLE directory_size_diagnostics (
            id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            path_id INTEGER NOT NULL REFERENCES paths(id), parent_id INTEGER REFERENCES paths(id),
            depth INTEGER NOT NULL, apparent_bytes INTEGER NOT NULL, disk_bytes INTEGER NOT NULL,
            file_count INTEGER NOT NULL, dir_count INTEGER NOT NULL, error TEXT, collapsed INTEGER NOT NULL,
            collapse_reason TEXT, collapsed_dirs INTEGER, top_child_id INTEGER REFERENCES paths(id),
            top_child_disk_bytes INTEGER, UNIQUE(snapshot_id, path_id)
        );
        CREATE INDEX intervals_path_idx ON directory_size_intervals(root_path, path_id, valid_from_snapshot_id);
        CREATE INDEX intervals_state_idx ON directory_size_intervals(valid_from_snapshot_id, valid_to_snapshot_id, root_path, path_id);
        CREATE INDEX intervals_parent_idx ON directory_size_intervals(parent_id) WHERE parent_id IS NOT NULL;
        CREATE INDEX intervals_top_child_idx ON directory_size_intervals(top_child_id) WHERE top_child_id IS NOT NULL;
        CREATE INDEX diagnostics_snapshot_idx ON directory_size_diagnostics(snapshot_id, path_id);
        CREATE INDEX diagnostics_path_gc_idx ON directory_size_diagnostics(path_id, parent_id, top_child_id);
    """)
    for table, columns in {
        "snapshots": ("id", "started_at", "finished_at", "root_path", "status", "notes", "error"),
        "paths": ("id", "path"),
        "snapshot_mounts": ("id", "snapshot_id", "mount_id", "parent_id", "major_minor", "root", "mount_point", "filesystem_type", "mount_source"),
    }.items():
        names = ", ".join(columns)
        rows = source.execute(f"SELECT {names} FROM {table} ORDER BY id")
        candidate.executemany(f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' for _ in columns)})", rows)

    active_by_root = {}
    roots = source.execute("SELECT DISTINCT root_path FROM snapshots WHERE status = 'complete' ORDER BY root_path")
    insert = f"INSERT INTO directory_size_intervals (root_path, path_id, valid_from_snapshot_id, valid_to_snapshot_id, {', '.join(state_columns)}) VALUES (?, ?, ?, NULL, {', '.join('?' for _ in state_columns)})"
    for (root_path,) in roots:
        active = active_by_root.setdefault(root_path, {})
        snapshots = source.execute("SELECT id FROM snapshots WHERE root_path = ? AND status = 'complete' ORDER BY id", (root_path,))
        for (snapshot_id,) in snapshots:
            current = {}
            rows = source.execute(f"SELECT path_id, {', '.join(state_columns)} FROM directory_sizes WHERE snapshot_id = ? ORDER BY path_id", (snapshot_id,))
            for row in rows:
                current[row[0]] = tuple(row[1:])
            for path_id, (start_id, prior) in list(active.items()):
                if path_id not in current:
                    candidate.execute("UPDATE directory_size_intervals SET valid_to_snapshot_id = ? WHERE root_path = ? AND path_id = ? AND valid_from_snapshot_id = ?", (snapshot_id, root_path, path_id, start_id))
                    del active[path_id]
            for path_id, state in current.items():
                prior = active.get(path_id)
                if prior is not None and prior[1] == state:
                    continue
                if prior is not None:
                    candidate.execute("UPDATE directory_size_intervals SET valid_to_snapshot_id = ? WHERE root_path = ? AND path_id = ? AND valid_from_snapshot_id = ?", (snapshot_id, root_path, path_id, prior[0]))
                candidate.execute(insert, (root_path, path_id, snapshot_id, *state))
                active[path_id] = (snapshot_id, state)
    diagnostic_insert = """
        INSERT INTO directory_size_diagnostics
        (snapshot_id, path_id, parent_id, depth, apparent_bytes, disk_bytes, file_count, dir_count,
         error, collapsed, collapse_reason, collapsed_dirs, top_child_id, top_child_disk_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    diagnostic_rows = source.execute(
        f"SELECT directory_sizes.snapshot_id, directory_sizes.path_id, "
        f"{', '.join('directory_sizes.' + column for column in state_columns)} FROM directory_sizes "
        "JOIN snapshots ON snapshots.id = directory_sizes.snapshot_id "
        "WHERE snapshots.status <> 'complete' ORDER BY snapshot_id, path_id"
    )
    candidate.executemany(
        diagnostic_insert,
        ((row[0], row[1], *row[2:]) for row in diagnostic_rows),
    )
    candidate.execute("PRAGMA user_version=7")
    candidate.commit()
    candidate.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    candidate.execute("VACUUM")
    candidate.commit()

source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
candidate = sqlite3.connect(candidate_path)
try:
    source.row_factory = sqlite3.Row
    copy_database(source, candidate)
finally:
    candidate.close()
    source.close()
PYTHON
}

function verify_cli {
    local -r database_path="$1"

    # assert: the deployed v7 CLI answers each canonical read query
    env -u HOME "$WATCHDIRS_BIN" snapshots --db "$database_path" --json >/dev/null \
        || die 'canonical v7 CLI query failed: snapshots'
    env -u HOME "$WATCHDIRS_BIN" top --db "$database_path" --snapshot latest --limit 1 --json >/dev/null \
        || die 'canonical v7 CLI query failed: top'
    env -u HOME "$WATCHDIRS_BIN" report --db "$database_path" --since 24h --limit 1 --json >/dev/null \
        || die 'canonical v7 CLI query failed: report'
    env -u HOME "$WATCHDIRS_BIN" diff --db "$database_path" --since 24h --limit 1 --json >/dev/null \
        || die 'canonical v7 CLI query failed: diff'
}

function cleanup {
    local exit_code=$?

    if (( exit_code != 0 && cutover_done )); then
        log 'verification failed after cutover; restoring the recoverable backup'
        rm -f -- "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
        mv -- "$backup_path" "$DB_PATH"
    fi
    if (( services_quiesced )); then
        restore_units || printf 'WARN: could not restore watchdirs units automatically\n' 1>&2
    fi
    [[ -z "$candidate_path" ]] || rm -rf -- "${candidate_path%/*}"
    [[ -z "$transformer_path" ]] || rm -f -- "$transformer_path"
    exit "$exit_code"
}

function main {
    local version

    # assert: this is a root-only host mutation
    (( EUID == 0 )) || die 'run as root'
    require_command systemctl
    require_command sqlite3
    require_command python3
    require_command flock
    require_command mktemp
    [[ -x "$WATCHDIRS_BIN" ]] || die "watchdirs executable is missing: ${WATCHDIRS_BIN}"
    [[ -f "$CONFIG_PATH" ]] || die "watchdirs configuration is missing: ${CONFIG_PATH}"
    [[ -d "$STATE_DIR" ]] || die "state directory is missing: ${STATE_DIR}"
    [[ -f "$DB_PATH" ]] || die "database is missing: ${DB_PATH}"

    exec 9>"$ROLLOUT_LOCK"
    flock -n 9 || die 'another v7 rollout is already running'
    trap cleanup EXIT

    assert_free_space "$DB_PATH"
    assert_database_integrity "$DB_PATH"
    version=$( database_version "$DB_PATH" )
    if [[ "$version" == '7' ]]; then
        assert_v7_shape "$DB_PATH"
        verify_cli "$DB_PATH"
        restore_units || die 'could not enable required watchdirs timers/socket'
        log 'database is already verified v7; no cutover was needed'
        return 0
    fi
    [[ "$version" == '6' ]] || die "refusing schema v${version}; only clean v6 to v7 cutover is supported"

    stop_units
    sqlite3 "$DB_PATH" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null \
        || die 'could not checkpoint the source database before backup'
    backup_path="${BACKUP_PREFIX}$(date -u +%Y%m%dT%H%M%SZ)"
    cp --reflink=auto --preserve=all -- "$DB_PATH" "$backup_path" || die 'could not create recoverable backup'
    assert_database_integrity "$backup_path"
    candidate_path=$( mktemp -d "${STATE_DIR}/.watchdirs-v7-candidate.XXXXXX" )
    write_transformer
    env -u HOME python3 "$transformer_path" "$backup_path" "${candidate_path}/watchdirs.sqlite3" || die 'v7 transformation failed'
    assert_v7_shape "${candidate_path}/watchdirs.sqlite3"
    verify_cli "${candidate_path}/watchdirs.sqlite3"

    mv -- "${candidate_path}/watchdirs.sqlite3" "$DB_PATH"
    rm -f -- "$DB_PATH-wal" "$DB_PATH-shm"
    cutover_done=1
    assert_v7_shape "$DB_PATH"
    verify_cli "$DB_PATH"
    restore_units || die 'could not enable required watchdirs timers/socket'
    rm -f -- "${BACKUP_PREFIX}"*
    log 'v7 cutover verified; temporary transformer and backup artifacts removed'
}

main "$@"
