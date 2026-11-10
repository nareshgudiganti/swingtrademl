"""Billing API against the scratch test database (Docker Postgres). No network: the provider is the fake."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.routing import APIRoute

from swing_trade_ml.api import deps
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.billing import BillingEvent, PlanGrant, Subscription
from swing_trade_ml.db.models.session import User
from swing_trade_ml.main import app
from swing_trade_ml.services.billing import entitlement, signature
from swing_trade_ml.services.billing import service as billing
from swing_trade_ml.services.billing.fake import FAKE_WEBHOOK_SECRET, FakeProvider

API_KEY = {"X-API-Key": "test-api-key"}
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def billing_on(monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENABLED", True)
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "fake")
    monkeypatch.setattr(settings, "ALLOW_LIVE_BILLING", False)
    fake = FakeProvider()
    billing.set_provider(fake)
    yield fake
    billing.set_provider(None)


@pytest.fixture()
def fake(billing_on) -> FakeProvider:
    return billing_on


def make_user(db, name, *, plan="free", role="member") -> tuple[User, dict[str, str]]:
    user = User(username=name, hashed_password="x", is_active=True, plan=plan, role=role)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def webhook(client, body: dict, *, event_id: str, sig: str | None = None, secret=FAKE_WEBHOOK_SECRET):
    raw = json.dumps(body).encode()
    headers = {"X-Razorpay-Event-Id": event_id, "Content-Type": "application/json"}
    headers["X-Razorpay-Signature"] = signature.sign(raw, secret) if sig is None else sig
    return client.post("/api/v1/billing/webhook", content=raw, headers=headers)


def event_body(event: str, sub_id: str) -> dict:
    return {"event": f"subscription.{event}", "payload": {"subscription": {"entity": {"id": sub_id}}}}


def start_subscription(client, hdr) -> str:
    r = client.post("/api/v1/billing/checkout", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json()["subscription_id"]


def plan_of(db, user) -> str:
    db.expire_all()
    return deps.plan_access_for(db, deps.Principal(user=user)).plan


# ------------------------------------------------------------------ disabled = 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/billing/plans"),
        ("GET", "/billing/me"),
        ("POST", "/billing/checkout"),
        ("POST", "/billing/cancel"),
        ("POST", "/billing/webhook"),
        ("POST", "/billing/fake/simulate"),
        ("GET", "/admin/users/1/grants"),
        ("POST", "/admin/users/1/grants"),
        ("DELETE", "/admin/users/1/grants/1"),
    ],
)
def test_every_billing_route_is_404_when_disabled(client, db_session, monkeypatch, method, path):
    monkeypatch.setattr(settings, "BILLING_ENABLED", False)
    _, hdr = make_user(db_session, "m404")
    r = client.request(method, "/api/v1" + path, headers=hdr, json={})
    assert r.status_code == 404
    r = client.request(method, "/api/v1" + path, headers=API_KEY, json={})
    assert r.status_code == 404  # the owner's key does not open a disabled feature either


# ------------------------------------------------------------------ plans / me / checkout / cancel


def test_plans_price_comes_from_settings(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "PRO_PRICE_MONTHLY_PAISE", 12345)
    _, hdr = make_user(db_session, "pricer")
    body = client.get("/api/v1/billing/plans", headers=hdr).json()
    pro = next(p for p in body["plans"] if p["key"] == "pro")
    assert pro["price"]["amount_paise"] == 12345 and body["sandbox"] is True
    assert "price" not in next(p for p in body["plans"] if p["key"] == "free")
    assert pro["features"]


def test_plans_requires_sign_in(client):
    assert client.get("/api/v1/billing/plans").status_code == 401


def test_api_key_has_no_person_so_billing_refuses_it(client):
    assert client.get("/api/v1/billing/me", headers=API_KEY).status_code == 403


def test_checkout_then_journey_activate_charge_pending_halt(client, db_session, fake):
    user, hdr = make_user(db_session, "journey")
    assert plan_of(db_session, user) == "free"
    r = client.post("/api/v1/billing/checkout", headers=hdr).json()
    assert r["provider"] == "fake" and r["completion_token"] == r["subscription_id"] and r["key_id"] is None
    assert plan_of(db_session, user) == "free"  # created is not paid

    def sim(event):
        resp = client.post("/api/v1/billing/fake/simulate", json={"event": event}, headers=hdr)
        assert resp.status_code == 200, resp.text
        return resp.json()["subscription"]

    assert sim("activated")["status"] == "active" and plan_of(db_session, user) == "pro"
    assert sim("charged")["status"] == "active" and plan_of(db_session, user) == "pro"
    assert sim("pending")["status"] == "pending" and plan_of(db_session, user) == "pro"  # retry grace
    assert sim("halted")["status"] == "halted" and plan_of(db_session, user) == "free"
    assert sim("activated")["status"] == "active" and plan_of(db_session, user) == "pro"
    assert sim("completed")["status"] == "completed" and plan_of(db_session, user) == "free"
    me = client.get("/api/v1/billing/me", headers=hdr).json()
    assert me["subscription"]["status"] == "completed" and me["plan"] == "free"


def test_second_checkout_while_subscribed_is_refused(client, db_session):
    _user, hdr = make_user(db_session, "twice")
    start_subscription(client, hdr)
    client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=hdr)
    assert client.post("/api/v1/billing/checkout", headers=hdr).status_code == 409


def test_me_shows_only_own_subscription(client, db_session):
    _a, ha = make_user(db_session, "alice")
    _b, hb = make_user(db_session, "bob")
    start_subscription(client, ha)
    client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=ha)
    mine = client.get("/api/v1/billing/me", headers=ha).json()
    theirs = client.get("/api/v1/billing/me", headers=hb).json()
    assert mine["subscription"]["status"] == "active" and mine["plan"] == "pro"
    assert theirs["subscription"] is None and theirs["plan"] == "free"
    assert "provider_subscription_id" not in json.dumps(mine)


def test_member_cannot_simulate_someone_elses_subscription(client, db_session):
    _a, ha = make_user(db_session, "owner_of_sub")
    _b, hb = make_user(db_session, "snoop")
    sid = start_subscription(client, ha)
    r = client.post(
        "/api/v1/billing/fake/simulate", json={"event": "activated", "subscription_id": sid}, headers=hb
    )
    assert r.status_code == 403
    _owner, ho = make_user(db_session, "theowner", role="owner")
    r = client.post(
        "/api/v1/billing/fake/simulate", json={"event": "activated", "subscription_id": sid}, headers=ho
    )
    assert r.status_code == 200


def test_simulate_is_404_when_provider_is_not_fake(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_PROVIDER", "razorpay")
    _, hdr = make_user(db_session, "nofake")
    assert (
        client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=hdr).status_code
        == 404
    )


def test_cancel_at_cycle_end_keeps_pro_then_free_when_time_passes(client, db_session, fake):
    user, hdr = make_user(db_session, "canceller")
    sid = start_subscription(client, hdr)
    client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=hdr)
    r = client.post("/api/v1/billing/cancel", json={"at_cycle_end": True}, headers=hdr)
    assert r.status_code == 200 and r.json()["subscription"]["cancel_scheduled"] is True
    assert r.json()["subscription"]["status"] == "active"
    assert plan_of(db_session, user) == "pro"
    paid_through = db_session.query(Subscription).filter_by(provider_subscription_id=sid).one().current_end
    just_before = paid_through - timedelta(minutes=1)
    after = paid_through + timedelta(minutes=1)
    assert entitlement.effective_plan_for_user(db_session, user, just_before) == "pro"
    assert entitlement.effective_plan_for_user(db_session, user, after) == "free"  # no job, no webhook needed


def test_cancel_immediately_is_free_at_once(client, db_session):
    user, hdr = make_user(db_session, "immediate")
    start_subscription(client, hdr)
    client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=hdr)
    r = client.post("/api/v1/billing/cancel", json={"at_cycle_end": False}, headers=hdr)
    assert (
        r.json()["subscription"]["status"] == "cancelled"
        and r.json()["subscription"]["cancel_scheduled"] is False
    )
    assert plan_of(db_session, user) == "free"


def test_cancel_with_no_subscription_is_404(client, db_session):
    _, hdr = make_user(db_session, "nosub")
    assert client.post("/api/v1/billing/cancel", headers=hdr).status_code == 404


# ------------------------------------------------------------------ webhook


def test_webhook_signature_tampered_and_missing_are_400_and_change_nothing(client, db_session, fake):
    _user, hdr = make_user(db_session, "sig")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated")
    body = event_body("activated", sid)
    assert webhook(client, body, event_id="e1", sig="deadbeef").status_code == 400
    assert webhook(client, body, event_id="e1", secret="wrong-secret").status_code == 400
    raw = json.dumps(body).encode()
    r = client.post(
        "/api/v1/billing/webhook", content=raw, headers={"X-Razorpay-Event-Id": "e1"}
    )  # no signature header at all
    assert r.status_code == 400
    assert db_session.query(BillingEvent).count() == 0
    assert db_session.query(Subscription).filter_by(provider_subscription_id=sid).one().status == "created"


def test_webhook_applies_state_and_records_event_without_payload(client, db_session, fake):
    user, hdr = make_user(db_session, "apply")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated")
    assert webhook(client, event_body("activated", sid), event_id="evt_A").status_code == 200
    row = db_session.query(BillingEvent).filter_by(event_id="evt_A").one()
    assert row.event_type == "subscription.activated" and row.processed_at is not None
    assert row.outcome == "synced:active" and row.payload_hash and len(row.payload_hash) == 64
    assert plan_of(db_session, user) == "pro"
    assert sid not in json.dumps([row.event_id, row.event_type, row.outcome, row.payload_hash])


def test_duplicate_delivery_changes_nothing(client, db_session, fake):
    _user, hdr = make_user(db_session, "dupe")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated", NOW)
    assert webhook(client, event_body("activated", sid), event_id="evt_D").status_code == 200
    sub = db_session.query(Subscription).filter_by(provider_subscription_id=sid).one()
    snapshot = (sub.status, sub.current_end, sub.updated_at)
    # The provider's world moves on; a re-delivery of the OLD event id must not re-sync.
    fake.simulate(sid, "halted", NOW)
    r = webhook(client, event_body("activated", sid), event_id="evt_D")
    assert r.status_code == 200 and r.json()["outcome"] == "duplicate"
    db_session.expire_all()
    sub = db_session.query(Subscription).filter_by(provider_subscription_id=sid).one()
    assert (sub.status, sub.current_end, sub.updated_at) == snapshot
    assert db_session.query(BillingEvent).filter_by(event_id="evt_D").count() == 1


def test_out_of_order_charged_before_activated(client, db_session, fake):
    user, hdr = make_user(db_session, "order1")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated", NOW)
    fake.simulate(sid, "charged", NOW)
    webhook(client, event_body("charged", sid), event_id="o1-charged")
    assert plan_of(db_session, user) == "pro"
    webhook(client, event_body("activated", sid), event_id="o1-activated")  # late
    assert db_session.query(Subscription).filter_by(provider_subscription_id=sid).one().status == "active"


def test_stale_activated_after_cancelled_ends_in_provider_state(client, db_session, fake):
    user, hdr = make_user(db_session, "order2")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated", NOW)
    fake.simulate(sid, "cancelled", NOW)  # provider's truth is now cancelled
    webhook(client, event_body("cancelled", sid), event_id="o2-cancelled")
    webhook(client, event_body("activated", sid), event_id="o2-activated-stale")
    db_session.expire_all()
    sub = db_session.query(Subscription).filter_by(provider_subscription_id=sid).one()
    assert sub.status == "cancelled"
    assert plan_of(db_session, user) == "free"


def test_unknown_event_and_unknown_subscription_return_200(client, db_session, fake):
    r = webhook(client, {"event": "payment.captured", "payload": {}}, event_id="x1")
    assert r.status_code == 200
    r = webhook(client, event_body("charged", "sub_not_ours"), event_id="x2")
    assert r.status_code == 200
    outcomes = {e.event_id: e.outcome for e in db_session.query(BillingEvent)}
    assert outcomes == {"x1": "ignored", "x2": "unknown_subscription"}
    assert (
        webhook(client, {"event": "subscription.halted"}, event_id="x3").status_code == 200
    )  # no subscription entity
    r = client.post(
        "/api/v1/billing/webhook",
        content=b"not json",
        headers={"X-Razorpay-Signature": signature.sign(b"not json", FAKE_WEBHOOK_SECRET)},
    )
    assert r.status_code == 200


def test_provider_fetch_failure_is_5xx_and_leaves_no_event_so_retry_works(
    client, db_session, fake, monkeypatch
):
    user, hdr = make_user(db_session, "retry")
    sid = start_subscription(client, hdr)
    fake.simulate(sid, "activated", NOW)
    original = fake.fetch_subscription
    from swing_trade_ml.services.billing.base import BillingError

    def broken(_):
        raise BillingError("provider down")

    monkeypatch.setattr(fake, "fetch_subscription", broken)
    assert webhook(client, event_body("activated", sid), event_id="r1").status_code == 502
    assert db_session.query(BillingEvent).filter_by(event_id="r1").count() == 0
    monkeypatch.setattr(fake, "fetch_subscription", original)
    assert webhook(client, event_body("activated", sid), event_id="r1").status_code == 200
    assert plan_of(db_session, user) == "pro"


def test_webhook_needs_no_sign_in(client, fake):
    r = webhook(client, {"event": "subscription.updated"}, event_id="pub")
    assert r.status_code == 200


# ---------------------------------------------------------------- entitlement via the real plan resolution


def test_user_with_no_subscription_and_no_grant_resolves_as_before(db_session, monkeypatch):
    user, _ = make_user(db_session, "plain")
    pro_user, _ = make_user(db_session, "plainpro", plan="pro")
    for enabled in (False, True):
        monkeypatch.setattr(settings, "BILLING_ENABLED", enabled)
        assert deps.plan_access_for(db_session, deps.Principal(user=user)).plan == "free"
        assert deps.plan_access_for(db_session, deps.Principal(user=pro_user)).plan == "pro"


def test_owner_is_never_limited(db_session):
    owner, _ = make_user(db_session, "boss", role="owner")
    assert deps.plan_access_for(db_session, deps.Principal(user=owner)).unrestricted is True


def test_billing_off_ignores_subscriptions_and_grants(db_session, monkeypatch):
    user, _ = make_user(db_session, "ignored")
    db_session.add(
        PlanGrant(user_id=user.id, plan_key="pro", starts_at=NOW - timedelta(days=1), reason="test")
    )
    db_session.flush()
    assert plan_of(db_session, user) == "pro"
    monkeypatch.setattr(settings, "BILLING_ENABLED", False)
    assert plan_of(db_session, user) == "free"


def test_admin_stored_pro_wins_over_a_halted_subscription(db_session):
    user, _ = make_user(db_session, "adminpro", plan="pro")
    db_session.add(
        Subscription(user_id=user.id, provider="fake", provider_subscription_id="s_h", status="halted")
    )
    db_session.flush()
    assert plan_of(db_session, user) == "pro"


# ------------------------------------------------------------------ grants


def grant_url(uid, gid=None):
    return f"/api/v1/admin/users/{uid}/grants" + (f"/{gid}" if gid else "")


def test_owner_grants_and_revokes_with_audit(client, db_session):
    owner, ho = make_user(db_session, "granter", role="owner")
    target, _ht = make_user(db_session, "gifted")
    r = client.post(grant_url(target.id), json={"reason": "early supporter"}, headers=ho)
    assert r.status_code == 201, r.text
    g = r.json()
    assert (
        g["granted_by_user_id"] == owner.id and g["reason"] == "early supporter" and g["expires_at"] is None
    )
    assert g["starts_at"] and g["created_at"] is not None
    assert plan_of(db_session, target) == "pro"
    audit_row = db_session.query(AuditLog).filter_by(action="plan.grant").one()
    assert audit_row.actor_user_id == owner.id and audit_row.target_id == str(target.id)
    assert client.get(grant_url(target.id), headers=ho).json()[0]["id"] == g["id"]
    r = client.delete(grant_url(target.id, g["id"]), headers=ho)
    assert r.status_code == 200 and r.json()["revoked_at"]
    assert plan_of(db_session, target) == "free"
    assert db_session.query(AuditLog).filter_by(action="plan.grant_revoke").count() == 1
    assert client.delete(grant_url(target.id, 999999), headers=ho).status_code == 404


def test_grant_with_expiry_and_future_start(client, db_session):
    _, ho = make_user(db_session, "granter2", role="owner")
    target, _ = make_user(db_session, "gifted2")
    soon = (NOW + timedelta(days=3)).isoformat()
    client.post(grant_url(target.id), json={"reason": "trial week", "expires_at": soon}, headers=ho)
    assert plan_of(db_session, target) == "pro"
    assert entitlement.effective_plan_for_user(db_session, target, NOW + timedelta(days=4)) == "free"
    later, _ = make_user(db_session, "gifted3")
    client.post(
        grant_url(later.id),
        json={"reason": "starts later", "starts_at": (NOW + timedelta(days=2)).isoformat()},
        headers=ho,
    )
    assert plan_of(db_session, later) == "free"
    r = client.post(
        grant_url(later.id),
        json={"reason": "bad dates", "starts_at": soon, "expires_at": (NOW).isoformat()},
        headers=ho,
    )
    assert r.status_code == 422


def test_non_owner_cannot_create_or_revoke_grants(client, db_session):
    _member, hm = make_user(db_session, "memberg")
    _tester, ht = make_user(db_session, "testerg", role="tester")
    target, _ = make_user(db_session, "victim")
    for hdr in (hm, ht):
        assert client.post(grant_url(target.id), json={"reason": "sneaky"}, headers=hdr).status_code == 403
        assert client.delete(grant_url(target.id, 1), headers=hdr).status_code == 403
        assert client.get(grant_url(target.id), headers=hdr).status_code == 403
    assert db_session.query(PlanGrant).count() == 0
    assert client.post(grant_url(target.id), json={"reason": "no auth"}).status_code == 401


def test_grant_needs_a_reason_and_a_real_user(client, db_session):
    _, ho = make_user(db_session, "granter3", role="owner")
    target, _ = make_user(db_session, "gifted4")
    assert client.post(grant_url(target.id), json={}, headers=ho).status_code == 422
    assert client.post(grant_url(target.id), json={"reason": "x"}, headers=ho).status_code == 422
    assert client.post(grant_url(987654), json={"reason": "ghost user"}, headers=ho).status_code == 404
    assert (
        client.post(
            grant_url(target.id), json={"reason": "free plan?", "plan_key": "free"}, headers=ho
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ secrets, classification


def test_no_secret_in_responses_or_logs(client, db_session, monkeypatch, caplog, capsys):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "SECRET_KEY_VALUE_123")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "SECRET_WEBHOOK_VALUE_456")
    caplog.set_level(logging.DEBUG)
    _user, hdr = make_user(db_session, "quiet")
    texts = []
    r = client.post("/api/v1/billing/checkout", headers=hdr)
    texts.append(r.text)
    sid = r.json()["subscription_id"]
    texts.append(client.post("/api/v1/billing/fake/simulate", json={"event": "activated"}, headers=hdr).text)
    texts.append(client.get("/api/v1/billing/me", headers=hdr).text)
    texts.append(client.get("/api/v1/billing/plans", headers=hdr).text)
    texts.append(webhook(client, event_body("activated", sid), event_id="q1", sig="bad").text)
    out = capsys.readouterr()
    blob = "\n".join(texts) + caplog.text + out.out + out.err
    assert "SECRET_KEY_VALUE_123" not in blob and "SECRET_WEBHOOK_VALUE_456" not in blob


def test_billing_routes_are_classified_for_the_plan_system():
    """members: own-data routes live outside require_auth (its writes are owner-only); webhook is public."""
    routes = {}
    for route in app.routes:
        contexts = route.effective_route_contexts() if hasattr(route, "effective_route_contexts") else [route]
        for ctx in contexts:
            if isinstance(ctx, APIRoute) or hasattr(ctx, "dependant"):
                path = ctx.path
                if "/billing" in path or ("/admin/users/" in path and "grants" in path):
                    calls = []

                    def walk(dep, calls=calls):
                        for sub in dep.dependencies:
                            calls.append(sub.call)
                            walk(sub)

                    walk(ctx.dependant)
                    for m in ctx.methods - {"HEAD", "OPTIONS"}:
                        routes[(m, path.removeprefix("/api/v1"))] = {
                            getattr(c, "__name__", "") for c in calls
                        }
    assert ("POST", "/billing/webhook") in routes and (
        "DELETE",
        "/admin/users/{user_id}/grants/{grant_id}",
    ) in routes
    for key, names in routes.items():
        assert "require_auth" not in names, key
        if key[0] == "POST" and key[1] == "/billing/webhook":
            assert "get_principal" not in names and "person" not in names  # public
        elif key[1].startswith("/admin/"):
            assert "require_owner" in names, key
        elif key[1] == "/billing/fake/simulate":
            pass  # takes the principal in its body-handling code (person() inside), tested above
        else:
            assert "person" in names, key
    assert len(routes) == 9
