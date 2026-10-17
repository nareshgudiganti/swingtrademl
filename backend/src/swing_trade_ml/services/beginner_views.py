"""Read-only helpers that turn trade plans into beginner-friendly numbers.

`money_at_stake` is pure; the event helpers below only read the database.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.modules.m13_news.calendar import trading_days_until
from swing_trade_ml.brain.trial_journal import TRIAL_START as BRAIN_TRIAL_START
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import PortfolioSnapshot, Position
from swing_trade_ml.services.brain_golive.compare import NEEDED_FINISHED, finished_brain_ideas
from swing_trade_ml.services.costs import compute_charges
from swing_trade_ml.services.portfolio import (
    exclude_hand_books,
    exclude_real_trading,
    performance_stats,
    trial_start,
)


def _charges(turnover: float, side: str) -> float:
    brokerage, taxes = compute_charges(turnover, side)
    return brokerage + taxes


def _unavailable(why: str) -> dict:
    return {
        "available": False,
        "why": why,
        "invested": 0.0,
        "loss_if_stop": 0.0,
        "gain_if_target": 0.0,
        "gain_if_half_out": 0.0,
        "charges_round_trip": 0.0,
    }


def money_at_stake(
    entry: float | None,
    stop: float | None,
    target: float | None,
    qty: int,
) -> dict:
    """Rupees at stake for a plan, after real charges.

    `loss_if_stop` and `gain_if_target` are net of the buy leg plus the sell
    leg at their own exit price. `charges_round_trip` is the buy leg plus the
    sell leg at the TARGET price. `gain_if_half_out` sells qty // 2 at
    entry * (1 + ML_FIRST_TARGET_PCT) and the rest at target, each sell leg
    paying its own charges (including the flat depository fee).
    """
    if qty is None or qty <= 0:
        return _unavailable("No shares allowed")
    if entry is None or stop is None or target is None or stop >= entry or target <= entry:
        return _unavailable("Plan incomplete")

    invested = qty * entry
    buy = _charges(invested, "BUY")
    sell_stop = _charges(qty * stop, "SELL")
    sell_target = _charges(qty * target, "SELL")

    loss = (entry - stop) * qty + buy + sell_stop
    gain = (target - entry) * qty - buy - sell_target

    first_qty = qty // 2
    rest_qty = qty - first_qty
    first_price = entry * (1 + settings.ML_FIRST_TARGET_PCT)
    half = (first_price - entry) * first_qty + (target - entry) * rest_qty - buy
    if first_qty > 0:
        half -= _charges(first_qty * first_price, "SELL")
    half -= _charges(rest_qty * target, "SELL")

    return {
        "available": True,
        "why": None,
        "invested": round(invested, 2),
        "loss_if_stop": round(loss, 2),
        "gain_if_target": round(gain, 2),
        "gain_if_half_out": round(half, 2),
        "charges_round_trip": round(buy + sell_target, 2),
    }


# ---------------------------------------------------------------------------
# Upcoming events (bx8) — read-only
# ---------------------------------------------------------------------------


def _event_plain(kind: str, detail: str, day: date, days_away: int) -> str:
    """One plain-English line for an upcoming event."""
    if kind == "results":
        when = "today" if days_away == 0 else "tomorrow" if days_away == 1 else f"in {days_away} trading days"
        return f"Results {when} — prices can jump either way"
    return f"{detail or 'Corporate action'} on {day.day} {day:%b}"


def watchlist_symbols(db: Session) -> list[str]:
    rows = db.scalars(select(Instrument.tradingsymbol).where(Instrument.is_watchlisted.is_(True)).distinct())
    return sorted(rows)


def held_symbols(db: Session) -> list[str]:
    """Open PAPER positions of the bot's own book (no My Holdings, no tester)."""
    rows = db.scalars(
        select(Instrument.tradingsymbol)
        .join(Position, Position.instrument_id == Instrument.id)
        .where(
            Position.status == PositionStatus.OPEN,
            Position.mode == TradingMode.PAPER,
            exclude_real_trading(Position.strategy_id),
            exclude_hand_books(Position.strategy_id),
        )
        .distinct()
    )
    return sorted(rows)


def upcoming_events(
    db: Session, symbols: list[str] | None, today: date, trading_days: int = 15
) -> list[dict]:
    """Results and corporate actions within `trading_days` trading days.

    `symbols=None` means every stock; an empty list means none. Days are
    counted on the market calendar (weekends and holidays do not count).
    """
    if symbols is not None and not symbols:
        return []
    stmt = select(UpcomingEvent).where(UpcomingEvent.event_date >= today)
    if symbols is not None:
        stmt = stmt.where(UpcomingEvent.symbol.in_(symbols))
    out = []
    for ev in db.scalars(stmt):
        away = trading_days_until(today, ev.event_date)
        if not 0 <= away <= trading_days:
            continue
        out.append(
            {
                "symbol": ev.symbol,
                "kind": ev.kind,
                "date": ev.event_date.isoformat(),
                "trading_days_away": away,
                "detail": ev.detail or "",
                "plain": _event_plain(ev.kind, ev.detail or "", ev.event_date, away),
            }
        )
    out.sort(key=lambda r: (r["date"], r["symbol"]))
    return out


# ---- bx4: evidence summary -------------------------------------------------

PAPER_LABEL = "Practice money (paper)"
ENOUGH_TRADES = 30
FEW_TRADES_NOTE = "Too few finished trades to judge — this could be luck."
SEALED_NOTE = "Results stay hidden until the planned review so the test stays fair."


def period_change_pct(db: Session, instrument_ids: list[int], since: datetime) -> float | None:
    """Equal-weight mean % change of daily closes, from the first stored day on/after `since`
    to the latest stored day. Only instruments with a candle on BOTH of those days count.
    None when there is no data or the period is a single day, never 0 as a guess."""
    if not instrument_ids:
        return None
    rows = db.execute(
        select(Candle.instrument_id, Candle.ts, Candle.close).where(
            Candle.instrument_id.in_(instrument_ids), Candle.interval == "day", Candle.ts >= since
        )
    ).all()
    closes: dict[int, dict[date, float]] = {}
    for iid, ts, close in rows:
        closes.setdefault(iid, {})[ts.astimezone(IST).date()] = close
    days = {d for per in closes.values() for d in per}
    if len(days) < 2:
        return None
    first, last = min(days), max(days)
    changes = [
        (per[last] / per[first] - 1) * 100
        for per in closes.values()
        if first in per and last in per and per[first]
    ]
    return round(sum(changes) / len(changes), 2) if changes else None


def evidence_summary(db: Session) -> dict:
    """Plain-figure summary of the v1 paper bot since the trial began, plus a SEALED brain-trial
    count. No brain win rate, profit or comparison is ever returned here."""
    stats = performance_stats(db, mode=TradingMode.PAPER, bot_book_only=True)
    since = trial_start(TradingMode.PAPER)
    finished = int(stats["total_trades"])
    enough = finished >= ENOUGH_TRADES

    # Account-wide even with bot_book_only: snapshots hold one total per mode (portfolio.py).
    # Fewer than 2 trial snapshots means no fall can be measured: None, never 0.
    n_snaps = (
        db.scalar(
            select(func.count())
            .select_from(PortfolioSnapshot)
            .where(PortfolioSnapshot.mode == TradingMode.PAPER, PortfolioSnapshot.ts >= since)
        )
        if since is not None
        else 0
    )
    worst_fall = round(stats["max_drawdown_pct"] * 100, 2) if n_snaps > 1 else None

    nifty = every = None
    if since is not None:
        nifty_ids = list(
            db.scalars(
                select(Instrument.id).where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL)
            )
        )
        watch_ids = list(db.scalars(select(Instrument.id).where(Instrument.is_watchlisted.is_(True))))
        nifty = period_change_pct(db, nifty_ids, since)
        every = period_change_pct(db, watch_ids, since)

    return {
        "paper_label": PAPER_LABEL,
        "bot": {
            "since": since.date().isoformat() if since else None,
            "profit_booked": stats["realized_pnl"],
            "profit_open": stats["unrealized_pnl"],
            "costs_paid": stats["total_charges"],
            "worst_fall_from_peak_pct": worst_fall,
            "finished_trades": finished,
            "win_rate_pct": round(stats["win_rate"] * 100, 1) if finished else None,
            "nifty_same_period_pct": nifty,
            "every_stock_same_period_pct": every,
            "enough_trades": enough,
            "note": "" if enough else FEW_TRADES_NOTE,
        },
        "brain_trial": {
            "since": BRAIN_TRIAL_START.isoformat(),
            "finished": finished_brain_ideas(db),
            "needed": NEEDED_FINISHED,
            "sealed": True,
            "sealed_note": SEALED_NOTE,
        },
    }


# ---- bx1: stock brief (six plain questions) --------------------------------

EVIDENCE_CLAIM = "model_ranking_predictive"


def _day_text(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def _gap(answer: str, why: str, **extra) -> dict:
    return {"answer": answer, "available": False, "why": why, **extra}


def _company(db: Session, inst: Instrument) -> dict:
    from swing_trade_ml.db.models.ml import MLModel, ModelStatus
    from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name
    from swing_trade_ml.strategies.tier import cap_tier

    sym = inst.tradingsymbol
    bucket = get_sector_bucket(sym)
    sector = sector_display_name(bucket) if bucket else None
    size = None
    for m in db.scalars(select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)):
        if sym in (m.training_symbols or []):
            size = {"large": "Large", "midcap": "Mid", "smallcap": "Small"}[cap_tier(m.name)]
            break
    if not inst.name:
        return _gap(
            "Company details not available",
            "No company name is stored for this stock",
            sector=sector,
            size=size,
        )
    parts = [inst.name, f"{sector} sector" if sector else "sector not available"]
    parts.append(f"{size} size" if size else "size not available")
    return {
        "answer": " · ".join(parts),
        "available": True,
        "why": None,
        "name": inst.name,
        "sector": sector,
        "size": size,
    }


def _latest_nightly(db: Session):
    from swing_trade_ml.db.models.brain import BrainRun

    return db.scalars(
        select(BrainRun)
        .where(BrainRun.kind == "nightly", BrainRun.status == "done")
        .order_by(BrainRun.as_of.desc())
        .limit(1)
    ).first()


def _evidence_answer() -> dict:
    from swing_trade_ml.services.brain_observatory import verdicts

    claims = {c["claim"]: c for c in verdicts.evaluate(verdicts.load_registry())}
    c = claims[EVIDENCE_CLAIM]
    return {
        "answer": c["word"],
        "available": True,
        "why": None,
        "claim": EVIDENCE_CLAIM,
        "claim_label": c["label"],
    }


def stock_brief(db: Session, symbol: str, today: date) -> dict:
    """Six plain answers about one stock, from stored data only (never runs the brain).

    Raises LookupError for a symbol that is not an instrument we hold.
    """
    from swing_trade_ml.core.market_session import next_trading_day
    from swing_trade_ml.db.models.brain import BrainDecision

    symbol = symbol.upper()
    inst = db.scalars(select(Instrument).where(Instrument.tradingsymbol == symbol).limit(1)).first()
    if inst is None:
        raise LookupError(symbol)

    run = _latest_nightly(db)
    dec = None
    if run is not None:
        dec = db.scalars(
            select(BrainDecision)
            .where(BrainDecision.run_id == run.id, BrainDecision.symbol == symbol)
            .order_by(BrainDecision.id.desc())
            .limit(1)
        ).first()

    events = upcoming_events(db, [symbol], today)
    if events:
        q5 = {"answer": events[0]["plain"], "available": True, "why": None, "events": events}
    else:
        q5 = {
            "answer": "Nothing scheduled in the next 15 trading days",
            "available": True,
            "why": None,
            "events": [],
        }

    out = {
        "symbol": symbol,
        "as_of": run.as_of.isoformat() if run else None,
        "q1_company": _company(db, inst),
    }
    if dec is None:
        if run is None:
            why = "There is no brain run on record yet"
        else:
            why = f"The brain's last run was on {_day_text(run.as_of.astimezone(IST).date())}"
        no = "The brain has not looked at this stock today"
        out["q2_brain"] = _gap(no, why)
        out["q3_plan"] = _gap("No plan without a brain decision", why)
        out["q4_money"] = _gap("No figures without a plan", why)
    else:
        out["q2_brain"] = {
            "answer": f"{dec.word}: " + ("; ".join(dec.reasons or []) or "no reasons recorded"),
            "available": True,
            "why": None,
            "decision": {
                "id": dec.id,
                "run_id": dec.run_id,
                "symbol": dec.symbol,
                "kind": dec.kind,
                "word": dec.word,
                "reasons": list(dec.reasons or []),
                "entry_low": dec.entry_low,
                "entry_high": dec.entry_high,
                "target": dec.target,
                "stop": dec.stop,
                "qty": dec.qty,
                "horizon_days": dec.horizon_days,
                "confidence": dec.confidence,
                "honest_score": None,
                "evidence_text": dec.evidence_text,
                "downgraded_from": dec.downgraded_from,
                "downgrade_reason": dec.downgrade_reason,
                "overruled_word": dec.overruled_word,
                "overrule_reason": dec.overrule_reason,
                "overruled_by": dec.overruled_by,
                "overruled_at": dec.overruled_at,
            },
        }
        have_zone = dec.entry_low is not None and dec.entry_high is not None
        entry = (dec.entry_low + dec.entry_high) / 2 if have_zone else None
        if dec.target is None or dec.stop is None or not have_zone:
            out["q3_plan"] = _gap(
                "The plan is incomplete", "The brain did not give a full buy zone, target and stop"
            )
        else:
            day = run.as_of.astimezone(IST).date()
            for _ in range(dec.horizon_days):
                day = next_trading_day(day)
            out["q3_plan"] = {
                "answer": f"Buy between {dec.entry_low:g} and {dec.entry_high:g}, sell half at +"
                f"{settings.ML_FIRST_TARGET_PCT:.0%}, target {dec.target:g}, stop {dec.stop:g}, "
                f"out by {_day_text(day)}",
                "available": True,
                "why": None,
                "buy_zone": [dec.entry_low, dec.entry_high],
                "sell_half_price": round(entry * (1 + settings.ML_FIRST_TARGET_PCT), 2),
                "sell_half_pct": settings.ML_FIRST_TARGET_PCT,
                "target": dec.target,
                "target_pct": settings.ML_TARGET_RETURN_PCT,
                "stop": dec.stop,
                "stop_pct": settings.ML_STOP_RETURN_PCT,
                "last_exit_day": day.isoformat(),
            }
        money = money_at_stake(entry, dec.stop, dec.target, dec.qty or 0)
        if money["available"]:
            money = {
                "answer": f"About ₹{money['invested']:,.0f} in; ₹{money['loss_if_stop']:,.0f} lost "
                f"if the stop hits; ₹{money['gain_if_target']:,.0f} gained at the target (after charges)",
                **money,
            }
        else:
            money = {"answer": "Money figures not available", **money}
        out["q4_money"] = money
    out["q5_events"] = q5
    out["q6_evidence"] = _evidence_answer()
    return out
