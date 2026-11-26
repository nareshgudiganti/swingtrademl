# ruff: noqa: E501  (long plain-English test sentences)
"""#291 acceptance: every optional module has a lifecycle test (off: routes refuse, jobs absent, core and other
modules untouched; on: restored), every part of the app is declared, and the inventory is complete."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager

import pytest

from swing_trade_ml.api.v1.endpoints import admin_modules
from swing_trade_ml.core import modules
from swing_trade_ml.core.modules import REGISTRY, ModuleSwitches, apply_to_scheduler
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import module_audit

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}

OPTIONAL = [m for m in REGISTRY if not m.core]
# One real GET route per optional module (a path under one of its prefixes).
PROBE = {
    "finance": "/finance/categories",
    "mutual_funds": "/mutual-funds/holdings",
    "brain": "/brain/health",
    "discover": "/compare",
    "today": "/beginner/events",
    "watchlist": "/me/watchlist",
    "reports": "/real-report",
    "research_lanes": "/research/lanes",
}
# Areas that no module owns on purpose (shared plumbing and v1 trading screens). A new area must be declared in
# the registry or be added here deliberately, so nothing exists that the registry does not know about.
UNOWNED_OK = {
    "/", "/status", "/refresh-data", "/market", "/market-data", "/instruments", "/signals", "/strategies",
    "/ml", "/model-registry", "/experiments", "/backtest", "/notifications", "/ops", "/me", "/account",
    "/billing", "/config",
}  # fmt: skip


@pytest.fixture()
def durable_in_test(monkeypatch, db_session):
    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(module_audit, "_new_session", same_session)
    return db_session


@pytest.fixture()
def who(db_session):
    """Sign-in per module: the shared key, except the watchlist, which answers only a person's own account."""
    u = User(username="lifecycle-291", hashed_password="x", is_active=True, plan="free", role="member")
    db_session.add(u)
    db_session.flush()
    own = {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}
    return lambda module: own if module == "watchlist" else KEY


def _declared_paths() -> set[str]:
    from swing_trade_ml.main import app

    return {p.removeprefix(API) for p in app.openapi()["paths"] if p.startswith(API)}


def test_every_part_of_the_app_named_in_the_issue_is_declared():
    ids = {m.id for m in REGISTRY}
    # Discover, Today, Watchlist (with the Groww Tracker), Portfolio, Reports, Admin, Brain views, research lanes, Finance
    assert {
        "discover",
        "today",
        "watchlist",
        "core.portfolio",
        "reports",
        "core.admin",
        "brain",
        "research_lanes",
        "finance",
    } <= ids
    assert modules.switches.module("finance").state is modules.ModuleState.PARKED


def test_every_optional_module_has_a_probe_route_in_this_test():
    assert {m.id for m in OPTIONAL} == set(PROBE)


def test_every_declared_package_exists():
    missing = [(m.id, p) for m in REGISTRY for p in m.packages if importlib.util.find_spec(p) is None]
    assert missing == []


def test_every_api_path_is_owned_by_a_module_or_named_here_as_unowned():
    stray = sorted(
        p
        for p in _declared_paths()
        if modules.switches.module_for_path(p) is None
        and ("/" + p.strip("/").split("/")[0]) not in UNOWNED_OK
    )
    assert stray == []


@pytest.mark.parametrize("module", [m.id for m in OPTIONAL])
def test_lifecycle_off_refuses_routes_removes_jobs_leaves_the_rest_alone_and_on_restores(
    client, durable_in_test, who, module
):
    probe = PROBE[module]
    mod = modules.switches.module(module)
    assert any(probe == p or probe.startswith(p + "/") for p in mod.route_prefixes)
    assert "switched off" not in client.get(f"{API}{probe}", headers=who(module)).text
    before = client.get(f"{API}{probe}", headers=who(module)).status_code

    class Sched:
        def __init__(self):
            self.jobs = set(mod.jobs) | {"heartbeat", "flush_alerts"}

        def get_job(self, job_id):
            return object() if job_id in self.jobs else None

        def remove_job(self, job_id):
            self.jobs.remove(job_id)

    with modules.switches.switched_off(module, by="lifecycle-test", reason="lifecycle test"):
        refused = client.get(f"{API}{probe}", headers=who(module))
        assert refused.status_code == 403 and "switched off" in refused.json()["detail"]
        sched = Sched()
        apply_to_scheduler(sched)
        assert not (set(mod.jobs) & sched.jobs)  # its jobs are absent
        assert {"heartbeat", "flush_alerts"} <= sched.jobs  # nothing else was removed
        assert client.get(f"{API}/orders", headers=KEY).status_code == 200  # core untouched
        assert client.get(f"{API}/health").status_code == 200
        for other in OPTIONAL:
            if other.id != module:
                assert (
                    "switched off" not in client.get(f"{API}{PROBE[other.id]}", headers=who(other.id)).text
                ), other.id
    assert client.get(f"{API}{probe}", headers=who(module)).status_code == before


def test_the_always_on_paths_of_an_optional_module_keep_answering_while_it_is_off(client, durable_in_test):
    with modules.switches.switched_off("brain", by="lifecycle-test", reason="lifecycle test"):
        assert "switched off" not in client.get(f"{API}/brain/stage", headers=KEY).text


@pytest.mark.parametrize("module", [m.id for m in REGISTRY if m.core])
def test_every_core_module_refuses_to_go_off(module):
    s = ModuleSwitches()
    with pytest.raises(modules.CoreModuleError):
        s.set_enabled(module, False, by="t", reason="try")
    assert s.enabled(module) is True


def test_a_retired_module_stays_declared_stays_off_and_can_never_come_back():
    """Retiring only turns a module off for good: its id and prefixes still resolve and the registry has no write
    path to any module's data."""
    retired = modules.Module("old", "Old part", state=modules.ModuleState.RETIRED, route_prefixes=("/old",))
    s = ModuleSwitches([retired])
    assert s.enabled("old") is False
    with pytest.raises(modules.ModuleError):
        s.set_enabled("old", True, by="t", reason="try")
    assert s.module_for_path("/old/x") is retired


def test_adding_a_module_is_one_declaration_and_nothing_else():
    """#259: a new connector or model family is added by one table entry; the registry then guards, lists and
    switches it with no other code."""
    new = modules.Module("new_feed", "A new data feed", route_prefixes=("/new-feed",), jobs=("new_feed_job",))
    s = ModuleSwitches([*REGISTRY, new])
    assert s.enabled("new_feed") and s.module_for_path("/new-feed/x") is new
    with s.switched_off("new_feed"):
        assert "new_feed_job" in s.jobs_to_skip()
    assert "new_feed_job" not in s.jobs_to_skip()


def test_the_admin_inventory_row_names_what_a_module_owns_and_needs():
    row = admin_modules._row(modules.switches.module("brain"))
    assert row["route_prefixes"] == ["/brain"] and "brain_nightly" in row["jobs"]
    assert row["capabilities"] == ["trademind"] and row["packages"] and row["depends_on"] == []
