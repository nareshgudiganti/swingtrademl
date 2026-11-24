"""#416: GET /config/trading-rules serves the numbers and calendar the screens show (read-only, signed in)."""

from __future__ import annotations

from datetime import date
from itertools import count

import pytest

from swing_trade_ml.core import research_config
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.holidays import NSE_HOLIDAYS
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import trading_rules
from swing_trade_ml.services.plans import set_plans_enabled

URL = "/api/v1/config/trading-rules"
_n = count()


def person(db, role, plan="free"):
    u = User(username=f"tr-{role}-{next(_n)}", hashed_password="x", is_active=True, plan=plan, role=role)
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def test_it_needs_a_sign_in(client):
    assert client.get(URL).status_code in (401, 403)


@pytest.mark.parametrize("role", ["owner", "member", "tester"])
def test_every_signed_in_person_reads_it_on_every_plan(client, db_session, role):
    set_plans_enabled(db_session, True)
    for plan in ("free", "pro"):
        r = client.get(URL, headers=person(db_session, role, plan))
        assert r.status_code == 200, (role, plan, r.text)


def test_the_shared_key_reads_it(client):
    assert client.get(URL, headers={"X-API-Key": "test-api-key"}).status_code == 200


def test_the_numbers_are_the_versioned_config_and_the_brain_plan_settings(client):
    body = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()
    version = research_config.get_version(research_config.ACTIVE_VERSION)
    assert body["research"]["version"] == "hz-rules-v1" == version.version
    assert body["research"]["sha256"] == version.sha256
    by_horizon = {h["horizon"]: h for h in body["research"]["horizons"]}
    assert set(by_horizon) == {5, 10, 15}
    assert by_horizon[5]["research_only"] is False
    assert by_horizon[10]["research_only"] is True and by_horizon[15]["research_only"] is True
    assert (by_horizon[5]["target_pct"], by_horizon[5]["stop_pct"]) == (0.02, 0.04)
    # the brain's 15-day plan as it exists in the settings: +8% target, -4% stop, half out at +5%, 15 sessions
    assert body["brain_plan"] == {
        "target_pct": settings.ML_TARGET_RETURN_PCT,
        "stop_pct": settings.ML_STOP_RETURN_PCT,
        "half_out_pct": settings.ML_FIRST_TARGET_PCT,
        "max_sessions": settings.ML_PREDICTION_HORIZON_DAYS,
    }
    plan = {"target_pct": 0.08, "stop_pct": 0.04, "half_out_pct": 0.05, "max_sessions": 15}
    assert body["brain_plan"] == plan


def test_the_drawdown_limit_is_served_read_only_from_the_setting_that_enforces_it(client):
    body = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()
    assert body["risk_limits"] == {"max_drawdown_pct": settings.MAX_PORTFOLIO_DRAWDOWN_PCT}
    assert body["risk_limits"]["max_drawdown_pct"] == 0.15
    # nothing writes it: the only routes on this path are the read
    paths = {r.path for r in client.app.routes if "trading-rules" in getattr(r, "path", "")}
    assert all(
        getattr(r, "methods", set()) <= {"GET", "HEAD"}
        for r in client.app.routes
        if getattr(r, "path", "") in paths
    )


def test_the_trial_and_the_calendar_come_from_their_services(client):
    body = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()
    assert body["trial"]["start"] == "2026-10-14"
    assert body["trial"]["min_sessions"] == 15
    listed = {d for days in NSE_HOLIDAYS.values() for d in days}
    assert set(body["calendar"]["holidays"]) == {d.isoformat() for d in listed}
    assert body["calendar"]["holidays"] == sorted(body["calendar"]["holidays"])
    assert {"2026-10-20", "2026-11-10"} <= set(body["calendar"]["holidays"])


def test_the_session_count_skips_weekends_and_holidays():
    # 14 Oct (Wed) .. 21 Oct: Wed 14, Thu 15, Fri 16, Mon 19, [Tue 20 is a holiday], Wed 21
    assert trading_rules.trial_sessions_so_far(date(2026, 10, 13)) == 0
    assert trading_rules.trial_sessions_so_far(date(2026, 10, 14)) == 1
    assert trading_rules.trial_sessions_so_far(date(2026, 10, 18)) == 3
    assert trading_rules.trial_sessions_so_far(date(2026, 10, 20)) == 4
    assert trading_rules.trial_sessions_so_far(date(2026, 10, 21)) == 5
    assert trading_rules.trading_rules(date(2026, 10, 21))["trial"]["sessions_so_far"] == 5


def test_it_changes_nothing(client, db_session):
    from sqlalchemy import func, select

    from swing_trade_ml.db.models.audit import AuditLog

    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    client.get(URL, headers={"X-API-Key": "test-api-key"})
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before
    assert client.post(URL, headers={"X-API-Key": "test-api-key"}).status_code == 405


def test_the_brain_plan_is_the_brains_own_constants_even_when_the_v1_settings_are_overridden(
    client, monkeypatch
):
    """Production sets the v1 target to 0.02; the brain's own 15-day plan is a separate rule."""
    from swing_trade_ml.brain import replay_scoring

    monkeypatch.setattr(settings, "ML_TARGET_RETURN_PCT", 0.02)
    monkeypatch.setattr(settings, "ML_STOP_RETURN_PCT", 0.07)
    monkeypatch.setattr(settings, "ML_FIRST_TARGET_PCT", 0.01)
    monkeypatch.setattr(settings, "ML_PREDICTION_HORIZON_DAYS", 5)
    plan = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()["brain_plan"]
    assert plan == {
        "target_pct": replay_scoring.TARGET,
        "stop_pct": replay_scoring.STOP,
        "half_out_pct": replay_scoring.HALF_OUT,
        "max_sessions": replay_scoring.HORIZON_BARS,
    }
    assert plan == {"target_pct": 0.08, "stop_pct": 0.04, "half_out_pct": 0.05, "max_sessions": 15}


def test_the_brain_plan_agrees_with_the_decision_policy_defaults():
    from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy

    plan = trading_rules.trading_rules(date(2026, 10, 21))["brain_plan"]
    policy = DecidePolicy()
    assert plan == {
        "target_pct": policy.target_pct,
        "stop_pct": policy.stop_pct,
        "half_out_pct": policy.first_target_pct,
        "max_sessions": policy.horizon_days,
    }


def test_only_the_owner_is_served_the_research_only_horizons(client, db_session):
    def horizons(headers):
        body = client.get(URL, headers=headers).json()
        return {h["horizon"] for h in body["research"]["horizons"]}

    assert horizons({"X-API-Key": "test-api-key"}) == {5, 10, 15}
    assert horizons(person(db_session, "owner")) == {5, 10, 15}
    for role in ("member", "tester"):
        seen = horizons(person(db_session, role))
        assert seen == {5}, (role, seen)
    body = client.get(URL, headers=person(db_session, "member")).json()
    assert all(h["research_only"] is False for h in body["research"]["horizons"])
    assert "0.035" not in str(body) and "0.06" not in str(body)
