#!/usr/bin/env bash
set -euo pipefail

function die {
    local -r message="${1:-}"
    local -ri code="${2:-1}"

    echo "FATAL: ${message}"
    exit "$code"
} 1>&2

function log_info {
    local -r message="$1"

    echo "INFO: ${message}"
} 1>&2

function usage {
    cat <<'EOF'
Usage: scripts/install-systemd-units.sh [OPTIONS]

Install the watchdirs launcher from this checkout into /usr/local/bin/watchdirs,
install systemd units into /etc/systemd/system, reload systemd, and verify that
Python bytecode writes are disabled for root-run services.

Options:
  --clean-pycache         Remove known __pycache__ directories from this checkout after install.
  --restart-query-socket  Restart watchdirs-query.socket after daemon-reload.
  -h, --help              Show this help.
EOF
}

function sudo_command {
    # code
    if (( EUID == 0 )); then
        "$@"
        return
    fi

    sudo "$@"
}

function install_units {
    # args
    local -r repo_root="$1"
    local -r systemd_dir="$2"

    # arrays
    local -a unit_files=(
        'watchdirs-collect.service'
        'watchdirs-collect.timer'
        'watchdirs-prune.service'
        'watchdirs-prune.timer'
        'watchdirs-vacuum.service'
        'watchdirs-vacuum.timer'
        'watchdirs-query.socket'
        'watchdirs-query@.service'
    )

    # vars
    local unit_file
    local source_path
    local target_path

    # code
    for unit_file in "${unit_files[@]}"; do
        source_path="${repo_root}/ops/systemd/${unit_file}"
        target_path="${systemd_dir}/${unit_file}"

        # assert: repo-owned unit file exists
        [[ -f "$source_path" ]] || die "missing unit file: ${source_path}"

        log_info "install ${source_path} -> ${target_path}"
        sudo_command install --mode '0644' "$source_path" "$target_path"
    done
}

function install_launcher {
    # args
    local -r repo_root="$1"

    # consts
    local -r launcher_path='/usr/local/bin/watchdirs'

    # vars
    local launcher_tmp

    # code
    launcher_tmp=$( mktemp ) || die 'failed to create temporary launcher file'
    {
        printf '#!/usr/bin/env bash\n'
        printf 'set -euo pipefail\n'
        printf 'export PYTHONDONTWRITEBYTECODE=1\n'
        # The generated launcher must expand any caller PYTHONPATH at runtime.
        # shellcheck disable=SC2016
        printf 'export PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}"\n' "${repo_root}/src"
        printf 'exec /usr/bin/python3 -m watchdirs "$@"\n'
    } > "$launcher_tmp" || die "failed to write temporary launcher: ${launcher_tmp}"

    log_info "install checkout launcher -> ${launcher_path}"
    if ! sudo_command install --mode '0755' "$launcher_tmp" "$launcher_path"; then
        rm -- "$launcher_tmp"
        die "failed to install checkout launcher: ${launcher_path}"
    fi
    rm -- "$launcher_tmp" || die "failed to remove temporary launcher: ${launcher_tmp}"
}

function clean_pycache {
    # args
    local -r repo_root="$1"

    # arrays
    local -a pycache_dirs=(
        "${repo_root}/src/watchdirs/__pycache__"
        "${repo_root}/src/watchdirs/bench/__pycache__"
        "${repo_root}/src/watchdirs/collect/__pycache__"
        "${repo_root}/src/watchdirs/db/__pycache__"
        "${repo_root}/src/watchdirs/diagnostics/__pycache__"
        "${repo_root}/src/watchdirs/reporting/__pycache__"
        "${repo_root}/tests/__pycache__"
    )

    # vars
    local pycache_dir

    # code
    for pycache_dir in "${pycache_dirs[@]}"; do
        if [[ -e "$pycache_dir" ]]; then
            log_info "remove generated cache: ${pycache_dir}"
            sudo_command rm --recursive --force -- "$pycache_dir"
        fi
    done
}

function verify_python_bytecode_disabled {
    # arrays
    local -a unit_names=(
        'watchdirs-collect.service'
        'watchdirs-prune.service'
        'watchdirs-vacuum.service'
        'watchdirs-query@.service'
    )

    # vars
    local unit_name
    local unit_text

    # code
    for unit_name in "${unit_names[@]}"; do
        unit_text=$( systemctl cat "$unit_name" )

        # assert: installed unit disables Python bytecode writes
        grep --fixed-strings --quiet 'Environment=PYTHONDONTWRITEBYTECODE=1' <<< "$unit_text" \
            || die "installed unit is missing PYTHONDONTWRITEBYTECODE=1: ${unit_name}"
    done
}

function main {
    # consts
    local -r script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    local -r repo_root="$(cd -- "${script_dir}/.." && pwd)"
    local -r systemd_dir='/etc/systemd/system'

    # flags
    local -i clean_cache=0 restart_query_socket=0

    # code
    while (( $# > 0 )); do
        case "$1" in
            --clean-pycache)
                clean_cache=1
                ;;
            --restart-query-socket)
                restart_query_socket=1
                ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                die "unknown argument: $1" 2
                ;;
        esac
        shift
    done

    # assert: script is running from a watchdirs checkout
    [[ -d "${repo_root}/ops/systemd" ]] || die "ops/systemd not found under ${repo_root}"
    [[ -x "${repo_root}/watchdirs" ]] || die "watchdirs launcher not found or not executable under ${repo_root}"

    install_launcher "$repo_root"
    install_units "$repo_root" "$systemd_dir"

    log_info 'reload systemd manager configuration'
    sudo_command systemctl daemon-reload

    verify_python_bytecode_disabled

    if (( restart_query_socket )); then
        log_info 'restart watchdirs-query.socket'
        sudo_command systemctl restart 'watchdirs-query.socket'
    fi

    if (( clean_cache )); then
        clean_pycache "$repo_root"
    fi

    log_info 'done'
}

main "$@"
