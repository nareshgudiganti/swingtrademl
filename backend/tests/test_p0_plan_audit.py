from __future__ import annotations

from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.session import User

API_KEY = {"X-API-Key": "test-api-key"}


def test_plan_change_and_switch_are_audited(client, db_session):
    user = User(username="pa1", hashed_password="x", plan="free")
    db_session.add(user)
    db_session.flush()
    client.put(f"/api/v1/admin/users/{user.id}/plan", json={"plan": "pro"}, headers=API_KEY)
    client.put("/api/v1/admin/switch", json={"enabled": False}, headers=API_KEY)
    rows = {
        a.action: a
        for a in db_session.query(AuditLog).filter(AuditLog.action.in_(["user.plan_change", "plans.switch"]))
    }
    assert rows["user.plan_change"].before == {"plan": "free"} and rows["user.plan_change"].after == {
        "plan": "pro"
    }
    assert rows["user.plan_change"].actor_label == "api-key"
    assert rows["plans.switch"].after == {"enabled": False}
