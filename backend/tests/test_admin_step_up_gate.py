"""Older privileged admin routes need the admin two-step code once ADMIN_MFA_ENFORCED is on (scratch DB)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User

API = "/api/v1"
API_KEY = {"X-API-Key": "test-api-key"}


def make_user(db, name, *, role="member"):
    u = User(username=name, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(u)
    db.flush()
    return u, {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def enrol(client, hdr):
    secret = client.post(f"{API}/admin/mfa/setup", headers=hdr).json()["secret"]
    code = pyotp.TOTP(secret).at(datetime.now(UTC) + timedelta(seconds=0))
    r = client.post(f"{API}/admin/mfa/enable", json={"code": code}, headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()["step_up_token"]


def gated(target_id: int):
    """(method, path, body) for every route that carries the step-up gate."""
    return [
        ("put", "/admin/switch", {"enabled": False}),
        ("put", f"/admin/users/{target_id}/plan", {"plan": "free"}),
        ("get", "/admin/users", None),
        ("get", f"/admin/users/{target_id}/grants", None),
        ("post", f"/admin/users/{target_id}/grants", {"plan_key": "pro", "reason": "test"}),
        ("post", f"/admin/users/{target_id}/send-reset", None),
        ("post", "/admin/invites/1/reject", {"note": None}),
        ("post", "/admin/service-keys", {"name": "x", "scope": "read_status"}),
    ]


def call(client, method, path, body, headers):
    kw = {"headers": headers}
    if body is not None:
        kw["json"] = body
    return getattr(client, method)(f"{API}{path}", **kw)


@pytest.fixture
def enforced(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_MFA_ENFORCED", True)
    monkeypatch.setattr(settings, "BILLING_ENABLED", True)


def test_off_by_default_nothing_changes(client, db_session):
    assert settings.ADMIN_MFA_ENFORCED is False
    _o, hdr = make_user(db_session, "boss_off", role="owner")
    r = client.get(f"{API}/admin/users", headers=hdr)
    assert r.status_code == 200


def test_owner_without_setup_or_token_is_refused(client, db_session, enforced):
    target, _ = make_user(db_session, "target1")
    _o, hdr = make_user(db_session, "boss_nosetup", role="owner")
    for method, path, body in gated(target.id):
        r = call(client, method, path, body, hdr)
        assert r.status_code == 403, (path, r.status_code)
        assert r.json()["detail"]["code"] == "mfa_setup_required", path


def test_enrolled_owner_without_token_is_refused_then_works_with_token(client, db_session, enforced):
    target, _ = make_user(db_session, "target2")
    _o, hdr = make_user(db_session, "boss_on", role="owner")
    token = enrol(client, hdr)
    for method, path, body in gated(target.id):
        r = call(client, method, path, body, hdr)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "mfa_required", path
    stepped = {**hdr, "X-Admin-Mfa": token}
    assert call(client, "get", "/admin/users", None, stepped).status_code == 200
    assert call(client, "put", f"/admin/users/{target.id}/plan", {"plan": "free"}, stepped).status_code == 200
    assert call(client, "get", f"/admin/users/{target.id}/grants", None, stepped).status_code == 200


def test_wrong_or_other_persons_token_is_refused(client, db_session, enforced):
    target, _ = make_user(db_session, "target3")
    _a, hdr_a = make_user(db_session, "boss_a", role="owner")
    _b, hdr_b = make_user(db_session, "boss_b", role="owner")
    token_a = enrol(client, hdr_a)
    enrol(client, hdr_b)
    bad = {**hdr_b, "X-Admin-Mfa": token_a}
    assert call(client, "get", "/admin/users", None, bad).status_code == 403
    junk = {**hdr_a, "X-Admin-Mfa": "not-a-token"}
    assert call(client, "get", "/admin/users", None, junk).status_code == 403
    _ = target


@pytest.mark.parametrize("role", ["member", "tester"])
def test_member_and_tester_refused_even_with_someone_elses_token(client, db_session, enforced, role):
    target, _ = make_user(db_session, f"target_{role}")
    _a, hdr_a = make_user(db_session, f"boss_{role}", role="owner")
    token = enrol(client, hdr_a)
    _u, hdr = make_user(db_session, f"x_{role}", role=role)
    hdr = {**hdr, "X-Admin-Mfa": token}
    for method, path, body in gated(target.id):
        assert call(client, method, path, body, hdr).status_code == 403, path


def test_api_key_refused_on_gated_routes(client, db_session, enforced):
    target, _ = make_user(db_session, "target4")
    for method, path, body in gated(target.id):
        r = call(client, method, path, body, API_KEY)
        assert r.status_code == 403, (path, r.status_code)


def test_read_only_views_stay_open_to_the_signed_in_owner(client, db_session, enforced):
    _o, hdr = make_user(db_session, "boss_ro", role="owner")
    for path in ["/admin/switch", "/admin/features", "/admin/plans", "/admin/jobs", "/admin/release-switches"]:
        assert call(client, "get", path, None, hdr).status_code == 200, path


def test_every_admin_write_route_is_gated_or_listed():
    """A new /admin write route must carry the step-up gate, or be listed here with a reason."""
    from swing_trade_ml.api.admin_step_up import require_admin_step_up
    from swing_trade_ml.main import app

    own_gate = ("/api/v1/admin/mfa", "/api/v1/admin/console")  # these have their own MFA checks
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/api/v1/admin") or path.startswith(own_gate):
            continue
        if not methods - {"GET", "HEAD", "OPTIONS"}:
            continue
        deps = [d.call for d in route.dependant.dependencies]
        if require_admin_step_up not in deps:
            missing.append(f"{sorted(methods)} {path}")
    assert missing == []
