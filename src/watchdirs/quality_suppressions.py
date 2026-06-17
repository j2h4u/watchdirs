from __future__ import annotations

import argparse
import io
import re
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

_TRIGGER_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "noqa": re.compile(r"#\s*noqa\b"),
    "type_ignore": re.compile(r"#\s*type:\s*ignore\b"),
    "pyright": re.compile(r"#\s*pyright:\s*"),
    "pylint": re.compile(r"#\s*pylint:\s*"),
    "ruff": re.compile(r"#\s*ruff:\s*"),
}

_VALID_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "noqa": re.compile(r"#\s*noqa:\s*[A-Z0-9]+(?:\s*,\s*[A-Z0-9]+)*\s*-\s*\S.*$"),
    "type_ignore": re.compile(r"#\s*type:\s*ignore\[[^\]]+\](?:\s*#.*)?$"),
    "pyright": re.compile(
        r"#\s*pyright:\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^,\s#]+"
        r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^,\s#]+)*\s*$"
    ),
    "pylint": re.compile(
        r"#\s*pylint:\s*[A-Za-z_][A-Za-z0-9_-]*\s*=\s*[^,\s#]+"
        r"(?:\s*,\s*[A-Za-z_][A-Za-z0-9_-]*\s*=\s*[^,\s#]+)*\s*$"
    ),
    "ruff": re.compile(r"#\s*ruff:\s*noqa(?::\s*[A-Z0-9]+(?:\s*,\s*[A-Z0-9]+)*)?\s*$"),
}


@dataclass(slots=True, frozen=True)
class SuppressionFinding:
    path: Path
    line_number: int
    category: str
    line: str
    message: str


@dataclass(slots=True, frozen=True)
class SuppressionPolicy:
    roots: tuple[Path, ...]
    baseline: dict[str, int]


@dataclass(slots=True)
class SuppressionReport:
    counts: dict[str, int]
    findings: list[SuppressionFinding]


def load_policy(repo_root: Path) -> SuppressionPolicy:
    pyproject_path = repo_root / "pyproject.toml"
    data = cast(dict[str, object], tomllib.loads(pyproject_path.read_text(encoding="utf-8")))
    try:
        tool = cast(dict[str, object], data["tool"])
        watchdirs = cast(dict[str, object], tool["watchdirs"])
        config = cast(dict[str, object], watchdirs["suppressions"])
    except KeyError as exc:  # pragma: no cover - configuration error is reported by main()
        raise KeyError("missing [tool.watchdirs.suppressions] in pyproject.toml") from exc

    roots = tuple(repo_root / Path(entry) for entry in cast(list[str], config["paths"]))
    baseline_raw = cast(dict[str, object], config["baseline"])
    baseline = {str(key): int(cast(int | str, value)) for key, value in baseline_raw.items()}
    return SuppressionPolicy(roots=roots, baseline=baseline)


def scan_policy(policy: SuppressionPolicy) -> SuppressionReport:
    counts = dict.fromkeys(policy.baseline, 0)
    findings: list[SuppressionFinding] = []
    for path in _iter_scan_files(policy.roots):
        if path.suffix == ".py":
            for line_number, line in _iter_python_comments(path):
                _record_comment(path, line_number, line, counts, findings)
            continue

        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            _record_comment(path, line_number, line, counts, findings)
    return SuppressionReport(counts=counts, findings=findings)


def check_policy(policy: SuppressionPolicy, repo_root: Path) -> list[str]:
    report = scan_policy(policy)
    return report_problems(policy, report, repo_root)


def report_problems(policy: SuppressionPolicy, report: SuppressionReport, repo_root: Path) -> list[str]:
    problems: list[str] = []
    for category in sorted(policy.baseline):
        current = report.counts.get(category, 0)
        allowed = policy.baseline[category]
        if current > allowed:
            problems.append(f"{category}: {current} > baseline {allowed}")
    problems.extend(
        f"{_display_path(finding.path, repo_root)}:{finding.line_number}: {finding.message}"
        for finding in report.findings
    )
    return problems


def format_report(policy: SuppressionPolicy, report: SuppressionReport, repo_root: Path) -> str:
    lines = ["suppression budget:"]
    for category in sorted(policy.baseline):
        current = report.counts.get(category, 0)
        allowed = policy.baseline[category]
        lines.append(f"  {category}: {current}/{allowed}")
    if report.findings:
        lines.append("malformed suppressions:")
        lines.extend(
            f"  {_display_path(finding.path, repo_root)}:{finding.line_number}: {finding.message}"
            for finding in report.findings
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m watchdirs.quality_suppressions")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root to scan",
    )
    args = parser.parse_args(argv)
    repo_root = cast(Path, args.repo_root)

    try:
        policy = load_policy(repo_root)
        report = scan_policy(policy)
    except (FileNotFoundError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError, tokenize.TokenError) as exc:
        sys.stderr.write(f"watchdirs suppression gate configuration error: {exc}\n")
        return 2

    problems = report_problems(policy, report, repo_root)

    print(format_report(policy, report, repo_root))
    if problems:
        sys.stderr.write("watchdirs suppression budget failed\n")
        for problem in problems:
            sys.stderr.write(f"  {problem}\n")
        return 1
    return 0


def _iter_scan_files(roots: tuple[Path, ...]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.exists():
            raise FileNotFoundError(root)
        for path in root.rglob("*"):
            rel_parts = path.relative_to(root).parts
            if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
                continue
            if _is_scanned_file(path):
                files.append(path)
    return files


def _is_scanned_file(path: Path) -> bool:
    return path.is_file() and path.suffix in {".py", ".toml", ".md", ".service", ".socket", ".timer", ".target"}


def _iter_python_comments(path: Path) -> list[tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    return [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]


def _record_comment(
    path: Path,
    line_number: int,
    line: str,
    counts: dict[str, int],
    findings: list[SuppressionFinding],
) -> None:
    stripped = line.lstrip()
    for category, trigger in _TRIGGER_PATTERNS.items():
        if category not in counts or not trigger.search(stripped):
            continue
        counts[category] += 1
        if not _VALID_PATTERNS[category].search(stripped):
            findings.append(
                SuppressionFinding(
                    path=path,
                    line_number=line_number,
                    category=category,
                    line=line,
                    message=_malformed_message(category),
                )
            )


def _malformed_message(category: str) -> str:
    if category == "noqa":
        return "expected `# noqa: CODE - reason`"
    if category == "type_ignore":
        return "expected `# type: ignore[code]`"
    if category == "pyright":
        return "expected `# pyright: name=value[, ...]`"
    if category == "pylint":
        return "expected `# pylint: option=value[, ...]`"
    return "expected `# ruff: noqa[: CODE[, ...]]`"


def _display_path(path: Path, repo_root: Path) -> Path:
    try:
        return path.relative_to(repo_root)
    except ValueError:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
