from __future__ import annotations

import fcntl
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class OperationLockedError(RuntimeError):
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = Path(lock_path)
        super().__init__(f"another watchdirs writer is already active: {self.lock_path}")


class OperationLockTimeoutError(RuntimeError):
    def __init__(self, lock_path: Path, *, timeout_seconds: float, elapsed_seconds: float) -> None:
        self.lock_path = Path(lock_path)
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds
        super().__init__(
            f"timed out waiting for another watchdirs writer to release {self.lock_path} after {elapsed_seconds:.3f}s"
        )


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

    def __exit__(self, _exc_type: object | None, exc: BaseException | None, _tb: object | None) -> bool:
        self.release()
        return False


def operation_lock_path_for_db(db_path: Path) -> Path:
    resolved = Path(db_path).expanduser().resolve(strict=False)
    return resolved.with_name(f"{resolved.name}.lock")


def acquire_operation_lock(lock_path: Path, *, timeout_seconds: float = 0.0) -> OperationLock:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("lock timeout must be a finite non-negative number")

    resolved = Path(lock_path).expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    handle = resolved.open("a+b")
    started_at = time.monotonic()
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError as exc:
            elapsed_seconds = time.monotonic() - started_at
            if timeout_seconds == 0:
                handle.close()
                raise OperationLockedError(resolved) from exc
            if elapsed_seconds >= timeout_seconds:
                handle.close()
                raise OperationLockTimeoutError(
                    resolved,
                    timeout_seconds=timeout_seconds,
                    elapsed_seconds=elapsed_seconds,
                ) from exc
            time.sleep(min(0.05, timeout_seconds - elapsed_seconds))
    return OperationLock(path=resolved, _handle=handle)
