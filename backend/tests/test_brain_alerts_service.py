"""Sending brain alerts: told once a day, only what was really sent is
recorded, never for replays, and reachable from the API and the jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.brain.alerts import service
from swing_trade_ml.core.config import Settings
from swing_trade_ml.db.models.brain import BrainAlert, BrainDecision, BrainRun

HEADERS = {"X-API-Key": "test-api-key"}
T0 = datetime(2026, 10, 1, 10, 20, tzinfo=UTC)  # 15:50 IST


def _run(db, run_id, *, when=T0, live=True, kind="nightly", mode="DEFENSIVE", decisions=()):
    db.add(
        BrainRun(
            id=run_id,
            kind=kind,
            as_of=when,
            book="paper",
            live=live,
            started_at=when,
            status="done",
            banner_mode=mode,
            banner_headline="NIFTY is in a down-trend.",
        )
    )
    db.flush()
    for symbol, kind_, word in decisions:
        db.add(
            BrainDecision(
                run_id=run_id,
                symbol=symbol,
                kind=kind_,
                word=word,
                reasons=[f"{symbol} reason."],
                qty=10,
                entry_low=99.0,
                entry_high=101.0,
                target=108.0,
                stop=96.0,
            )
        )
    db.commit()


class Sender:
    def __init__(self, ok=True):
        self.ok, self.texts = ok, []

    def __call__(self, text):
        self.texts.append(text)
        return self.ok


def test_preview_lists_what_changed(db_session):
    _run(db_session, "al-1", decisions=[("ABC", "idea", "TRADE"), ("HLD", "holding", "MONITOR")])
    preview = service.preview(db_session, "al-1")
    assert {i["key"] for i in preview["items"]} == {"banner:DEFENSIVE", "trade:ABC", "holding:HLD:MONITOR"}
    assert "TradeMind brain" in preview["text"]


def test_sending_records_and_the_same_day_is_not_repeated(db_session):
    _run(db_session, "al-2", decisions=[("ABC", "idea", "TRADE")])
    sender = Sender()
    first = service.send(db_session, "al-2", sender=sender)
    assert first["sent"] and first["count"] == 2
    assert db_session.query(BrainAlert).filter_by(alert_key="trade:ABC").count() == 1
    # A later run the same day where ABC flipped away and back is still not re-told.
    _run(db_session, "al-3", when=T0 + timedelta(hours=1), decisions=[("ABC", "idea", "WAIT")])
    _run(db_session, "al-4", when=T0 + timedelta(hours=2), decisions=[("ABC", "idea", "TRADE")])
    assert all(i.key != "trade:ABC" for i in service.pending(db_session, "al-4"))


def test_nothing_is_recorded_when_telegram_did_not_send(db_session):
    _run(db_session, "al-5", decisions=[("ABC", "idea", "TRADE")])
    result = service.send(db_session, "al-5", sender=Sender(ok=False))
    assert not result["sent"]
    assert db_session.query(BrainAlert).count() == 0


def test_nothing_new_sends_nothing(db_session):
    _run(db_session, "al-6", decisions=[("ABC", "idea", "WAIT")])
    _run(db_session, "al-7", when=T0 + timedelta(minutes=15), decisions=[("ABC", "idea", "WAIT")])
    service.send(db_session, "al-6", sender=Sender())
    sender = Sender()
    assert service.send(db_session, "al-7", sender=sender) == {"sent": False, "count": 0, "text": None}
    assert sender.texts == []


def test_replays_and_why_runs_never_alert(db_session):
    _run(db_session, "al-8", live=False, decisions=[("ABC", "idea", "TRADE")])
    _run(db_session, "al-9", kind="why", decisions=[("ABC", "idea", "TRADE")])
    assert service.pending(db_session, "al-8") == []
    assert service.pending(db_session, "al-9") == []


def test_the_previous_run_is_the_same_kind_and_live(db_session):
    _run(db_session, "al-10", mode="DEFENSIVE")
    _run(db_session, "al-11", when=T0 + timedelta(minutes=5), live=False, mode="NORMAL")  # replay: ignored
    _run(db_session, "al-12", when=T0 + timedelta(minutes=10), mode="DEFENSIVE")
    # Nothing was sent, so de-duplication cannot hide a wrong "previous run":
    # compared with the replay (NORMAL) the banner would look changed.
    assert all(not i.key.startswith("banner") for i in service.pending(db_session, "al-12"))


def test_api_preview_and_send(client, db_session, monkeypatch):
    _run(db_session, "al-13", decisions=[("ABC", "idea", "TRADE")])
    sender = Sender()
    monkeypatch.setattr(service, "default_sender", lambda: sender)
    preview = client.get("/api/v1/brain/runs/al-13/alerts", headers=HEADERS).json()
    assert preview["items"]
    sent = client.post("/api/v1/brain/runs/al-13/alerts/send", headers=HEADERS).json()
    assert sent["sent"] and sender.texts


def test_alerts_are_off_by_default():
    assert Settings(API_KEY="x", JWT_SECRET_KEY="x").BRAIN_ALERTS_ENABLED is False
