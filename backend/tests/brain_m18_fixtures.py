"""Shared rows for the M18 go-live tests. Nothing here can reach a broker:
`no_broker` makes any order attempt fail the test loudly."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2031, 1, 6)  # a Monday far from any real stored run


def at(day: date, hh: int = 15, mm: int = 55) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST).astimezone(UTC)


def instrument(db, symbol: str, token: int) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def candle(
    db, inst: Instrument, day: date, close: float, high: float | None = None, low: float | None = None
) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC),
            open=close,
            high=high if high is not None else close * 1.01,
            low=low if low is not None else close * 0.99,
            close=close,
            volume=100_000,
        )
    )
    db.flush()


def brain_strategy(db, name: str = "m18-brain", symbols: list[str] | None = None) -> Strategy:
    s = Strategy(
        name=name,
        strategy_type="brain",
        execution_mode="advisory",
        mode="paper",
        is_active=True,
        symbols=symbols or [],
        params={},
    )
    db.add(s)
    db.flush()
    return s


def v1_strategy(
    db, name: str = "m18-v1", strategy_type: str = "ml_swing", execution_mode: str = "auto"
) -> Strategy:
    s = Strategy(
        name=name,
        strategy_type=strategy_type,
        execution_mode=execution_mode,
        mode="paper",
        is_active=True,
        symbols=[],
        params={},
    )
    db.add(s)
    db.flush()
    return s


def run(
    db,
    run_id: str,
    day: date = DAY,
    *,
    kind: str = "nightly",
    live: bool = True,
    status: str = "done",
    book: str = "paper",
    hh: int = 15,
    mm: int = 50,
) -> BrainRun:
    r = BrainRun(
        id=run_id,
        kind=kind,
        as_of=at(day, hh, mm),
        book=book,
        live=live,
        started_at=at(day, hh, mm),
        status=status,
    )
    db.add(r)
    db.flush()
    return r


def decision(
    db,
    run_id: str,
    symbol: str,
    word: str = "TRADE",
    *,
    kind: str = "idea",
    stop: float | None = 96.0,
    target: float | None = 108.0,
    qty: int = 7,
    confidence: float | None = 0.62,
    reasons=("Strong trend with room to the target.",),
    overruled_word: str | None = None,
    overrule_reason: str | None = None,
) -> BrainDecision:
    d = BrainDecision(
        run_id=run_id,
        symbol=symbol,
        kind=kind,
        word=word,
        stop=stop,
        target=target,
        qty=qty,
        horizon_days=15,
        confidence=confidence,
        reasons=list(reasons),
        overruled_word=overruled_word,
        overrule_reason=overrule_reason,
    )
    db.add(d)
    db.flush()
    return d


def signal(
    db,
    strategy: Strategy,
    inst: Instrument,
    day: date = DAY,
    *,
    signal_type: str = SignalType.BUY,
    outcome: str | None = None,
    outcome_pct: float | None = None,
    advisory_only: bool = True,
    rejection_reason: str | None = None,
    hh: int = 15,
    mm: int = 55,
    price: float = 100.0,
) -> Signal:
    s = Signal(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        signal_type=signal_type,
        mode="paper",
        price=price,
        confidence=0.6,
        suggested_quantity=12,
        stop_loss=96.0,
        take_profit=108.0,
        horizon_days=15,
        reason="r",
        features={},
        advisory_only=advisory_only,
        rejection_reason=rejection_reason,
        outcome=outcome,
        outcome_pct=outcome_pct,
        generated_at=at(day, hh, mm),
    )
    db.add(s)
    db.flush()
    return s


def no_broker(monkeypatch) -> SimpleNamespace:
    """Any attempt to place an order through services.execution fails the test."""
    from swing_trade_ml.services import execution

    def boom(*args, **kwargs):
        raise AssertionError("a broker order was attempted")

    fake = SimpleNamespace(mode="paper", place_order=boom, get_ltp=lambda keys, db: {})
    monkeypatch.setattr(execution, "get_broker", lambda: fake)
    return fake
