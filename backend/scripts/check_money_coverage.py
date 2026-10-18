"""Fail CI if line coverage of the money code drops below its floor (tracker task qa8).

"Money code" is the code that decides how much is bought, when it is sold, and whether an order may
reach a broker at all: the risk gate and sizing, the account-size limits, the exit policy, execution,
and the broker package. A change there that is not tested is the most expensive kind of mistake this
repo can make, so CI holds a line-coverage floor on exactly these files.

Usage (from backend/, after pytest has written coverage.json):

    pytest -q --cov=swing_trade_ml --cov-report=json
    python scripts/check_money_coverage.py            # reads coverage.json
    python scripts/check_money_coverage.py path/to/coverage.json

The floor is 95% of lines (tracker target was 90%; every file was at 98.7%+ when it was set).
A file listed in FLOORS with a lower number is one that genuinely cannot
reach 90% without a real Zerodha session; the comment next to it says why. Raise a floor whenever
coverage goes up; never lower one to make a build pass. Exit code 1 means at least one file is below
its floor or is missing from the report.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_FLOOR = 95.0  # 2026-10-18 all files 98.7-100%; 90% was the tracker target

# Paths relative to the swing_trade_ml package, with forward slashes.
FLOORS: dict[str, float] = {
    "services/risk.py": DEFAULT_FLOOR,
    "services/limits.py": DEFAULT_FLOOR,
    "services/exit_policy.py": DEFAULT_FLOOR,
    "services/execution.py": DEFAULT_FLOOR,
    "brokers/__init__.py": DEFAULT_FLOOR,
    "brokers/base.py": DEFAULT_FLOOR,
    "brokers/paper.py": DEFAULT_FLOOR,
    "brokers/kite.py": DEFAULT_FLOOR,
}


def _package_relative(path: str) -> str | None:
    norm = path.replace("\\", "/")
    marker = "swing_trade_ml/"
    idx = norm.rfind(marker)
    return norm[idx + len(marker) :] if idx != -1 else None


def check(report: dict) -> list[str]:
    by_file: dict[str, float] = {}
    for path, data in report.get("files", {}).items():
        rel = _package_relative(path)
        if rel is not None:
            # Lines only, even if branch coverage is ever switched on (percent_covered would then
            # blend in branches and silently move every floor).
            summary = data["summary"]
            statements = summary["num_statements"]
            by_file[rel] = 100.0 * summary["covered_lines"] / statements if statements else 100.0

    failures: list[str] = []
    print(f"{'file':32} {'covered':>8} {'floor':>7}")
    for rel, floor in FLOORS.items():
        pct = by_file.get(rel)
        if pct is None:
            failures.append(f"{rel}: not in the coverage report (was --cov=swing_trade_ml used?)")
            print(f"{rel:32} {'missing':>8} {floor:>6.0f}%")
            continue
        flag = "" if pct >= floor else "  <-- BELOW FLOOR"
        print(f"{rel:32} {pct:>7.1f}% {floor:>6.0f}%{flag}")
        if pct < floor:
            failures.append(f"{rel}: {pct:.1f}% of lines covered, floor is {floor:.0f}%")
    return failures


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("coverage.json")
    if not path.exists():
        print(f"No coverage report at {path}. Run pytest with --cov=swing_trade_ml --cov-report=json first.")
        return 1
    failures = check(json.loads(path.read_text(encoding="utf-8")))
    if failures:
        print("\nMoney-code coverage is below its floor:")
        for line in failures:
            print(f"  - {line}")
        print("Add tests for the uncovered lines (see docs/QUALITY-CHECKS.md, qa8).")
        return 1
    print("\nMoney-code coverage floor: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
