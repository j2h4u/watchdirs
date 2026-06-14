from __future__ import annotations

import sqlite3
from pathlib import Path


# Forensic file-type magic for `PRAGMA application_id` (D-05). Lets `file`/tooling
# identify a watchdirs database independent of extension. ASCII "WdRs" => 0x57645273.
WATCHDIRS_APPLICATION_ID = 0x57645273

# Researched default page size (D-05 / A3). Must be set on the virgin file, before
# any table is written, or SQLite ignores it.
WATCHDIRS_PAGE_SIZE = 8192


def open_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_virgin = not db_path.exists() or db_path.stat().st_size == 0
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    if is_virgin:
        # These MUST precede the first table/write (Pattern 4 / Pitfall 3). page_size
        # and auto_vacuum are only meaningful on a brand-new file, so guard on virgin
        # to avoid silently mis-toggling an already-populated DB.
        connection.execute(f"PRAGMA page_size={WATCHDIRS_PAGE_SIZE}")
        connection.execute("PRAGMA auto_vacuum=FULL")
        connection.execute(f"PRAGMA application_id={WATCHDIRS_APPLICATION_ID}")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection
