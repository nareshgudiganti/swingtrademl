"""oa11 Insights: day / week / month figures for the practice book and the real book, side by side, with two
benchmarks after costs. Read-only; nothing here trades, scores or changes a decision.

- Practice (paper): version 1's own trades, with exactly the filters of `beginner_views.bot_paper_figures`
  (paper, no testing book, no hand books, the brain strategy left out so its sealed trial never reaches here).
- Real: trades of the real Zerodha book (`real_trading` strategy, live mode), as /portfolio/trades?book=real.
  Only built for a caller allowed to see the real account; the endpoint decides that.
- The two are never added together: there is no total row or field anywhere in this module.
- Benchmarks reuse evidence-defs-v1's buy-and-hold rule (`baselines.nifty_hold`): bought at the period's
  first trading day open, sold at its last trading day close, one round trip of slippage and charges.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.replay_scoring import POSITION_INR
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import TradingMode
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.core.strategy_policy import outside_tester_book
from swing_trade_ml.db.models.trading import Strategy, Trade
from swing_trade_ml.services.beginner_views import PAPER_LABEL, _not_brain
from swing_trade_ml.services.brain_observatory import baselines, defs, queries
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME, exclude_hand_books

Period = Literal["day", "week", "month"]
HOW_MANY: dict[str, int] = {"day": 15, "week": 12, "month": 12}
BRAIN_BOOK = "paper"  # the brain's practice runs, as the Observatory's `outcomes.BOOK`
REAL_LABEL = "Real money (your Zerodha account)"

DEFINITIONS = {
    "paper": (
        "Version 1's practice-money trades that finished in the period: the bot's own book only (testing "
        "trades, your own buys and the brain's sealed trial are left out). Result is after all costs. "
        "'Return on money used' = that result divided by the money put into those trades."
    ),
    "real": (
        "Trades closed in your real Zerodha account (My Holdings) in the period, after the costs recorded "
        "on each trade. Same 'return on money used' rule."
    ),
    "nifty_50": (
        f"NIFTY 50 bought with Rs {POSITION_INR:,.0f} at the open of the period's first trading day and sold "
        "at the close of its last trading day, with one round trip of slippage and charges "
        f"({defs.EVIDENCE_DEFS_VERSION}: the Observatory's 'NIFTY bought and held')."
    ),
    "every_stock": (
        "Every stock the brain looked at in its live practice runs during the period (the Observatory's "
        "'every stock' pool), each bought with the same money at the open of the period's first trading day "
        "and sold at the close of its last, same slippage and charges; the plain average of those stocks. "
        "Only stocks with prices on both days count."
    ),
}
NOTE = (
    "Practice money and real money are shown side by side and never added together. The benchmarks are "
    "buy-and-hold over the whole period; the bot's figure is per finished trade. Read the comparison as a "
    "guide, not as proof."
)


# --- periods ------------------------------------------------------------------------------------------


def _label(period: str, first: date, last: date) -> str:
    if period == "day":
        return f"{first.day} {first:%b %Y}"
    if period == "week":
        return f"Week of {first.day} {first:%b}" + (f" (to {last.day} {last:%b})" if last != first else "")
    return f"{first:%B %Y}"


def periods(period: str, today: date, start: date | None) -> list[dict]:
    """The last HOW_MANY[period] periods ending today, newest first, never before `start`.
    Days are Monday to Friday; weeks start on Monday; a period is cut at today and at `start`."""
    out: list[dict] = []
    cursor = today
    while len(out) < HOW_MANY[period]:
        if period == "day":
            if cursor.weekday() >= 5:
                cursor -= timedelta(days=1)
                continue
            first, last = cursor, cursor
            nxt = cursor - timedelta(days=1)
        elif period == "week":
            first = cursor - timedelta(days=cursor.weekday())
            last = min(first + timedelta(days=6), today)
            nxt = first - timedelta(days=1)
        else:
            first = cursor.replace(day=1)
            following = (first + timedelta(days=32)).replace(day=1)
            last = min(following - timedelta(days=1), today)
            nxt = first - timedelta(days=1)
        if start is not None and last < start:
            break
        if start is not None and first < start:
            first = start
        out.append(
            {"key": first.isoformat(), "label": _label(period, first, last), "from": first, "to": last}
        )
        cursor = nxt
    return out


# --- trades -------------------------------------------------------------------------------------------


def _paper_where():
    return (
        Trade.mode == TradingMode.PAPER,
        outside_tester_book(Trade.strategy_id),
        exclude_hand_books(Trade.strategy_id),
        _not_brain(Trade.strategy_id),
    )


def _real_where():
    real_ids = select(Strategy.id).where(Strategy.name == REAL_TRADING_STRATEGY_NAME)
    return (Trade.mode == TradingMode.LIVE, Trade.strategy_id.in_(real_ids))


def _empty() -> dict:
    return {"finished": 0, "wins": 0, "net_pnl": 0.0, "charges": 0.0, "money_used": 0.0, "return_pct": None}


def book_by_period(db: Session, where, rows: list[dict]) -> dict[str, dict]:
    """Finished trades per period by their exit day (IST). Every period is present; one with no trades
    has zeros and no return (None, never 0%)."""
    out = {p["key"]: _empty() for p in rows}
    if not rows:
        return out
    lo = datetime.combine(min(p["from"] for p in rows), time.min, tzinfo=IST)
    hi = datetime.combine(max(p["to"] for p in rows) + timedelta(days=1), time.min, tzinfo=IST)
    trades = db.execute(
        select(
            Trade.exit_at, Trade.net_pnl, Trade.charges, Trade.is_win, Trade.entry_price, Trade.quantity
        ).where(*where, Trade.exit_at >= lo, Trade.exit_at < hi)
    ).all()
    for exit_at, net, charges, win, entry, qty in trades:
        d = exit_at.astimezone(IST).date()
        for p in rows:
            if p["from"] <= d <= p["to"]:
                r = out[p["key"]]
                r["finished"] += 1
                r["wins"] += 1 if win else 0
                r["net_pnl"] += float(net or 0.0)
                r["charges"] += float(charges or 0.0)
                r["money_used"] += float(entry or 0.0) * int(qty or 0)
                break
    for r in out.values():
        r["net_pnl"] = round(r["net_pnl"], 2)
        r["charges"] = round(r["charges"], 2)
        r["money_used"] = round(r["money_used"], 2)
        r["return_pct"] = round(r["net_pnl"] / r["money_used"] * 100, 2) if r["money_used"] > 0 else None
    return out


# --- benchmarks ---------------------------------------------------------------------------------------


def _hold_pct(bars, first: date, last: date) -> float | None:
    """evidence-defs-v1 buy-and-hold (baselines.nifty_hold) over [first, last], as a % after costs."""
    if bars is None or bars.empty:
        return None
    res = baselines.nifty_hold(bars, [first, last], POSITION_INR)
    return None if res is None else res["final_net_return"] * 100


def _na(why: str) -> dict:
    return {"pct": None, "why": why}


def benchmarks(db: Session, rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not rows:
        return out
    lo, hi = min(p["from"] for p in rows), max(p["to"] for p in rows)
    index = settings.BENCHMARK_INDEX_SYMBOL
    index_bars = queries.daily_bars(db, [index], lo, hi).get(index)
    sessions = queries.nightly_sessions(db, lo, hi, live=True, book=BRAIN_BOOK)
    pool_symbols = sorted({i.symbol for s in sessions for i in s.ideas})
    bars = queries.daily_bars(db, pool_symbols, lo, hi)
    for p in rows:
        first, last = p["from"], p["to"]
        idx_days = (
            sorted(d for d in index_bars["day"] if first <= d <= last) if index_bars is not None else []
        )
        nifty = _hold_pct(index_bars, idx_days[0], idx_days[-1]) if idx_days else None
        n_row = (
            {"pct": round(nifty, 2), "why": None}
            if nifty is not None
            else _na("No NIFTY 50 prices are stored for these days.")
        )

        pool = sorted({i.symbol for s in sessions if first <= s.day <= last for i in s.ideas})
        if not pool:
            e_row = {**_na("The brain made no live practice run in these days."), "stocks": 0}
        else:
            days = sorted({d for s in pool if s in bars for d in bars[s]["day"] if first <= d <= last})
            pcts = []
            if days:
                d0, d1 = days[0], days[-1]
                for s in pool:
                    df = bars.get(s)
                    if df is None:
                        continue
                    have = set(df["day"])
                    if d0 in have and d1 in have:
                        v = _hold_pct(df, d0, d1)
                        if v is not None:
                            pcts.append(v)
            e_row = (
                {"pct": round(sum(pcts) / len(pcts), 2), "why": None, "stocks": len(pcts)}
                if pcts
                else {**_na("No prices are stored for those stocks on these days."), "stocks": 0}
            )
        out[p["key"]] = {"nifty_50": n_row, "every_stock": e_row}
    return out


# --- the one function ---------------------------------------------------------------------------------


def build(db: Session, period: str, today: date, *, with_real: bool) -> dict:
    """Day / week / month rows. `with_real` is decided by the caller from the principal; when False the
    real book is not read at all and `real` is None."""
    if period not in HOW_MANY:
        raise ValueError(f"period must be one of {tuple(HOW_MANY)}")
    start = settings.PAPER_TRIAL_START_DATE
    rows = periods(period, today, start)
    paper = book_by_period(db, _paper_where(), rows)
    real = book_by_period(db, _real_where(), rows) if with_real else None
    bench = benchmarks(db, rows)
    return {
        "period": period,
        "today": today.isoformat(),
        "since": start.isoformat() if start else None,
        "paper_label": PAPER_LABEL,
        "real_label": REAL_LABEL if with_real else None,
        "real_shown": with_real,
        "defs": defs.EVIDENCE_DEFS_VERSION,
        "definitions": DEFINITIONS if with_real else {k: v for k, v in DEFINITIONS.items() if k != "real"},
        "note": NOTE,
        "rows": [
            {
                "key": p["key"],
                "label": p["label"],
                "from": p["from"].isoformat(),
                "to": p["to"].isoformat(),
                "paper": paper[p["key"]],
                "real": real[p["key"]] if real is not None else None,
                **bench.get(p["key"], {"nifty_50": _na("No prices."), "every_stock": _na("No prices.")}),
            }
            for p in rows
        ],
    }
