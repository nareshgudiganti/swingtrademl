"""Regression tests for the 2026-10-01 checkpoint code review (one per finding)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from brain_fakes import FakeReader, make_module, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.alerts import service as alerts
from swing_trade_ml.brain.module import Manifest, Step
from swing_trade_ml.brain.modules.m08_decide.engine import IdeaFacts, decide_idea
from swing_trade_ml.brain.modules.m08_decide.money import cost_pct
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun

HEADERS = {"X-API-Key": "test-api-key"}
T0 = datetime(2026, 10, 1, 10, 20, tzinfo=UTC)


# 1 · a crashed run is recorded with its real cause, also when storing fails --------


def test_a_database_error_inside_a_run_is_recorded_with_the_real_cause(db_session, monkeypatch):
    def broken(*args, **kwargs):
        db_session.execute(text("SELECT 1/0"))

    monkeypatch.setattr(service, "execute", broken)
    with pytest.raises(Exception) as caught:
        service.run_brain(db_session, kind="nightly", as_of=T0, symbols=["X"])
    assert "division by zero" in str(caught.value).lower()
    failed = db_session.query(BrainRun).filter_by(status="failed").one()
    assert "division by zero" in failed.error.lower()


def test_a_failure_while_storing_is_recorded(db_session, monkeypatch):
    def store_fails(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_store", store_fails)
    with pytest.raises(RuntimeError):
        service.run_brain(db_session, kind="nightly", as_of=T0, symbols=["X"])
    assert "disk full" in db_session.query(BrainRun).filter_by(status="failed").one().error


# 2 · manual runs never become the alert baseline; books are not mixed ------------


def _stored_run(db, run_id, when, decisions, book="paper", live=True):
    db.add(
        BrainRun(
            id=run_id,
            kind="nightly",
            as_of=when,
            book=book,
            live=live,
            started_at=when,
            status="done",
            banner_mode="DEFENSIVE",
            banner_headline="Down-trend.",
        )
    )
    db.flush()
    for symbol, word in decisions:
        db.add(BrainDecision(run_id=run_id, symbol=symbol, kind="idea", word=word, reasons=["r"]))
    db.commit()


def test_a_manual_run_does_not_swallow_the_scheduled_alert(db_session):
    _stored_run(db_session, "fx-a", T0, [("ABC", "WAIT")])
    alerts.send(db_session, "fx-a", sender=lambda t: True)  # scheduled, alerted
    _stored_run(
        db_session, "fx-manual", T0 + timedelta(hours=1), [("ABC", "TRADE")]
    )  # "Run now", never alerted
    _stored_run(db_session, "fx-b", T0 + timedelta(hours=2), [("ABC", "TRADE")])  # scheduled
    assert "trade:ABC" in {i.key for i in alerts.pending(db_session, "fx-b")}


def test_the_alert_baseline_is_the_same_book(db_session):
    _stored_run(db_session, "fx-p", T0, [("ABC", "TRADE")], book="paper")
    alerts.send(db_session, "fx-p", sender=lambda t: True)
    _stored_run(db_session, "fx-l", T0 + timedelta(hours=1), [("ABC", "WAIT")], book="live")
    alerts.send(db_session, "fx-l", sender=lambda t: True)
    _stored_run(db_session, "fx-p2", T0 + timedelta(days=1), [("ABC", "TRADE")], book="paper")
    # Compared with the paper run (TRADE), not the live one (WAIT): nothing new.
    assert "trade:ABC" not in {i.key for i in alerts.pending(db_session, "fx-p2")}


# 3 · health only trusts live nightly runs ------------------------------------------


def test_health_ignores_replays_and_one_stock_runs(db_session):
    db_session.add(
        BrainRun(
            id="fx-replay",
            kind="nightly",
            as_of=T0,
            book="paper",
            live=False,
            started_at=T0,
            status="done",
            quality={"overall": {"score": 1.0, "fresh": True, "issues": []}, "stale": []},
        )
    )
    db_session.add(
        BrainRun(
            id="fx-why",
            kind="why",
            as_of=T0,
            book="paper",
            live=True,
            started_at=T0 + timedelta(minutes=1),
            status="done",
            quality={"overall": {"score": 1.0, "fresh": True, "issues": []}, "stale": []},
        )
    )
    db_session.commit()
    h = service.health(db_session)
    assert h["last_nightly_ok"] is None
    assert h["data"]["fresh"] is None  # no live nightly yet: not checked


# 4 · the shared market cache is refreshed only when it is behind ----------------


def test_a_fresh_market_cache_is_left_alone(db_session, monkeypatch):
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.ml import market_context

    calls = []
    monkeypatch.setattr(market_context, "clear_cache", lambda: calls.append(1))
    reader = DatedReader(db_session, as_of=T0, live=True)
    monkeypatch.setattr(reader, "_cached_index_last", lambda: datetime(2026, 9, 30, tzinfo=UTC))
    monkeypatch.setattr(reader, "_db_index_last", lambda: datetime(2026, 9, 30, tzinfo=UTC))
    reader.refresh_context_if_stale()
    assert calls == []
    monkeypatch.setattr(reader, "_db_index_last", lambda: datetime(2026, 10, 1, tzinfo=UTC))
    reader._context_checked = False
    reader.refresh_context_if_stale()
    assert calls == [1]


# 5 · a time without a timezone is read as India time -----------------------------


def test_a_naive_as_of_is_read_as_india_time(client):
    r = client.post(
        "/api/v1/brain/runs",
        json={"kind": "nightly", "symbols": ["NONE"], "as_of": "2026-09-15T15:30:00"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    as_of = datetime.fromisoformat(r.json()["as_of"])
    assert as_of.utcoffset() is not None
    assert as_of.astimezone(UTC).hour == 10  # 15:30 IST = 10:00 UTC


# 6 · intraday budgets can be set per module ---------------------------------------


def test_a_module_can_set_its_own_intraday_budget():
    m = Manifest(
        id="MX", name="x", step=Step.STATE, kind="step", version="1", budget_s=20.0, intraday_budget_s=8.0
    )
    assert m.budget("intraday") == 8.0 and m.budget("nightly") == 20.0
    assert (
        Manifest(id="MY", name="y", step=Step.STATE, kind="step", version="1", budget_s=20.0).budget(
            "intraday"
        )
        == 2.0
    )


def test_state_and_market_modules_have_room_in_intraday_runs():
    from swing_trade_ml.brain.modules.m03_state.module import StateEngine
    from swing_trade_ml.brain.modules.m10_market.module import MarketBrain

    assert StateEngine.manifest.budget("intraday") >= 5
    assert MarketBrain.manifest.budget("intraday") >= 5


# 7 · expected result is priced on a real position, not one share -----------------


def test_a_refused_idea_is_not_turned_into_wait_by_one_share_costs():
    price, policy = 150.0, DecidePolicy()
    notional_qty = round(100_000 / price)
    p = (1 + 0.05 + cost_pct(price, notional_qty) / policy.stop_pct) / (policy.reward_r + 1)  # EV = +0.05 R
    facts = IdeaFacts(
        symbol="ABC",
        snapshot=c.Snapshot(symbol="ABC", as_of="d", close=price, atr_14=3.0),
        opinion=c.Opinion(
            source="model",
            symbol="ABC",
            stance=0.4,
            confidence=0.4,
            probability=0.7,
            threshold=0.6,
            reasons=("liked",),
        ),
        verdict=c.RiskVerdict(symbol="ABC", allowed=False, rule="SECTOR_CAP", reason="Sector full"),
        quality=c.DataQuality(symbol="ABC", score=1.0, fresh=True),
        stock=c.StockState(symbol="ABC", trend="up"),
        situations=(),
        recall=c.Recall(symbol="ABC", n_similar=200, hit_rate=p, p25=-0.03, p75=0.06),
        market_mode=c.MarketMode.NORMAL,
    )
    d = decide_idea(facts, policy)
    assert d.word is c.IdeaWord.WATCH
    assert "+0.05 R" in d.evidence_text


# 8 · lowering a holding keeps its share count ---------------------------------------


def test_lowering_a_holding_keeps_its_shares():
    d = c.Decision(symbol="INFY", kind="holding", word=c.HoldingWord.HOLD, reasons=("ok",), qty=40)
    assert c.downgrade(d, c.HoldingWord.REDUCE, "first target").qty == 40
    idea = c.Decision(symbol="X", kind="idea", word=c.IdeaWord.TRADE, reasons=("ok",), qty=40)
    assert c.downgrade(idea, c.IdeaWord.WATCH, "blocked").qty == 0


# 9 · fallbacks only fill gaps, they do not redo the work ----------------------------


class CountingReader(FakeReader):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.last_close_calls = 0

    def last_close(self, symbol):
        self.last_close_calls += 1
        return super().last_close(symbol)


def test_the_perceive_fallback_skips_stocks_a_module_already_priced():
    def snaps(view):
        return c.Contribution(
            snapshots=tuple(c.Snapshot(symbol=s, as_of="d", close=1.0) for s in view.request.universe)
        )

    reader = CountingReader()
    execute(
        request(), reader, registry(make_module("M02", Step.PERCEIVE, writes=("Snapshot@1",), run=snaps)), {}
    )
    assert reader.last_close_calls == 0
