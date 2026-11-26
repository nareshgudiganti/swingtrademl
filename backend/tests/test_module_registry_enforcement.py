# ruff: noqa: E501  (long plain-English test sentences)
"""Registry follow-up (#291 cross-review): a declared optional module is really guarded, jobs are enforced where
they can be, and every switch is written to the app's durable audit log.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from swing_trade_ml.core import modules
from swing_trade_ml.core.modules import REGISTRY, ModuleSwitches, apply_to_scheduler
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.services import module_audit

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}


@pytest.fixture()
def durable_in_test(monkeypatch, db_session):
    """The durable audit sink writes into the test's own (rolled-back) session instead of opening a new one."""

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(module_audit, "_new_session", same_session)
    return db_session


def _ids_of(dependencies) -> set[str]:
    """Module ids of the registry guards among these `Depends(...)` entries."""
    return {mid for d in dependencies if (mid := getattr(d.dependency, "module_id", None))}


def _routes_with_guards() -> list[tuple[str, set[str]]]:
    """(path, ids of the module guards on it) for every route of the v1 router, however FastAPI stores the includes:
    an included router keeps the include-time dependencies (`protected`, the module guard) beside its own routes."""
    from swing_trade_ml.api.v1.router import api_router

    out: list[tuple[str, set[str]]] = []
    for entry in api_router.routes:
        context = getattr(entry, "include_context", None)
        if context is not None:  # an included router (newer FastAPI)
            included = _ids_of(context.dependencies)
            for route in context.included_router.routes:
                if isinstance(route, APIRoute):
                    out.append((context.prefix + route.path, included | _ids_of(route.dependencies)))
        elif isinstance(entry, APIRoute):
            out.append((entry.path, _ids_of(entry.dependencies)))
    return out


# ---------------------------------------------------------------- every declared optional module is guarded
def test_every_route_under_a_declared_optional_module_carries_that_modules_guard():
    optional = {m.id for m in REGISTRY if not m.core and m.route_prefixes}
    seen: dict[str, int] = dict.fromkeys(optional, 0)
    unguarded: list[tuple[str, str]] = []
    for path, guards in _routes_with_guards():
        owner = modules.switches.module_for_path(path)
        if owner is None or owner.core or owner.id not in optional:
            continue
        seen[owner.id] += 1
        if owner.id not in guards:
            unguarded.append((owner.id, path))
    assert unguarded == [], f"declared but not guarded: {unguarded[:8]}"
    assert all(count > 0 for count in seen.values()), f"a module has no routes under its prefixes: {seen}"


def test_a_core_route_is_never_behind_an_optional_modules_guard():
    walked = 0
    for path, guards in _routes_with_guards():
        owner = modules.switches.module_for_path(path)
        if owner is not None and owner.core:
            walked += 1
            assert guards == set(), path
    assert walked > 0


@pytest.mark.parametrize("module", ["mutual_funds", "brain", "research_lanes"])
def test_switching_a_module_off_refuses_its_routes_and_back_on_restores_them(client, durable_in_test, module):
    probe = {
        "mutual_funds": "/mutual-funds/search?q=zz",
        "brain": "/brain/modules",
        "research_lanes": "/research/lanes",
    }[module]
    before = client.get(f"{API}{probe}", headers=KEY).status_code
    # the baseline is whatever the app answered before; it is never the "switched off" answer
    assert "switched off" not in client.get(f"{API}{probe}", headers=KEY).text
    with modules.switches.switched_off(module, by="registry-test", reason="guard test"):
        refused = client.get(f"{API}{probe}", headers=KEY)
        assert refused.status_code == 403 and "switched off" in refused.json()["detail"]
        assert client.get(f"{API}/orders", headers=KEY).status_code == 200  # a core route is untouched
    assert client.get(f"{API}{probe}", headers=KEY).status_code == before


# ---------------------------------------------------------------- jobs
class _FakeScheduler:
    def __init__(self, ids):
        self.jobs = set(ids)
        self.removed: list[str] = []

    def get_job(self, job_id):
        return object() if job_id in self.jobs else None

    def remove_job(self, job_id):
        self.jobs.remove(job_id)
        self.removed.append(job_id)


def test_jobs_of_a_module_that_is_off_are_removed_from_the_scheduler_and_nothing_else():
    s = ModuleSwitches()
    all_ids = {job for m in REGISTRY for job in m.jobs} | {"heartbeat", "check_exits"}
    scheduler = _FakeScheduler(all_ids)
    assert apply_to_scheduler(scheduler, s) == []  # defaults: every module on, nothing removed
    assert scheduler.jobs == all_ids
    s.set_enabled("brain", False, by="owner", reason="test")
    removed = apply_to_scheduler(scheduler, s)
    brain_jobs = set(next(m for m in REGISTRY if m.id == "brain").jobs)
    assert set(removed) == brain_jobs and scheduler.jobs == all_ids - brain_jobs
    assert {"heartbeat", "check_exits"} <= scheduler.jobs
    assert apply_to_scheduler(scheduler, s) == []  # a second pass finds nothing left to remove


def test_a_job_that_was_never_added_is_not_an_error():
    s = ModuleSwitches()
    s.set_enabled("mutual_funds", False, by="owner", reason="test")
    assert apply_to_scheduler(_FakeScheduler(set()), s) == []


def test_the_scheduler_applies_the_registry_before_it_starts():
    source = (Path(modules.__file__).parent.parent / "workers" / "scheduler.py").read_text(encoding="utf8")
    start = source.index("def start_scheduler")
    body = source[start:]
    assert "apply_to_scheduler(scheduler)" in body
    assert body.index("apply_to_scheduler(scheduler)") < body.index("scheduler.start()")


def test_the_registry_says_what_it_enforces_and_where():
    assert modules.ENFORCEMENT["routes"].startswith("enforced")
    assert "every run" in modules.ENFORCEMENT["jobs"] and "database" in modules.ENFORCEMENT["scope"]
    s = ModuleSwitches()
    s.set_enabled("brain", False, by="owner", reason="test")
    assert s.events[-1]["scope"] == modules.ENFORCEMENT["scope"]


# ---------------------------------------------------------------- the durable audit log
def test_the_default_registry_writes_every_switch_to_the_apps_audit_log(durable_in_test, db_session):
    s = modules.switches
    with s.switched_off("finance", by="registry-test", reason="audit test"):
        pass
    rows = list(
        db_session.scalars(select(AuditLog).where(AuditLog.action == "module.switch").order_by(AuditLog.id))
    )
    assert [(r.actor_label, r.target_type, r.target_id) for r in rows[-2:]] == [("registry-test", "module", "finance")] * 2
    first, second = rows[-2:]
    assert first.before == {"enabled": True} and first.after["enabled"] is False
    assert first.after["outcome"] == "applied" and first.after["reason"] == "audit test"
    assert second.before == {"enabled": False} and second.after["enabled"] is True


def test_a_refused_request_is_in_the_audit_log_too(durable_in_test, db_session):
    with pytest.raises(modules.CoreModuleError):
        modules.switches.set_enabled("core.orders", False, by="registry-test", reason="must refuse")
    row = db_session.scalars(select(AuditLog).where(AuditLog.action == "module.switch").order_by(AuditLog.id.desc())).first()
    assert row.target_id == "core.orders" and row.after["outcome"].startswith("refused")


def test_a_failing_audit_write_stops_the_change(monkeypatch, db_session):
    @contextmanager
    def broken():
        raise RuntimeError("audit store is down")
        yield db_session  # pragma: no cover

    monkeypatch.setattr(module_audit, "_new_session", broken)
    assert modules.switches.enabled("finance")
    with pytest.raises(RuntimeError):
        modules.switches.set_enabled("finance", False, by="registry-test", reason="audit down")
    assert modules.switches.enabled("finance"), "nothing is switched without its durable record"


def test_the_live_registry_uses_the_durable_sink_not_nothing():
    assert modules.switches._audit is not None
    assert modules.switches._audit is modules.durable_audit
