#!/usr/bin/env bash
set -euo pipefail
umask 0077

# One-time v7 cutover. The deployed watchdirs executable must already speak v7.
# This script deliberately has no v6 runtime fallback: a failed verification
# leaves the original database in place and preserves the cutover backup.

declare -r STATE_DIR='/var/lib/watchdirs'
declare -r DB_PATH="${STATE_DIR}/watchdirs.sqlite3"
declare -r CONFIG_PATH='/etc/watchdirs/watchdirs.toml'
declare -r WATCHDIRS_BIN='/usr/local/bin/watchdirs'
declare -r ROLLOUT_LOCK='/run/lock/watchdirs-v7-rollout.lock'
declare -r OPERATION_LOCK="${DB_PATH}.lock"
declare -r BACKUP_PREFIX="${DB_PATH}.v7-backup-"
declare -ri VACUUM_PEAK_RESERVE_BYTES=134217728
declare backup_path=''
declare candidate_path=''
declare transformer_path=''
declare -i services_quiesced=0
declare -i cutover_done=0

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
    # args
    local -r database_path="$1"

    # vars
    local version interval_table diagnostic_table legacy_table boundary_foreign_key index_name

    version=$( database_version "$database_path" )
    [[ "$version" == '7' ]] || die "expected schema v7, got v${version} in ${database_path}"
    interval_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_size_intervals';" )
    [[ "$interval_table" == '1' ]] || die "v7 interval table is missing from ${database_path}"
    diagnostic_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_size_diagnostics';" )
    [[ "$diagnostic_table" == '1' ]] || die "v7 diagnostic table is missing from ${database_path}"
    legacy_table=$( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='directory_sizes';" )
    [[ "$legacy_table" == '0' ]] || die "legacy directory_sizes table remains in ${database_path}"
    boundary_foreign_key=$( sqlite_scalar "$database_path" "SELECT count(*) FROM pragma_foreign_key_list('directory_size_intervals') WHERE \"from\" = 'valid_to_snapshot_id';" )
    [[ "$boundary_foreign_key" == '0' ]] || die "v7 interval end boundary must not reference snapshots metadata"
    for index_name in \
        'directory_size_intervals_path_idx' \
        'directory_size_intervals_snapshot_idx' \
        'directory_size_intervals_path_gc_idx' \
        'directory_size_diagnostics_snapshot_idx' \
        'directory_size_diagnostics_path_gc_idx' \
        'snapshot_mounts_snapshot_idx' \
        'snapshot_mounts_snapshot_mount_point_idx' \
        'snapshot_mounts_snapshot_domain_idx'; do
        [[ $( sqlite_scalar "$database_path" "SELECT count(*) FROM sqlite_master WHERE type = 'index' AND name = '${index_name}';" ) == '1' ]] \
            || die "canonical v7 index is missing: ${index_name}"
    done
    assert_database_integrity "$database_path"
}

function assert_free_space {
    # args
    local -r database_path="$1"

    # vars
    local database_bytes required_bytes available_bytes

    # code
    database_bytes=$( stat --format='%s' "$database_path" )
    # assert: room for the backup, candidate, candidate VACUUM copy, and WAL growth
    required_bytes=$(( database_bytes * 4 + VACUUM_PEAK_RESERVE_BYTES ))
    available_bytes=$( df --output=avail -B1 "$STATE_DIR" | tail -n 1 | tr -d ' ' )
    [[ "$available_bytes" =~ ^[0-9]+$ ]] || die "could not determine free space for ${STATE_DIR}"
    (( available_bytes >= required_bytes )) || die "insufficient free space: need ${required_bytes} bytes, have ${available_bytes}"
}

function unit_is_active {
    # args
    local -r unit_name="$1"

    # result: true when the requested unit is active
    systemctl is-active --quiet "$unit_name"
}

function stop_units {
    # vars
    local unit

    # code
    log 'stopping watchdirs writers and query socket'
    for unit in \
        'watchdirs-collect.timer' \
        'watchdirs-prune.timer' \
        'watchdirs-vacuum.timer' \
        'watchdirs-collect.service' \
        'watchdirs-prune.service' \
        'watchdirs-vacuum.service'; do
        systemctl stop "$unit" || die "could not stop ${unit}"
    done
    systemctl stop 'watchdirs-query.socket' || die 'could not stop watchdirs-query.socket'
    while IFS= read -r unit || [[ -n "$unit" ]]; do
        [[ -n "$unit" ]] || continue
        systemctl stop "$unit" || die "could not stop ${unit}"
    done < <(systemctl list-units --all --plain --no-legend --full 'watchdirs-query@*.service' | awk '{print $1}')
    if systemctl list-units --state=active --plain --no-legend --full 'watchdirs-query@*.service' | awk 'NF { found = 1 } END { exit !found }'; then
        die 'watchdirs query workers remain active after socket quiescence'
    fi
    services_quiesced=1
}

function restore_units {
    # vars
    local unit

    # code
    for unit in \
        'watchdirs-collect.timer' \
        'watchdirs-prune.timer' \
        'watchdirs-vacuum.timer' \
        'watchdirs-query.socket'; do
        systemctl enable --now "$unit" || return 1
    done
}

function checkpoint_source_database {
    # args
    local -r database_path="$1"

    # vars
    local checkpoint_result busy_frames log_frames checkpointed_frames

    # code
    checkpoint_result=$( sqlite3 "$database_path" 'PRAGMA wal_checkpoint(TRUNCATE);' ) \
        || die 'could not checkpoint the source database before backup'
    IFS='|' read -r busy_frames log_frames checkpointed_frames <<<"$checkpoint_result"
    [[ "$busy_frames" =~ ^[0-9]+$ && "$log_frames" =~ ^[0-9]+$ && "$checkpointed_frames" =~ ^[0-9]+$ ]] \
        || die "unexpected wal_checkpoint result: ${checkpoint_result}"
    (( busy_frames == 0 && log_frames == 0 && checkpointed_frames == 0 )) \
        || die "WAL is not fully checkpointed: ${checkpoint_result}"
}

function secure_database_files {
    # args
    local -r database_path="$1"

    # vars
    local suffix file_path

    # code
    for suffix in '' '-wal' '-shm'; do
        file_path="${database_path}${suffix}"
        [[ -e "$file_path" ]] || continue
        chown root:root -- "$file_path" || die "could not set owner on ${file_path}"
        chmod 0600 -- "$file_path" || die "could not set mode on ${file_path}"
    done
}

function remove_database_sidecars {
    # args
    local -r database_path="$1"

    rm -f -- "${database_path}-wal" "${database_path}-shm"
}

function write_transformer {
    transformer_path=$( mktemp /run/watchdirs-v7-transformer.XXXXXX.py )
    chmod 0700 "$transformer_path"
    cat >"$transformer_path" <<'PYTHON'
import sqlite3
import sys
from pathlib import Path

from watchdirs.db.connection import open_connection
from watchdirs.db.migrations import SCHEMA_VERSION, initialize_database

source_path = Path(sys.argv[1])
candidate_path = Path(sys.argv[2])

if SCHEMA_VERSION != 7:
    raise RuntimeError(f"packaged watchdirs schema must be v7, got v{SCHEMA_VERSION}")


def table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def state_columns(source: sqlite3.Connection, candidate: sqlite3.Connection) -> tuple[str, ...]:
    source_columns = tuple(
        column
        for column in table_columns(source, "directory_sizes")
        if column not in {"id", "snapshot_id", "path_id"}
    )
    candidate_columns = tuple(
        column
        for column in table_columns(candidate, "directory_size_intervals")
        if column not in {"id", "root_path", "path_id", "valid_from_snapshot_id", "valid_to_snapshot_id"}
    )
    if source_columns != candidate_columns:
        raise RuntimeError(
            "v6 source aggregate columns do not match packaged v7 interval columns: "
            f"source={source_columns!r} candidate={candidate_columns!r}"
        )
    return source_columns

def copy_database(source: sqlite3.Connection, candidate: sqlite3.Connection) -> None:
    initialize_database(candidate)
    aggregate_columns = state_columns(source, candidate)
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
    insert = f"INSERT INTO directory_size_intervals (root_path, path_id, valid_from_snapshot_id, valid_to_snapshot_id, {', '.join(aggregate_columns)}) VALUES (?, ?, ?, NULL, {', '.join('?' for _ in aggregate_columns)})"
    for (root_path,) in roots:
        active = active_by_root.setdefault(root_path, {})
        snapshots = source.execute("SELECT id FROM snapshots WHERE root_path = ? AND status = 'complete' ORDER BY id", (root_path,))
        for (snapshot_id,) in snapshots:
            current = {}
            rows = source.execute(f"SELECT path_id, {', '.join(aggregate_columns)} FROM directory_sizes WHERE snapshot_id = ? ORDER BY path_id", (snapshot_id,))
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
        f"{', '.join('directory_sizes.' + column for column in aggregate_columns)} FROM directory_sizes "
        "JOIN snapshots ON snapshots.id = directory_sizes.snapshot_id "
        "WHERE snapshots.status <> 'complete' ORDER BY snapshot_id, path_id"
    )
    candidate.executemany(
        diagnostic_insert,
        ((row[0], row[1], *row[2:]) for row in diagnostic_rows),
    )
    candidate.commit()
    candidate.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    candidate.execute("VACUUM")
    candidate.commit()

source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
candidate = open_connection(candidate_path)
try:
    source.row_factory = sqlite3.Row
    copy_database(source, candidate)
finally:
    candidate.close()
    source.close()
PYTHON
}

function verify_cli {
    # args
    local -r database_path="$1"

    # code
    # assert: the deployed v7 CLI answers each canonical read query
    env -u HOME "$WATCHDIRS_BIN" snapshots --db "$database_path" --json >/dev/null \
        || die 'canonical v7 CLI query failed: snapshots'
    env -u HOME "$WATCHDIRS_BIN" top --db "$database_path" --snapshot latest --limit 1 --json >/dev/null \
        || die 'canonical v7 CLI query failed: top'
    if has_usable_pair "$database_path"; then
        env -u HOME "$WATCHDIRS_BIN" report --db "$database_path" --since 24h --limit 1 --json >/dev/null \
            || die 'canonical v7 CLI query failed: report'
        env -u HOME "$WATCHDIRS_BIN" diff --db "$database_path" --since 24h --limit 1 --json >/dev/null \
            || die 'canonical v7 CLI query failed: diff'
    fi
}

function has_usable_pair {
    # args
    local -r database_path="$1"

    # vars
    local result

    # code
    if result=$( env -u HOME python3 - "$database_path" 2>&1 <<'PYTHON'
import sys

from watchdirs.db.connection import open_readonly_connection
from watchdirs.reporting.errors import ReportError
from watchdirs.reporting.pairs import resolve_snapshot_pairs

connection = open_readonly_connection(sys.argv[1])
try:
    resolve_snapshot_pairs(connection, since="24h")
except ReportError as exc:
    if exc.code == "no_snapshot_pairs":
        raise SystemExit(1)
    raise
finally:
    connection.close()
PYTHON
    ); then
        return 0
    fi
    [[ -z "$result" ]] && return 1
    die "could not determine whether a usable snapshot pair exists: ${result}"
}

function cleanup {
    # vars
    local exit_code=$?

    # code
    if (( exit_code != 0 && cutover_done )); then
        log 'verification failed after cutover; restoring the recoverable backup'
        rm -f -- "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
        mv -- "$backup_path" "$DB_PATH"
        secure_database_files "$DB_PATH"
    fi
    if (( services_quiesced )); then
        restore_units || printf 'WARN: could not restore watchdirs units automatically\n' 1>&2
    fi
    [[ -z "$candidate_path" ]] || rm -rf -- "${candidate_path%/*}"
    [[ -z "$transformer_path" ]] || rm -f -- "$transformer_path"
    exit "$exit_code"
}

function main {
    # vars
    local version

    # code
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

    # assert: serialize concurrent v7 rollouts independently of database writers
    exec 8>>"$ROLLOUT_LOCK"
    flock -n 8 || die 'another v7 rollout is already running'
    # assert: hold the same nonblocking writer lock used by watchdirs operations
    exec 9>>"$OPERATION_LOCK"
    flock -n 9 || die "another watchdirs writer is already active: ${OPERATION_LOCK}"
    trap cleanup EXIT

    assert_free_space "$DB_PATH"
    secure_database_files "$DB_PATH"
    assert_database_integrity "$DB_PATH"
    version=$( database_version "$DB_PATH" )
    if [[ "$version" == '7' ]]; then
        assert_v7_shape "$DB_PATH"
        secure_database_files "$DB_PATH"
        verify_cli "$DB_PATH"
        secure_database_files "$DB_PATH"
        restore_units || die 'could not enable required watchdirs timers/socket'
        log 'database is already verified v7; no cutover was needed'
        return 0
    fi
    [[ "$version" == '6' ]] || die "refusing schema v${version}; only clean v6 to v7 cutover is supported"

    stop_units
    checkpoint_source_database "$DB_PATH"
    remove_database_sidecars "$DB_PATH"
    backup_path="${BACKUP_PREFIX}$(date -u +%Y%m%dT%H%M%SZ)"
    cp --reflink=auto --preserve=all -- "$DB_PATH" "$backup_path" || die 'could not create recoverable backup'
    secure_database_files "$backup_path"
    assert_database_integrity "$backup_path"
    candidate_path=$( mktemp -d "${STATE_DIR}/.watchdirs-v7-candidate.XXXXXX" )
    chown root:root -- "$candidate_path" || die "could not set owner on ${candidate_path}"
    chmod 0700 -- "$candidate_path" || die "could not set mode on ${candidate_path}"
    write_transformer
    env -u HOME python3 "$transformer_path" "$backup_path" "${candidate_path}/watchdirs.sqlite3" || die 'v7 transformation failed'
    remove_database_sidecars "${candidate_path}/watchdirs.sqlite3"
    secure_database_files "${candidate_path}/watchdirs.sqlite3"
    assert_v7_shape "${candidate_path}/watchdirs.sqlite3"
    verify_cli "${candidate_path}/watchdirs.sqlite3"

    mv -- "${candidate_path}/watchdirs.sqlite3" "$DB_PATH"
    remove_database_sidecars "$DB_PATH"
    secure_database_files "$DB_PATH"
    cutover_done=1
    assert_v7_shape "$DB_PATH"
    verify_cli "$DB_PATH"
    restore_units || die 'could not enable required watchdirs timers/socket'
    rm -f -- "${BACKUP_PREFIX}"*
    log 'v7 cutover verified; temporary transformer and backup artifacts removed'
}

main "$@"
