# backend/src/swing_trade_ml/brain/trial_journal.py
"""Trial journal: over a run of sessions, what the app signalled and what following it would have done.

Read-only. For every session (a live nightly brain run) it records the banner and the brain's words,
then scores the ideas a follower could have taken with the settled rule used everywhere else
(`replay_scoring.strict_score`: next-day open, +8% / -4%, half out at +5%, 15 trading days, real costs):

- brain TRADE          what the app would actually have bought;
- brain top 5          the five highest-scored ideas of the day, whatever their word;
- score over 80        the top five among ideas scored 0.80 or more (owner's reading rule, 2026-10-09);
- version 1 buys       `ml_swing` BUY signals the same days.

Every set is set against "every stock" (a random pick has exactly that average). Ideas that have not had
15 sessions yet are listed as open and never counted. Fewer than `MIN_SESSIONS` sessions is reported as
"too early", not as a result. It changes no rule, no run and no stored decision.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from swing_trade_ml.brain.horizon_grid import summarise
from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET, StrictOutcome
from swing_trade_ml.brain.walk_forward import daily_edge, outcomes_for

IST = ZoneInfo("Asia/Kolkata")
TRIAL_START = date(2026, 10, 14)  # owner decision 2026-10-13 (docs/brain/EXPOSURE-LEDGER.md)
MIN_SESSIONS = 15  # fewer sessions than this is "too early"
GATE_IDEAS = 30  # the M18 gate, shown for reference
# Forward gate, protocol section 5a (docs/superpowers/specs/2026-10-13-layer2-validation-protocol-DRAFT.md).
GATE_MIN_IDEAS = GATE_IDEAS
CLEARLY_WORSE = -0.01  # an average daily gap below every stock beyond this is called out first
SCORE_LINE = 0.80  # the owner reads scores of 80 and above
TOP_N = 5  # at most five ideas a day (owner decision 2026-10-09)
SETS = ("brain_trade", "brain_blocked", "brain_top5", "brain_over_80", "v1_buys")
SET_NAMES = {
    "brain_trade": "Brain says TRADE",
    "brain_blocked": "TRADE blocked by the risk check (not counted)",
    "brain_top5": "Brain top 5 by score",
    "brain_over_80": "Score 80 or more (top 5)",
    "v1_buys": "Version 1 buys",
    "every_stock": "Every stock (random baseline)",
}


@dataclass(frozen=True, slots=True)
class Idea:
    symbol: str
    word: str  # the word that counts: the owner's overrule when there is one
    score: float | None
    # The brain said TRADE but the risk check (version 1's limits) lowered it to WATCH. Reported as
    # its own set so a stressed market still produces evidence; never counted toward the gate.
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class Session:
    day: date
    banner: str | None
    ideas: tuple[Idea, ...]


def picks_for(session: Session, v1: Sequence[str] = ()) -> dict[str, list[str]]:
    """The symbols each followed set would have taken on one session."""
    scored = sorted(
        (i for i in session.ideas if i.score is not None), key=lambda i: (-i.score, i.symbol)
    )
    return {
        "brain_trade": sorted(i.symbol for i in session.ideas if i.word == "TRADE"),
        "brain_blocked": sorted(i.symbol for i in session.ideas if i.blocked),
        "brain_top5": [i.symbol for i in scored[:TOP_N]],
        "brain_over_80": [i.symbol for i in scored if i.score >= SCORE_LINE][:TOP_N],
        "v1_buys": sorted(set(v1)),
    }


def _open_so_far(bars: pd.DataFrame, day: date) -> float | None:
    """Move since the next day's open, for an idea that has not finished. Shown, never counted."""
    after = bars[bars["day"] > day]
    if after.empty:
        return None
    return float(after.iloc[-1]["close"]) / float(after.iloc[0]["open"]) - 1.0


def _outcome_row(sym: str, day: date, o: StrictOutcome | None, bars: dict[str, pd.DataFrame]) -> dict:
    if o is None:
        return {"symbol": sym, "status": "no data", "net": None, "days": None, "so_far": None}
    so_far = _open_so_far(bars[sym], day) if o.net_return is None and sym in bars else None
    return {"symbol": sym, "status": o.status, "net": o.net_return, "days": o.days, "so_far": so_far}


def index_baseline(index_bars: pd.DataFrame | None, days: Sequence[date], horizon: int) -> dict | None:
    """NIFTY bought at the open after each session and sold at the close of the `horizon`-th session:
    what simply holding the market would have done over the same days. No costs (an index fund's are
    small next to a stock trade's). A session without `horizon` later bars is open and not counted."""
    if index_bars is None or index_bars.empty:
        return None
    df = index_bars.sort_values("day").reset_index(drop=True)
    results, open_n = [], 0
    for d in days:
        after = df[df["day"] > d]
        if len(after) < horizon:
            open_n += 1
            continue
        results.append(float(after.iloc[horizon - 1]["close"]) / float(after.iloc[0]["open"]) - 1.0)
    return {
        "finished": len(results),
        "open": open_n,
        "avg": sum(results) / len(results) if results else None,
    }


def build_journal(
    sessions: Sequence[Session],
    bars: dict[str, pd.DataFrame],
    v1_by_day: dict[date, Sequence[str]] | None = None,
    *,
    index_bars: pd.DataFrame | None = None,
    horizon: int = HORIZON_BARS,
    target: float = TARGET,
    stop: float = STOP,
) -> dict:
    """Pure: sessions + price bars in, journal out. `index_bars` (NIFTY 50) adds the hold-the-market
    baseline; cash (0%) is always shown."""
    v1_by_day = v1_by_day or {}
    days = [s.day for s in sessions]
    outcomes = outcomes_for(bars, days, horizon, target, stop)
    # The baseline is the stocks the brain itself looked at that day, so a pick is always compared
    # with the same pool it was chosen from.
    looked_at = {s.day: {i.symbol for i in s.ideas} for s in sessions}
    everyone = {d: sorted(sym for sym in looked_at[d] if (sym, d) in outcomes) for d in days}

    picks_by_set: dict[str, dict[date, list[str]]] = {name: {} for name in SETS}
    for s in sessions:
        for name, syms in picks_for(s, v1_by_day.get(s.day, ())).items():
            picks_by_set[name][s.day] = syms

    summaries: dict[str, dict] = {}
    for name in SETS:
        grouped: dict[date, list[StrictOutcome]] = {}
        open_n = 0
        for d, syms in picks_by_set[name].items():
            outs = [outcomes[(sym, d)] for sym in syms if (sym, d) in outcomes]
            grouped[d] = outs
            open_n += sum(1 for o in outs if o.net_return is None)
        row = summarise(grouped)
        edge = daily_edge(picks_by_set[name], everyone, outcomes)
        row.update(
            picked=sum(len(v) for v in picks_by_set[name].values()),
            still_open=open_n,
            edge_vs_every_stock=sum(edge) / len(edge) if edge else None,
            edge_days=len(edge),
        )
        summaries[name] = row
    summaries["every_stock"] = summarise(
        {d: [outcomes[(sym, d)] for sym in syms if (sym, d) in outcomes] for d, syms in everyone.items()}
    )
    summaries["nifty"] = index_baseline(index_bars, days, horizon)

    journal_days = []
    for s in sessions:
        words: dict[str, int] = {}
        for i in s.ideas:
            words[i.word] = words.get(i.word, 0) + 1
        journal_days.append(
            {
                "day": s.day.isoformat(),
                "banner": s.banner,
                "words": words,
                "picks": {
                    name: [_outcome_row(sym, s.day, outcomes.get((sym, s.day)), bars) for sym in picks_by_set[name][s.day]]
                    for name in SETS
                },
            }
        )

    n = len(sessions)
    return {
        "rule": {"horizon": horizon, "target": target, "stop": stop},
        "sessions": n,
        "first_day": days[0].isoformat() if days else None,
        "last_day": days[-1].isoformat() if days else None,
        "enough_sessions": n >= MIN_SESSIONS,
        "summaries": summaries,
        "days": journal_days,
    }


def gate(journal: dict) -> dict:
    """The forward-gate answer (protocol section 5a) from a journal: 'too early', 'pass' or 'behind'.

    Only finished brain TRADE ideas count. Safety is not judged here: the journal has no account, so it
    cannot see a sector cap or drawdown halt being broken; the report says so.
    """
    row = journal["summaries"]["brain_trade"]
    finished, avg, edge = row["ideas"], row["avg_net"], row["edge_vs_every_stock"]
    out = {
        "sessions": journal["sessions"],
        "finished": finished,
        "profit": avg is not None and avg > 0,
        "beats_random": edge is not None and edge > 0,
        "clearly_worse": edge is not None and edge < CLEARLY_WORSE,
    }
    if journal["sessions"] < MIN_SESSIONS or finished < GATE_MIN_IDEAS:
        out["word"] = "too early"
    else:
        out["word"] = "pass" if out["profit"] and out["beats_random"] else "behind"
    return out


# --- reading the database -----------------------------------------------------------------------


def load_sessions(db, start: date, end: date, *, live: bool = True) -> list[Session]:
    """Nightly brain runs, one per IST day, with that day's ideas. `live=False` reads replayed runs
    instead (no TRADE words: the risk gate refuses a replay, so only the score-based sets fill in)."""
    from sqlalchemy import select

    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
    from swing_trade_ml.strategies.brain import blocked_by_risk  # the same test the practice stage uses

    lo = datetime.combine(start, time(0, 0), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=IST)
    runs = db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(live),
            BrainRun.status == "done",
            BrainRun.book == settings.TRADING_MODE,
            BrainRun.as_of >= lo,
            BrainRun.as_of < hi,
        )
        .order_by(BrainRun.started_at.asc())
    ).scalars()
    latest: dict[date, BrainRun] = {}
    for r in runs:  # a later run of the same day replaces an earlier one
        latest[r.as_of.astimezone(IST).date()] = r
    sessions = []
    for day in sorted(latest):
        run = latest[day]
        rows = db.execute(
            select(BrainDecision).where(BrainDecision.run_id == run.id, BrainDecision.kind == "idea")
        ).scalars()
        ideas = tuple(
            # Only a model score or a calibrated chance ranks stocks; any other number is not a score.
            Idea(
                d.symbol,
                d.overruled_word or d.word,
                d.confidence if d.score_source else None,
                blocked=blocked_by_risk(d),
            )
            for d in rows
        )
        sessions.append(Session(day, run.banner_mode, ideas))
    return sessions


# --- the report -----------------------------------------------------------------------------------


def _pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def plain_report(j: dict) -> str:
    r, s = j["rule"], j["summaries"]
    lines = ["# Trial journal", ""]
    if j["sessions"] == 0:
        return "# Trial journal\n\nNo live nightly brain runs in this range, so there is nothing to record.\n"
    if j.get("source") == "replay":
        lines += [
            "**Replay, not live.** These sessions were re-run on past days, so there are no TRADE words "
            "(the risk gate refuses replays) and the account is not simulated. Only the score-based sets mean anything.",
            "",
        ]
    lines += [
        f"{j['sessions']} sessions, {j['first_day']} to {j['last_day']}. Rule: next-day open, "
        f"+{r['target']:.0%} / -{r['stop']:.0%}, half out at +5%, {r['horizon']} trading days, costs and slippage included.",
        "",
    ]
    g = gate(j)
    lines.append(f"**Gate answer: {g['word']}.** {_gate_text(g)}")
    if g["clearly_worse"]:
        lines.append("")
        lines.append("**Warning: brain TRADE ideas did more than 1 point worse per day than every stock.**")
    lines.append("")
    if j["enough_sessions"]:
        lines.append(f"{j['sessions']} sessions: the minimum of {MIN_SESSIONS} is met. Read the table below with its caveats.")
    else:
        lines.append(
            f"**Too early: {j['sessions']} of {MIN_SESSIONS} sessions.** The numbers below are a record, not a result."
        )
    lines += [
        "",
        "## What following each signal would have done (finished ideas only, after costs)",
        "| Followed | Picked | Finished | Still open | Hit target | Average per idea | Better than every stock |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in (*SETS, "every_stock"):
        row = s[name]
        picked = row.get("picked", "")
        open_n = row.get("still_open", "")
        edge = _pct(row.get("edge_vs_every_stock")) if name != "every_stock" else "-"
        lines.append(
            f"| {SET_NAMES[name]} | {picked} | {row['ideas']} | {open_n} | {_pct(row['hit_rate'], 0)} | "
            f"{_pct(row['avg_net'])} | {edge} |"
        )
    nifty = s.get("nifty")
    if nifty is not None:
        lines.append(
            f"| NIFTY 50, held 15 sessions (no costs) | {nifty['finished'] + nifty['open']} | {nifty['finished']} | "
            f"{nifty['open']} | - | {_pct(nifty['avg'])} | - |"
        )
    lines.append("| Cash | - | - | - | - | 0.00% | - |")
    brain_finished = s["brain_trade"]["ideas"]
    lines += [
        "",
        "Read the bottom two rows as: would simply holding the market, or doing nothing, have done better?",
        "",
        f"Brain TRADE ideas finished: {brain_finished} of {GATE_IDEAS} the go-live gate asks for.",
        "",
        "## Session by session",
        "| Day | Banner | TRADE | WATCH | WAIT | AVOID | Top 5 and how each did |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in j["days"]:
        w = d["words"]
        top = ", ".join(_pick_text(p) for p in d["picks"]["brain_top5"]) or "none"
        lines.append(
            f"| {d['day']} | {d['banner'] or '-'} | {w.get('TRADE', 0)} | {w.get('WATCH', 0)} | "
            f"{w.get('WAIT', 0)} | {w.get('AVOID', 0)} | {top} |"
        )
    lines += [
        "",
        "## Read this before drawing a conclusion",
        f"- An idea needs {r['horizon']} trading days to finish, so the last sessions of a window are still open. "
        f"A {MIN_SESSIONS}-session trial is only fully scored about {MIN_SESSIONS} sessions after it ends.",
        "- Ideas from the same day share one market; a few good or bad weeks can decide the result.",
        "- 'Better than every stock' is the average of daily differences. It has no confidence bound under 30 days.",
        "- The pool is the stocks the brain looked at each day (today's instrument list), so stocks that were "
        "later dropped are missing.",
        "- A daily candle cannot say whether the target or the stop came first; a bar touching both counts as the stop.",
        "- Nothing here changes a rule. Use it to see what the signals did, then decide.",
    ]
    return "\n".join(lines) + "\n"


def _gate_text(g: dict) -> str:
    if g["word"] == "too early":
        return (
            f"Needs {MIN_SESSIONS} sessions and {GATE_MIN_IDEAS} finished TRADE ideas; "
            f"has {g['sessions']} and {g['finished']}."
        )
    parts = [
        "profit after costs: " + ("yes" if g["profit"] else "no"),
        "better than every stock: " + ("yes" if g["beats_random"] else "no"),
    ]
    tail = (
        " You may move to 'Your OK needed'; each buy still needs your Approve."
        if g["word"] == "pass"
        else " Stay in Practice and keep recording."
    )
    return "; ".join(parts) + "." + tail + " Safety limits are not checked by this report."


def _pick_text(p: dict) -> str:
    if p["status"] in ("target", "stop", "timeout"):
        return f"{p['symbol']} {p['status']} {_pct(p['net'], 1)}"
    if p["status"] == "open":
        return f"{p['symbol']} open ({_pct(p['so_far'], 1)} so far)"
    return f"{p['symbol']} {p['status']}"


def write_journal(j: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"trial_journal_{j['first_day']}_{j['last_day']}"
    md, js = directory / f"{stem}.md", directory / f"{stem}.json"
    md.write_text(plain_report(j), encoding="utf-8")
    js.write_text(json.dumps(j, indent=1, default=str), encoding="utf-8")
    return md, js


def journal_for(db, start: date, end: date, *, replays: bool = False) -> dict:
    """Read sessions, prices, version 1's buys and NIFTY from the database and build the journal, with
    its gate answer. Read-only: shared by the command line and the API."""
    from swing_trade_ml.brain.replay_score import load_bars, v1_buys
    from swing_trade_ml.core.config import settings

    sessions = load_sessions(db, start, end, live=not replays)
    v1 = v1_buys(db, start, end)
    symbols = sorted({i.symbol for s in sessions for i in s.ideas} | {x for v in v1.values() for x in v})
    upto = end + timedelta(days=60)  # ideas from the last session need about 15 more sessions to finish
    bars = load_bars(db, symbols, upto)
    index = settings.BENCHMARK_INDEX_SYMBOL
    index_bars = load_bars(db, [index], upto).get(index)
    journal = build_journal(sessions, bars, v1, index_bars=index_bars)
    journal["source"] = "replay" if replays else "live"
    journal["gate"] = gate(journal)
    return journal


def main(argv: Sequence[str] | None = None) -> int:
    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Trial journal: signals, and what following them would have done")
    p.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD: first session")
    p.add_argument("--to", dest="end", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--out", default="docs/brain/evidence")
    p.add_argument("--replays", action="store_true", help="read replayed runs (local practice) instead of live ones")
    a = p.parse_args(argv)
    start = date.fromisoformat(a.start)
    end = date.fromisoformat(a.end) if a.end else datetime.now(IST).date()
    with SessionLocal() as db:
        journal = journal_for(db, start, end, replays=a.replays)
    print(plain_report(journal))
    if journal["sessions"]:
        md, js = write_journal(journal, Path(a.out))
        print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
