"""oa8: the top-bar bell reads what the brain really told the owner (brain_alerts), newest first.
Reading only: the endpoint never writes, and a tester is refused like the rest of the alerts area."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from swing_trade_ml.api.deps import PRIVATE_AREA
from swing_trade_ml.brain.alerts import service
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainAlert
from swing_trade_ml.db.models.session import User

HEADERS = {"X-API-Key": "test-api-key"}
T0 = datetime(2026, 10, 20, 10, 20, tzinfo=UTC)


def _alert(db, key, when, kind="trade", text=None):
    db.add(
        BrainAlert(
            alert_key=key,
            alert_date=when.date(),
            kind=kind,
            text=text or f"{key} happened.",
            channel="telegram",
            sent_at=when,
        )
    )
    db.commit()


def test_recent_is_newest_first_and_limited(db_session):
    for i in range(5):
        _alert(db_session, f"trade:S{i}", T0 + timedelta(hours=i))
    rows = service.recent(db_session, limit=3)
    assert [r["text"] for r in rows] == ["trade:S4 happened.", "trade:S3 happened.", "trade:S2 happened."]
    assert set(rows[0]) == {"id", "kind", "text", "alert_date", "sent_at", "channel"}
    assert rows[0]["alert_date"] == date(2026, 10, 20)


def test_api_lists_recent_alerts_and_writes_nothing(client, db_session):
    _alert(db_session, "banner:DEFENSIVE", T0, kind="banner", text="Market mode is now DEFENSIVE.")
    _alert(db_session, "holding:TCS:EXIT", T0 + timedelta(minutes=5), kind="holding", text="TCS: EXIT.")
    before = db_session.query(BrainAlert).count()
    r = client.get("/api/v1/brain/alerts?limit=10", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert [a["text"] for a in body] == ["TCS: EXIT.", "Market mode is now DEFENSIVE."]
    assert body[0]["kind"] == "holding"
    assert db_session.query(BrainAlert).count() == before


def test_api_limit_is_bounded(client):
    assert client.get("/api/v1/brain/alerts?limit=0", headers=HEADERS).status_code == 422
    assert client.get("/api/v1/brain/alerts?limit=51", headers=HEADERS).status_code == 422


def test_a_tester_cannot_read_the_owners_alerts(client, db_session):
    user = User(username="oa8-tester", hashed_password="x", is_active=True, role="tester", plan="free")
    db_session.add(user)
    db_session.flush()
    token = create_access_token(user.username, {"uid": user.id})
    r = client.get("/api/v1/brain/alerts", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["detail"] == PRIVATE_AREA
