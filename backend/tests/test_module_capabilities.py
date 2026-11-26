"""#335 slice: plans map onto the module registry's optional modules, enforced on the server.

Every plan x optional module is checked twice: as a pure rule (core/capabilities.py) and through the real
app (a signed-in member with that plan calls one route of the module). Defaults are unchanged: plans off,
the owner, the shared key and a tester (plans off) see what they saw before; a member is always held to the
plan. No billing, no payment, no migration.
"""

from __future__ import annotations

from itertools import count

import pytest

from swing_trade_ml.api import deps
from swing_trade_ml.core import capabilities, modules
from swing_trade_ml.core.plans import DEFAULT_PLANS, FEATURES, PLAN_KEYS, ROUTE_RULES
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import service_keys
from swing_trade_ml.services.plans import set_plans_enabled

_n = count()
API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}

# One real GET route per optional module.
ROUTE = {
    "finance": "/finance/categories",
    "mutual_funds": "/mutual-funds/holdings",
    "brain": "/brain/health",
    "research_lanes": "/research/lanes",
}
# Only the modules behind the plan check (optional() in the router). The others (switchable()) are on/off
# switches only and keep the access rules they had; tests/test_module_lifecycle.py covers those.
OPTIONAL = list(ROUTE)

# The written-down expectation (not derived from the code under test): only TradeMind, a Pro feature, reaches
# a plan caller; every other optional module is owner-only, as it is today.
PLAN_MAY_USE = {("pro", "brain")}

# Already closed to a tester before this change (private areas in api/deps.py, or the router's owner check).
OWNER_ONLY_FOR_TESTERS = {"finance", "mutual_funds", "research_lanes"}


def person(db, role, plan):
    u = User(
        username=f"cap-{role}-{plan}-{next(_n)}",
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan=plan,
        role=role,
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def features(plan):
    return frozenset(k for k, on in DEFAULT_PLANS[plan]["features"].items() if on)


# ---------------------------------------------------------------- the rule itself
def test_every_module_capability_is_a_real_plan_feature():
    for m in modules.REGISTRY:
        assert set(m.capabilities) <= set(FEATURES), (m.id, m.capabilities)


@pytest.mark.parametrize("plan", PLAN_KEYS)
@pytest.mark.parametrize("module_id", OPTIONAL)
def test_the_rule_matches_the_written_matrix(plan, module_id):
    module = modules.switches.module(module_id)
    assert capabilities.plan_may_use_module(module, features(plan)) is ((plan, module_id) in PLAN_MAY_USE)


def test_a_module_with_no_capability_is_owner_only_for_plans():
    for m in modules.REGISTRY:
        if not m.capabilities and not m.core:
            assert capabilities.plan_may_use_module(m, frozenset(FEATURES)) is False


# ---------------------------------------------------------------- through the real app
@pytest.fixture()
def plans_on(db_session):
    set_plans_enabled(db_session, True)


@pytest.mark.parametrize("plan", PLAN_KEYS)
@pytest.mark.parametrize("module_id", OPTIONAL)
def test_a_member_on_each_plan_reaches_only_what_the_matrix_allows(
    client, db_session, plans_on, plan, module_id
):
    r = client.get(f"{API}{ROUTE[module_id]}", headers=person(db_session, "member", plan))
    if (plan, module_id) in PLAN_MAY_USE:
        assert r.status_code != 403, r.text
    else:
        assert r.status_code == 403, (plan, module_id, r.status_code)


@pytest.mark.parametrize("module_id", OPTIONAL)
def test_plans_off_changes_nothing_for_members_owner_or_tester(client, db_session, module_id):
    set_plans_enabled(db_session, False)
    free = client.get(f"{API}{ROUTE[module_id]}", headers=person(db_session, "member", "free"))
    assert free.status_code == 403  # a member is never opened up by "plans off"
    assert client.get(f"{API}{ROUTE[module_id]}", headers=KEY).status_code != 403
    tester = client.get(f"{API}{ROUTE[module_id]}", headers=person(db_session, "tester", "free"))
    # a tester keeps today's view while plans are off, except what was already owner-only (as before)
    assert (tester.status_code == 403) is (module_id in OWNER_ONLY_FOR_TESTERS)


@pytest.mark.parametrize("module_id", [m for m in OPTIONAL if m != "brain"])
def test_the_module_check_holds_even_if_the_route_rules_were_opened_by_mistake(
    client, db_session, plans_on, monkeypatch, module_id
):
    """Defence in depth: open an owner-only module's route in ROUTE_RULES; the module check still refuses."""
    monkeypatch.setitem(ROUTE_RULES, ("GET", ROUTE[module_id]), ("picks", {}))
    monkeypatch.setattr(deps, "TESTER_PRIVATE_PREFIXES", ())  # the private-area check would answer first
    r = client.get(f"{API}{ROUTE[module_id]}", headers=person(db_session, "member", "free"))
    assert r.status_code == 403
    assert "isn't included in your plan" in r.text


# ---------------------------------------------------------------- scoped service keys keep their brain routes
KEY_ROUTES = [
    ("read_status", "/brain/stage", True),
    ("read_status", "/brain/daily-checks/latest", True),
    ("read_status", "/brain/runs/latest", False),  # not in the key's own list
    ("read_all", "/brain/runs/latest", True),
    ("read_all", "/brain/approvals", False),  # a forbidden area, whatever the scope
    ("read_ops", "/brain/stage", False),  # not the ops digest
]


@pytest.mark.parametrize("plans", [True, False])
@pytest.mark.parametrize(("scope", "path", "allowed"), KEY_ROUTES)
def test_a_scoped_service_key_reaches_exactly_what_its_scope_allows_on_brain_routes(
    client, db_session, plans, scope, path, allowed
):
    set_plans_enabled(db_session, plans)
    _, raw = service_keys.create_key(db_session, name="cap-key", scope=scope, created_by="owner1")
    r = client.get(f"{API}{path}", headers={"X-API-Key": raw})
    if allowed:
        assert r.status_code != 403, (scope, path, r.text)
    else:
        assert r.status_code == 403, (scope, path)
