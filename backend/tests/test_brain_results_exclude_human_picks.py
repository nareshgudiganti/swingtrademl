"""Human-selected ideas never count as the brain's (evidence plan amendment 1, A3).

Stocks a person chose live in three places:

1. the owner's horizon-experiment picks (`experiment_*` tables, services/experiments),
2. My Holdings / Real Trading: the `real_trading` strategy (book "real", stored as mode "live"), including the
   BUY signals the daily scan records for it, and the brain's own run on the live book that holds them,
3. the manual paper-testing book (`tester_paper` strategy), whose positions the paper brain run holds.

On a day BEFORE the blind trial (so results are visible, services/trial_seal.py) each source gets a stock
with a distinctive name (HUMANPICK...) and a distinctive result (+6.17%), next to one normal brain idea and
one normal version 1 idea. Every brain result route and report is then read as the owner: the human
marker must never appear, while the brain idea (and version 1's own idea, as the baseline) still does.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from brain_m18_fixtures import brain_strategy
from swing_trade_ml.core.enums import PositionStatus, SignalType
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.experiments import (
    ExperimentCohort,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentSelection,
)
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.services import brain_daily_check as daily
from swing_trade_ml.services import tester_paper
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

API_KEY = {"X-API-Key": "test-api-key"}
IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 10, 9)  # a Friday before the trial (TRIAL_START 2026-10-14): results are visible
NOW = datetime(2026, 10, 13, 18, 0, tzinfo=IST)
BRAIN, V1 = "BRAINOK", "VONEOK"
HUMAN_EXPERIMENT, HUMAN_REAL, HUMAN_TESTER = "HUMANPICKX", "HUMANPICKR", "HUMANPICKT"
HUMAN_RETURN = 0.0617  # appears nowhere else
BRAIN_RETURN = 0.08
MARKERS = ("HUMANPICK", "0.0617", "6.17", "real_trading", "tester_paper")
CLOCK = re.compile(r"\d{2}:\d{2}:\d{2}(\.\d+)?")


@pytest.fixture(autouse=True)
def _brain_on(monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)


@pytest.fixture()
def obs_client(client, db_session):
    """The Observatory reads through its own read-only session: point it at the test transaction."""
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


def _ist(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST).astimezone(UTC)


def _instrument(db, symbol: str, token: int, *, candles: bool) -> Instrument:
    """Human picks get no candles and are not watch-listed, so they cannot reach the brain's universe (the
    every-stock baseline) by being part of the market: only a leak of the human rows could show them."""
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, name=symbol, exchange="NSE", is_watchlisted=candles
    )
    db.add(inst)
    db.flush()
    if candles:
        price, d = 100.0, DAY - timedelta(days=45)
        while d <= DAY + timedelta(days=45):
            if d.weekday() < 5:
                db.add(
                    Candle(
                        instrument_id=inst.id,
                        interval="day",
                        ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                        open=price,
                        high=price + 3,
                        low=price - 1,
                        close=price + 2,
                        volume=100_000,
                    )
                )
                price += 2
            d += timedelta(days=1)
    return inst


def _run(db, run_id: str, book: str) -> None:
    db.add(
        BrainRun(
            id=run_id,
            kind="nightly",
            live=True,
            status="done",
            book=book,
            as_of=_ist(DAY, 16, 30),
            started_at=_ist(DAY, 16, 30),
            banner_mode="NORMAL",
        )
    )
    db.flush()


def _holding(db, run_id: str, symbol: str) -> None:
    """The brain looks after every open position of a book, so a person's stock is a `holding` decision."""
    db.add(
        BrainDecision(
            run_id=run_id,
            symbol=symbol,
            kind="holding",
            word="HOLD",
            reasons=["Held by a person; the brain only watches it."],
        )
    )


def _buy(db, strategy: Strategy, inst: Instrument, mode: str, pct: float, features: dict | None = None):
    db.add(
        Signal(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            signal_type=SignalType.BUY,
            mode=mode,
            price=100.0,
            confidence=0.6,
            suggested_quantity=10,
            stop_loss=96.0,
            take_profit=108.0,
            horizon_days=15,
            reason="r",
            features=features or {},
            advisory_only=True,
            outcome="TARGET_HIT",
            outcome_pct=pct,
            outcome_at=_ist(DAY + timedelta(days=2), 15, 30),
            generated_at=_ist(DAY, 16, 35),
        )
    )


def _position(db, strategy: Strategy, inst: Instrument, mode: str) -> None:
    db.add(
        Position(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            mode=mode,
            status=PositionStatus.OPEN,
            quantity=10,
            entry_price=100.0,
            entry_at=_ist(DAY, 10, 0),
        )
    )


def _seed(db) -> dict:
    # The brain: one live nightly paper run with a finished TRADE idea, and its practice Signal.
    brain_inst = _instrument(db, BRAIN, 881_001, candles=True)
    _run(db, "human-guard-paper", "paper")
    idea = BrainDecision(
        run_id="human-guard-paper",
        symbol=BRAIN,
        kind="idea",
        word="TRADE",
        confidence=0.85,
        score_source="model",
        stop=96.0,
        target=108.0,
        horizon_days=15,
        reasons=["Strong trend with room to the target."],
        outcome="target",
        outcome_return=BRAIN_RETURN,
        outcome_days=3,
        max_up=0.09,
        max_down=-0.01,
        resolved_on=DAY + timedelta(days=3),
    )
    db.add(idea)
    brain = brain_strategy(db, name="guard-brain", symbols=[BRAIN])
    _buy(db, brain, brain_inst, "paper", BRAIN_RETURN)

    # Version 1's own scan (the baseline the brain is compared with).
    v1_inst = _instrument(db, V1, 881_002, candles=True)
    v1 = Strategy(name="guard-v1", strategy_type="ml_swing", mode="paper", is_active=True, params={})
    db.add(v1)
    db.flush()
    _buy(db, v1, v1_inst, "paper", BRAIN_RETURN)

    # 1. The owner's horizon-experiment pick, scored +6.17%.
    x_inst = _instrument(db, HUMAN_EXPERIMENT, 881_003, candles=False)
    protocol = ExperimentProtocol(code="guard-v1", params={"horizons": [5, 30]})
    db.add(protocol)
    db.flush()
    cohort = ExperimentCohort(protocol_id=protocol.id, source="owner", name="owner")
    db.add(cohort)
    db.flush()
    pick = ExperimentSelection(
        cohort_id=cohort.id,
        instrument_id=x_inst.id,
        symbol_at_entry=HUMAN_EXPERIMENT,
        intended_horizon=5,
        submitted_at=_ist(DAY, 9, 0),
        submitted_by="owner",
        entry_session=DAY,
        status="accepted",
    )
    db.add(pick)
    db.flush()
    db.add(
        ExperimentOutcome(
            selection_id=pick.id,
            horizon=5,
            protocol_id=protocol.id,
            state="closed",
            entry_price=100.0,
            exit_session=DAY + timedelta(days=7),
            exit_price=106.17,
            gross_return=HUMAN_RETURN,
            net_return=HUMAN_RETURN,
            scorer_version="guard",
        )
    )

    # 2. My Holdings / Real Trading: the advisory `real_trading` strategy exactly as the app creates it
    # (strategy type ml_swing, mode live), a stock held there, the scan's BUY signal for it, and the brain's
    # own nightly run on the live book, which holds that stock.
    r_inst = _instrument(db, HUMAN_REAL, 881_004, candles=False)
    real = Strategy(
        name=REAL_TRADING_STRATEGY_NAME,
        strategy_type="ml_swing",
        mode="live",
        execution_mode="advisory",
        is_active=True,
        params={},
    )
    db.add(real)
    db.flush()
    _position(db, real, r_inst, "live")
    _buy(db, real, r_inst, "live", HUMAN_RETURN)
    _run(db, "human-guard-live", "live")
    _holding(db, "human-guard-live", HUMAN_REAL)

    # 3. The manual paper-testing book: a tester's buy (Signal + Position, as services/tester_paper records
    # it). The paper brain run holds it, because it reads every open paper position.
    t_inst = _instrument(db, HUMAN_TESTER, 881_005, candles=False)
    tester = tester_paper.get_or_create_strategy(db)
    _position(db, tester, t_inst, "paper")
    _buy(db, tester, t_inst, "paper", HUMAN_RETURN, {"source": "paper_tester"})
    _holding(db, "human-guard-paper", HUMAN_TESTER)
    db.flush()
    return {"brain_strategy": brain.name, "v1_strategy": v1.name}


def _markers(text: str) -> list[str]:
    text = CLOCK.sub("", text)
    return [m for m in MARKERS if m in text]


ROUTES = (
    "/api/v1/brain/compare",
    "/api/v1/brain/compare?since=2026-10-01",
    "/api/v1/brain/stage",
    "/api/v1/brain/trial-journal?from=2026-10-01&to=2026-10-13",
    "/api/v1/brain/learning",
    "/api/v1/brain/learning?since=2026-10-01",
    "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-13&category=practice",
    "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-13&category=paper",
    "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-13&category=backtest",
    "/api/v1/brain/observatory/score-bands?from=2026-10-01&to=2026-10-13",
    "/api/v1/brain/observatory/learning?from=2026-10-01&to=2026-10-13",
    "/api/v1/brain/observatory/forward-gate",
    "/api/v1/brain/observatory/evidence-pack?month=2026-10",
    "/api/v1/brain/daily-checks?days=30",
    "/api/v1/brain/daily-checks/latest",
)


def test_no_brain_result_route_includes_a_human_pick(obs_client, db_session, tmp_path):
    ids = _seed(db_session)
    daily.store(db_session, daily.compute(db_session, NOW, backup_dir=str(tmp_path)))
    bodies = {}
    for url in ROUTES:
        r = obs_client.get(url, headers=API_KEY)
        assert r.status_code == 200, (url, r.status_code, r.text[:300])
        bodies[url] = r.text
    found = {url: _markers(t) for url, t in bodies.items() if _markers(t)}
    assert found == {}, f"human picks in a brain result: {found}"

    # ... while the brain's idea is there, and version 1's own idea is the only baseline.
    compare = json.loads(bodies["/api/v1/brain/compare"])
    assert compare["brain"]["finished"] == 1
    assert compare["brain"]["avg_outcome_pct"] == pytest.approx(BRAIN_RETURN)
    assert compare["version1"]["ideas"] == 1
    assert compare["version1"]["avg_outcome_pct"] == pytest.approx(BRAIN_RETURN)
    assert {s["name"] for s in compare["strategies"]} == {ids["brain_strategy"], ids["v1_strategy"]}
    journal = json.loads(bodies["/api/v1/brain/trial-journal?from=2026-10-01&to=2026-10-13"])["journal"]
    assert journal["sessions"] == 1
    day = journal["days"][0]["picks"]
    assert [p["symbol"] for p in day["brain_trade"]] == [BRAIN]
    assert [p["symbol"] for p in day["v1_buys"]] == [V1]
    learning = json.loads(bodies["/api/v1/brain/learning"])
    assert learning["n_scored"] == 1
    practice = json.loads(
        bodies["/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-13&category=practice"]
    )
    assert practice["stored_grades"]["count"] == 1
    assert practice["stored_grades"]["avg_gross_return"] == pytest.approx(BRAIN_RETURN)
    assert (
        json.loads(bodies["/api/v1/brain/observatory/learning?from=2026-10-01&to=2026-10-13"])[
            "results_collected"
        ]
        == 1
    )
    assert BRAIN in bodies["/api/v1/brain/trial-journal?from=2026-10-01&to=2026-10-13"]


def test_no_brain_report_or_command_line_text_includes_a_human_pick(db_session, tmp_path):
    from swing_trade_ml.brain.replay_score import v1_buys
    from swing_trade_ml.brain.trial_journal import journal_for, plain_report
    from swing_trade_ml.services import trial_seal
    from swing_trade_ml.services.brain_golive import compare
    from swing_trade_ml.services.brain_observatory import outcomes, pack, score_bands

    _seed(db_session)
    journal = journal_for(db_session, date(2026, 10, 1), date(2026, 10, 13))
    texts = {
        "trial journal": plain_report(journal) + json.dumps(journal, default=str),
        "compare.report": json.dumps(compare.report(db_session), default=str),
        "learning report": json.dumps(trial_seal.learning_report(db_session), default=str),
        "outcomes.build": json.dumps(
            outcomes.build(db_session, date(2026, 10, 1), date(2026, 10, 13), "practice"), default=str
        ),
        "score bands": json.dumps(
            score_bands.build(db_session, date(2026, 10, 1), date(2026, 10, 13), "paper"), default=str
        ),
        "v1 buys": str(v1_buys(db_session, date(2026, 10, 1), date(2026, 10, 13))),
        "daily check": json.dumps(daily.compute(db_session, NOW, backup_dir=str(tmp_path)), default=str),
    }
    built = pack.build_pack(db_session, "2026-10", NOW.date())
    texts["evidence pack"] = pack.plain_report(built) + json.dumps(built, default=str)
    found = {name: _markers(t) for name, t in texts.items() if _markers(t)}
    assert found == {}, f"human picks in a brain report: {found}"
    assert BRAIN in texts["trial journal"] and V1 in texts["v1 buys"]

    # The go-live counter (and everything else reading compare.load) sees the brain's idea only.
    assert compare.finished_brain_ideas(db_session) == 1
    rows, _ = compare.load(db_session)
    assert {r.symbol for r in rows} == {BRAIN, V1}
    assert all(r.symbol == BRAIN for r in rows if r.is_brain)


def test_the_human_rows_really_exist(db_session):
    """Guard against a vacuous pass: the human rows are stored and found by their own books."""
    from sqlalchemy import func, select

    _seed(db_session)
    assert db_session.scalar(select(func.count()).select_from(ExperimentOutcome)) >= 1
    names = {
        s.name: s
        for s in db_session.scalars(
            select(Strategy).where(Strategy.name.in_([REAL_TRADING_STRATEGY_NAME, "tester_paper"]))
        )
    }
    assert set(names) == {REAL_TRADING_STRATEGY_NAME, "tester_paper"}
    for s in names.values():
        n = db_session.scalar(select(func.count()).select_from(Signal).where(Signal.strategy_id == s.id))
        assert n == 1
    holdings = db_session.scalars(select(BrainDecision.symbol).where(BrainDecision.kind == "holding")).all()
    assert set(holdings) == {HUMAN_REAL, HUMAN_TESTER}
