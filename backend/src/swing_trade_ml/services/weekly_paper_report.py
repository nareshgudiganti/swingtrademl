# ruff: noqa: E501 (long plain-English report sentences, as in brain/lanes/h05_report.py)
"""Weekly report: the 5-day horizon lane, Bot (paper) and Testing (paper), kept apart. Read only.

Three sources, never added together:
  * h05      shadow predictions of the existing 5-day models and their matured outcomes (no money);
  * bot      the paper bot's own book (every paper strategy except the Testing book and hand books);
  * testing  the manual Testing (paper) book, with its own starting capital.

Counting rules, so the numbers can be checked against transaction records:
  * BUY and SELL events come from the ORDER log (completed orders). Counting buys from the positions
    that are still open misses every position that was opened and closed inside the week.
  * Each SELL order has one Trade row (the same fill). The report compares the two counts and shows any
    difference instead of hiding it. A trade with no exit reason is shown as UNCLASSIFIED, never dropped,
    so the exit-reason counts always add up to the SELL count.
  * SCALE_OUT is a partial SELL (part of the position sold at the first target); every other reason is a
    full exit.
  * Realized P&L = the week's trades, net of the charges stored on each trade. Unrealized P&L = open
    positions at their last stored price, before the cost of selling them. They are never summed.

Nothing here writes to the database, places an order or changes a past event.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.strategy_policy import HAND_BOOK_STRATEGY_NAMES
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.strategies.tier import cap_tier

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TESTING_STRATEGY = "tester_paper"
PARTIAL = "SCALE_OUT"
UNCLASSIFIED = "UNCLASSIFIED"
WINDOW_DAYS = 7
# The newest events listed in each book's table.
RECENT_EVENT_LIMIT = 60


def source_of(strategy_name: str | None) -> str | None:
    """'testing', 'bot', or None for a hand book (My Holdings / Real Trading), which is not part of this report."""
    if strategy_name == TESTING_STRATEGY:
        return "testing"
    if strategy_name in HAND_BOOK_STRATEGY_NAMES:
        return None
    return "bot"


def is_brain_strategy(name: str | None, strategy_type: str | None = None) -> bool:
    """The TradeMind brain's own paper strategy, matched by name and by type (as `ensure_brain_strategy` does)."""
    from swing_trade_ml.services.brain_golive.shadow import BRAIN_STRATEGY_NAME

    return name == BRAIN_STRATEGY_NAME or strategy_type == "brain"


# ----------------------------------------------------------------------- pure summary --


def _pnl_block(trades: list[dict]) -> dict[str, Any]:
    return {
        "gross": round(sum(t["gross_pnl"] for t in trades), 2),
        "charges": round(sum(t["charges"] for t in trades), 2),
        "net": round(sum(t["net_pnl"] for t in trades), 2),
    }


def summarise_book(
    orders: list[dict], trades: list[dict], open_positions: list[dict], start: date, end: date
) -> dict[str, Any]:
    """One book's week from plain dicts (so it can be tested without a database).

    orders:   id, side, status, on (IST date), symbol, strategy, cap_tier
    trades:   id, symbol, strategy, cap_tier, exit_on, exit_reason, gross_pnl, charges, net_pnl, return_pct, holding_days
    open_positions: symbol, strategy, cap_tier, invested, unrealized_pnl, current_price, stop_loss, take_profit
    """
    in_window = lambda d: start <= d <= end  # noqa: E731
    done = [o for o in orders if o["status"] == "COMPLETE" and in_window(o["on"])]
    buys = [o for o in done if o["side"] == "BUY"]
    sells = [o for o in done if o["side"] == "SELL"]
    week_trades = [t for t in trades if in_window(t["exit_on"])]

    reasons = Counter((t["exit_reason"] or UNCLASSIFIED) for t in week_trades)
    partial = reasons.get(PARTIAL, 0)
    full = len(week_trades) - partial

    by_tier: dict[str, dict[str, Any]] = {}
    for tier in sorted({t["cap_tier"] or "unknown" for t in week_trades}):
        rows = [t for t in week_trades if (t["cap_tier"] or "unknown") == tier]
        by_tier[tier] = {
            "sells": len(rows),
            "wins": sum(1 for t in rows if t["net_pnl"] > 0),
            "net_pnl": round(sum(t["net_pnl"] for t in rows), 2),
            "avg_return_pct": round(sum(t["return_pct"] for t in rows) / len(rows) * 100, 2)
            if rows
            else None,
        }

    invested = sum(p["invested"] for p in open_positions)
    return {
        "buys": {
            "orders": len(buys),
            "stocks": len({o["symbol"] for o in buys}),
            "by_strategy": dict(Counter(o["strategy"] or "none" for o in buys)),
        },
        "sells": {
            "orders": len(sells),
            "trade_rows": len(week_trades),
            "partial": partial,
            "full": full,
            "exit_reasons": dict(sorted(reasons.items())),
            "by_strategy": dict(Counter(t["strategy"] or "none" for t in week_trades)),
        },
        "reconciliation": {
            "sell_orders_equal_trade_rows": len(sells) == len(week_trades),
            "exit_reasons_add_up": sum(reasons.values()) == len(week_trades),
            "unclassified_exits": reasons.get(UNCLASSIFIED, 0),
            "note": "BUYs are counted from completed BUY orders, SELLs from completed SELL orders and checked against the trade rows.",
        },
        "positions": {
            "open": len(open_positions),
            "invested": round(invested, 2),
            "closed_in_week": full,
            "partially_sold_in_week": partial,
        },
        "realized_pnl": {**_pnl_block(week_trades), "wins": sum(1 for t in week_trades if t["net_pnl"] > 0)},
        "unrealized_pnl": {
            "amount": round(sum(p["unrealized_pnl"] for p in open_positions), 2),
            "pct_of_invested": round(sum(p["unrealized_pnl"] for p in open_positions) / invested * 100, 2)
            if invested
            else None,
            "note": "open positions at their last stored price, before the cost of selling them",
        },
        "by_cap_group": by_tier,
        "avg_sell_return_pct": round(sum(t["return_pct"] for t in week_trades) / len(week_trades) * 100, 2)
        if week_trades
        else None,
        "events": _events(done, week_trades),
        "data_status": "no buys or sells this week" if not (done or week_trades) else "activity recorded",
    }


def _events(done_orders: list[dict], week_trades: list[dict]) -> list[dict]:
    # A SELL order and its trade row share the position and the exact fill time.
    reason_by_trade = {(t["position_id"], t["at"]): (t["exit_reason"] or UNCLASSIFIED) for t in week_trades}
    rows = []
    for o in done_orders:
        rows.append(
            {
                "on": o["on"].isoformat(),
                "side": o["side"],
                "symbol": o["symbol"],
                "strategy": o["strategy"],
                "exit_reason": reason_by_trade.get((o["position_id"], o["at"]), "NO_TRADE_ROW")
                if o["side"] == "SELL"
                else None,
            }
        )
    return sorted(rows, key=lambda r: (r["on"], r["symbol"]), reverse=True)[:RECENT_EVENT_LIMIT]


# ------------------------------------------------------------------------- database --


def _ist_date(value: datetime) -> date:
    return value.astimezone(IST).date()


def _brain_ids(db: Session) -> set[int]:
    return {
        s.id for s in db.execute(select(Strategy)).scalars() if is_brain_strategy(s.name, s.strategy_type)
    }


def _strategy_maps(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    names, tiers = {}, {}
    for s in db.execute(select(Strategy)).scalars():
        names[s.id] = s.name
        tiers[s.id] = cap_tier((s.params or {}).get("model_name"))
    return names, tiers


def _instrument_tiers(db: Session, position_ids: set[int]) -> dict[int, str | None]:
    """The Testing book picks its tier per trade (stored on the entry signal), so ask the same helper the Testing tab uses."""
    from swing_trade_ml.services.tester_paper import entry_signal_cap_tier

    return {pid: entry_signal_cap_tier(db, pid) for pid in position_ids}


def collect(db: Session, start: date, end: date) -> dict[str, dict[str, list[dict]]]:
    """Plain-dict inputs per source, from paper-mode rows only. Reads only."""
    names, tiers = _strategy_maps(db)
    since = datetime.combine(start - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    out: dict[str, dict[str, list[dict]]] = {
        s: {"orders": [], "trades": [], "open_positions": []} for s in ("bot", "testing", "brain_paper")
    }
    brain_ids = _brain_ids(db)

    def pick(strategy_id: int | None) -> tuple[str | None, str | None, str | None]:
        name = names.get(strategy_id) if strategy_id is not None else None
        if strategy_id in brain_ids:  # the brain's reserved paper slot: its own book, never the Bot's
            return "brain_paper", name, tiers.get(strategy_id)
        # A row with no strategy at all belongs to the bot (same rule as outside_tester_book).
        return (source_of(name) if name is not None else "bot"), name, tiers.get(strategy_id)

    orders = (
        db.execute(select(Order).where(Order.mode == TradingMode.PAPER, Order.placed_at >= since))
        .scalars()
        .all()
    )
    position_ids = {o.position_id for o in orders if o.position_id}
    trades = (
        db.execute(select(Trade).where(Trade.mode == TradingMode.PAPER, Trade.exit_at >= since))
        .scalars()
        .all()
    )
    position_ids |= {t.position_id for t in trades if t.position_id}
    testing_tiers = _instrument_tiers(db, position_ids)

    for o in orders:
        src, name, tier = pick(o.strategy_id)
        if src is None:
            continue
        if src == "testing":
            tier = testing_tiers.get(o.position_id) or tier
        out[src]["orders"].append(
            {
                "id": o.id,
                "side": str(o.transaction_type),
                "status": str(o.status),
                "on": _ist_date(o.placed_at),
                "position_id": o.position_id,
                "at": o.placed_at.isoformat(),
                "symbol": o.instrument.tradingsymbol if o.instrument else str(o.instrument_id),
                "strategy": name,
                "cap_tier": tier,
            }
        )
    for t in trades:
        src, name, tier = pick(t.strategy_id)
        if src is None:
            continue
        if src == "testing":
            tier = testing_tiers.get(t.position_id) or tier
        out[src]["trades"].append(
            {
                "id": t.id,
                "position_id": t.position_id,
                "at": t.exit_at.isoformat(),
                "symbol": t.symbol,
                "strategy": name,
                "cap_tier": tier,
                "exit_on": _ist_date(t.exit_at),
                "exit_reason": str(t.exit_reason) if t.exit_reason else None,
                "gross_pnl": t.gross_pnl,
                "charges": t.charges,
                "net_pnl": t.net_pnl,
                "return_pct": t.return_pct,
                "holding_days": t.holding_days,
            }
        )
    for p in db.execute(
        select(Position).where(Position.mode == TradingMode.PAPER, Position.status == PositionStatus.OPEN)
    ).scalars():
        src, name, tier = pick(p.strategy_id)
        if src is None:
            continue
        if src == "testing":
            tier = testing_tiers.get(p.id) or entry_tier_fallback(db, p.id, tier)
        price = p.current_price or p.entry_price
        out[src]["open_positions"].append(
            {
                "symbol": p.instrument.tradingsymbol if p.instrument else str(p.instrument_id),
                "strategy": name,
                "cap_tier": tier,
                "entry_on": _ist_date(p.entry_at) if p.entry_at else None,
                "invested": p.entry_price * p.quantity,
                "unrealized_pnl": (price - p.entry_price) * p.quantity,
                "current_price": price,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
            }
        )
    return out


def brain_paper_section(books: dict[str, list[dict]], start: date, end: date) -> dict[str, Any]:
    """The brain's paper slot as its own book. While the trial seal is on, days from the trial start are
    COUNTS ONLY (buys, sell orders, open positions): no symbol, price, P&L, return, win, exit reason or
    strategy breakdown. Days before the trial start keep the full book. Never added to the Bot or Testing."""
    from swing_trade_ml.services import trial_seal

    inwin = lambda d: start <= d <= end  # noqa: E731
    done = [o for o in books["orders"] if o["status"] == "COMPLETE" and inwin(o["on"])]
    sealed_o = [o for o in done if trial_seal.is_sealed_day(o["on"])]
    open_sealed = books["open_positions"] if trial_seal.active() else []
    out: dict[str, Any] = {
        "source": "brain_paper",
        "note": "The brain's reserved paper slot. Kept apart from the Bot's results and never added to them.",
    }
    if trial_seal.active():
        out.update(
            sealed=True,
            text="sealed during the trial",
            buys=sum(1 for o in sealed_o if o["side"] == "BUY"),
            sell_orders=sum(1 for o in sealed_o if o["side"] == "SELL"),
            open_positions=len(open_sealed),
        )
    else:
        out["sealed"] = False
    # Days before the trial start (or everything, with the seal off) keep the ordinary full book.
    open_full = [] if trial_seal.active() else books["open_positions"]
    before = summarise_book(
        [o for o in books["orders"] if not trial_seal.is_sealed_day(o["on"])],
        [t for t in books["trades"] if not trial_seal.is_sealed_day(t["exit_on"])],
        open_full,
        start,
        end,
    )
    out["before_trial"] = None if before["data_status"].startswith("no buys") and not open_full else before
    return out


def entry_tier_fallback(db: Session, position_id: int, default: str | None) -> str | None:
    from swing_trade_ml.services.tester_paper import entry_signal_cap_tier

    return entry_signal_cap_tier(db, position_id) or default


def window(now: datetime | None = None) -> tuple[date, date]:
    """Seven calendar days ending on the day before the run, in IST.

    Calendar days, not trading days: the Testing book can be traded on a weekend or a holiday, and week
    after week the windows touch with no gap and no overlap (a Sunday run covers Sunday to Saturday)."""
    today = (now or datetime.now(UTC)).astimezone(IST).date()
    end = today - timedelta(days=1)
    return end - timedelta(days=WINDOW_DAYS - 1), end


def benchmark(db: Session, start: date, end: date) -> dict[str, Any]:
    """NIFTY 50 return over the same window: last close on or before `end` vs the last close before `start`."""
    from swing_trade_ml.ml.market_context import load_index_candles

    df = load_index_candles(db, "day")
    if df.empty:
        return {"available": False, "reason": "no NIFTY 50 candles stored"}
    days = {_ist_date(t.to_pydatetime()): float(c) for t, c in zip(df["ts"], df["close"], strict=False)}
    last = max((d for d in days if d <= end), default=None)
    base = max((d for d in days if d < start), default=None)
    if last is None or base is None or last == base:
        return {"available": False, "reason": "not enough NIFTY 50 candles in the window"}
    return {
        "available": True,
        "index": "NIFTY 50",
        "from": base.isoformat(),
        "to": last.isoformat(),
        "return_pct": round((days[last] / days[base] - 1) * 100, 2),
        "newest_bar": last.isoformat(),
        "note": "price index return, same dates as the week; compare with 'avg sell return', which is per trade, not per rupee",
    }


def outcomes_status(picks_total: int, matured_total: int, matured_in_week: int) -> str:
    """Plain words for how complete the outcome data is, so a missing result is never read as a zero."""
    if picks_total == 0:
        return "no picks recorded yet"
    if matured_total == 0:
        return "no outcomes yet: the 5th session after each signal has not closed"
    if matured_in_week == 0:
        return f"{matured_total} of {picks_total} picks matured in total, none this week"
    return f"{matured_total} of {picks_total} picks matured in total, {matured_in_week} this week"


def h05_section(db: Session, start: date, end: date) -> dict[str, Any]:
    """Predictions recorded and outcomes matured this week, by cap group (large, mid, small)."""
    from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal

    run = (
        db.execute(select(H05Run).where(H05Run.status == "active").order_by(H05Run.run_no.desc()))
        .scalars()
        .first()
    )
    if run is None:
        return {"active": False, "note": "no active h05 run"}
    days = db.execute(select(H05GroupDay).where(H05GroupDay.run_id == run.id)).scalars().all()
    in_week = [d for d in days if start <= d.signal_day <= end]
    groups: dict[str, dict[str, Any]] = {}
    for g in ("large", "mid", "small"):
        sigs = (
            db.execute(
                select(H05Signal).where(
                    H05Signal.run_id == run.id, H05Signal.group == g, H05Signal.status == "scored"
                )
            )
            .scalars()
            .all()
        )
        picks = [s for s in sigs if s.selected]
        # Matured = the 5th session has a close to compare. A pick with no label_hit has not matured (or has no data).
        matured_in_week = [
            s for s in picks if s.label_hit is not None and s.label_day5 and start <= s.label_day5 <= end
        ]
        matured_all = [s for s in sigs if s.label_hit is not None]
        picks_matured_ever = [s for s in picks if s.label_hit is not None]
        week_days = [d for d in in_week if d.group == g]
        groups[g] = {
            "signal_days_recorded": len(week_days),
            "stocks_scored": sum(d.scored_n for d in week_days),
            "picks_made": sum(d.selected_n for d in week_days),
            "picks_matured": len(matured_in_week),
            "picks_hit_plus_2pct": sum(1 for s in matured_in_week if s.label_hit == 1),
            "every_stock_matured_so_far": len(matured_all),
            "stocks_waiting_for_outcome": sum(1 for s in sigs if s.label_status == "pending"),
            "outcomes_status": outcomes_status(len(picks), len(picks_matured_ever), len(matured_in_week)),
        }
    recorded = {d.signal_day for d in days}
    from swing_trade_ml.core.market_session import is_trading_day

    expected = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    expected = [d for d in expected if is_trading_day(d) and run.start_day <= d <= run.end_day]
    events = (
        db.execute(select(H05Event).where(H05Event.run_id == run.id, H05Event.signal_day >= start))
        .scalars()
        .all()
    )
    return {
        "active": True,
        "run_no": run.run_no,
        "horizon": "5 trading days",
        "run": f"{run.start_day} to {run.end_day}",
        "sessions_expected_this_week": len(expected),
        "sessions_recorded_this_week": len([d for d in expected if d in recorded]),
        "sessions_not_recorded": [d.isoformat() for d in expected if d not in recorded],
        "events": [
            {"kind": e.kind, "signal_day": str(e.signal_day), "detail": e.detail[:200]} for e in events
        ],
        "groups": groups,
        "note": "Hit = the close 5 sessions after the signal reached +2% above the signal close. No verdict is drawn from a week.",
    }


def jobs_and_data(db: Session, end: date, now: datetime | None = None) -> dict[str, Any]:
    """Jobs whose last run failed or was missed, and data that is out of date."""
    from swing_trade_ml.workers import job_runs

    now = now or datetime.now(UTC)
    runs, available = job_runs.read_runs()
    problems = []
    for job_id, run in sorted(runs.items()):
        failed = run.get("last_status") not in (None, "ok")
        missed = run.get("last_missed_at")
        if failed or missed:
            problems.append(
                {
                    "job": job_id,
                    "name": job_runs.label_for(job_id)[0],
                    "last_status": run.get("last_status"),
                    "error_kind": run.get("last_error_kind"),
                    "last_started_at": run.get("last_started_at"),
                    "last_missed_at": missed,
                }
            )
    stale = []
    bench = benchmark(db, end - timedelta(days=30), end)
    if bench.get("available") and bench["newest_bar"] < end.isoformat():
        stale.append(
            {"what": "NIFTY 50 daily bars", "newest": bench["newest_bar"], "expected": end.isoformat()}
        )
    return {
        "job_history_available": available,
        "problems": problems,
        "stale_data": stale,
        "note": "job_history_available=false means the worker's run history could not be read, so nothing is claimed about jobs.",
    }


def build_report(db: Session, now: datetime | None = None) -> dict[str, Any]:
    start, end = window(now)
    books = collect(db, start, end)
    report: dict[str, Any] = {
        "title": "Weekly report: 5-day horizon lane, Bot (paper), Testing (paper)",
        "generated_at": (now or datetime.now(UTC)).isoformat(),
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "separate_sources": "h05, bot and testing are three different sources and are never added together",
        "h05": h05_section(db, start, end),
        "bot": summarise_book(**books["bot"], start=start, end=end),
        "testing": summarise_book(**books["testing"], start=start, end=end),
        "brain_paper": brain_paper_section(books["brain_paper"], start, end),
        "benchmark": benchmark(db, start, end),
        "horizons": {
            "5D": "h05 shadow lane above (existing models 2/16/17)",
            "10D": "no lane (the one history test failed; nothing is running)",
            "15D": "sealed trial and the 5 Dec lab: not part of this report",
        },
        "jobs_and_data": jobs_and_data(db, end, now),
    }
    return report


# ---------------------------------------------------------------------------- message --


def _money(x: float) -> str:
    return f"{'-' if x < 0 else ''}₹{abs(x):,.0f}"


def format_message(report: dict[str, Any]) -> str:
    """Short Telegram summary (plain words). The full numbers stay in the report."""
    w = report["window"]
    lines = [f"📊 <b>Weekly report</b> {w['from']} to {w['to']}", ""]
    h = report["h05"]
    if h.get("active"):
        lines.append(
            f"5-day lane: {h['sessions_recorded_this_week']} of {h['sessions_expected_this_week']} sessions recorded; "
            + ", ".join(f"{g} {v['picks_matured']} matured" for g, v in h["groups"].items())
        )
    for key, label in (("bot", "Bot (paper)"), ("testing", "Testing (paper)")):
        b = report[key]
        lines.append(
            f"{label}: {b['buys']['orders']} buys, {b['sells']['orders']} sells "
            f"({b['sells']['partial']} partial), realized {_money(b['realized_pnl']['net'])} after costs, "
            f"open now {_money(b['unrealized_pnl']['amount'])}"
        )
        if not (
            b["reconciliation"]["sell_orders_equal_trade_rows"] and b["reconciliation"]["exit_reasons_add_up"]
        ):
            lines.append(f"⚠️ {label}: sell orders and trade records do not match")
    jd = report["jobs_and_data"]
    if jd["problems"] or jd["stale_data"]:
        lines.append(
            f"⚠️ {len(jd['problems'])} job(s) failed or missed, {len(jd['stale_data'])} stale data source(s)"
        )
    else:
        lines.append("Jobs: no failures or missed runs")
    return "\n".join(lines)
