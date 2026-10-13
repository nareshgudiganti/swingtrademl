"""F-17: with the plans switch off (as on prod) every signed-in account used to be "unrestricted", so a
non-owner could change the trading stage, approve a buy or pull the safety switches. Every change now
needs the owner (or the API key), whether plans are on or off. Reading is unchanged. Stage changes and
approvals record who really made them, not a name sent in the request."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services.brain_golive import stage

API_KEY = {"X-API-Key": "test-api-key"}


def _login(db_session, username: str, *, owner: bool = False) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, is_superuser=owner, plan="free")
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_a_non_owner_cannot_change_the_stage(client, db_session):
    guest = _login(db_session, "guest1")
    r = client.put("/api/v1/brain/stage", json={"stage": "shadow", "reason": "x"}, headers=guest)
    assert r.status_code == 403


def test_a_non_owner_cannot_approve_or_reject_a_buy(client, db_session):
    guest = _login(db_session, "guest2")
    assert client.post("/api/v1/brain/approvals/1/approve", json={}, headers=guest).status_code == 403
    rejected = client.post("/api/v1/brain/approvals/1/reject", json={"reason": "no"}, headers=guest)
    assert rejected.status_code == 403


def test_a_non_owner_cannot_use_the_safety_switches_or_strategies(client, db_session):
    guest = _login(db_session, "guest3")
    assert client.post("/api/v1/safety/halt", json={"reason": "x"}, headers=guest).status_code == 403
    assert client.post("/api/v1/safety/exits/disable", json={}, headers=guest).status_code == 403
    assert client.post("/api/v1/strategies/1/activate", headers=guest).status_code == 403


def test_a_non_owner_can_still_read_while_plans_are_off(client, db_session):
    guest = _login(db_session, "guest4")
    assert client.get("/api/v1/brain/stage", headers=guest).status_code == 200
    assert client.get("/api/v1/strategies", headers=guest).status_code == 200


def test_the_owner_and_the_api_key_still_get_through(client, db_session):
    boss = _login(db_session, "boss1", owner=True)
    # Already in practice: the stage service refuses (409), which proves the request got past the guard.
    for headers in (boss, API_KEY):
        r = client.put("/api/v1/brain/stage", json={"stage": "shadow", "reason": "x"}, headers=headers)
        assert r.status_code == 409


def test_a_stage_change_records_who_really_made_it(client, db_session):
    boss = _login(db_session, "boss2", owner=True)
    db_session.add(
        BrainStageChange(
            stage="approval", previous_stage="shadow", changed_by="owner", reason="r",
            changed_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        )
    )
    db_session.flush()
    r = client.put(
        "/api/v1/brain/stage", json={"stage": "shadow", "reason": "back", "by": "someone-else"}, headers=boss
    )
    assert r.status_code == 200
    assert stage.current_stage(db_session) == "shadow"
    latest = db_session.execute(
        select(BrainStageChange).order_by(BrainStageChange.id.desc()).limit(1)
    ).scalar_one()
    assert latest.changed_by == "boss2"
