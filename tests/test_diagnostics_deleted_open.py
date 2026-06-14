from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


GIB = 1024 ** 3


# ---------------------------------------------------------------------------
# Helpers: synthetic lsof -nP +L1 -F0 (NUL-delimited field) output.
#
# lsof field output is one field per line; with -F0 each line is terminated by
# a NUL byte instead of a newline. Process-set ("p"/"c") lines apply to all of
# the following file-set lines until the next process line. File-set lines we
# care about: f=fd, t=type, s=size, n=name. The "+L1" filter only emits files
# whose link count is < 1, i.e. deleted-but-open; lsof appends "(deleted)" to
# the name in -nP human form but with -F it surfaces via the link-count field.
# We model deleted entries by an "n" name carrying the deleted marker so the
# parser does not depend on a separate link-count field that lsof omits in -F0.
# ---------------------------------------------------------------------------


def _lsof_record(*fields: str) -> bytes:
    return b"".join(field.encode("utf-8") + b"\0" for field in fields)


def _lsof_process(pid: int, command: str) -> bytes:
    return _lsof_record(f"p{pid}", f"c{command}")


def _lsof_file(*, fd: int, ftype: str, size: int | None, name: str, deleted: bool = True) -> bytes:
    suffix = " (deleted)" if deleted else ""
    fields = [f"f{fd}", f"t{ftype}"]
    if size is not None:
        fields.append(f"s{size}")
    fields.append(f"n{name}{suffix}")
    return _lsof_record(*fields)


def _fake_lsof_runner(*, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0,
                      raises: Exception | None = None):
    """Return a callable matching the lsof_runner(argv) seam contract."""

    captured: dict[str, object] = {}

    def runner(argv: list[str]):
        captured["argv"] = list(argv)
        if raises is not None:
            raise raises
        return stdout, stderr, returncode

    runner.captured = captured  # type: ignore[attr-defined]
    return runner


def _make_proc_fixture(tmp_path: Path, processes: dict[int, dict[str, object]]) -> Path:
    """Build a synthetic /proc tree.

    processes maps pid -> {
        "comm": str,
        "fds": {fd_int: target_str},   # symlink targets, may end with " (deleted)"
        "fd_unreadable": bool,         # make /proc/<pid>/fd unreadable (perm gap)
    }
    """
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    # A non-numeric entry that must be ignored by the scanner.
    (proc_root / "cpuinfo").write_text("x", encoding="utf-8")
    for pid, spec in processes.items():
        pid_dir = proc_root / str(pid)
        pid_dir.mkdir()
        comm = spec.get("comm")
        if comm is not None:
            (pid_dir / "comm").write_text(str(comm) + "\n", encoding="utf-8")
        fd_dir = pid_dir / "fd"
        fd_dir.mkdir()
        if spec.get("fd_unreadable"):
            os.chmod(fd_dir, 0o000)
            continue
        for fd, target in spec.get("fds", {}).items():  # type: ignore[union-attr]
            link = fd_dir / str(fd)
            # Use a non-existent target so the deleted marker is what matters,
            # and traversal must never follow the link target.
            os.symlink(str(target), link)
    return proc_root


# ---------------------------------------------------------------------------
# Test 1: NUL-delimited lsof field parsing -> culprit rows.
# ---------------------------------------------------------------------------


def test_parse_lsof_field_output_produces_culprit_rows(repo_root: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    stdout = (
        _lsof_process(1234, "python3")
        + _lsof_file(fd=7, ftype="REG", size=500 * GIB, name="/var/log/app.log")
        + _lsof_process(5678, "journald")
        + _lsof_file(fd=3, ftype="REG", size=2 * GIB, name="/var/log/journal/x")
    )

    rows, warnings = deleted_open.parse_lsof_field_output(stdout)

    assert len(rows) == 2
    by_pid = {row.pid: row for row in rows}
    assert by_pid[1234].command == "python3"
    assert by_pid[1234].fd == "7"
    assert by_pid[1234].size_bytes == 500 * GIB
    assert os.fsdecode(by_pid[1234].path) == "/var/log/app.log"
    assert by_pid[5678].command == "journald"
    assert by_pid[5678].size_bytes == 2 * GIB
    # No warnings for clean field output.
    assert warnings == []


def test_parse_lsof_handles_missing_size_and_malformed_records(repo_root: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    stdout = (
        _lsof_process(42, "rsyslogd")
        + _lsof_file(fd=9, ftype="REG", size=None, name="/tmp/no-size")
        # A file-set line that appears before any process line is malformed and
        # must be tolerated as a warning, not a crash.
        + _lsof_record("f99", "tREG", "s1", "n/orphan (deleted)")
    )

    rows, warnings = deleted_open.parse_lsof_field_output(stdout)

    sized = {os.fsdecode(row.path): row for row in rows}
    assert sized["/tmp/no-size"].size_bytes is None
    warning_codes = {warning.code for warning in warnings}
    # Missing size and/or orphan file record surface as warnings.
    assert "deleted_open_missing_size" in warning_codes or "deleted_open_malformed_record" in warning_codes


# ---------------------------------------------------------------------------
# Test 2: stderr warnings / permission gaps preserved, not fatal.
# ---------------------------------------------------------------------------


def test_lsof_stderr_warning_is_preserved_when_stdout_usable(repo_root: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    stdout = _lsof_process(1, "init") + _lsof_file(fd=4, ftype="REG", size=GIB, name="/x")
    runner = _fake_lsof_runner(
        stdout=stdout,
        stderr=b"lsof: WARNING: can't stat() proc file system\n",
        returncode=1,  # lsof commonly exits nonzero with partial+warnings.
    )

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=Path("/nonexistent-proc-should-not-be-read"),
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert diagnostic.ok is True
    assert len(diagnostic.culprits) == 1
    warning_codes = {warning.code for warning in diagnostic.warnings}
    assert "lsof_stderr" in warning_codes


def test_lsof_command_not_found_falls_back_to_procfs(repo_root: Path, tmp_path: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    proc_root = _make_proc_fixture(
        tmp_path,
        {
            321: {
                "comm": "nginx",
                "fds": {
                    5: "/var/log/nginx/access.log (deleted)",
                    6: "/dev/null",  # not deleted -> ignored
                },
            },
        },
    )
    runner = _fake_lsof_runner(raises=FileNotFoundError("lsof"))

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=proc_root,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert diagnostic.ok is True
    assert len(diagnostic.culprits) == 1
    culprit = diagnostic.culprits[0]
    assert culprit.pid == 321
    assert culprit.command == "nginx"
    assert os.fsdecode(culprit.path).startswith("/var/log/nginx/access.log")
    warning_codes = {warning.code for warning in diagnostic.warnings}
    assert "lsof_unavailable" in warning_codes


def test_lsof_nonzero_exit_without_stdout_falls_back_to_procfs(repo_root: Path, tmp_path: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    proc_root = _make_proc_fixture(
        tmp_path,
        {7: {"comm": "dockerd", "fds": {3: "/var/lib/docker/x (deleted)"}}},
    )
    runner = _fake_lsof_runner(stdout=b"", stderr=b"lsof: fatal\n", returncode=1)

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=proc_root,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    # No usable stdout -> fallback used, warning recorded, still ok.
    assert diagnostic.ok is True
    assert len(diagnostic.culprits) == 1
    warning_codes = {warning.code for warning in diagnostic.warnings}
    assert "lsof_no_output" in warning_codes or "lsof_stderr" in warning_codes


# ---------------------------------------------------------------------------
# Test 3: procfs fallback with injected root, deleted-suffix detection,
# inaccessible process directories.
# ---------------------------------------------------------------------------


def test_procfs_fallback_detects_deleted_links_and_records_permission_gaps(
    repo_root: Path, tmp_path: Path
) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    proc_root = _make_proc_fixture(
        tmp_path,
        {
            100: {"comm": "good", "fds": {1: "/data/big.bin (deleted)", 2: "/data/live.txt"}},
            200: {"comm": "locked", "fd_unreadable": True},
        },
    )

    rows, warnings = deleted_open.scan_procfs_deleted_open(proc_root)

    assert len(rows) == 1
    assert rows[0].pid == 100
    assert os.fsdecode(rows[0].path).startswith("/data/big.bin")
    warning_codes = {warning.code for warning in warnings}
    assert "deleted_open_permission_denied" in warning_codes

    # Cleanup the unreadable dir so tmp_path teardown does not fail.
    os.chmod(proc_root / "200" / "fd", 0o755)


def test_collector_never_reads_real_proc_when_proc_root_injected(
    repo_root: Path, tmp_path: Path
) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    proc_root = _make_proc_fixture(tmp_path, {})  # empty proc, no culprits
    runner = _fake_lsof_runner(raises=FileNotFoundError("lsof"))

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=proc_root,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert diagnostic.ok is True
    assert diagnostic.culprits == ()
    # Verification command examples must use the public /proc spelling, never tmp_path.
    rendered = " ".join(diagnostic.verification_commands)
    assert str(tmp_path) not in rendered


# ---------------------------------------------------------------------------
# Test 4: sort by size desc, capped by --limit, truncation metadata.
# ---------------------------------------------------------------------------


def test_results_sorted_by_size_desc_capped_with_truncation_metadata(
    repo_root: Path, tmp_path: Path
) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    stdout = (
        _lsof_process(1, "a") + _lsof_file(fd=1, ftype="REG", size=1 * GIB, name="/a")
        + _lsof_process(2, "b") + _lsof_file(fd=1, ftype="REG", size=9 * GIB, name="/b")
        + _lsof_process(3, "c") + _lsof_file(fd=1, ftype="REG", size=5 * GIB, name="/c")
    )
    runner = _fake_lsof_runner(stdout=stdout)

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=tmp_path / "proc",
        limit=2,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert [row.size_bytes for row in diagnostic.culprits] == [9 * GIB, 5 * GIB]
    assert diagnostic.limit == 2
    assert diagnostic.effective_limit == 2
    assert diagnostic.truncated is True
    assert diagnostic.totals.culprit_count == 3
    assert diagnostic.totals.shown_count == 2


# ---------------------------------------------------------------------------
# Test 5: injected lsof_runner covers command-not-found, nonzero, stderr, stdout.
# (Covered across the cases above; this asserts the fixed-argv contract.)
# ---------------------------------------------------------------------------


def test_collector_invokes_lsof_with_fixed_safe_argv(repo_root: Path, tmp_path: Path) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")

    runner = _fake_lsof_runner(stdout=b"")
    deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=tmp_path / "proc",
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    argv = runner.captured["argv"]  # type: ignore[index]
    assert argv[0] == "lsof"
    # Fixed flags: numeric/no-resolve, deleted-open filter, field output.
    assert "+L1" in argv
    assert "-nP" in argv
    assert any(flag.startswith("-F") for flag in argv)
    # No shell metacharacters / no user-controlled interpolation.
    for token in argv:
        assert ";" not in token and "|" not in token and "&" not in token


# ---------------------------------------------------------------------------
# D-08/D-09/D-10 contract: fields, cautious hints, no directory persistence.
# ---------------------------------------------------------------------------


def test_culprit_rows_carry_d08_d09_fields_and_cautious_action_hint(
    repo_root: Path, tmp_path: Path
) -> None:
    deleted_open = import_module(repo_root, "watchdirs.diagnostics.deleted_open")
    render = import_module(repo_root, "watchdirs.reporting.render")

    stdout = _lsof_process(4321, "mysqld") + _lsof_file(fd=12, ftype="REG", size=42 * GIB, name="/var/lib/mysql/ibtmp1")
    runner = _fake_lsof_runner(stdout=stdout)

    diagnostic = deleted_open.collect_deleted_open_files(
        lsof_runner=runner,
        proc_root=tmp_path / "proc",
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    culprit = diagnostic.culprits[0]
    # D-08 / D-09 fields.
    assert culprit.command == "mysqld"
    assert culprit.pid == 4321
    assert culprit.fd == "12"
    assert culprit.size_bytes == 42 * GIB
    assert os.fsdecode(culprit.path) == "/var/lib/mysql/ibtmp1"
    assert hasattr(culprit, "storage_domain")  # resolvable storage-domain slot, may be None
    assert isinstance(culprit.action_hint, str) and culprit.action_hint

    # Action hint is cautious, non-command guidance: it must NOT contain
    # process-control / destructive commands.
    hint = culprit.action_hint.lower()
    for forbidden in ("kill ", "kill-", "systemctl stop", "systemctl restart", "rm ", "docker stop", "truncate"):
        assert forbidden not in hint
    # It should point the agent at verifying owner + log rotation / service context.
    assert "verify" in hint or "owner" in hint or "rotation" in hint or "service" in hint

    # Render payload escaping reuse + stable envelope fields.
    payload = render.render_deleted_open_payload(diagnostic)
    assert payload["ok"] is True
    assert payload["command"] == "deleted-open-files"
    assert payload["culprits"][0]["pid"] == 4321
    assert payload["culprits"][0]["size_bytes"] == 42 * GIB

    text = render.render_deleted_open_text(diagnostic)
    assert "command=deleted-open-files" in text
    assert "pid=4321" in text


def test_deleted_open_never_writes_directory_sizes_rows(repo_root: Path) -> None:
    """D-10: deleted-open evidence must never be persisted as directory aggregate rows."""
    deleted_open_path = repo_root / "src" / "watchdirs" / "diagnostics" / "deleted_open.py"
    source = deleted_open_path.read_text(encoding="utf-8")
    # No writes to the directory aggregate table or insert helpers.
    assert "insert_directory_rows" not in source
    assert "directory_sizes" not in source
    assert "INSERT INTO directory" not in source.upper().replace("  ", " ")


# ---------------------------------------------------------------------------
# Test 6: CLI envelope is stable even with no culprits.
# ---------------------------------------------------------------------------


def test_cli_deleted_open_json_stable_envelope_with_no_culprits(repo_root: Path, tmp_path: Path) -> None:
    # Build a real (empty) db so --db opens cleanly; lsof is the live host's, but
    # +L1 with no deleted-open files should produce a stable empty envelope. To
    # keep this deterministic we point the command at an empty injected proc via
    # the dedicated test entrypoint instead of spawning host lsof.
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    connection.close()

    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}:{env['PYTHONPATH']}"
    # WATCHDIRS_TEST_PROC_ROOT and WATCHDIRS_TEST_NO_LSOF force deterministic seams
    # so the CLI envelope test does not depend on the live host.
    env["WATCHDIRS_TEST_PROC_ROOT"] = str(tmp_path / "empty-proc")
    (tmp_path / "empty-proc").mkdir()
    env["WATCHDIRS_TEST_NO_LSOF"] = "1"

    result = subprocess.run(
        ["python3", "-m", "watchdirs", "deleted-open-files", "--db", str(db_path), "--json", "--limit", "5"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "deleted-open-files"
    assert payload["limit"] == 5
    assert payload["effective_limit"] == 5
    assert payload["culprits"] == []
    assert payload["truncated"] is False
    assert "totals" in payload
    assert "verification_commands" in payload
    assert "warnings" in payload
    assert "generated_at" in payload
