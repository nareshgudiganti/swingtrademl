"""Read-only audit (tv27): compare session days against the NSE trading calendar.

Takes ISO dates (arguments, or one per line on stdin) and prints every day that is not a real NSE trading day
(weekend or listed holiday), with the reason. Touches no database, network or file.
Exit code 1 if any mismatch.

    python scripts/audit_session_days.py 2026-10-19 2026-10-20 2026-11-10
"""

from __future__ import annotations

import sys
from datetime import date

from swing_trade_ml.core.holidays import is_trading_holiday


def audit(days) -> list[tuple[date, str]]:
    """(day, reason) for each day that is not a real trading day, in date order. Read-only."""
    out = []
    for d in sorted(set(days)):
        if d.weekday() >= 5:
            out.append((d, "weekend"))
        elif is_trading_holiday(d):
            out.append((d, "NSE holiday"))
    return out


def main(argv: list[str]) -> int:
    raw = argv or [ln.strip() for ln in sys.stdin if ln.strip()]
    days = [date.fromisoformat(x) for x in raw]
    bad = audit(days)
    print(f"{len(set(days))} session days checked, {len(bad)} not real trading days")
    for d, why in bad:
        print(f"  {d.isoformat()} ({d:%a}): {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
