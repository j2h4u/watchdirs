from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Callable

from watchdirs.models import (
    DeletedOpenDiagnostic,
    DeletedOpenFile,
    DeletedOpenTotals,
    GroupLabel,
    ReportWarning,
)


# Fixed, safe argv for the deleted-but-open probe. ``+L1`` selects files whose
# link count is below 1 (deleted-but-open), ``-nP`` disables host/port name
# resolution, and ``-F0`` emits NUL-delimited field records that parse without
# whitespace ambiguity. The argv is constant: no user input is ever interpolated
# and ``shell=False`` is always used (T-03-07).
_LSOF_ARGV: tuple[str, ...] = ("lsof", "-nP", "+L1", "-F0")

# Marker lsof appends to a deleted file's name under ``-n``.
_DELETED_MARKER = " (deleted)"

# Cautious, non-command action guidance (D-08/D-09). It deliberately suggests no
# process-control, cleanup, or service-mutation command; the agent must verify
# the owning service and log-rotation context before deciding any operation.
_ACTION_HINT = (
    "verify the owning service and its log rotation context before any action; "
    "a service holding a deleted file releases the space once it reopens or cycles "
    "the descriptor, so check the owner and rotation policy first rather than "
    "acting blindly"
)

# Verification-only commands (D-07/T-03-05): read-only checks, never mutations.
_VERIFICATION_COMMANDS: tuple[str, ...] = (
    "lsof +L1 -nP",
    "readlink /proc/<pid>/fd/<fd>",
)


# A runner returns ``(stdout, stderr, returncode)`` for a fixed argv. It is the
# sole host seam for lsof execution so tests inject deterministic results
# without spawning the live binary (T-03-11).
LsofRunner = Callable[[list[str]], tuple[bytes, bytes, int]]
TimeProvider = Callable[[], str]
DomainResolver = Callable[[bytes], GroupLabel | None]


def default_lsof_runner(argv: list[str]) -> tuple[bytes, bytes, int]:
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        check=False,
    )
    return completed.stdout, completed.stderr, completed.returncode


def _default_generated_at() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_lsof_field_output(
    stdout: bytes,
) -> tuple[list[DeletedOpenFile], list[ReportWarning]]:
    """Parse NUL-delimited ``lsof -F0`` output into deleted-open culprit rows.

    Process-set fields (``p``/``c``) apply to every following file-set record
    until the next process-set field. A file-set record terminates on the ``f``
    (fd) field. Malformed records (a file field before any process context, or a
    record missing required fields) are tolerated as warnings rather than fatal.
    """

    rows: list[DeletedOpenFile] = []
    warnings: list[ReportWarning] = []

    current_pid: int | None = None
    current_command: str | None = None

    pending_fd: str | None = None
    pending_size: int | None = None
    pending_name: bytes | None = None
    pending_has_size = False

    def _flush() -> None:
        nonlocal pending_fd, pending_size, pending_name, pending_has_size
        if pending_fd is None and pending_name is None:
            return
        if current_pid is None or current_command is None:
            warnings.append(
                ReportWarning(
                    code="deleted_open_malformed_record",
                    message="lsof file record appeared before any process context",
                )
            )
        elif pending_name is None:
            warnings.append(
                ReportWarning(
                    code="deleted_open_malformed_record",
                    message=f"lsof file record for pid {current_pid} had no name field",
                )
            )
        else:
            if not pending_has_size:
                warnings.append(
                    ReportWarning(
                        code="deleted_open_missing_size",
                        message=f"deleted-open file for pid {current_pid} has no size from lsof",
                        path=pending_name,
                    )
                )
            rows.append(
                DeletedOpenFile(
                    pid=current_pid,
                    command=current_command,
                    fd=pending_fd if pending_fd is not None else "?",
                    size_bytes=pending_size,
                    path=pending_name,
                    storage_domain=None,
                    action_hint=_ACTION_HINT,
                    source="lsof",
                )
            )
        pending_fd = None
        pending_size = None
        pending_name = None
        pending_has_size = False

    for raw_field in stdout.split(b"\0"):
        # ``lsof -F0`` NUL-terminates each field but still newline-terminates each
        # logical line, so a field token can carry the previous line's trailing
        # ``\n`` (and the field after the last on a line is empty). Strip the
        # line framing before reading the tag.
        field = raw_field.strip(b"\n")
        if field == b"":
            continue
        tag = field[:1]
        value = field[1:]
        if tag == b"p":
            _flush()
            current_command = None
            try:
                current_pid = int(value)
            except ValueError:
                current_pid = None
                warnings.append(
                    ReportWarning(
                        code="deleted_open_malformed_record",
                        message=f"lsof emitted a non-numeric pid field: {value!r}",
                    )
                )
        elif tag == b"c":
            current_command = os.fsdecode(value)
        elif tag == b"f":
            # A new file-set record begins at the fd field.
            _flush()
            pending_fd = os.fsdecode(value)
        elif tag == b"s":
            try:
                pending_size = int(value)
                pending_has_size = True
            except ValueError:
                pending_size = None
                pending_has_size = False
        elif tag == b"n":
            name = value
            if name.endswith(_DELETED_MARKER.encode("utf-8")):
                name = name[: -len(_DELETED_MARKER.encode("utf-8"))]
            pending_name = name
        # Other field tags (t, u, g, ...) are ignored.
    _flush()
    return rows, warnings


def scan_procfs_deleted_open(
    proc_root: Path,
) -> tuple[list[DeletedOpenFile], list[ReportWarning]]:
    """Bounded fallback: scan ``<proc_root>/<pid>/fd`` for deleted-open links.

    Reads only below the injected ``proc_root``. Symlink targets are read with
    ``os.readlink`` (never followed for traversal). Inaccessible process or fd
    directories are recorded as permission-denied warnings, never fatal. lsof
    sizes are unavailable here, so size is ``None`` with an evidence warning.
    """

    rows: list[DeletedOpenFile] = []
    warnings: list[ReportWarning] = []

    try:
        entries = sorted(os.scandir(proc_root), key=lambda e: e.name)
    except FileNotFoundError:
        warnings.append(
            ReportWarning(
                code="procfs_unavailable",
                message=f"proc root {os.fsdecode(os.fsencode(str(proc_root)))} does not exist",
            )
        )
        return rows, warnings
    except PermissionError as exc:
        warnings.append(
            ReportWarning(
                code="deleted_open_permission_denied",
                message=f"cannot list proc root: {exc}",
            )
        )
        return rows, warnings

    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        pid_dir = Path(entry.path)
        command = _read_proc_comm(pid_dir)
        fd_dir = pid_dir / "fd"
        try:
            fd_entries = sorted(os.scandir(fd_dir), key=lambda e: e.name)
        except (PermissionError, FileNotFoundError, OSError) as exc:
            warnings.append(
                ReportWarning(
                    code="deleted_open_permission_denied",
                    message=f"cannot read fd directory for pid {pid}: {exc}",
                )
            )
            continue
        for fd_entry in fd_entries:
            try:
                target = os.readlink(fd_entry.path)
            except (PermissionError, FileNotFoundError, OSError) as exc:
                warnings.append(
                    ReportWarning(
                        code="deleted_open_permission_denied",
                        message=f"cannot read fd {fd_entry.name} of pid {pid}: {exc}",
                    )
                )
                continue
            if not target.endswith(_DELETED_MARKER):
                continue
            clean = target[: -len(_DELETED_MARKER)]
            rows.append(
                DeletedOpenFile(
                    pid=pid,
                    command=command,
                    fd=fd_entry.name,
                    size_bytes=None,
                    path=os.fsencode(clean),
                    storage_domain=None,
                    action_hint=_ACTION_HINT,
                    source="procfs",
                )
            )
            warnings.append(
                ReportWarning(
                    code="deleted_open_missing_size",
                    message=f"procfs fallback cannot determine size for pid {pid} fd {fd_entry.name}",
                    path=os.fsencode(clean),
                )
            )
    return rows, warnings


def _read_proc_comm(pid_dir: Path) -> str:
    try:
        return (pid_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return "?"


def collect_deleted_open_files(
    *,
    db_connection=None,
    limit: int = 20,
    proc_root: Path = Path("/proc"),
    lsof_runner: LsofRunner | None = None,
    domain_resolver: DomainResolver | None = None,
    generated_at_provider: TimeProvider = _default_generated_at,
) -> DeletedOpenDiagnostic:
    """Collect deleted-but-open files via lsof, falling back to procfs.

    The two host seams (``lsof_runner`` and ``proc_root``) default to the live
    host only here; tests inject deterministic substitutes. lsof is preferred
    because it carries sizes; the procfs fallback runs when lsof is unavailable
    or produced no usable output.
    """

    runner = lsof_runner if lsof_runner is not None else default_lsof_runner
    generated_at = generated_at_provider()

    rows: list[DeletedOpenFile] = []
    warnings: list[ReportWarning] = []
    evidence_source = "lsof"
    used_lsof = False

    try:
        stdout, stderr, returncode = runner(list(_LSOF_ARGV))
    except FileNotFoundError:
        warnings.append(
            ReportWarning(
                code="lsof_unavailable",
                message="lsof binary not found; using bounded procfs fallback",
            )
        )
        stdout, stderr, returncode = b"", b"", None  # type: ignore[assignment]
    except OSError as exc:
        warnings.append(
            ReportWarning(
                code="lsof_unavailable",
                message=f"lsof could not be executed ({exc}); using bounded procfs fallback",
            )
        )
        stdout, stderr, returncode = b"", b"", None  # type: ignore[assignment]
    else:
        if stderr:
            warnings.append(
                ReportWarning(
                    code="lsof_stderr",
                    message="lsof emitted warnings: " + _summarize_stderr(stderr),
                )
            )
        if stdout:
            parsed_rows, parse_warnings = parse_lsof_field_output(stdout)
            rows.extend(parsed_rows)
            warnings.extend(parse_warnings)
            used_lsof = True
            if returncode not in (0, None):
                # lsof commonly exits nonzero (e.g. 1) on partial permission
                # failures while still emitting valid records for accessible
                # processes. The inventory is then incomplete, so surface a
                # caveat rather than presenting the partial result as
                # authoritative.
                warnings.append(
                    ReportWarning(
                        code="lsof_partial",
                        message=(
                            f"lsof exited {returncode} but produced usable output; "
                            "the deleted-open inventory may be incomplete "
                            "(some processes were inaccessible)"
                        ),
                    )
                )
        else:
            warnings.append(
                ReportWarning(
                    code="lsof_no_output",
                    message=(
                        f"lsof produced no usable output (exit {returncode}); "
                        "using bounded procfs fallback"
                    ),
                )
            )

    if not used_lsof:
        fallback_rows, fallback_warnings = scan_procfs_deleted_open(proc_root)
        rows.extend(fallback_rows)
        warnings.extend(fallback_warnings)
        evidence_source = "procfs"

    if domain_resolver is not None:
        rows = [_resolve_domain(row, domain_resolver, warnings) for row in rows]

    rows.sort(key=lambda row: (row.size_bytes if row.size_bytes is not None else -1), reverse=True)

    culprit_count = len(rows)
    shown = rows[:limit]
    truncated = culprit_count > limit

    permission_denied_count = sum(
        1 for warning in warnings if warning.code == "deleted_open_permission_denied"
    )
    totals = DeletedOpenTotals(
        culprit_count=culprit_count,
        shown_count=len(shown),
        total_size_bytes=sum(row.size_bytes or 0 for row in rows),
        shown_size_bytes=sum(row.size_bytes or 0 for row in shown),
        permission_denied_count=permission_denied_count,
    )

    return DeletedOpenDiagnostic(
        ok=True,
        limit=limit,
        effective_limit=limit,
        generated_at=generated_at,
        evidence_source=evidence_source,
        culprits=tuple(shown),
        totals=totals,
        truncated=truncated,
        verification_commands=_VERIFICATION_COMMANDS,
        warnings=tuple(warnings),
    )


def _resolve_domain(
    row: DeletedOpenFile,
    domain_resolver: DomainResolver,
    warnings: list[ReportWarning],
) -> DeletedOpenFile:
    try:
        domain = domain_resolver(row.path)
    except Exception as exc:  # resolver failures are non-fatal evidence gaps.
        warnings.append(
            ReportWarning(
                code="storage_domain_unresolved",
                message=f"could not resolve storage-domain for {os.fsdecode(row.path)}: {exc}",
                path=row.path,
            )
        )
        return row
    if domain is None:
        warnings.append(
            ReportWarning(
                code="storage_domain_unresolved",
                message=f"no persisted mount prefix matched {os.fsdecode(row.path)}",
                path=row.path,
            )
        )
        return row
    return DeletedOpenFile(
        pid=row.pid,
        command=row.command,
        fd=row.fd,
        size_bytes=row.size_bytes,
        path=row.path,
        storage_domain=domain,
        action_hint=row.action_hint,
        source=row.source,
    )


def _summarize_stderr(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "; ".join(lines[:5]) if lines else "(empty)"
