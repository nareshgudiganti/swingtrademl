"""Costs audit (bx5): pin today's paper charges so any later change is visible.

These tests document current behaviour; they change nothing.
"""

from types import SimpleNamespace

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services import real_report
from swing_trade_ml.services.costs import compute_charges, flat_charge


def test_buy_100k_costs():
    # 11.9 bps, no DP fee, zero brokerage
    assert compute_charges(100_000, "BUY") == pytest.approx((0.0, 119.0))


def test_sell_100k_costs():
    # 10.4 bps + 15.93 flat DP fee
    assert compute_charges(100_000, "SELL") == pytest.approx((0.0, 104.0 + 15.93))


def test_flat_charge_only_on_sells():
    assert flat_charge("BUY") == 0.0
    assert flat_charge("SELL") == pytest.approx(15.93)


def test_component_sum_is_not_below_config():
    # Config may round up, never down (the cautious direction).
    exchange, sebi = 0.307, 0.01  # bps, NSE equity rate in force today
    gst = 0.18 * (exchange + sebi)  # 18% GST on exchange + SEBI fees (brokerage is 0)
    assert 10 + exchange + sebi + 1.5 + gst <= settings.PAPER_TAX_BPS_BUY
    assert 10 + exchange + sebi + gst <= settings.PAPER_TAX_BPS_SELL


def test_real_report_uses_same_cost_model(monkeypatch):
    calls = []

    def fake(turnover, side):
        calls.append((turnover, side))
        return (1.0, 2.0)

    monkeypatch.setattr(real_report, "compute_charges", fake)
    fill = SimpleNamespace(quantity=10, price=100.0, side="BUY")
    assert real_report._charge(fill) == pytest.approx(3.0)
    assert calls == [(1000.0, "BUY")]
