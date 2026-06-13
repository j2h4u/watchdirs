CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    root_path TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS directory_sizes (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path BLOB NOT NULL,
    parent_path BLOB,
    name BLOB NOT NULL,
    depth INTEGER NOT NULL,
    apparent_bytes INTEGER NOT NULL,
    disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    dir_count INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS snapshot_mounts (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    mount_id INTEGER NOT NULL,
    parent_id INTEGER NOT NULL,
    major_minor TEXT NOT NULL,
    root BLOB NOT NULL,
    mount_point BLOB NOT NULL,
    filesystem_type TEXT NOT NULL,
    mount_source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS directory_sizes_path_snapshot_idx
    ON directory_sizes(path, snapshot_id);

CREATE INDEX IF NOT EXISTS directory_sizes_snapshot_size_idx
    ON directory_sizes(snapshot_id, disk_bytes);

CREATE INDEX IF NOT EXISTS directory_sizes_snapshot_parent_idx
    ON directory_sizes(snapshot_id, parent_path);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_idx
    ON snapshot_mounts(snapshot_id);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_mount_point_idx
    ON snapshot_mounts(snapshot_id, mount_point);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_domain_idx
    ON snapshot_mounts(snapshot_id, major_minor, root, filesystem_type, mount_source);
