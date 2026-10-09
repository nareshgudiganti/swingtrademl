"""The TradeMind brain as a version-1 strategy (build book M18).

It does no thinking of its own: for each stock it reads what today's live
nightly brain run already decided and hands that to version 1 as a signal.
"brain" is a staged type (core/strategy_policy.py): the scan path always
treats it as advisory, so it records and scores its ideas and never places
an order. Orders happen only in services/brain_golive/approvals.py after the
owner's OK. Brain tables are read through the models only — this module never
imports the brain package (that package must stay free of execution, C10).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.strategies.base import BaseStrategy, SignalDecision, register_strategy

IST = ZoneInfo("Asia/Kolkata")
NO_RUN_TODAY = "No brain run today — the brain has not looked at the market yet today."
NOT_LOOKED_AT = "The brain did not look at this stock today."
NO_LEVELS = "The brain's idea has no stop or target, so it cannot be tracked."


def today_ist() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=IST)
    return start, start + timedelta(days=1)


def todays_run(db: Session, today: date, book: str) -> BrainRun | None:
    """The latest finished live nightly run made on `today` (IST) for `book`.
    Replays, why-runs, intraday runs and failed runs never count."""
    start, end = ist_day_bounds(today)
    return db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.book == book,
            BrainRun.as_of >= start,
            BrainRun.as_of < end,
        )
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def todays_decisions(db: Session, today: date, book: str) -> tuple[BrainRun | None, dict[str, BrainDecision]]:
    run = todays_run(db, today, book)
    if run is None:
        return None, {}
    by_symbol: dict[str, BrainDecision] = {}
    for d in db.execute(select(BrainDecision).where(BrainDecision.run_id == run.id)).scalars():
        current = by_symbol.get(d.symbol)
        if current is None or (d.kind == "idea" and current.kind != "idea"):
            by_symbol[d.symbol] = d
    return run, by_symbol


def effective_word(d: BrainDecision) -> str:
    """The owner's overrule (always more careful) wins over the brain's own word."""
    return d.overruled_word or d.word


def why(d: BrainDecision) -> str:
    if d.overruled_word:
        return f"You overruled the brain to {d.overruled_word}: {d.overrule_reason or 'no reason given'}"
    if d.reasons:
        return str(d.reasons[0])
    return d.evidence_text or f"The brain says {d.word}."


RISK_SAID_NO = "but the risk check said no"
# == services.execution.BLOCKED_BY_RISK_KEY (not imported: strategies must not
# depend on execution).
BLOCKED_BY_RISK_KEY = "blocked_by_risk_limit"


def blocked_by_risk(d: BrainDecision) -> bool:
    """A TRADE the brain itself lowered to WATCH only because the risk check
    (version 1's limits, via M07) said no — a good idea nothing could buy.
    Never true after an owner overrule: that is a judgement, not a limit."""
    return (
        d.kind == "idea"
        and d.overruled_word is None
        and d.word == "WATCH"
        and d.downgraded_from == "TRADE"
        and RISK_SAID_NO in (d.downgrade_reason or "")
    )


def to_signal(
    d: BrainDecision | None, run: BrainRun | None, price: float, *, practice: bool = False
) -> SignalDecision:
    if run is None:
        return SignalDecision(SignalType.HOLD, price, reason=NO_RUN_TODAY)
    if d is None:
        return SignalDecision(SignalType.HOLD, price, reason=NOT_LOOKED_AT, features={"brain_run_id": run.id})
    word = effective_word(d)
    features: dict[str, Any] = {
        "brain_run_id": run.id,
        "brain_decision_id": d.id,
        "brain_word": word,
        "brain_qty": d.qty,  # informational only: version 1's risk service sizes the order
        "brain_entry_low": d.entry_low,
        "brain_entry_high": d.entry_high,
    }
    if d.kind == "idea" and word == "TRADE":
        if d.stop is None or d.target is None:
            return SignalDecision(SignalType.HOLD, price, reason=NO_LEVELS, features=features)
        return SignalDecision(
            SignalType.BUY,
            price,
            d.confidence,
            why(d),
            stop_loss=float(d.stop),
            take_profit=float(d.target),
            horizon_days=int(d.horizon_days),
            features=features,
        )
    if practice and blocked_by_risk(d) and d.stop is not None and d.target is not None:
        # Practice evidence only: recorded as a BUY so it is scored to its
        # outcome like any idea, and tagged so it never counts as placeable
        # (services/brain_golive/compare.py). The brain strategy is advisory,
        # so nothing is bought; outside practice this branch never runs.
        return SignalDecision(
            SignalType.BUY,
            price,
            d.confidence,
            why(d),
            stop_loss=float(d.stop),
            take_profit=float(d.target),
            horizon_days=int(d.horizon_days),
            features={**features, BLOCKED_BY_RISK_KEY: "BRAIN_RISK_CHECK"},
        )
    # No confidence on a HOLD: the brain's number is not always a probability
    # (BrainDecision.score_source), and v1's decay alert must not read it as one.
    return SignalDecision(SignalType.HOLD, price, reason=why(d), features=features)


@register_strategy
class BrainStrategy(BaseStrategy):
    strategy_type: ClassVar[str] = "brain"
    display_name: ClassVar[str] = "TradeMind brain"
    description: ClassVar[str] = (
        "The TradeMind brain's ideas, recorded and scored next to version 1. "
        "It never buys on its own: the owner chooses the stage on the Brain page."
    )
    default_params: ClassVar[dict[str, Any]] = {}

    def __init__(self, config) -> None:
        super().__init__(config)
        self._loaded_for: date | None = None
        self._run: BrainRun | None = None
        self._decisions: dict[str, BrainDecision] = {}
        self._practice = False

    def min_bars_required(self) -> int:
        return 1  # it reads stored decisions; one bar gives today's price

    def evaluate(self, df: pd.DataFrame, instrument: Instrument, db: Session) -> SignalDecision | None:
        if df.empty:
            return None
        today = today_ist()
        if self._loaded_for != today:
            self._run, self._decisions = todays_decisions(db, today, self.config.mode)
            # Imported here: the stage service sits above strategies.
            from swing_trade_ml.services.brain_golive.stage import current_stage

            self._practice = current_stage(db) not in ("approval", "auto")
            self._loaded_for = today
        price = float(df["close"].iloc[-1])
        return to_signal(
            self._decisions.get(instrument.tradingsymbol), self._run, price, practice=self._practice
        )
