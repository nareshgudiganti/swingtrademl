"""bx1: the stock brief answers six plain questions from stored data only."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from observatory_fixtures import (  # noqa: F401 — fixtures
    SYM_PREFIX,
    TOKEN_BASE,
    committed,
    make_decision,
    make_run,
    obs_ns,
)
from swing_trade_ml.api.v1.endpoints import beginner
from swing_trade_ml.brain import service
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.beginner_views import money_at_stake, stock_brief

HEADERS = {"X-API-Key": "test-api-key"}
TODAY = date(2026, 10, 16)
AS_OF = datetime(2026, 10, 16, 10, 20, tzinfo=UTC)  # 15:50 IST
SYM = "BXSTOCKA"


@pytest.fixture(autouse=True)
def _wiring(db_session, monkeypatch):
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    def boom(*a, **k):
        raise AssertionError("the stock brief must never run the brain")

    monkeypatch.setattr(service, "run_brain", boom)
    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield
    app.dependency_overrides.pop(get_readonly_db, None)


def _inst(db, symbol=SYM, name="Bx Stock Ltd"):
    db.add(Instrument(instrument_token=hash(symbol) % 10**8 + 5_000_000_000, tradingsymbol=symbol, name=name))
    db.flush()


def _run(db, rid, as_of=AS_OF, kind="nightly", book="paper", live=True):
    db.add(BrainRun(id=rid, kind=kind, as_of=as_of, book=book, live=live, status="done"))
    db.flush()


def _dec(db, rid, **kw):
    base = dict(
        run_id=rid,
        symbol=SYM,
        kind="idea",
        word="TRADE",
        entry_low=100.0,
        entry_high=102.0,
        target=108.0,
        stop=96.0,
        qty=10,
        horizon_days=15,
        confidence=70.0,
        reasons=["Trend is up"],
    )
    base.update(kw)
    d = BrainDecision(**base)
    db.add(d)
    db.flush()
    return d


def test_unknown_symbol_is_404(client):
    r = client.get("/api/v1/beginner/stock/NOSUCHXX", headers=HEADERS)
    assert r.status_code == 404
    assert r.json()["detail"] == "Not a stock we follow"


def test_requires_auth(client, db_session):
    _inst(db_session)
    assert client.get(f"/api/v1/beginner/stock/{SYM}").status_code == 401


def test_no_decision_names_last_run_and_hides_figures(db_session):
    _inst(db_session)
    _run(db_session, "bx-old", as_of=datetime(2026, 10, 15, 10, 20, tzinfo=UTC))
    out = stock_brief(db_session, SYM, TODAY)
    assert list(out)[:2] == ["symbol", "as_of"]
    for k in ("q1_company", "q2_brain", "q3_plan", "q4_money", "q5_events", "q6_evidence"):
        assert k in out
    for k in ("q2_brain", "q3_plan", "q4_money"):
        assert out[k]["available"] is False
        assert "15 Oct 2026" in out[k]["why"]
    assert out["q2_brain"]["answer"] == "The brain has not looked at this stock today"
    assert "decision" not in out["q2_brain"]
    assert out["q4_money"].get("invested") is None


def test_no_decision_and_no_run_at_all(db_session):
    _inst(db_session)
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q2_brain"]["available"] is False
    assert "no brain run" in out["q2_brain"]["why"].lower()


def test_stock_missing_from_latest_run_is_not_looked_at(db_session):
    _inst(db_session)
    _run(db_session, "bx-old", as_of=datetime(2026, 10, 14, 10, 20, tzinfo=UTC))
    _dec(db_session, "bx-old")
    _run(db_session, "bx-new")  # newest run did not include the stock
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q2_brain"]["available"] is False
    assert "16 Oct 2026" in out["q2_brain"]["why"]


def test_trade_decision_fills_q2_to_q4(db_session):
    _inst(db_session)
    _run(db_session, "bx-new")
    _run(db_session, "bx-why", kind="why")
    _dec(db_session, "bx-new")
    _dec(db_session, "bx-why", word="AVOID", qty=0)  # a "why" run must be ignored
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q1_company"]["available"] and out["q1_company"]["name"] == "Bx Stock Ltd"
    assert out["q2_brain"]["available"] and out["q2_brain"]["decision"]["word"] == "TRADE"
    assert "Trend is up" in out["q2_brain"]["decision"]["reasons"]
    assert out["q3_plan"]["available"] and out["q3_plan"]["buy_zone"] == [100.0, 102.0]
    assert out["q3_plan"]["last_exit_day"] is not None
    expected = money_at_stake(101.0, 96.0, 108.0, 10)
    assert out["q4_money"]["available"] is True
    for k, v in expected.items():
        assert out["q4_money"][k] == v


def test_missing_entry_range_gives_unavailable_money(db_session):
    _inst(db_session)
    _run(db_session, "bx-new")
    _dec(db_session, "bx-new", entry_low=None)
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q4_money"]["available"] is False
    assert out["q4_money"]["why"]


def test_events_and_evidence(db_session):
    _inst(db_session)
    db_session.add(UpcomingEvent(symbol=SYM, kind="results", event_date=date(2026, 10, 19), detail=""))
    db_session.flush()
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q5_events"]["available"] is True
    assert len(out["q5_events"]["events"]) == 1
    assert out["q6_evidence"]["answer"].startswith("Not proven")
    assert out["q6_evidence"]["claim"] == "model_ranking_predictive"


def test_no_events_is_an_answer_not_a_gap(db_session):
    _inst(db_session)
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q5_events"]["available"] is True
    assert out["q5_events"]["events"] == []


def test_route_uses_read_only_db_and_get_only():
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    for route in beginner.router.routes:
        assert {m for m in route.methods} == {"GET"}
        assert any(d.call is get_readonly_db for d in route.dependant.dependencies), route.path


def test_real_read_only_session_serves_the_brief(client, obs_ns):
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides.pop(get_readonly_db, None)  # use the real READ ONLY session
    sym = f"{SYM_PREFIX}Z"
    inst = Instrument(instrument_token=TOKEN_BASE + 7, tradingsymbol=sym, name="Real Ro Ltd")
    now = datetime.now(UTC)  # the endpoint uses the real clock, so the run must be current
    with committed(inst, make_run("ro1", as_of=now), make_decision("ro1", sym, word="WAIT")):
        r = client.get(f"/api/v1/beginner/stock/{sym}", headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["q2_brain"]["decision"]["word"] == "WAIT"


# ---- final-review fixes -----------------------------------------------------


def test_owner_overrule_wins_and_hides_plan_and_money(db_session):
    """F1: a TRADE the owner overruled to AVOID must never read as TRADE or show money figures."""
    _inst(db_session)
    _run(db_session, "bx-new")
    _dec(db_session, "bx-new", overruled_word="AVOID", overrule_reason="Too risky this week")
    out = stock_brief(db_session, SYM, TODAY)
    q2 = out["q2_brain"]
    assert q2["word"] == "AVOID"
    assert q2["answer"].startswith("AVOID")
    assert "You overruled the brain to AVOID: Too risky this week" in q2["answer"]
    for k in ("q3_plan", "q4_money"):
        assert out[k]["available"] is False
        assert out[k]["why"] == "The brain says AVOID, so there is no buy plan"
    assert "buy_zone" not in out["q3_plan"]
    assert out["q4_money"].get("invested") is None


@pytest.mark.parametrize("word", ["WATCH", "WAIT", "AVOID"])
def test_non_trade_word_has_no_buy_plan(db_session, word):
    """F2: a WATCH/WAIT/AVOID with a full zone must not say "Buy between ..."."""
    _inst(db_session)
    _run(db_session, "bx-new")
    _dec(db_session, "bx-new", word=word)
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q3_plan"]["available"] is False
    assert out["q3_plan"]["answer"] == f"No buy plan — the brain says {word}"
    assert out["q4_money"]["available"] is False
    assert out["q4_money"].get("invested") is None


def test_holding_has_no_buy_plan_and_idea_is_preferred(db_session):
    _inst(db_session)
    _run(db_session, "bx-new")
    _dec(db_session, "bx-new", kind="idea", word="TRADE")
    _dec(db_session, "bx-new", kind="holding", word="HOLD")  # newer id, but the idea wins
    assert stock_brief(db_session, SYM, TODAY)["q2_brain"]["word"] == "TRADE"

    _run(db_session, "bx-hold", as_of=datetime(2026, 10, 16, 10, 30, tzinfo=UTC))
    _dec(db_session, "bx-hold", kind="holding", word="HOLD")
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q2_brain"]["word"] == "HOLD"
    assert out["q3_plan"]["available"] is False
    assert out["q4_money"]["available"] is False


@pytest.mark.parametrize(
    "levels",
    [
        {"stop": 103.0},  # stop above the buy zone
        {"target": 101.0},  # target inside the buy zone
        {"entry_low": 103.0, "entry_high": 101.0},  # zone upside down
        {"target": None},
    ],
)
def test_trade_with_levels_out_of_order_is_plan_incomplete(db_session, levels):
    """F2: bad data never yields an "available" plan."""
    _inst(db_session)
    _run(db_session, "bx-new")
    _dec(db_session, "bx-new", **levels)
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q3_plan"]["available"] is False
    assert out["q3_plan"]["why"].startswith("Plan incomplete")
    assert out["q4_money"]["available"] is False
    assert out["q4_money"].get("loss_if_stop") is None


def test_stale_run_is_not_today(db_session):
    """F3: a days-old TRADE (nightly stopped) is not today's: no card, no figures, last run date."""
    _inst(db_session)
    _run(db_session, "bx-stale", as_of=datetime(2026, 10, 13, 10, 20, tzinfo=UTC))
    _dec(db_session, "bx-stale")
    out = stock_brief(db_session, SYM, TODAY)  # Fri 16 Oct; expected run day is Thu 15 Oct or later
    assert out["as_of"].startswith("2026-10-13")
    assert out["q2_brain"]["available"] is False
    assert out["q2_brain"]["answer"] == "The brain has not looked at this stock today"
    assert "13 Oct 2026" in out["q2_brain"]["why"]
    assert "decision" not in out["q2_brain"]
    for k in ("q3_plan", "q4_money"):
        assert out[k]["available"] is False
    assert out["q4_money"].get("invested") is None


def test_previous_trading_day_run_counts_before_tonights_nightly(db_session):
    _inst(db_session)
    _run(db_session, "bx-thu", as_of=datetime(2026, 10, 15, 10, 20, tzinfo=UTC))
    _dec(db_session, "bx-thu")
    assert stock_brief(db_session, SYM, TODAY)["q2_brain"]["available"] is True
    # Monday 19 Oct morning: Friday's run is still the latest expected one.
    _run(db_session, "bx-fri")
    _dec(db_session, "bx-fri", word="WAIT")
    assert stock_brief(db_session, SYM, date(2026, 10, 19))["q2_brain"]["word"] == "WAIT"


@pytest.mark.parametrize("other", [{"live": False}, {"book": "live"}])
def test_replay_or_live_book_runs_are_never_read(db_session, other):
    """F3: a replay (live=False) or a real-money book run is never the stock brief's source."""
    _inst(db_session)
    _run(db_session, "bx-paper", as_of=datetime(2026, 10, 16, 9, 0, tzinfo=UTC))
    _dec(db_session, "bx-paper", word="WAIT")
    _run(db_session, "bx-other", **other)  # newer
    _dec(db_session, "bx-other", word="TRADE")
    out = stock_brief(db_session, SYM, TODAY)
    assert out["q2_brain"]["word"] == "WAIT"
    assert out["as_of"].startswith("2026-10-16T09:00")
