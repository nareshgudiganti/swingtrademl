"""Day-by-day strength score for positions the brain owns.

A brain position only gets a number when the run's score for it is a
comparable kind (source "model" or "combined"). Anything else is a gap, a
superseded run writes nothing, and one slip message goes out per day at most.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.modules.m08_decide.engine import HoldingFacts, decide_holding
from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, PositionScore, Strategy
from swing_trade_ml.services import brain_position_score as bps
from swing_trade_ml.services import score_history

HEADERS = {"X-API-Key": "test-api-key"}
_TOKENS = iter(range(780_001, 780_999))
_RUNS = iter(range(1, 9999))
IST_TZ = ZoneInfo("Asia/Kolkata")


def _brain_position(db_session, symbol="BRAINPOS"):
    strat = Strategy(
        name=f"brain_{symbol}", strategy_type="brain", mode="paper", is_active=True,
        params={}, execution_mode="advisory",
    )
    db_session.add(strat)
    db_session.flush()
    inst = Instrument(
        instrument_token=next(_TOKENS), tradingsymbol=symbol, exchange="NSE", is_watchlisted=True
    )
    db_session.add(inst)
    db_session.flush()
    pos = Position(
        strategy_id=strat.id, instrument_id=inst.id, mode="paper", quantity=10,
        entry_price=100.0, current_price=100.0, stop_loss=96.0, entry_at=datetime.now(UTC),
        status=PositionStatus.OPEN, entry_confidence=0.9, last_confidence=0.9,
    )
    db_session.add(pos)
    db_session.commit()
    return pos


def _run(db_session, symbol, score, source="model", day=(2026, 10, 5), status="done", kind="nightly"):
    run = BrainRun(
        id=f"nightly-test-{next(_RUNS)}", kind=kind, book="paper", live=True, status=status,
        as_of=datetime(*day, 21, 0, tzinfo=IST_TZ),
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        BrainDecision(
            run_id=run.id, symbol=symbol, kind="holding", word="HOLD", confidence=score,
            score_source=source, reasons=[],
        )
    )
    db_session.commit()
    return run


def _record(db_session, symbol, score, sent, **kw):
    run = _run(db_session, symbol, score, **kw)
    return bps.record_run_scores(db_session, run.id, send=sent.append)


def _rows(db_session, pos):
    return list(
        db_session.query(PositionScore).filter_by(position_id=pos.id).order_by(PositionScore.as_of)
    )


def test_a_comparable_score_is_recorded_with_its_source(db_session):
    pos = _brain_position(db_session)
    run = _run(db_session, "BRAINPOS", 0.72)
    assert bps.record_run_scores(db_session, run.id, send=lambda _t: None) == 1
    (row,) = _rows(db_session, pos)
    assert row.score == 0.72
    assert row.model_version == "brain:model"
    assert row.as_of.isoformat() == "2026-10-05"


def test_a_score_that_is_not_comparable_leaves_a_gap(db_session):
    pos = _brain_position(db_session)
    for source in (None, "opinion"):
        run = _run(db_session, "BRAINPOS", 0.72, source=source)
        assert bps.record_run_scores(db_session, run.id, send=lambda _t: None) == 0
    run = _run(db_session, "BRAINPOS", None, source="model")
    assert bps.record_run_scores(db_session, run.id, send=lambda _t: None) == 0
    assert _rows(db_session, pos) == []


def test_superseded_failed_and_replay_runs_write_nothing(db_session):
    pos = _brain_position(db_session)
    for status in ("superseded", "failed"):
        run = _run(db_session, "BRAINPOS", 0.72, status=status)
        assert bps.record_run_scores(db_session, run.id, send=lambda _t: None) == 0
    replay = _run(db_session, "BRAINPOS", 0.72)
    replay.live = False
    db_session.commit()
    assert bps.record_run_scores(db_session, replay.id, send=lambda _t: None) == 0
    assert _rows(db_session, pos) == []


def test_a_second_run_the_same_day_replaces_the_score(db_session):
    pos = _brain_position(db_session)
    bps.record_run_scores(db_session, _run(db_session, "BRAINPOS", 0.72).id, send=lambda _t: None)
    bps.record_run_scores(db_session, _run(db_session, "BRAINPOS", 0.66).id, send=lambda _t: None)
    (row,) = _rows(db_session, pos)
    assert row.score == 0.66


def test_a_slide_into_a_worse_band_sends_one_message_a_day(db_session):
    pos = _brain_position(db_session)
    sent: list[str] = []
    _record(db_session, "BRAINPOS", 0.80, sent, day=(2026, 10, 5))
    assert sent == []  # first day: nothing to compare with
    slid = _run(db_session, "BRAINPOS", 0.50, day=(2026, 10, 6))
    bps.record_run_scores(db_session, slid.id, send=sent.append)
    assert len(sent) == 1
    assert "SCORE SLIPPING" in sent[0] and "BRAINPOS" in sent[0] and "first tracked" in sent[0]
    # Another run the same day (even lower) must not message again.
    _record(db_session, "BRAINPOS", 0.40, sent, day=(2026, 10, 6))
    assert len(sent) == 1
    assert [r.band for r in _rows(db_session, pos)] == ["strong", "weak"]


def test_a_change_of_score_source_is_a_break_not_an_alert(db_session):
    pos = _brain_position(db_session)
    sent: list[str] = []
    _record(db_session, "BRAINPOS", 0.80, sent, source="combined", day=(2026, 10, 5))
    _record(db_session, "BRAINPOS", 0.40, sent, source="model", day=(2026, 10, 6))
    assert sent == []
    assert [r.model_version for r in _rows(db_session, pos)] == ["brain:combined", "brain:model"]


def test_only_open_brain_owned_positions_get_a_trail(db_session):
    mine = _brain_position(db_session, "ONLYMINE")
    v1 = _brain_position(db_session, "V1OWNED")
    db_session.get(Strategy, v1.strategy_id).strategy_type = "ml_swing"
    db_session.commit()
    run = _run(db_session, "ONLYMINE", 0.7)
    db_session.add(BrainDecision(run_id=run.id, symbol="V1OWNED", kind="holding", word="HOLD",
                                 confidence=0.7, score_source="model", reasons=[]))
    db_session.commit()
    assert bps.record_run_scores(db_session, run.id, send=lambda _t: None) == 1
    assert len(_rows(db_session, mine)) == 1
    assert _rows(db_session, v1) == []


def test_the_positions_api_gives_a_brain_position_its_trail_and_band(client, db_session):
    pos = _brain_position(db_session, "APIBRAIN")
    bps.record_run_scores(db_session, _run(db_session, "APIBRAIN", 0.52).id, send=lambda _t: None)
    resp = client.get("/api/v1/portfolio/positions/detailed", headers=HEADERS)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == pos.id)
    assert row["score_from_trail"] is True
    assert [t["score"] for t in row["score_trail"]] == [0.52]
    assert row["score_band"] == score_history.score_band(0.52, 0.35)


def test_a_brain_position_with_no_trail_shows_no_band(client, db_session):
    pos = _brain_position(db_session, "NOTRAIL")
    resp = client.get("/api/v1/portfolio/positions/detailed", headers=HEADERS)
    row = next(r for r in resp.json() if r["id"] == pos.id)
    assert row["score_trail"] == [] and row["score_band"] is None


def test_a_holding_decision_carries_the_model_score_but_keeps_its_word():
    holding = c.Holding(symbol="X", qty=5, avg_price=100.0, stop=96.0, target=108.0)
    base = {"holding": holding, "snapshot": None, "stock": None, "market_mode": c.MarketMode.NORMAL}
    d = decide_holding(HoldingFacts(**base, score=(0.64, "model")), DEFAULT_POLICY)
    assert (d.confidence, d.confidence_source) == (0.64, "model")
    assert d.word is c.HoldingWord.MONITOR  # no price today: unchanged caution
    bare = decide_holding(HoldingFacts(**base), DEFAULT_POLICY)
    assert bare.confidence is None and bare.confidence_source is None
