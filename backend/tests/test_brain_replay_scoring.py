# backend/tests/test_brain_replay_scoring.py
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.replay_scoring import after_day, locked_score, strict_for, strict_score

START = date(2026, 9, 28)


def bars(rows):
    return pd.DataFrame(
        [
            {"day": START + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


FLAT = (100.0, 100.5, 99.5, 100.0)


def test_empty_bars_are_open():
    assert strict_score(bars([])).status == "open"


def test_fewer_than_fifteen_quiet_bars_are_open_not_scored():
    out = strict_score(bars([FLAT] * 5))
    assert out.status == "open" and out.net_return is None


def test_fifteen_quiet_bars_time_out_slightly_negative_after_costs():
    out = strict_score(bars([FLAT] * 15))
    assert out.status == "timeout" and out.days == 15
    assert -0.02 < out.net_return < 0.0  # flat price minus costs and slippage


def test_target_after_half_out_is_between_five_and_eight_percent():
    out = strict_score(bars([(100, 101, 99, 100)] * 2 + [(100, 109, 100, 108)]))
    assert out.status == "target" and out.half_out and not out.gap
    assert 0.05 < out.net_return < 0.08


def test_stop_is_about_minus_four_percent_after_costs():
    out = strict_score(bars([(100, 101, 99, 100), (100, 100, 95, 96)]))
    assert out.status == "stop" and not out.gap
    assert -0.05 < out.net_return < -0.04


def test_gap_through_the_stop_fills_at_the_open_and_loses_more():
    out = strict_score(bars([(100, 101, 99, 100), (90, 91, 89, 90)]))
    assert out.status == "stop" and out.gap
    assert out.net_return < -0.09


def test_a_bar_touching_both_target_and_stop_is_the_stop():
    out = strict_score(bars([(100, 109, 95, 100)]))
    assert out.status == "stop"


def test_half_sold_then_stopped_is_about_break_even():
    out = strict_score(bars([(100, 101, 99, 100), (100, 106, 99, 105), (105, 105, 90, 92)]))
    assert out.status == "stop" and out.half_out
    assert -0.01 < out.net_return < 0.01


def test_gap_up_through_the_target_fills_at_the_open_and_gains_more():
    out = strict_score(bars([(100, 101, 99, 100), (110, 112, 109, 111)]))
    assert out.status == "target" and out.gap
    assert out.net_return > 0.08


def test_after_day_keeps_only_later_bars():
    df = bars([FLAT] * 5)
    later = after_day(df, START + timedelta(days=1))
    assert list(later["day"]) == [START + timedelta(days=i) for i in (2, 3, 4)]


def test_locked_score_enters_at_the_decision_days_close():
    # decision day = START (close 100); the next bar's high is 108.5 -> +8% target
    rows = [(100, 100, 100, 100), (100, 108.5, 99.5, 108)]
    out = locked_score(bars(rows), START)
    assert out is not None and out.outcome == "target" and out.ret == 0.08


def test_locked_score_is_none_without_a_bar_on_or_before_the_decision_day():
    assert locked_score(bars([FLAT] * 3), START - timedelta(days=5)) is None


def test_strict_for_uses_the_bar_after_the_decision_day_as_entry():
    df = bars([FLAT] * 17)
    assert strict_for(df, START).status == "timeout"


# --- the same rule at other targets, stops and horizons (horizon grid) ---


def test_default_rule_is_unchanged_by_the_new_options():
    rows = [(100, 101, 99, 100)] * 2 + [(100, 109, 100, 108)]
    same = strict_score(bars(rows), horizon=15, target=0.08, stop=0.04, half_out=0.05)
    assert strict_score(bars(rows)) == same


def test_a_smaller_target_is_reached_where_the_big_one_is_not():
    rows = [(100, 103, 99.5, 102)] * 3 + [FLAT] * 12
    assert strict_score(bars(rows)).status == "timeout"
    out = strict_score(bars(rows), target=0.02, half_out=None)
    assert out.status == "target" and out.days == 1 and out.net_return > 0


def test_a_shorter_horizon_times_out_sooner():
    out = strict_score(bars([FLAT] * 7), horizon=5, half_out=None)
    assert out.status == "timeout" and out.days == 5
    assert strict_score(bars([FLAT] * 4), horizon=5, half_out=None).status == "open"


def test_a_tighter_stop_is_hit_by_a_small_drop():
    rows = [(100, 100.5, 97.5, 98)] + [FLAT] * 14
    assert strict_score(bars(rows)).status == "timeout"
    assert strict_score(bars(rows), stop=0.02, half_out=None).status == "stop"


# ps3 cost stress: the default must not move, and each stress must cost more in a predictable way.


def test_normal_stress_is_the_default():
    from swing_trade_ml.brain.replay_scoring import NORMAL

    rows = [FLAT] * 2 + [(100, 109, 100, 108)]
    assert strict_score(bars(rows), stress=NORMAL) == strict_score(bars(rows))


def test_double_charges_cost_more_but_do_not_change_the_exit():
    from swing_trade_ml.brain.replay_scoring import CostStress

    rows = [FLAT] * 2 + [(100, 109, 100, 108)]
    base = strict_score(bars(rows))
    double = strict_score(bars(rows), stress=CostStress(charges_x=2.0))
    assert double.status == base.status == "target" and double.days == base.days
    assert double.net_return < base.net_return


def test_worse_fills_cost_about_the_extra_slippage_on_each_side():
    from swing_trade_ml.brain.replay_scoring import CostStress

    rows = [FLAT] * 15
    base = strict_score(bars(rows))
    worse = strict_score(bars(rows), stress=CostStress(extra_slip=0.003))
    assert worse.status == "timeout"
    # buy 0.3% dearer and sell 0.3% cheaper: about 0.6% of the money, a little less because
    # the dearer buy also buys fewer shares
    assert 0.0055 < base.net_return - worse.net_return < 0.0062


def test_worse_buy_fill_moves_the_levels_with_it():
    """Levels are set from the price really paid, as a live order would be."""
    from swing_trade_ml.brain.replay_scoring import CostStress

    # +8% from a fill of 100 plus slippage is touched at 108.2, but not after a 0.3% worse fill
    rows = [(100, 100.5, 99.5, 100)] + [(100, 108.2, 99.5, 100)] + [FLAT] * 13
    assert strict_score(bars(rows), half_out=None).status == "target"
    assert strict_score(bars(rows), half_out=None, stress=CostStress(extra_slip=0.003)).status == "timeout"


def test_stress_labels_are_plain():
    from swing_trade_ml.brain.replay_scoring import NORMAL, CostStress

    assert NORMAL.label == "normal costs"
    assert CostStress(charges_x=2.0, extra_slip=0.003).label == "2x charges, fills 0.30% worse"
