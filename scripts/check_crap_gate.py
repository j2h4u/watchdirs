from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from coverage import CoverageData
from pytest_crap.calculator import FunctionScore, calculate_crap


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when any function reaches the CRAP threshold.")
    parser.add_argument("--threshold", type=float, default=30.0)
    parser.add_argument("--data-file", default=".coverage")
    parser.add_argument("--source", default="src/watchdirs")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    threshold = cast("float", args.threshold)
    data_file = cast("str", args.data_file)
    source = cast("str", args.source)
    top = cast("int", args.top)

    repo_root = Path.cwd()
    source_root = (repo_root / source).resolve()
    data = CoverageData(basename=data_file)
    data.read()

    scores = _function_scores(data, source_root)
    failures = [score for score in scores if score.crap >= threshold]
    if not failures:
        print(f"CRAP gate passed: {len(scores)} functions below {threshold:g}")
        return 0

    print(f"CRAP gate failed: {len(failures)} function(s) >= {threshold:g}")
    for score in sorted(failures, key=lambda item: (-item.crap, item.file_path, item.start_line))[:top]:
        path = _relative_path(repo_root, Path(score.file_path))
        print(
            f"{score.crap:.2f} CRAP | CC {score.cc} | {score.coverage_percent:.1f}% | "
            f"{path}:{score.start_line} | {score.name}"
        )
    return 1


def _function_scores(data: CoverageData, source_root: Path) -> list[FunctionScore]:
    scores: list[FunctionScore] = []
    for filename in data.measured_files():
        path = Path(filename).resolve()
        if path.suffix != ".py" or not path.is_relative_to(source_root):
            continue
        scores.extend(calculate_crap(str(path), set(data.lines(filename) or ())))
    return scores


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
