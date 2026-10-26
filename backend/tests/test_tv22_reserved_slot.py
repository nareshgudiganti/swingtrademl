"""tv22: one reserved paper slot for the brain (owner approved A-F on 2026-10-25, F = option (i)).

docs/superpowers/specs/2026-10-24-tv22-brain-reserved-slot.md, section 6. Numbers are the prod account's
of 2026-10-24: portfolio about Rs 9.76L, stressed market (10% may be invested, ceiling Rs 97,579),
minimum position Rs 39,734.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, instrument, no_broker, run, v1_strategy
from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.modules.m07_risk import module as m07
from swing_trade_ml.brain.modules.m07_risk.allocator import Candidate, Policy, allocate
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.safety import SystemState
from swing_trade_ml.db.models.trading import Order, Position, Signal
from swing_trade_ml.services import deployable, engine, execution, risk, system_state
from swing_trade_ml.services.brain_golive import compare
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_strategy_mod
from swing_trade_ml.strategies.base import SignalDecision

PV = 975_790.0
CEILING = 0.10 * PV  # Rs 97,579
MIN = limits_for(PV).min_position_inr  # Rs 39,733.9
DAY_UTC = at(DAY)


@pytest.fixture()
def stressed(db_session, monkeypatch):
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "risk_based")
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="stressed", fraction=0.10, context_available=True),
    )
    monkeypatch.setattr(m07, "portfolio_value_and_cash", lambda db, book: (PV, PV))
    db_session.add(SystemState(id=1, new_entries_enabled=True, exits_enabled=True))
    db_session.flush()


def _banner(db, mode: str, run_id: str = "tv22-run") -> None:
    r = run(db, run_id, DAY)
    r.banner_mode = mode
    db.flush()


def _hold(db, strategy, symbol: str, token: int, value: float) -> Position:
    inst = instrument(db, symbol, token)
    pos = Position(
        strategy_id=strategy.id,
        instrument_id=inst.id,
        mode="paper",
        status="OPEN",
        quantity=1,
        entry_price=value,
        current_price=value,
        entry_at=DAY_UTC,
    )
    db.add(pos)
    db.flush()
    return pos


def _check(db, inst, price: float, strategy):
    return risk.check_entry(
        db,
        "paper",
        inst.id,
        price=price,
        stop_loss=round(price * 0.96, 2),
        portfolio_value=PV,
        available_cash=PV,
        strategy=strategy,
    )


def _m07(db, *cands: tuple[str, float, int], mode=MarketMode.DEFENSIVE):
    account = m07.account_snapshot(db, "paper")
    candidates = [
        Candidate(symbol=s, price=p, strength=1.0 - i / 10, bucket=None, instrument_id=iid)
        for i, (s, p, iid) in enumerate(cands)
    ]
    return allocate(candidates, account, m07._v1_check(db, "paper", PV), Policy(mode=mode), risk.buy_cost)


def _setup(db, banner: str, price: float, *, brain: bool = True):
    """v1 holds everything but the reservation for one share at `price`."""
    v1 = v1_strategy(db, name="tv22-v1")
    b = brain_strategy(db, name="tv22-brain") if brain else None
    _banner(db, banner)
    held = CEILING - risk.brain_reservation(MIN, price, banner)
    _hold(db, v1, "TVXHELD", 922000, held)
    return v1, b


# ------------------------------------------------------------- the helper --


def test_reservation_factor_matches_m07():
    """Fails if M07's defensive size factor changes without the reservation (or the other way round)."""
    assert risk.RESERVATION_DEFENSIVE_SIZE_FACTOR == m07.DEFENSIVE_SIZE_FACTOR
    assert risk.brain_reservation(MIN, 1000.0, "DEFENSIVE") == pytest.approx(
        (MIN + 1000.0) / m07.DEFENSIVE_SIZE_FACTOR
    )


def test_reservation_sizes():
    assert risk.brain_reservation(MIN, 1000.0, "NORMAL") == pytest.approx(MIN + 1000.0)
    # DEFENSIVE: twice the minimum plus headroom (one share for each half).
    assert risk.brain_reservation(MIN, 1000.0, "DEFENSIVE") == pytest.approx(2 * MIN + 2000.0)
    # NO NEW TRADES or no brain run yet: the cautious (bigger) reservation.
    assert risk.brain_reservation(MIN, 1000.0, None) == risk.brain_reservation(MIN, 1000.0, "DEFENSIVE")
    assert risk.brain_reservation(MIN, 1000.0, "NO_NEW_TRADES") == risk.brain_reservation(
        MIN, 1000.0, "DEFENSIVE"
    )


# ------------------------------------------------------ end to end, layer 1 + 2 --


def test_defensive_day_brain_uses_reserved_slot_v1_cannot(db_session, stressed):
    v1, brain = _setup(db_session, "DEFENSIVE", 1000.0)
    a = instrument(db_session, "TVXA", 922001)
    b = instrument(db_session, "TVXB", 922002)

    # v1 may not use the reserved room
    v1_try = _check(db_session, a, 1000.0, v1)
    assert not v1_try.allowed and v1_try.rule == "DEPLOYABLE"
    assert "reserved slot" in v1_try.reason

    # M07 (no strategy, whole-account room): first idea allowed at half size, at least the minimum
    verdicts = _m07(db_session, ("TVXA", 1000.0, a.id), ("TVXB", 1000.0, b.id))
    first, second = verdicts
    assert first.allowed and first.max_qty * 1000.0 >= MIN
    assert first.max_qty == 40
    # only one fits the reserved room
    assert not second.allowed

    # execution check for the brain passes, and the order is capped at M07's quantity (F)
    at_exec = _check(db_session, a, 1000.0, brain)
    assert at_exec.allowed
    assert 1000.0 * at_exec.quantity <= risk.brain_reservation(MIN, 1000.0, "DEFENSIVE")
    d = SimpleNamespace(qty=first.max_qty)
    assert brain_strategy_mod.capped_order_quantity(at_exec.quantity, d, "DEFENSIVE") == first.max_qty


def test_normal_day_one_minimum_plus_one_share(db_session, stressed):
    v1, brain = _setup(db_session, "NORMAL", 1000.0)
    a = instrument(db_session, "TVXA", 922001)
    assert not _check(db_session, a, 1000.0, v1).allowed
    (verdict,) = _m07(db_session, ("TVXA", 1000.0, a.id), mode=MarketMode.NORMAL)
    assert verdict.allowed and verdict.max_qty * 1000.0 >= MIN
    assert _check(db_session, a, 1000.0, brain).allowed


def test_exactly_the_minimum_is_refused_minimum_plus_one_share_passes(db_session, stressed):
    v1 = v1_strategy(db_session, name="tv22-v1")
    _banner(db_session, "NORMAL")
    _hold(db_session, v1, "TVXHELD", 922000, CEILING - MIN)  # room = exactly the minimum
    a = instrument(db_session, "TVXA", 922001)
    (verdict,) = _m07(db_session, ("TVXA", 1000.0, a.id), mode=MarketMode.NORMAL)
    assert not verdict.allowed


def test_defensive_one_share_of_headroom_is_not_enough_two_are(db_session, stressed):
    """Why the DEFENSIVE reservation carries one share per half: M07 halves rounding down."""
    v1 = v1_strategy(db_session, name="tv22-v1")
    _banner(db_session, "DEFENSIVE")
    pos = _hold(db_session, v1, "TVXHELD", 922000, CEILING - (2 * MIN + 3000.0))
    a = instrument(db_session, "TVXA", 922001)
    (verdict,) = _m07(db_session, ("TVXA", 3000.0, a.id))
    assert not verdict.allowed  # 27 shares fit, half is 13 = Rs 39,000 < minimum
    pos.entry_price = pos.current_price = CEILING - risk.brain_reservation(MIN, 3000.0, "DEFENSIVE")
    db_session.flush()
    (verdict,) = _m07(db_session, ("TVXA", 3000.0, a.id))
    assert verdict.allowed and verdict.max_qty * 3000.0 >= MIN


# --------------------------------------------------------------- the rooms --


def test_rooms_by_caller(db_session, stressed):
    v1, brain = _setup(db_session, "DEFENSIVE", 1000.0)
    invested = sum(h.value for h in risk.open_holdings(db_session, "paper"))
    whole = CEILING - invested
    reservation = risk.brain_reservation(MIN, 1000.0, "DEFENSIVE")
    # no strategy (M07): unchanged
    assert risk.market_room(db_session, "paper", None, CEILING, invested, MIN, 1000.0).room == whole
    # v1: minus the reservation
    assert risk.market_room(db_session, "paper", v1, CEILING, invested, MIN, 1000.0).room == pytest.approx(
        whole - reservation
    )
    # brain: the lesser of reservation and whole-account room
    assert risk.market_room(db_session, "paper", brain, CEILING, invested, MIN, 1000.0).room == pytest.approx(
        min(reservation, whole)
    )


def test_brain_holding_frees_v1_and_shrinks_brain_room(db_session, stressed):
    v1, brain = _setup(db_session, "DEFENSIVE", 1000.0)
    _hold(db_session, brain, "TVXBRAIN", 922010, 40_000.0)
    invested = sum(h.value for h in risk.open_holdings(db_session, "paper"))
    whole = CEILING - invested
    assert risk.market_room(db_session, "paper", v1, CEILING, invested, MIN, 1000.0).room == whole
    reservation = risk.brain_reservation(MIN, 1000.0, "DEFENSIVE")
    assert risk.market_room(db_session, "paper", brain, CEILING, invested, MIN, 1000.0).room == pytest.approx(
        min(reservation - 40_000.0, whole)
    )


def test_no_brain_strategy_no_reservation(db_session, stressed):
    v1, _ = _setup(db_session, "DEFENSIVE", 1000.0, brain=False)
    invested = sum(h.value for h in risk.open_holdings(db_session, "paper"))
    room = risk.market_room(db_session, "paper", v1, CEILING, invested, MIN, 1000.0)
    assert room.room == CEILING - invested and room.reserved == 0
    # the live book (real orders) has no brain strategy, so nothing is reserved there either
    live = risk.market_room(db_session, "live", v1, CEILING, 0.0, MIN, 1000.0)
    assert live.room == CEILING and live.reserved == 0


@pytest.mark.parametrize("banner", ["NORMAL", "DEFENSIVE"])
@pytest.mark.parametrize("held", [0.0, 30_000.0, 60_000.0, 90_000.0])
def test_account_never_exceeds_ceiling(db_session, stressed, banner, held):
    v1 = v1_strategy(db_session, name="tv22-v1")
    brain = brain_strategy(db_session, name="tv22-brain")
    _banner(db_session, banner)
    if held:
        _hold(db_session, v1, "TVXHELD", 922000, held)
    invested = sum(h.value for h in risk.open_holdings(db_session, "paper"))
    a = instrument(db_session, "TVXA", 922001)
    for strategy in (None, v1, brain):
        d = _check(db_session, a, 1000.0, strategy)
        assert invested + d.quantity * 1000.0 <= CEILING
        assert risk.market_room(db_session, "paper", strategy, CEILING, invested, MIN, 1000.0).room <= (
            CEILING - invested
        )


def test_kill_switch_drawdown_and_no_new_trades_still_refuse_the_brain(db_session, stressed, monkeypatch):
    _v1, brain = _setup(db_session, "DEFENSIVE", 1000.0)
    a = instrument(db_session, "TVXA", 922001)
    assert _check(db_session, a, 1000.0, brain).allowed

    (verdict,) = _m07(db_session, ("TVXA", 1000.0, a.id), mode=MarketMode.NO_NEW_TRADES)
    assert not verdict.allowed

    monkeypatch.setattr(risk, "current_drawdown", lambda db, mode, value=None: 0.5)
    assert _check(db_session, a, 1000.0, brain).rule == "DRAWDOWN"
    monkeypatch.undo()

    system_state.halt(db_session, reason="test", by="test")
    assert _check(db_session, a, 1000.0, brain).rule == "HALTED"


def test_engine_mirror_is_never_stricter_and_takes_the_reservation_off(db_session, stressed):
    v1 = v1_strategy(db_session, name="tv22-v1")
    assert engine._market_room_slots(db_session, v1, "paper", PV) == 2  # 97,579 / 39,734
    brain_strategy(db_session, name="tv22-brain")
    _banner(db_session, "NORMAL")
    assert engine._market_room_slots(db_session, v1, "paper", PV) == 1  # (97,579 - 39,734) / 39,734
    _banner(db_session, "DEFENSIVE", "tv22-run-2")
    # no v1 room left: still one candidate tried, so check_entry records the real reason
    assert engine._market_room_slots(db_session, v1, "paper", PV) == 1


# ------------------------------------------------------------- item F --


def test_brain_order_capped_at_m07_quantity_on_defensive_days():
    d = SimpleNamespace(qty=40)
    assert brain_strategy_mod.capped_order_quantity(81, d, "DEFENSIVE") == 40
    assert brain_strategy_mod.capped_order_quantity(81, d, "NO_NEW_TRADES") == 40
    assert brain_strategy_mod.capped_order_quantity(81, d, None) == 40
    assert brain_strategy_mod.capped_order_quantity(81, d, "NORMAL") == 81
    # only ever smaller
    assert brain_strategy_mod.capped_order_quantity(30, d, "DEFENSIVE") == 30
    assert brain_strategy_mod.capped_order_quantity(30, SimpleNamespace(qty=0), "DEFENSIVE") == 0


# ------------------------------------------------- item C: one counted idea a day --

BUY = SignalDecision(SignalType.BUY, 100.0, 0.6, "r", stop_loss=96.0, take_profit=108.0, horizon_days=15)


def _allow(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (PV, PV))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10, "ok"))


def _shift_days(db, strategy, days: int) -> None:
    for s in db.query(Signal).filter_by(strategy_id=strategy.id):
        s.generated_at = s.generated_at - timedelta(days=days)
    db.flush()


def test_practice_counts_at_most_one_idea_a_day_and_scores_the_rest(db_session, monkeypatch):
    _allow(monkeypatch)
    brain = brain_strategy(db_session, name="tv22-count")
    a, b, c = (instrument(db_session, f"TVC{x}", 922100 + i) for i, x in enumerate("ABC"))

    first = execution.process_decision(db_session, brain, a, BUY)
    assert execution.BEYOND_SLOT_KEY not in (first.features or {}) and first.rejection_reason is None
    second = execution.process_decision(db_session, brain, b, BUY)
    assert second.features[execution.BEYOND_SLOT_KEY] == "ONE_PER_DAY"
    assert second.rejection_reason.startswith(execution.BEYOND_SLOT_PREFIX)
    assert second.stop_loss and second.take_profit  # still scored to its outcome
    # the same idea recorded again the same day is not a second idea
    again = execution.process_decision(db_session, brain, a, BUY)
    assert execution.BEYOND_SLOT_KEY not in (again.features or {})
    # an idea blocked by a risk limit neither counts nor takes the slot
    blocked = dataclasses.replace(BUY, features={execution.BLOCKED_BY_RISK_KEY: "BRAIN_RISK_CHECK"})
    sig = execution.process_decision(db_session, brain, c, blocked)
    assert execution.BEYOND_SLOT_KEY not in sig.features

    # next day: A is still a counted, unfinished idea -> not counted again; C takes the slot
    _shift_days(db_session, brain, 1)
    a2 = execution.process_decision(db_session, brain, a, BUY)
    assert a2.features[execution.BEYOND_SLOT_KEY] == "ALREADY_COUNTED"
    c2 = execution.process_decision(db_session, brain, c, BUY)
    assert execution.BEYOND_SLOT_KEY not in (c2.features or {})
    assert db_session.query(Order).filter_by(strategy_id=brain.id).count() == 0


def test_v1_and_live_stage_brain_are_never_tagged(db_session, monkeypatch):
    from swing_trade_ml.db.models.brain_golive import BrainStageChange

    _allow(monkeypatch)
    v1 = v1_strategy(db_session, name="tv22-v1-adv", execution_mode="advisory")
    a, b = instrument(db_session, "TVCV", 922110), instrument(db_session, "TVCW", 922111)
    execution.process_decision(db_session, v1, a, BUY)
    s = execution.process_decision(db_session, v1, b, BUY)
    assert execution.BEYOND_SLOT_KEY not in (s.features or {})
    db_session.add(BrainStageChange(stage="approval", previous_stage="shadow", changed_by="t", reason="t"))
    db_session.flush()
    brain = brain_strategy(db_session, name="tv22-live")
    execution.process_decision(db_session, brain, a, BUY)
    s2 = execution.process_decision(db_session, brain, b, BUY)
    assert execution.BEYOND_SLOT_KEY not in (s2.features or {})


def _row(symbol: str, *, beyond=False, blocked=False, day: date = DAY):
    return compare.Row(
        strategy="b",
        is_brain=True,
        symbol=symbol,
        day=day,
        generated_at=DAY_UTC,
        outcome="TARGET_HIT",
        outcome_pct=0.08,
        blocked=blocked,
        beyond_slot=beyond,
    )


def test_compare_reports_beyond_slot_apart_and_never_counts_it():
    out = compare.compare([_row("A"), _row("B", beyond=True), _row("C", blocked=True)], {DAY})
    assert out["brain"]["ideas"] == 1
    assert out["brain_beyond_slot"]["ideas"] == 1
    assert out["brain_blocked"]["ideas"] == 1
    # sealed trial: counts only for the beyond-slot group too
    sealed = compare.compare([_row("A"), _row("B", beyond=True)], {DAY}, sealed_from=DAY)
    assert sealed["brain_beyond_slot"]["hit_rate"] is None and sealed["brain_beyond_slot"]["ideas"] == 1


def test_gate_count_excludes_beyond_slot(db_session):
    brain = brain_strategy(db_session, name="tv22-gate")
    base = compare.finished_brain_ideas(db_session)
    beyond0 = compare.finished_beyond_slot_brain_ideas(db_session)
    for i, feats in enumerate(({}, {compare.BEYOND_SLOT_KEY: "ONE_PER_DAY"})):
        inst = instrument(db_session, f"TVG{i}", 922120 + i)
        db_session.add(
            Signal(
                strategy_id=brain.id,
                instrument_id=inst.id,
                signal_type=SignalType.BUY,
                mode="paper",
                price=100.0,
                stop_loss=96.0,
                take_profit=108.0,
                horizon_days=15,
                generated_at=DAY_UTC,
                features=feats,
                outcome="TARGET_HIT",
                outcome_pct=0.08,
            )
        )
    db_session.flush()
    assert compare.finished_brain_ideas(db_session) == base + 1
    assert compare.finished_beyond_slot_brain_ideas(db_session) == beyond0 + 1


# ------------------------------------------------------- never force a trade --


def test_no_brain_idea_no_order_room_unused(db_session, stressed, monkeypatch):
    no_broker(monkeypatch)
    v1, brain = _setup(db_session, "DEFENSIVE", 1000.0)
    a = instrument(db_session, "TVXA", 922001)
    before = sum(h.value for h in risk.open_holdings(db_session, "paper"))
    hold = brain_strategy_mod.to_signal(None, SimpleNamespace(id="tv22-run"), 1000.0, practice=True)
    assert hold.signal == SignalType.HOLD
    execution.process_decision(db_session, brain, a, hold)
    assert db_session.query(Order).filter_by(strategy_id=brain.id).count() == 0
    assert db_session.query(Position).filter_by(strategy_id=brain.id).count() == 0
    assert sum(h.value for h in risk.open_holdings(db_session, "paper")) == before
    # and v1 holdings are never sold to make room
    assert db_session.query(Position).filter_by(strategy_id=v1.id, status="OPEN").count() == 1


# ----------------------------------------------- item B: the trial journal split --


def _journal_bars(n: int = 40) -> pd.DataFrame:
    rows, d, price = [], date(2026, 10, 15), 100.0
    while len(rows) < n:
        if d.weekday() < 5:
            rows.append(
                {"day": d, "open": price, "high": price * 1.03, "low": price * 0.99, "close": price * 1.01}
            )
            price *= 1.01
        d += timedelta(days=1)
    return pd.DataFrame(rows)


def test_journal_reports_before_and_after_the_change_apart_and_gate_is_unchanged():
    from swing_trade_ml.brain import trial_journal as tj

    days = [date(2026, 10, 20), date(2026, 10, 23), tj.TV22_CHANGE_DATE, date(2026, 10, 27)]
    sessions = [
        tj.Session(d, "DEFENSIVE", (tj.Idea("AAA", "TRADE", 0.9), tj.Idea("BBB", "WAIT", 0.5))) for d in days
    ]
    bars = {"AAA": _journal_bars(), "BBB": _journal_bars()}
    j = tj.build_journal(sessions, bars)
    assert j["change_date"] == tj.TV22_CHANGE_DATE.isoformat()
    before, after = j["periods"]
    assert (before["label"], before["sessions"]) == ("before_tv22", 2)
    assert (after["label"], after["sessions"], after["first_day"]) == ("from_tv22", 2, "2026-10-26")
    assert (
        before["summaries"]["brain_trade"]["picked"] + after["summaries"]["brain_trade"]["picked"]
        == (j["summaries"]["brain_trade"]["picked"])
    )
    # the gate reads the whole range, exactly as before the change
    whole = tj.build_journal(sessions, bars)
    whole.pop("periods")
    assert tj.gate(j) == tj.gate(whole)
    assert tj.GATE_MIN_IDEAS == 30 and tj.MIN_SESSIONS == 15
    assert "Before and after the reserved slot" in tj.plain_report(j)


def test_sealed_journal_seals_the_periods_too():
    from swing_trade_ml.brain import trial_journal as tj
    from swing_trade_ml.services import trial_seal

    days = [date(2026, 10, 23), tj.TV22_CHANGE_DATE]
    sessions = [tj.Session(d, "DEFENSIVE", (tj.Idea("AAA", "TRADE", 0.9),)) for d in days]
    j = tj.build_journal(sessions, {"AAA": _journal_bars()})
    sealed = trial_seal.seal_journal(j)
    if not trial_seal.SEALED:
        pytest.skip("the trial seal is off")
    for p in sealed["periods"]:
        for row in p["summaries"].values():
            if isinstance(row, dict):
                assert all(row.get(k) is None for k in row if k not in trial_seal.COUNT_FIELDS)
    assert "Hit target" not in tj.plain_report(sealed).split("Before and after")[1].split("##")[0]
