# ruff: noqa: E501  (long plain-English test sentences)
"""The module registry contract (#291): core modules cannot be switched off, optional modules can, dependencies are
honoured, every request is audited, nothing is deleted, and the defaults change nothing.

Unit tests use small made-up registries; the declarations that ship are checked against the real app (every route
prefix and every scheduler job id they name must exist). One integration test switches an optional module off and on
again through the real app with real data.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from swing_trade_ml.core import modules
from swing_trade_ml.core.modules import (
    REGISTRY,
    CoreModuleError,
    DependencyError,
    Module,
    ModuleError,
    ModuleState,
    ModuleSwitches,
    RegistryError,
    UnknownModuleError,
    require_module,
    validate,
)
from test_module_registry_enforcement import durable_in_test  # noqa: F401  (writes the audit rows into the test's session)

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}  # the placeholder the test environment pins (tests/_env_safety.py)


def small() -> ModuleSwitches:
    """core -> nothing; a (optional); b (optional, needs a); c (retired)."""
    return ModuleSwitches(
        (
            Module("core.x", "Core", core=True, route_prefixes=("/x",)),
            Module("a", "A", route_prefixes=("/a",), jobs=("job_a",)),
            Module("b", "B", route_prefixes=("/a/deep", "/b"), jobs=("job_b",), depends_on=("a",)),
            Module("c", "C", state=ModuleState.RETIRED),
        )
    )


def change(s: ModuleSwitches, module: str, on: bool):
    return s.set_enabled(module, on, by="owner", reason="test")


# ---------------------------------------------------------------- core modules never go off
def test_a_core_module_is_always_on_and_cannot_be_switched_off():
    s = small()
    assert s.enabled("core.x")
    with pytest.raises(CoreModuleError):
        change(s, "core.x", False)
    assert s.enabled("core.x")
    assert s.events[-1]["outcome"].startswith("refused") and s.events[-1]["module"] == "core.x"


def test_every_shipped_core_module_refuses_to_go_off():
    s = ModuleSwitches()
    cores = [m.id for m in REGISTRY if m.core]
    assert {"core.auth", "core.safety", "core.orders", "core.health"} <= set(cores)
    for module in cores:
        with pytest.raises(CoreModuleError):
            change(s, module, False)
        assert s.enabled(module)


def test_a_core_module_must_be_active_and_may_not_depend_on_an_optional_one():
    with pytest.raises(RegistryError):
        validate((Module("core.x", "C", core=True, state=ModuleState.PARKED),))
    with pytest.raises(RegistryError):
        validate((Module("opt", "O"), Module("core.x", "C", core=True, depends_on=("opt",))))


# ---------------------------------------------------------------- optional modules
def test_an_optional_module_is_on_by_default_and_can_be_switched_off_and_on():
    s = small()
    assert s.enabled("a") and s.enabled("b")
    assert change(s, "b", False) is True and not s.enabled("b")
    assert change(s, "b", False) is False  # already off: nothing changes (and it is still recorded)
    assert change(s, "b", True) is True and s.enabled("b")


def test_defaults_are_preserved_every_shipped_module_starts_on():
    s = ModuleSwitches()
    assert all(s.enabled(m.id) for m in REGISTRY)
    assert modules.switches.jobs_to_skip() == frozenset()  # the live registry, as the app starts


def test_a_module_that_is_not_active_or_parked_is_off_by_default_and_a_retired_one_can_never_be_on():
    s = ModuleSwitches(
        (
            Module("dev", "D", state=ModuleState.DEVELOPMENT),
            Module("dep", "D", state=ModuleState.DEPRECATED),
            Module("ret", "R", state=ModuleState.RETIRED),
        )
    )
    assert not s.enabled("dev") and not s.enabled("dep") and not s.enabled("ret")
    assert change(s, "dev", True) and s.enabled("dev")
    with pytest.raises(ModuleError, match="retired"):
        change(s, "ret", True)


def test_an_unknown_module_is_an_error_not_a_guess():
    s = small()
    with pytest.raises(UnknownModuleError):
        s.enabled("nope")
    with pytest.raises(UnknownModuleError):
        change(s, "nope", False)
    with pytest.raises(UnknownModuleError):
        require_module("nope")  # fails when the router is built, not on the first request


# ---------------------------------------------------------------- dependencies
def test_a_module_cannot_be_switched_on_while_what_it_needs_is_off():
    s = small()
    change(s, "b", False)
    change(s, "a", False)
    with pytest.raises(DependencyError, match="needs a"):
        change(s, "b", True)
    assert not s.enabled("b")
    change(s, "a", True)
    assert change(s, "b", True)


def test_a_module_cannot_be_switched_off_while_another_one_needs_it_and_nothing_cascades():
    s = small()
    with pytest.raises(DependencyError, match="b depend on a"):
        change(s, "a", False)
    assert s.enabled("a") and s.enabled("b")  # nothing was switched behind the owner's back
    change(s, "b", False)
    assert change(s, "a", False)


def test_a_bad_registry_is_refused_a_duplicate_a_missing_dependency_and_a_cycle():
    with pytest.raises(RegistryError, match="twice"):
        validate((Module("a", "A"), Module("a", "A")))
    with pytest.raises(RegistryError, match="not declared"):
        validate((Module("a", "A", depends_on=("zzz",)),))
    with pytest.raises(RegistryError, match="cycle"):
        validate((Module("a", "A", depends_on=("b",)), Module("b", "B", depends_on=("a",))))


# ---------------------------------------------------------------- audit
def test_every_request_is_audited_including_refusals_and_a_failing_audit_stops_the_change():
    seen: list[dict] = []
    s = ModuleSwitches(small().modules(), audit=seen.append)
    change(s, "b", False)
    change(s, "b", False)
    with pytest.raises(CoreModuleError):
        change(s, "core.x", False)
    assert [(e["module"], e["from"], e["to"], e["outcome"][:7]) for e in seen] == [
        ("b", True, False, "applied"),
        ("b", False, False, "unchang"),
        ("core.x", True, False, "refused"),
    ]
    assert all(e["by"] == "owner" and e["reason"] == "test" and e["at"] for e in seen)
    assert seen == s.events

    def broken(_event: dict) -> None:
        raise RuntimeError("audit store is down")

    s2 = ModuleSwitches(small().modules(), audit=broken)
    with pytest.raises(RuntimeError):
        change(s2, "b", False)
    assert s2.enabled("b"), "nothing is switched without its audit record"


def test_a_change_needs_who_and_why():
    s = small()
    with pytest.raises(ModuleError):
        s.set_enabled("b", False, by="", reason="x")
    with pytest.raises(ModuleError):
        s.set_enabled("b", False, by="owner", reason="  ")
    assert s.enabled("b") and s.events == []


# ---------------------------------------------------------------- routes and jobs
def test_a_path_belongs_to_the_module_with_the_longest_matching_prefix():
    s = small()
    assert s.module_for_path("/a/thing").id == "a"
    assert s.module_for_path("/a/deep/thing").id == "b"
    assert s.module_for_path("/a").id == "a"
    assert s.module_for_path("/apple") is None  # a prefix ends at a path boundary
    assert s.module_for_path("/x/anything").id == "core.x"


def test_jobs_of_a_module_that_is_off_are_listed_to_skip_and_come_back_with_it():
    s = small()
    assert s.jobs_to_skip() == frozenset()
    with s.switched_off("b"):
        assert s.jobs_to_skip() == {"job_b"}
    assert s.jobs_to_skip() == frozenset() and s.enabled("b")
    assert [e["outcome"] for e in s.events] == ["applied", "applied"]


def test_the_guard_does_nothing_while_on_and_says_switched_off_while_off(monkeypatch):
    s = small()
    monkeypatch.setattr(modules, "switches", s)
    guard = require_module("b")
    assert guard() is None
    change(s, "b", False)
    with pytest.raises(HTTPException) as refused:
        guard()
    assert refused.value.status_code == 403 and "switched off" in refused.value.detail


# ---------------------------------------------------------------- the shipped declarations match the real app
def _app_paths() -> set[str]:
    from swing_trade_ml.main import app

    return {p.removeprefix(API) for p in app.openapi()["paths"] if p.startswith(API)}


def test_every_declared_route_prefix_exists_in_the_app():
    paths = _app_paths()
    missing = [
        (m.id, prefix)
        for m in REGISTRY
        for prefix in m.route_prefixes
        if not any(p == prefix or p.startswith(prefix + "/") for p in paths)
    ]
    assert missing == []


def test_every_declared_job_id_exists_in_the_scheduler():
    source = (Path(modules.__file__).parent.parent / "workers" / "scheduler.py").read_text(encoding="utf8")
    ids = set(re.findall(r'id="([a-z_]+)"', source))
    missing = [(m.id, job) for m in REGISTRY for job in m.jobs if job not in ids]
    assert missing == []


def test_the_shipped_registry_is_valid_and_no_two_modules_claim_one_prefix():
    validate(REGISTRY)
    claimed = [p for m in REGISTRY for p in m.route_prefixes]
    assert len(claimed) == len(set(claimed))


# ---------------------------------------------------------------- one optional module off and on, through the real app
@pytest.fixture()
def finance_rows(db_session):
    from datetime import UTC, datetime

    from swing_trade_ml.db.models.finance import FinanceTransaction

    for n in range(3):
        db_session.add(
            FinanceTransaction(
                dedup_key=f"registry-291-{n}",
                txn_date=datetime(2026, 11, 1 + n, tzinfo=UTC),
                month="2026-11",
                description=f"registry test {n}",
                amount=10.0 * (n + 1),
                direction="debit",
                category="Test",
            )
        )
    db_session.flush()
    return FinanceTransaction


def test_finance_off_then_on_through_the_app_refuses_its_routes_keeps_its_data_and_touches_nothing_else(
    client, db_session, finance_rows, durable_in_test  # noqa: F811
):
    """The whole path: the owner's key reads Finance; with the module off every Finance route refuses, but its rows are
    still there, orders, health and another optional module's routes answer as before, and switching back on restores
    the same answers. Both changes are in the audit trail."""
    model = finance_rows
    before = client.get(f"{API}/finance/transactions", headers=KEY)
    assert before.status_code == 200 and {t["description"] for t in before.json()} >= {"registry test 0"}
    rows_before = db_session.scalar(select(func.count()).select_from(model))
    orders_before = client.get(f"{API}/orders", headers=KEY).status_code
    funds_before = client.get(f"{API}/mutual-funds/search?q=zz", headers=KEY).status_code
    events_before = len(modules.switches.events)

    with modules.switches.switched_off("finance", by="registry-test", reason="integration test"):
        for path in ("/finance/transactions", "/finance/categories", "/finance/summary/monthly"):
            refused = client.get(f"{API}{path}", headers=KEY)
            assert refused.status_code == 403 and "switched off" in refused.json()["detail"], path
        assert client.get(f"{API}/finance/transactions").status_code == 401  # sign-in is still checked first
        # the data is untouched
        assert db_session.scalar(select(func.count()).select_from(model)) == rows_before
        # nothing unrelated moved
        assert client.get(f"{API}/orders", headers=KEY).status_code == orders_before
        assert client.get(f"{API}/mutual-funds/search?q=zz", headers=KEY).status_code == funds_before
        assert client.get(f"{API}/health").status_code == 200

    after = client.get(f"{API}/finance/transactions", headers=KEY)
    assert after.status_code == 200 and after.json() == before.json()
    assert db_session.scalar(select(func.count()).select_from(model)) == rows_before
    new = modules.switches.events[events_before:]
    assert [(e["module"], e["from"], e["to"], e["outcome"], e["by"]) for e in new] == [
        ("finance", True, False, "applied", "registry-test"),
        ("finance", False, True, "applied", "registry-test"),
    ]


def test_a_core_module_cannot_be_switched_off_through_the_live_registry_and_the_app_still_answers(
    client, durable_in_test  # noqa: F811
):
    with pytest.raises(CoreModuleError):
        modules.switches.set_enabled("core.orders", False, by="registry-test", reason="must refuse")
    assert client.get(f"{API}/orders", headers=KEY).status_code == 200
    assert modules.switches.events[-1]["outcome"].startswith("refused")
