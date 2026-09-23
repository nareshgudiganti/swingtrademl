"""The daily scan has to say why it bought nothing.

check_entry has always written a RiskEvent per refused entry, but nothing read
them back: a scan that found candidates and took none reported `executed: 0`
and stopped there. That is how a week of blocked entries came to look exactly
like a week of quiet markets.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.safety import RiskEvent
from swing_trade_ml.workers import jobs


def _use_test_session(monkeypatch, db_session) -> None:
    """job_signal_scan opens its own session; hand it this test's instead so
    the rolled-back transaction still applies."""

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)


def _event(db_session, rule: str, reason: str, *, minutes_ago: int = 1) -> None:
    db_session.add(
        RiskEvent(
            ts=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            mode="paper",
            rule=rule,
            reason=reason,
        )
    )


def test_blocked_entries_are_grouped_commonest_first(db_session):
    since = datetime.now(UTC) - timedelta(hours=1)
    for _ in range(3):
        _event(db_session, "POSITION_LIMIT", "You already hold 40 positions")
    _event(db_session, "DEPLOYABLE", "The market looks under stress right now")
    db_session.commit()

    blocked = jobs._blocked_entries(db_session, since)

    assert [b["rule"] for b in blocked] == ["POSITION_LIMIT", "DEPLOYABLE"]
    assert blocked[0]["count"] == 3
    assert blocked[0]["reason"] == "You already hold 40 positions"


def test_refusals_from_before_this_scan_are_ignored(db_session):
    _event(db_session, "POSITION_LIMIT", "yesterday's refusal", minutes_ago=2000)
    db_session.commit()

    assert jobs._blocked_entries(db_session, datetime.now(UTC) - timedelta(hours=1)) == []


def test_alert_quotes_the_risk_layers_own_wording(db_session):
    """The reason the user reads must be the one the limit actually applied,
    not a second copy written here that could drift from it."""
    message = jobs._blocked_entries_message(
        [
            {"rule": "POSITION_LIMIT", "count": 40, "reason": "You already hold 40 positions"},
            {"rule": "DEPLOYABLE", "count": 2, "reason": "The market looks under stress"},
        ]
    )

    assert "40" in message
    assert "You already hold 40 positions" in message
    assert "The market looks under stress" in message


def test_alert_fires_when_candidates_were_refused_and_nothing_bought(db_session, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda text, event=None: sent.append(text) or True)

    class _Result:
        strategies_run = 1
        instruments_evaluated = 10
        signals_generated = 5
        buys = 5
        exits = 0
        executed = 0
        errors = ()  # only len() and truthiness are read here

    _use_test_session(monkeypatch, db_session)
    monkeypatch.setattr(jobs.engine, "run_all_active", lambda db, interval="day": _Result())
    monkeypatch.setattr(
        jobs, "_blocked_entries",
        lambda db, since: [{"rule": "POSITION_LIMIT", "count": 5, "reason": "You already hold 40 positions"}],
    )
    monkeypatch.setattr(jobs.heartbeat, "write_last_scan", lambda data: None)

    jobs.job_signal_scan()

    assert len(sent) == 1
    assert "You already hold 40 positions" in sent[0]


def test_no_alert_when_a_buy_went_through(db_session, monkeypatch):
    """A partly-blocked scan that still bought something is working as
    designed — alerting on it would nag daily and train the alert to be
    ignored before the day it matters."""
    sent: list[str] = []
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda text, event=None: sent.append(text) or True)

    class _Result:
        strategies_run = 1
        instruments_evaluated = 10
        signals_generated = 5
        buys = 5
        exits = 0
        executed = 1
        errors = ()  # only len() and truthiness are read here

    _use_test_session(monkeypatch, db_session)
    monkeypatch.setattr(jobs.engine, "run_all_active", lambda db, interval="day": _Result())
    monkeypatch.setattr(
        jobs, "_blocked_entries",
        lambda db, since: [{"rule": "SECTOR_CAP", "count": 4, "reason": "Financial services is full"}],
    )
    monkeypatch.setattr(jobs.heartbeat, "write_last_scan", lambda data: None)

    jobs.job_signal_scan()

    assert sent == []
