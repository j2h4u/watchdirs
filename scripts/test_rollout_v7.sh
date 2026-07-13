#!/usr/bin/env bash
set -euo pipefail
umask 0077

REPO_ROOT="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )/.." && pwd )"
declare -r REPO_ROOT
declare -r ROLLOUT_SCRIPT="${REPO_ROOT}/scripts/rollout_v7.sh"
TEMP_ROOT="$( mktemp -d )"
declare -r TEMP_ROOT

function cleanup {
    rm -rf -- "$TEMP_ROOT"
}

trap cleanup EXIT HUP INT TERM

bash -n "$ROLLOUT_SCRIPT"
shellcheck "$ROLLOUT_SCRIPT" "$0"

declare -r TRANSFORMER="${TEMP_ROOT}/transformer.py"
awk '
    /cat >.*transformer_path.*PYTHON/ { found = 1; next }
    found && $0 == "PYTHON" { exit }
    found { print }
' "$ROLLOUT_SCRIPT" >"$TRANSFORMER"

declare -r SOURCE_DB="${TEMP_ROOT}/v6.sqlite3"
declare -r MALFORMED_DB="${TEMP_ROOT}/malformed-v6.sqlite3"
declare -r CANDIDATE_DB="${TEMP_ROOT}/candidate/watchdirs.sqlite3"
declare -r MALFORMED_CANDIDATE="${TEMP_ROOT}/malformed-candidate/watchdirs.sqlite3"
declare -r MALFORMED_STDERR="${TEMP_ROOT}/malformed-v6.stderr"

PYTHONPATH="${REPO_ROOT}/src" python3 - "$SOURCE_DB" "$MALFORMED_DB" <<'PYTHON'
import sqlite3
import sys
from pathlib import Path

source_path, malformed_path = map(Path, sys.argv[1:])

v6_schema = """
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    root_path TEXT NOT NULL, status TEXT NOT NULL, notes TEXT, error TEXT
);
CREATE TABLE paths (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE);
CREATE TABLE directory_sizes (
    id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    path_id INTEGER NOT NULL REFERENCES paths(id), parent_id INTEGER REFERENCES paths(id),
    depth INTEGER NOT NULL, apparent_bytes INTEGER NOT NULL, disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL, dir_count INTEGER NOT NULL, error TEXT,
    collapsed INTEGER NOT NULL DEFAULT 0, collapse_reason TEXT, collapsed_dirs INTEGER,
    top_child_id INTEGER REFERENCES paths(id), top_child_disk_bytes INTEGER
);
CREATE TABLE snapshot_mounts (
    id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    mount_id INTEGER NOT NULL, parent_id INTEGER NOT NULL, major_minor TEXT NOT NULL,
    root BLOB NOT NULL, mount_point BLOB NOT NULL, filesystem_type TEXT NOT NULL,
    mount_source TEXT NOT NULL
);
PRAGMA user_version = 6;
"""

state = ("parent_id", "depth", "apparent_bytes", "disk_bytes", "file_count", "dir_count",
         "error", "collapsed", "collapse_reason", "collapsed_dirs", "top_child_id",
         "top_child_disk_bytes")

connection = sqlite3.connect(source_path)
connection.executescript(v6_schema)
connection.executemany(
    "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
    [
        (1, "2026-07-13T00:00:00Z", "2026-07-13T00:00:01Z", "/synthetic", "complete", None, None),
        (2, "2026-07-13T01:00:00Z", "2026-07-13T01:00:01Z", "/synthetic", "complete", None, None),
        (3, "2026-07-13T02:00:00Z", "2026-07-13T02:00:01Z", "/synthetic", "partial", None, "permission denied"),
    ],
)
connection.executemany("INSERT INTO paths VALUES (?, ?)", [(1, "/synthetic"), (2, "/synthetic/child"), (3, "/synthetic/gone"), (4, "/synthetic/diagnostic")])
rows = []
for row_id, snapshot_id, path_id, values in [
    (1, 1, 1, (None, 0, 100, 200, 10, 1, None, 0, None, None, None, None)),
    (2, 1, 2, (1, 1, 10, 20, 2, 1, None, 0, None, None, None, None)),
    (3, 1, 3, (1, 1, 30, 40, 3, 1, None, 0, None, None, None, None)),
    (4, 2, 1, (None, 0, 100, 200, 10, 1, None, 0, None, None, None, None)),
    (5, 2, 2, (1, 1, 30, 40, 3, 1, None, 0, None, None, None, None)),
    (6, 3, 4, (1, 1, 7, 8, 1, 1, "diagnostic", 1, "permission", 2, 2, 8)),
]:
    rows.append((row_id, snapshot_id, path_id, *values))
connection.executemany(
    "INSERT INTO directory_sizes (id, snapshot_id, path_id, " + ", ".join(state) + ") VALUES (" + ",".join("?" for _ in range(3 + len(state))) + ")",
    rows,
)
connection.commit()
connection.close()

malformed = sqlite3.connect(malformed_path)
malformed.executescript(
    """
    CREATE TABLE snapshots (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
        root_path TEXT NOT NULL, status TEXT NOT NULL, notes TEXT, error TEXT);
    CREATE TABLE paths (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE);
    CREATE TABLE directory_sizes (id INTEGER PRIMARY KEY, snapshot_id INTEGER, path_id INTEGER);
    PRAGMA user_version = 6;
    """
)
malformed.execute("INSERT INTO snapshots VALUES (1, 'now', NULL, '/synthetic', 'complete', NULL, NULL)")
malformed.commit()
malformed.close()
PYTHON

SOURCE_HASH="$( sha256sum "$MALFORMED_DB" )"
declare -r SOURCE_HASH
if PYTHONPATH="${REPO_ROOT}/src" python3 "$TRANSFORMER" "$MALFORMED_DB" "$MALFORMED_CANDIDATE" 2>"$MALFORMED_STDERR"; then
    printf 'malformed v6 conversion unexpectedly succeeded\n' >&2
    cat "$MALFORMED_STDERR" >&2
    exit 1
fi
[[ "$( sha256sum "$MALFORMED_DB" )" == "$SOURCE_HASH" ]]

PYTHONPATH="${REPO_ROOT}/src" python3 "$TRANSFORMER" "$SOURCE_DB" "$CANDIDATE_DB"

PYTHONPATH="${REPO_ROOT}/src" python3 - "$CANDIDATE_DB" <<'PYTHON'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
connection.execute("PRAGMA foreign_keys = ON")
assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
assert "directory_sizes" not in tables
assert {"directory_size_intervals", "directory_size_diagnostics"} <= tables
foreign_keys = connection.execute("PRAGMA foreign_key_list(directory_size_intervals)").fetchall()
assert not any(row[3] in {"valid_from_snapshot_id", "valid_to_snapshot_id"} for row in foreign_keys)
assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
intervals = connection.execute(
    "SELECT path_id, valid_from_snapshot_id, valid_to_snapshot_id, apparent_bytes, disk_bytes "
    "FROM directory_size_intervals ORDER BY path_id, valid_from_snapshot_id"
).fetchall()
assert intervals == [
    (1, 1, None, 100, 200),
    (2, 1, 2, 10, 20),
    (2, 2, None, 30, 40),
    (3, 1, 2, 30, 40),
]
diagnostic = connection.execute(
    "SELECT snapshot_id, path_id, apparent_bytes, disk_bytes, error, collapsed, collapse_reason, "
    "collapsed_dirs, top_child_id, top_child_disk_bytes FROM directory_size_diagnostics"
).fetchall()
assert diagnostic == [(3, 4, 7, 8, "diagnostic", 1, "permission", 2, 2, 8)]
connection.close()
PYTHON

printf 'rollout v7 smoke test passed\n'
