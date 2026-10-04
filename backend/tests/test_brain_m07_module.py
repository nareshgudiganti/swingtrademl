"""M07 against the real database and v1's risk rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain_fakes import make_module, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Step
from swing_trade_ml.brain.modules.m07_risk.module import RiskGate
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.runner import execute
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.safety import SystemState
from swing_trade_ml.services import deployable

NOW = datetime.now(UTC)
HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture()
def liked_stock(db_session, monkeypatch):
    """One watchlisted stock at ₹1,000, entries enabled, market limit wide open."""
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="strong", fraction=1.0, context_available=True),
    )
    if db_session.get(SystemState, 1) is None:
        db_session.add(SystemState(id=1, new_entries_enabled=True, exits_enabled=True))
    inst = Instrument(
        instrument_token=993001, tradingsymbol="M07TEST", exchange="NSE", is_watchlisted=True, is_active=True
    )
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=NOW - timedelta(days=1),
            open=1000,
            high=1000,
            low=1000,
            close=1000,
            volume=1_000_000,
        )
    )
    db_session.commit()
    return inst


def _opinion_module(symbol="M07TEST", p=0.9):
    def run(view):
        return c.Contribution(
            opinions=(
                c.Opinion(
                    source="model",
                    symbol=symbol,
                    stance=2 * p - 1,
                    confidence=0.8,
                    probability=p,
                    threshold=0.6,
                    reasons=("Test model likes it",),
                ),
            )
        )

    return make_module("M90", Step.REASON, writes=("Opinion@1",), run=run, kind="plugin")


def _fresh(symbol="M07TEST", fresh=True):
    def run(view):
        return c.Contribution(
            quality=(c.DataQuality(symbol=symbol, score=1.0 if fresh else 0.2, fresh=fresh),)
        )

    return make_module("M01", Step.PERCEIVE, writes=("DataQuality@1",), run=run)


def _run(db_session, *modules, live=True, symbols=("M07TEST",)):
    req = c.RunRequest(run_id="t", kind="nightly", as_of=NOW, universe=symbols, live=live)
    return execute(req, DatedReader(db_session, as_of=NOW, live=live), registry(RiskGate, *modules), {})


def test_m07_is_registered_as_the_mandatory_risk_step():
    import swing_trade_ml.brain.modules  # noqa: F401 — registers installed modules

    cls = REGISTRY.get("M07")
    assert cls is RiskGate
    assert cls.manifest.mandatory and cls.manifest.step is Step.RISK


def test_a_liked_stock_gets_a_size_from_v1_risk_rules(db_session, liked_stock):
    ctx = _run(db_session, _opinion_module(), _fresh())
    verdict = ctx.verdicts["M07TEST"]
    assert verdict.allowed and verdict.max_qty > 0
    assert ctx.risk_gate_ran
    assert ctx.decisions["M07TEST"].word is c.IdeaWord.TRADE
    assert ctx.banner.mode is not c.MarketMode.NO_NEW_TRADES


def test_without_the_data_gateway_the_approved_stock_is_still_only_watch(db_session, liked_stock):
    ctx = _run(db_session, _opinion_module())
    assert ctx.verdicts["M07TEST"].allowed
    assert ctx.decisions["M07TEST"].word is c.IdeaWord.WATCH


def test_stale_data_is_refused(db_session, liked_stock):
    ctx = _run(db_session, _opinion_module(), _fresh(fresh=False))
    assert ctx.verdicts["M07TEST"].rule == "DATA"


def test_a_liked_stock_without_a_price_is_refused(db_session, liked_stock):
    ctx = _run(db_session, _opinion_module(symbol="NOPRICE"), symbols=("NOPRICE",))
    assert ctx.verdicts["NOPRICE"].rule == "NO_PRICE"


def test_a_stock_below_the_buy_level_is_not_a_candidate(db_session, liked_stock):
    ctx = _run(db_session, _opinion_module(p=0.4))
    assert "M07TEST" not in ctx.verdicts


def test_a_replay_never_approves(db_session, liked_stock):
    def run(view):
        return c.Contribution(
            opinions=(
                c.Opinion(
                    source="model",
                    symbol="M07TEST",
                    stance=0.8,
                    confidence=0.8,
                    probability=0.9,
                    threshold=0.6,
                    reasons=("x",),
                ),
            )
        )

    ctx = _run(
        db_session, make_module("M90", Step.REASON, writes=("Opinion@1",), run=run, kind="plugin"), live=False
    )
    assert ctx.verdicts["M07TEST"].rule == "REPLAY"


def test_owner_halt_is_refused_by_v1_rules(db_session, liked_stock):
    state = db_session.get(SystemState, 1)
    state.new_entries_enabled = False
    state.halt_reason = "holiday"
    db_session.commit()
    ctx = _run(db_session, _opinion_module(), _fresh())
    assert ctx.verdicts["M07TEST"].rule == "HALTED"
    assert ctx.banner.mode is c.MarketMode.NO_NEW_TRADES


def test_api_lists_m07_and_refuses_to_switch_it_off(client):
    body = client.get("/api/v1/brain/modules", headers=HEADERS).json()
    m07 = next(m for m in body["modules"] if m["id"] == "M07")
    assert m07["mandatory"] and m07["mode"] == "on"
    r = client.put("/api/v1/brain/modules/M07", json={"mode": "off"}, headers=HEADERS)
    assert r.status_code == 409
