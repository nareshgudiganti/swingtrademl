"""A plain member (not the owner, not a tester) never reads the owner's brain areas:
the alerts bell, the go-live stage and approvals, the trial journal, run traces and
per-run alerts. Whatever the plans switch says and whatever plan the member is on.
Only the owner (or the API key) gets in; plan users keep their TradeMind routes."""

from __future__ import annotations

import pytest

from swing_trade_ml.api.deps import PRIVATE_AREA
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services.plans import set_plans_enabled
from test_permissions_review import _routes, _url  # sibling import, like test_p0_role_matrix

OWNER_BRAIN_PREFIXES = (
    "/brain/alerts",
    "/brain/stage",
    "/brain/approvals",
    "/brain/compare",
    "/brain/trial-journal",
)


def _owner_brain_reads() -> list[str]:
    found = [
        path
        for method, path in _routes()
        if method == "GET"
        and (
            any(path == p or path.startswith(p + "/") for p in OWNER_BRAIN_PREFIXES)
            or (path.startswith("/brain/runs/") and path.endswith(("/alerts", "/trace")))
        )
    ]
    return sorted(found)


def _member(db, username: str, plan: str) -> dict[str, str]:
    user = User(username=username, hashed_password="x", is_active=True, role="member", plan=plan)
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def test_the_walk_finds_every_owner_brain_read():
    found = _owner_brain_reads()
    for path in ("/brain/alerts", "/brain/stage", "/brain/approvals", "/brain/runs/{run_id}/alerts"):
        assert path in found, path


@pytest.mark.parametrize("plans_on", [False, True])
@pytest.mark.parametrize("plan", ["free", "plus", "pro"])
@pytest.mark.parametrize("path", _owner_brain_reads())
def test_member_cannot_read_owner_brain_routes(client, db_session, path, plan, plans_on):
    set_plans_enabled(db_session, plans_on)
    r = client.get(_url(path), headers=_member(db_session, f"mob-{plan}", plan))
    switch = "on" if plans_on else "off"
    assert r.status_code == 403, f"GET {path} let a {plan} member through (plans {switch})"
    if any(path == p or path.startswith(p + "/") for p in OWNER_BRAIN_PREFIXES):
        # Refused as a private area, not merely "not in your plan": no plan edit can ever open it.
        assert r.json()["detail"] == PRIVATE_AREA


@pytest.mark.parametrize("path", ["/brain/alerts", "/brain/stage"])
def test_owner_still_reads_them(client, path):
    r = client.get(_url(path), headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200, r.text
