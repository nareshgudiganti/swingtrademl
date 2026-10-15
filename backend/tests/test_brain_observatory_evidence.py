"""Evidence plan A3 and A5: results kept apart by category, each read from the code that already owns it,
and every number in the monthly pack reconciles with the screen that already shows it. Plus owner-only,
GET-only and read-only for the pack's route (Observatory spec 3.5)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainModuleSetting, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import engine
from swing_trade_ml.services.brain_observatory import evidence, outcomes, pack
from swing_trade_ml.services.plans import set_plans_enabled

API_KEY = {"X-API-Key": "test-api-key"}
IST = ZoneInfo("Asia/Kolkata")
DECIDED = date(2026, 1, 5)  # a Monday
NOW = datetime(2026, 3, 31, 18, 0, tzinfo=IST)
URL = "/api/v1/brain/observatory"


@pytest.fixture()
def obs_client(client, db_session):
    """The API client, with the Observatory's read-only session pointed at the test transaction (so the
    seeded rows are visible and nothing is committed) and a fixed clock."""
    from swing_trade_ml.api.v1.endpoints import brain_observatory as ep
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    app.dependency_overrides[ep.get_now] = lambda: NOW
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_readonly_db, None)
        app.dependency_overrides.pop(ep.get_now, None)


def _trading_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _seed(db) -> None:
    """Two stocks (one rising, one flat), one live nightly run on DECIDED with a TRADE and a WATCH."""
    for token, sym, step in ((515151, "OBUP", 0.02), (515152, "OBFL", 0.0)):
        inst = Instrument(instrument_token=token, tradingsymbol=sym, exchange="NSE", is_watchlisted=True)
        db.add(inst)
        db.flush()
        price = 100.0
        for d in _trading_days(DECIDED - timedelta(days=45), 50):
            nxt = price * (1 + step)
            db.add(
                Candle(
                    instrument_id=inst.id,
                    interval="day",
                    ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                    open=price,
                    high=max(price, nxt) * 1.001,
                    low=min(price, nxt) * 0.999,
                    close=nxt,
                    volume=1000,
                )
            )
            price = nxt
    db.add(
        BrainRun(
            id="obs-ev-run-1",
            kind="nightly",
            live=True,
            status="done",
            book="paper",
            as_of=datetime(2026, 1, 5, 10, 20, tzinfo=UTC),
            banner_mode="NORMAL",
        )
    )
    db.flush()
    db.add_all(
        [
            BrainDecision(
                run_id="obs-ev-run-1",
                symbol="OBUP",
                kind="idea",
                word="TRADE",
                confidence=0.85,
                score_source="model",
                stop=96.0,
                target=108.0,
            ),
            BrainDecision(
                run_id="obs-ev-run-1",
                symbol="OBFL",
                kind="idea",
                word="WATCH",
                confidence=0.4,
                score_source="model",
            ),
        ]
    )
    db.flush()


def _strip(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "redacted_fields"}


# --- category isolation (A3) -------------------------------------------------------------------


def test_results_from_different_categories_cannot_be_combined():
    a = evidence.Evidence(evidence.Category.PRACTICE, "x", {})
    b = evidence.Evidence(evidence.Category.BACKTEST, "y", {})
    assert evidence.require_one_category([a, a]) == evidence.Category.PRACTICE
    with pytest.raises(evidence.MixedCategoriesError):
        evidence.require_one_category([a, b])
    with pytest.raises(evidence.MixedCategoriesError):
        evidence.require_one_category([])


def test_the_categories_are_the_observatorys_three():
    assert tuple(c.value for c in evidence.Category) == outcomes.CATEGORIES


def test_backtest_is_the_observatorys_verdicts(obs_client):
    bt = evidence.backtest()
    assert bt.category == evidence.Category.BACKTEST
    assert "verdicts.evaluate" in bt.source
    screen = obs_client.get(f"{URL}/effectiveness", headers=API_KEY).json()
    assert bt.data["claims"] == screen["claims"]
    assert bt.data["rejected_entries"] == screen["rejected_entries"]


def test_pack_keeps_the_three_categories_apart(db_session):
    _seed(db_session)
    built = pack.build_pack(db_session, "2026-01", NOW.date())
    assert set(built["sections"]) == {"practice", "paper", "backtest"}
    for key, section in built["sections"].items():
        assert section["category"] == key
    # nothing at the top level adds the sections up
    numeric_top = {
        k for k, val in built.items() if isinstance(val, int | float) and not isinstance(val, bool)
    }
    assert numeric_top == set()
    report = pack.plain_report(built)
    assert "never added" in report and "Observed, not proof" in report
    for name in evidence.CATEGORY_NAMES.values():
        assert name in report


# --- reconciliation (A1, A3, A5) ----------------------------------------------------------------


def test_paper_section_equals_the_performance_screen(obs_client, db_session):
    _seed(db_session)
    screen = obs_client.get("/api/v1/portfolio/summary?mode=paper", headers=API_KEY).json()
    r = obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY)
    assert r.status_code == 200
    assert r.json()["pack"]["sections"]["paper"]["data"] == screen


def test_practice_section_equals_the_outcomes_page(obs_client, db_session):
    _seed(db_session)
    page = obs_client.get(
        f"{URL}/outcomes?from=2026-01-01&to=2026-01-31&category=practice", headers=API_KEY
    ).json()
    got = obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).json()["pack"]
    practice = got["sections"]["practice"]
    assert practice["data"] == _strip(page)
    assert practice["data"]["computed"]["candidate"]["picked"] == 1


def test_forward_gate_is_the_whole_trial_not_the_month(obs_client, db_session):
    _seed(db_session)
    gate = obs_client.get(f"{URL}/forward-gate", headers=API_KEY).json()
    got = obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).json()["pack"]
    assert got["sections"]["practice"]["forward_gate"] == _strip(gate)
    assert gate["cohort_from"] == "2026-10-14"


def test_pack_baselines_cover_the_recorded_ideas(obs_client, db_session):
    _seed(db_session)
    got = obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).json()["pack"]
    practice = got["sections"]["practice"]
    base = practice["baselines"]
    assert base["available"] and base["sessions"] == 1
    trade = base["trade_level"]["brain_trade"]
    assert trade["candidate"]["picked"] == 1 and trade["every_stock"]["picked"] == 2
    assert trade["candidate"]["avg_net"] > trade["every_stock"]["avg_net"]
    # the "Brain says TRADE" row is the Outcomes page's own computed row
    computed = practice["data"]["computed"]
    assert trade["candidate"]["avg_net"] == computed["candidate"]["avg_net"]
    assert trade["every_stock"]["avg_net"] == computed["every_stock"]["avg_net"]
    port = base["portfolio_level"]["brain_trade"]
    assert port["candidate"]["final_net_return"] > 0
    assert port["defs"] == "evidence-defs-v1"


def test_report_is_written_from_the_pack(obs_client, db_session):
    _seed(db_session)
    body = obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).json()
    assert body["report"] == pack.plain_report(body["pack"])
    assert "Brain says TRADE" in body["report"] and "Forward gate over the whole trial" in body["report"]


def test_an_empty_month_says_so(obs_client):
    body = obs_client.get(f"{URL}/evidence-pack?month=2026-02", headers=API_KEY).json()
    assert body["pack"]["sections"]["practice"]["baselines"] == {"available": True, "sessions": 0}
    assert "No live nightly brain runs" in body["report"]


# --- input checks, access, read-only ------------------------------------------------------------


def test_bad_inputs_are_refused(obs_client):
    assert obs_client.get(f"{URL}/evidence-pack?month=2026-13", headers=API_KEY).status_code == 422
    assert obs_client.get(f"{URL}/evidence-pack?month=2026-04", headers=API_KEY).status_code == 422
    assert obs_client.get(f"{URL}/evidence-pack", headers=API_KEY).status_code == 422


@pytest.mark.parametrize("plans_on", [False, True])
@pytest.mark.parametrize("plan", ["free", "pro"])
def test_owner_only(obs_client, db_session, plan, plans_on):
    set_plans_enabled(db_session, plans_on)
    user = User(username=f"obs-ev-{plan}", hashed_password="x", is_active=True, is_superuser=False, plan=plan)
    db_session.add(user)
    db_session.flush()
    guest = {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}
    assert obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=guest).status_code == 403
    assert obs_client.get(f"{URL}/evidence-pack?month=2026-01").status_code == 401


def test_hidden_while_the_brain_is_off(obs_client, monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)
    assert obs_client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).status_code == 404


def test_the_route_is_get_only():
    from swing_trade_ml.api.v1.endpoints.brain_observatory import router

    methods = {m for r in router.routes if r.path.endswith("/evidence-pack") for m in r.methods}
    assert methods == {"GET"}


def test_the_pack_runs_in_the_read_only_session(client, monkeypatch):
    """No override: the real READ ONLY session. The whole pack (paper figures included) builds in it, and a
    write slipped into it is refused by Postgres."""
    from swing_trade_ml.api.v1.endpoints import brain_observatory as ep
    from swing_trade_ml.main import app

    app.dependency_overrides[ep.get_now] = lambda: NOW
    try:
        assert client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY).status_code == 200

        real = pack.practice_baselines

        def sneaky(db, *a, **k):
            db.execute(text("INSERT INTO brain_modules (module_id, mode) VALUES ('OBEV', 'on')"))
            return real(db, *a, **k)

        monkeypatch.setattr(pack, "practice_baselines", sneaky)
        with pytest.raises(DBAPIError, match="read-only"):
            client.get(f"{URL}/evidence-pack?month=2026-01", headers=API_KEY)
    finally:
        app.dependency_overrides.pop(ep.get_now, None)
    with Session(engine) as check:
        assert check.get(BrainModuleSetting, "OBEV") is None
