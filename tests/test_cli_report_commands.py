# pyright: reportMissingParameterType=false, reportAny=false
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest
from conftest import DirectoryAggregateLike, JsonDict, MountInfoLike


def import_module(repo_root: Path, module_name: str):
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    return __import__(module_name, fromlist=["__name__"])


def run_module(repo_root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    command_env["PYTHONDONTWRITEBYTECODE"] = "1"
    command_env["WATCHDIRS_REPO_ROOT"] = str(repo_root)
    src_path = str(repo_root / "src")
    existing_pythonpath = command_env.get("PYTHONPATH")
    command_env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"
    return subprocess.run(
        [sys.executable, "-m", "watchdirs", *args],
        cwd=repo_root,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )


def parse_json_output(result: subprocess.CompletedProcess[str]) -> JsonDict:
    assert result.stdout, f"expected JSON on stdout, got stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_unprivileged_default_report_proxies_to_query_socket(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    socket_path = tmp_path / "query.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    received: list[JsonDict] = []

    def serve_once() -> None:
        connection, _ = server.accept()
        with connection:
            request = connection.recv(65536)
            received.append(json.loads(request.decode("utf-8")))
            connection.sendall(
                json.dumps({
                    "returncode": 0,
                    "stdout": '{"ok":true}\n',
                    "stderr": "from-service\n",
                }).encode("utf-8")
            )
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    monkeypatch.setenv("WATCHDIRS_QUERY_SOCKET", str(socket_path))
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)

    try:
        assert cli.main(["report", "--since", "24h", "--json"]) == 0
    finally:
        thread.join(timeout=5)
        server.close()

    assert received == [{"argv": ["report", "--since", "24h", "--json"]}]
    captured = capsys.readouterr()
    assert captured.out == '{"ok":true}\n'
    assert captured.err == "from-service\n"


def test_no_args_defaults_to_latest_top_via_query_socket(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    socket_path = tmp_path / "query.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    received: list[JsonDict] = []

    def serve_once() -> None:
        connection, _ = server.accept()
        with connection:
            request = connection.recv(65536)
            received.append(json.loads(request.decode("utf-8")))
            connection.sendall(
                json.dumps({
                    "returncode": 0,
                    "stdout": "command=top\n",
                    "stderr": "",
                }).encode("utf-8")
            )
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    monkeypatch.setenv("WATCHDIRS_QUERY_SOCKET", str(socket_path))
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)

    try:
        assert cli.main([]) == 0
    finally:
        thread.join(timeout=5)
        server.close()

    assert received == [{"argv": ["top"]}]
    captured = capsys.readouterr()
    assert captured.out == "command=top\n"
    assert captured.err == ""


def test_query_server_rejects_mutating_commands_and_forces_host_db(repo_root: Path) -> None:
    cli = import_module(repo_root, "watchdirs.cli")

    assert cli._validated_query_argv({"argv": ["report", "--since", "24h"]}) == ("report", "--since", "24h")
    assert cli._validated_query_argv({"argv": ["snapshots", "--limit", "5"]}) == ("snapshots", "--limit", "5")
    assert cli._with_forced_host_db(("report", "--since", "24h")) == (
        "report",
        "--db",
        "/var/lib/watchdirs/watchdirs.sqlite3",
        "--since",
        "24h",
    )

    with pytest.raises(ValueError, match="not allowed"):
        cli._validated_query_argv({"argv": ["collect", "--config", "/etc/watchdirs/watchdirs.toml"]})
    with pytest.raises(ValueError, match="always uses"):
        cli._validated_query_argv({"argv": ["report", "--db", "/tmp/other.sqlite3", "--since", "24h"]})


def test_query_response_broken_pipe_exits_cleanly(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli = import_module(repo_root, "watchdirs.cli")

    class BrokenStdout:
        def write(self, _value: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise AssertionError("flush should not run after BrokenPipeError")

    monkeypatch.setattr(cli.sys, "stdout", BrokenStdout())

    assert cli._write_query_response({"returncode": 0, "stdout": "", "stderr": ""}) == 0


def test_proxy_stdout_broken_pipe_exits_cleanly(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cli = import_module(repo_root, "watchdirs.cli")

    class BrokenStdout:
        def write(self, _value: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise AssertionError("flush should not run after BrokenPipeError")

    monkeypatch.setattr(cli.sys, "stdout", BrokenStdout())

    assert cli._write_stdout("command=top\n") is False


def test_since_defaults_to_24h_for_growth_commands(repo_root: Path) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    parser = cli.build_parser()

    assert parser.parse_args(["report"]).since == "24h"
    assert parser.parse_args(["diff"]).since == "24h"
    assert parser.parse_args(["deleted"]).since == "24h"
    assert parser.parse_args(["explain-path", "/var/lib"]).since == "24h"


def test_snapshots_defaults_to_ten_rows(repo_root: Path) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    parser = cli.build_parser()

    assert parser.parse_args(["snapshots"]).limit == "10"


def _open_db(repo_root: Path, tmp_path: Path):
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    models_module = import_module(repo_root, "watchdirs.models")

    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    return db_path, connection, migrations_module, models_module


def _directory_row(
    models_module,
    snapshot_id: int,
    path: bytes,
    *,
    disk_bytes: int,
    apparent_bytes: int,
    depth: int,
    parent_path: bytes | None,
    file_count: int = 0,
    dir_count: int = 0,
    error: str | None = None,
    collapsed: bool = False,
    collapse_reason: str | None = None,
    collapsed_dirs: int | None = None,
    top_child_path: bytes | None = None,
    top_child_disk_bytes: int | None = None,
) -> DirectoryAggregateLike:
    return models_module.DirectoryAggregate(
        snapshot_id=snapshot_id,
        path=path,
        parent_path=parent_path,
        depth=depth,
        apparent_bytes=apparent_bytes,
        disk_bytes=disk_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
        collapsed=collapsed,
        collapse_reason=collapse_reason,
        collapsed_dirs=collapsed_dirs,
        top_child_path=top_child_path,
        top_child_disk_bytes=top_child_disk_bytes,
    )


def _mount(
    models_module,
    *,
    mount_id: int,
    parent_id: int,
    major_minor: str,
    root: bytes,
    mount_point: bytes,
    filesystem_type: str,
    mount_source: str,
) -> MountInfoLike:
    return models_module.MountInfo(
        mount_id=mount_id,
        parent_id=parent_id,
        major_minor=major_minor,
        root=root,
        mount_point=mount_point,
        options=("rw",),
        filesystem_type=filesystem_type,
        mount_source=mount_source,
        super_options=("rw",),
    )


def _seed_snapshot(
    connection,
    migrations_module,
    models_module,
    *,
    root_path: Path,
    status: str,
    started_at: str,
    finished_at: str,
    rows: list[DirectoryAggregateLike],
    mounts: list[MountInfoLike] | None = None,
    notes: str | None = None,
    error: str | None = None,
) -> int:
    snapshot = migrations_module.create_snapshot(connection, root_path, notes=notes)
    persisted_rows = [
        models_module.DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=row.path,
            parent_path=row.parent_path,
            depth=row.depth,
            apparent_bytes=row.apparent_bytes,
            disk_bytes=row.disk_bytes,
            file_count=row.file_count,
            dir_count=row.dir_count,
            error=row.error,
            collapsed=row.collapsed,
            collapse_reason=row.collapse_reason,
            collapsed_dirs=row.collapsed_dirs,
            top_child_path=row.top_child_path,
            top_child_disk_bytes=row.top_child_disk_bytes,
        )
        for row in rows
    ]
    if persisted_rows:
        migrations_module.insert_directory_rows(connection, persisted_rows, commit=False)
    if mounts:
        migrations_module.insert_snapshot_mounts(connection, snapshot.id, mounts, commit=False)
    migrations_module.finalize_snapshot(
        connection,
        snapshot.id,
        status=models_module.SnapshotStatus(status),
        notes=notes,
        error=error,
        commit=False,
    )
    connection.execute(
        "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
        (started_at, finished_at, snapshot.id),
    )
    connection.commit()
    return snapshot.id


def _section_by_root(payload: JsonDict, root_path: str) -> JsonDict:
    sections = payload["sections"]
    assert isinstance(sections, list)
    return next(section for section in sections if section["snapshot"]["root_path"] == root_path)


def _write_collect_config(config_path: Path, root_path: Path) -> None:
    config_path.write_text(
        textwrap.dedent(
            f"""
            [[roots]]
            path = "{root_path}"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_top_json_envelope_and_top_level_subtree_grouping(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=900,
                apparent_bytes=700,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/log",
                disk_bytes=600,
                apparent_bytes=590,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "2",
        "--group-by",
        "top-level-subtree",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "top"
    assert payload["snapshot_selector"] == "latest"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert payload["group_by"] == "top-level-subtree"
    assert payload["warnings"] == []
    assert len(payload["sections"]) == 1

    section = payload["sections"][0]
    assert section["snapshot"]["id"] == snapshot_id
    assert section["snapshot"]["root_path"] == "/srv"
    assert section["snapshot"]["status"] == "complete"
    assert section["snapshot"]["started_at"] == "2026-06-13T18:20:00Z"
    assert section["snapshot"]["finished_at"] == "2026-06-13T18:21:00Z"
    assert section["warnings"] == []
    assert [row["path"] for row in section["rows"]] == ["/srv", "/srv/cache"]
    assert section["rows"][0]["path_bytes_hex"] == b"/srv".hex()
    assert section["rows"][0]["current_disk_bytes"] == 1500
    assert section["rows"][0]["current_apparent_bytes"] == 1200
    assert section["rows"][0]["group"] == {"kind": "top-level-subtree", "key": "."}
    assert section["rows"][1]["group"] == {"kind": "top-level-subtree", "key": "cache"}


def test_snapshots_json_lists_snapshot_observability_summary(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    older_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1024,
                apparent_bytes=2048,
                depth=0,
                parent_path=None,
                file_count=10,
                dir_count=2,
            ),
        ],
    )
    newer_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T19:20:00Z",
        finished_at="2026-06-13T19:22:05Z",
        rows=[
            _directory_row(
                models_module,
                2,
                b"/srv",
                disk_bytes=1536,
                apparent_bytes=4096,
                depth=0,
                parent_path=None,
                file_count=12,
                dir_count=3,
            ),
            _directory_row(
                models_module,
                2,
                b"/srv/cache",
                disk_bytes=512,
                apparent_bytes=256,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="name",
                collapsed_dirs=7,
            ),
        ],
    )

    result = run_module(repo_root, "snapshots", "--db", str(db_path), "--limit", "2", "--json")

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "snapshots"
    assert payload["limit"] == 2
    summaries = payload["snapshots"]
    assert isinstance(summaries, list)
    assert [summary["snapshot"]["id"] for summary in summaries] == [newer_id, older_id]
    assert summaries[0]["processing_seconds"] == 125.0
    assert summaries[0]["processing_human"] == "2m5s"
    assert summaries[0]["row_count"] == 2
    assert summaries[0]["collapsed_row_count"] == 1
    assert summaries[0]["indexed_disk_bytes"] == 1536
    assert summaries[0]["indexed_disk_bytes_human"] == "1.5 KiB"
    assert summaries[0]["indexed_apparent_bytes"] == 4096
    assert summaries[0]["indexed_apparent_bytes_human"] == "4.0 KiB"
    assert summaries[0]["file_count"] == 12
    assert summaries[0]["dir_count"] == 3


def test_snapshots_text_includes_humanized_size_and_duration(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:01Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1024 * 1024,
                apparent_bytes=512 * 1024,
                depth=0,
                parent_path=None,
                file_count=10,
                dir_count=2,
            ),
        ],
    )

    result = run_module(repo_root, "snapshots", "--db", str(db_path), "--limit", "1")

    assert result.returncode == 0, result.stderr
    assert "Snapshots: showing 1 of up to 1" in result.stdout
    assert "ID" in result.stdout
    assert "Status" in result.stdout
    assert "Started" in result.stdout
    assert "Time" in result.stdout
    assert "Rows" in result.stdout
    assert "Disk" in result.stdout
    assert "Apparent" in result.stdout
    assert "Files" in result.stdout
    assert "Dirs" in result.stdout
    assert str(snapshot_id) in result.stdout
    assert "2026-06-13T18:20:00Z" in result.stdout
    assert "finished_at" not in result.stdout
    assert "1m1s" in result.stdout
    assert "1.0 MiB" in result.stdout
    assert "512.0 KiB" in result.stdout
    assert "10" in result.stdout


def test_snapshots_text_keeps_fractional_seconds_below_one_minute(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:20:03.1Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1024,
                apparent_bytes=1024,
                depth=0,
                parent_path=None,
            ),
        ],
    )

    result = run_module(repo_root, "snapshots", "--db", str(db_path), "--limit", "1")

    assert result.returncode == 0, result.stderr
    assert "3.1s" in result.stdout


def test_snapshots_text_compacts_large_count_columns(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:20:03.1Z",
        rows=[
            _directory_row(
                models_module,
                1,
                b"/srv",
                disk_bytes=1024,
                apparent_bytes=1024,
                depth=0,
                parent_path=None,
                file_count=2_031_980,
                dir_count=271_303,
                collapsed=True,
                collapsed_dirs=2_079,
            ),
        ],
    )

    result = run_module(repo_root, "snapshots", "--db", str(db_path), "--limit", "1")

    assert result.returncode == 0, result.stderr
    assert "2.0M" in result.stdout
    assert "271.3k" in result.stdout
    assert "1" in result.stdout
    assert "2,031,980" not in result.stdout


def test_snapshots_text_renders_empty_table_and_missing_counts(repo_root: Path) -> None:
    render = import_module(repo_root, "watchdirs.reporting.render")

    output = render.render_snapshots_text(limit=10, snapshots=())

    assert "Snapshots: showing 0 of up to 10" in output
    assert "ID" in output
    assert "Status" in output
    assert "Rows" in output


def test_snapshots_text_compacts_summary_counts_without_commas(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    render = import_module(repo_root, "watchdirs.reporting.render")

    snapshot = models_module.SnapshotRecord(
        id=42,
        started_at="2026-06-13T18:20:00Z",
        finished_at=None,
        root_path=Path("/srv"),
        status=models_module.SnapshotStatus.COMPLETE,
        notes=None,
        error=None,
    )
    summary = models_module.SnapshotSummary(
        snapshot=snapshot,
        processing_seconds=None,
        row_count=12_345,
        collapsed_row_count=2_079,
        error_row_count=1_234,
        indexed_apparent_bytes=None,
        indexed_disk_bytes=None,
        file_count=None,
        dir_count=None,
    )

    output = render.render_snapshots_text(limit=1, snapshots=(summary,))

    assert "12.3k" in output
    assert "2.1k" in output
    assert "1.2k" in output
    assert "12,345" not in output
    assert "2,079" not in output
    assert "1,234" not in output


def test_snapshots_renderers_keep_small_text_counts_and_raw_json(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    render = import_module(repo_root, "watchdirs.reporting.render")

    snapshot = models_module.SnapshotRecord(
        id=43,
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:20:03Z",
        root_path=Path("/srv"),
        status=models_module.SnapshotStatus.COMPLETE,
        notes=None,
        error=None,
    )
    summary = models_module.SnapshotSummary(
        snapshot=snapshot,
        processing_seconds=3.0,
        row_count=999,
        collapsed_row_count=12,
        error_row_count=0,
        indexed_apparent_bytes=1024,
        indexed_disk_bytes=2048,
        file_count=345,
        dir_count=67,
    )

    text_output = render.render_snapshots_text(limit=1, snapshots=(summary,))
    payload = render.render_snapshots_payload(limit=1, snapshots=(summary,))

    assert "999" in text_output
    assert "345" in text_output
    assert "999.0" not in text_output
    assert payload["snapshots"][0]["row_count"] == 999
    assert payload["snapshots"][0]["file_count"] == 345
    assert payload["snapshots"][0]["indexed_disk_bytes"] == 2048


def test_snapshots_renderers_show_running_status_consistently(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    render = import_module(repo_root, "watchdirs.reporting.render")

    snapshot = models_module.SnapshotRecord(
        id=44,
        started_at="2026-06-13T18:20:00Z",
        finished_at=None,
        root_path=Path("/srv"),
        status=models_module.SnapshotStatus.RUNNING,
        notes=None,
        error=None,
    )
    summary = models_module.SnapshotSummary(
        snapshot=snapshot,
        processing_seconds=None,
        row_count=0,
        collapsed_row_count=0,
        error_row_count=0,
        indexed_apparent_bytes=None,
        indexed_disk_bytes=None,
        file_count=None,
        dir_count=None,
    )

    text_output = render.render_snapshots_text(limit=1, snapshots=(summary,))
    payload = render.render_snapshots_payload(limit=1, snapshots=(summary,))

    assert "running" in text_output
    assert "failed" not in text_output
    assert payload["snapshots"][0]["display_status"] == "running"
    assert payload["snapshots"][0]["snapshot"]["status"] == "running"


def test_snapshots_json_normalizes_legacy_unfinished_failed_as_running(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, _migrations_module, _models_module = _open_db(repo_root, tmp_path)
    connection.execute(
        """
        INSERT INTO snapshots (started_at, finished_at, root_path, status, notes, error)
        VALUES (?, NULL, ?, 'failed', NULL, NULL)
        """,
        ("2026-06-13T18:20:00Z", "/srv"),
    )
    connection.commit()

    result = run_module(repo_root, "snapshots", "--db", str(db_path), "--limit", "1", "--json")

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["snapshots"][0]["display_status"] == "running"
    assert payload["snapshots"][0]["snapshot"]["status"] == "running"


def test_top_json_surfaces_warning_for_rows_outside_snapshot_root(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    snapshot_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:20:00Z",
        finished_at="2026-06-13T18:21:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/mystery", disk_bytes=1500, apparent_bytes=1200, depth=1, parent_path=b"/"
            ),
        ],
        error="permission denied",
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        str(snapshot_id),
        "--limit",
        "2",
        "--group-by",
        "top-level-subtree",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert {warning["code"] for warning in payload["warnings"]} == {"partial_snapshot", "path_outside_root"}
    assert {warning["code"] for warning in payload["sections"][0]["warnings"]} == {
        "partial_snapshot",
        "path_outside_root",
    }
    assert {
        "code": "path_outside_root",
        "message": "path '/mystery' is not under snapshot root '/srv'",
        "path": "/mystery",
    } in payload["sections"][0]["warnings"]
    assert payload["sections"][0]["rows"][0]["path"] == "/mystery"
    assert payload["sections"][0]["rows"][0]["group"] is None


def test_top_text_output_is_terse_and_labels_snapshot_status_and_current_sizes(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:22:00Z",
        finished_at="2026-06-13T18:23:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=900,
                apparent_bytes=700,
                depth=1,
                parent_path=b"/srv",
            ),
        ],
        error="permission denied",
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "2",
    )

    assert result.returncode == 0, result.stderr
    assert "snapshot=" in result.stdout
    assert "status=partial" in result.stdout
    assert "current_disk_bytes=" in result.stdout
    assert "current_apparent_bytes=" in result.stdout
    assert "permission denied" in result.stdout
    assert "rows:" not in result.stdout
    assert "children:" not in result.stdout


def test_top_renderers_escape_text_mode_fields_but_leave_json_payload_values_unchanged(repo_root: Path) -> None:
    models_module = import_module(repo_root, "watchdirs.models")
    render = import_module(repo_root, "watchdirs.reporting.render")

    warning = models_module.ReportWarning(
        code="path_spoof",
        message="bad\nmessage",
        path=b"/srv/warn\npath",
    )
    row = models_module.TopRow(
        snapshot_id=1,
        root_path=Path("/srv"),
        path=b"/srv/evil\nwarning code=fake message=hijacked",
        path_bytes_hex=b"/srv/evil\nwarning code=fake message=hijacked".hex(),
        depth=1,
        current_apparent_bytes=80,
        current_disk_bytes=90,
        file_count=1,
        dir_count=0,
        error="row\terror",
        group=models_module.GroupLabel(kind="top-level-subtree", key="evil\nsegment"),
    )
    snapshot = models_module.SnapshotRecord(
        id=1,
        started_at="2026-06-13T18:22:00Z",
        finished_at="2026-06-13T18:23:00Z",
        root_path=Path("/srv\nroot"),
        status=models_module.SnapshotStatus.PARTIAL,
        notes=None,
        error="permission\ndenied",
    )

    text = render.render_top_text(
        snapshot_selector="latest",
        limit=1,
        effective_limit=1,
        group_by="top-level-subtree",
        sections=[{"snapshot": snapshot, "warnings": (warning,), "rows": (row,)}],
    )
    payload = render.render_top_payload(
        snapshot_selector="latest",
        limit=1,
        effective_limit=1,
        group_by="top-level-subtree",
        sections=[{"snapshot": snapshot, "warnings": (warning,), "rows": (row,)}],
    )

    assert "root_path=/srv\\nroot" in text
    assert "error=permission\\ndenied" in text
    assert "path=/srv/warn\\npath" in text
    assert "message=bad\\nmessage" in text
    assert "path=/srv/evil\\nwarning code=fake message=hijacked" in text
    assert "group=top-level-subtree:evil\\nsegment" in text
    assert "error=row\\terror" in text
    assert "path=/srv/evil\nwarning code=fake message=hijacked" not in text
    assert "message=bad\nmessage" not in text

    section = payload["sections"][0]
    assert section["snapshot"]["root_path"] == "/srv\nroot"
    assert section["snapshot"]["error"] == "permission\ndenied"
    assert section["warnings"][0]["path"] == "/srv/warn\npath"
    assert section["warnings"][0]["message"] == "bad\nmessage"
    assert section["rows"][0]["path"] == "/srv/evil\nwarning code=fake message=hijacked"
    assert section["rows"][0]["group"] == {"kind": "top-level-subtree", "key": "evil\nsegment"}
    assert section["rows"][0]["error"] == "row\terror"


def test_report_json_returns_pairs_summary_groups_frontier_deleted_preview_and_warnings(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/old", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/shrink", disk_bytes=60, apparent_bytes=60, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/same", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T17:00:00Z",
        finished_at="2026-06-13T17:01:00Z",
        rows=[],
        error="scan crashed",
    )
    srv_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=300, apparent_bytes=300, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=200, apparent_bytes=200, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/shrink", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/same", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=50, apparent_bytes=50, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
    )

    result = run_module(
        repo_root,
        "report",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "2",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "report"
    assert payload["since"] == "24h"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert payload["group_by"] == "root"
    assert len(payload["pairs"]) == 2
    assert payload["classification_summary"]["counts"] == {
        "deleted": 1,
        "grown": 3,
        "shrunk": 1,
        "unchanged": 1,
    }
    assert payload["classification_summary"]["disk_bytes_delta_by_classification"]["grown"] == 240
    assert payload["frontier"][0]["path"] == "/srv/cache"
    assert payload["frontier"][0]["snapshot_pair"]["current_id"] == srv_current
    assert payload["frontier"][1]["path"] == "/var"
    assert payload["group_summary"] == [
        {
            "group": {"kind": "root", "key": "/srv"},
            "path_count": 1,
            "disk_bytes_delta": 190,
            "apparent_bytes_delta": 190,
        },
        {"group": {"kind": "root", "key": "/var"}, "path_count": 1, "disk_bytes_delta": 50, "apparent_bytes_delta": 50},
    ]
    assert payload["deleted_preview"][0]["path"] == "/srv/old"
    assert payload["deleted_preview"][0]["classification"] == "deleted"
    warning_codes = {warning["code"] for warning in payload["warnings"]}
    assert {"failed_snapshot_excluded", "partial_snapshot"} <= warning_codes


def test_report_json_applies_group_by_to_deleted_preview_rows(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/old", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=90, apparent_bytes=90, depth=1, parent_path=b"/srv"
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=21,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
    )

    result = run_module(
        repo_root,
        "report",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "2",
        "--group-by",
        "mount",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["group_by"] == "mount"
    assert payload["frontier"][0]["group"] == {
        "kind": "mount",
        "key": "/srv",
        "mount_point": "/srv",
    }
    assert payload["deleted_preview"][0]["group"] == {
        "kind": "mount",
        "key": "/srv",
        "mount_point": "/srv",
    }


def test_report_reuses_existing_diff_rows_for_deleted_preview(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = import_module(repo_root, "watchdirs.cli")
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/old", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=120, apparent_bytes=120, depth=0, parent_path=None)],
    )

    def fail_deleted_query(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("report must not run a second diff for deleted preview")

    monkeypatch.setattr(cli, "query_deleted_rows", fail_deleted_query)

    assert cli.main(["report", "--db", str(db_path), "--since", "24h", "--json"], allow_proxy=False) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted_preview"][0]["path"] == "/srv/old"


def test_report_json_keeps_hidden_by_collapse_out_of_deleted_preview(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=80, apparent_bytes=80, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module,
                1,
                b"/srv/cache/packages",
                disk_bytes=60,
                apparent_bytes=60,
                depth=2,
                parent_path=b"/srv/cache",
            ),
            _directory_row(
                models_module, 1, b"/srv/gone", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=80,
                apparent_bytes=80,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=1,
                top_child_path=b"/srv/cache/packages",
                top_child_disk_bytes=60,
            ),
        ],
    )

    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json")

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["classification_summary"]["counts"]["hidden_by_collapse"] == 1
    assert [row["path"] for row in payload["deleted_preview"]] == ["/srv/gone"]


def test_deleted_json_returns_baseline_only_rows_sorted_and_limited(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/old-big", disk_bytes=90, apparent_bytes=80, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/old-small", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=110, apparent_bytes=110, depth=0, parent_path=None)],
    )

    result = run_module(
        repo_root,
        "deleted",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "1",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "deleted"
    assert payload["limit"] == 1
    assert payload["effective_limit"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["path"] == "/srv/old-big"
    assert payload["rows"][0]["classification"] == "deleted"
    assert payload["rows"][0]["previous_disk_bytes"] == 90
    assert payload["rows"][0]["current_disk_bytes"] == 0
    assert payload["rows"][0]["disk_bytes_delta"] == -90
    assert payload["rows"][0]["snapshot_pair"]["baseline_id"] < payload["rows"][0]["snapshot_pair"]["current_id"]


def test_explain_path_json_normalizes_user_path_and_returns_drilldown_with_residuals(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    home_dir = tmp_path / "home"
    root_path = home_dir / "incident"
    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=300,
                apparent_bytes=300,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache")),
                disk_bytes=100,
                apparent_bytes=100,
                depth=1,
                parent_path=os.fsencode(str(root_path)),
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache" / "a")),
                disk_bytes=20,
                apparent_bytes=20,
                depth=2,
                parent_path=os.fsencode(str(root_path / "cache")),
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache" / "b")),
                disk_bytes=20,
                apparent_bytes=20,
                depth=2,
                parent_path=os.fsencode(str(root_path / "cache")),
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=460,
                apparent_bytes=460,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache")),
                disk_bytes=260,
                apparent_bytes=260,
                depth=1,
                parent_path=os.fsencode(str(root_path)),
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache" / "a")),
                disk_bytes=120,
                apparent_bytes=120,
                depth=2,
                parent_path=os.fsencode(str(root_path / "cache")),
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache" / "a" / "leaf")),
                disk_bytes=110,
                apparent_bytes=110,
                depth=3,
                parent_path=os.fsencode(str(root_path / "cache" / "a")),
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path / "cache" / "b")),
                disk_bytes=60,
                apparent_bytes=60,
                depth=2,
                parent_path=os.fsencode(str(root_path / "cache")),
            ),
        ],
        error="permission denied",
    )

    result = run_module(
        repo_root,
        "explain-path",
        "~/incident/cache/",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "1",
        "--depth",
        "2",
        "--group-by",
        "top-level-subtree",
        "--json",
        env={"HOME": str(home_dir)},
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "explain-path"
    assert payload["pairs"] == [
        {
            "root_path": str(root_path),
            "baseline": {
                "id": baseline_id,
                "root_path": str(root_path),
                "started_at": "2026-06-12T18:00:00Z",
                "finished_at": "2026-06-12T18:00:00Z",
                "status": "complete",
                "error": None,
            },
            "current": {
                "id": current_id,
                "root_path": str(root_path),
                "started_at": "2026-06-13T18:00:00Z",
                "finished_at": "2026-06-13T18:00:00Z",
                "status": "partial",
                "error": "permission denied",
            },
            "warning_codes": ["partial_snapshot"],
        }
    ]
    assert payload["target"]["path"] == str(root_path / "cache")
    assert payload["target"]["group"] == {"kind": "top-level-subtree", "key": "cache"}
    assert [row["path"] for row in payload["children"]] == [str(root_path / "cache" / "a")]
    assert payload["unshown_or_direct_disk_bytes_delta"] == 60
    assert payload["unshown_or_direct_apparent_bytes_delta"] == 60


@pytest.mark.parametrize(
    ("path_arg", "extra_rows", "limit_value", "depth_value", "expected_code"),
    [
        ("~/outside", [], "5", "1", "path_outside_roots"),
        ("~/incident/missing", [], "5", "1", "path_not_indexed"),
        ("~/incident/cache", ["/home/user/incident/cache"], "5", "1", "ambiguous_root"),
        ("~/incident/cache", [], "0", "1", "invalid_limit"),
        ("~/incident/cache", [], "5", "21", "invalid_depth"),
    ],
)
def test_explain_path_json_errors_for_scope_and_validation(
    repo_root: Path,
    tmp_path: Path,
    path_arg: str,
    extra_rows: list[str],
    limit_value: str,
    depth_value: str,
    expected_code: str,
) -> None:
    del extra_rows
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    home_dir = tmp_path / "home"
    incident_root = home_dir / "incident"
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=incident_root,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(incident_root)),
                disk_bytes=100,
                apparent_bytes=100,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(incident_root / "cache")),
                disk_bytes=50,
                apparent_bytes=50,
                depth=1,
                parent_path=os.fsencode(str(incident_root)),
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=incident_root,
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(incident_root)),
                disk_bytes=120,
                apparent_bytes=120,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(incident_root / "cache")),
                disk_bytes=80,
                apparent_bytes=80,
                depth=1,
                parent_path=os.fsencode(str(incident_root)),
            ),
        ],
    )
    if expected_code == "ambiguous_root":
        nested_root = incident_root / "nested"
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=nested_root,
            status="complete",
            started_at="2026-06-12T18:00:00Z",
            finished_at="2026-06-12T18:00:00Z",
            rows=[
                _directory_row(
                    models_module,
                    1,
                    os.fsencode(str(nested_root)),
                    disk_bytes=10,
                    apparent_bytes=10,
                    depth=0,
                    parent_path=None,
                )
            ],
        )
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=nested_root,
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            rows=[
                _directory_row(
                    models_module,
                    1,
                    os.fsencode(str(nested_root)),
                    disk_bytes=20,
                    apparent_bytes=20,
                    depth=0,
                    parent_path=None,
                ),
                _directory_row(
                    models_module,
                    1,
                    os.fsencode(str(nested_root / "cache")),
                    disk_bytes=15,
                    apparent_bytes=15,
                    depth=1,
                    parent_path=os.fsencode(str(nested_root)),
                ),
            ],
        )
        path_arg = "~/incident/nested/cache"

    result = run_module(
        repo_root,
        "explain-path",
        path_arg,
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        limit_value,
        "--depth",
        depth_value,
        "--json",
        env={"HOME": str(home_dir).replace("/tmp", "/tmp")},
    )

    payload = parse_json_output(result)
    assert result.returncode == 1, result.stderr
    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code


def test_report_deleted_and_explain_text_output_is_terse_and_labeled(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    root_path = Path("/srv")
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/old", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=120, apparent_bytes=120, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )

    report_result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h")
    deleted_result = run_module(repo_root, "deleted", "--db", str(db_path), "--since", "24h")
    explain_result = run_module(repo_root, "explain-path", "/srv/cache", "--db", str(db_path), "--since", "24h")

    assert report_result.returncode == 0, report_result.stderr
    assert "command=report" in report_result.stdout
    assert "directory_size_intervals" not in report_result.stdout
    assert "directory_size_diagnostics" not in report_result.stdout
    assert "children:" not in report_result.stdout

    assert deleted_result.returncode == 0, deleted_result.stderr
    assert "command=deleted" in deleted_result.stdout
    assert "classification=deleted" in deleted_result.stdout
    assert "rows:" not in deleted_result.stdout

    assert explain_result.returncode == 0, explain_result.stderr
    assert "command=explain-path" in explain_result.stdout
    assert "path=/srv/cache" in explain_result.stdout
    assert "scanner" not in explain_result.stdout


def test_explain_path_descendant_inside_collapsed_subtree_uses_collapsed_ancestor(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    root_path = Path("/srv")
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=40,
                apparent_bytes=40,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="known_noise",
                collapsed_dirs=10,
                top_child_path=b"/srv/cache/pip",
                top_child_disk_bytes=20,
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=160, apparent_bytes=160, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/cache",
                disk_bytes=120,
                apparent_bytes=120,
                depth=1,
                parent_path=b"/srv",
                collapsed=True,
                collapse_reason="fan_out",
                collapsed_dirs=200,
                top_child_path=b"/srv/cache/node_modules",
                top_child_disk_bytes=80,
            ),
        ],
        error="permission denied",
    )

    result = run_module(
        repo_root,
        "explain-path",
        "/srv/cache/deep/file.txt",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["target"]["path"] == "/srv/cache"
    assert payload["target"]["collapsed"] is True
    assert payload["target"]["collapse_reason"] == "fan_out"
    assert payload["target"]["top_child"]["path"] == "/srv/cache/node_modules"
    assert payload["children"] == []


def test_diff_end_to_end_incident_workflow_detects_positive_growth(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    root_path = tmp_path / "incident-root"
    cache_path = root_path / "cache"
    baseline_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=100,
                apparent_bytes=100,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(cache_path)),
                disk_bytes=20,
                apparent_bytes=20,
                depth=1,
                parent_path=os.fsencode(str(root_path)),
            ),
        ],
    )
    current_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=180,
                apparent_bytes=180,
                depth=0,
                parent_path=None,
            ),
            _directory_row(
                models_module,
                1,
                os.fsencode(str(cache_path)),
                disk_bytes=120,
                apparent_bytes=120,
                depth=1,
                parent_path=os.fsencode(str(root_path)),
            ),
        ],
    )

    diff_result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--json",
    )

    payload = parse_json_output(diff_result)
    assert diff_result.returncode == 0, diff_result.stderr
    cache_row = next(row for row in payload["rows"] if row["path"] == str(cache_path))
    assert cache_row["disk_bytes_delta"] > 0
    assert cache_row["snapshot_pair"] == {"baseline_id": baseline_id, "current_id": current_id}
    assert payload["pairs"] == [
        {
            "root_path": str(root_path),
            "baseline": {
                "id": baseline_id,
                "root_path": str(root_path),
                "started_at": "2026-06-12T18:00:00Z",
                "finished_at": "2026-06-12T18:00:00Z",
                "status": "complete",
                "error": None,
            },
            "current": {
                "id": current_id,
                "root_path": str(root_path),
                "started_at": "2026-06-13T18:00:00Z",
                "finished_at": "2026-06-13T18:00:00Z",
                "status": "complete",
                "error": None,
            },
            "warning_codes": [],
        }
    ]


def test_top_latest_returns_latest_usable_snapshot_per_root_with_partial_warnings(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:01:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1000, apparent_bytes=900, depth=0, parent_path=None)
        ],
    )
    failed_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T18:05:00Z",
        finished_at="2026-06-13T18:06:00Z",
        rows=[],
        error="scan crashed",
    )
    partial_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:10:00Z",
        finished_at="2026-06-13T18:11:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1200, apparent_bytes=950, depth=0, parent_path=None)
        ],
        error="permission denied",
    )
    latest_var = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T18:12:00Z",
        finished_at="2026-06-13T18:13:00Z",
        rows=[_directory_row(models_module, 1, b"/var", disk_bytes=600, apparent_bytes=600, depth=0, parent_path=None)],
    )

    result = run_module(repo_root, "top", "--db", str(db_path), "--snapshot", "latest", "--json")

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert len(payload["sections"]) == 2
    assert failed_id not in [section["snapshot"]["id"] for section in payload["sections"]]

    srv_section = _section_by_root(payload, "/srv")
    var_section = _section_by_root(payload, "/var")
    assert srv_section["snapshot"]["id"] == partial_id
    assert srv_section["snapshot"]["status"] == "partial"
    assert srv_section["snapshot"]["error"] == "permission denied"
    assert srv_section["warnings"]
    assert "partial" in srv_section["warnings"][0]["message"].lower()
    assert var_section["snapshot"]["id"] == latest_var
    assert var_section["snapshot"]["status"] == "complete"
    assert var_section["warnings"] == []


def test_top_numeric_snapshot_selector_returns_exact_snapshot_section(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    requested_id = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:30:00Z",
        finished_at="2026-06-13T18:31:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=500, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:32:00Z",
        finished_at="2026-06-13T18:33:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=900, apparent_bytes=800, depth=0, parent_path=None)],
    )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        str(requested_id),
        "--limit",
        "5",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert len(payload["sections"]) == 1
    assert payload["sections"][0]["snapshot"]["id"] == requested_id
    assert payload["sections"][0]["snapshot"]["root_path"] == "/srv"


@pytest.mark.parametrize(
    ("snapshot_selector", "limit_value", "seed_mode", "error_code"),
    [
        ("abc", "2", "usable", "invalid_snapshot_id"),
        ("999", "2", "usable", "snapshot_not_found"),
        ("latest", "2", "failed-only", "no_usable_snapshots"),
        ("latest", "0", "usable", "invalid_limit"),
        ("latest", "-1", "usable", "invalid_limit"),
        ("latest", "banana", "usable", "invalid_limit"),
        ("latest", "1001", "usable", "limit_too_large"),
    ],
)
def test_top_json_errors_for_invalid_snapshot_selectors_and_limits(
    repo_root: Path,
    tmp_path: Path,
    snapshot_selector: str,
    limit_value: str,
    seed_mode: str,
    error_code: str,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    if seed_mode == "usable":
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:40:00Z",
            finished_at="2026-06-13T18:41:00Z",
            rows=[
                _directory_row(models_module, 1, b"/srv", disk_bytes=500, apparent_bytes=500, depth=0, parent_path=None)
            ],
        )
    else:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="failed",
            started_at="2026-06-13T18:42:00Z",
            finished_at="2026-06-13T18:43:00Z",
            rows=[],
            error="scan crashed",
        )

    result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        snapshot_selector,
        "--limit",
        limit_value,
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 1, result.stderr
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code
    assert payload["error"]["message"]


def test_top_storage_domain_grouping_and_unknown_mount_contract(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:50:00Z",
        finished_at="2026-06-13T18:51:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=1500, apparent_bytes=1200, depth=0, parent_path=None),
            _directory_row(
                models_module,
                1,
                b"/srv/archive",
                disk_bytes=900,
                apparent_bytes=800,
                depth=1,
                parent_path=b"/srv",
            ),
            _directory_row(
                models_module,
                1,
                b"/mystery",
                disk_bytes=800,
                apparent_bytes=790,
                depth=1,
                parent_path=b"/",
            ),
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            ),
            _mount(
                models_module,
                mount_id=11,
                parent_id=10,
                major_minor="8:17",
                root=b"/",
                mount_point=b"/srv/archive",
                filesystem_type="xfs",
                mount_source="/dev/archive",
            ),
        ],
        error="permission denied",
    )

    mount_result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "5",
        "--group-by",
        "mount",
        "--json",
    )
    domain_result = run_module(
        repo_root,
        "top",
        "--db",
        str(db_path),
        "--snapshot",
        "latest",
        "--limit",
        "5",
        "--group-by",
        "storage-domain",
        "--json",
    )

    mount_payload = parse_json_output(mount_result)
    domain_payload = parse_json_output(domain_result)
    mount_rows = mount_payload["sections"][0]["rows"]
    domain_rows = domain_payload["sections"][0]["rows"]
    archive_mount = next(row for row in mount_rows if row["path"] == "/srv/archive")
    archive_domain = next(row for row in domain_rows if row["path"] == "/srv/archive")
    mystery_mount = next(row for row in mount_rows if row["path"] == "/mystery")
    mystery_domain = next(row for row in domain_rows if row["path"] == "/mystery")

    assert archive_mount["group"] == {
        "kind": "mount",
        "key": "/srv/archive",
        "mount_point": "/srv/archive",
    }
    assert archive_domain["group"] == {
        "kind": "storage-domain",
        "key": "8:17|/|xfs|/dev/archive",
        "mount_point": "/srv/archive",
        "filesystem_type": "xfs",
        "mount_source": "/dev/archive",
        "major_minor": "8:17",
        "root": "/",
    }
    assert mystery_mount["group"] is None
    assert mystery_domain["group"] is None
    mount_warning_codes = [warning["code"] for warning in mount_payload["sections"][0]["warnings"]]
    domain_warning_codes = [warning["code"] for warning in domain_payload["sections"][0]["warnings"]]
    assert "path_outside_root" in mount_warning_codes
    assert "path_outside_root" in domain_warning_codes


def test_diff_json_returns_global_growth_frontier_pair_metadata_and_warnings(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/log", disk_bytes=10, apparent_bytes=10, depth=1, parent_path=b"/srv"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="failed",
        started_at="2026-06-13T16:00:00Z",
        finished_at="2026-06-13T16:01:00Z",
        rows=[],
        error="scan crashed",
    )
    srv_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="partial",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/cache", disk_bytes=116, apparent_bytes=110, depth=1, parent_path=b"/srv"
            ),
            _directory_row(
                models_module, 1, b"/srv/log", disk_bytes=15, apparent_bytes=15, depth=1, parent_path=b"/srv"
            ),
        ],
        error="permission denied",
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-12T17:00:00Z",
        finished_at="2026-06-12T17:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/var", disk_bytes=100, apparent_bytes=90, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/var/tmp", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/var"
            ),
        ],
    )
    var_current = _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/var"),
        status="complete",
        started_at="2026-06-13T20:00:00Z",
        finished_at="2026-06-13T20:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/var", disk_bytes=220, apparent_bytes=200, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/var/tmp", disk_bytes=30, apparent_bytes=30, depth=1, parent_path=b"/var"
            ),
        ],
    )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "2",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    assert payload["command"] == "diff"
    assert payload["since"] == "24h"
    assert payload["limit"] == 2
    assert payload["effective_limit"] == 2
    assert payload["group_by"] == "root"
    assert len(payload["pairs"]) == 2
    assert {pair["root_path"] for pair in payload["pairs"]} == {"/srv", "/var"}
    srv_pair = next(pair for pair in payload["pairs"] if pair["root_path"] == "/srv")
    assert srv_pair["current"]["id"] == srv_current
    assert srv_pair["current"]["status"] == "partial"
    assert "partial_snapshot" in srv_pair["warning_codes"]
    assert [row["path"] for row in payload["rows"]] == ["/var", "/srv/cache"]
    assert payload["rows"][0]["disk_bytes_delta"] == 120
    assert payload["rows"][1]["disk_bytes_delta"] == 96
    assert payload["rows"][1]["suppressed_ancestor_count"] == 1
    assert payload["rows"][1]["snapshot_pair"] == {"baseline_id": srv_pair["baseline"]["id"], "current_id": srv_current}
    assert payload["classification_counts"]["grown"] >= 3
    warning_codes = {warning["code"] for warning in payload["warnings"]}
    assert {"failed_snapshot_excluded", "partial_snapshot"} <= warning_codes
    assert all("group" in row for row in payload["rows"])
    assert var_current in [pair["current"]["id"] for pair in payload["pairs"]]


def test_diff_json_top_level_subtree_grouping_uses_root_label_and_first_segment(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var", disk_bytes=40, apparent_bytes=40, depth=1, parent_path=b"/"),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/", disk_bytes=180, apparent_bytes=180, depth=0, parent_path=None),
            _directory_row(models_module, 1, b"/var", disk_bytes=120, apparent_bytes=120, depth=1, parent_path=b"/"),
            _directory_row(
                models_module, 1, b"/var/log", disk_bytes=118, apparent_bytes=118, depth=2, parent_path=b"/var"
            ),
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[_directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(models_module, 1, b"/srv", disk_bytes=150, apparent_bytes=150, depth=0, parent_path=None),
            _directory_row(
                models_module, 1, b"/srv/tmp", disk_bytes=20, apparent_bytes=20, depth=1, parent_path=b"/srv"
            ),
        ],
    )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--limit",
        "3",
        "--group-by",
        "top-level-subtree",
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["group_by"] == "top-level-subtree"
    assert payload["rows"][0]["group"] == {"kind": "top-level-subtree", "key": "var"}
    assert any(
        row["path"] == "/srv" and row["group"] == {"kind": "top-level-subtree", "key": "."} for row in payload["rows"]
    )


@pytest.mark.parametrize(
    ("since_value", "limit_value", "seed_snapshots", "error_code"),
    [
        ("24 h", "2", True, "invalid_since"),
        ("1h30m", "2", True, "invalid_since"),
        ("24h", "0", True, "invalid_limit"),
        ("24h", "1001", True, "limit_too_large"),
        ("24h", "2", False, "no_snapshot_pairs"),
    ],
)
def test_diff_json_errors_for_invalid_since_limit_and_missing_pairs(
    repo_root: Path,
    tmp_path: Path,
    since_value: str,
    limit_value: str,
    seed_snapshots: bool,
    error_code: str,
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    if seed_snapshots:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-12T18:00:00Z",
            finished_at="2026-06-12T18:00:00Z",
            rows=[
                _directory_row(models_module, 1, b"/srv", disk_bytes=100, apparent_bytes=100, depth=0, parent_path=None)
            ],
        )
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            rows=[
                _directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=200, depth=0, parent_path=None)
            ],
        )
    else:
        _seed_snapshot(
            connection,
            migrations_module,
            models_module,
            root_path=Path("/srv"),
            status="complete",
            started_at="2026-06-13T18:00:00Z",
            finished_at="2026-06-13T18:00:00Z",
            rows=[
                _directory_row(models_module, 1, b"/srv", disk_bytes=200, apparent_bytes=200, depth=0, parent_path=None)
            ],
        )

    result = run_module(
        repo_root,
        "diff",
        "--db",
        str(db_path),
        "--since",
        since_value,
        "--limit",
        limit_value,
        "--json",
    )

    payload = parse_json_output(result)
    assert result.returncode == 1, result.stderr
    assert payload["ok"] is False
    assert payload["error"]["code"] == error_code
    assert payload["error"]["message"]


# ---------------------------------------------------------------------------
# DIAG-03 / DIAG-05: report-time compact diagnostic hints and pressure summary.
#
# The report command computes a cheap df/index reconciliation for the indexed
# storage-domains only. A deterministic statvfs seam (WATCHDIRS_TEST_DF_STAT_JSON)
# maps a mount-point to {"size", "free"} byte totals, or to {"error": true} to
# simulate a stale/absent mountpoint OSError, so these tests never depend on the
# live host.
# ---------------------------------------------------------------------------


GIB = 1024**3


def _seed_domain_pair(
    connection,
    migrations_module,
    models_module,
    *,
    root_path: Path,
    baseline_disk: int,
    current_disk: int,
    major_minor: str,
    mount_source: str,
    mount_point: bytes,
    status: str = "complete",
) -> None:
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=baseline_disk,
                apparent_bytes=baseline_disk,
                depth=0,
                parent_path=None,
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor=major_minor,
                root=b"/",
                mount_point=mount_point,
                filesystem_type="ext4",
                mount_source=mount_source,
            )
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=root_path,
        status=status,
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(
                models_module,
                1,
                os.fsencode(str(root_path)),
                disk_bytes=current_disk,
                apparent_bytes=current_disk,
                depth=0,
                parent_path=None,
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor=major_minor,
                root=b"/",
                mount_point=mount_point,
                filesystem_type="ext4",
                mount_source=mount_source,
            )
        ],
        error="permission denied" if status != "complete" else None,
    )


def _df_stat_env(mapping: dict[str, dict[str, object]]) -> dict[str, str]:
    return {"WATCHDIRS_TEST_DF_STAT_JSON": json.dumps(mapping)}


def test_report_json_emits_diagnostic_hints_with_deleted_open_suspicion_on_full_coverage(
    repo_root: Path, tmp_path: Path
) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    connection.close()

    # df used = 200 - 20 = 180 GiB; indexed visible = 10 GiB -> material remainder.
    env = _df_stat_env({"/srv": {"size": 200 * GIB, "free": 20 * GIB}})
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert "diagnostic_hints" in payload
    hints = payload["diagnostic_hints"]
    assert isinstance(hints, list) and hints
    codes = {hint["code"] for hint in hints}
    assert "deleted_open_file_suspected" in codes
    assert "unattributed_usage" in codes
    # Bounded: hints point to the explicit verification commands, not inline probes.
    blob = json.dumps(payload)
    assert "deleted-open-files --json" in blob
    assert "df-vs-index --json" in blob
    assert "pressure_summary" in payload


def test_report_json_partial_coverage_does_not_emit_deleted_open_suspicion(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    # The indexed root /srv/app is a strict subtree of the live filesystem mount
    # point /srv, so the filesystem is broader than indexed coverage -> scope extends
    # and deleted-open suspicion from the remainder alone must be blocked.
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv/app"),
        status="complete",
        started_at="2026-06-12T18:00:00Z",
        finished_at="2026-06-12T18:00:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv/app", disk_bytes=8 * GIB, apparent_bytes=8 * GIB, depth=0, parent_path=None
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
    )
    _seed_snapshot(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv/app"),
        status="complete",
        started_at="2026-06-13T18:00:00Z",
        finished_at="2026-06-13T18:00:00Z",
        rows=[
            _directory_row(
                models_module, 1, b"/srv/app", disk_bytes=10 * GIB, apparent_bytes=10 * GIB, depth=0, parent_path=None
            )
        ],
        mounts=[
            _mount(
                models_module,
                mount_id=10,
                parent_id=1,
                major_minor="8:1",
                root=b"/",
                mount_point=b"/srv",
                filesystem_type="ext4",
                mount_source="/dev/root",
            )
        ],
    )
    connection.close()

    env = _df_stat_env({"/srv": {"size": 200 * GIB, "free": 20 * GIB}})
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    hints = payload["diagnostic_hints"]
    codes = {hint["code"] for hint in hints}
    # Partial filesystem coverage is surfaced and deleted-open suspicion is blocked.
    assert "filesystem_scope_extends_beyond_indexed_roots" in codes
    assert "deleted_open_file_suspected" not in codes


def test_report_json_partial_snapshot_blocks_deleted_open_suspicion(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
        status="partial",
    )
    connection.close()

    env = _df_stat_env({"/srv": {"size": 200 * GIB, "free": 20 * GIB}})
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    hints = payload["diagnostic_hints"]
    codes = {hint["code"] for hint in hints}
    assert "partial_snapshot_evidence" in codes
    assert "deleted_open_file_suspected" not in codes


def test_report_json_statvfs_called_only_for_indexed_domains(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    connection.close()

    # The seam records which mount points were probed. Only /srv is indexed, so an
    # unrelated mount point in the map must never be probed (report stays bounded).
    env = _df_stat_env({
        "/srv": {"size": 200 * GIB, "free": 20 * GIB},
        "/unrelated": {"size": 999 * GIB, "free": 1 * GIB},
    })
    env["WATCHDIRS_TEST_DF_STAT_RECORD"] = str(tmp_path / "stat_calls.txt")
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    assert result.returncode == 0, result.stderr
    recorded = (tmp_path / "stat_calls.txt").read_text().split()
    assert recorded == ["/srv"]


def test_report_json_statvfs_failure_for_one_domain_does_not_crash_report(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/data"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:33",
        mount_source="/dev/data",
        mount_point=b"/data",
    )
    connection.close()

    env = _df_stat_env({
        "/srv": {"error": True},
        "/data": {"size": 200 * GIB, "free": 20 * GIB},
    })
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["ok"] is True
    blob = json.dumps(payload)
    # The stale/absent mountpoint surfaces as a warning or hint and the report still
    # contains other diagnostic hints / sections.
    assert "filesystem_stat_unavailable" in blob
    hints = payload["diagnostic_hints"]
    codes = {hint["code"] for hint in hints}
    # /data still produced material remainder hints.
    assert "unattributed_usage" in codes or "deleted_open_file_suspected" in codes


def test_report_json_pressure_summary_has_storage_domain_fields_and_truncation(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    connection.close()

    env = _df_stat_env({"/srv": {"size": 200 * GIB, "free": 20 * GIB}})
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    summary = payload["pressure_summary"]
    assert "sections" in summary
    assert "limits" in summary
    assert "truncated_sections" in summary
    assert summary["limits"]["max_sections"] == 4
    assert summary["limits"]["max_items_per_section"] == 5
    section = summary["sections"][0]
    assert "storage_domain_key" in section
    assert "unattributed_bytes" in section
    assert "filesystem_usage_ratio" in section
    assert "indexed_visible_disk_bytes" in section
    assert "over_indexed_bytes" in section
    assert "recent_growth_disk_bytes" in section
    assert isinstance(section["facts"], list)
    assert isinstance(section["next_checks"], list)
    assert len(section["facts"]) <= 5
    assert len(section["next_checks"]) <= 5
    # D-17: cautious wording, no destructive guidance.
    blob = json.dumps(payload)
    for token in ("rm -rf", "docker builder prune", "is safe"):
        assert token not in blob


def test_report_storage_domain_growth_joins_into_pressure_summary_recent_growth(
    repo_root: Path, tmp_path: Path
) -> None:
    # WR-01 regression lock: an end-to-end `report --group-by storage-domain` run
    # must populate the pressure section's recent_growth_disk_bytes via the
    # cross-path key contract. The report group key is produced by
    # resolve_group_for_path's storage-domain branch; the df/index section key is
    # produced by queries._domain_key. They share the identical
    # "major_minor|root|fs|source" format today, so the growth join lands. If
    # either key format, or the `args.group_by == "storage-domain"` gate, ever
    # drifts, this test fails instead of silently zeroing the growth column again
    # (the original WR-03 regression).
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    connection.close()

    env = _df_stat_env({"/srv": {"size": 200 * GIB, "free": 20 * GIB}})
    result = run_module(
        repo_root,
        "report",
        "--db",
        str(db_path),
        "--since",
        "24h",
        "--group-by",
        "storage-domain",
        "--json",
        env=env,
    )

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    assert payload["group_by"] == "storage-domain"

    expected_domain_key = "8:1|/|ext4|/dev/root"
    expected_growth = 2 * GIB  # current_disk - baseline_disk at the /srv root row.

    # The report group summary attributes the growth to the storage-domain key.
    growth_groups = {
        group["group"]["key"]: group["disk_bytes_delta"]
        for group in payload["group_summary"]
        if group["group"] is not None and group["group"]["kind"] == "storage-domain"
    }
    assert growth_groups.get(expected_domain_key) == expected_growth

    # The pressure summary section keyed by the SAME domain key carries that growth
    # through the cross-path join (this is the contract WR-03 fixed and WR-01 locks).
    sections = payload["pressure_summary"]["sections"]
    matching = next(section for section in sections if section["storage_domain_key"] == expected_domain_key)
    assert matching["recent_growth_disk_bytes"] == expected_growth


def test_report_json_below_threshold_has_no_deleted_open_suspicion(repo_root: Path, tmp_path: Path) -> None:
    db_path, connection, migrations_module, models_module = _open_db(repo_root, tmp_path)
    _seed_domain_pair(
        connection,
        migrations_module,
        models_module,
        root_path=Path("/srv"),
        baseline_disk=8 * GIB,
        current_disk=10 * GIB,
        major_minor="8:1",
        mount_source="/dev/root",
        mount_point=b"/srv",
    )
    connection.close()

    # Remainder under the 1 GiB floor: used ~10 GiB + 100 MiB, indexed 10 GiB.
    env = _df_stat_env({"/srv": {"size": 100 * GIB, "free": 100 * GIB - (10 * GIB + 100 * 1024 * 1024)}})
    result = run_module(repo_root, "report", "--db", str(db_path), "--since", "24h", "--json", env=env)

    payload = parse_json_output(result)
    assert result.returncode == 0, result.stderr
    hints = payload.get("diagnostic_hints", [])
    codes = {hint["code"] for hint in hints}
    assert "deleted_open_file_suspected" not in codes
