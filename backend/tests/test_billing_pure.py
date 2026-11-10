"""Billing, no database and no network: entitlement rule, webhook signature, Razorpay provider
(mocked httpx transport only), the live-key guard."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.billing import signature
from swing_trade_ml.services.billing.base import BillingConfigError, BillingError
from swing_trade_ml.services.billing.entitlement import effective_plan_for, effective_plan_for_user
from swing_trade_ml.services.billing.fake import FakeProvider
from swing_trade_ml.services.billing.razorpay import BASE_URL, RazorpayProvider

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
MIN = timedelta(minutes=1)


def sub(status, end=None, cancel=False, requested=None, ended=None):
    return SimpleNamespace(
        status=status,
        current_end=end,
        cancel_at_cycle_end=cancel,
        cycle_end_requested_at=requested,
        cancelled_at=ended,
    )


def grant(starts=NOW - DAY, expires=None, revoked=None, plan="pro"):
    return SimpleNamespace(starts_at=starts, expires_at=expires, revoked_at=revoked, plan_key=plan)


# ------------------------------------------------------------------ entitlement matrix


@pytest.mark.parametrize(
    ("subscription", "expected"),
    [
        (sub("active", NOW + 10 * DAY), "pro"),
        (sub("active", NOW - 2 * DAY), "pro"),  # inside the grace window while the renewal webhook lands
        (sub("active", NOW - 10 * DAY), "free"),  # long past paid-through, nothing renewed it
        (sub("pending", NOW - 1 * DAY), "pro"),  # renewal being retried
        (sub("pending", NOW - 10 * DAY), "free"),
        (sub("halted", NOW + 10 * DAY), "free"),
        (sub("paused", NOW + 10 * DAY), "free"),
        (sub("created"), "free"),
        (sub("authenticated"), "free"),
        (sub("completed", NOW + 5 * DAY), "free"),
        (sub("completed", NOW - 5 * DAY), "free"),
        # cancelled: Pro only if WE asked for a cycle-end cancel AND the provider's ended_at confirms it
        (sub("cancelled", NOW + 5 * DAY, requested=NOW - DAY, ended=NOW + 5 * DAY - 5 * MIN), "pro"),
        (sub("cancelled", NOW - 1 * DAY, requested=NOW - 9 * DAY, ended=NOW - 1 * DAY), "free"),  # past it
        (sub("cancelled", NOW + 5 * DAY, cancel=False), "free"),  # immediate cancel
        (sub("cancelled", NOW + 5 * DAY, cancel=True), "free"),  # stale flag alone never earns access
        (sub("cancelled", NOW + 5 * DAY, cancel=True, requested=NOW - DAY, ended=NOW), "free"),  # dashboard
        (sub("cancelled", NOW + 5 * DAY, cancel=True, requested=NOW - DAY), "free"),  # no ended_at: ambiguous
        (sub("cancelled", NOW + 5 * DAY, ended=NOW + 5 * DAY), "free"),  # never requested by us
        (sub("active", NOW + 5 * DAY, cancel=True), "pro"),
        (sub("active", NOW - 1 * DAY, cancel=True), "free"),  # ending subscription gets no grace
        (None, "free"),
    ],
)
def test_subscription_matrix(subscription, expected):
    assert effective_plan_for("free", subscription, [], NOW) == expected


def test_cancel_at_cycle_end_then_time_passes_returns_to_free():
    s = sub("active", NOW + 5 * DAY, cancel=True)
    assert effective_plan_for("free", s, [], NOW) == "pro"
    assert effective_plan_for("free", s, [], NOW + 4 * DAY) == "pro"
    assert effective_plan_for("free", s, [], NOW + 5 * DAY) == "free"


@pytest.mark.parametrize(
    ("g", "expected"),
    [
        (grant(), "pro"),  # in force, no expiry
        (grant(expires=NOW + DAY), "pro"),
        (grant(expires=NOW - DAY), "free"),  # expired
        (grant(expires=NOW), "free"),  # expires_at is exclusive
        (grant(revoked=NOW - DAY), "free"),
        (grant(starts=NOW + DAY), "free"),  # future-dated
        (grant(starts=NOW), "pro"),  # starts_at inclusive
        (grant(plan="free"), "free"),
    ],
)
def test_grant_matrix(g, expected):
    assert effective_plan_for("free", None, [g], NOW) == expected


def test_stored_pro_and_no_rows_are_unchanged():
    assert effective_plan_for("pro", None, [], NOW) == "pro"
    assert effective_plan_for("pro", sub("halted"), [grant(revoked=NOW)], NOW) == "pro"  # admin-set stays
    assert effective_plan_for("free", None, [], NOW) == "free"
    assert effective_plan_for("free", [], None, NOW) == "free"


def test_naive_datetimes_are_treated_as_utc():
    s = sub("active", (NOW + DAY).replace(tzinfo=None))
    assert effective_plan_for("free", s, [], NOW) == "pro"


def test_glue_edge_cases_never_touch_the_db():
    assert effective_plan_for_user(None, SimpleNamespace(id=3, plan="pro")) == "pro"
    assert effective_plan_for_user(None, None) is None


def test_cancel_at_cycle_end_via_pure_rule_pro_until_current_end_then_free():
    end = NOW + 5 * DAY
    active = sub("active", end, cancel=True, requested=NOW)
    assert effective_plan_for("free", active, [], end - timedelta(minutes=1)) == "pro"
    assert effective_plan_for("free", active, [], end) == "free"
    # provider then reports the cycle-end cancel having happened at current_end
    done = sub("cancelled", end, requested=NOW, ended=end)
    assert effective_plan_for("free", done, [], end - timedelta(minutes=1)) == "pro"
    assert effective_plan_for("free", done, [], end + timedelta(minutes=1)) == "free"


def test_active_with_our_flag_then_sync_reports_immediate_cancel_is_free_at_once():
    s = sub("cancelled", NOW + 20 * DAY, cancel=False, requested=NOW - DAY, ended=NOW)
    assert effective_plan_for("free", s, [], NOW) == "free"


def test_fetch_unreadable_replies_are_failed_lookups_not_states():
    for reply in ({"id": "sub_1"}, {"id": "sub_1", "status": None}, [], {"status": "active"},
                  {"id": "s", "status": "active", "current_end": "garbage"}):
        p = _provider(lambda r, reply=reply: httpx.Response(200, json=reply))
        with pytest.raises(BillingError):
            p.fetch_subscription("sub_1")
    for code in (500, 502, 401, 403):
        with pytest.raises(BillingError):
            _provider(lambda r, code=code: httpx.Response(code, json={})).fetch_subscription("sub_1")
    with pytest.raises(BillingError):
        _provider(lambda r: httpx.Response(200, content=b"<html>")).fetch_subscription("sub_1")


# ------------------------------------------------------------------ signature


SECRET = "whsec_unit_test_value"


def test_signature_valid_tampered_missing():
    body = b'{"event":"subscription.charged"}'
    good = signature.sign(body, SECRET)
    assert signature.verify(body, good, SECRET)
    assert not signature.verify(body + b" ", good, SECRET)  # tampered body
    assert not signature.verify(body, good[:-1] + ("0" if good[-1] != "0" else "1"), SECRET)
    assert not signature.verify(body, "", SECRET)
    assert not signature.verify(body, None, SECRET)
    assert not signature.verify(body, good, "")  # no secret configured: nothing verifies
    assert not signature.verify(body, good, "other-secret")


def test_signature_is_over_raw_bytes_not_reencoded_json():
    raw = b'{ "event" :  "x" }'
    assert signature.verify(raw, signature.sign(raw, SECRET), SECRET)
    assert not signature.verify(raw, signature.sign(json.dumps(json.loads(raw)).encode(), SECRET), SECRET)


# ------------------------------------------------------------------ live-key guard


def test_live_key_refused_while_live_billing_is_off(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LIVE_BILLING", False)
    with pytest.raises(BillingConfigError) as err:
        RazorpayProvider(key_id="rzp_live_abcdef", key_secret="topsecretvalue")
    assert "topsecretvalue" not in str(err.value)
    assert "rzp_live_abcdef" not in str(err.value)
    with pytest.raises(BillingConfigError):
        RazorpayProvider(key_id="", key_secret="x")


def test_live_key_allowed_only_when_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LIVE_BILLING", True)
    assert RazorpayProvider(key_id="rzp_live_abcdef", key_secret="s").name == "razorpay"


def test_guard_also_applies_at_use_time(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LIVE_BILLING", False)
    p = RazorpayProvider(
        key_id="rzp_test_ok",
        key_secret="s",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
    )
    p._key_id = "rzp_live_sneaky"
    with pytest.raises(BillingConfigError):
        p.fetch_subscription("sub_1")


# ------------------------------------------------------------------ Razorpay over a mocked transport


def _provider(handler, plan_id="plan_test_1"):
    return RazorpayProvider(
        key_id="rzp_test_key",
        key_secret="rzp_test_secret_value",
        webhook_secret=SECRET,
        plan_id=plan_id,
        transport=httpx.MockTransport(handler),
    )


def test_create_subscription_request_shape_and_checkout_info():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "sub_123", "plan_id": "plan_test_1", "status": "created"})

    info = _provider(handler).create_subscription(SimpleNamespace(id=7), "pro")
    assert seen["url"] == BASE_URL + "subscriptions"
    assert seen["auth"].startswith("Basic ")
    assert seen["body"]["plan_id"] == "plan_test_1" and seen["body"]["notes"] == {"user_id": "7"}
    assert info.provider_subscription_id == "sub_123" and info.key_id == "rzp_test_key"
    assert "rzp_test_secret_value" not in repr(info)


def test_fetch_subscription_maps_fields():
    start, end = 1_760_000_000, 1_762_600_000

    def handler(request):
        assert request.method == "GET" and request.url.path.endswith("/subscriptions/sub_1")
        return httpx.Response(
            200,
            json={
                "id": "sub_1",
                "status": "active",
                "plan_id": "p",
                "current_start": start,
                "current_end": end,
            },
        )

    got = _provider(handler).fetch_subscription("sub_1")
    assert got.status == "active"
    assert got.current_end == datetime.fromtimestamp(end, tz=UTC)
    assert got.cancel_at_cycle_end is None


def test_cancel_sends_flag():
    bodies = []

    def handler(request):
        bodies.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"id": "sub_1", "status": "active"})

    p = _provider(handler)
    p.cancel_subscription("sub_1", True)
    p.cancel_subscription("sub_1", False)
    assert bodies[0][1] == {"cancel_at_cycle_end": 1} and bodies[1][1] == {"cancel_at_cycle_end": 0}
    assert bodies[0][0].endswith("/subscriptions/sub_1/cancel")


def test_http_error_and_transport_failure_raise_clean_errors():
    p = _provider(
        lambda r: httpx.Response(400, json={"error": {"description": "rzp_test_secret_value leaked?"}})
    )
    with pytest.raises(BillingError) as err:
        p.fetch_subscription("sub_1")
    assert "400" in str(err.value) and "rzp_test_secret_value" not in str(err.value)

    def boom(request):
        raise httpx.ConnectError("no network", request=request)

    with pytest.raises(BillingError):
        _provider(boom).fetch_subscription("sub_1")


def test_missing_plan_id_is_a_config_error():
    with pytest.raises(BillingConfigError):
        _provider(lambda r: httpx.Response(200, json={}), plan_id="").create_subscription(
            SimpleNamespace(id=1), "pro"
        )


def test_razorpay_verify_webhook_uses_webhook_secret():
    p = _provider(lambda r: httpx.Response(200, json={}))
    body = b"{}"
    assert p.verify_webhook(body, signature.sign(body, SECRET))
    assert not p.verify_webhook(
        body, signature.sign(body, "rzp_test_secret_value")
    )  # API secret is not the webhook secret


# ------------------------------------------------------------------ fake provider


def test_fake_provider_walks_states_without_network():
    fake = FakeProvider()
    info = fake.create_subscription(SimpleNamespace(id=1), "pro")
    sid = info.provider_subscription_id
    assert fake.fetch_subscription(sid).status == "created"
    s = fake.simulate(sid, "activated", NOW)
    assert s.status == "active" and s.current_end == NOW + timedelta(days=30)
    assert fake.simulate(sid, "pending", NOW).status == "pending"
    assert fake.simulate(sid, "halted", NOW).status == "halted"
    with pytest.raises(BillingError):
        fake.simulate(sid, "bogus", NOW)
    assert (
        FakeProvider().create_subscription(SimpleNamespace(id=1), "pro").provider_subscription_id
        == "sub_fake_000001"
    )
