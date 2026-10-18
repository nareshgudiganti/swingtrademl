"""Execution edge paths: exit claims, reconciliation guards, partial-close bookkeeping (qa8 floor).

Paper mode only. Live-style behaviour (an order the broker accepts but has not filled) is simulated with
fake brokers and Order rows; nothing reaches Zerodha. The Kite singleton's place_order is replaced with
a fake wherever a My Holdings order path is exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from swing_trade_ml.brokers.base import OrderResult
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core.enums import ExitReason, OrderStatus, SignalType
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy, Trade
from swing_trade_ml.services import deployable, execution
from swing_trade_ml.strategies.base import SignalDecision

_TOKEN = iter(range(860_000_000, 870_000_000))


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda msg, *a, **kw: sent.append(msg))
    monkeypatch.setattr(kite_broker, "_token_loaded", False)
    return sent


def _inst(db, symbol="QAEXEC", price=None):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    if price is not None:
        db.add(Quote(instrument_id=inst.id, last_price=price, ts=datetime.now(UTC)))
        db.flush()
    return inst


def _strat(db, name, **kw):
    s = Strategy(name=name, strategy_type=kw.pop("strategy_type", "ml_swing"), mode="paper", **kw)
    db.add(s)
    db.flush()
    return s


def _pos(db, strat, inst, qty=10, price=100.0, **kw):
    p = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode=kw.pop("mode", "paper"),
        status=kw.pop("status", "OPEN"),
        quantity=qty,
        entry_price=price,
        entry_at=kw.pop("entry_at", datetime.now(UTC)),
        current_price=price,
        total_charges=kw.pop("total_charges", 10.0),
        **kw,
    )
    db.add(p)
    db.flush()
    return p


def _order(db, inst, side="SELL", **kw):
    o = Order(
        instrument_id=inst.id,
        mode="paper",
        transaction_type=side,
        order_type="MARKET",
        product="CNC",
        quantity=kw.pop("quantity", 10),
        status=kw.pop("status", "PENDING"),
        placed_at=datetime.now(UTC),
        **kw,
    )
    db.add(o)
    db.flush()
    return o


# ------------------------------------------------------- opening positions --


def test_adding_to_a_position_averages_price_and_fills_a_missing_stop(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_add")
    pos = _pos(db_session, strat, inst, qty=10, price=100.0, stop_loss=None, take_profit=None)
    out = execution._finalize_open_position(
        db_session,
        strat,
        inst,
        "paper",
        10,
        110.0,
        5.0,
        1.0,
        96.0,
        120.0,
        datetime.now(UTC),
    )
    assert out.id == pos.id and out.quantity == 20
    assert out.entry_price == pytest.approx(105.0)
    assert out.stop_loss == 96.0 and out.initial_stop_loss == 96.0 and out.take_profit == 120.0
    assert out.total_charges == pytest.approx(16.0)


def test_add_never_loosens_an_existing_stop(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_add_keep")
    _pos(db_session, strat, inst, stop_loss=98.0, take_profit=110.0)
    out = execution._finalize_open_position(
        db_session,
        strat,
        inst,
        "paper",
        5,
        100.0,
        0.0,
        0.0,
        80.0,
        200.0,
        datetime.now(UTC),
    )
    assert out.stop_loss == 98.0 and out.take_profit == 110.0


def test_manual_open_with_signal_marks_it_executed(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_manual_open")
    sig = Signal(
        strategy_id=strat.id,
        instrument_id=inst.id,
        signal_type="BUY",
        mode="paper",
        price=100.0,
        confidence=0.7,
        generated_at=datetime.now(UTC),
    )
    db_session.add(sig)
    db_session.flush()
    pos = execution.manual_open_position(db_session, strat, inst, 5, 100.0, 96.0, 108.0, signal=sig)
    assert sig.was_executed is True and pos.entry_confidence == 0.7


# -------------------------------------------------------- closing positions --


def test_close_refuses_zero_shares_and_missing_instrument(db_session, monkeypatch):
    inst, strat = _inst(db_session, price=100.0), _strat(db_session, "qa8_close_guard")
    pos = _pos(db_session, strat, inst)
    with pytest.raises(ValueError):
        execution.close_position(db_session, pos, 100.0, ExitReason.MANUAL, quantity=0)
    real_get = db_session.get
    monkeypatch.setattr(
        db_session,
        "get",
        lambda model, ident, **kw: None if model is Instrument else real_get(model, ident, **kw),
    )
    assert execution.close_position(db_session, pos, 100.0, ExitReason.MANUAL) is None
    with pytest.raises(ValueError):
        execution.manual_close_position(db_session, pos, 100.0)
    with pytest.raises(ValueError):
        execution.place_real_holding_sell(db_session, pos, 1)


def test_partial_then_full_close_reports_the_whole_position(db_session):
    inst, strat = _inst(db_session, price=110.0), _strat(db_session, "qa8_partial_full")
    pos = _pos(db_session, strat, inst, qty=10, price=100.0, initial_quantity=10, total_charges=10.0)
    half = execution.close_position(db_session, pos, 110.0, ExitReason.SCALE_OUT, note="half", quantity=5)
    assert half.quantity == 5 and pos.status == "OPEN" and pos.quantity == 5
    assert pos.stop_loss == pytest.approx(pos.entry_price)  # the rest can no longer become a loss
    assert pos.notes == "half"
    rest = execution.manual_close_position(db_session, pos, 112.0)
    assert pos.status == "CLOSED" and pos.quantity == 10
    assert pos.realized_pnl == pytest.approx(half.net_pnl + rest.net_pnl)
    trades = db_session.execute(select(Trade).where(Trade.position_id == pos.id)).scalars().all()
    assert pos.total_charges == pytest.approx(sum(t.charges for t in trades))


def test_partial_close_freezes_size_of_old_rows_and_rejects_bad_quantities(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_partial_old")
    pos = _pos(db_session, strat, inst, qty=10, initial_quantity=None, stop_loss=None)
    for bad in (0, 10, 11):
        with pytest.raises(ValueError):
            execution._finalize_partial_close(
                db_session, pos, inst, bad, 105.0, 0.0, 0.0, ExitReason.SCALE_OUT, datetime.now(UTC)
            )
    trade = execution._finalize_partial_close(
        db_session, pos, inst, 4, 105.0, 1.0, 1.0, ExitReason.SCALE_OUT, datetime.now(UTC), note="n"
    )
    assert pos.initial_quantity == 10 and pos.quantity == 6
    assert trade.charges == pytest.approx(10.0 * 4 / 10 + 2.0)
    assert pos.total_charges == pytest.approx(6.0)
    assert pos.stop_loss == pytest.approx(100.0) and pos.notes == "n"


# -------------------------------------------------------------- exit claims --


def test_claim_exit_refuses_a_fresh_naive_claim_and_a_resting_sell(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_claim")
    pos = _pos(db_session, strat, inst, exit_in_progress_at=datetime.now(UTC).replace(tzinfo=None))
    assert execution._claim_exit(db_session, pos) is False

    pos.exit_in_progress_at = datetime.now(UTC) - timedelta(minutes=10)  # stale claim
    _order(db_session, inst, position_id=pos.id, status="PENDING")
    assert execution._claim_exit(db_session, pos) is False  # a sell is already resting

    pos.exit_in_progress_at = datetime.now(UTC)
    execution._release_exit(db_session, pos)
    assert pos.exit_in_progress_at is not None  # kept while that sell is still at the broker


def test_claim_exit_refuses_a_closed_position(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_claim_closed")
    pos = _pos(db_session, strat, inst, status="CLOSED")
    assert execution._claim_exit(db_session, pos) is False


def test_check_exits_skips_positions_without_a_price(db_session, monkeypatch):
    inst, strat = _inst(db_session, "QAEXNOPRICE"), _strat(db_session, "qa8_noprice")
    pos = _pos(db_session, strat, inst, stop_loss=150.0)  # would be a stop-loss if priced
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: {})
    assert execution.check_exits(db_session) == []
    assert pos.status == "OPEN"


def test_check_exits_time_stop_closes_regardless_of_pnl(db_session, monkeypatch):
    inst, strat = _inst(db_session, "QAEXTIME", price=100.5), _strat(db_session, "qa8_timestop")
    pos = _pos(
        db_session,
        strat,
        inst,
        stop_loss=90.0,
        take_profit=120.0,
        entry_at=datetime.now(UTC) - timedelta(days=31),
    )
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, 100.5))
    closed = execution.check_exits(db_session)
    mine = [t for t in closed if t.position_id == pos.id]
    assert mine and mine[0].exit_reason == ExitReason.TIME_STOP
    assert pos.status == "CLOSED"


# ----------------------------------------------------------- process_decision --


@pytest.fixture
def calm(monkeypatch):
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )


def _decision(signal, price=100.0, confidence=0.7):
    return SignalDecision(
        signal=signal, price=price, confidence=confidence, stop_loss=96.0, take_profit=108.0, reason="qa8"
    )


def test_exit_signal_without_a_position_is_recorded_as_rejected(db_session):
    inst, strat = _inst(db_session), _strat(db_session, "qa8_exit_none")
    sig = execution.process_decision(db_session, strat, inst, _decision(SignalType.EXIT))
    assert sig.rejection_reason == "No open position to exit"


def test_pyramiding_only_into_a_winning_position(db_session, calm):
    inst = _inst(db_session, "QAEXPYR", price=100.0)
    strat = _strat(db_session, "qa8_pyramid", allow_pyramiding=True)
    pos = _pos(db_session, strat, inst, qty=10, price=90.0, unrealized_pnl=-5.0)
    sig = execution.process_decision(db_session, strat, inst, _decision(SignalType.BUY))
    assert sig.rejection_reason == "Position already open"  # averaging down refused
    pos.unrealized_pnl = 100.0
    db_session.flush()
    sig = execution.process_decision(db_session, strat, inst, _decision(SignalType.BUY))
    assert sig.rejection_reason != "Position already open"


# ------------------------------------------------------- confidence decay --


def test_confidence_decay_alerts_once(db_session, _quiet):
    inst, strat = _inst(db_session, "QAEXDECAY"), _strat(db_session, "qa8_decay")
    pos = _pos(db_session, strat, inst, entry_confidence=0.8)
    execution._check_confidence_decay(db_session, pos, strat, inst, None, "paper")
    assert pos.confidence_alert_sent_at is None and not _quiet
    execution._check_confidence_decay(db_session, pos, strat, inst, 0.10, "paper")
    assert pos.confidence_alert_sent_at is not None
    assert any("CONFIDENCE FALLING" in m for m in _quiet)


# ------------------------------------------------------- My Holdings order --


def test_real_holding_order_refused_by_zerodha_is_recorded_and_alerted(db_session, monkeypatch, _quiet):
    inst, strat = _inst(db_session, "QAEXREAL"), _strat(db_session, "qa8_real_refused")
    monkeypatch.setattr(
        kite_broker,
        "place_order",
        lambda req, db: OrderResult(broker_order_id="", status=OrderStatus.REJECTED, message="RMS block"),
    )
    order = execution.place_real_holding_buy(db_session, strat, inst, 2, 100.0)
    assert order.status == OrderStatus.REJECTED and order.mode == "live"
    assert any("refused by Zerodha" in m for m in _quiet)


# ----------------------------------------------------------- reconciliation --


class _StatusBroker:
    def __init__(self, result):
        self.result = result

    def get_order_status(self, broker_order_id, db):
        return self.result


def test_reconcile_counts_unchanged_orders(db_session):
    inst = _inst(db_session)
    order = _order(db_session, inst, broker_order_id="X1")
    counts = {"checked": 0, "filled": 0, "failed": 0, "unchanged": 0}
    execution._reconcile_orders(db_session, _StatusBroker(None), [order], counts)
    execution._reconcile_orders(
        db_session,
        _StatusBroker(OrderResult(broker_order_id="X1", status=OrderStatus.PENDING)),
        [order],
        counts,
    )
    assert counts == {"checked": 2, "filled": 0, "failed": 0, "unchanged": 2}


def test_finish_reconciled_guards_return_without_writing(db_session, monkeypatch):
    done = OrderResult(
        broker_order_id="X", status=OrderStatus.COMPLETE, filled_quantity=1, average_price=None
    )
    # No instrument.
    execution._finish_reconciled_order(db_session, SimpleNamespace(id=1, instrument_id=-1), done)
    inst = _inst(db_session)
    # No fill price anywhere.
    execution._finish_reconciled_order(
        db_session, SimpleNamespace(id=2, instrument_id=inst.id, price=None), done
    )
    priced = OrderResult(
        broker_order_id="X", status=OrderStatus.COMPLETE, filled_quantity=1, average_price=10.0
    )
    # A buy already finished, and a buy whose strategy is gone.
    buy_done = _order(db_session, inst, side="BUY", status="COMPLETE")
    buy_done.position_id = _pos(db_session, _strat(db_session, "qa8_rec_done"), inst).id
    execution._finish_reconciled_order(db_session, buy_done, priced)
    orphan = _order(db_session, inst, side="BUY", status="COMPLETE")
    execution._finish_reconciled_order(db_session, orphan, priced)
    assert orphan.position_id is None
    # A sell with no position, and a sell for a position already closed.
    sell_orphan = _order(db_session, inst, status="COMPLETE")
    execution._finish_reconciled_order(db_session, sell_orphan, priced)
    closed = _pos(db_session, _strat(db_session, "qa8_rec_closed"), inst, status="CLOSED")
    sell_closed = _order(db_session, inst, status="COMPLETE", position_id=closed.id)
    execution._finish_reconciled_order(db_session, sell_closed, priced)
    assert db_session.execute(select(Trade).where(Trade.position_id == closed.id)).first() is None


def test_reconciled_buy_marks_its_signal_executed(db_session):
    inst, strat = _inst(db_session, "QAEXRECBUY"), _strat(db_session, "qa8_rec_buy")
    sig = Signal(
        strategy_id=strat.id,
        instrument_id=inst.id,
        signal_type="BUY",
        mode="paper",
        price=100.0,
        confidence=0.7,
        stop_loss=96.0,
        take_profit=108.0,
        generated_at=datetime.now(UTC),
    )
    db_session.add(sig)
    db_session.flush()
    order = _order(
        db_session, inst, side="BUY", status="COMPLETE", signal_id=sig.id, strategy_id=strat.id, quantity=3
    )
    execution._finish_reconciled_order(
        db_session,
        order,
        OrderResult(broker_order_id="B", status=OrderStatus.COMPLETE, filled_quantity=3, average_price=100.0),
    )
    pos = db_session.get(Position, order.position_id)
    assert sig.was_executed is True and pos.stop_loss == 96.0 and pos.quantity == 3


def test_failed_sell_releases_the_exit_claim_and_alerts(db_session, _quiet):
    inst, strat = _inst(db_session, "QAEXFAIL"), _strat(db_session, "qa8_fail_sell")
    pos = _pos(db_session, strat, inst, exit_in_progress_at=datetime.now(UTC))
    sig = Signal(
        strategy_id=strat.id,
        instrument_id=inst.id,
        signal_type="EXIT",
        mode="paper",
        price=100.0,
        generated_at=datetime.now(UTC),
    )
    db_session.add(sig)
    db_session.flush()
    order = _order(db_session, inst, position_id=pos.id, signal_id=sig.id)
    execution._fail_reconciled_order(
        db_session, order, OrderResult(broker_order_id="S", status=OrderStatus.REJECTED, message=None)
    )
    assert pos.exit_in_progress_at is None
    assert sig.rejection_reason == "Order REJECTED"
    assert any("Order REJECTED" in m for m in _quiet)
