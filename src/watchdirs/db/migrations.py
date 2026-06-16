from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
import sqlite3

from watchdirs.models import DirectoryAggregate, MountInfo, SnapshotMount, SnapshotRecord, SnapshotStatus


SCHEMA_VERSION = 4
INSERT_BATCH_SIZE = 10000
_COLLAPSE_COLUMN_DEFINITIONS = (
    ("collapsed", "INTEGER NOT NULL DEFAULT 0"),
    ("collapse_reason", "TEXT"),
    ("collapsed_dirs", "INTEGER"),
    ("top_child_id", "INTEGER REFERENCES paths(id)"),
    ("top_child_disk_bytes", "INTEGER"),
)


def initialize_database(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {user_version} is newer than supported version {SCHEMA_VERSION}"
        )
    if user_version == SCHEMA_VERSION:
        return
    if user_version in {1, 2}:
        raise RuntimeError(
            f"unsupported schema version {user_version}: upgrade to schema version 3 before applying schema version 4"
        )
    if user_version == 3:
        connection.execute("BEGIN")
        try:
            _migrate_v3_to_v4(connection)
        except Exception:
            connection.rollback()
            raise
        connection.commit()
        return

    schema_sql = resources.files("watchdirs.db").joinpath("schema.sql").read_text(encoding="utf-8")
    migration_script = "\n".join(
        (
            "BEGIN;",
            schema_sql,
            f"PRAGMA user_version = {SCHEMA_VERSION};",
            "COMMIT;",
        )
    )
    try:
        connection.executescript(migration_script)
    except Exception:
        connection.rollback()
        raise


def create_snapshot(
    connection: sqlite3.Connection,
    root_path,
    *,
    notes: str | None = None,
    commit: bool = True,
) -> SnapshotRecord:
    started_at = _timestamp_now()
    cursor = connection.execute(
        """
        INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error)
        VALUES (?, NULL, ?, ?, ?, NULL)
        """,
        (started_at, str(root_path), SnapshotStatus.FAILED.value, notes),
    )
    if commit:
        connection.commit()
    return SnapshotRecord(
        id=int(cursor.lastrowid),
        started_at=started_at,
        finished_at=None,
        root_path=root_path,
        status=SnapshotStatus.FAILED,
        notes=notes,
        error=None,
    )


def insert_directory_rows(
    connection,
    rows: list[DirectoryAggregate] | tuple[DirectoryAggregate, ...],
    *,
    commit: bool = True,
) -> None:
    if not rows:
        if commit:
            connection.commit()
        return

    sql = """
        INSERT INTO directory_sizes (
            snapshot_id,
            path_id,
            parent_id,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error,
            collapsed,
            collapse_reason,
            collapsed_dirs,
            top_child_id,
            top_child_disk_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cache: dict[bytes, int] = {}
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        connection.executemany(
            sql, [_directory_row_values(connection, cache, row) for row in batch]
        )
    if commit:
        connection.commit()


def _resolve_path_id(connection, cache: dict[bytes, int], path: bytes) -> int:
    cached = cache.get(path)
    if cached is not None:
        return cached
    row = connection.execute(
        "SELECT id FROM paths WHERE path = ?", (sqlite3.Binary(path),)
    ).fetchone()
    if row is not None:
        path_id = int(row[0])
    else:
        cursor = connection.execute(
            "INSERT INTO paths (path) VALUES (?)", (sqlite3.Binary(path),)
        )
        path_id = int(cursor.lastrowid)
    cache[path] = path_id
    return path_id


def insert_snapshot_mounts(
    connection: sqlite3.Connection,
    snapshot_id: int,
    mounts: list[MountInfo] | tuple[MountInfo, ...],
    *,
    commit: bool = True,
) -> None:
    if not mounts:
        if commit:
            connection.commit()
        return

    sql = """
        INSERT INTO snapshot_mounts (
            snapshot_id,
            mount_id,
            parent_id,
            major_minor,
            root,
            mount_point,
            filesystem_type,
            mount_source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    connection.executemany(
        sql,
        [_snapshot_mount_row_values(snapshot_id, mount) for mount in mounts],
    )
    if commit:
        connection.commit()


def load_snapshot_mounts(connection: sqlite3.Connection, snapshot_id: int) -> tuple[SnapshotMount, ...]:
    rows = connection.execute(
        """
        SELECT
            snapshot_id,
            mount_id,
            parent_id,
            major_minor,
            root,
            mount_point,
            filesystem_type,
            mount_source
        FROM snapshot_mounts
        WHERE snapshot_id = ?
        ORDER BY id
        """,
        (snapshot_id,),
    )
    return tuple(
        SnapshotMount(
            snapshot_id=int(row["snapshot_id"]),
            mount_id=int(row["mount_id"]),
            parent_id=int(row["parent_id"]),
            major_minor=row["major_minor"],
            root=bytes(row["root"]),
            mount_point=bytes(row["mount_point"]),
            filesystem_type=row["filesystem_type"],
            mount_source=row["mount_source"],
        )
        for row in rows
    )


def finalize_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *,
    status: SnapshotStatus,
    notes: str | None = None,
    error: str | None = None,
    commit: bool = True,
) -> SnapshotRecord:
    finished_at = _timestamp_now()
    connection.execute(
        """
        UPDATE snapshots
        SET finished_at = ?, status = ?, notes = ?, error = ?
        WHERE id = ?
        """,
        (finished_at, status.value, notes, error, snapshot_id),
    )
    if commit:
        connection.commit()
    row = connection.execute(
        """
        SELECT id, started_at, finished_at, root_path, status, notes, error
        FROM snapshots
        WHERE id = ?
        """,
        (snapshot_id,),
    ).fetchone()
    return SnapshotRecord(
        id=int(row["id"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        root_path=Path(row["root_path"]),
        status=SnapshotStatus(row["status"]),
        notes=row["notes"],
        error=row["error"],
    )


def _directory_row_values(
    connection, cache: dict[bytes, int], row: DirectoryAggregate
) -> tuple[object, ...]:
    path_id = _resolve_path_id(connection, cache, row.path)
    parent_id = (
        _resolve_path_id(connection, cache, row.parent_path)
        if row.parent_path is not None
        else None
    )
    top_child_id = (
        _resolve_path_id(connection, cache, row.top_child_path)
        if row.top_child_path is not None
        else None
    )
    return (
        row.snapshot_id,
        path_id,
        parent_id,
        row.depth,
        row.apparent_bytes,
        row.disk_bytes,
        row.file_count,
        row.dir_count,
        row.error,
        int(row.collapsed),
        row.collapse_reason,
        row.collapsed_dirs,
        top_child_id,
        row.top_child_disk_bytes,
    )


def _snapshot_mount_row_values(snapshot_id: int, mount: MountInfo) -> tuple[object, ...]:
    return (
        snapshot_id,
        mount.mount_id,
        mount.parent_id,
        mount.major_minor,
        sqlite3.Binary(mount.root),
        sqlite3.Binary(mount.mount_point),
        mount.filesystem_type,
        mount.mount_source,
    )


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    columns = _directory_sizes_table_info(connection)
    for column_name, definition in _COLLAPSE_COLUMN_DEFINITIONS:
        if column_name in columns:
            continue
        connection.execute(
            f"ALTER TABLE directory_sizes ADD COLUMN {column_name} {definition}"
        )
    _verify_directory_sizes_v4_shape(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _directory_sizes_table_info(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        row["name"]: row
        for row in connection.execute("PRAGMA table_info('directory_sizes')")
    }


def _verify_directory_sizes_v4_shape(connection: sqlite3.Connection) -> None:
    columns = _directory_sizes_table_info(connection)
    required_columns = {
        "collapsed",
        "collapse_reason",
        "collapsed_dirs",
        "top_child_id",
        "top_child_disk_bytes",
    }
    missing_columns = required_columns - set(columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise RuntimeError(f"collapse column verification failed: missing {missing}")

    collapsed = columns["collapsed"]
    if collapsed["type"].upper() != "INTEGER" or collapsed["notnull"] != 1 or collapsed["dflt_value"] != "0":
        raise RuntimeError("collapse column verification failed: collapsed must be INTEGER NOT NULL DEFAULT 0")

    for nullable_integer in ("collapsed_dirs", "top_child_id", "top_child_disk_bytes"):
        column = columns[nullable_integer]
        if column["type"].upper() != "INTEGER" or column["notnull"] != 0:
            raise RuntimeError(
                f"collapse column verification failed: {nullable_integer} must be a nullable INTEGER column"
            )

    collapse_reason = columns["collapse_reason"]
    if collapse_reason["type"].upper() != "TEXT" or collapse_reason["notnull"] != 0:
        raise RuntimeError("collapse column verification failed: collapse_reason must be a nullable TEXT column")

    foreign_keys = tuple(connection.execute("PRAGMA foreign_key_list('directory_sizes')"))
    has_top_child_fk = any(
        row["from"] == "top_child_id" and row["table"] == "paths" and row["to"] == "id"
        for row in foreign_keys
    )
    if not has_top_child_fk:
        raise RuntimeError("collapse column verification failed: top_child_id must reference paths(id)")
