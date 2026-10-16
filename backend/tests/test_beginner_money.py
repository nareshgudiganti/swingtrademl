import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.beginner_views import money_at_stake
from swing_trade_ml.services.costs import compute_charges


def test_basic_trade():
    m = money_at_stake(1000, 960, 1080, 10)
    assert m["available"] and m["why"] is None and m["invested"] == 10_000
    assert m["loss_if_stop"] == pytest.approx(400 + m["charges_round_trip"], abs=2)
    assert m["gain_if_target"] == pytest.approx(800 - m["charges_round_trip"], abs=0.5)


def test_charges_match_compute_charges():
    m = money_at_stake(1000, 960, 1080, 10)
    buy = sum(compute_charges(10_000, "BUY"))
    sell_t = sum(compute_charges(10_800, "SELL"))
    assert m["charges_round_trip"] == round(buy + sell_t, 2)
    sell_s = sum(compute_charges(9_600, "SELL"))
    assert m["loss_if_stop"] == round(400 + buy + sell_s, 2)


def test_half_out_uses_setting_and_two_sell_legs():
    m = money_at_stake(1000, 960, 1080, 10)
    lvl = 1000 * (1 + settings.ML_FIRST_TARGET_PCT)
    buy = sum(compute_charges(10_000, "BUY"))
    s1 = sum(compute_charges(5 * lvl, "SELL"))
    s2 = sum(compute_charges(5 * 1080, "SELL"))
    expected = 5 * (lvl - 1000) + 5 * 80 - buy - s1 - s2
    assert m["gain_if_half_out"] == round(expected, 2)


def test_zero_qty_not_available():
    m = money_at_stake(1000, 960, 1080, 0)
    assert m["available"] is False and m["why"] == "No shares allowed"
    assert m["loss_if_stop"] == 0.0 and m["invested"] == 0.0


def test_qty_checked_before_plan():
    assert money_at_stake(None, None, None, 0)["why"] == "No shares allowed"


def test_stop_above_entry_not_available():
    m = money_at_stake(1000, 1010, 1080, 10)
    assert m["available"] is False and m["why"] == "Plan incomplete"


def test_target_not_above_entry_not_available():
    assert money_at_stake(1000, 960, 1000, 10)["why"] == "Plan incomplete"


def test_missing_target_not_available():
    assert money_at_stake(1000, 960, None, 10)["why"] == "Plan incomplete"


def test_missing_stop_or_entry_not_available():
    assert money_at_stake(1000, None, 1080, 10)["why"] == "Plan incomplete"
    assert money_at_stake(None, 960, 1080, 10)["why"] == "Plan incomplete"


def test_single_share_half_out_sells_nothing_early():
    m = money_at_stake(1000, 960, 1080, 1)
    assert m["available"] and m["gain_if_half_out"] == m["gain_if_target"]
