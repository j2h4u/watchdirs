from __future__ import annotations

from pathlib import Path


UNIT_DIR = Path("ops/systemd")

EXPECTED_UNIT_TEXT = {
    "watchdirs-collect.service": (
        "Type=oneshot",
        "Environment=PYTHONUNBUFFERED=1",
        "ExecStart=/usr/local/bin/watchdirs collect --config /etc/watchdirs/watchdirs.toml --db /var/lib/watchdirs/watchdirs.sqlite3 --json --verbose",
        "StateDirectory=watchdirs",
        "ConfigurationDirectory=watchdirs",
        "UMask=0077",
    ),
    "watchdirs-collect.timer": (
        "OnCalendar=hourly",
        "Persistent=true",
        "Unit=watchdirs-collect.service",
    ),
    "watchdirs-prune.service": (
        "Type=oneshot",
        "Environment=PYTHONUNBUFFERED=1",
        "ExecStart=/usr/local/bin/watchdirs prune --db /var/lib/watchdirs/watchdirs.sqlite3 --hourly-days 14 --daily-days 90 --json",
        "StateDirectory=watchdirs",
        "ConfigurationDirectory=watchdirs",
        "UMask=0077",
    ),
    "watchdirs-prune.timer": (
        "OnCalendar=*-*-* 00:17:00",
        "RandomizedDelaySec=300",
        "Persistent=true",
        "Unit=watchdirs-prune.service",
    ),
    "watchdirs-vacuum.service": (
        "Type=oneshot",
        "Environment=PYTHONUNBUFFERED=1",
        "ExecStart=/usr/local/bin/watchdirs vacuum --db /var/lib/watchdirs/watchdirs.sqlite3 --json",
        "StateDirectory=watchdirs",
        "ConfigurationDirectory=watchdirs",
        "UMask=0077",
    ),
    "watchdirs-vacuum.timer": (
        "OnCalendar=Sun *-*-* 03:17:00",
        "Persistent=true",
        "Unit=watchdirs-vacuum.service",
    ),
}


def _read_unit(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_systemd_unit_files_exist_and_use_oneshot(repo_root: Path) -> None:
    for name, expected_lines in EXPECTED_UNIT_TEXT.items():
        path = repo_root / UNIT_DIR / name
        assert path.exists(), f"missing unit file: {path}"
        text = _read_unit(path)
        for expected in expected_lines:
            assert expected in text
        if name.endswith(".service"):
            assert "Type=oneshot" in text


def test_collect_service_low_priority_settings(repo_root: Path) -> None:
    text = _read_unit(repo_root / UNIT_DIR / "watchdirs-collect.service")

    assert "Nice=19" in text
    assert "IOSchedulingClass=best-effort" in text
    assert "IOSchedulingPriority=7" in text
    assert "ExecStart=/usr/local/bin/watchdirs collect" in text


def test_timers_are_persistent_and_prune_avoids_hourly_collision(repo_root: Path) -> None:
    collect_timer = _read_unit(repo_root / UNIT_DIR / "watchdirs-collect.timer")
    prune_timer = _read_unit(repo_root / UNIT_DIR / "watchdirs-prune.timer")
    vacuum_timer = _read_unit(repo_root / UNIT_DIR / "watchdirs-vacuum.timer")

    assert "Persistent=true" in collect_timer
    assert "Persistent=true" in prune_timer
    assert "Persistent=true" in vacuum_timer
    assert "OnCalendar=*-*-* 00:17:00" in prune_timer
    assert "RandomizedDelaySec=300" in prune_timer


def test_ops_assets_do_not_introduce_cron_or_cleanup_hooks(repo_root: Path) -> None:
    ops_dir = repo_root / "ops"
    assert not list(ops_dir.rglob("*cron*"))

    forbidden = (
        "docker prune",
        "docker builder prune",
        "docker image prune",
        "docker system prune",
        "logrotate",
        "cleanup",
        "systemctl stop",
    )
    for path in (repo_root / UNIT_DIR).iterdir():
        text = _read_unit(path)
        for token in forbidden:
            assert token not in text


def test_readme_documents_operations_and_verification_commands(repo_root: Path) -> None:
    text = _read_unit(repo_root / "README.md")

    required = (
        "/usr/local/bin/watchdirs",
        "/etc/watchdirs/watchdirs.toml",
        "/var/lib/watchdirs/watchdirs.sqlite3",
        "watchdirs-collect.timer",
        "watchdirs-prune.timer",
        "watchdirs-vacuum.timer",
        "systemd-analyze verify ops/systemd/*.service ops/systemd/*.timer",
        "test -x /usr/local/bin/watchdirs",
        "/usr/local/bin/watchdirs --help",
        "systemctl list-timers 'watchdirs-*'",
        "systemctl status watchdirs-collect.timer watchdirs-prune.timer watchdirs-vacuum.timer",
        "journalctl -u watchdirs-collect.service -u watchdirs-prune.service -u watchdirs-vacuum.service",
        "/usr/local/bin/watchdirs report --since 24h --json",
        "/usr/local/bin/watchdirs prune --db /var/lib/watchdirs/watchdirs.sqlite3 --json",
        "/usr/local/bin/watchdirs vacuum --db /var/lib/watchdirs/watchdirs.sqlite3 --json",
        "keep all hourly snapshots for 14 days",
        "keep one COMPLETE snapshot per UTC day for the next 90 days",
        "keep one COMPLETE snapshot per UTC month beyond that",
        "Cleanup orchestration remains out of",
    )

    for expected in required:
        assert expected in text

    forbidden = (
        "optionally collect a snapshot before and after daily cleanup",
        "optional weekly rollups or top-delta summaries",
    )
    for token in forbidden:
        assert token not in text
