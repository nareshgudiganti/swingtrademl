# ruff: noqa: E501 (long explanatory lines)
"""Verified stock splits and bonus issues on open paper positions (Bot and Testing books), and the review flag.

Pure tests need no database. The DB tests use the normal rolled-back test session.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from fractions import Fraction

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.corporate_actions import CorporateAction, PositionAdjustment
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Order, Position, Strategy, Trade
from swing_trade_ml.services import corporate_action_accounting as ca
from swing_trade_ml.services import portfolio, tester_paper

EX = date(2026, 11, 10)
BEFORE = date(2026, 11, 3)


def _state(q=100, entry=1000.0, stop=960.0, target=1080.0, high=1010.0, initq=100):
    return {
        "quantity": q,
        "initial_quantity": initq,
        "broker_stop_qty": None,
        "entry_price": entry,
        "stop_loss": stop,
        "take_profit": target,
        "highest_price": high,
        "initial_stop_loss": stop,
        "broker_stop_trigger": None,
    }


def _plan(
    kind="split", num=2, den=1, state=None, status="OPEN", entry=BEFORE, book="bot", action_status="VERIFIED"
):
    return ca.plan_adjustment(
        position_status=status,
        entry_date=entry,
        book=book,
        state=state or _state(),
        kind=kind,
        action_status=action_status,
        ex_date=EX,
        numerator=num,
        denominator=den,
    )


# ---------------------------------------------------------------- pure ----


@pytest.mark.parametrize(
    ("kind", "num", "den", "k"),
    [
        ("split", 2, 1, 2),
        ("split", 5, 1, 5),
        ("split", 10, 2, 5),
        ("bonus", 1, 1, 2),
        ("bonus", 1, 2, Fraction(3, 2)),
    ],
)
def test_factor(kind, num, den, k):
    assert ca.factor(kind, num, den) == k


def test_two_for_one_split():
    p = _plan("split", 2, 1)
    assert p.status == "APPLIED"
    assert p.after["quantity"] == 200 and p.after["initial_quantity"] == 200
    assert p.after["entry_price"] == pytest.approx(500.0)
    assert p.after["stop_loss"] == pytest.approx(480.0) and p.after["take_profit"] == pytest.approx(540.0)
    assert p.after["highest_price"] == pytest.approx(505.0) and p.after["initial_stop_loss"] == pytest.approx(
        480.0
    )
    assert p.after["quantity"] * p.after["entry_price"] == pytest.approx(100 * 1000.0)
    assert p.before == _state()  # complete before record


def test_one_to_one_bonus():
    p = _plan("bonus", 1, 1)
    assert (
        p.status == "APPLIED"
        and p.after["quantity"] == 200
        and p.after["entry_price"] == pytest.approx(500.0)
    )


def test_one_for_two_bonus_even_quantity():
    p = _plan("bonus", 1, 2, _state(q=100, initq=100))
    assert p.status == "APPLIED" and p.after["quantity"] == 150
    assert p.after["entry_price"] == pytest.approx(1000.0 / 1.5)


def test_five_for_one_split():
    p = _plan("split", 5, 1)
    assert p.after["quantity"] == 500 and p.after["stop_loss"] == pytest.approx(192.0)


def test_fractional_result_is_not_guessed():
    p = _plan("bonus", 1, 2, _state(q=101, initq=101))
    assert p.status == "NEEDS_REVIEW" and p.after is None and "whole number" in p.explanation


def test_fractional_initial_quantity_also_blocks():
    p = _plan("bonus", 1, 2, _state(q=100, initq=101))
    assert p.status == "NEEDS_REVIEW" and p.after is None


def test_closed_position_untouched():
    p = _plan(status="CLOSED")
    assert p.status == "SKIPPED" and p.after is None


def test_entered_on_ex_date_untouched():
    assert _plan(entry=EX).status == "SKIPPED"


def test_unverified_action_changes_nothing():
    p = _plan(action_status="UNVERIFIED")
    assert p.status == "NEEDS_REVIEW" and p.after is None


@pytest.mark.parametrize("kind", ["demerger", "rights", "dividend", "merger", "buyback"])
def test_other_kinds_only_flag(kind):
    p = _plan(kind, 1, 1)
    assert p.status == "NEEDS_REVIEW" and p.after is None and "not implemented" in p.explanation


def test_real_book_never_adjusted():
    assert _plan(book="real").status == "NEEDS_REVIEW"


def test_bad_ratio_and_reverse_split_flag():
    assert _plan("split", 1, 2).status == "NEEDS_REVIEW"
    assert _plan("split", 0, 1).status == "NEEDS_REVIEW"


# ------------------------------------------------------------------ DB ----


@pytest.fixture
def world(db_session, monkeypatch):
    monkeypatch.setattr(settings, "TRADING_MODE", "paper")
    inst = Instrument(instrument_token=990001, tradingsymbol="CASPLIT", exchange="NSE", is_watchlisted=True)
    bot = Strategy(name="ca_bot", strategy_type="ml_swing", mode="paper", params={})
    db_session.add_all([inst, bot])
    db_session.flush()
    tester = tester_paper.get_or_create_strategy(db_session)
    return db_session, inst, bot, tester


def _pos(db, inst, strat, qty=100, entry=1000.0, entry_at=None, status="OPEN", price=1000.0):
    p = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        status=status,
        quantity=qty,
        initial_quantity=qty,
        entry_price=entry,
        entry_at=entry_at or datetime(2026, 11, 3, 5, 0, tzinfo=UTC),
        stop_loss=entry * 0.96,
        take_profit=entry * 1.08,
        highest_price=entry,
        initial_stop_loss=entry * 0.96,
        total_charges=25.0,
        current_price=price,
    )
    db.add(p)
    db.flush()
    return p


def _action(db, inst, kind="split", num=2, den=1, status="VERIFIED", ex=EX):
    a = CorporateAction(
        instrument_id=inst.id,
        symbol="CASPLIT",
        kind=kind,
        ex_date=ex,
        ratio_numerator=num,
        ratio_denominator=den,
        status=status,
        source_url="https://example.invalid/announcement",
    )
    db.add(a)
    db.flush()
    return a


def _bot_cash(db):
    return portfolio.portfolio_value_and_cash(db, "paper")[1]


def _counts(db):
    return (
        db.execute(select(func.count()).select_from(Order)).scalar_one(),
        db.execute(select(func.count()).select_from(Trade)).scalar_one(),
    )


def test_dry_run_is_the_default_and_writes_nothing(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot)
    a = _action(db, inst)
    result = ca.apply_action(db, a.id)
    assert result.applied is False and [c.status for c in result.changes] == ["APPLIED"]
    assert result.changes[0].after["quantity"] == 200 and result.changes[0].written is False
    db.refresh(pos)
    assert pos.quantity == 100 and pos.entry_price == 1000.0
    assert db.execute(select(func.count()).select_from(PositionAdjustment)).scalar_one() == 0


def test_bot_book_apply_is_idempotent_with_complete_records_and_cash_identity(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot)
    a = _action(db, inst)
    cash_before = _bot_cash(db)
    assert cash_before == pytest.approx(settings.PAPER_STARTING_CAPITAL - 1000.0 * 100 - 25.0, abs=0.01)
    orders_trades = _counts(db)

    first = ca.apply_action(db, a.id, apply=True)
    assert [c.written for c in first.changes] == [True]
    db.refresh(pos)
    assert pos.quantity == 200 and pos.initial_quantity == 200 and pos.entry_price == pytest.approx(500.0)
    assert pos.stop_loss == pytest.approx(480.0) and pos.take_profit == pytest.approx(540.0)
    assert pos.total_charges == 25.0
    assert _bot_cash(db) == pytest.approx(cash_before, abs=0.01)
    assert _bot_cash(db) == pytest.approx(
        settings.PAPER_STARTING_CAPITAL - pos.entry_price * pos.quantity - pos.total_charges, abs=0.01
    )

    row = db.execute(select(PositionAdjustment)).scalar_one()
    assert row.status == "APPLIED" and row.book == "bot" and row.applied_at is not None
    assert row.before["quantity"] == 100 and row.after["quantity"] == 200
    assert set(row.before) == set(row.after) == {*ca.QTY_FIELDS, *ca.PRICE_FIELDS}
    assert row.before["entry_price"] == 1000.0 and row.after["entry_price"] == pytest.approx(500.0)

    second = ca.apply_action(db, a.id, apply=True)
    assert second.changes == []
    db.refresh(pos)
    assert pos.quantity == 200 and pos.entry_price == pytest.approx(500.0)
    assert db.execute(select(func.count()).select_from(PositionAdjustment)).scalar_one() == 1
    assert _counts(db) == orders_trades


def test_testing_book_apply_is_separate_and_cash_identity_holds(world):
    db, inst, bot, tester = world
    bot_pos = _pos(db, inst, bot, qty=50)
    tester_pos = _pos(db, inst, tester, qty=100)
    a = _action(db, inst, "bonus", 1, 1)
    bot_cash = _bot_cash(db)
    tester_cash = tester_paper.available_cash(db)

    ca.apply_action(db, a.id, apply=True)
    rows = {r.position_id: r for r in db.execute(select(PositionAdjustment)).scalars()}
    assert rows[tester_pos.id].book == "tester" and rows[bot_pos.id].book == "bot"
    db.refresh(tester_pos)
    db.refresh(bot_pos)
    assert tester_pos.quantity == 200 and tester_pos.entry_price == pytest.approx(500.0)
    assert bot_pos.quantity == 100 and bot_pos.entry_price == pytest.approx(500.0)
    assert tester_paper.available_cash(db) == pytest.approx(tester_cash, abs=0.01)
    assert _bot_cash(db) == pytest.approx(bot_cash, abs=0.01)


def test_closed_position_and_trade_never_modified(world):
    db, inst, bot, _ = world
    closed = _pos(db, inst, bot, status="CLOSED")
    closed.exit_price, closed.exit_at, closed.exit_reason = (
        1020.0,
        datetime(2026, 11, 5, tzinfo=UTC),
        "TARGET_HIT",
    )
    trade = Trade(
        position_id=closed.id,
        strategy_id=bot.id,
        instrument_id=inst.id,
        mode="paper",
        symbol="CASPLIT",
        quantity=100,
        entry_price=1000.0,
        exit_price=1020.0,
        entry_at=closed.entry_at,
        exit_at=closed.exit_at,
        holding_days=2,
        gross_pnl=2000.0,
        charges=30.0,
        net_pnl=1970.0,
        return_pct=2.0,
        exit_reason="TARGET_HIT",
        is_win=True,
    )
    order = Order(
        instrument_id=inst.id,
        position_id=closed.id,
        mode="paper",
        transaction_type="BUY",
        quantity=100,
        status="COMPLETE",
        placed_at=closed.entry_at,
    )
    db.add_all([trade, order])
    db.flush()
    a = _action(db, inst)
    ca.apply_action(db, a.id, apply=True)
    db.refresh(closed)
    db.refresh(trade)
    db.refresh(order)
    assert closed.quantity == 100 and closed.entry_price == 1000.0 and closed.status == "CLOSED"
    assert trade.quantity == 100 and trade.entry_price == 1000.0 and trade.net_pnl == 1970.0
    assert order.quantity == 100
    assert db.execute(select(func.count()).select_from(PositionAdjustment)).scalar_one() == 0
    assert _counts(db) == (1, 1)


def test_position_opened_after_ex_date_is_skipped(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot, entry_at=datetime(2026, 11, 11, 5, 0, tzinfo=UTC))
    a = _action(db, inst)
    ca.apply_action(db, a.id, apply=True)
    db.refresh(pos)
    assert pos.quantity == 100
    assert db.execute(select(PositionAdjustment.status)).scalar_one() == "SKIPPED"


def test_demerger_on_open_position_is_flagged_with_expected_exit(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot, price=900.0)  # raw price fell 10% after the demerger, below the 960 stop
    a = _action(db, inst, "demerger", 1, 1)
    ca.apply_action(db, a.id, apply=True)
    db.refresh(pos)
    assert pos.quantity == 100 and pos.entry_price == 1000.0 and pos.stop_loss == pytest.approx(960.0)
    row = db.execute(select(PositionAdjustment)).scalar_one()
    assert row.status == "NEEDS_REVIEW" and row.after is None
    assert row.expected_exit["reason"] == "STOP_LOSS_HIT" and row.expected_exit["would_exit"] is True
    assert "STOP_LOSS_HIT" in row.explanation and "not implemented" in row.explanation
    assert "Raw losses are not hidden" in row.explanation


def test_unverified_action_flags_only(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot)
    a = _action(db, inst, status="UNVERIFIED")
    ca.apply_action(db, a.id, apply=True)
    db.refresh(pos)
    assert pos.quantity == 100
    assert db.execute(select(PositionAdjustment.status)).scalar_one() == "NEEDS_REVIEW"


def test_fractional_case_flags_and_rerun_changes_nothing(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot, qty=101)
    a = _action(db, inst, "bonus", 1, 2)
    ca.apply_action(db, a.id, apply=True)
    ca.apply_action(db, a.id, apply=True)
    db.refresh(pos)
    assert pos.quantity == 101
    assert db.execute(select(func.count()).select_from(PositionAdjustment)).scalar_one() == 1


def test_review_flags_unadjusted_position_once_and_alerts_once(world):
    db, inst, bot, tester = world
    _pos(db, inst, bot, price=500.0)
    _pos(db, inst, tester, price=500.0)
    _action(db, inst)
    sent: list[str] = []
    lines = ca.review_open_positions(db, date(2026, 11, 12), alert=sent.append)
    assert len(lines) == 2 and len(sent) == 2
    rows = db.execute(select(PositionAdjustment)).scalars().all()
    assert {r.book for r in rows} == {"bot", "tester"} and {r.status for r in rows} == {"NEEDS_REVIEW"}
    assert all(
        r.expected_exit["reason"] == "STOP_LOSS_HIT" for r in rows
    )  # raw 500 <= stop 960, nothing hidden
    again = ca.review_open_positions(db, date(2026, 11, 12), alert=sent.append)
    assert len(again) == 2 and len(sent) == 2
    assert db.execute(select(func.count()).select_from(PositionAdjustment)).scalar_one() == 2


def test_review_before_ex_date_and_after_apply_flags_nothing(world):
    db, inst, bot, _ = world
    _pos(db, inst, bot)
    a = _action(db, inst)
    assert ca.review_open_positions(db, date(2026, 11, 9)) == []
    ca.apply_action(db, a.id, apply=True)
    assert ca.review_open_positions(db, date(2026, 11, 12)) == []


def test_apply_upgrades_a_review_flag_and_keeps_it_as_evidence(world):
    db, inst, bot, _ = world
    pos = _pos(db, inst, bot, price=500.0)
    a = _action(db, inst)
    ca.review_open_positions(db, date(2026, 11, 12))
    ca.apply_action(db, a.id, apply=True)
    db.refresh(pos)
    row = db.execute(select(PositionAdjustment)).scalar_one()
    assert pos.quantity == 200 and row.status == "APPLIED"
    assert "Earlier review flag" in row.explanation and row.expected_exit["reason"] == "STOP_LOSS_HIT"


def test_pending_event_does_not_change_check_exits(world, monkeypatch):
    """A position with an unapplied verified event still hits its stop exactly as before."""
    from swing_trade_ml.brokers.paper import PaperBroker
    from swing_trade_ml.services import execution

    db, inst, bot, _ = world
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)
    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, d: dict.fromkeys(keys, 900.0))
    from swing_trade_ml.db.models.market import Quote

    db.add(Quote(instrument_id=inst.id, last_price=900.0, ts=datetime.now(UTC)))
    pos = _pos(db, inst, bot, price=1000.0)
    _action(db, inst)
    ca.review_open_positions(db, date(2026, 11, 12), price_for=lambda p: 900.0)
    closed = execution.check_exits(db)
    assert [t.exit_reason for t in closed if t.position_id == pos.id] == ["STOP_LOSS_HIT"]
    db.refresh(pos)
    assert pos.status == "CLOSED" and pos.quantity == 100


def test_models_are_additive_with_unique_keys(db_session):
    names = {c.name for c in PositionAdjustment.__table__.constraints}
    assert "uq_position_adjustment" in names
