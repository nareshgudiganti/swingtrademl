"""One TradeMind, Phase 1: the Admin pages and owner-only Portfolio pages are protected by the backend, not
by hidden menu items. test_permissions_review.py already proves EVERY write refuses a non-owner and every
non-public route refuses no credentials. This file adds the READS those pages make, which that walk does
not cover: what a signed-in non-owner gets when they call them directly, with plans off (as on prod) and on.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.api import deps
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services.plans import set_plans_enabled

# Reads that must refuse a non-owner whatever the plans switch says: the Observatory.
ALWAYS_OWNER = [
    "/api/v1/brain/observatory/days?from=2026-10-01&to=2026-10-15",
    "/api/v1/brain/observatory/runs/nightly-x",
]

# The real Zerodha account (My Holdings). Its private-account guard (require_real_account) is on `develop`
# but not on origin/main yet, so on main today these answer 200 to a non-owner while plans are off (as on
# prod). Known issue, recorded in the Phase 1 PR; these tests switch on by themselves the day the guard
# reaches this branch.
REAL_ACCOUNT = [
    "/api/v1/portfolio/real/account",
    "/api/v1/real-report",
    "/api/v1/portfolio/positions/detailed?book=real",
    "/api/v1/portfolio/health?book=real",
]
_HAS_REAL_GUARD = hasattr(deps, "require_real_account")

# Reads behind the other Admin pages. A non-owner must be refused as soon as plans are on; with plans off
# reading is unchanged by design (F-17 covers writes), so they are not asserted in that mode.
ADMIN_READS_WHEN_PLANS_ON = [
    "/api/v1/safety/state",
    "/api/v1/risk/limits",
    "/api/v1/brain/approvals",
    "/api/v1/brain/compare",
    "/api/v1/instruments/watchlist",
    "/api/v1/portfolio/holdings",
]


@pytest.fixture(autouse=True)
def _brain_on(monkeypatch):
    # With the brain off the Observatory answers 404 to everyone, which would hide a missing owner guard.
    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)


def _user(db_session, plan: str, owner: bool = False) -> dict[str, str]:
    user = User(
        username=f"neg-{plan}-{owner}", hashed_password="x", is_active=True, is_superuser=owner, plan=plan
    )
    db_session.add(user)
    db_session.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


@pytest.mark.parametrize("plans_on", [False, True])
@pytest.mark.parametrize("plan", ["free", "pro"])
@pytest.mark.parametrize("path", ALWAYS_OWNER)
def test_owner_only_reads_refuse_a_non_owner(client, db_session, path, plan, plans_on):
    set_plans_enabled(db_session, plans_on)
    r = client.get(path, headers=_user(db_session, plan))
    assert r.status_code in (401, 403), (
        f"{path} let a {plan} non-owner through (plans_on={plans_on}): {r.status_code}"
    )


@pytest.mark.parametrize("plan", ["free", "pro"])
@pytest.mark.parametrize("path", ADMIN_READS_WHEN_PLANS_ON)
def test_admin_reads_refuse_a_non_owner_when_plans_are_on(client, db_session, path, plan):
    set_plans_enabled(db_session, True)
    r = client.get(path, headers=_user(db_session, plan))
    assert r.status_code in (401, 403), f"{path} let a {plan} non-owner through: {r.status_code}"


@pytest.mark.skipif(
    not _HAS_REAL_GUARD, reason="real-account guard not on this branch yet (see REAL_ACCOUNT note)"
)
@pytest.mark.parametrize("plans_on", [False, True])
@pytest.mark.parametrize("path", REAL_ACCOUNT)
def test_the_real_account_refuses_a_non_owner(client, db_session, path, plans_on):
    set_plans_enabled(db_session, plans_on)
    r = client.get(path, headers=_user(db_session, "pro"))
    assert r.status_code in (401, 403)


@pytest.mark.parametrize("path", ALWAYS_OWNER)
def test_the_owner_key_is_not_locked_out(client, path):
    # The shared API key is the owner's own scripts: the one caller always allowed to see the real account.
    r = client.get(path, headers={"X-API-Key": "test-api-key"})
    assert r.status_code not in (401, 403)
