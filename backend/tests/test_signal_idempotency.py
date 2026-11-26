"""#360: a retried scan records ONE v1 signal per signal_key and places ONE order.

signal_key = strategy, stock, mode, type, horizon, session (the last closed trading day of the scan time).
Settled signals are returned unchanged on a retry; an unsettled one (written, no order yet) is reused so the
retry completes the buy exactly once; rows without a key are never touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy
from swing_trade_ml.services import deployable, execution
from swing_trade_ml.strategies.base import SignalDecision

FRI_EVENING = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)  # 17:30 IST, after the close
MON_EVENING = FRI_EVENING + timedelta(days=3)


@pytest.fixture
def world(db_session, monkeypatch):
    from swing_trade_ml.brokers.paper import PaperBroker

    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, 1000.0))
    clock = {"now": FRI_EVENING}
    monkeypatch.setattr(execution, "_now", lambda: clock["now"])
    inst = Instrument(instrument_token=738599, tradingsymbol="IDEM360", exchange="NSE", is_watchlisted=True)
    strat = Strategy(name="idem360", strategy_type="ml_swing", mode="paper", params={})
    db_session.add_all([inst, strat])
    db_session.flush()
    db_session.add(Quote(instrument_id=inst.id, last_price=1000.0, ts=datetime.now(UTC)))
    db_session.commit()
    return SimpleNamespace(db=db_session, strat=strat, inst=inst, clock=clock)


def _buy(horizon=15):
    return SignalDecision(
        signal=SignalType.BUY, price=1000.0, confidence=0.8, stop_loss=960.0, take_profit=1080.0,
        reason="idem", horizon_days=horizon,
    )


def _count(w, model):
    return w.db.scalar(select(func.count()).select_from(model).where(model.instrument_id == w.inst.id))


def test_a_single_scan_is_unchanged_one_signal_one_order_one_position(world):
    w = world
    sig = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert sig.was_executed and sig.signal_key is not None
    assert (_count(w, Signal), _count(w, Order), _count(w, Position)) == (1, 1, 1)


def test_a_retried_scan_returns_the_settled_signal_and_places_no_second_order(world):
    w = world
    first = execution.process_decision(w.db, w.strat, w.inst, _buy())
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and again.was_executed and again.rejection_reason is None
    assert (_count(w, Signal), _count(w, Order), _count(w, Position)) == (1, 1, 1)


def test_a_retry_after_midnight_maps_to_the_same_session(world):
    w = world
    first = execution.process_decision(w.db, w.strat, w.inst, _buy())
    w.clock["now"] = FRI_EVENING + timedelta(hours=8)  # 01:30 IST Saturday
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and _count(w, Signal) == 1


def test_a_settled_rejection_is_returned_unchanged(world):
    w = world
    first = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    first.rejection_reason = "Position already open"
    w.db.commit()
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and again.rejection_reason == "Position already open"
    assert (_count(w, Signal), _count(w, Order)) == (1, 0)


def test_an_unsettled_signal_is_reused_and_completes_exactly_one_order(world):
    w = world
    first = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")  # scan died before the order
    assert not first.was_executed and _count(w, Order) == 0
    done = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert done.id == first.id and done.was_executed
    assert (_count(w, Signal), _count(w, Order), _count(w, Position)) == (1, 1, 1)
    execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert (_count(w, Signal), _count(w, Order), _count(w, Position)) == (1, 1, 1)


def test_rows_without_a_key_are_never_touched(world):
    w = world
    old = Signal(
        strategy_id=w.strat.id, instrument_id=w.inst.id, signal_type="BUY", mode="paper", price=1000.0,
        generated_at=FRI_EVENING, horizon_days=15, signal_key=None,
    )
    w.db.add(old)
    w.db.commit()
    execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    w.db.refresh(old)
    assert old.signal_key is None and old.rejection_reason is None and not old.was_executed
    assert _count(w, Signal) == 2


def test_two_sessions_stay_distinct(world):
    w = world
    a = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    w.clock["now"] = MON_EVENING
    b = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    assert a.id != b.id and a.signal_key != b.signal_key


def test_two_horizons_stay_distinct(world):
    w = world
    a = execution.record_signal(w.db, w.strat, w.inst, _buy(5), "paper")
    b = execution.record_signal(w.db, w.strat, w.inst, _buy(15), "paper")
    assert a.id != b.id


def test_a_concurrent_scan_that_loses_the_race_gets_the_winners_row(world, monkeypatch):
    w = world
    winner = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    real = execution._signal_by_key
    calls = {"n": 0}

    def blind_first(db, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, key)

    monkeypatch.setattr(execution, "_signal_by_key", blind_first)
    loser = execution.record_signal(w.db, w.strat, w.inst, _buy(), "paper")
    assert loser.id == winner.id and _count(w, Signal) == 1


# ---- an order already exists for the signal: a retry never places a second one (Developer-5's P1) -------------

def _orders(w):
    return list(w.db.scalars(select(Order).where(Order.instrument_id == w.inst.id)))


def _crash(*a, **kw):
    raise RuntimeError("process died")


def _retry_places_nothing(w, expect_orders=1):
    first_id = w.db.scalar(select(Signal.id).where(Signal.instrument_id == w.inst.id))
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first_id
    assert len(_orders(w)) == expect_orders
    assert _count(w, Signal) == 1


def test_crash_after_the_order_row_is_committed_then_a_retry_places_no_second_order(world, monkeypatch):
    from swing_trade_ml.brokers.paper import PaperBroker

    w = world
    with monkeypatch.context() as m:
        m.setattr(PaperBroker, "place_order", _crash)
        with pytest.raises(RuntimeError):
            execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert len(_orders(w)) == 1 and _orders(w)[0].status == "PENDING"
    _retry_places_nothing(w)
    assert _count(w, Position) == 0


def test_crash_after_complete_before_finalize_then_a_retry_places_no_second_order(world, monkeypatch):
    w = world
    with monkeypatch.context() as m:
        m.setattr(execution, "_finalize_open_position", _crash)
        with pytest.raises(RuntimeError):
            execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert [o.status for o in _orders(w)] == ["COMPLETE"]
    _retry_places_nothing(w)


def test_a_live_pending_order_with_no_message_is_not_placed_again(world, monkeypatch):
    from swing_trade_ml.brokers.base import OrderResult
    from swing_trade_ml.brokers.paper import PaperBroker
    from swing_trade_ml.core.enums import OrderStatus

    w = world
    with monkeypatch.context() as m:
        m.setattr(PaperBroker, "place_order", lambda self, req, db: OrderResult("B1", OrderStatus.PENDING, message=None))
        execution.process_decision(w.db, w.strat, w.inst, _buy())
    sig = w.db.scalar(select(Signal).where(Signal.instrument_id == w.inst.id))
    assert sig.rejection_reason is None and not sig.was_executed  # unsettled, yet an order is in flight
    _retry_places_nothing(w)


def test_a_crash_before_any_order_row_still_lets_the_retry_place_exactly_one(world, monkeypatch):
    w = world
    with monkeypatch.context() as m:
        m.setattr(execution, "open_position", _crash)
        with pytest.raises(RuntimeError):
            execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert _orders(w) == []
    done = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert done.was_executed and len(_orders(w)) == 1 and _count(w, Signal) == 1


def test_open_position_itself_refuses_a_second_order_for_the_same_signal(world):
    w = world
    sig = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert execution.open_position(w.db, w.strat, w.inst, sig, 5) is None
    assert len(_orders(w)) == 1


# ---- what counts as settled: final outcomes only; a transient rejection stays retryable (Developer-5's P2) ------

def _busy_lock(*a, **kw):
    from swing_trade_ml.services.entry_lock import EntryLockBusy

    raise EntryLockBusy("busy")


def test_an_entry_lock_busy_rejection_is_retried_in_the_same_session_through_the_full_check(world, monkeypatch):
    w = world
    with monkeypatch.context() as m:
        m.setattr(execution, "entry_lock", _busy_lock)
        first = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert first.rejection_reason and "same moment" in first.rejection_reason and _orders(w) == []
    checks = []
    real = execution.risk.check_entry
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: checks.append(1) or real(**kw))
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and again.was_executed and again.rejection_reason is None
    assert checks == [1] and len(_orders(w)) == 1 and _count(w, Signal) == 1
    assert "retryable_rejection" not in (again.features or {})


def test_a_ranked_out_signal_can_be_bought_when_the_same_session_is_rescanned(world):
    w = world
    first = execution.process_decision(w.db, w.strat, w.inst, _buy(), ranked_out_reason="no slots")
    assert first.rejection_reason == "no slots" and _orders(w) == []
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and again.was_executed and again.rejection_reason is None
    assert len(_orders(w)) == 1


def test_a_ranked_out_signal_ranked_out_again_stays_one_rejected_row(world):
    w = world
    first = execution.process_decision(w.db, w.strat, w.inst, _buy(), ranked_out_reason="no slots")
    again = execution.process_decision(w.db, w.strat, w.inst, _buy(), ranked_out_reason="no slots today")
    assert again.id == first.id and again.rejection_reason == "no slots today" and _orders(w) == []


def test_a_risk_check_block_is_final_for_the_session_no_second_check_or_risk_event(world, monkeypatch):
    from swing_trade_ml.db.models.safety import RiskEvent
    from swing_trade_ml.services import risk

    w = world
    verdict = SimpleNamespace(allowed=False, reason="too big", rule="MAX_POSITION", quantity=0, amount_inr=0.0)
    calls = []
    monkeypatch.setattr(risk, "check_entry", lambda **kw: calls.append(1) or verdict)
    first = execution.process_decision(w.db, w.strat, w.inst, _buy())
    again = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert again.id == first.id and again.rejection_reason == "too big" and calls == [1]
    assert w.db.scalar(select(func.count()).select_from(RiskEvent).where(RiskEvent.strategy_id == w.strat.id)) == 1


def test_a_same_session_rescan_still_refreshes_the_open_positions_confidence(world):
    w = world
    execution.process_decision(w.db, w.strat, w.inst, _buy())
    pos = w.db.scalar(select(Position).where(Position.instrument_id == w.inst.id))
    low = SignalDecision(
        signal=SignalType.BUY, price=1000.0, confidence=0.41, stop_loss=960.0, take_profit=1080.0,
        reason="idem", horizon_days=15,
    )
    execution.process_decision(w.db, w.strat, w.inst, low)
    w.db.refresh(pos)
    assert pos.last_confidence == pytest.approx(0.41) and _count(w, Signal) == 1


def test_a_retried_unsettled_buy_does_not_send_its_entry_alert_twice(world, monkeypatch):
    w = world
    sent = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda msg, kind_name=None, **kw: sent.append(kind_name))
    with monkeypatch.context() as m:
        m.setattr(execution, "open_position", _crash)
        with pytest.raises(RuntimeError):
            execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert sent.count("signal") == 1
    done = execution.process_decision(w.db, w.strat, w.inst, _buy())
    assert done.was_executed and sent.count("signal") == 1 and sent.count("fill") == 1
