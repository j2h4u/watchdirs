from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

# Forensic file-type magic for `PRAGMA application_id` (D-05). Lets `file`/tooling
# identify a watchdirs database independent of extension. ASCII "WdRs" => 0x57645273.
WATCHDIRS_APPLICATION_ID = 0x57645273

# Researched default page size (D-05 / A3). Must be set on the virgin file, before
# any table is written, or SQLite ignores it.
WATCHDIRS_PAGE_SIZE = 8192


def _configure_connection(
    connection: sqlite3.Connection, *, is_virgin: bool, readonly: bool = False
) -> sqlite3.Connection:
    try:
        connection.row_factory = sqlite3.Row
        if is_virgin:
            # These MUST precede the first table/write (Pattern 4 / Pitfall 3).
            connection.execute(f"PRAGMA page_size={WATCHDIRS_PAGE_SIZE}")
            connection.execute("PRAGMA auto_vacuum=FULL")
            connection.execute(f"PRAGMA application_id={WATCHDIRS_APPLICATION_ID}")
        if readonly:
            connection.execute("PRAGMA query_only=ON")
        else:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def owned_connection(factory: Callable[[Path], sqlite3.Connection], path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection owned by this scope and close it on every exit."""

    connection = factory(path)
    try:
        yield connection
    finally:
        connection.close()


def open_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    is_virgin = not db_path.exists() or db_path.stat().st_size == 0
    return _configure_connection(sqlite3.connect(db_path), is_virgin=is_virgin)


def open_existing_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"watchdirs database does not exist: {db_path}")

    return _configure_connection(
        sqlite3.connect(f"file:{db_path}?mode=rw", uri=True),
        is_virgin=False,
    )


def open_readonly_connection(path: Path) -> sqlite3.Connection:
    db_path = Path(path).expanduser()
    if not db_path.is_file():
        raise FileNotFoundError(f"watchdirs database does not exist: {db_path}")

    return _configure_connection(
        sqlite3.connect(f"file:{db_path}?mode=ro", uri=True),
        is_virgin=False,
        readonly=True,
    )
