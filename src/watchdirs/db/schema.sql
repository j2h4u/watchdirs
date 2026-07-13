CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    root_path TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS paths (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE
);

-- COMPLETE snapshots store only versions whose aggregate changed. Bounds are
-- half-open snapshot ids: valid_from <= snapshot < valid_to.
CREATE TABLE IF NOT EXISTS directory_size_intervals (
    id INTEGER PRIMARY KEY,
    root_path TEXT NOT NULL,
    path_id INTEGER NOT NULL REFERENCES paths(id),
    valid_from_snapshot_id INTEGER NOT NULL,
    valid_to_snapshot_id INTEGER,
    parent_id INTEGER REFERENCES paths(id),
    depth INTEGER NOT NULL,
    apparent_bytes INTEGER NOT NULL,
    disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    dir_count INTEGER NOT NULL,
    error TEXT,
    collapsed INTEGER NOT NULL,
    collapse_reason TEXT,
    collapsed_dirs INTEGER,
    top_child_id INTEGER REFERENCES paths(id),
    top_child_disk_bytes INTEGER,
    UNIQUE(root_path, path_id, valid_from_snapshot_id)
);

-- Non-complete snapshots are diagnostic evidence and are retained as rows for
-- the diagnostic retention window before their owning snapshot is pruned.
CREATE TABLE IF NOT EXISTS directory_size_diagnostics (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES paths(id),
    parent_id INTEGER REFERENCES paths(id),
    depth INTEGER NOT NULL,
    apparent_bytes INTEGER NOT NULL,
    disk_bytes INTEGER NOT NULL,
    file_count INTEGER NOT NULL,
    dir_count INTEGER NOT NULL,
    error TEXT,
    collapsed INTEGER NOT NULL,
    collapse_reason TEXT,
    collapsed_dirs INTEGER,
    top_child_id INTEGER REFERENCES paths(id),
    top_child_disk_bytes INTEGER,
    UNIQUE(snapshot_id, path_id)
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

CREATE INDEX IF NOT EXISTS directory_size_intervals_path_idx
    ON directory_size_intervals(root_path, path_id, valid_from_snapshot_id);

CREATE INDEX IF NOT EXISTS directory_size_intervals_snapshot_idx
    ON directory_size_intervals(valid_from_snapshot_id, valid_to_snapshot_id, root_path, path_id);

CREATE INDEX IF NOT EXISTS directory_size_intervals_path_gc_idx
    ON directory_size_intervals(path_id, parent_id, top_child_id);

CREATE INDEX IF NOT EXISTS directory_size_diagnostics_snapshot_idx
    ON directory_size_diagnostics(snapshot_id, path_id);

CREATE INDEX IF NOT EXISTS directory_size_diagnostics_path_gc_idx
    ON directory_size_diagnostics(path_id, parent_id, top_child_id);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_idx
    ON snapshot_mounts(snapshot_id);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_mount_point_idx
    ON snapshot_mounts(snapshot_id, mount_point);

CREATE INDEX IF NOT EXISTS snapshot_mounts_snapshot_domain_idx
    ON snapshot_mounts(snapshot_id, major_minor, root, filesystem_type, mount_source);
