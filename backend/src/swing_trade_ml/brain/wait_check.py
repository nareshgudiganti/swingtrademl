# backend/src/swing_trade_ml/brain/wait_check.py
"""Was WAIT / AVOID the right call? (ps11, read-only evidence tool)

Every stock-day of a whole-brain replay is scored as if it had been bought (the settled strict rule,
normal costs) and grouped by the brain's final word: the ideas it wanted (TRADE, or a TRADE something
lowered), WAIT, AVOID, and every stock-day. A WAIT is a good call when buying would have lost money.

Protocol `ps11-wait-check-v1` (docs/brain/evidence/wait_check/PROTOCOL.md). Development data only: a good
result is not evidence, a bad one is a real warning. Nothing here writes to the database.

Run (backend/): python -m swing_trade_ml.brain.wait_check
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from swing_trade_ml.brain.replay_scoring import StrictOutcome

PROTOCOL_ID = "ps11-wait-check-v1"
GROUPS = ("wanted", "WAIT", "AVOID", "every stock-day")


@dataclass(frozen=True, slots=True)
class Judged:
    day: date
    symbol: str
    word: str
    wanted: bool


Outcomes = dict[tuple[date, str], StrictOutcome | None]


def load_judged(path: Path) -> list[Judged]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    i = {f: n for n, f in enumerate(raw["fields"])}
    return [
        Judged(date.fromisoformat(r[i["day"]]), r[i["symbol"]], r[i["word"]], bool(r[i["liked"]]))
        for r in raw["rows"]
    ]


def grouped(rows: Sequence[Judged]) -> dict[str, list[Judged]]:
    out: dict[str, list[Judged]] = {g: [] for g in GROUPS}
    for r in rows:
        if r.wanted:
            out["wanted"].append(r)
        elif r.word in ("WAIT", "AVOID"):
            out[r.word].append(r)
        out["every stock-day"].append(r)
    return out


def _finished(rows: Sequence[Judged], outcomes: Outcomes) -> list[StrictOutcome]:
    return [
        o for r in rows if (o := outcomes.get((r.day, r.symbol))) is not None and o.net_return is not None
    ]


def summary(rows: Sequence[Judged], outcomes: Outcomes) -> dict:
    done = _finished(rows, outcomes)
    n = len(done)
    return {
        "stock_days": len(rows),
        "finished": n,
        "stop": sum(o.status == "stop" for o in done),
        "target": sum(o.status == "target" for o in done),
        "timeout": sum(o.status == "timeout" for o in done),
        "avg_net": sum(o.net_return for o in done) / n if n else None,
        "lost_share": sum(o.net_return < 0 for o in done) / n if n else None,
    }


def day_by_day(rows: Sequence[Judged], outcomes: Outcomes) -> dict:
    """Days on which the wanted ideas' average beat WAIT's (only days where both finished something)."""
    per: dict[date, dict[str, list[Judged]]] = defaultdict(lambda: {"wanted": [], "WAIT": []})
    for r in rows:
        if r.wanted:
            per[r.day]["wanted"].append(r)
        elif r.word == "WAIT":
            per[r.day]["WAIT"].append(r)
    days = better = 0
    for g in per.values():
        w, s = summary(g["wanted"], outcomes), summary(g["WAIT"], outcomes)
        if w["finished"] and s["finished"]:
            days += 1
            better += w["avg_net"] > s["avg_net"]
    return {"days": days, "wanted_better": better}


def reading(wanted: dict, wait: dict) -> str:
    if not wait["finished"]:
        return "WAIT: nothing to judge (no finished WAIT stock-days)."
    right = "the right call on average" if wait["avg_net"] < 0 else "not the right call on average"
    out = f"WAIT was {right} (buying anyway averaged {wait['avg_net']:+.2%} after costs)."
    if wanted["finished"]:
        if wanted["avg_net"] > wait["avg_net"]:
            out += " The ideas the brain wanted did better than the ones it waited on."
        else:
            out += " The ideas the brain wanted did no better than the ones it waited on."
    return out


def run(rows: Sequence[Judged], outcomes: Outcomes) -> dict:
    groups = grouped(rows)
    sums = {g: summary(rs, outcomes) for g, rs in groups.items()}
    days = sorted({r.day for r in rows})
    return {
        "protocol": PROTOCOL_ID,
        "from": days[0].isoformat() if days else None,
        "to": days[-1].isoformat() if days else None,
        "groups": sums,
        "day_by_day": day_by_day(rows, outcomes),
        "reading": reading(sums["wanted"], sums["WAIT"]),
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def _share(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def plain_report(result: dict) -> str:
    g, dd = result["groups"], result["day_by_day"]
    lines = [
        "# Was WAIT / AVOID the right call? (ps11)",
        "",
        f"Protocol: `{result['protocol']}`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).",
        f"Whole-brain replay {result['from']} to {result['to']} (the ps1 'all modules' run). Every stock-day "
        "scored as if it had been bought: next-day open, +8% / -4%, half out at +5%, 15 days, after costs.",
        "",
        f"**Answer:** {result['reading']}",
        "",
        "| Brain's word | Stock-days | Finished | -4% first | +8% first | Ran out of time | Avg after costs "
        "| Would have lost money |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in GROUPS:
        s = g[name]
        lines.append(
            f"| {name} | {s['stock_days']} | {s['finished']} | {s['stop']} | {s['target']} | "
            f"{s['timeout']} | {_pct(s['avg_net'])} | {_share(s['lost_share'])} |"
        )
    lines += [
        "",
        f"Good WAIT rate (buying would have lost money): **{_share(g['WAIT']['lost_share'])}**. "
        + (
            f"Good AVOID rate: **{_share(g['AVOID']['lost_share'])}**."
            if g["AVOID"]["finished"]
            else "AVOID: never said in this replay, nothing to judge."
        ),
        "",
        f"Day by day: on {dd['wanted_better']} of {dd['days']} days the wanted ideas did better than WAIT.",
        "",
        "## Limits",
        "",
        "- Development data only, one replay, one model: a good result is not evidence; a bad one is a real "
        "warning.",
        "- 'Wanted' means a TRADE the replay's risk check lowered (it reads today's account), so these are "
        "the ideas the brain would have bought.",
        "- Stock-days overlap: the same stock is judged again the next day, so they are not independent.",
        "- Universe is today's watchlist (survivor bias).",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.replay_scoring import strict_for
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Was WAIT / AVOID the right call? (read-only evidence, ps11)")
    p.add_argument("--judged", default="../docs/brain/evidence/wait_check/judged_all_modules.json")
    p.add_argument("--upto", default="2026-09-07", help="last day of prices used to score")
    p.add_argument("--out", default="../docs/brain/evidence/wait_check")
    a = p.parse_args(argv)
    rows = load_judged(Path(a.judged))
    with SessionLocal() as db:
        bars = load_bars(db, sorted({r.symbol for r in rows}), date.fromisoformat(a.upto))
    outcomes: Outcomes = {
        (r.day, r.symbol): (strict_for(bars[r.symbol], r.day) if r.symbol in bars else None) for r in rows
    }
    result = run(rows, outcomes)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "wait_check.md").write_text(plain_report(result), encoding="utf-8")
    (out / "wait_check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(plain_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
