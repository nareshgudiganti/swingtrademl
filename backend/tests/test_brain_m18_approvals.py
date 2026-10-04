"""M18 task 7: in the approval stage an idea is bought only after the owner's
OK, and only if it is still fresh; the automatic stage uses the very same
checks. No broker is ever reached: open_position is replaced by a recorder.

Owner decision (2026-10-04): an idea stays good until the close of the NEXT
trading session. An approval made while the market is closed orders nothing
then; it waits for the next market open (09:15-09:20 IST, trading days only),
where every check runs again before anything is bought.

DAY (fixtures) is Monday 6 Jan 2031; the brain's ideas are made at 15:55 IST,
after the close. Unless a test moves it, the clock is Tuesday 10:00 IST: the
market is open and the idea is still good until Tuesday 15:30."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brain_m18_fixtures import DAY, at, brain_strategy, decision, instrument, no_broker, run, signal
from swing_trade_ml.core import holidays
from swing_trade_ml.core.enums import PositionStatus, SignalType
from swing_trade_ml.db.models.brain_golive import BrainApproval, BrainStageChange
from swing_trade_ml.db.models.trading import Order, Position
from swing_trade_ml.services.brain_golive import approvals, shadow, stage
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod
from swing_trade_ml.workers import jobs

HEADERS = {"X-API-Key": "test-api-key"}
TUE = DAY + timedelta(days=1)
WED = DAY + timedelta(days=2)


def _stage(db, name: str) -> None:
    db.add(BrainStageChange(stage=name, previous_stage="shadow", changed_by="test", reason="test"))
    db.flush()


@pytest.fixture()
def fx(db_session, monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: DAY)
    clock = {"now": at(TUE, 10, 0)}
    monkeypatch.setattr(approvals, "_now", lambda: clock["now"])
    monkeypatch.setattr(approvals, "current_mode", lambda: "paper")
    monkeypatch.setattr(approvals, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    verdict = {"v": RiskDecision(True, 12)}
    risk_calls: list[dict] = []
    monkeypatch.setattr(approvals.risk, "check_entry", lambda **kw: risk_calls.append(kw) or verdict["v"])
    live = {"price": 100.0}  # the broker's live price; None = could not get one
    monkeypatch.setattr(approvals, "_live_price", lambda db, inst: live["price"])
    opened: list[tuple[int, int]] = []

    def fake_open(db, strategy, instrument, sig, quantity):
        opened.append((sig.id, quantity))
        return SimpleNamespace(id=None, quantity=quantity, entry_price=sig.price)

    monkeypatch.setattr(approvals, "open_position", fake_open)
    sent: list[str] = []
    monkeypatch.setattr(
        approvals.notifier, "send_sync", lambda text, event="system": sent.append(text) or True
    )
    strategy = brain_strategy(db_session)
    inst = instrument(db_session, "M18APR", 918301)
    run(db_session, "m18-apr")
    dec = decision(db_session, "m18-apr", "M18APR", "TRADE")
    dec.entry_low, dec.entry_high = 98.0, 103.0  # the brain's buy range; the stop is 96
    db_session.flush()
    sig = signal(db_session, strategy, inst, DAY)
    return SimpleNamespace(
        db=db_session,
        strategy=strategy,
        inst=inst,
        decision=dec,
        signal=sig,
        opened=opened,
        sent=sent,
        verdict=verdict,
        clock=clock,
        live=live,
        risk_calls=risk_calls,
    )


def _pending(fx) -> BrainApproval:
    _stage(fx.db, "approval")
    (a,) = approvals.create_pending(fx.db, DAY)
    return a


def _waiting(fx) -> BrainApproval:
    """Approved on Monday evening, after the close: nothing is bought yet."""
    a = _pending(fx)
    fx.clock["now"] = at(DAY, 20, 0)
    approvals.approve(fx.db, a.id, by="owner")
    return a


def _hold(fx) -> None:
    fx.db.add(
        Position(
            strategy_id=fx.strategy.id,
            instrument_id=fx.inst.id,
            mode="paper",
            status=PositionStatus.OPEN,
            quantity=5,
            initial_quantity=5,
            entry_price=100.0,
            entry_at=at(DAY, 10, 0),
            stop_loss=96.0,
            initial_stop_loss=96.0,
            take_profit=108.0,
            highest_price=100.0,
            current_price=100.0,
            total_charges=0.0,
        )
    )
    fx.db.flush()


# ------------------------------------------------------------ creating ideas --


def test_shadow_creates_no_approvals_and_sends_nothing(fx):
    assert approvals.after_scan(fx.db, DAY) == {"created": 0, "approved": 0}
    assert fx.sent == [] and fx.opened == []
    assert fx.db.query(BrainApproval).count() == 0


def test_one_pending_approval_per_safe_brain_buy_of_the_day(fx):
    other = instrument(fx.db, "M18APS", 918302)
    signal(fx.db, fx.strategy, other, DAY, rejection_reason="Sector limit reached")
    signal(fx.db, fx.strategy, other, DAY, signal_type=SignalType.HOLD)
    signal(fx.db, fx.strategy, other, DAY - timedelta(days=1))
    _stage(fx.db, "approval")
    created = approvals.create_pending(fx.db, DAY)
    assert [(a.signal_id, a.symbol, a.status, a.suggested_qty) for a in created] == [
        (fx.signal.id, "M18APR", "pending", 12)
    ]
    assert approvals.create_pending(fx.db, DAY) == []


def test_a_rerun_scan_does_not_create_a_second_approval_for_the_same_stock(fx):
    signal(fx.db, fx.strategy, fx.inst, DAY, hh=17, mm=0)
    _stage(fx.db, "approval")
    assert len(approvals.create_pending(fx.db, DAY)) == 1
    assert fx.db.query(BrainApproval).filter_by(symbol="M18APR").count() == 1


def test_after_scan_announces_with_a_link_to_the_console(fx):
    _stage(fx.db, "approval")
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 0}
    (text,) = fx.sent
    assert (
        "M18APR" in text
        and "/brain#approvals" in text
        and "Nothing is bought until you press Approve" in text
    )
    assert "next trading day" in text


def test_stage_two_never_orders_without_an_approval(fx):
    _stage(fx.db, "approval")
    approvals.after_scan(fx.db, DAY)
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    assert fx.opened == []
    assert fx.db.query(Order).filter_by(strategy_id=fx.strategy.id).count() == 0
    assert fx.db.query(BrainApproval).one().status == "pending"


def test_the_shadow_scan_hands_its_ideas_to_the_approvals_step(fx, monkeypatch):
    seen = MagicMock(return_value={"created": 0, "approved": 0})
    monkeypatch.setattr(approvals, "after_scan", seen)
    monkeypatch.setattr(
        shadow.engine, "run_strategy", lambda db, s, interval: shadow.ScanResult(strategies_run=1)
    )
    shadow.run_brain_strategy(fx.db)
    seen.assert_called_once_with(fx.db, DAY)


def test_a_newer_idea_replaces_an_older_one_still_waiting_for_an_ok(fx, monkeypatch):
    """Tuesday is a holiday, so Monday's idea is still good when Tuesday's
    (holiday) scan makes a new one for the same stock."""
    monkeypatch.setitem(holidays.NSE_HOLIDAYS, 2031, {TUE})
    old = _pending(fx)
    run(fx.db, "m18-apr-2", TUE)
    decision(fx.db, "m18-apr-2", "M18APR", "TRADE")
    newer = signal(fx.db, fx.strategy, fx.inst, TUE)
    fx.clock["now"] = at(TUE, 16, 0)
    (a,) = approvals.create_pending(fx.db, TUE)
    assert a.signal_id == newer.id
    fx.db.refresh(old)
    assert old.status == "expired" and "newer idea" in old.decided_note


def test_an_idea_already_approved_and_waiting_is_not_replaced(fx, monkeypatch):
    monkeypatch.setitem(holidays.NSE_HOLIDAYS, 2031, {TUE})
    old = _waiting(fx)
    run(fx.db, "m18-apr-2", TUE)
    decision(fx.db, "m18-apr-2", "M18APR", "TRADE")
    signal(fx.db, fx.strategy, fx.inst, TUE)
    fx.clock["now"] = at(TUE, 16, 0)
    assert approvals.create_pending(fx.db, TUE) == []
    fx.db.refresh(old)
    assert old.status == "waiting"


# ------------------------------------------------- approving in market hours --


def test_approve_in_market_hours_buys_at_once_through_version_1_with_v1_sizing(fx):
    a = _pending(fx)
    done = approvals.approve(fx.db, a.id, by="owner", note="go")
    assert fx.opened == [(fx.signal.id, 12)]
    assert (done.status, done.decided_by, done.decided_note) == ("approved", "owner", "go")
    assert done.result_note.startswith("Bought 12 shares")


def test_approving_twice_orders_once(fx):
    a = _pending(fx)
    approvals.approve(fx.db, a.id, by="owner")
    with pytest.raises(approvals.ApprovalRefused, match="already approved"):
        approvals.approve(fx.db, a.id, by="owner")
    assert len(fx.opened) == 1


def test_a_tap_that_loses_the_race_orders_nothing(fx, monkeypatch):
    """Another Approve claims the row between this one's checks and its claim."""
    a = _pending(fx)

    def other_tap_wins(**kw):
        fx.db.query(BrainApproval).filter_by(id=a.id).update({"status": "approved"})
        return RiskDecision(True, 12)

    monkeypatch.setattr(approvals.risk, "check_entry", other_tap_wins)
    with pytest.raises(approvals.ApprovalRefused, match="already decided"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_a_failed_order_is_recorded_and_never_retried(fx, monkeypatch):
    a = _pending(fx)

    def broken(*args, **kwargs):
        raise RuntimeError("broker down")

    monkeypatch.setattr(approvals, "open_position", broken)
    with pytest.raises(approvals.ApprovalError, match="may not have been sent"):
        approvals.approve(fx.db, a.id, by="owner")
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "approved" and "broker down" in row.result_note
    assert "check the Orders page" in row.result_note
    with pytest.raises(approvals.ApprovalRefused):
        approvals.approve(fx.db, a.id, by="owner")


def test_approving_just_before_the_close_still_buys(fx):
    a = _pending(fx)
    fx.clock["now"] = at(TUE, 15, 29)
    assert approvals.approve(fx.db, a.id, by="owner").status == "approved"
    assert fx.opened == [(fx.signal.id, 12)]


# --------------------------------------- approving while the market is closed --


def test_an_approval_while_the_market_is_closed_buys_nothing_then(fx):
    a = _pending(fx)
    fx.clock["now"] = at(DAY, 20, 0)
    done = approvals.approve(fx.db, a.id, by="owner", note="tomorrow")
    assert fx.opened == []
    assert (done.status, done.decided_by, done.decided_note) == ("waiting", "owner", "tomorrow")
    assert "market opens" in done.result_note
    assert approvals.approval_out(done)["status_plain"] == "Approved — will be placed when the market opens"
    with pytest.raises(approvals.ApprovalRefused, match="already"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_the_market_open_job_buys_a_waiting_approval_once(fx):
    a = _waiting(fx)
    fx.clock["now"] = at(TUE, 9, 16)
    (done,) = approvals.execute_waiting(fx.db)
    assert done.id == a.id and done.status == "approved" and done.result_note.startswith("Bought 12 shares")
    assert fx.opened == [(fx.signal.id, 12)]
    fx.clock["now"] = at(TUE, 9, 17)
    assert approvals.execute_waiting(fx.db) == []
    assert len(fx.opened) == 1


@pytest.mark.parametrize(
    "when",
    [
        at(DAY, 20, 0),
        at(TUE, 9, 14),
        at(TUE, 9, 20),
        at(TUE, 11, 0),
        at(TUE, 15, 45),
        at(DAY + timedelta(days=5), 9, 16),
    ],
    ids=["evening", "before-open", "after-window", "midday", "after-close", "saturday"],
)
def test_the_market_open_job_does_nothing_outside_the_opening_minutes(fx, when):
    a = _waiting(fx)
    fx.clock["now"] = when
    assert approvals.execute_waiting(fx.db) == []
    assert fx.opened == [] and fx.db.get(BrainApproval, a.id).status == "waiting"


def test_a_holiday_moves_the_buy_and_the_deadline_to_the_next_trading_day(fx, monkeypatch):
    monkeypatch.setitem(holidays.NSE_HOLIDAYS, 2031, {TUE})
    a = _waiting(fx)
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    fx.clock["now"] = at(TUE, 16, 0)
    assert approvals.expire_stale(fx.db) == 0
    fx.clock["now"] = at(WED, 9, 15)
    assert [x.id for x in approvals.execute_waiting(fx.db)] == [a.id]
    assert fx.opened == [(fx.signal.id, 12)]


def test_the_market_open_job_rechecks_that_the_brain_still_says_trade(fx):
    a = _waiting(fx)
    fx.decision.overruled_word = "WATCH"
    fx.decision.overrule_reason = "Results next week"
    fx.db.flush()
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "no longer says TRADE" in row.decided_note and fx.opened == []


def test_the_market_open_job_rechecks_the_safety_check(fx):
    a = _waiting(fx)
    fx.verdict["v"] = RiskDecision(False, 0, "New buying is paused by the safety switch.")
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "paused by the safety switch" in row.decided_note
    assert "Nothing was bought" in row.decided_note and fx.opened == []


def test_the_market_open_job_rechecks_what_is_already_held(fx):
    a = _waiting(fx)
    _hold(fx)
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_the_market_open_job_rechecks_the_broker_mode(fx, monkeypatch):
    a = _waiting(fx)
    monkeypatch.setattr(approvals, "current_mode", lambda: "live")
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_the_market_open_job_buys_nothing_after_a_switch_back_to_practice(fx):
    a = _waiting(fx)
    _stage(fx.db, "shadow")  # a raw row, as if the expiry on rollback had been missed
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == []
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_the_market_open_job_is_scheduled_and_never_raises(monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler

    from swing_trade_ml.workers.scheduler import add_brain_jobs

    s = BackgroundScheduler()
    add_brain_jobs(s)
    job = s.get_job("brain_approvals_open")
    assert job is not None and "9" in str(job.trigger) and "15-19" in str(job.trigger)
    monkeypatch.setattr(approvals, "execute_waiting", MagicMock(side_effect=RuntimeError("x")))
    reported = MagicMock()
    monkeypatch.setattr(jobs, "_report_error", reported)
    jobs.job_brain_approvals_open()
    reported.assert_called_once()


# ------------------------------------------------------------- freshness --


def test_an_idea_past_the_next_sessions_close_cannot_be_approved(fx):
    a = _pending(fx)
    fx.clock["now"] = at(TUE, 15, 31)
    with pytest.raises(approvals.ApprovalExpired, match="close of the next trading day"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_an_idea_the_owner_overruled_after_the_scan_cannot_be_approved(fx):
    a = _pending(fx)
    fx.decision.overruled_word = "WATCH"
    fx.decision.overrule_reason = "Results next week"
    fx.db.flush()
    with pytest.raises(approvals.ApprovalExpired, match="no longer says TRADE"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.db.get(BrainApproval, a.id).status == "expired" and fx.opened == []


def test_a_newer_brain_run_that_drops_the_idea_wins(fx):
    a = _pending(fx)
    run(fx.db, "m18-apr-later", DAY, hh=18, mm=0)
    decision(fx.db, "m18-apr-later", "M18APR", "WAIT", kind="watch")
    with pytest.raises(approvals.ApprovalExpired, match="no longer says TRADE"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_a_stock_already_held_by_the_brain_cannot_be_bought_again(fx):
    a = _pending(fx)
    _hold(fx)
    with pytest.raises(approvals.ApprovalExpired, match="already hold"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_when_the_safety_check_says_no_nothing_is_bought_and_it_stays_pending(fx):
    a = _pending(fx)
    fx.verdict["v"] = RiskDecision(False, 0, "New buying is paused by the safety switch.")
    with pytest.raises(approvals.ApprovalRefused, match="paused by the safety switch"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.db.get(BrainApproval, a.id).status == "pending" and fx.opened == []


def test_approve_in_practice_mode_is_refused(fx):
    a = _pending(fx)
    _stage(fx.db, "shadow")
    with pytest.raises(approvals.ApprovalRefused, match="practice"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_reject_records_why_and_never_orders(fx):
    a = _pending(fx)
    with pytest.raises(approvals.ApprovalRefused, match="Say why"):
        approvals.reject(fx.db, a.id, by="owner", reason=" ")
    done = approvals.reject(fx.db, a.id, by="owner", reason="Too risky this week")
    assert (done.status, done.decided_by, done.decided_note) == ("rejected", "owner", "Too risky this week")
    with pytest.raises(approvals.ApprovalRefused):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_a_waiting_approval_can_still_be_cancelled_with_reject(fx):
    a = _waiting(fx)
    done = approvals.reject(fx.db, a.id, by="owner", reason="Changed my mind")
    assert done.status == "rejected"
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []


def test_ideas_expire_at_the_close_of_the_next_trading_day(fx):
    a = _pending(fx)
    fx.clock["now"] = at(TUE, 15, 0)
    assert approvals.expire_stale(fx.db) == 0
    fx.clock["now"] = at(TUE, 15, 30)
    assert approvals.expire_stale(fx.db) == 1
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "close of the next trading day" in row.decided_note


def test_a_waiting_approval_not_bought_by_the_close_expires_with_a_plain_reason(fx):
    a = _waiting(fx)
    fx.clock["now"] = at(TUE, 15, 31)
    assert approvals.expire_stale(fx.db) == 1
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "Nothing was bought" in row.decided_note


def test_switching_back_to_shadow_expires_pending_and_waiting_ideas(fx, monkeypatch):
    monkeypatch.setattr(stage, "finished_brain_ideas", lambda db: 30)
    stage.set_stage(fx.db, "approval", by="owner", reason="Enough evidence")
    other = instrument(fx.db, "M18APT", 918303)
    decision(fx.db, "m18-apr", "M18APT", "TRADE")
    signal(fx.db, fx.strategy, other, DAY)
    first, second = approvals.create_pending(fx.db, DAY)
    fx.clock["now"] = at(DAY, 20, 0)
    approvals.approve(fx.db, second.id, by="owner")
    stage.set_stage(fx.db, "shadow", by="owner", reason="Back to practice")
    for a in (first, second):
        fx.db.refresh(a)
        assert a.status == "expired" and "practice" in a.decided_note
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []


# -------------------------------------------------------------- automatic --


def test_the_automatic_stage_buys_through_the_same_checks_at_the_next_open(fx):
    _stage(fx.db, "auto")
    fx.clock["now"] = at(DAY, 16, 0)
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 1}
    row = fx.db.query(BrainApproval).one()
    assert (row.status, row.decided_by) == ("waiting", approvals.AUTO_BY)
    assert fx.opened == [] and fx.sent == []
    fx.clock["now"] = at(TUE, 9, 15)
    approvals.execute_waiting(fx.db)
    assert fx.opened == [(fx.signal.id, 12)]


def test_the_automatic_stage_skips_an_overruled_idea(fx):
    fx.decision.overruled_word = "WAIT"
    fx.db.flush()
    _stage(fx.db, "auto")
    assert approvals.after_scan(fx.db, DAY) == {"created": 1, "approved": 0}
    assert fx.opened == []


def test_switching_from_automatic_to_approval_hands_automatic_oks_back_to_the_owner(fx, monkeypatch):
    monkeypatch.setattr(stage, "finished_brain_ideas", lambda db: 30)
    _stage(fx.db, "approval")
    stage.set_stage(fx.db, "auto", by="owner", reason="Trust it")
    fx.clock["now"] = at(DAY, 16, 0)
    approvals.after_scan(fx.db, DAY)
    row = fx.db.query(BrainApproval).one()
    assert row.status == "waiting"
    stage.set_stage(fx.db, "approval", by="owner", reason="Back to asking me")
    fx.db.refresh(row)
    assert row.status == "pending" and row.decided_by is None and "your OK" in row.result_note
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []


def test_the_market_open_job_never_acts_on_an_automatic_ok_outside_the_automatic_stage(fx):
    _stage(fx.db, "auto")
    fx.clock["now"] = at(DAY, 16, 0)
    approvals.after_scan(fx.db, DAY)
    _stage(fx.db, "approval")  # a raw row, as if the hand-back on the switch had been missed
    fx.clock["now"] = at(TUE, 9, 16)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []
    assert fx.db.query(BrainApproval).one().status == "expired"


def test_an_unknown_stage_counts_as_practice_and_buys_nothing(fx, monkeypatch):
    a = _pending(fx)
    monkeypatch.setattr(approvals, "current_stage", lambda db: "garbage")
    assert approvals.create_pending(fx.db, DAY) == []
    with pytest.raises(approvals.ApprovalRefused, match="practice"):
        approvals.approve(fx.db, a.id, by="owner")
    assert approvals.auto_approve(fx.db, DAY) == [] and fx.opened == []


def test_the_approval_stage_never_presses_approve_by_itself(fx):
    a = _pending(fx)
    assert approvals.auto_approve(fx.db, DAY) == []
    assert fx.db.get(BrainApproval, a.id).status == "pending" and fx.opened == []


# -------------------------------------------------------------- endpoints --


def test_approval_endpoints(fx, client):
    a = _pending(fx)
    listed = client.get("/api/v1/brain/approvals", params={"status": "pending"}, headers=HEADERS).json()
    assert [x["id"] for x in listed] == [a.id] and listed[0]["symbol"] == "M18APR"
    assert listed[0]["valid_until"].startswith(TUE.isoformat())
    r = client.post(f"/api/v1/brain/approvals/{a.id}/approve", json={"note": "ok"}, headers=HEADERS)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.post(f"/api/v1/brain/approvals/{a.id}/approve", json={}, headers=HEADERS).status_code == 409
    assert (
        client.post("/api/v1/brain/approvals/999999999/approve", json={}, headers=HEADERS).status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/brain/approvals/{a.id}/reject", json={"reason": " "}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/brain/approvals", params={"status": "nonsense"}, headers=HEADERS).status_code
        == 422
    )
    waiting = client.get("/api/v1/brain/approvals", params={"status": "waiting"}, headers=HEADERS)
    assert waiting.status_code == 200 and waiting.json() == []


def test_valid_until_is_the_close_of_the_next_trading_day(monkeypatch):
    friday = DAY + timedelta(days=4)
    assert approvals.valid_until(friday) == at(DAY + timedelta(days=7), 15, 30)
    monkeypatch.setitem(holidays.NSE_HOLIDAYS, 2031, {TUE})
    assert approvals.valid_until(DAY) == at(WED, 15, 30)
    assert isinstance(approvals.valid_until(DAY), datetime)


# ------------------------------------------------- fix round 1: live price --


@pytest.mark.parametrize(
    ("price", "words"),
    [(97.0, "outside the brain's buy range"), (104.5, "outside the brain's buy range")],
    ids=["gap-below-the-range", "gap-above-the-range"],
)
def test_the_market_open_job_buys_nothing_when_the_open_price_is_outside_the_range(fx, price, words):
    a = _waiting(fx)
    fx.live["price"] = price
    fx.clock["now"] = at(TUE, 9, 15)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and words in row.decided_note and f"₹{price:,.2f}" in row.decided_note
    assert "₹98.00 to ₹103.00" in row.decided_note
    assert row.decided_note.lower().count("nothing was bought") == 1


def test_the_market_open_job_buys_inside_the_range_sized_on_the_live_price(fx):
    a = _waiting(fx)
    fx.live["price"] = 101.5
    fx.clock["now"] = at(TUE, 9, 15)
    assert [x.id for x in approvals.execute_waiting(fx.db)] == [a.id]
    assert fx.opened == [(fx.signal.id, 12)]
    assert fx.risk_calls[-1]["price"] == 101.5


def test_the_market_open_job_buys_nothing_without_a_live_price(fx):
    a = _waiting(fx)
    fx.live["price"] = None
    fx.clock["now"] = at(TUE, 9, 15)
    assert approvals.execute_waiting(fx.db) == [] and fx.opened == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "Could not get a live price" in row.decided_note


def test_a_live_price_at_or_below_the_stop_buys_nothing(fx):
    fx.decision.entry_low = 90.0  # even if the brain's range reached below its stop
    fx.db.flush()
    a = _pending(fx)
    fx.live["price"] = 96.0
    with pytest.raises(approvals.ApprovalExpired, match="stop"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == [] and fx.db.get(BrainApproval, a.id).status == "expired"


def test_an_in_session_approve_outside_the_range_buys_nothing(fx):
    a = _pending(fx)
    fx.live["price"] = 110.0
    with pytest.raises(approvals.ApprovalExpired, match="outside the brain's buy range"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []


def test_an_approve_while_closed_does_not_need_a_live_price(fx):
    fx.live["price"] = None
    assert _waiting(fx).status == "waiting" and fx.opened == []


def test_a_switch_to_practice_while_an_order_is_in_flight_orders_nothing(fx, monkeypatch):
    a = _pending(fx)

    def rollback_lands(**kw):
        _stage(fx.db, "shadow")  # lands after the checks, before the order
        return RiskDecision(True, 12)

    monkeypatch.setattr(approvals.risk, "check_entry", rollback_lands)
    with pytest.raises(approvals.ApprovalError, match="practice"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []
    row = fx.db.get(BrainApproval, a.id)
    assert row.status == "expired" and "Nothing was bought" in row.decided_note


def test_an_order_still_waiting_to_fill_reads_as_normal(fx, monkeypatch):
    a = _pending(fx)
    monkeypatch.setattr(approvals, "open_position", lambda *args, **kw: None)
    monkeypatch.setattr(approvals, "_order_status", lambda db, sig: "PENDING")
    done = approvals.approve(fx.db, a.id, by="owner")
    assert done.result_note == "Order sent; it will show as a position once it fills."


def test_a_waiting_approval_expired_by_the_clock_is_reported_on_telegram(fx):
    _waiting(fx)
    fx.sent.clear()
    fx.clock["now"] = at(TUE, 15, 31)
    assert approvals.expire_stale(fx.db) == 1
    (text,) = fx.sent
    assert "M18APR" in text and "Nothing was bought" in text
    assert approvals.expire_stale(fx.db) == 0 and len(fx.sent) == 1


def test_a_pending_idea_expiring_sends_nothing(fx):
    _pending(fx)
    fx.clock["now"] = at(TUE, 15, 31)
    assert approvals.expire_stale(fx.db) == 1 and fx.sent == []


# ------------------------------------------------------------ fix round 2 --


class _Broker:
    def __init__(self, result):
        self.result = result

    def get_ltp(self, keys, db):
        if isinstance(self.result, Exception):
            raise self.result
        return {keys[0]: self.result} if self.result != "missing" else {}


@pytest.mark.parametrize(
    "result",
    [RuntimeError("no session"), "missing", 0, 0.0, -5.0, float("nan"), None],
    ids=["raises", "empty", "zero", "zero-float", "negative", "nan", "none"],
)
def test_live_price_gives_none_when_there_is_no_usable_price(monkeypatch, result):
    monkeypatch.setattr(approvals, "get_broker", lambda: _Broker(result))
    inst = SimpleNamespace(symbol_key="NSE:M18X", tradingsymbol="M18X")
    assert approvals._live_price(None, inst) is None


def test_live_price_gives_the_brokers_price_as_a_float(monkeypatch):
    monkeypatch.setattr(approvals, "get_broker", lambda: _Broker(101))
    inst = SimpleNamespace(symbol_key="NSE:M18X", tradingsymbol="M18X")
    got = approvals._live_price(None, inst)
    assert got == 101.0 and isinstance(got, float)


@pytest.mark.parametrize("price", [98.0, 103.0], ids=["exactly-the-bottom", "exactly-the-top"])
def test_a_live_price_on_the_edge_of_the_range_still_buys(fx, price):
    a = _pending(fx)
    fx.live["price"] = price
    assert approvals.approve(fx.db, a.id, by="owner").status == "approved"
    assert fx.opened == [(fx.signal.id, 12)] and fx.risk_calls[-1]["price"] == price


def test_a_live_price_exactly_at_the_stop_is_refused(fx):
    fx.decision.entry_low = 96.0  # the range starts at the stop itself
    fx.db.flush()
    a = _pending(fx)
    fx.live["price"] = 96.0
    with pytest.raises(approvals.ApprovalExpired, match="at or below the stop"):
        approvals.approve(fx.db, a.id, by="owner")
    assert fx.opened == []
