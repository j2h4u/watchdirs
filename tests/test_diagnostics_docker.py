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
# Helpers: synthetic `docker system df --format json` (NDJSON) and
# `docker buildx du --format json` output. Modern Docker emits one JSON object
# per line for `system df --format json` (Type/TotalCount/Active/Size/Reclaimable
# fields). `buildx du --format json` emits one JSON object per build-cache record.
# ---------------------------------------------------------------------------


def _system_df_line(*, kind: str, total: int, active: int, size: str, reclaimable: str) -> bytes:
    return (
        json.dumps(
            {
                "Type": kind,
                "TotalCount": total,
                "Active": active,
                "Size": size,
                "Reclaimable": reclaimable,
            }
        ).encode("utf-8")
        + b"\n"
    )


def _system_df_ndjson() -> bytes:
    return (
        _system_df_line(kind="Images", total=42, active=10, size="20GB", reclaimable="12GB (60%)")
        + _system_df_line(kind="Containers", total=8, active=3, size="500MB", reclaimable="400MB (80%)")
        + _system_df_line(kind="Local Volumes", total=15, active=5, size="6GB", reclaimable="2GB (33%)")
        + _system_df_line(kind="Build Cache", total=120, active=0, size="9GB", reclaimable="9GB (100%)")
    )


def _buildx_du_line(*, cache_id: str, size: int, reclaimable: bool, last_used: str | None = None) -> bytes:
    record: dict[str, object] = {
        "ID": cache_id,
        "Size": size,
        "Reclaimable": reclaimable,
    }
    if last_used is not None:
        record["LastUsedAt"] = last_used
    return json.dumps(record).encode("utf-8") + b"\n"


def _buildx_du_ndjson() -> bytes:
    return (
        _buildx_du_line(cache_id="aaa", size=3 * GIB, reclaimable=True)
        + _buildx_du_line(cache_id="bbb", size=2 * GIB, reclaimable=False)
        + _buildx_du_line(cache_id="ccc", size=1 * GIB, reclaimable=True)
    )


def _fake_docker_runner(responses: dict[tuple[str, ...], tuple[bytes, bytes, int]],
                        *, missing: bool = False):
    """Return a runner(argv) seam matching the docker_runner contract.

    ``responses`` maps a normalized argv key (the argv minus the leading
    "docker") to ``(stdout, stderr, returncode)``. Unmatched argv yields an
    empty successful response. ``missing=True`` raises FileNotFoundError to
    model an absent Docker CLI.
    """

    captured: dict[str, object] = {"argvs": []}

    def runner(argv: list[str]):
        captured["argvs"].append(list(argv))  # type: ignore[union-attr]
        if missing:
            raise FileNotFoundError("docker")
        key = tuple(argv[1:]) if argv and argv[0] == "docker" else tuple(argv)
        return responses.get(key, (b"", b"", 0))

    runner.captured = captured  # type: ignore[attr-defined]
    return runner


def _system_df_key() -> tuple[str, ...]:
    return ("system", "df", "--format", "json")


def _buildx_du_key() -> tuple[str, ...]:
    return ("buildx", "du", "--format", "json")


# ---------------------------------------------------------------------------
# Test 1: `docker system df --format json` NDJSON normalizes categories.
# ---------------------------------------------------------------------------


def test_parse_docker_system_df_normalizes_categories(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    categories, warnings = docker.parse_docker_system_df(_system_df_ndjson())

    by_kind = {category.kind: category for category in categories}
    # D-11: total/reclaimable rows per Docker category.
    assert set(by_kind) == {"Images", "Containers", "Local Volumes", "Build Cache"}
    images = by_kind["Images"]
    assert images.total_count == 42
    assert images.active_count == 10
    assert images.size_text == "20GB"
    assert images.reclaimable_text == "12GB (60%)"
    assert images.source_command == "docker system df --format json"
    # Build cache category is present and grouped under its own kind.
    assert by_kind["Build Cache"].total_count == 120
    assert warnings == []


def test_parse_docker_system_df_tolerates_blank_and_malformed_lines(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    stdout = (
        _system_df_line(kind="Images", total=1, active=1, size="1GB", reclaimable="0B (0%)")
        + b"\n"  # blank line
        + b"{not valid json}\n"  # malformed
        + _system_df_line(kind="Containers", total=2, active=0, size="2GB", reclaimable="2GB (100%)")
    )

    categories, warnings = docker.parse_docker_system_df(stdout)

    kinds = {category.kind for category in categories}
    assert kinds == {"Images", "Containers"}
    warning_codes = {warning.code for warning in warnings}
    assert "docker_malformed_output" in warning_codes


def test_parse_docker_system_df_accepts_single_json_array_output(repo_root: Path) -> None:
    """Some Docker clients emit a single JSON array instead of NDJSON (WR-02).

    The whole payload must not be discarded; each object element is accepted.
    """

    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    array_payload = json.dumps(
        [
            {"Type": "Images", "TotalCount": 5, "Active": 2, "Size": "10GB", "Reclaimable": "4GB (40%)"},
            {"Type": "Containers", "TotalCount": 3, "Active": 1, "Size": "1GB", "Reclaimable": "1GB (100%)"},
        ]
    ).encode("utf-8")

    categories, warnings = docker.parse_docker_system_df(array_payload)

    by_kind = {category.kind: category for category in categories}
    assert set(by_kind) == {"Images", "Containers"}
    assert by_kind["Images"].total_count == 5
    assert by_kind["Containers"].size_text == "1GB"
    assert warnings == []


def test_parse_docker_system_df_array_skips_non_object_elements_with_warning(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    array_payload = json.dumps(
        [
            {"Type": "Images", "TotalCount": 1, "Active": 1, "Size": "1GB", "Reclaimable": "0B (0%)"},
            "not-an-object",
        ]
    ).encode("utf-8")

    categories, warnings = docker.parse_docker_system_df(array_payload)

    assert {category.kind for category in categories} == {"Images"}
    assert {warning.code for warning in warnings} == {"docker_malformed_output"}


# ---------------------------------------------------------------------------
# Test 2: `docker buildx du --format json` normalizes build-cache rows + totals.
# ---------------------------------------------------------------------------


def test_parse_docker_buildx_du_normalizes_build_cache(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    entries, totals, warnings = docker.parse_docker_buildx_du(_buildx_du_ndjson())

    assert len(entries) == 3
    assert {entry.cache_id for entry in entries} == {"aaa", "bbb", "ccc"}
    by_id = {entry.cache_id: entry for entry in entries}
    assert by_id["aaa"].size_bytes == 3 * GIB
    assert by_id["aaa"].reclaimable is True
    assert by_id["bbb"].reclaimable is False
    assert by_id["aaa"].source_command == "docker buildx du --format json"
    # Totals separate reclaimable from total bytes.
    assert totals.total_bytes == 6 * GIB
    assert totals.reclaimable_bytes == 4 * GIB
    assert warnings == []


def test_parse_docker_buildx_du_accepts_human_string_sizes(repo_root: Path) -> None:
    """Real ``docker buildx du --format json`` emits Size as a human string.

    Current Docker clients emit ``"Size":"8.192kB"`` (and ``"7.451GB"``) rather
    than a raw byte integer; the parser must convert those or every total is 0.
    """
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    stdout = (
        b'{"ID":"aaa","Size":"7.451GB","Reclaimable":true,"LastUsedAt":"About an hour ago"}\n'
        b'{"ID":"bbb","Size":"8.192kB","Reclaimable":false}\n'
    )

    entries, totals, warnings = docker.parse_docker_buildx_du(stdout)

    by_id = {entry.cache_id: entry for entry in entries}
    assert by_id["aaa"].size_bytes == int(7.451 * 1000 ** 3)
    assert by_id["bbb"].size_bytes == int(8.192 * 1000)
    assert totals.total_bytes == by_id["aaa"].size_bytes + by_id["bbb"].size_bytes
    assert totals.reclaimable_bytes == by_id["aaa"].size_bytes
    assert warnings == []


def test_parse_docker_buildx_du_blank_output_is_not_an_error(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    entries, totals, warnings = docker.parse_docker_buildx_du(b"")

    assert entries == []
    assert totals.total_bytes == 0
    assert totals.reclaimable_bytes == 0
    assert warnings == []


# ---------------------------------------------------------------------------
# Test 3: Docker absence / daemon errors / empty / malformed degrade to warnings
# without breaking non-Docker diagnostics.
# ---------------------------------------------------------------------------


def test_collect_docker_unavailable_degrades_to_warnings(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner({}, missing=True)
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert enrichment.ok is True  # never crashes other diagnostics
    assert enrichment.docker_available is False
    assert enrichment.categories == ()
    assert enrichment.build_cache_entries == ()
    warning_codes = {warning.code for warning in enrichment.warnings}
    assert "docker_unavailable" in warning_codes


def test_collect_docker_daemon_error_degrades_to_warning(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {
            _system_df_key(): (b"", b"Cannot connect to the Docker daemon", 1),
            _buildx_du_key(): (b"", b"Cannot connect to the Docker daemon", 1),
        }
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert enrichment.ok is True
    assert enrichment.docker_available is False
    warning_codes = {warning.code for warning in enrichment.warnings}
    assert "docker_daemon_error" in warning_codes or "docker_command_failed" in warning_codes


def test_collect_docker_success_groups_categories_and_build_cache(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {
            _system_df_key(): (_system_df_ndjson(), b"", 0),
            _buildx_du_key(): (_buildx_du_ndjson(), b"", 0),
        }
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    assert enrichment.ok is True
    assert enrichment.docker_available is True
    kinds = {category.kind for category in enrichment.categories}
    assert {"Images", "Containers", "Local Volumes", "Build Cache"} <= kinds
    assert len(enrichment.build_cache_entries) == 3
    assert enrichment.build_cache_totals.total_bytes == 6 * GIB
    assert enrichment.build_cache_totals.reclaimable_bytes == 4 * GIB


# ---------------------------------------------------------------------------
# Test 4: indexed paths include /var/lib/docker and /var/lib/containerd hints.
# ---------------------------------------------------------------------------


def test_indexed_path_hints_include_docker_and_containerd(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {_system_df_key(): (_system_df_ndjson(), b"", 0)}
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        indexed_path_hints=(b"/var/lib/docker", b"/var/lib/containerd", b"/home/x"),
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    docker_hints = {os.fsdecode(path) for path in enrichment.docker_path_hints}
    assert "/var/lib/docker" in docker_hints
    containerd_hints = {os.fsdecode(path) for path in enrichment.containerd_path_hints}
    assert "/var/lib/containerd" in containerd_hints


# ---------------------------------------------------------------------------
# Test 4b: `_collect_indexed_docker_path_hints` resolves docker/containerd
# prefixes through the path-dictionary JOIN, binding raw byte prefixes to the
# GLOB parameter (regression for the D-01 dictionary rewrite).
# ---------------------------------------------------------------------------


def test_collect_indexed_docker_path_hints_resolves_via_dictionary_join(
    repo_root: Path, tmp_path: Path
) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations = import_module(repo_root, "watchdirs.db.migrations")
    models = import_module(repo_root, "watchdirs.models")
    cli = import_module(repo_root, "watchdirs.cli")

    connection = connection_module.open_connection(tmp_path / "watchdirs.sqlite3")
    migrations.initialize_database(connection)

    root = Path("/var/lib/docker")
    snapshot = migrations.create_snapshot(connection, root)
    rows = [
        models.DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=b"/var/lib/docker",
            parent_path=None,
            depth=0,
            apparent_bytes=10,
            disk_bytes=10,
            file_count=0,
            dir_count=1,
            error=None,
        ),
        models.DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=b"/var/lib/docker/overlay2",
            parent_path=b"/var/lib/docker",
            depth=1,
            apparent_bytes=8,
            disk_bytes=8,
            file_count=0,
            dir_count=0,
            error=None,
        ),
        # A non-docker sibling that must NOT be surfaced by the GLOB.
        models.DirectoryAggregate(
            snapshot_id=snapshot.id,
            path=b"/var/lib/dockerfoo",
            parent_path=None,
            depth=0,
            apparent_bytes=3,
            disk_bytes=3,
            file_count=0,
            dir_count=0,
            error=None,
        ),
    ]
    migrations.insert_directory_rows(connection, rows, commit=False)
    migrations.finalize_snapshot(
        connection,
        snapshot.id,
        status=models.SnapshotStatus.COMPLETE,
        notes=None,
        error=None,
        commit=False,
    )
    connection.commit()

    hints = cli._collect_indexed_docker_path_hints(connection)

    assert b"/var/lib/docker" in hints
    assert b"/var/lib/docker/overlay2" in hints
    # The prefix-bound GLOB (`prefix + b"/*"`) must not match `dockerfoo`.
    assert b"/var/lib/dockerfoo" not in hints
    # Paths come back as raw bytes through the dictionary JOIN.
    assert all(isinstance(path, bytes) for path in hints)


# ---------------------------------------------------------------------------
# Test 5: containerd path hints WITHOUT a native probe emit explicit
# unavailable fields and never fabricate containerd category totals.
# ---------------------------------------------------------------------------


def test_containerd_path_hints_emit_unavailable_not_category_totals(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {_system_df_key(): (_system_df_ndjson(), b"", 0)}
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        indexed_path_hints=(b"/var/lib/containerd",),
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    # Explicit unavailable containerd state.
    assert enrichment.containerd_available is False
    assert b"/var/lib/containerd" in enrichment.containerd_path_hints
    warning_codes = {warning.code for warning in enrichment.warnings}
    assert "containerd_enrichment_unavailable" in warning_codes

    # No fabricated containerd category totals: every Docker category kind must
    # come only from the Docker probes, never from a containerd path name.
    for category in enrichment.categories:
        assert "containerd" not in category.kind.lower()


def test_no_containerd_warning_when_no_containerd_hint(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {_system_df_key(): (_system_df_ndjson(), b"", 0)}
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        indexed_path_hints=(b"/var/lib/docker",),
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    warning_codes = {warning.code for warning in enrichment.warnings}
    assert "containerd_enrichment_unavailable" not in warning_codes
    assert enrichment.containerd_path_hints == ()


# ---------------------------------------------------------------------------
# Test 6: read-only, fixed argv; no Docker mutation commands anywhere.
# ---------------------------------------------------------------------------


def test_collect_invokes_fixed_read_only_docker_argv(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {
            _system_df_key(): (_system_df_ndjson(), b"", 0),
            _buildx_du_key(): (_buildx_du_ndjson(), b"", 0),
        }
    )
    docker.collect_docker_enrichment(
        docker_runner=runner,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    forbidden = ("prune", "rm", "rmi", "stop", "kill", "down", "remove", "delete", "reload")
    for argv in runner.captured["argvs"]:  # type: ignore[index]
        assert argv[0] == "docker"
        for token in argv:
            assert token not in forbidden
            assert ";" not in token and "|" not in token and "&" not in token


def test_docker_module_source_contains_no_mutation_commands(repo_root: Path) -> None:
    """D-13: the module must never embed Docker mutation/cleanup commands."""
    docker_path = repo_root / "src" / "watchdirs" / "diagnostics" / "docker.py"
    source = docker_path.read_text(encoding="utf-8").lower()
    for forbidden in (
        "docker builder prune",
        "docker image prune",
        "docker system prune",
        "docker volume prune",
        "docker container prune",
        "buildx prune",
        "docker rm",
        "docker rmi",
        "docker stop",
        "docker kill",
        "docker compose down",
    ):
        assert forbidden not in source, f"mutation command leaked into module: {forbidden}"


def test_verification_commands_are_read_only(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")

    runner = _fake_docker_runner(
        {
            _system_df_key(): (_system_df_ndjson(), b"", 0),
            _buildx_du_key(): (_buildx_du_ndjson(), b"", 0),
        }
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    rendered = " ".join(enrichment.verification_commands).lower()
    for forbidden in ("prune", "rm ", "rmi", "stop", "kill", "down", "delete"):
        assert forbidden not in rendered
    # The documented read-only probes must appear as next checks.
    assert "docker system df" in rendered
    assert "docker buildx du" in rendered


# ---------------------------------------------------------------------------
# Render + CLI: stable JSON/text envelope, top-N limiting, truncation metadata.
# ---------------------------------------------------------------------------


def test_render_docker_enrichment_payload_and_text(repo_root: Path) -> None:
    docker = import_module(repo_root, "watchdirs.diagnostics.docker")
    render = import_module(repo_root, "watchdirs.reporting.render")

    runner = _fake_docker_runner(
        {
            _system_df_key(): (_system_df_ndjson(), b"", 0),
            _buildx_du_key(): (_buildx_du_ndjson(), b"", 0),
        }
    )
    enrichment = docker.collect_docker_enrichment(
        docker_runner=runner,
        indexed_path_hints=(b"/var/lib/containerd",),
        limit=2,
        generated_at_provider=lambda: "2026-06-14T09:00:00Z",
    )

    payload = render.render_docker_enrichment_payload(enrichment)
    assert payload["ok"] is True
    assert payload["command"] == "docker-enrichment"
    assert payload["docker_available"] is True
    assert payload["containerd_available"] is False
    assert "/var/lib/containerd" in payload["containerd_path_hints"]
    assert "categories" in payload
    assert "build_cache" in payload
    # Build cache entries are limited to top-N with truncation metadata.
    assert len(payload["build_cache"]["entries"]) == 2
    assert payload["build_cache"]["truncated"] is True
    assert "verification_commands" in payload
    assert "warnings" in payload

    text = render.render_docker_enrichment_text(enrichment)
    assert "command=docker-enrichment" in text
    assert "docker_available=true" in text
    assert "containerd_available=false" in text


def test_cli_docker_enrichment_json_envelope_when_docker_absent(repo_root: Path, tmp_path: Path) -> None:
    connection_module = import_module(repo_root, "watchdirs.db.connection")
    migrations_module = import_module(repo_root, "watchdirs.db.migrations")
    db_path = tmp_path / "watchdirs.sqlite3"
    connection = connection_module.open_connection(db_path)
    migrations_module.initialize_database(connection)
    connection.close()

    env = os.environ.copy()
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}:{env['PYTHONPATH']}"
    # Force the absent-Docker seam so the CLI envelope test does not depend on a
    # live Docker daemon.
    env["WATCHDIRS_TEST_NO_DOCKER"] = "1"

    result = subprocess.run(
        ["python3", "-m", "watchdirs", "docker-enrichment", "--db", str(db_path), "--json", "--limit", "5"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, f"stderr={result.stderr!r}"
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "docker-enrichment"
    assert payload["docker_available"] is False
    assert payload["limit"] == 5
    assert "categories" in payload
    assert "build_cache" in payload
    assert "containerd_available" in payload
    assert "verification_commands" in payload
    assert "warnings" in payload
    assert "generated_at" in payload
