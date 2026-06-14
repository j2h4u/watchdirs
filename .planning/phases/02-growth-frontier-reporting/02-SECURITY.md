---
phase: 02-growth-frontier-reporting
verified: 2026-06-14
status: secured
mode: declared-threats-plus-retroactive-checks
asvs_level: not_specified
block_on: not_specified
declared_threats: 20
retroactive_checks: 2
threats_total: 22
threats_open: 0
accepted_risks: 2
unregistered_flags: 0
verification_commands:
  - "python3 -m pytest -q tests/test_grouping.py tests/test_db_schema.py tests/test_frontier.py tests/test_reporting_queries.py tests/test_cli_report_commands.py"
verification_results:
  - "62 passed in 3.91s"
---

# Phase 02 Security Verification

## Scope

Verified the declared threat models in:

- `02-01-PLAN.md`
- `02-02-PLAN.md`
- `02-03-PLAN.md`
- `02-04-PLAN.md`

Also verified the user-requested retroactive checks for text-output spoofing and report-time live filesystem rescan avoidance.

## Accepted Risks Log

| Threat ID | Accepted Risk | Rationale |
| --- | --- | --- |
| T-02-04 | Mount row volume per snapshot | Accepted. `collect` persists one row per mount table entry per snapshot, and reporting reuses stored rows instead of creating a new recursive scan or mount crawl. |
| T-02-17 | Local path disclosure in CLI output | Accepted. Phase 02 is a local forensic CLI and intentionally renders indexed local paths in JSON/text for the operator/agent. |

## Threat Verification

| Threat ID | Category | Disposition | Result | Evidence |
| --- | --- | --- | --- | --- |
| T-02-01 | Spoofing | mitigate | CLOSED | `src/watchdirs/db/schema.sql:25-35`; `src/watchdirs/reporting/queries.py:398-408`; `tests/test_grouping.py:241-303` |
| T-02-02 | Tampering | mitigate | CLOSED | `src/watchdirs/db/migrations.py:219-228`; `src/watchdirs/db/schema.sql:30-33`; `tests/test_grouping.py:129-185` |
| T-02-03 | Repudiation | mitigate | CLOSED | `src/watchdirs/db/migrations.py:132-149`; `src/watchdirs/reporting/queries.py:119-120,180-181`; `src/watchdirs/reporting/render.py:467-485` |
| T-02-04 | Denial of Service | accept | CLOSED | Accepted risk logged above; bounded write path in `src/watchdirs/cli.py:193-215`; report commands read stored evidence only in `src/watchdirs/cli.py:291-605` |
| T-02-SC | Tampering | mitigate | CLOSED | Runtime deps remain empty in `pyproject.toml:1-10`; Phase 02 commit span changed only `src/watchdirs/**` and `tests/**` implementation/test files, not dependency manifests |
| T-02-05 | Tampering | mitigate | CLOSED | `src/watchdirs/cli.py:62-72`; `src/watchdirs/reporting/queries.py:57-106,109-137` |
| T-02-06 | Tampering | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:141-168`; `src/watchdirs/reporting/render.py:20-46,487-500`; `tests/test_cli_report_commands.py:334-390` |
| T-02-07 | Repudiation | mitigate | CLOSED | `src/watchdirs/cli.py:301-313,684-699`; `src/watchdirs/reporting/render.py:49-79,81-123`; `tests/test_cli_report_commands.py:243-283` |
| T-02-08 | Spoofing | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:119-120,386-409`; `tests/test_reporting_queries.py:228-311` |
| T-02-09 | Denial of Service | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:36-54`; `src/watchdirs/cli.py:297-307` |
| T-02-10 | Tampering | mitigate | CLOSED | `src/watchdirs/cli.py:75-85`; `src/watchdirs/reporting/queries.py:171-223` |
| T-02-11 | Repudiation | mitigate | CLOSED | `src/watchdirs/reporting/pairs.py:77-99,137-164`; `src/watchdirs/reporting/render.py:478-485`; `tests/test_reporting_queries.py:585-663` |
| T-02-12 | Spoofing | mitigate | CLOSED | `src/watchdirs/reporting/pairs.py:70-75,101-164`; `src/watchdirs/cli.py:367-377`; `tests/test_reporting_queries.py:585-663` |
| T-02-13 | Tampering | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:228-254`; `src/watchdirs/reporting/frontier.py:9-85`; `src/watchdirs/reporting/render.py:42-46,503-547` |
| T-02-14 | Denial of Service | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:36-54`; `src/watchdirs/reporting/frontier.py:9-85`; `src/watchdirs/cli.py:367-377` |
| T-02-15 | Tampering | mitigate | CLOSED | `src/watchdirs/cli.py:726-753`; `src/watchdirs/reporting/queries.py:282-298`; `tests/test_cli_report_commands.py:639-825`. Inferred control: `explain-path` never interpolates the user path into SQL; the exact target check happens in Python after the parameterized diff query. |
| T-02-16 | Repudiation | mitigate | CLOSED | `src/watchdirs/reporting/render.py:204-229,314-332,376-401,467-485`; `tests/test_cli_report_commands.py:401-509,639-728` |
| T-02-17 | Information Disclosure | accept | CLOSED | Accepted risk logged above; payload renderers intentionally expose local indexed paths in `src/watchdirs/reporting/render.py:42-46,529-586` |
| T-02-18 | Denial of Service | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:36-54`; `src/watchdirs/cli.py:564-577,714-723`; `tests/test_cli_report_commands.py:730-825` |
| T-02-19 | Spoofing | mitigate | CLOSED | `src/watchdirs/reporting/queries.py:180-181,386-421`; `tests/test_reporting_queries.py:228-311,376-509`; `tests/test_cli_report_commands.py:1121-1233` |
| RT-02-01 | Spoofing | mitigate | CLOSED | Text-mode escaping in `src/watchdirs/reporting/render.py:24-39,81-123,151-201,232-311,335-373,404-464`; regression coverage in `tests/test_cli_report_commands.py:334-390` |
| RT-02-02 | Tampering / Denial of Service | mitigate | CLOSED | Reporting handlers use SQLite only in `src/watchdirs/cli.py:291-605`; query layer reads persisted `directory_sizes`/`snapshot_mounts` only in `src/watchdirs/reporting/queries.py:121-223,275-299`; no report command calls `scan_root()` or `load_mountinfo()` |

## Constraint Crosswalk

| Requested Check | Verified By |
| --- | --- |
| Path text spoofing | RT-02-01 |
| SQL injection / dynamic query safety | T-02-05, T-02-10, T-02-15 |
| Corrupted snapshot evidence | T-02-07, T-02-11, T-02-16, T-02-19 |
| Path traversal in `explain-path` | T-02-15 |
| Live filesystem rescan avoidance | T-02-04, RT-02-02 |
| Persisted mount grouping integrity | T-02-01, T-02-03, T-02-08, T-02-19 |

## Unregistered Flags

None. No `## Threat Flags` section was present in the Phase 02 summaries, and no additional blocker-grade unmapped attack surface was required to explain the implementation.
