"""Signal history — the record of what the bot recommended and why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import aliased

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy, Trade
from swing_trade_ml.schemas import SignalOut

router = APIRouter(prefix="/signals", tags=["signals"])


def _cap_tier(model_name: str | None) -> str:
    """Map an ml_swing strategy's model_name param to a cap tier — mirrors
    frontend/src/lib/tiers.ts's TIERS convention. Strategies with no model
    (e.g. sma_crossover) or the default large-cap model both fall back to
    "large".
    """
    if model_name == "swing_classifier_midcap":
        return "midcap"
    if model_name == "swing_classifier_smallcap":
        return "smallcap"
    return "large"


@router.get("", response_model=list[SignalOut])
def list_signals(
    db: DbSession,
    signal_type: str | None = Query(None, description="BUY | SELL | HOLD | EXIT"),
    executed_only: bool = False,
    days: int = Query(30, le=365),
    limit: int = Query(100, le=1000),
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.mode == get_broker().mode, Signal.generated_at >= since)
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    )
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type.upper())
    if executed_only:
        stmt = stmt.where(Signal.was_executed.is_(True))
    return [
        {
            "id": signal.id,
            "strategy_id": signal.strategy_id,
            "instrument_id": signal.instrument_id,
            "tradingsymbol": tradingsymbol,
            "name": name,
            "signal_type": signal.signal_type,
            "mode": signal.mode,
            "price": signal.price,
            "confidence": signal.confidence,
            "suggested_quantity": signal.suggested_quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "features": signal.features,
            "was_executed": signal.was_executed,
            "rejection_reason": signal.rejection_reason,
            "advisory_only": signal.advisory_only,
            "generated_at": signal.generated_at,
        }
        for signal, tradingsymbol, name in db.execute(stmt).all()
    ]


@router.get("/latest", response_model=list[dict])
def latest_actionable(
    db: DbSession,
    limit: int = Query(20, le=100),
    symbol: str | None = Query(
        None, description="Look up one symbol's full score history instead of the cross-strategy feed"
    ),
) -> list[dict]:
    """The most recent BUY/EXIT signals, symbol-resolved for the dashboard.

    HOLD signals are excluded by default — there is one per instrument per
    scan and they would bury the actionable ones. But when `symbol` narrows
    this to one stock, HOLD *is* the useful history (most days for most
    stocks are HOLD, not BUY/EXIT) — so it's included, and the limit ceiling
    opens up, for a "search this stock, see every score, newest first" view.
    """
    stmt = (
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.mode == get_broker().mode)
        .order_by(Signal.generated_at.desc())
    )
    if symbol:
        stmt = stmt.where(Instrument.tradingsymbol == symbol.strip().upper())
        limit = max(limit, 200)
    else:
        stmt = stmt.where(Signal.signal_type.in_(["BUY", "SELL", "EXIT"]))
    rows = db.execute(stmt.limit(limit)).all()

    return [
        {
            "id": signal.id,
            "symbol": symbol,
            "name": name,
            "signal": signal.signal_type,
            "price": signal.price,
            "confidence": signal.confidence,
            "quantity": signal.suggested_quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "executed": signal.was_executed,
            "advisory_only": signal.advisory_only,
            "rejection_reason": signal.rejection_reason,
            "generated_at": signal.generated_at,
        }
        for signal, symbol, name in rows
    ]


def _cap_tier(model_name: str | None) -> str:
    """Cap-tier label from an ml_swing strategy's model_name — see
    ml.sector_map's neighbouring cap-tier convention
    (swing_classifier[_midcap|_smallcap]). Anything else (a non-ML strategy
    like sma_crossover, or no model_name at all) is treated as "large" —
    the safest assumption when tier genuinely isn't known."""
    name = model_name or ""
    if name.endswith("_smallcap"):
        return "smallcap"
    if name.endswith("_midcap"):
        return "midcap"
    return "large"


@router.get("/top-picks", response_model=list[dict])
def top_picks(
    db: DbSession,
    budget: float = Query(25_000.0, gt=0, description="Total real-money rupees to allocate"),
    max_picks: int = Query(5, ge=1, le=20),
    min_confidence: float = Query(0.70, ge=0.5, le=0.99),
    include_smallcap: bool = Query(
        False, description="Small-caps are excluded by default: harder to exit cleanly with real money"
    ),
) -> list[dict]:
    """A short, risk-ranked shortlist for manually buying a few of today's
    paper signals with real money — not a new model, just a stricter filter
    plus a suggested rupee split over `buy_list`'s same fresh-BUY signals.

    Ranking, in order:
    1. Cap-tier: small-caps excluded by default (`include_smallcap=true` to
       include them) — the largest real risk with real money is not being
       able to exit cleanly, which small-caps carry more of regardless of
       model confidence.
    2. Confidence: only signals at/above `min_confidence`, which defaults
       well above the bot's own bare minimum (ML_MIN_CONFIDENCE=0.60) —
       "the model will paper-trade this" and "confident enough to risk real
       money on" are deliberately different bars.
    3. Composite score = confidence, minus a 10-point penalty if the
       signal's own `bear_market` flag is set (see ml_swing.py — it already
       required extra confidence to fire at all, so a signal that only
       barely cleared that raised bar is weaker than its raw confidence
       number suggests), minus the stop-loss distance as a fraction of price
       (capped at 15 points) — a signal with a tighter stop is safer at the
       same confidence, because it risks less if wrong.

    Sizing: `budget` is split across the picks in inverse proportion to each
    one's stop distance (tighter stop -> larger rupee allocation), not split
    evenly — this keeps the rupee amount actually at risk roughly equal
    across picks, which an equal-rupee split would not.

    This does not execute anything — it only ranks and suggests. Nothing
    here places an order; that stays a manual decision in Kite.
    """
    latest_signal = (
        select(Signal)
        .where(Signal.mode == "paper")
        .distinct(Signal.strategy_id, Signal.instrument_id)
        .order_by(Signal.strategy_id, Signal.instrument_id, Signal.generated_at.desc())
    ).subquery()
    LatestSignal = aliased(Signal, latest_signal)  # noqa: N806 — matches buy_list's own convention below

    held_instrument_ids = select(Position.instrument_id).where(
        Position.mode == "paper", Position.status == PositionStatus.OPEN
    )

    rows = db.execute(
        select(LatestSignal, Instrument.tradingsymbol, Instrument.name, Strategy)
        .join(Instrument, Instrument.id == LatestSignal.instrument_id)
        .join(Strategy, Strategy.id == LatestSignal.strategy_id)
        .where(
            LatestSignal.signal_type == "BUY",
            LatestSignal.confidence >= min_confidence,
            LatestSignal.instrument_id.not_in(held_instrument_ids),
        )
    ).all()

    candidates: list[dict] = []
    for sig, symbol, name, strategy in rows:
        tier = _cap_tier(strategy.params.get("model_name") if strategy.params else None)
        if tier == "smallcap" and not include_smallcap:
            continue
        # A share priced above the whole budget can never be bought regardless
        # of how the split works out — exclude it outright rather than let it
        # win a slot and then round down to a useless "buy 0 shares".
        if sig.price and sig.price > budget:
            continue

        stop_pct = (
            max((sig.price - sig.stop_loss) / sig.price, 0.0)
            if sig.stop_loss and sig.price
            else 0.10  # no stop on record — treat as an average-risk guess, not zero risk
        )
        bear_market = bool((sig.features or {}).get("bear_market"))
        score = float(sig.confidence or 0.0) - (0.10 if bear_market else 0.0) - min(stop_pct, 0.15)

        candidates.append(
            {
                "symbol": symbol,
                "name": name,
                "cap_tier": tier,
                "strategy_name": strategy.name,
                "price": sig.price,
                "confidence": sig.confidence,
                "stop_loss": sig.stop_loss,
                "take_profit": sig.take_profit,
                "stop_distance_pct": round(stop_pct, 4),
                "bear_market": bear_market,
                "score": round(score, 4),
                "reason": sig.reason,
                "generated_at": sig.generated_at,
                "_weight": 1.0 / max(stop_pct, 0.01),
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)

    # Selecting the top max_picks by score and splitting the budget can still
    # leave a low-priority, expensive pick rounding down to 0 shares once
    # split among several others — worthless as a recommendation. Rather than
    # show that, drop it and backfill from the next-best remaining candidate,
    # recomputing the split each time, until every surviving pick is
    # actually buyable or candidates run out.
    picks = candidates[:max_picks]
    backfill_pool = candidates[max_picks:]

    while picks:
        total_weight = sum(p["_weight"] for p in picks) or 1.0
        for p in picks:
            p["suggested_allocation_inr"] = round(budget * p["_weight"] / total_weight, 2)
            p["suggested_quantity"] = int(p["suggested_allocation_inr"] // p["price"]) if p["price"] else 0

        unbuyable = [p for p in picks if p["suggested_quantity"] < 1]
        if not unbuyable:
            break
        for p in unbuyable:
            picks.remove(p)
            if backfill_pool:
                picks.append(backfill_pool.pop(0))

    for p in picks:
        del p["_weight"]

    return picks


@router.get("/buy-list", response_model=list[dict])
def buy_list(db: DbSession) -> list[dict]:
    """Every symbol that is a fresh, still-current BUY right now — nothing else.

    Answers "the Signals page shows a BUY row for this stock, but is that
    still true today or from three days ago?" by construction: it's deduped
    to each instrument's single most recent signal (any strategy), then kept
    only if that latest signal is BUY. A stock that reconfirms BUY every day
    for a week stays on the list the whole week; the moment a later scan
    reads HOLD or weaker, it silently drops off next call — no manual
    dismissal needed for that case, since a stale row is structurally
    impossible here. Already-held symbols are excluded — this list is only
    for fresh entries, not stocks already bought (that's the Portfolio page).
    """
    latest_signal = (
        select(Signal)
        .where(Signal.mode == get_broker().mode)
        .distinct(Signal.strategy_id, Signal.instrument_id)
        .order_by(Signal.strategy_id, Signal.instrument_id, Signal.generated_at.desc())
    ).subquery()
    LatestSignal = aliased(Signal, latest_signal)

    held_instrument_ids = select(Position.instrument_id).where(
        Position.mode == get_broker().mode, Position.status == PositionStatus.OPEN
    )

    stmt = (
        select(LatestSignal, Instrument.tradingsymbol, Instrument.name, Strategy.name)
        .join(Instrument, Instrument.id == LatestSignal.instrument_id)
        .join(Strategy, Strategy.id == LatestSignal.strategy_id)
        .where(
            LatestSignal.signal_type == "BUY",
            LatestSignal.instrument_id.not_in(held_instrument_ids),
        )
        .order_by(LatestSignal.confidence.desc().nullslast())
    )
    rows = db.execute(stmt).all()

    return [
        {
            "symbol": symbol,
            "name": name,
            "strategy_name": strategy_name,
            "price": sig.price,
            "confidence": sig.confidence,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "reason": sig.reason,
            "generated_at": sig.generated_at,
        }
        for sig, symbol, name, strategy_name in rows
    ]


@router.get("/track-record", response_model=list[dict])
def track_record(db: DbSession) -> list[dict]:
    """Every signal with a stop/target set, scored or still open — the
    honest ledger behind the Scan Results tab. Unlike /buy-list (a
    same-day shortlist), this returns full history: wins, losses, and
    expirations together, never filtered down to only the flattering ones.
    See docs/superpowers/specs/2026-09-12-signal-track-record-design.md.
    """
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol, Instrument.name, Strategy)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .where(Signal.stop_loss.isnot(None), Signal.take_profit.isnot(None))
        .order_by(Signal.generated_at.desc())
    ).all()

    out: list[dict] = []
    for sig, symbol, name, strategy in rows:
        trade_row = None
        if sig.was_executed:
            trade_row = db.execute(
                select(Trade).where(Trade.instrument_id == sig.instrument_id, Trade.entry_at >= sig.generated_at)
                .order_by(Trade.entry_at.asc())
                .limit(1)
            ).scalar_one_or_none()

        current_price = None
        latest_candle = db.execute(
            select(Candle.close)
            .where(Candle.instrument_id == sig.instrument_id, Candle.interval == "day")
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_candle is not None:
            current_price = float(latest_candle)

        age_days = (datetime.now(UTC) - sig.generated_at).days

        out.append({
            "signal_id": sig.id,
            "symbol": symbol,
            "name": name,
            "cap_tier": _cap_tier(strategy.params.get("model_name") if strategy.params else None),
            "strategy_name": strategy.name,
            "mode": sig.mode,
            "generated_at": sig.generated_at,
            "age_days": age_days,
            "price": sig.price,
            "stop_loss": sig.stop_loss,
            "take_profit": sig.take_profit,
            "current_price": current_price,
            "confidence": sig.confidence,
            "outcome": sig.outcome,
            "outcome_pct": sig.outcome_pct,
            "outcome_at": sig.outcome_at,
            "was_executed": sig.was_executed,
            "reason": sig.reason,
            "trade_net_pnl": trade_row.net_pnl if trade_row else None,
            "trade_return_pct": trade_row.return_pct if trade_row else None,
        })
    return out
