from __future__ import annotations

from dataclasses import dataclass
import fcntl
from pathlib import Path
from typing import BinaryIO


class OperationLocked(RuntimeError):
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)
        super().__init__(f"another watchdirs writer is already active: {self.lock_path}")


@dataclass
class OperationLock:
    path: Path
    _handle: BinaryIO

    def release(self) -> None:
        if self._handle.closed:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()

    def __enter__(self) -> OperationLock:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


def operation_lock_path_for_db(db_path: Path) -> Path:
    resolved = Path(db_path).expanduser().resolve(strict=False)
    return resolved.with_name(f"{resolved.name}.lock")


def acquire_operation_lock(lock_path: Path) -> OperationLock:
    resolved = Path(lock_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handle = resolved.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise OperationLocked(resolved)
    return OperationLock(path=resolved, _handle=handle)
