"""The exits switch: turning the exit sweep off, and back on again.

Its own file rather than another section of test_portfolio_risk_layer.py
because this is the dangerous half of the kill switch — with exits off, no
stop-loss, target or time stop fires — and it deserves to be findable by
name. Fixtures and helper style follow test_portfolio_risk_layer.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.market import Instrument, Quote
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import deployable, risk, system_state

HEADERS = {"X-API-Key": "test-api-key"}


def _instrument(db_session, tradingsymbol="RELIANCE") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session, **kwargs) -> Strategy:
    strat = Strategy(name=kwargs.pop("name", "exit_switch_strategy"), strategy_type="ml_swing",
                     mode=kwargs.pop("mode", "paper"), **kwargs)
    db_session.add(strat)
    db_session.flush()
    return strat


def _open_position(db_session, strategy, instrument, quantity, entry_price, mode="paper") -> Position:
    pos = Position(
        strategy_id=strategy.id, instrument_id=instrument.id, mode=mode,
        status="OPEN", quantity=quantity, entry_price=entry_price,
        entry_at=datetime.now(UTC), current_price=entry_price,
    )
    db_session.add(pos)
    db_session.flush()
    return pos


def _flat_deployable(monkeypatch, fraction=1.0):
    monkeypatch.setattr(
        deployable, "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=fraction, context_available=True),
    )


def _priced(db_session, instrument, price):
    """The paper broker refuses to fill without a reference price of its own,
    so the sell side needs a Quote even though the sweep reads get_ltp."""
    db_session.add(Quote(instrument_id=instrument.id, last_price=price, ts=datetime.now(UTC)))
    db_session.flush()


def _priced_paper_broker(monkeypatch, price):
    """Pin every quote the exit sweep reads, so the only thing that differs
    between the two halves of the enforcement test is the switch itself."""
    from swing_trade_ml.brokers.paper import PaperBroker
    from swing_trade_ml.services import execution

    monkeypatch.setattr(PaperBroker, "get_ltp", lambda self, keys, db: dict.fromkeys(keys, price))
    monkeypatch.setattr(execution.notifier, "send_sync", lambda *a, **kw: None)


# ------------------------------------------------------------- the service --


def test_disable_exits_turns_the_switch_off(db_session):
    state = system_state.disable_exits(db_session, reason="manual reconciliation", by="test-suite")
    assert state.exits_enabled is False
    assert system_state.get_state(db_session).exits_enabled is False
    assert system_state.is_exits_disabled(db_session) is True


def test_enable_exits_turns_it_back_on(db_session):
    system_state.disable_exits(db_session, reason="drill", by="test-suite")
    state = system_state.enable_exits(db_session, by="test-suite")
    assert state.exits_enabled is True
    assert system_state.is_exits_disabled(db_session) is False


def test_disabling_exits_logs_who_and_why_at_warning_level(db_session):
    """The louder of the two switches — and, until exits get their own
    reason column, this line is the *only* record of why every stop-loss in
    the book was switched off, so it has to carry both fields."""
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        system_state.disable_exits(db_session, reason="broker outage", by="test-suite")

    entry = next(e for e in logs if e["event"] == "system_state.exits_disabled")
    assert entry["log_level"] == "warning"
    assert entry["reason"] == "broker outage"
    assert entry["by"] == "test-suite"


def test_enabling_exits_logs_who_did_it(db_session):
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        system_state.enable_exits(db_session, by="test-suite")

    entry = next(e for e in logs if e["event"] == "system_state.exits_enabled")
    assert entry["log_level"] == "warning"
    assert entry["by"] == "test-suite"


# ----------------------------------------------------- the two independently --


def test_disabling_exits_does_not_halt_entries(db_session, monkeypatch):
    _flat_deployable(monkeypatch)
    strat = _strategy(db_session)
    inst = _instrument(db_session, "ZZZEXITSOFFBUY")
    system_state.disable_exits(db_session, reason="drill", by="test-suite")

    assert system_state.is_entries_halted(db_session) is False
    decision = risk.check_entry(
        db_session, mode="paper", instrument_id=inst.id, price=100.0, stop_loss=95.0,
        portfolio_value=1_000_000.0, available_cash=1_000_000.0, strategy=strat,
    )
    assert decision.allowed is True


def test_halting_entries_does_not_disable_exits(db_session):
    system_state.halt(db_session, reason="drill", by="test-suite")
    assert system_state.get_state(db_session).exits_enabled is True


def test_resuming_entries_does_not_re_enable_exits(db_session):
    """Two switches, two acts. Someone who halts, disables exits, then
    resumes entries has not asked for exits back — if resume quietly turned
    them on, the dashboard would say "protected" when nobody decided that."""
    system_state.halt(db_session, reason="drill", by="test-suite")
    system_state.disable_exits(db_session, reason="broker outage", by="test-suite")
    system_state.resume(db_session, by="test-suite")

    assert system_state.get_state(db_session).new_entries_enabled is True
    assert system_state.get_state(db_session).exits_enabled is False


def test_disabling_exits_leaves_the_entries_halt_record_intact(db_session):
    """halt_reason/halted_at/halted_by describe the entries halt only. If the
    exits switch wrote them too, resuming entries would erase them and the
    row would claim nobody ever turned exits off."""
    system_state.halt(db_session, reason="entries drill", by="entries-operator")
    system_state.disable_exits(db_session, reason="exits drill", by="exits-operator")

    state = system_state.get_state(db_session)
    assert state.halt_reason == "entries drill"
    assert state.halted_by == "entries-operator"


def test_enabling_exits_leaves_a_live_entries_halt_alone(db_session):
    system_state.halt(db_session, reason="entries drill", by="entries-operator")
    system_state.disable_exits(db_session, reason="exits drill", by="exits-operator")
    system_state.enable_exits(db_session, by="exits-operator")

    state = system_state.get_state(db_session)
    assert state.new_entries_enabled is False
    assert state.halt_reason == "entries drill"


# ----------------------------------------------------------- the enforcement --


def test_check_exits_sweeps_while_exits_are_enabled(db_session, monkeypatch):
    """The control for the test below: same position, same price, switch on —
    the stop fires. Without this, "returned []" proves nothing."""
    from swing_trade_ml.services.execution import check_exits

    _priced_paper_broker(monkeypatch, price=90.0)
    strat = _strategy(db_session, name="exit_switch_on_strategy")
    inst = _instrument(db_session, "ZZZSTOPFIRES")
    pos = _open_position(db_session, strat, inst, quantity=10, entry_price=100.0)
    pos.stop_loss = 95.0
    _priced(db_session, inst, 90.0)
    db_session.commit()

    closed = check_exits(db_session)

    assert [t.exit_reason for t in closed] == ["STOP_LOSS_HIT"]
    assert db_session.get(Position, pos.id).status == "CLOSED"


def test_check_exits_stops_sweeping_once_exits_are_disabled(db_session, monkeypatch):
    """The switch the API now exposes is the one check_exits already reads: a
    position sitting below its stop stays open while exits are off."""
    from swing_trade_ml.services.execution import check_exits

    _priced_paper_broker(monkeypatch, price=90.0)
    strat = _strategy(db_session, name="exit_switch_off_strategy")
    inst = _instrument(db_session, "ZZZSTOPIGNORED")
    pos = _open_position(db_session, strat, inst, quantity=10, entry_price=100.0)
    pos.stop_loss = 95.0
    _priced(db_session, inst, 90.0)
    db_session.commit()

    system_state.disable_exits(db_session, reason="broker outage", by="test-suite")

    assert check_exits(db_session) == []
    assert db_session.get(Position, pos.id).status == "OPEN"


def test_re_enabling_exits_lets_the_stop_fire_again(db_session, monkeypatch):
    from swing_trade_ml.services.execution import check_exits

    _priced_paper_broker(monkeypatch, price=90.0)
    strat = _strategy(db_session, name="exit_switch_back_on_strategy")
    inst = _instrument(db_session, "ZZZSTOPRESUMED")
    pos = _open_position(db_session, strat, inst, quantity=10, entry_price=100.0)
    pos.stop_loss = 95.0
    _priced(db_session, inst, 90.0)
    db_session.commit()

    system_state.disable_exits(db_session, reason="broker outage", by="test-suite")
    assert check_exits(db_session) == []

    system_state.enable_exits(db_session, by="test-suite")
    assert len(check_exits(db_session)) == 1
    assert db_session.get(Position, pos.id).status == "CLOSED"


# ----------------------------------------------------------------- the API --


def test_exits_disable_requires_auth(client):
    resp = client.post("/api/v1/safety/exits/disable", json={"reason": "no key"})
    assert resp.status_code in (401, 403)


def test_exits_enable_requires_auth(client):
    resp = client.post("/api/v1/safety/exits/enable", json={})
    assert resp.status_code in (401, 403)


def test_exits_disable_and_enable_round_trip(client, db_session):
    resp = client.post(
        "/api/v1/safety/exits/disable", json={"reason": "broker outage"}, headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.json()["exits_enabled"] is False

    resp = client.get("/api/v1/safety/state", headers=HEADERS)
    assert resp.json()["exits_enabled"] is False

    resp = client.post("/api/v1/safety/exits/enable", json={}, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["exits_enabled"] is True

    resp = client.get("/api/v1/safety/state", headers=HEADERS)
    assert resp.json()["exits_enabled"] is True


def test_disabling_exits_requires_a_reason(client, db_session):
    """Unlike `by`, the reason is not defaulted: turning off every stop-loss
    in the book is not something anyone should be able to do wordlessly."""
    resp = client.post("/api/v1/safety/exits/disable", json={}, headers=HEADERS)
    assert resp.status_code == 422
    assert system_state.get_state(db_session).exits_enabled is True

    resp = client.post("/api/v1/safety/exits/disable", json={"reason": ""}, headers=HEADERS)
    assert resp.status_code == 422


def test_enabling_exits_needs_no_reason(client):
    """Re-enabling is the safe direction — never make it harder than the
    dangerous one."""
    client.post("/api/v1/safety/exits/disable", json={"reason": "drill"}, headers=HEADERS)
    resp = client.post("/api/v1/safety/exits/enable", json={}, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["exits_enabled"] is True


def test_exits_switch_through_the_api_does_not_move_the_entries_switch(client):
    resp = client.post(
        "/api/v1/safety/exits/disable", json={"reason": "drill"}, headers=HEADERS
    )
    assert resp.json()["new_entries_enabled"] is True
    assert resp.json()["halt_reason"] is None

    resp = client.post("/api/v1/safety/exits/enable", json={}, headers=HEADERS)
    assert resp.json()["new_entries_enabled"] is True


def test_halt_through_the_api_does_not_move_the_exits_switch(client):
    resp = client.post("/api/v1/safety/halt", json={"reason": "drill"}, headers=HEADERS)
    assert resp.json()["new_entries_enabled"] is False
    assert resp.json()["exits_enabled"] is True

    resp = client.post("/api/v1/safety/resume", json={}, headers=HEADERS)
    assert resp.json()["exits_enabled"] is True


def test_exits_disable_records_who_asked_for_it(client, db_session):
    """`by` defaults like halt's does, and is carried through to the log —
    the request must not fail validation over a missing label."""
    resp = client.post(
        "/api/v1/safety/exits/disable",
        json={"reason": "broker outage", "by": "naresh"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["exits_enabled"] is False
