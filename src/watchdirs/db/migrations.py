from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import cast

from watchdirs.models import DirectoryAggregate, MountInfo, SnapshotMount, SnapshotRecord, SnapshotStatus

SCHEMA_VERSION = 4
SCHEMA_VERSION_V3 = 3
INSERT_BATCH_SIZE = 10000
_COLLAPSE_COLUMN_DEFINITIONS = (
    ("collapsed", "INTEGER NOT NULL DEFAULT 0"),
    ("collapse_reason", "TEXT"),
    ("collapsed_dirs", "INTEGER"),
    ("top_child_id", "INTEGER REFERENCES paths(id)"),
    ("top_child_disk_bytes", "INTEGER"),
)


def initialize_database(connection: sqlite3.Connection) -> None:
    user_version_row = cast(
        sqlite3.Row | tuple[object, ...] | None, connection.execute("PRAGMA user_version").fetchone()
    )
    if user_version_row is None:
        raise RuntimeError("sqlite did not return a user_version row")
    user_version = int(cast(int | str, user_version_row[0]))
    if user_version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema version {user_version} is newer than supported version {SCHEMA_VERSION}")
    if user_version == SCHEMA_VERSION:
        return
    if user_version in {1, 2}:
        raise RuntimeError(
            f"unsupported schema version {user_version}: upgrade to schema version 3 before applying schema version 4"
        )
    if user_version == SCHEMA_VERSION_V3:
        connection.execute("BEGIN")
        try:
            _migrate_v3_to_v4(connection)
        except Exception:
            connection.rollback()
            raise
        connection.commit()
        return

    schema_sql = resources.files("watchdirs.db").joinpath("schema.sql").read_text(encoding="utf-8")
    migration_script = "\n".join((
        "BEGIN;",
        schema_sql,
        f"PRAGMA user_version = {SCHEMA_VERSION};",
        "COMMIT;",
    ))
    try:
        connection.executescript(migration_script)
    except Exception:
        connection.rollback()
        raise


def create_snapshot(
    connection: sqlite3.Connection,
    root_path: Path,
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
    if cursor.lastrowid is None:
        raise RuntimeError("sqlite did not return a snapshot id")
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
    connection: sqlite3.Connection,
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
        connection.executemany(sql, [_directory_row_values(connection, cache, row) for row in batch])
    if commit:
        connection.commit()


def _resolve_path_id(connection: sqlite3.Connection, cache: dict[bytes, int], path: bytes) -> int:
    cached = cache.get(path)
    if cached is not None:
        return cached
    row = cast(
        sqlite3.Row | None,
        connection.execute("SELECT id FROM paths WHERE path = ?", (sqlite3.Binary(path),)).fetchone(),
    )
    if row is not None:
        path_value = cast(int | str, row[0])
        if path_value is None:
            raise RuntimeError(f"path id lookup returned NULL for path: {path!r}")
        path_id = int(path_value)
    else:
        cursor = connection.execute("INSERT INTO paths (path) VALUES (?)", (sqlite3.Binary(path),))
        if cursor.lastrowid is None:
            raise RuntimeError(f"sqlite did not return a path id for path: {path!r}")
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
    rows = cast(
        list[sqlite3.Row],
        connection.execute(
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
        ).fetchall(),
    )
    return tuple(
        SnapshotMount(
            snapshot_id=int(cast(int | str, row["snapshot_id"])),
            mount_id=int(cast(int | str, row["mount_id"])),
            parent_id=int(cast(int | str, row["parent_id"])),
            major_minor=cast(str, row["major_minor"]),
            root=cast(bytes, row["root"]),
            mount_point=cast(bytes, row["mount_point"]),
            filesystem_type=cast(str, row["filesystem_type"]),
            mount_source=cast(str, row["mount_source"]),
        )
        for row in rows
    )


def finalize_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    *args: object,
    **kwargs: object,
) -> SnapshotRecord:
    if args:
        raise TypeError("finalize_snapshot() takes 2 positional arguments but more were given")
    status = _coerce_snapshot_status(kwargs.pop("status", None))
    notes = kwargs.pop("notes", None)
    error = kwargs.pop("error", None)
    commit = bool(kwargs.pop("commit", True))
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"finalize_snapshot() got unexpected keyword arguments: {unexpected}")
    return _finalize_snapshot(
        connection,
        snapshot_id,
        _FinalizeSnapshotOptions(
            status=status,
            notes=notes if notes is None or isinstance(notes, str) else str(notes),
            error=error if error is None or isinstance(error, str) else str(error),
            commit=commit,
        ),
    )


def _finalize_snapshot(
    connection: sqlite3.Connection,
    snapshot_id: int,
    options: _FinalizeSnapshotOptions,
) -> SnapshotRecord:
    finished_at = _timestamp_now()
    connection.execute(
        """
        UPDATE snapshots
        SET finished_at = ?, status = ?, notes = ?, error = ?
        WHERE id = ?
        """,
        (finished_at, options.status.value, options.notes, options.error, snapshot_id),
    )
    if options.commit:
        connection.commit()
    row = cast(
        sqlite3.Row | None,
        connection.execute(
            """
            SELECT id, started_at, finished_at, root_path, status, notes, error
            FROM snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone(),
    )
    if row is None:
        raise RuntimeError(f"snapshot id {snapshot_id} was not found after update")
    return SnapshotRecord(
        id=int(cast(int | str, row["id"])),
        started_at=cast(str, row["started_at"]),
        finished_at=cast(str | None, row["finished_at"]),
        root_path=Path(cast(str, row["root_path"])),
        status=SnapshotStatus(cast(str, row["status"])),
        notes=cast(str | None, row["notes"]),
        error=cast(str | None, row["error"]),
    )


@dataclass(frozen=True, slots=True)
class _FinalizeSnapshotOptions:
    status: SnapshotStatus
    notes: str | None
    error: str | None
    commit: bool


def _coerce_snapshot_status(raw_value: object) -> SnapshotStatus:
    if isinstance(raw_value, SnapshotStatus):
        return raw_value
    if isinstance(raw_value, str):
        return SnapshotStatus(raw_value)
    raise TypeError("finalize_snapshot() missing required keyword argument: 'status'")


def _directory_row_values(
    connection: sqlite3.Connection,
    cache: dict[bytes, int],
    row: DirectoryAggregate,
) -> tuple[object, ...]:
    path_id = _resolve_path_id(connection, cache, row.path)
    parent_id = _resolve_path_id(connection, cache, row.parent_path) if row.parent_path is not None else None
    top_child_id = _resolve_path_id(connection, cache, row.top_child_path) if row.top_child_path is not None else None
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
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _migrate_v3_to_v4(connection: sqlite3.Connection) -> None:
    columns = _directory_sizes_table_info(connection)
    for column_name, definition in _COLLAPSE_COLUMN_DEFINITIONS:
        if column_name in columns:
            continue
        connection.execute(f"ALTER TABLE directory_sizes ADD COLUMN {column_name} {definition}")
    _verify_directory_sizes_v4_shape(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _directory_sizes_table_info(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = cast(list[sqlite3.Row], connection.execute("PRAGMA table_info('directory_sizes')").fetchall())
    return {cast(str, row["name"]): row for row in rows}


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
    if (
        cast(str, collapsed["type"]).upper() != "INTEGER"
        or int(cast(int | str, collapsed["notnull"])) != 1
        or cast(str | None, collapsed["dflt_value"]) != "0"
    ):
        raise RuntimeError("collapse column verification failed: collapsed must be INTEGER NOT NULL DEFAULT 0")

    for nullable_integer in ("collapsed_dirs", "top_child_id", "top_child_disk_bytes"):
        column = columns[nullable_integer]
        if cast(str, column["type"]).upper() != "INTEGER" or int(cast(int | str, column["notnull"])) != 0:
            raise RuntimeError(
                f"collapse column verification failed: {nullable_integer} must be a nullable INTEGER column"
            )

    collapse_reason = columns["collapse_reason"]
    if cast(str, collapse_reason["type"]).upper() != "TEXT" or int(cast(int | str, collapse_reason["notnull"])) != 0:
        raise RuntimeError("collapse column verification failed: collapse_reason must be a nullable TEXT column")

    foreign_keys = cast(list[sqlite3.Row], connection.execute("PRAGMA foreign_key_list('directory_sizes')").fetchall())
    has_top_child_fk = any(
        cast(str, row["from"]) == "top_child_id" and cast(str, row["table"]) == "paths" and cast(str, row["to"]) == "id"
        for row in foreign_keys
    )
    if not has_top_child_fk:
        raise RuntimeError("collapse column verification failed: top_child_id must reference paths(id)")
