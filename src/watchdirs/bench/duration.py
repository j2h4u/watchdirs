"""Cold/warm scan wall-clock harness (D-10), operator-run.

Times a real ``scan_root`` under PRODUCTION priority -- wrapped in ``nice`` and
``ionice -c2 -n7`` (both at ``/usr/bin``) -- and reports the COLD-cache and
WARM-cache legs SEPARATELY, root-by-root, as a median of >=3 runs plus the spread.

Timing uses ``time.monotonic()`` (NOT ``time.time()``): the monotonic clock cannot
step backward on an NTP adjustment mid-scan, so an elapsed measurement is never
corrupted by a wall-clock correction.

Cold-cache leg -- the privilege fallback (Pitfall 5)
----------------------------------------------------
Dropping the page cache requires writing ``3`` to ``/proc/sys/vm/drop_caches``,
which is mode 0200 (root-only). This harness tries three strategies IN ORDER and
NEVER silently mislabels a warm run as cold:

1. ``sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'`` -- the real system-wide drop,
   if the operator is in the sudo group. This is the ONLY privileged operation in
   the phase and runs ONLY here in the benchmark, never in the collect runtime
   (threat T-03.1-04-01).
2. Unprivileged fallback: ``os.posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED)`` on the
   scanned target -- advises the kernel to drop THAT target's cached pages without
   root. Narrower than a full drop, but honest.
3. If neither works, the leg is reported as ``cold unavailable, warm only`` -- the
   cold median is omitted rather than a warm number relabeled as cold.

This module is OPERATOR-run (the cold leg is privileged and a real scan is slow);
it is NOT part of the unattended unit suite. See the Plan 04 human-verify checkpoint
and VALIDATION.md Manual-Only Verifications.

Run as a dev tool::

    uv run python -m watchdirs.bench.duration <root> [<root> ...] --runs 3
    # cold leg needs privilege for the real drop_caches:
    sudo --preserve-env uv run python -m watchdirs.bench.duration <root>
"""

from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from watchdirs.collect.scanner import scan_root
from watchdirs.models import ScannerOptions

# Production I/O priority: best-effort class (-c2), lowest niceness within it (-n7),
# matching how collect runs in prod. Both binaries verified present at /usr/bin.
NICE_BIN = "/usr/bin/nice"
IONICE_BIN = "/usr/bin/ionice"
IONICE_ARGS = ("-c2", "-n7")

DROP_CACHES_PATH = "/proc/sys/vm/drop_caches"
MIN_SPREAD_SAMPLES = 2
MIN_RECOMMENDED_RUNS = 3


@dataclass(frozen=True)
class LegResult:
    """One cache leg (cold or warm) for one root: the per-run times + median/spread."""

    leg: str  # "cold" | "warm"
    root: str
    available: bool
    cold_method: str | None  # "sudo-drop-caches" | "posix-fadvise" | None (warm leg)
    times: tuple[float, ...]

    @property
    def median(self) -> float | None:
        return statistics.median(self.times) if self.times else None

    @property
    def spread(self) -> float | None:
        """max - min across runs (None if fewer than 2 runs)."""
        if len(self.times) < MIN_SPREAD_SAMPLES:
            return None
        return max(self.times) - min(self.times)


# --- cold-cache drop: the three-branch privilege fallback (Pitfall 5) ---------


def _try_sudo_drop_caches() -> bool:
    """Branch 1: system-wide drop via sudo. Returns True only on a real drop."""
    if shutil.which("sudo") is None:
        return False
    try:
        completed = subprocess.run(
            ["sudo", "-n", "sh", "-c", f"echo 3 > {DROP_CACHES_PATH}"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _try_fadvise_dontneed(target: Path) -> bool:
    """Branch 2: unprivileged per-target page drop via posix_fadvise(DONTNEED)."""
    if not hasattr(os, "posix_fadvise"):
        return False
    try:
        fd = os.open(str(target), os.O_RDONLY)
    except OSError:
        return False
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


def drop_cache_for(target: Path) -> str | None:
    """Drop the page cache before a cold run, trying the three branches in order.

    Returns the method actually used (``"sudo-drop-caches"`` / ``"posix-fadvise"``)
    or ``None`` if neither worked -- in which case the caller MUST mark the cold leg
    unavailable, never relabel a warm run as cold (Pitfall 5).
    """
    if _try_sudo_drop_caches():
        return "sudo-drop-caches"
    if _try_fadvise_dontneed(target):
        return "posix-fadvise"
    return None


# --- timing -------------------------------------------------------------------


def _time_one_scan_under_priority(root: Path) -> float:
    """Run one ``scan_root`` under nice/ionice and return its wall-clock seconds.

    The scan is wrapped in a ``nice``/``ionice -c2 -n7`` subprocess so the measured
    run carries the SAME I/O + CPU priority collect uses in prod. ``time.monotonic()``
    brackets the whole wrapped run (clock-step immune).
    """
    cmd = [
        NICE_BIN,
        IONICE_BIN,
        *IONICE_ARGS,
        sys.executable,
        "-c",
        # Minimal in-process scan mirroring cli.py's scan_root(ScannerOptions(root=...)).
        (
            "import sys; from watchdirs.collect.scanner import scan_root; "
            "from watchdirs.models import ScannerOptions; "
            "scan_root(ScannerOptions(root=sys.argv[1]))"
        ),
        str(root),
    ]
    start = time.monotonic()
    subprocess.run(cmd, capture_output=True, check=False)
    return time.monotonic() - start


def _time_one_scan_inprocess(root: Path) -> float:
    """In-process timing fallback when the priority wrappers are unavailable.

    Still ``time.monotonic()``-bracketed; used only if nice/ionice are missing so the
    harness degrades to an un-prioritized but honestly-timed measurement.
    """
    start = time.monotonic()
    scan_root(ScannerOptions(root=root))
    return time.monotonic() - start


def _priority_wrappers_available() -> bool:
    return Path(NICE_BIN).exists() and Path(IONICE_BIN).exists()


def _time_scan(root: Path) -> float:
    if _priority_wrappers_available():
        return _time_one_scan_under_priority(root)
    return _time_one_scan_inprocess(root)


def measure_warm_leg(root: Path, *, runs: int) -> LegResult:
    """Warm-cache leg: no cache drop between runs; median of ``runs`` (>=3)."""
    times = tuple(_time_scan(root) for _ in range(runs))
    return LegResult(leg="warm", root=str(root), available=True, cold_method=None, times=times)


def measure_cold_leg(root: Path, *, runs: int) -> LegResult:
    """Cold-cache leg: drop the cache BEFORE each run; median of ``runs`` (>=3).

    If no drop strategy is available the leg is returned ``available=False`` with no
    times -- the cold median is omitted, never faked from a warm number (Pitfall 5).
    """
    times: list[float] = []
    method: str | None = None
    for _ in range(runs):
        used = drop_cache_for(root)
        if used is None:
            return LegResult(leg="cold", root=str(root), available=False, cold_method=None, times=())
        method = used
        times.append(_time_scan(root))
    return LegResult(leg="cold", root=str(root), available=True, cold_method=method, times=tuple(times))


def measure_root(root: Path, *, runs: int) -> tuple[LegResult, LegResult]:
    """Measure the cold and warm legs for one root, reported separately."""
    cold = measure_cold_leg(root, runs=runs)
    warm = measure_warm_leg(root, runs=runs)
    return cold, warm


# --- dev entry point ----------------------------------------------------------


def _format_leg(leg: LegResult) -> str:
    if not leg.available:
        return f"  {leg.leg}: cold unavailable, warm only (no sudo drop_caches, no posix_fadvise)"
    median = leg.median
    spread = leg.spread
    method = f" via {leg.cold_method}" if leg.cold_method else ""
    spread_text = f" spread={spread:.4f}s" if spread is not None else ""
    return f"  {leg.leg}: median={median:.4f}s{spread_text} (n={len(leg.times)}){method}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m watchdirs.bench.duration",
        description="Cold/warm scan wall-clock under nice/ionice -c2 -n7, median of >=3.",
    )
    parser.add_argument("roots", nargs="+", help="root path(s) to scan, root-by-root")
    parser.add_argument("--runs", type=int, default=3, help="runs per leg (>=3 recommended)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.runs < MIN_RECOMMENDED_RUNS:
        print(
            f"warning: --runs={args.runs} < {MIN_RECOMMENDED_RUNS}; D-10 wants a median of >=3 runs",
            file=sys.stderr,
        )
    if not _priority_wrappers_available():
        print(
            f"warning: {NICE_BIN}/{IONICE_BIN} not both present; timing without prod priority",
            file=sys.stderr,
        )

    for root_arg in args.roots:
        root = Path(root_arg)
        print(f"root: {root}")
        cold, warm = measure_root(root, runs=args.runs)
        print(_format_leg(cold))
        print(_format_leg(warm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
