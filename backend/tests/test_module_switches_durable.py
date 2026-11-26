"""#291 follow-up: research_lanes switched off then on by the owner is seen by an API request and a worker.

Both go through the database; no data is deleted and no safety route is touched.

The worker side is a SEPARATE `ModuleSwitches` instance (as a separate process would have), reading the same
test database; it never shares memory with the API's `modules.switches`.
"""

from __future__ import annotations

from contextlib import contextmanager
from itertools import count

import pyotp
import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, select

from swing_trade_ml.core import modules
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.module_switch import ModuleSwitch
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import module_audit

_n = count()
LANE_URL = "/api/v1/research/lanes"
JOB_ID = "lane_shadow_daily"


@pytest.fixture()
def same_db(monkeypatch, db_session):
    """Every durable read and write (state and audit) goes to the test's own rolled-back session."""

    @contextmanager
    def same_session():
        yield db_session

    monkeypatch.setattr(module_audit, "_new_session", same_session)
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "sudeeksha")  # the one named real-account owner
    modules.switches._loaded_at = None
    yield db_session
    modules.switches._on["research_lanes"] = True
    modules.switches._loaded_at = None


def _headers(db, role):
    u = User(
        username=f"mod-{role}-{next(_n)}",
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="pro",
        role=role,
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def _named_owner(client, db):
    """The named real-account owner, signed in, with two-step set up and a live step-up token."""
    u = User(
        username="sudeeksha", hashed_password="x", is_active=True, is_superuser=True, plan="pro", role="owner"
    )
    db.add(u)
    db.flush()
    hdr = {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}
    secret = client.post("/api/v1/admin/mfa/setup", headers=hdr).json()["secret"]
    r = client.post("/api/v1/admin/mfa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=hdr)
    assert r.status_code == 200, r.text
    return {**hdr, "X-Admin-Mfa": r.json()["step_up_token"]}


def _worker():
    """A separate worker process: its own state object, the same database, no lingering cache."""
    return modules.ModuleSwitches(store=modules.DurableStore(), cache_seconds=0)


def test_research_lanes_off_then_on_is_seen_by_the_api_and_by_a_worker_job(client, same_db):
    owner = _named_owner(client, same_db)
    ran: list[int] = []
    scheduler = BackgroundScheduler()  # never started: only the job's function is exercised
    scheduler.add_job(lambda: ran.append(1), "interval", hours=1, id=JOB_ID)
    worker = _worker()
    assert modules.guard_scheduler_jobs(scheduler, worker) == [JOB_ID]

    def run_job():
        scheduler.get_job(JOB_ID).func()

    # on (the default): the API answers, the worker job runs
    assert client.get(LANE_URL, headers=owner).status_code != 403
    run_job()
    assert ran == [1]

    # the owner switches it off through the admin endpoint
    r = client.put(
        "/api/v1/admin/modules/research_lanes", json={"enabled": False, "reason": "test off"}, headers=owner
    )
    assert r.status_code == 200 and r.json()["enabled"] is False

    # an API request is refused; the worker (its own state, same database) skips the run but keeps the job
    assert client.get(LANE_URL, headers=owner).status_code == 403
    run_job()
    assert ran == [1]
    assert scheduler.get_job(JOB_ID) is not None
    assert same_db.get(ModuleSwitch, "research_lanes").enabled is False

    # switched back on: both resume; nothing was deleted
    r = client.put(
        "/api/v1/admin/modules/research_lanes", json={"enabled": True, "reason": "test on"}, headers=owner
    )
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert client.get(LANE_URL, headers=owner).status_code != 403
    run_job()
    assert ran == [1, 1]

    # both changes are in the audit log
    rows = same_db.scalars(select(AuditLog).where(AuditLog.action == "module.switch")).all()
    assert [r.after["enabled"] for r in rows if r.after.get("outcome") == "applied"] == [False, True]


def test_a_second_process_sees_the_switch_made_in_the_first(same_db):
    api_side = modules.ModuleSwitches(store=modules.DurableStore(), cache_seconds=0)
    other = _worker()
    api_side.set_enabled("research_lanes", False, by="owner", reason="two process check")
    assert other.enabled("research_lanes") is False
    assert other.enabled("brain") is True  # nothing else moved
    api_side.set_enabled("research_lanes", True, by="owner", reason="two process check")
    assert other.enabled("research_lanes") is True


def test_a_core_module_is_refused_by_the_endpoint_and_never_stored(client, same_db):
    owner = _named_owner(client, same_db)
    r = client.put(
        "/api/v1/admin/modules/core.safety", json={"enabled": False, "reason": "no way"}, headers=owner
    )
    assert r.status_code == 403
    assert same_db.scalar(select(func.count()).select_from(ModuleSwitch)) == 0
    assert client.get("/api/v1/admin/modules/../health").status_code in (
        200,
        404,
    )  # path sanity, not a bypass


def test_only_the_owner_can_switch(client, same_db):
    member = _headers(same_db, "member")
    r = client.put(
        "/api/v1/admin/modules/research_lanes",
        json={"enabled": False, "reason": "member try"},
        headers=member,
    )
    assert r.status_code in (401, 403)
    assert modules.switches.enabled("research_lanes") is True


def test_an_unreadable_table_never_switches_anything(same_db):
    class Broken:
        def read(self):
            raise RuntimeError("db down")

        def write(self, *a):
            raise RuntimeError("db down")

    s = modules.ModuleSwitches(store=Broken(), cache_seconds=0)
    assert s.enabled("research_lanes") is True and s.enabled("brain") is True


# ---------------------------------------------------------------- who may switch (review P2-1)
def _put(client, headers, module="research_lanes", on=False):
    return client.put(
        f"/api/v1/admin/modules/{module}", json={"enabled": on, "reason": "who may switch"}, headers=headers
    )


def test_a_second_owner_who_is_not_the_named_real_account_owner_is_refused(client, same_db):
    _named_owner(client, same_db)
    other = _headers(same_db, "owner")  # an owner login, not named in REAL_ACCOUNT_USERS
    assert _put(client, other).status_code == 403
    assert modules.switches.enabled("research_lanes") is True


def test_the_shared_api_key_cannot_switch_a_module(client, same_db):
    assert _put(client, {"X-API-Key": "test-api-key"}).status_code == 403
    assert modules.switches.enabled("research_lanes") is True


def test_the_named_owner_needs_the_step_up_code_even_while_the_mfa_setting_is_off(client, same_db):
    assert settings.ADMIN_MFA_ENFORCED is False
    hdr = _named_owner(client, same_db)
    no_code = {k: v for k, v in hdr.items() if k != "X-Admin-Mfa"}
    assert _put(client, no_code).status_code == 403
    assert modules.switches.enabled("research_lanes") is True
    assert _put(client, hdr).status_code == 200
    _put(client, hdr, on=True)


# ---------------------------------------------------------------- safety is never switchable (review P2-2)
SAFETY_JOBS = ("brain_intraday", "brain_run_queue")


def test_the_holdings_check_and_the_run_queue_are_not_switchable_jobs():
    brain = modules.switches.module("brain")
    for job in SAFETY_JOBS:
        assert job not in brain.jobs
    off = modules.ModuleSwitches()
    off.set_enabled("brain", False, by="owner", reason="check")
    assert not set(SAFETY_JOBS) & off.jobs_to_skip()


def test_with_the_brain_off_the_stage_and_approval_routes_still_answer(client, same_db):
    hdr = _named_owner(client, same_db)
    assert _put(client, hdr, module="brain").status_code == 200
    try:
        assert client.get("/api/v1/brain/runs", headers=hdr).status_code == 403  # a view: switched off
        for path in ("/api/v1/brain/stage", "/api/v1/brain/approvals"):
            r = client.get(path, headers=hdr)
            assert r.status_code != 403 or "switched off" not in r.text, path
        # stage rollback (PUT /brain/stage) is reached, not stopped by the module switch
        body = {"stage": "shadow", "reason": "rollback check"}
        r = client.put("/api/v1/brain/stage", json=body, headers=hdr)
        assert "switched off" not in r.text
    finally:
        _put(client, hdr, module="brain", on=True)


# ---------------------------------------------------------------- review P3s
def test_an_unreadable_table_is_reported_as_state_unknown_and_logged_as_an_error(client, same_db, caplog):
    class Broken:
        def read(self):
            raise RuntimeError("db down")

        def write(self, *a):
            raise RuntimeError("db down")

    s = modules.ModuleSwitches(store=Broken(), cache_seconds=0)
    assert s.state_unknown is True  # nothing has been read yet
    with caplog.at_level("ERROR"):
        assert s.enabled("research_lanes") is True  # falls back to the default
    assert s.state_unknown is True
    assert any(r.levelname == "ERROR" and "module_switches" in r.getMessage() for r in caplog.records)
    healthy = modules.ModuleSwitches(store=modules.DurableStore(), cache_seconds=0)
    healthy.enabled("research_lanes")
    assert healthy.state_unknown is False


def test_the_admin_list_says_when_the_state_is_unknown(client, same_db, monkeypatch):
    hdr = _named_owner(client, same_db)
    assert client.get("/api/v1/admin/modules", headers=hdr).json()["state_unknown"] is False
    monkeypatch.setattr(modules.switches, "_store", type("B", (), {"read": lambda s: 1 / 0})())
    modules.switches._loaded_at = None
    assert client.get("/api/v1/admin/modules", headers=hdr).json()["state_unknown"] is True


def test_a_switch_decides_and_writes_inside_one_exclusive_lock():
    steps: list[str] = []

    class Store:
        def __init__(self):
            self.rows: dict[str, bool] = {}

        @contextmanager
        def exclusive(self):
            steps.append("lock")
            yield
            steps.append("unlock")

        def read(self):
            steps.append("read")
            return dict(self.rows)

        def write(self, module_id, enabled, by, reason):
            steps.append("write")
            self.rows[module_id] = enabled

    s = modules.ModuleSwitches(store=Store(), cache_seconds=0)
    s.set_enabled("research_lanes", False, by="owner", reason="lock check")
    assert steps[0] == "lock" and steps[-1] == "unlock"
    assert "read" in steps[1:-1] and "write" in steps[1:-1]


def test_the_database_store_takes_a_lock_that_only_one_switch_at_a_time_can_hold(same_db):
    with modules.DurableStore().exclusive():
        pass  # acquiring and releasing the database lock works on the test database
