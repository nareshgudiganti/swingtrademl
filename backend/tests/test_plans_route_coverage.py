"""Plan coverage audit (Free / Pro table, decision D7). No database needed.

1. Every /api/v1 route is classified: public/auth, owner-checks-itself, plan-gated
   (core/plans.py::ROUTE_RULES or a TradeMind brain read), a person's own
   watchlist, or owner-only by default (behind require_auth, not in any list).
   A route that fits none of these (e.g. a new endpoint with no auth at all) fails
   the audit by name.
2. Driven from ROUTE_RULES: a Free caller is refused every Pro-only route, and a
   Pro caller is refused every owner-only route (and the owner's real book).

The gate under test is the real `require_auth`; only the caller's identity and
plan are faked through dependency overrides. Nothing here reads or writes data.
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.requests import Request

from swing_trade_ml.api import deps
from swing_trade_ml.api.deps import (
    SELF_SERVICE_ROUTES,
    PlanAccess,
    Principal,
    get_plan_access,
    get_principal,
    require_auth,
)
from swing_trade_ml.core.plans import FEATURES, ROUTE_RULES, brain_route_access, default_plan
from swing_trade_ml.db.session import get_db
from swing_trade_ml.main import app

PREFIX = "/api/v1"
SKIP_METHODS = {"HEAD", "OPTIONS"}

#: Open to the world by design (no credential exists yet, or an orchestrator / browser redirect calls it).
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/health"): "liveness probe",
    ("GET", "/ready"): "readiness probe",
    ("GET", "/auth/options"): "login screen asks which sign-in methods exist",
    ("POST", "/auth/login"): "no credential yet",
    ("POST", "/auth/signup"): "invite-code sign-up (handler checks the code)",
    ("POST", "/auth/invite-request"): "asking for an invite is public, rate-limited",
    ("GET", "/auth/google/login"): "starts Google sign-in",
    ("GET", "/auth/google/callback"): "Google redirect, browser cannot send headers",
    ("POST", "/auth/google/exchange"): "swaps a Google one-time code for a login",
    ("POST", "/auth/register"): "self sign-up; answers 404 unless ALLOW_SIGNUP is on",
    ("POST", "/auth/verify-email"): "the one-time emailed token is the credential",
    ("POST", "/auth/resend-verification"): "same answer for every email; rate-limited",
    ("POST", "/auth/forgot-password"): "same answer for every email; rate-limited",
    ("POST", "/auth/reset-password"): "the one-time emailed token is the credential",
    ("POST", "/billing/webhook"): "the provider calls it; the signature over the raw body is the credential",
    ("POST", "/account/deletion/confirm"): "the one-time emailed token is the credential; 404 unless ACCOUNT_DELETION_ENABLED",
    ("POST", "/account/deletion/cancel"): "the one-time emailed keep-my-account token is the credential",
    ("GET", "/auth/kite/login"): "starts the Zerodha login (redirect only; see report finding)",
    ("GET", "/auth/kite/callback"): "Zerodha redirect, browser cannot send headers",
}

#: Needs a signed-in person (bearer token) but no plan: their own account.
SIGNED_IN_ONLY_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/auth/me"): "who am I",
    ("POST", "/auth/password"): "change own password",
    ("POST", "/auth/logout-all"): "end own sessions",
    ("GET", "/me/plan"): "how the app learns what to show; must answer every plan",
    ("GET", "/billing/plans"): "a signed-in person sees the plans (404 unless BILLING_ENABLED)",
    ("GET", "/billing/me"): "a signed-in person sees their own subscription",
    ("POST", "/billing/checkout"): "a signed-in person starts their own subscription (sandbox only)",
    ("POST", "/billing/cancel"): "a signed-in person cancels their own subscription only",
    ("POST", "/billing/fake/simulate"): "fake provider only; the caller's own subscription",
    ("POST", "/account/deletion/request"): "a signed-in person asks to delete their own account",
    ("GET", "/account/deletion"): "a signed-in person sees their own deletion status",
    ("GET", "/account/export"): "a signed-in person downloads their own data",
}

#: Dependencies that mean "the handler is checked as the owner itself".
OWNER_SELF_CHECKS = {"require_owner", "require_owner_signed_in", "require_admin_user", "require_admin_mfa"}


def _contexts():
    """Flattened (method, path-without-prefix, dependency-call-names, route-call-set) for every /api/v1 route.

    This FastAPI wraps routers lazily (_IncludedRouter), so its effective route
    contexts are used when present; older versions expose plain APIRoutes."""

    def walk(dependant):
        for sub in dependant.dependencies:
            yield sub.call
            yield from walk(sub)

    raw = []
    for route in app.routes:
        if hasattr(route, "effective_route_contexts"):
            raw.extend(route.effective_route_contexts())
        elif isinstance(route, APIRoute):
            raw.append(route)
    found = {}
    for ctx in raw:
        if not ctx.path.startswith(PREFIX + "/"):
            continue
        calls = set(walk(ctx.dependant))
        names = {getattr(c, "__name__", "") for c in calls}
        for method in ctx.methods - SKIP_METHODS:
            found[(method, ctx.path[len(PREFIX) :])] = (calls, names)
    return found


ROUTES = _contexts()


def classify(method: str, path: str) -> str:
    calls, names = ROUTES[(method, path)]
    if require_auth in calls:
        if (method, path) in SELF_SERVICE_ROUTES:
            return "self_service"
        if (method, path) in ROUTE_RULES or brain_route_access(method, path) == "trademind":
            return "plan_gated"
        return "owner_only"
    if (method, path) in PUBLIC_ROUTES:
        return "public"
    if (method, path) in SIGNED_IN_ONLY_ROUTES:
        return "signed_in_only"
    if names & OWNER_SELF_CHECKS:
        return "owner_self_checked"
    return "UNCLASSIFIED"


#: Routes known to be unclassified today. None at the time of writing; any entry
#: added here must say why and is a finding for the owner.
KNOWN_UNCLASSIFIED: dict[tuple[str, str], str] = {}


def test_the_walk_sees_the_whole_app():
    assert len(ROUTES) > 150
    assert ("GET", "/signals/picks") in ROUTES and ("POST", "/portfolio/tester/buy") in ROUTES


def test_every_route_is_classified():
    unclassified = sorted(k for k in ROUTES if classify(*k) == "UNCLASSIFIED" and k not in KNOWN_UNCLASSIFIED)
    assert not unclassified, (
        "These routes have no auth and are on no allow-list. Gate them with require_auth, "
        f"or list them (with a reason) in this test: {unclassified}"
    )


@pytest.mark.parametrize("key", sorted(KNOWN_UNCLASSIFIED))
@pytest.mark.xfail(strict=False, reason="known unclassified route (see KNOWN_UNCLASSIFIED)")
def test_known_unclassified_route_is_classified(key):
    assert classify(*key) != "UNCLASSIFIED"


def test_allow_lists_have_no_stale_entries():
    for table in (PUBLIC_ROUTES, SIGNED_IN_ONLY_ROUTES, ROUTE_RULES, dict.fromkeys(SELF_SERVICE_ROUTES)):
        stale = [k for k in table if k not in ROUTES]
        assert not stale, f"listed but no such route: {stale}"


def test_allow_listed_routes_never_sit_behind_a_plan_gate_by_accident():
    # A public / signed-in-only route that also carried require_auth would be double-listed.
    for key in [*PUBLIC_ROUTES, *SIGNED_IN_ONLY_ROUTES]:
        assert require_auth not in ROUTES[key][0], key


def test_plan_rules_point_at_real_features():
    for key, (feature, _query) in ROUTE_RULES.items():
        assert feature in FEATURES, key


# ---------------------------------------------------------------- gate behaviour


def _access(plan_key: str) -> PlanAccess:
    plan = default_plan(plan_key)
    return PlanAccess(
        unrestricted=False,
        plan=plan_key,
        features=frozenset(k for k, on in plan["features"].items() if on),
        limits=plan["limits"],
    )


def _member(plan_key: str) -> Principal:
    user = SimpleNamespace(
        id=1, username=f"{plan_key}-member", role="member", plan=plan_key, is_superuser=False
    )
    return Principal(user=user)


@pytest.fixture()
def as_plan():
    """Call the app as a fake signed-in member on a given default plan. No database."""
    saved = dict(app.dependency_overrides)

    def use(plan_key: str) -> TestClient:
        app.dependency_overrides[get_principal] = lambda: _member(plan_key)
        app.dependency_overrides[get_plan_access] = lambda: _access(plan_key)
        app.dependency_overrides[get_db] = lambda: None
        return TestClient(app, raise_server_exceptions=False)  # no context manager: no lifespan, no scheduler

    yield use
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def _url(path: str, rule_query: dict[str, str] | None = None) -> str:
    url = PREFIX + re.sub(r"\{[^}]+\}", "1", path)
    if rule_query:
        url += "?" + "&".join(f"{k}={v}" for k, v in rule_query.items())
    return url


def _send(client: TestClient, method: str, path: str, query: dict[str, str] | None = None):
    return client.request(method, _url(path, query))


def _free_features() -> frozenset[str]:
    return _access("free").features


def pro_only_routes() -> list[tuple[str, str, dict[str, str]]]:
    """ROUTE_RULES routes whose feature Free does not have, plus TradeMind brain reads."""
    rows = [
        (m, p, q) for (m, p), (feature, q) in sorted(ROUTE_RULES.items()) if feature not in _free_features()
    ]
    if "trademind" not in _free_features():
        rows += [(m, p, {}) for (m, p) in sorted(ROUTES) if brain_route_access(m, p) == "trademind"]
    return rows


def owner_only_routes() -> list[tuple[str, str]]:
    return sorted(k for k in ROUTES if classify(*k) == "owner_only")


def test_there_are_pro_only_and_owner_only_routes_to_check():
    assert len(pro_only_routes()) >= 5
    assert len(owner_only_routes()) > 100


@pytest.mark.parametrize(("method", "path", "query"), pro_only_routes(), ids=lambda v: str(v))
def test_free_is_refused_every_pro_only_route(as_plan, method, path, query):
    response = _send(as_plan("free"), method, path, query)
    assert response.status_code == 403, (method, path, response.status_code)
    assert "isn't included in the free plan" in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), owner_only_routes(), ids=lambda v: str(v))
@pytest.mark.parametrize("plan_key", ["free", "pro"])
def test_no_plan_reaches_an_owner_only_route(as_plan, plan_key, method, path):
    response = _send(as_plan(plan_key), method, path)
    assert response.status_code == 403, (plan_key, method, path, response.status_code)


@pytest.mark.parametrize(
    ("method", "path", "query"),
    [(m, p, q) for (m, p), (_f, q) in sorted(ROUTE_RULES.items()) if q],
    ids=lambda v: str(v),
)
def test_pro_is_refused_the_owners_real_book(as_plan, method, path, query):
    wrong = dict.fromkeys(query, "real")
    response = _send(as_plan("pro"), method, path, wrong)
    assert response.status_code == 403
    assert _send(as_plan("pro"), method, path, {}).status_code == 403  # no `book` at all is refused too


def test_pro_plan_default_covers_every_catalogue_feature():
    assert _access("pro").features == frozenset(FEATURES)


def _gate(method: str, path: str, query: str, plan_key: str):
    scope = {
        "type": "http",
        "method": method,
        "path": PREFIX + path,
        "query_string": query.encode(),
        "headers": [],
        "route": SimpleNamespace(path=PREFIX + path),
    }
    return asyncio.run(require_auth(Request(scope), _access(plan_key), _member(plan_key)))


@pytest.mark.parametrize(("plan_key"), ["free", "pro"])
def test_each_plan_passes_the_gate_for_exactly_its_features(plan_key):
    features = _access(plan_key).features
    for (method, path), (feature, query) in sorted(ROUTE_RULES.items()):
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        if feature in features:
            assert _gate(method, path, qs, plan_key) is None, (plan_key, path)
        else:
            with pytest.raises(HTTPException) as err:
                _gate(method, path, qs, plan_key)
            assert err.value.status_code == 403


def test_deps_module_is_the_one_under_test():
    assert deps.require_auth is require_auth


def test_pro_cannot_read_the_real_book_through_brain_track():
    # Fixed on main (holdings PR): the handler refuses any non-paper book for a non-owner.
    # The plan gate lets a Pro member in (it is a TradeMind read), so the check lives in the handler;
    # it raises before touching the database, so no database is needed here.
    from swing_trade_ml.api.v1.endpoints.brain import holding_track

    assert _gate("GET", "/brain/track/{symbol}", "book=real", "pro") is None  # the gate lets Pro in
    principal = SimpleNamespace(via_api_key=False, is_owner=False)
    with pytest.raises(HTTPException) as err:
        holding_track("ABC", None, principal, book="real")
    assert err.value.status_code == 403
