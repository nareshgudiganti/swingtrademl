"""M14 portfolio brain: correlation, concentration, ordering, what-if."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m07_risk.allocator import Account, Candidate, CheckResult, Policy, allocate
from swing_trade_ml.brain.modules.m14_portfolio.correlation import close_pairs, concentration, correlations
from swing_trade_ml.brain.modules.m14_portfolio.module import PortfolioBrain
from swing_trade_ml.brain.modules.m14_portfolio.whatif import what_if
from swing_trade_ml.brain.runner import execute


def _dated(values, start="2026-01-01") -> pd.Series:
    return pd.Series(np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)).date)


def _walk(seed, n=120):
    rng = np.random.default_rng(seed)
    return 100 * np.cumprod(1 + rng.normal(0, 0.01, n))


def test_twins_correlate_and_strangers_do_not():
    a = _walk(1)
    closes = {"A": _dated(a), "TWIN": _dated(a * 1.5), "OTHER": _dated(_walk(2))}
    corr = correlations(closes)
    assert corr.loc["A", "TWIN"] == pytest.approx(1.0)
    assert abs(corr.loc["A", "OTHER"]) < 0.3
    assert close_pairs(corr) == [("A", "TWIN", pytest.approx(1.0))]


def test_only_the_last_60_days_count():
    a, b = _walk(3, 200), _walk(4, 200)
    b[-61:] = a[-61:] * (b[-62] / a[-62])  # identical moves for the last 60 days only
    corr = correlations({"A": _dated(a), "B": _dated(b)})
    assert corr.loc["A", "B"] == pytest.approx(1.0)


def test_too_little_overlap_claims_nothing():
    corr = correlations({"A": _dated(_walk(5)), "NEW": _dated(_walk(5)[:30], start="2026-05-01")})
    assert np.isnan(corr.loc["A", "NEW"])
    assert close_pairs(corr) == []


def test_concentration_names_the_largest_position_and_sector():
    values = {"HDFCBANK": 40_000.0, "ICICIBANK": 30_000.0, "TCS": 10_000.0}
    c = concentration(values, portfolio_value=200_000.0)
    assert c["largest_position"] == ("HDFCBANK", pytest.approx(0.20))
    assert c["top_sector"] == ("BANK", pytest.approx(0.35))


# --- the module ------------------------------------------------------------------------------

BANK = _walk(10)


class BookReader(FakeReader):
    def __init__(self, closes, value=200_000.0, **kw):
        super().__init__(**kw)
        self._dated = closes
        self._value = value

    def dated_closes(self, symbol):
        return self._dated.get(symbol, pd.Series(dtype=float))

    def portfolio_numbers(self, book):
        return {"value": self._value, "cash": 50_000.0}


def _run(reader, universe=("ICICIBANK", "TCS")):
    return execute(request(universe=universe), reader, registry(PortfolioBrain), {"M14": Mode.ON})


HELD = (c.Holding(symbol="HDFCBANK", qty=100, avg_price=100.0),)
CLOSES = {"HDFCBANK": _dated(BANK), "ICICIBANK": _dated(BANK * 2), "TCS": _dated(_walk(11))}


def test_m14_is_a_state_plugin_that_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M14") is PortfolioBrain
    m = PortfolioBrain.manifest
    assert m.step is Step.STATE and m.kind == "plugin" and m.default_mode is Mode.ON


def test_an_idea_moving_with_a_holding_is_nudged_down_and_says_why():
    ctx = _run(BookReader(CLOSES, holdings=HELD))
    notes = {o.symbol: o for o in ctx.opinions if o.source == "portfolio"}
    assert notes["ICICIBANK"].stance == -0.1
    assert notes["ICICIBANK"].reasons[0].startswith("Moves closely with HDFCBANK, which you already hold")
    assert notes["TCS"].stance == 0.05 and notes["TCS"].reasons[0].startswith("Adds variety")


def test_the_portfolio_state_holds_pairs_and_concentration():
    ctx = _run(BookReader(CLOSES, holdings=HELD))
    p = ctx.portfolio
    assert ("HDFCBANK", "ICICIBANK") in {(a, b) for a, b, _ in p.correlated}
    symbol, share = p.largest_position
    assert symbol == "HDFCBANK" and share == pytest.approx(100 * BANK[-1] / 200_000.0)
    assert p.top_sector[0] == "BANK"


def test_without_holdings_there_is_nothing_to_compare():
    ctx = _run(BookReader(CLOSES))
    assert not [o for o in ctx.opinions if o.source == "portfolio"]


def test_portfolio_opinions_are_modifiers():
    from swing_trade_ml.brain.opinions import MODIFIER_SOURCES

    assert "portfolio" in MODIFIER_SOURCES


# --- ordering in the risk gate ---------------------------------------------------------------


def _account(slots=2):
    return Account(
        portfolio_value=1e6,
        cash=1e6,
        free_slots=slots,
        min_position_inr=1e4,
        sector_rule="pct_cap",
        sector_cap_pct=None,
        deploy_room=1e6,
    )


def _allocate(cands, pairs, slots=2):
    seen = []

    def check(cand, cash):
        seen.append(cand.symbol)
        return CheckResult(allowed=True, qty=100)

    policy = Policy(mode=MarketMode.NORMAL, pairs=frozenset(frozenset(p) for p in pairs))
    verdicts = {v.symbol: v for v in allocate(cands, _account(slots), check, policy, lambda p, q: p * q)}
    return verdicts, seen


def test_a_candidate_moving_with_a_stronger_one_is_judged_last():
    cands = [
        Candidate("HDFCBANK", 100, 0.9, None),
        Candidate("ICICIBANK", 100, 0.8, None),
        Candidate("TCS", 100, 0.7, None),
    ]
    verdicts, seen = _allocate(cands, [("HDFCBANK", "ICICIBANK")])
    assert seen == ["HDFCBANK", "TCS"]  # two slots: the twin waited and lost out
    assert not verdicts["ICICIBANK"].allowed
    assert "moved closely with HDFCBANK" in verdicts["ICICIBANK"].note


def test_a_twin_that_still_fits_is_approved_with_its_note():
    cands = [Candidate("HDFCBANK", 100, 0.9, None), Candidate("ICICIBANK", 100, 0.8, None)]
    verdicts, _ = _allocate(cands, [("HDFCBANK", "ICICIBANK")], slots=5)
    assert verdicts["ICICIBANK"].allowed and verdicts["ICICIBANK"].note.startswith("Judged after HDFCBANK")
    assert verdicts["HDFCBANK"].note == ""


def test_m08_shows_the_note_on_a_trade_card():
    from swing_trade_ml.brain.modules.m08_decide.engine import IdeaFacts, decide_idea
    from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy

    note = "Judged after HDFCBANK, which it has moved closely with over 60 days."
    facts = IdeaFacts(
        symbol="ICICIBANK",
        snapshot=c.Snapshot(symbol="ICICIBANK", as_of="d", close=1000.0, atr_14=20.0),
        opinion=c.Opinion(
            source="model",
            symbol="ICICIBANK",
            stance=0.4,
            confidence=0.4,
            probability=0.7,
            threshold=0.6,
            reasons=("Model 70%.",),
        ),
        verdict=c.RiskVerdict(symbol="ICICIBANK", allowed=True, max_qty=5, note=note),
        quality=c.DataQuality(symbol="ICICIBANK", score=1.0, fresh=True),
        stock=None,
        situations=(),
        recall=None,
        market_mode=MarketMode.NORMAL,
    )
    d = decide_idea(facts, DecidePolicy())
    assert d.word.value == "TRADE" and note in d.reasons


# --- what-if -------------------------------------------------------------------------------------


def test_whatif_shows_shares_before_and_after_with_plain_warnings():
    out = what_if(
        "ICICIBANK",
        qty=100,
        price=1_000.0,
        portfolio_value=500_000.0,
        cash=200_000.0,
        holdings={"HDFCBANK": 100_000.0},
        max_position_pct=0.15,
        sector_cap_pct=0.25,
    )
    assert out["value"] == 100_000.0 and out["cash_after"] == 100_000.0
    assert out["stock_share_after"] == pytest.approx(0.20)
    assert out["sector"] == "BANK" and out["sector_share_before"] == pytest.approx(0.20)
    assert out["sector_share_after"] == pytest.approx(0.40)
    assert "20% of the portfolio in ICICIBANK, above the 15% limit" in out["warnings"][0]
    assert any("Banks would be 40%" in w or "BANK would be 40%" in w for w in out["warnings"])


def test_whatif_adds_to_an_existing_holding():
    out = what_if(
        "HDFCBANK",
        qty=10,
        price=1_000.0,
        portfolio_value=500_000.0,
        cash=200_000.0,
        holdings={"HDFCBANK": 40_000.0},
        max_position_pct=0.15,
        sector_cap_pct=0.25,
    )
    assert out["stock_share_before"] == pytest.approx(0.08) and out["stock_share_after"] == pytest.approx(
        0.10
    )
    assert out["warnings"] == []


def test_whatif_warns_when_cash_runs_short():
    out = what_if(
        "TCS",
        qty=100,
        price=4_000.0,
        portfolio_value=500_000.0,
        cash=100_000.0,
        holdings={},
        max_position_pct=1.0,
        sector_cap_pct=None,
    )
    assert any("more than the" in w and "cash" in w for w in out["warnings"])


def test_the_whatif_endpoint_answers(client):
    r = client.post(
        "/api/v1/brain/whatif",
        json={"symbol": "tcs", "qty": 1, "price": 1000.0},
        headers={"X-API-Key": "test-api-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "TCS" and body["value"] == 1000.0 and "warnings" in body


def test_the_run_keeps_the_portfolio_view_for_the_console():
    from swing_trade_ml.brain.service import _portfolio_summary

    ctx = _run(BookReader(CLOSES, holdings=(*HELD, c.Holding(symbol="ICICIBANK", qty=10, avg_price=1.0))))
    summary = _portfolio_summary(ctx)
    assert summary["largest_position"][0] == "HDFCBANK"
    assert summary["holdings_moving_together"] == [["HDFCBANK", "ICICIBANK", 1.0]]
