"""A buy that a risk limit refuses leaves nothing behind (#244).

Every other test of the entry gate checks the verdict (`risk.check_entry` says no, with a rule).
None proved what the refusal does NOT do once it goes through the real buy path. This file does,
for the block reasons listed in CASES (halt, position limit, drawdown, sector cap, deployable
capital, cash reserve, stop-loss cooldown, liquidity, exchange avoid list, share price, cap tier),
through `execution.process_decision` with the paper broker:

- the broker is never asked to place an order;
- no Order, Trade or Position row is written;
- the paper account's cash is exactly what it was;
- the refusal is recorded: one Signal carrying the rejection reason, and one RiskEvent for the rule;
- and that record is COMMITTED: at the last real commit the Signal, its stored rejection reason and the
  RiskEvent all exist, so it survives the request. A reason assigned after the last commit fails this.

Refusals NOT covered here: an instrument already held (ALREADY_OPEN), and the small-company budget and
market-condition ceilings beyond DEPLOYABLE.

Tests only: no source, frozen file or limit changes. A failing case here is a finding to report, not
something to patch in this file.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, func, select

from swing_trade_ml.brokers.paper import paper_broker
from swing_trade_ml.core.enums import ExitReason, SignalType
from swing_trade_ml.db.models.feeds import TradingRestriction
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.db.models.trading import (
    Order,
    PortfolioSnapshot,
    Position,
    Signal,
    Strategy,
    Trade,
)
from swing_trade_ml.services import deployable, execution, system_state
from swing_trade_ml.strategies.base import SignalDecision

ACCOUNT = 1_000_000.0  # the test paper account (the 10 lakh rung of the limits ladder)


def _instrument(db, symbol: str, price: float = 100.0) -> Instrument:
    inst = Instrument(
        instrument_token=hash(symbol) % 1_000_000, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True
    )
    db.add(inst)
    db.flush()
    db.add(Quote(instrument_id=inst.id, last_price=price, ts=datetime.now(UTC)))
    db.flush()
    return inst


def _strategy(db, **kwargs) -> Strategy:
    strategy = Strategy(name=kwargs.pop("name", "rb244"), strategy_type="ml_swing", mode="paper", **kwargs)
    db.add(strategy)
    db.flush()
    return strategy


def _hold(db, strategy: Strategy, inst: Instrument, quantity: int, price: float) -> Position:
    position = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode="paper",
        status="OPEN",
        quantity=quantity,
        entry_price=price,
        entry_at=datetime.now(UTC),
        current_price=price,
    )
    db.add(position)
    db.flush()
    return position


def _snapshot(db, *, total: float, peak: float) -> None:
    db.add(
        PortfolioSnapshot(
            mode="paper",
            ts=datetime.now(UTC) - timedelta(days=1),
            cash=total,
            holdings_value=0.0,
            total_value=total,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            day_pnl=0.0,
            open_positions=0,
            peak_value=peak,
            drawdown_pct=max(0.0, (peak - total) / peak),
        )
    )
    db.flush()


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def _reasons(db) -> int:
    """How many Signal rows carry a non-empty rejection reason right now."""
    stored = Signal.rejection_reason.isnot(None) & (Signal.rejection_reason != "")
    return db.execute(select(func.count()).select_from(Signal).where(stored)).scalar_one()


def _state(db) -> tuple[int, int, int]:
    """(Signal rows, RiskEvent rows, Signal rows with a stored rejection reason)."""
    return _count(db, Signal), _count(db, RiskEvent), _reasons(db)


class _SpyBroker:
    """The paper broker's identity, with `place_order` recording any call. A refused buy never reaches it."""

    mode = "paper"

    def __init__(self) -> None:
        self.placed: list[object] = []

    def place_order(self, request, db):
        self.placed.append(request)
        raise AssertionError("a refused buy asked the broker to place an order")


@pytest.fixture()
def book(db_session, monkeypatch):
    """The buy path with the money inputs pinned: `cash` is what the entry gate sees as spendable.

    The test session shares one outer transaction, so a row read back in it looks saved even if the code
    never committed it. `book.commits` therefore records, at every real `commit()`, how many Signal rows,
    RiskEvent rows and Signal rows with a stored rejection reason existed at that moment: the proof that
    the refusal record, reason included, was committed. `book.price` is the buy price the case uses.
    """
    spy = _SpyBroker()
    commits: list[tuple[int, int, int]] = []

    def _on_commit(session) -> None:
        session.flush()
        commits.append(_state(session))

    event.listen(db_session, "before_commit", _on_commit)
    monkeypatch.setattr(execution, "get_broker", lambda: spy)
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)
    state = SimpleNamespace(total=ACCOUNT, cash=ACCOUNT)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (state.total, state.cash))
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    yield SimpleNamespace(
        db=db_session, spy=spy, money=state, monkeypatch=monkeypatch, commits=commits, price=1600.0
    )
    event.remove(db_session, "before_commit", _on_commit)


# Each case builds the situation, then names the rule the entry gate must refuse with.


def _halt(book, strategy, inst):
    system_state.halt(book.db, reason="drill for #244", by="test-suite")


def _position_limit(book, strategy, inst):
    strategy.max_positions = 1
    other = _instrument(book.db, "RB244HELD")
    _hold(book.db, strategy, other, quantity=10, price=100.0)


def _drawdown(book, strategy, inst):
    _snapshot(book.db, total=ACCOUNT, peak=ACCOUNT)
    book.money.total = 800_000.0  # 20% below its peak, past the 15% brake
    book.money.cash = 800_000.0


def _sector_cap(book, strategy, inst):
    # ICICIBANK and HDFCBANK share a sector bucket; 24% of the account is already in banking.
    held = _instrument(book.db, "ICICIBANK", price=1000.0)
    _hold(book.db, strategy, held, quantity=240, price=1000.0)


def _deployable(book, strategy, inst):
    book.monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="weak", fraction=0.01, context_available=True),
    )


def _cash(book, strategy, inst):
    book.money.cash = 105_000.0  # inside the reserve kept aside at this account size


def _cooldown(book, strategy, inst):
    # This strategy was stopped out of this stock yesterday; the default cooldown is several days.
    book.db.add(
        Position(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            mode="paper",
            status="CLOSED",
            quantity=10,
            entry_price=1700.0,
            entry_at=datetime.now(UTC) - timedelta(days=3),
            current_price=1600.0,
            exit_price=1600.0,
            exit_at=datetime.now(UTC) - timedelta(days=1),
            exit_reason=ExitReason.STOP_LOSS_HIT,
        )
    )
    book.db.flush()


def _liquidity(book, strategy, inst):
    # Twenty days of thin trading: about 1.6 lakh a day, so 2% of it is far below the minimum position.
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    book.db.add_all(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=today - timedelta(days=n),
            open=1600.0,
            high=1610.0,
            low=1590.0,
            close=1600.0,
            volume=100,
        )
        for n in range(1, 21)
    )
    book.db.flush()


def _avoid(book, strategy, inst):
    # The exchange put this stock on its extra-watch list today (services/avoid.py). The gate reads that
    # table by symbol and IST date, before any limit, so no account figure needs changing.
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    book.db.add(TradingRestriction(symbol=inst.tradingsymbol, kind="ASM", stage="Stage I", as_of=today))
    book.db.flush()


def _share_price(book, strategy, inst):
    # The smallest rung of the limits ladder (10,000) skips shares above 2,500 (limits.max_share_price_inr).
    book.money.total = 10_000.0
    book.money.cash = 10_000.0
    book.price = 3_000.0


def _cap_tier(book, strategy, inst):
    # The smallest rung allows large companies only; this strategy buys with a small-company model. The share
    # price stays under that rung's 2,500 ceiling, so the tier check, not the price check, is what refuses.
    book.money.total = 10_000.0
    book.money.cash = 10_000.0
    strategy.params = {"model_name": "swing_classifier_smallcap"}


CASES = [
    pytest.param(_halt, ("HALTED",), "HDFCBANK", id="halt"),
    pytest.param(_position_limit, ("POSITION_LIMIT",), "HDFCBANK", id="position-limit"),
    pytest.param(_drawdown, ("DRAWDOWN",), "HDFCBANK", id="drawdown"),
    pytest.param(_sector_cap, ("SECTOR_CAP",), "HDFCBANK", id="sector-cap"),
    pytest.param(_deployable, ("DEPLOYABLE",), "HDFCBANK", id="deployable"),
    pytest.param(_cash, ("CASH_FLOOR", "MIN_POSITION", "CASH"), "HDFCBANK", id="cash"),
    pytest.param(_cooldown, ("COOLDOWN",), "HDFCBANK", id="stop-loss-cooldown"),
    pytest.param(_liquidity, ("LIQUIDITY",), "HDFCBANK", id="liquidity"),
    pytest.param(_avoid, ("AVOID",), "HDFCBANK", id="exchange-avoid-list"),
    pytest.param(_share_price, ("SHARE_PRICE",), "HDFCBANK", id="share-price"),
    pytest.param(_cap_tier, ("CAP_TIER",), "HDFCBANK", id="cap-tier"),
]


def test_control_an_unblocked_buy_does_reach_the_broker(book):
    """The harness can see a real buy: with nothing blocking, the same call asks the broker to place an
    order. Without this, the 'never asked' assertions below could pass for the wrong reason."""
    db = book.db
    strategy = _strategy(db)
    inst = _instrument(db, "HDFCBANK", price=1600.0)
    db.commit()
    decision = SignalDecision(
        signal=SignalType.BUY,
        price=1600.0,
        confidence=0.7,
        stop_loss=1550.0,
        take_profit=1700.0,
        reason="244",
    )

    with pytest.raises(AssertionError, match="asked the broker to place an order"):
        execution.process_decision(db, strategy, inst, decision)

    assert len(book.spy.placed) == 1


def _attempt_buy(book, arrange, symbol):
    """Arrange one refusal, snapshot the books, send one BUY through the real buy path.

    Returns (signal, before) where `before` holds the counts and cash taken just before the call."""
    db = book.db
    strategy = _strategy(db)
    inst = _instrument(db, symbol, price=1600.0)
    arrange(book, strategy, inst)
    db.commit()

    before = SimpleNamespace(
        cash=paper_broker.get_available_cash(db),
        orders=_count(db, Order),
        trades=_count(db, Trade),
        positions=_count(db, Position),
        state=_state(db),
    )
    decision = SignalDecision(
        signal=SignalType.BUY,
        price=book.price,
        confidence=0.7,
        stop_loss=book.price - 50.0,
        take_profit=book.price + 100.0,
        reason="244",
    )
    return execution.process_decision(db, strategy, inst, decision), before


def _assert_refusal_committed(book, before) -> None:
    """At the last real commit the Signal, its stored rejection reason and the RiskEvent all existed."""
    signals, events, reasons = before.state
    assert book.commits, "the refusal path never committed, so its record would be lost with the request"
    assert book.commits[-1] == (signals + 1, events + 1, reasons + 1), (
        "the last commit missed part of the refusal record (signal, rejection reason or risk event)"
    )


@pytest.mark.parametrize(("arrange", "rules", "symbol"), CASES)
def test_a_buy_the_risk_gate_refuses_leaves_nothing_behind(book, arrange, rules, symbol):
    db = book.db
    signal, before = _attempt_buy(book, arrange, symbol)
    cash_before, (orders, trades, positions) = before.cash, (before.orders, before.trades, before.positions)
    signals, events, _ = before.state

    # Nothing was bought.
    assert book.spy.placed == [], "the broker was never asked to place an order"
    assert (_count(db, Order), _count(db, Trade), _count(db, Position)) == (orders, trades, positions)
    assert paper_broker.get_available_cash(db) == cash_before, "the paper account's cash did not move"
    assert signal is not None and signal.was_executed is False

    # The refusal is on record, with the reason.
    assert _count(db, Signal) == signals + 1
    stored = db.get(Signal, signal.id)
    assert stored.rejection_reason, "the signal says why it was refused"
    assert stored.signal_type == SignalType.BUY
    new_events = db.execute(select(RiskEvent).order_by(RiskEvent.id.desc())).scalars().all()
    assert _count(db, RiskEvent) == events + 1
    assert new_events[0].rule in rules
    assert new_events[0].reason == stored.rejection_reason, "signal and risk event give the same reason"

    # ... and it was committed, not just flushed: at the last real commit all of it already existed.
    _assert_refusal_committed(book, before)


class _ReasonAfterTheLastCommit:
    """Stands in for the Signal the buy path holds, but keeps a rejection reason aside until `release()`:
    the shape of a defect where the reason is assigned after the last commit."""

    def __init__(self, signal) -> None:
        object.__setattr__(self, "_signal", signal)
        object.__setattr__(self, "_held", None)

    def __getattr__(self, name):
        return getattr(self._signal, name)

    def __setattr__(self, name, value) -> None:
        if name == "rejection_reason":
            object.__setattr__(self, "_held", value)
        else:
            setattr(self._signal, name, value)

    def release(self) -> None:
        self._signal.rejection_reason = self._held


def test_the_commit_check_fails_when_the_reason_is_stored_after_the_last_commit(book, monkeypatch):
    """Proof that the commit-time check can fail. A temporary patch of `execution.record_signal` hands the buy
    path a Signal whose rejection reason lands only after every commit. Everything is still true once the call
    returns (the row, the reason, the risk event), so only the commit-time check can see it."""
    real = execution.record_signal
    wrapped: list[_ReasonAfterTheLastCommit] = []

    def late_reason(*args, **kwargs):
        proxy = _ReasonAfterTheLastCommit(real(*args, **kwargs))
        wrapped.append(proxy)
        return proxy

    monkeypatch.setattr(execution, "record_signal", late_reason)

    signal, before = _attempt_buy(book, _halt, "HDFCBANK")
    wrapped[0].release()
    book.db.flush()

    assert book.db.get(Signal, signal.id).rejection_reason, "after the call the reason is on the row"
    assert _state(book.db)[:2] == (before.state[0] + 1, before.state[1] + 1), "the rows exist after the call"
    with pytest.raises(AssertionError, match="missed part of the refusal record"):
        _assert_refusal_committed(book, before)
