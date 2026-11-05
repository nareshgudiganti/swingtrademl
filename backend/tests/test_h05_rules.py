# ruff: noqa: N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""h05 lane: the pure rules. Sessions, the endpoint label, the shadow trade, ranking, repeats, the guards.

No database. The trade tests use a hand-made calendar with a weekend and a holiday so "five sessions" is
proved to mean market sessions, not calendar days.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain.five_day_train import endpoint_target
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R

# Mon 5 Oct 2026 ... a week with a holiday on Thu 8 Oct and a weekend, then the next week.
SESSIONS = [date(2026, 10, d) for d in (5, 6, 7, 9, 12, 13, 14, 15, 16, 19, 20)]
SIGNAL = date(2026, 10, 6)  # sessions 1..5 after it: 7, 9, 12, 13, 14


def flat(price: float = 100.0) -> dict:
    return dict.fromkeys(SESSIONS, (price, price, price, price))


def test_five_sessions_skip_weekends_and_the_holiday():
    window = R.sessions_after(SESSIONS, SIGNAL, 5)
    assert window == [
        date(2026, 10, 7),
        date(2026, 10, 9),
        date(2026, 10, 12),
        date(2026, 10, 13),
        date(2026, 10, 14),
    ]
    assert (window[-1] - SIGNAL).days == 8  # eight calendar days, five sessions


def test_fewer_than_five_sessions_left_is_pending_not_guessed():
    closes = {d: b[3] for d, b in flat().items()}
    assert R.endpoint_outcome(closes, SESSIONS, date(2026, 10, 16)).status == "pending"
    assert R.simulate_trade(flat(), SESSIONS, date(2026, 10, 16), 100.0, "large").status == "pending"


# ----------------------------------------------------------------- the endpoint label


def test_endpoint_label_matches_the_training_expression_exactly():
    closes = {d: 100.0 + i for i, d in enumerate(SESSIONS)}
    out = R.endpoint_outcome(closes, SESSIONS, SIGNAL)
    frame = pd.DataFrame({"forward_return": [closes[date(2026, 10, 13)] / closes[SIGNAL] - 1]})
    assert out.label == int(endpoint_target(frame, 0.02)["target"].iloc[0])  # the trainer's own rule
    assert out.day5 == date(2026, 10, 14)


@pytest.mark.parametrize("close5,hit", [(102.0, 1), (101.99, 0), (102.01, 1), (95.0, 0)])
def test_endpoint_label_boundary_at_plus_two_percent(close5, hit):
    closes = flat(100.0)
    closes[date(2026, 10, 14)] = (close5,) * 4
    c = {d: b[3] for d, b in closes.items()}
    assert R.endpoint_outcome(c, SESSIONS, SIGNAL).label == hit


def test_missing_session_five_candle_is_not_evaluated_not_the_next_bar():
    c = dict.fromkeys(SESSIONS, 100.0)
    del c[date(2026, 10, 14)]
    c[date(2026, 10, 15)] = 120.0  # the stock's own "5th bar" would have been a +20% hit
    out = R.endpoint_outcome(c, SESSIONS, SIGNAL)
    assert out.status == "not_evaluated" and out.label is None


# ----------------------------------------------------------------- the shadow trade


def bars_with(**days: tuple) -> dict:
    """bars_with(n1=bar, n5=bar): n<k> is trading session k after the signal (7, 9, 12, 13, 14 Oct)."""
    b = flat(100.0)
    for key, bar in days.items():
        b[R.sessions_after(SESSIONS, SIGNAL, 5)[int(key[1:]) - 1]] = bar
    return b


def test_target_hit_exits_at_the_level_and_is_a_win():
    t = R.simulate_trade(bars_with(n2=(100, 103, 100, 102)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "target" and t.sessions_held == 2 and t.exit_day == date(2026, 10, 9)
    assert t.net_return > 0 and not t.ambiguous and not t.gap_fill


def test_stop_hit_exits_at_the_level_and_is_a_loss():
    t = R.simulate_trade(bars_with(n1=(100, 100, 95, 96)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "stop" and t.sessions_held == 1 and t.net_return < -0.04


def test_expiry_sells_at_the_close_of_session_five_with_entry_session_counted_as_one():
    t = R.simulate_trade(bars_with(n5=(100, 101, 99, 100.5)), SESSIONS, SIGNAL, 100.0, "mid")
    assert t.status == "expiry" and t.sessions_held == 5
    assert t.exit_day == date(2026, 10, 14) and t.exit_price == 100.5


def test_gap_through_the_stop_fills_at_the_open_not_the_level():
    t = R.simulate_trade(bars_with(n2=(90, 91, 89, 90)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "stop" and t.gap_fill and t.exit_price == 90 and "gap_fill" in t.flags


def test_gap_through_the_target_fills_at_the_open():
    t = R.simulate_trade(bars_with(n2=(105, 106, 104, 105)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "target" and t.gap_fill and t.exit_price == 105


def test_a_candle_touching_both_levels_is_the_stop_and_is_flagged_ambiguous():
    t = R.simulate_trade(bars_with(n1=(100, 104, 95, 100)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "stop" and t.ambiguous and "same_candle_both_levels" in t.flags


def test_a_missing_candle_in_the_window_leaves_the_trade_unresolved():
    b = flat()
    del b[date(2026, 10, 12)]
    t = R.simulate_trade(b, SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "unresolved" and "missing_candle" in t.flags


def test_a_missing_candle_after_the_exit_does_not_matter():
    b = bars_with(n1=(100, 100, 95, 96))
    del b[date(2026, 10, 13)]
    assert R.simulate_trade(b, SESSIONS, SIGNAL, 100.0, "large").status == "stop"


def test_a_big_overnight_move_inside_the_window_is_flagged_not_removed():
    t = R.simulate_trade(bars_with(n2=(130, 131, 129, 130)), SESSIONS, SIGNAL, 100.0, "large")
    assert "possible_corporate_action" in t.flags and t.status == "target"


def test_a_stock_too_dear_for_the_notional_is_unresolved():
    t = R.simulate_trade(dict.fromkeys(SESSIONS, (200000.0,) * 4), SESSIONS, SIGNAL, 200_000.0, "large")
    assert t.status == "unresolved" and "too_expensive" in t.flags


def test_costs_make_the_net_return_smaller_than_the_gross_move():
    t = R.simulate_trade(bars_with(n5=(100, 100.5, 99.5, 100.0)), SESSIONS, SIGNAL, 100.0, "large")
    assert t.status == "expiry" and t.net_return < 0 and t.costs_inr > 0


def test_the_endpoint_label_and_the_trade_outcome_are_separate_answers():
    """Falls 5% on session 1 (stopped out), then recovers to +3% by session 5: the model's question is
    answered YES while the shadow trade lost money."""
    b = bars_with(n1=(100, 100, 94, 95), n5=(103, 104, 102, 103))
    label = R.endpoint_outcome({d: x[3] for d, x in b.items()}, SESSIONS, SIGNAL)
    trade = R.simulate_trade(b, SESSIONS, SIGNAL, 100.0, "large")
    assert label.label == 1 and trade.status == "stop" and trade.net_return < 0


def test_group_slippage_is_applied_per_group(monkeypatch):
    monkeypatch.setitem(P.SLIPPAGE_BPS, "small", 50.0)
    flat_bars = bars_with(n5=(100, 100.5, 99.5, 100.0))
    big = R.simulate_trade(flat_bars, SESSIONS, SIGNAL, 100.0, "large")
    small = R.simulate_trade(flat_bars, SESSIONS, SIGNAL, 100.0, "small")
    assert small.net_return < big.net_return


# ----------------------------------------------------------------- ranking and selection


def test_ranking_is_within_one_group_and_ties_break_by_symbol():
    ranked = R.rank_group([("ZED", 0.7), ("ABC", 0.7), ("MID", 0.9), ("LOW", 0.1)])
    assert [(s, r) for s, _, r in ranked] == [("MID", 1), ("ABC", 2), ("ZED", 3), ("LOW", 4)]
    assert R.rank_group([("ZED", 0.7), ("ABC", 0.7)]) == R.rank_group([("ABC", 0.7), ("ZED", 0.7)])


def test_top_five_with_a_shortfall_when_a_group_is_small():
    ranked = R.rank_group([(f"S{i}", 1 - i / 10) for i in range(3)])
    chosen, shortfall = R.select_top(ranked)
    assert chosen == ["S0", "S1", "S2"] and shortfall == 2
    ranked = R.rank_group([(f"S{i}", 1 - i / 100) for i in range(40)])
    assert len(R.select_top(ranked)[0]) == 5 and R.select_top(ranked)[1] == 0


def test_a_repeat_inside_five_sessions_is_blocked_and_may_count_again_on_session_five():
    sel = {SESSIONS[0]: ["AAA"], SESSIONS[1]: ["AAA", "BBB"], SESSIONS[5]: ["AAA"]}
    blocked = R.repeat_blocked(sel, SESSIONS)
    assert (SESSIONS[1], "AAA") in blocked
    assert (SESSIONS[1], "BBB") not in blocked
    assert (SESSIONS[5], "AAA") not in blocked  # five sessions after the counted one at index 0


# ----------------------------------------------------------------- uncertainty


def test_block_range_is_none_for_a_short_series_and_ordered_otherwise():
    assert R.block_range([0.1] * 6) is None
    lo, hi = R.block_range([(-1) ** i * 0.01 + 0.002 for i in range(60)])
    assert lo < hi


def test_random_k_distribution_is_seeded_and_sorted():
    pools = [[0.01, -0.02, 0.03, 0.0, -0.01, 0.02]] * 20
    a = R.random_k_distribution(pools)
    assert a == R.random_k_distribution(pools) and a == sorted(a)


# ----------------------------------------------------------------- the protocol guards


def test_the_lane_is_disabled_by_default_and_every_write_refuses():
    with pytest.raises(P.ProtocolError, match="disabled"):
        P.require_runnable(P.H05Settings(ENABLED=False))


def test_an_incomplete_protocol_refuses_even_when_accepted(monkeypatch):
    monkeypatch.setitem(P.RUN_VALUES, "run_length_sessions", None)  # a value the owner has not set
    s = P.H05Settings(ENABLED=True, ACCEPTED_PROTOCOL_HASH=P.protocol_hash())
    with pytest.raises(P.ProtocolError, match="incomplete"):
        P.require_runnable(s)


def test_an_unaccepted_or_changed_protocol_refuses(monkeypatch):
    with pytest.raises(P.ProtocolError, match="not been accepted"):
        P.require_runnable(P.H05Settings(ENABLED=True, ACCEPTED_PROTOCOL_HASH="wrong"))
    with pytest.raises(P.ProtocolError, match="not been accepted"):
        P.require_runnable(P.H05Settings(ENABLED=True, ACCEPTED_PROTOCOL_HASH=""))
    accepted = P.H05Settings(ENABLED=True, ACCEPTED_PROTOCOL_HASH=P.protocol_hash())
    P.require_runnable(accepted)  # all three conditions met
    monkeypatch.setitem(P.RULES, "entry", "a changed rule")
    with pytest.raises(P.ProtocolError, match="not been accepted"):
        P.require_runnable(accepted)  # the accepted hash no longer matches the rules


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.setitem(P.SLIPPAGE_BPS, "small", 99.0),
        lambda m: m.setitem(P.STRESS, "charges_x", 3.0),
        lambda m: m.setitem(P.FEATURE_CODE_SHA256, "ml/features.py", "0" * 64),
        lambda m: m.setitem(P.EXPECTED_MODELS["mid"], "sha256", "0" * 64),
        lambda m: m.setitem(P.RUN_VALUES, "run_length_sessions", 30),
        lambda m: m.setattr(P, "PRIMARY_BASIS", "production_path"),
    ],
)
def test_every_frozen_part_is_inside_the_protocol_hash(monkeypatch, change):
    before = P.protocol_hash()
    change(monkeypatch)
    assert P.protocol_hash() != before


def test_protocol_pins_the_existing_models_and_the_five_day_question():
    assert [P.EXPECTED_MODELS[g]["id"] for g in P.GROUPS] == [2, 16, 17]
    assert (P.HORIZON, P.LABEL_TARGET, P.LABEL_KIND) == (5, 0.02, "endpoint")
    assert (P.TRADE_TARGET, P.TRADE_STOP, P.TRADE_SESSIONS, P.TOP_K) == (0.02, 0.04, 5, 5)
    assert timedelta  # keep the import honest


# ----------------------------------------------------------------- position size and rounding


def test_position_size_is_whole_shares_of_one_lakh_and_charges_are_a_share_of_what_was_invested():
    """Flat price 3,000: floor(100000 / (3000 x 1.001)) = 33 shares, so about Rs 99,100 is invested and the
    Rs 15.93 depository charge is a percentage of THAT amount, not of the Rs 1,00,000 notional."""
    price = 3000.0
    t = R.simulate_trade(dict.fromkeys(SESSIONS, (price,) * 4), SESSIONS, SIGNAL, price, "large")
    slip = P.SLIPPAGE_BPS["large"] / 10_000
    fill_in, fill_out = price * (1 + slip), price * (1 - slip)
    qty = int(P.NOTIONAL_INR // fill_in)
    assert qty == 33
    cost = qty * fill_in + R.charges(qty * fill_in, "BUY")
    proceeds = qty * fill_out - R.charges(qty * fill_out, "SELL")
    assert t.net_return == pytest.approx((proceeds - cost) / cost, abs=1e-12)
    assert R.charges(qty * fill_out, "SELL") == pytest.approx(
        qty * fill_out * P.COSTS["tax_bps_sell"] / 10_000 + P.COSTS["dp_charge_per_sell"]
    )
    # the same flat Rs 100 stock invests 999 shares (Rs 99,900): rounding changes the charge share slightly
    cheap = R.simulate_trade(flat(100.0), SESSIONS, SIGNAL, 100.0, "large")
    assert cheap.net_return != t.net_return


def test_a_price_above_the_notional_buys_no_share_and_is_unresolved():
    t = R.simulate_trade(flat(150_000.0), SESSIONS, SIGNAL, 150_000.0, "large")
    assert t.status == "unresolved" and "too_expensive" in t.flags and t.net_return is None
