# ruff: noqa: E501 (long plain-English test text)
"""#238: one 5-day large-cap idea across Today, Stock Detail and AI Analysis (verification tests; nothing here changes the app).

Findings note: docs/verification/238-5d-ideas-screens.md. The three screens read the same stored brain decision:
  Today and Stock Detail   GET /brain/runs/latest?kind=nightly  (the idea list), GET /brain/score-trail/{symbol}
                           (the day-by-day score), GET /beginner/stock/{symbol} (the six plain answers)
  AI Analysis              the same latest run, or GET /brain/runs/{run_id}; /brain/why/{symbol} only for a stock the run lacks
                           (it starts a fresh run, so it is not called here)
One fixed dataset: a large-cap stock, a 5-session model (`swing_classifier v2`, prediction_horizon_days = 5) and one finished
nightly run whose stored decision is TRADE with a plan. Cited, not repeated: #385 (the Brain stamps 15 days on a score from a
5-session model), #448/#449/#451 (identity, score ledger, 5-session records), #416 (trading numbers from one endpoint).

Gaps are strict expected failures (`xfail(strict=True, raises=AssertionError)`): they state what the code SHOULD do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST, next_trading_day
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import horizon_nightly
from swing_trade_ml.services.identity import resolve, writer

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}
SYMBOL = "ZZLARGECAP"
FIRST_REASON = "The market is calm and the stock is in an up-trend."
MODEL_LINE = "The active model (swing_classifier v2) ranks this stock 84 today."
PLAN = {"entry_low": 100.0, "entry_high": 101.0, "target": 108.0, "stop": 96.0}
_token = iter(range(860_100_000, 860_200_000))
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _pro_member(db, name="v238-pro") -> dict[str, str]:
    user = User(username=name, hashed_password="x", is_active=True, role="member", plan="pro")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _run(db, run_id: str, *, book="paper", confidence=0.84, when=None, plan=PLAN, symbol=SYMBOL, started=None) -> BrainRun:
    now = when or datetime.now(UTC)
    run = BrainRun(
        id=run_id, kind="nightly", as_of=now, book=book, live=True, status="done",
        started_at=started or now, finished_at=now, banner_mode="NORMAL", banner_headline="The market looks normal.",
        trace=[], context={},
    )
    db.add(run)
    db.flush()
    db.add(
        BrainDecision(
            run_id=run_id, symbol=symbol, kind="idea", word="TRADE", reasons=[FIRST_REASON, MODEL_LINE],
            qty=10, horizon_days=15, confidence=confidence, evidence_text=None, score_source="model", **plan,
        )
    )
    db.flush()
    return run


@pytest.fixture()
def world(db_session, monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)
    inst = Instrument(instrument_token=next(_token), tradingsymbol=SYMBOL, name="Zz Large Cap Limited", exchange="NSE", instrument_type="EQ", is_active=True, is_watchlisted=True)
    model = MLModel(
        name="swing_classifier", version="v2", algorithm="lightgbm", status="ACTIVE", prediction_horizon_days=5,
        label_kind="endpoint", model_role="final", feature_names=["a"], training_symbols=["X"],
    )
    db_session.add_all([inst, model])
    db_session.flush()
    run = _run(db_session, "v238-run")
    # The plain-answers route reads through its own read-only session; point it at the test's session.
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    yield {"db": db_session, "run": run, "model": model, "inst": inst}
    app.dependency_overrides.pop(get_readonly_db, None)


def _get(client, path, headers=KEY):
    return client.get(f"{API}{path}", headers=headers)


def _idea(body: dict) -> dict:
    return next(d for d in body["decisions"] if d["symbol"] == SYMBOL and d["kind"] == "idea")


def _facts(d: dict) -> tuple:
    """What a screen shows of one idea: score, horizon label, plan levels, decision word and the first reason."""
    return (d["confidence"], d["horizon_days"], d["entry_low"], d["entry_high"], d["target"], d["stop"], d["word"], d["reasons"][0])


# ------------------------------------------------------------------------------- one decision behind all three screens


def test_today_and_ai_analysis_read_the_same_stored_decision(client, world):
    """`api/v1/endpoints/brain.py` (`/runs/latest`, `/runs/{id}`, `_decision_out`). The list on Today and the card on AI Analysis
    are the same row: same id, run, score, horizon, plan levels, word and first reason."""
    latest = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())
    by_id = _idea(_get(client, f"/brain/runs/{world['run'].id}").json())
    assert latest["id"] == by_id["id"] and latest["run_id"] == by_id["run_id"] == world["run"].id
    assert _facts(latest) == _facts(by_id) == (0.84, 15, 100.0, 101.0, 108.0, 96.0, "TRADE", FIRST_REASON)


def test_stock_detail_plain_answers_carry_the_same_decision_and_plan(client, world):
    """`services/beginner_views.py:stock_brief` (the six answers on Stock Detail): the same stored decision, the same plan levels."""
    latest = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())
    brief = _get(client, f"/beginner/stock/{SYMBOL}").json()
    decision = brief["q2_brain"]["decision"]
    assert decision["id"] == latest["id"] and decision["run_id"] == latest["run_id"]
    assert _facts(decision) == _facts(latest)
    assert brief["q2_brain"]["word"] == latest["word"] == "TRADE" and FIRST_REASON in brief["q2_brain"]["answer"]
    plan = brief["q3_plan"]
    assert plan["buy_zone"] == [latest["entry_low"], latest["entry_high"]] and plan["target"] == latest["target"] and plan["stop"] == latest["stop"]


def test_the_score_line_on_stock_detail_is_the_score_of_the_same_decision_and_names_its_model(client, world):
    latest = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())
    trail = _get(client, f"/brain/score-trail/{SYMBOL}").json()["score_trail"]
    assert trail[-1]["score"] == latest["confidence"] == 0.84
    assert trail[-1]["model_version"] == "swing_classifier v2"
    assert trail[-1]["date"] == world["run"].started_at.astimezone(IST).date().isoformat()


def test_a_plan_member_is_shown_the_same_score_horizon_levels_word_and_first_reason(client, world):
    """The Pro member's view (`public_verdict`) keeps everything above and only takes the account's size away."""
    member = _pro_member(world["db"])
    shown = _idea(_get(client, "/brain/runs/latest?kind=nightly", member).json())
    owner = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())
    assert _facts(shown) == _facts(owner) and shown["id"] == owner["id"]
    assert shown["qty"] == 0 and owner["qty"] == 10  # the only difference: the account's size


def test_the_last_exit_day_on_stock_detail_counts_the_decisions_own_horizon_from_the_run_date(client, world):
    plan = _get(client, f"/beginner/stock/{SYMBOL}").json()["q3_plan"]
    day = world["run"].as_of.astimezone(IST).date()
    for _ in range(15):
        day = next_trading_day(day)
    assert plan["last_exit_day"] == day.isoformat()


# ------------------------------------------------------------------------------- the idea and its 5-session record


def test_the_idea_traces_to_its_five_session_record_with_the_same_stock_model_and_score(client, world):
    """#448/#449/#451 (on main at this baseline): the nightly writer turns the model's stored 5-session prediction into a horizon
    record keyed by the stock's permanent id, naming the exact prediction and model version. The record carries the horizon of
    the model (5); the idea beside it still says 15 (gap h1 below).

    What this shows: the record is a real, correctly keyed record of the same model, stock, date and score. What it does NOT show:
    a stored link from the decision to the record. A BrainDecision stores no prediction or record id, so the link is stock + date
    + score. The test seeds the prediction and the decision with the same 0.84 itself, so the equal score is by construction."""
    db, inst, model, run = world["db"], world["inst"], world["model"], world["run"]
    security_id = writer.ensure_for_instrument(db, inst)
    session = run.as_of.astimezone(IST).date()
    prediction = Prediction(
        model_id=model.id, instrument_id=inst.id, ts=datetime(session.year, session.month, session.day, tzinfo=IST),
        predicted_class=1, probability=0.84, price_at_prediction=100.5, features={}, label_kind="endpoint",
    )
    db.add(prediction)
    db.flush()
    saved = horizon_nightly.record_prediction(db, prediction, model, inst, session)
    assert saved is not None and saved.created
    row = db.get(HorizonRecordRow, saved.row_id)
    idea = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())
    assert row.security_id == security_id == resolve(db, token=inst.instrument_token)
    assert (row.model_name, row.model_version, row.horizon_days) == ("swing_classifier", "v2", 5)
    assert row.run_ref == f"prediction:{prediction.id}" and row.model_id == model.id
    assert row.score == idea["confidence"] == 0.84  # equal by construction here: the test seeds both
    assert row.horizon_days != idea["horizon_days"]  # the idea's 15 is not the record's 5


# ------------------------------------------------------------------------------- missing pieces say so


def test_a_stock_the_run_did_not_look_at_says_so_instead_of_inventing_a_plan(client, world):
    other = Instrument(instrument_token=next(_token), tradingsymbol="ZZNOTSCANNED", name="Zz Not Scanned Limited", exchange="NSE", instrument_type="EQ")
    world["db"].add(other)
    world["db"].flush()
    brief = _get(client, "/beginner/stock/ZZNOTSCANNED").json()
    assert brief["q2_brain"]["available"] is False and "has not looked at this stock" in brief["q2_brain"]["answer"]
    assert brief["q3_plan"]["available"] is False and brief["q4_money"]["available"] is False


def test_a_decision_with_a_missing_level_gives_no_plan_and_no_zeros_anywhere(client, world):
    _run(world["db"], "v238-gap", plan={"entry_low": 100.0, "entry_high": 101.0, "target": None, "stop": 96.0}, symbol="ZZGAPCAP", when=datetime.now(UTC) + timedelta(minutes=1))
    world["db"].add(Instrument(instrument_token=next(_token), tradingsymbol="ZZGAPCAP", name="Zz Gap Cap Limited", exchange="NSE", instrument_type="EQ"))
    world["db"].flush()
    brief = _get(client, "/beginner/stock/ZZGAPCAP").json()
    assert brief["q3_plan"]["available"] is False and "incomplete" in brief["q3_plan"]["answer"].lower()
    latest = next(d for d in _get(client, "/brain/runs/latest?kind=nightly").json()["decisions"] if d["symbol"] == "ZZGAPCAP")
    assert latest["target"] is None  # the list says "no target", it does not show 0


def test_an_old_run_is_named_as_old_by_the_plain_answers_and_dated_by_the_run_list(client, world):
    old = datetime.now(UTC) - timedelta(days=10)
    world["db"].query(BrainRun).filter(BrainRun.id == "v238-run").update({"as_of": old, "started_at": old, "finished_at": old})
    world["db"].flush()
    brief = _get(client, f"/beginner/stock/{SYMBOL}").json()
    assert brief["q2_brain"]["available"] is False and "last run was on" in brief["q3_plan"]["why"]
    assert _get(client, "/brain/runs/latest?kind=nightly").json()["as_of"].startswith(old.date().isoformat()[:7])  # the list carries the run's own date


# ------------------------------------------------------------------------------- horizon and numbers


def test_the_decision_is_scored_by_a_five_session_model_and_the_screens_label_the_score_as_a_five_day_one(world):
    """The model really is a 5-session one (ml_models), and the stock pages call the score a '5-day model score'."""
    assert world["model"].prediction_horizon_days == 5
    text = (FRONTEND / "trademind" / "stockParts.tsx").read_text(encoding="utf-8")
    assert "5-day model score" in text


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#385): the decision step stamps policy.horizon_days (15) on every TRADE idea (m08_decide/engine.py:177) and ignores "
    "the horizon of the opinion it was built from, so an idea scored by a 5-session model leaves the engine saying 15",
)
def test_the_horizon_the_brain_stamps_on_an_idea_is_the_horizon_of_the_score_behind_it():
    """Derived from the real decision step (not from a stored row): the opinion says its score is a 5-session one."""
    from swing_trade_ml.brain import contracts as c
    from swing_trade_ml.brain.contracts import MarketMode
    from swing_trade_ml.brain.modules.m08_decide.engine import IdeaFacts, decide_idea
    from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy

    opinion = c.Opinion(
        source="model", symbol=SYMBOL, stance=0.4, confidence=0.4, probability=0.84, threshold=0.6, horizon_days=5, reasons=(MODEL_LINE,)
    )
    facts = IdeaFacts(
        symbol=SYMBOL,
        snapshot=c.Snapshot(symbol=SYMBOL, as_of="2026-11-24", close=1000.0, atr_14=20.0),
        opinion=opinion,
        verdict=c.RiskVerdict(symbol=SYMBOL, allowed=True, max_qty=25, reason="Sized by risk-per-trade"),
        quality=c.DataQuality(symbol=SYMBOL, score=1.0, fresh=True),
        stock=c.StockState(symbol=SYMBOL, trend="up", rel_strength_vs_nifty=0.03),
        situations=(),
        recall=None,
        market_mode=MarketMode.NORMAL,
    )
    decision = decide_idea(facts, DecidePolicy())
    assert decision.word.value == "TRADE" and decision.confidence == 0.84  # control: the idea really was drafted from that opinion
    assert decision.horizon_days == opinion.horizon_days


def test_the_api_passes_the_stored_horizon_through_so_the_label_comes_from_the_brain_not_the_screen(client, world):
    """Control for the gap above: the API shows what the Brain stored (15 here) and invents no other horizon."""
    assert _idea(_get(client, "/brain/runs/latest?kind=nightly").json())["horizon_days"] == 15


def test_the_percentages_on_the_plan_card_come_from_the_brain_policy_not_the_v1_settings(client, world, monkeypatch):
    """Was GAP (#416); fixed by #498 (#239 gap G10): `beginner_views.py:q3_plan` takes target %, stop % and the half-out % from the
    Brain's own `DEFAULT_POLICY`, so overriding the v1 ml_swing settings no longer moves them."""
    from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY

    monkeypatch.setattr(settings, "ML_TARGET_RETURN_PCT", 0.02)
    monkeypatch.setattr(settings, "ML_FIRST_TARGET_PCT", 0.02)
    plan = _get(client, f"/beginner/stock/{SYMBOL}").json()["q3_plan"]
    assert plan["target_pct"] == DEFAULT_POLICY.target_pct == 0.08
    assert plan["stop_pct"] == DEFAULT_POLICY.stop_pct
    assert plan["sell_half_pct"] == DEFAULT_POLICY.first_target_pct


def test_the_idea_list_and_the_plain_answers_use_the_same_run_when_a_live_book_run_is_newest(client, world):
    newer = datetime.now(UTC) + timedelta(minutes=5)
    _run(world["db"], "v238-live", book="live", confidence=0.61, when=newer)
    list_run = _idea(_get(client, "/brain/runs/latest?kind=nightly").json())["run_id"]
    brief_run = _get(client, f"/beginner/stock/{SYMBOL}").json()["q2_brain"]["decision"]["run_id"]
    assert list_run == brief_run


def test_a_member_sees_the_paper_run_too_and_never_a_live_book_run(client, world):
    """Fixed #238: the selection rule is the same for everyone, so a member's idea list never shows the live book."""
    member = _pro_member(world["db"])
    _run(world["db"], "v238-live", book="live", confidence=0.61, when=datetime.now(UTC) + timedelta(minutes=5))
    body = _get(client, "/brain/runs/latest?kind=nightly", member).json()
    assert body["book"] == "paper" and body["run_id"] != "v238-live"
