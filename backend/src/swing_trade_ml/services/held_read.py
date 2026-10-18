"""The daily read on a stock you already hold, for the Testing and My Holdings tabs.

Three things per open position, all display only:
  * which day of the trade it is ("Day 4 of 15"), counted in trading days;
  * one suggestion word: SELL, SELL_PARTIALLY, WATCH or HOLD;
  * a daily model score for Testing positions, which no scan covered before
    (the tester book's strategy is never active, so engine.run_all_active
    skipped it and a stock bought there only had a score if it happened to be
    on the watchlist).

Nothing here places, changes or cancels an order, a stop or a size. The
suggestion is built from the verdict position_action() already gives, plus the
settled half-out-at-first-target rule, so it can only say what the app already
says in other words. There is no "add more": advice on a held stock only ever
moves toward caution.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import IST, is_trading_day, trading_days_between
from swing_trade_ml.core.strategy_policy import is_staged
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy

log = get_logger(__name__)

#: The settled trading rule: every trade is done within 15 trading days.
#: (v1's own time stop is 30 calendar days, which agrees; this is only the label.)
TRADE_LIMIT_TRADING_DAYS = 15

SELL = "SELL"
SELL_PARTIALLY = "SELL_PARTIALLY"
WATCH = "WATCH"
HOLD = "HOLD"


def day_number(entry_at: datetime, today: date | None = None) -> int:
    """Pure: which trading day of the trade today is. Bought Monday, today Thursday -> 4.

    A stock imported on a weekend or holiday starts at Day 1 on the next
    trading day rather than counting the day it was not traded.
    """
    today = today or datetime.now(IST).date()
    entry_day = entry_at.astimezone(IST).date()
    if today < entry_day:
        return 1
    days = trading_days_between(entry_day, today) + (1 if is_trading_day(entry_day) else 0)
    return max(days, 1)


def suggestion(
    action_code: str,
    action_label: str,
    pnl_pct: float,
    scaled_out: bool,
    day: int,
    first_target: float | None = None,
    limit_days: int = TRADE_LIMIT_TRADING_DAYS,
) -> tuple[str, str]:
    """Pure: one word for what to do with a held stock, plus a plain reason.

    Strongest first: the bot's own sell verdict, then the half-out rule at the
    first target, then any weakening (or running past the trade's day limit),
    then hold.
    """
    first_target = settings.ML_FIRST_TARGET_PCT if first_target is None else first_target

    if action_code == "exit":
        return SELL, action_label
    if not scaled_out and pnl_pct >= first_target:
        return (
            SELL_PARTIALLY,
            f"Up {pnl_pct:.1%} — the plan is to sell half at +{first_target:.0%} and let the rest run",
        )
    if action_code in ("alert", "weak", "dip"):
        return WATCH, action_label
    if day > limit_days:
        return WATCH, f"Day {day} — past the usual {limit_days}-trading-day plan for a trade"
    return HOLD, action_label


# --------------------------------------------------------------------------
# Daily score for Testing positions.
# --------------------------------------------------------------------------


def _reference_strategies(db: Session) -> dict[str, Strategy]:
    """cap tier -> an active ml_swing strategy whose model scores that tier.

    The bot's own strategies are preferred over advisory ones (My Holdings)
    so a Testing stock is read by the same model the bot would use.
    """
    from swing_trade_ml.strategies.tier import cap_tier

    rows = db.execute(
        select(Strategy)
        .where(Strategy.is_active.is_(True), Strategy.strategy_type == "ml_swing")
        .order_by(Strategy.id)
    ).scalars()
    by_tier: dict[str, Strategy] = {}
    for strategy in rows:
        if is_staged(strategy):
            continue
        tier = cap_tier((strategy.params or {}).get("model_name"))
        current = by_tier.get(tier)
        if current is None or (
            current.execution_mode == "advisory" and strategy.execution_mode != "advisory"
        ):
            by_tier[tier] = strategy
    return by_tier


def score_tester_positions(db: Session, today: date | None = None) -> int:
    """Store today's model score for every open Testing position. Returns rows written.

    Never raises: a display feature must not be able to break the scan. Each
    position is isolated in a savepoint, and a stock the model cannot read
    today (too little history, missing data) is a gap, never a made-up number.
    No Telegram message is sent: Testing is a practice book.
    """
    from swing_trade_ml.ml.dataset import load_candles
    from swing_trade_ml.services import score_history
    from swing_trade_ml.services.exit_policy import exit_confidence_for
    from swing_trade_ml.services.tester_paper import entry_signal_cap_tier, strategy_id_subquery
    from swing_trade_ml.strategies import get_strategy

    try:
        rows = db.execute(
            select(Position, Instrument)
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(
                Position.status == PositionStatus.OPEN,
                Position.strategy_id.in_(strategy_id_subquery()),
            )
        ).all()
        if not rows:
            return 0
        by_tier = _reference_strategies(db)
        if not by_tier:
            log.info("held_read.tester_scores.no_model_strategy")
            return 0
    except Exception as exc:  # noqa: BLE001
        log.warning("held_read.tester_scores.failed", error=str(exc))
        db.rollback()
        return 0

    fallback = by_tier.get("large") or next(iter(by_tier.values()))
    written = 0
    for position, instrument in rows:
        try:
            with db.begin_nested():
                tier = entry_signal_cap_tier(db, position.id) or "large"
                strategy = by_tier.get(tier, fallback)
                impl = get_strategy(strategy)
                df = load_candles(db, instrument.id, "day", limit=impl.min_bars_required() + 50)
                if df.empty:
                    continue
                decision = impl.evaluate(df, instrument, db)
                raw = (decision.features or {}).get("probability") if decision else None
                if not isinstance(raw, (int, float)):
                    continue
                score = float(raw)
                model = (decision.features or {}).get("model")
                position.last_confidence = score
                # Testing buys carry no model score; the first daily read stands in
                # as "where it started" so the trail can say up or down since then.
                if position.entry_confidence is None:
                    position.entry_confidence = score
                score_history.record_score(
                    db,
                    position.id,
                    score,
                    exit_confidence_for(strategy),
                    model_version=model[:64] if isinstance(model, str) else None,
                    today=today,
                )
            written += 1
        except Exception as exc:  # noqa: BLE001 - one stock must not stop the rest
            log.warning(
                "held_read.tester_score.failed",
                position_id=position.id,
                symbol=instrument.tradingsymbol,
                error=str(exc),
            )
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("held_read.tester_scores.commit_failed", error=str(exc))
        db.rollback()
        return 0
    log.info("held_read.tester_scores", written=written, open=len(rows))
    return written


def describe(
    position: Position, action_code: str, action_label: str, pnl_pct: float, today: date | None = None
) -> dict[str, Any]:
    """The extra fields one detailed-position row carries for the two tabs."""
    day = day_number(position.entry_at, today)
    code, reason = suggestion(
        action_code, action_label, pnl_pct, scaled_out=position.scaled_out_at is not None, day=day
    )
    return {
        "day_number": day,
        "trade_limit_days": TRADE_LIMIT_TRADING_DAYS,
        "suggestion": code,
        "suggestion_reason": reason,
    }
