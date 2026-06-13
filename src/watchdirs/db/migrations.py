from __future__ import annotations

from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
import sqlite3

from watchdirs.models import DirectoryAggregate, MountInfo, SnapshotMount, SnapshotRecord, SnapshotStatus


SCHEMA_VERSION = 2
INSERT_BATCH_SIZE = 10000


def initialize_database(connection: sqlite3.Connection) -> None:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {user_version} is newer than supported version {SCHEMA_VERSION}"
        )
    if user_version == SCHEMA_VERSION:
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
            path,
            parent_path,
            name,
            depth,
            apparent_bytes,
            disk_bytes,
            file_count,
            dir_count,
            error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        connection.executemany(sql, [_directory_row_values(row) for row in batch])
    if commit:
        connection.commit()


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


def _directory_row_values(row: DirectoryAggregate) -> tuple[object, ...]:
    return (
        row.snapshot_id,
        sqlite3.Binary(row.path),
        sqlite3.Binary(row.parent_path) if row.parent_path is not None else None,
        sqlite3.Binary(row.name),
        row.depth,
        row.apparent_bytes,
        row.disk_bytes,
        row.file_count,
        row.dir_count,
        row.error,
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
