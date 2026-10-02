"""M14 portfolio brain: correlation, concentration, ordering, what-if."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, registry, request
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m14_portfolio.correlation import close_pairs, concentration, correlations
from swing_trade_ml.brain.modules.m14_portfolio.module import PortfolioBrain
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
