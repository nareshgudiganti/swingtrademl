"""Admin console: two-step sign-in and the admin-only users API (scratch test database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.admin_mfa import AdminMfa, AdminRecoveryCode
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.billing import PlanGrant
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import admin_mfa as mfa_service

API_KEY = {"X-API-Key": "test-api-key"}


def make_user(db, name, *, role="member", plan="free"):
    u = User(username=name, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(u)
    db.flush()
    return u, {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def totp_for(secret: str, *, offset: int = 0) -> str:
    return pyotp.TOTP(secret).at(datetime.now(UTC) + timedelta(seconds=30 * offset))


def enrol(client, db, name="boss"):
    admin, hdr = make_user(db, name, role="owner")
    secret = client.post("/api/v1/admin/mfa/setup", headers=hdr).json()["secret"]
    r = client.post("/api/v1/admin/mfa/enable", json={"code": totp_for(secret)}, headers=hdr)
    assert r.status_code == 200, r.text
    return admin, hdr, secret, r.json()


def stepped(hdr, token):
    return {**hdr, "X-Admin-Mfa": token}


# ---------------------------------------------------------------- who may even see it


@pytest.mark.parametrize("role", ["member", "tester"])
def test_non_admin_is_refused_everywhere(client, db_session, role):
    _u, hdr = make_user(db_session, f"x_{role}", role=role)
    for method, path in [
        ("get", "/api/v1/admin/mfa"),
        ("post", "/api/v1/admin/mfa/setup"),
        ("post", "/api/v1/admin/mfa/verify"),
        ("get", "/api/v1/admin/console/users"),
        ("get", "/api/v1/admin/console/audit"),
        ("get", "/api/v1/admin/console/release-switches"),
    ]:
        assert getattr(client, method)(path, headers=hdr).status_code == 403, path


def test_api_key_is_not_an_admin(client):
    assert client.get("/api/v1/admin/mfa", headers=API_KEY).status_code == 403
    assert client.get("/api/v1/admin/console/users", headers=API_KEY).status_code == 403


def test_no_credentials_is_401(client):
    assert client.get("/api/v1/admin/console/users").status_code == 401


# ---------------------------------------------------------------- MFA


def test_console_needs_enrolment_then_step_up(client, db_session):
    _admin, hdr = make_user(db_session, "fresh", role="owner")
    r = client.get("/api/v1/admin/console/users", headers=hdr)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_setup_required"
    assert client.get("/api/v1/admin/mfa", headers=hdr).json() == {
        "enrolled": False,
        "recovery_codes_left": 0,
    }


def test_setup_alone_does_not_enable(client, db_session):
    admin, hdr = make_user(db_session, "half", role="owner")
    r = client.post("/api/v1/admin/mfa/setup", headers=hdr)
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert client.get("/api/v1/admin/mfa", headers=hdr).json()["enrolled"] is False
    bad = client.post("/api/v1/admin/mfa/enable", json={"code": "000000"}, headers=hdr)
    assert bad.status_code == 400
    assert db_session.get(AdminMfa, admin.id).enabled_at is None


def test_enable_gives_ten_recovery_codes_stored_hashed(client, db_session):
    admin, hdr, _secret, body = enrol(client, db_session)
    codes = body["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    stored = {r.code_hash for r in db_session.query(AdminRecoveryCode).filter_by(user_id=admin.id)}
    assert len(stored) == 10 and not stored & set(codes)
    r = client.get("/api/v1/admin/console/users", headers=stepped(hdr, body["step_up_token"]))
    assert r.status_code == 200


def test_missing_wrong_or_foreign_step_up_token_refused(client, db_session):
    _admin, hdr, _s, body = enrol(client, db_session, "a1")
    _other, _ohdr, _s2, obody = enrol(client, db_session, "a2")
    url = "/api/v1/admin/console/users"
    assert client.get(url, headers=hdr).json()["detail"]["code"] == "mfa_required"
    assert client.get(url, headers=stepped(hdr, "garbage")).status_code == 403
    # a token issued to a different admin never works for this one
    assert client.get(url, headers=stepped(hdr, obody["step_up_token"])).status_code == 403
    # and the session token itself is not a step-up token
    session_token = hdr["Authorization"].split()[1]
    assert client.get(url, headers=stepped(hdr, session_token)).status_code == 403
    assert client.get(url, headers=stepped(hdr, body["step_up_token"])).status_code == 200


def test_step_up_token_is_not_a_login_token(client, db_session):
    _admin, _hdr, _s, body = enrol(client, db_session)
    r = client.get("/api/v1/admin/mfa", headers={"Authorization": f"Bearer {body['step_up_token']}"})
    assert r.status_code == 401


def test_token_dies_when_sessions_are_ended(client, db_session):
    admin, _hdr, _s, body = enrol(client, db_session)
    admin.token_version = (admin.token_version or 0) + 1
    db_session.flush()
    assert not mfa_service.step_up_valid(body["step_up_token"], admin)


def test_totp_cannot_be_reused_in_the_same_step(client, db_session):
    _admin, hdr, secret, _b = enrol(client, db_session)
    # enable already consumed the current step; the same code is refused
    r = client.post("/api/v1/admin/mfa/verify", json={"code": totp_for(secret)}, headers=hdr)
    assert r.status_code == 400
    r = client.post("/api/v1/admin/mfa/verify", json={"code": totp_for(secret, offset=1)}, headers=hdr)
    assert r.status_code == 200 and "step_up_token" in r.json()


def test_recovery_code_works_once(client, db_session):
    admin, hdr, _s, body = enrol(client, db_session)
    code = body["recovery_codes"][0]
    ok = client.post("/api/v1/admin/mfa/verify", json={"recovery_code": code}, headers=hdr)
    assert ok.status_code == 200 and ok.json()["recovery_codes_left"] == 9
    again = client.post("/api/v1/admin/mfa/verify", json={"recovery_code": code}, headers=hdr)
    assert again.status_code == 400
    actions = {a.action for a in db_session.query(AuditLog).filter_by(actor_user_id=admin.id)}
    assert {"admin.mfa_enabled", "admin.mfa_recovery_used", "admin.mfa_failed"} <= actions


def test_five_wrong_codes_lock_even_the_right_code(client, db_session):
    admin, hdr, secret, _b = enrol(client, db_session)
    for _ in range(5):
        assert (
            client.post("/api/v1/admin/mfa/verify", json={"code": "111111"}, headers=hdr).status_code == 400
        )
    locked = client.post("/api/v1/admin/mfa/verify", json={"code": totp_for(secret, offset=1)}, headers=hdr)
    assert locked.status_code == 400 and "Too many" in locked.json()["detail"]
    row = db_session.get(AdminMfa, admin.id)
    row.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert (
        client.post(
            "/api/v1/admin/mfa/verify", json={"code": totp_for(secret, offset=1)}, headers=hdr
        ).status_code
        == 200
    )


def test_re_setup_of_active_mfa_needs_step_up(client, db_session):
    _admin, hdr, _s, body = enrol(client, db_session)
    assert client.post("/api/v1/admin/mfa/setup", headers=hdr).status_code == 403
    assert (
        client.post("/api/v1/admin/mfa/setup", headers=stepped(hdr, body["step_up_token"])).status_code == 200
    )
    assert (
        client.get("/api/v1/admin/mfa", headers=hdr).json()["enrolled"] is False
    )  # must prove the new secret


# ---------------------------------------------------------------- users


def test_users_list_search_and_effective_plan(client, db_session):
    _admin, hdr, _s, body = enrol(client, db_session)
    h = stepped(hdr, body["step_up_token"])
    member, _ = make_user(db_session, "asha_member")
    make_user(db_session, "ravi_member", plan="pro")
    db_session.add(
        PlanGrant(
            user_id=member.id, plan_key="pro", starts_at=datetime.now(UTC) - timedelta(days=1), reason="gift"
        )
    )
    db_session.flush()
    rows = client.get("/api/v1/admin/console/users?q=member", headers=h).json()["users"]
    by = {r["username"]: r for r in rows}
    assert set(by) == {"asha_member", "ravi_member"}
    assert by["asha_member"]["stored_plan"] == "free"
    assert by["asha_member"]["effective_plan"] == "pro" and by["asha_member"]["has_active_grant"] is True
    assert by["ravi_member"]["effective_plan"] == "pro"
    assert "hashed_password" not in str(rows) and "secret" not in str(rows)
    assert client.get("/api/v1/admin/console/users?q=zzzz", headers=h).json()["users"] == []


def test_free_pro_switch_is_audited_and_validated(client, db_session):
    admin, hdr, _s, body = enrol(client, db_session)
    h = stepped(hdr, body["step_up_token"])
    member, _ = make_user(db_session, "switchme")
    r = client.put(f"/api/v1/admin/console/users/{member.id}/plan", json={"plan": "pro"}, headers=h)
    assert r.status_code == 200 and r.json()["stored_plan"] == "pro"
    entry = db_session.query(AuditLog).filter_by(action="user.plan_change", target_id=str(member.id)).one()
    assert entry.before == {"plan": "free"} and entry.after == {"plan": "pro"} and entry.actor_label == "boss"
    assert (
        client.put(
            f"/api/v1/admin/console/users/{member.id}/plan", json={"plan": "gold"}, headers=h
        ).status_code
        == 422
    )
    assert (
        client.put("/api/v1/admin/console/users/999999/plan", json={"plan": "pro"}, headers=h).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/admin/console/users/{admin.id}/plan", json={"plan": "free"}, headers=h
        ).status_code
        == 422
    )


def test_plan_change_without_step_up_is_refused_and_changes_nothing(client, db_session):
    _admin, hdr, _s, _b = enrol(client, db_session)
    member, _ = make_user(db_session, "untouched")
    r = client.put(f"/api/v1/admin/console/users/{member.id}/plan", json={"plan": "pro"}, headers=hdr)
    assert r.status_code == 403
    assert db_session.get(User, member.id).plan == "free"


def test_grant_with_reason_and_expiry_then_revoke(client, db_session):
    _admin, hdr, _s, body = enrol(client, db_session)
    h = stepped(hdr, body["step_up_token"])
    member, _ = make_user(db_session, "granted")
    end = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    r = client.post(
        f"/api/v1/admin/console/users/{member.id}/grants",
        json={"reason": "beta tester", "expires_at": end},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["reason"] == "beta tester"
    gid = r.json()["id"]
    assert (
        client.post(
            f"/api/v1/admin/console/users/{member.id}/grants", json={"reason": "x"}, headers=h
        ).status_code
        == 422
    )  # reason too short
    listed = client.get(f"/api/v1/admin/console/users/{member.id}/grants", headers=h).json()
    assert [g["id"] for g in listed] == [gid]
    assert (
        client.delete(f"/api/v1/admin/console/users/{member.id}/grants/{gid}", headers=h).status_code == 200
    )
    row = client.get("/api/v1/admin/console/users?q=granted", headers=h).json()["users"][0]
    assert row["has_active_grant"] is False
    actions = {a.action for a in db_session.query(AuditLog)}
    assert {"plan.grant", "plan.grant_revoke"} <= actions


def test_audit_trail_and_release_switches_view(client, db_session):
    _admin, hdr, _s, body = enrol(client, db_session)
    h = stepped(hdr, body["step_up_token"])
    trail = client.get("/api/v1/admin/console/audit?action=admin.mfa_enabled", headers=h).json()
    assert trail and trail[0]["actor"] == "boss"
    sw = client.get("/api/v1/admin/console/release-switches", headers=h).json()["switches"]
    assert sw and all(s["enabled"] is False for s in (sw if isinstance(sw, list) else sw.values()))
