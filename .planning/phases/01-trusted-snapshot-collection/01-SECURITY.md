---
phase: 01
slug: trusted-snapshot-collection
status: verified
threats_open: 0
asvs_level: 1
block_on: high
created: 2026-06-13
updated: 2026-06-13
register_authored_at_plan_time: true
---

# Phase 01 — Security

Per-phase security contract: verify the plan-time threat register against implementation, tests, accepted risks, and transfer documentation.

## Scope

- Audited sources: `01-01-PLAN.md` through `01-04-PLAN.md` `<threat_model>` blocks, all four `## Threat Flags` sections, `01-REVIEW.md`, and `01-VERIFICATION.md`.
- Implementation reviewed: `watchdirs`, `pyproject.toml`, `src/watchdirs/{__main__,cli,config,models}.py`, `src/watchdirs/db/{connection,migrations,schema.sql}`, `src/watchdirs/collect/{scanner,mounts,classify}.py`, and the Phase 01 pytest files.
- Audit rule: verify plan-time threats only. No unrelated threat discovery beyond phase-caused surface changes.

## Threat Verification

| Source Plan | Threat ID | Category | Component | Disposition | Status | Evidence |
|-----------|----------|-----------|-----------|-------------|--------|----------|
| 01-01 | T-01-01 | Tampering | `config.load_config` roots | mitigate | closed | `src/watchdirs/config.py:63-70,73-90,220-224`; `tests/test_cli_collect.py:140-145,215-223` |
| 01-01 | T-01-02 | Spoofing | command surface | mitigate | closed | [watchdirs](/home/j2h4u/repos/j2h4u/watchdirs/watchdirs:1); [__main__.py](/home/j2h4u/repos/j2h4u/watchdirs/src/watchdirs/__main__.py:1); `tests/test_cli_collect.py:129-137` |
| 01-01 | T-01-03 | Information Disclosure | JSON CLI errors | accept | closed | Accepted Risks Log `AR-01` below |
| 01-01 | T-01-04 | Elevation of Privilege | future timer config permissions | transfer | closed | `01-01-SUMMARY.md:94-96` documents the Phase 4 transfer and requires config owner/mode verification before any root-run systemd timer consumes TOML roots. |
| 01-01 | T-01-SC | Tampering | package installs | mitigate | closed | [watchdirs](/home/j2h4u/repos/j2h4u/watchdirs/watchdirs:1); [pyproject.toml](/home/j2h4u/repos/j2h4u/watchdirs/pyproject.toml:5); `tests/test_cli_collect.py:129-137` |
| 01-02 | T-01-04 | Repudiation | `snapshots.status` and `snapshots.error` | mitigate | closed | `src/watchdirs/db/schema.sql:1-8`; `src/watchdirs/db/migrations.py:30-53,81-115`; `tests/test_db_schema.py:15-33`; `tests/test_cli_collect.py:276-305,399-430` |
| 01-02 | T-01-05 | Tampering | SQLite migration lifecycle | mitigate | closed | `src/watchdirs/db/connection.py:12-14`; `src/watchdirs/db/migrations.py:15-27,81-98`; `tests/test_db_schema.py:36-70`; `tests/test_cli_collect.py:596-663,758-836` |
| 01-02 | T-01-06 | Tampering | directory row contract | mitigate | closed | `src/watchdirs/models.py:25-36`; `src/watchdirs/db/schema.sql:11-23`; `src/watchdirs/db/migrations.py:61-78,118-129` |
| 01-02 | T-01-07 | Denial of Service | per-row SQLite inserts | mitigate | closed | `src/watchdirs/db/migrations.py:12,75-78`; `tests/test_db_schema.py:110-135` |
| 01-02 | T-01-08 | Repudiation | interrupted collection | mitigate | closed | `src/watchdirs/cli.py:70-85,142-161`; `tests/test_cli_collect.py:666-755,758-836` |
| 01-02 | T-01-09 | Tampering | non-UTF-8 path storage | mitigate | closed | `src/watchdirs/models.py:25-36,92-96`; `src/watchdirs/db/schema.sql:11-23`; `src/watchdirs/db/migrations.py:118-123`; `tests/test_db_schema.py:73-89`; `tests/test_scanner_semantics.py:77-125` |
| 01-02 | T-01-SC | Tampering | package installs | mitigate | closed | [watchdirs](/home/j2h4u/repos/j2h4u/watchdirs/watchdirs:1); [pyproject.toml](/home/j2h4u/repos/j2h4u/watchdirs/pyproject.toml:5); `tests/test_cli_collect.py:129-137` |
| 01-03 | T-01-05 | Tampering | symlink traversal | mitigate | closed | `src/watchdirs/collect/scanner.py:57-80,179-180,188-229`; `tests/test_scanner_semantics.py:200-230` |
| 01-03 | T-01-06 | Tampering | hardlink accounting | mitigate | closed | `src/watchdirs/collect/scanner.py:314-315,412-438`; `tests/test_scanner_semantics.py:233-247` |
| 01-03 | T-01-07 | Repudiation | path-level errors | mitigate | closed | `src/watchdirs/models.py:91-96`; `src/watchdirs/collect/scanner.py:140-159,181-186,254-261,382-408`; `tests/test_scanner_semantics.py:328-350`; `tests/test_cli_collect.py:433-489` |
| 01-03 | T-01-08 | Denial of Service | recursive traversal | mitigate | closed | `src/watchdirs/collect/scanner.py:109-168`; `tests/test_scanner_semantics.py:128-140` |
| 01-03 | T-01-09 | Denial of Service | hardlink dedup memory | mitigate | closed | `src/watchdirs/models.py:82-89`; `src/watchdirs/collect/scanner.py:424-438`; `tests/test_scanner_semantics.py:250-299` |
| 01-03 | T-01-10 | Tampering | non-UTF-8 path identity | mitigate | closed | `src/watchdirs/models.py:25-36,92-96`; `src/watchdirs/collect/scanner.py:300-311,473-479`; `src/watchdirs/db/migrations.py:118-123`; `tests/test_scanner_semantics.py:77-125` |
| 01-03 | T-01-11 | Tampering | configured exclude paths | mitigate | closed | `src/watchdirs/config.py:67,138-150`; `src/watchdirs/cli.py:103-110,153-174`; `src/watchdirs/collect/scanner.py:49,174-177,448-456`; `tests/test_cli_collect.py:264-273`; `tests/test_scanner_semantics.py:302-325` |
| 01-03 | T-01-SC | Tampering | package installs | mitigate | closed | [watchdirs](/home/j2h4u/repos/j2h4u/watchdirs/watchdirs:1); [pyproject.toml](/home/j2h4u/repos/j2h4u/watchdirs/pyproject.toml:5); `tests/test_cli_collect.py:129-137` |
| 01-04 | T-01-09 | Spoofing | mount parser | mitigate | closed | `src/watchdirs/collect/mounts.py:12-41,48-58,61-77`; `tests/test_mount_policy.py:95-131`; focused probe returned `longest_match_mount_id=3` |
| 01-04 | T-01-10 | Tampering | mount classifier | mitigate | closed | `src/watchdirs/collect/classify.py:6-23,26-80`; `src/watchdirs/config.py:153-180`; `tests/test_mount_policy.py:134-193` |
| 01-04 | T-01-11 | Denial of Service | scanner descent into virtual trees | mitigate | closed | `src/watchdirs/collect/scanner.py:81-107,188-216,318-379`; `tests/test_mount_policy.py:195-238` |
| 01-04 | T-01-12 | Repudiation | skipped mount evidence | mitigate | closed | `src/watchdirs/collect/scanner.py:205-214,397-409`; `tests/test_mount_policy.py:233-238,288-290` |
| 01-04 | T-01-13 | Denial of Service | bind mount cycles | mitigate | closed | `src/watchdirs/collect/scanner.py:348-379`; `tests/test_mount_policy.py:366-397` |
| 01-04 | T-01-14 | Tampering | cross-filesystem traversal | mitigate | closed | `src/watchdirs/models.py:62-67`; `src/watchdirs/config.py:170-179`; `src/watchdirs/collect/scanner.py:336-346`; `tests/test_mount_policy.py:241-292,295-363` |
| 01-04 | T-01-SC | Tampering | package installs | mitigate | closed | [watchdirs](/home/j2h4u/repos/j2h4u/watchdirs/watchdirs:1); [pyproject.toml](/home/j2h4u/repos/j2h4u/watchdirs/pyproject.toml:5); `tests/test_cli_collect.py:129-137` |

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | 01-01 / T-01-03 | JSON CLI errors are local operator evidence only; Phase 01 exposes no network or service boundary and does not transmit data. | Phase 01-01 threat model disposition | 2026-06-13 |

## Transfer Notes

| Threat Ref | Expected Transfer Documentation | Status | Evidence |
|------------|---------------------------------|--------|----------|
| 01-01 / T-01-04 | `01-01-SUMMARY.md` should call out that Phase 4 service work must verify config owner/mode before any root-run timer consumes TOML roots. | closed | `01-01-SUMMARY.md:94-96` now contains the required `## Security Transfers` note. |

## Threat Flags

All four Phase 01 summary files declare `## Threat Flags` as `None.` No unregistered flags were found.

## Commands Run

```text
# initial audit
pytest tests/test_cli_collect.py tests/test_db_schema.py tests/test_scanner_semantics.py tests/test_mount_policy.py -q
PYTHONPATH=src python3 - <<'PY'
from watchdirs.collect.mounts import parse_mountinfo, find_mount_for_path
raw = "\n".join([
    "1 0 8:1 / / rw - ext4 /dev/root rw",
    "2 1 8:1 / /srv rw - ext4 /dev/root rw",
    "3 2 8:1 / /srv/root rw - ext4 /dev/root rw",
]) + "\n"
mounts = parse_mountinfo(raw)
match = find_mount_for_path("/srv/root/nested/path", mounts)
assert match is not None
assert match.mount_id == 3
print(f"longest_match_mount_id={match.mount_id}")
PY
rg -n "owner|mode|root-run|timer|Phase 4" .planning/phases/01-trusted-snapshot-collection/01-01-SUMMARY.md

# narrow re-check
sed -n '1,260p' .planning/phases/01-trusted-snapshot-collection/01-01-PLAN.md
sed -n '1,260p' .planning/phases/01-trusted-snapshot-collection/01-01-SUMMARY.md
sed -n '1,260p' .planning/phases/01-trusted-snapshot-collection/01-SECURITY.md
rg -n "T-01-04|<threat_model>|disposition: transfer|owner|mode|root-run|timer" .planning/phases/01-trusted-snapshot-collection/01-01-PLAN.md
rg -n "Security Transfers|T-01-04 transferred to Phase 4|owner/mode|root-run systemd timer|consumes TOML roots" .planning/phases/01-trusted-snapshot-collection/01-01-SUMMARY.md
nl -ba .planning/phases/01-trusted-snapshot-collection/01-01-SUMMARY.md | sed -n '60,90p'
rg -n "T-01-04|threats_open|status:|Transfer Notes|Approval:|Security Audit Trail|Commands Run" .planning/phases/01-trusted-snapshot-collection/01-SECURITY.md
```

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-13 | 27 | 26 | 1 | Codex security audit |
| 2026-06-13 | 27 | 27 | 0 | Codex narrow re-check |

## Sign-Off

- [x] All threats have a disposition.
- [x] Accepted risks documented in Accepted Risks Log.
- [x] `threats_open: 0` confirmed.
- [x] `status: verified` set in frontmatter.

**Approval:** verified; all 27 Phase 01 threats are closed as of 2026-06-13.
