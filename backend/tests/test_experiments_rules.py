"""Horizon experiments (design rev 3): the pure rules, no database.

Session timing: a pick saved before 09:00 IST on a trading day enters at that session's open, otherwise at the
next session's open. The entry session is session 1; the N-day exit is the close of session N. Weekends and
NSE
holidays are skipped, and a year with no holiday list is refused rather than guessed.

Fill maths: equal notional, whole shares, slippage against us on both sides, the frozen charges."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.services.costs import compute_charges
from swing_trade_ml.services.experiments import rules
from swing_trade_ml.services.experiments.protocol import PROTOCOL_V1, frozen_charges

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# ------------------------------------------------------------------ timing --


def test_before_cutoff_on_a_trading_day_enters_that_session():
    assert rules.entry_session(ist(2026, 10, 19, 8, 59)) == date(2026, 10, 19)  # Monday


def test_at_or_after_cutoff_enters_the_next_session():
    # Tuesday 20 Oct 2026 is an NSE holiday (Dussehra), so the next session is Wednesday 21 Oct.
    assert rules.entry_session(ist(2026, 10, 19, 9, 0)) == date(2026, 10, 21)
    assert rules.entry_session(ist(2026, 10, 19, 15, 0)) == date(2026, 10, 21)
    assert rules.entry_session(ist(2026, 10, 21, 9, 30)) == date(2026, 10, 22)


def test_a_weekend_pick_enters_monday():
    assert rules.entry_session(ist(2026, 10, 17, 11, 0)) == date(2026, 10, 19)  # Saturday


def test_cutoff_uses_ist_even_when_given_utc():
    # 03:00 UTC = 08:30 IST, before the cutoff
    assert rules.entry_session(datetime(2026, 10, 19, 3, 0, tzinfo=UTC)) == date(2026, 10, 19)


def test_a_holiday_is_skipped():
    assert rules.entry_session(ist(2026, 10, 20, 8, 0)) == date(2026, 10, 21)  # Dussehra


def test_session_one_is_the_entry_and_session_n_skips_weekends():
    entry = date(2026, 10, 19)  # Monday
    assert rules.session_n(entry, 1) == entry
    # 19 (1), 20 is Dussehra, 21 (2), 22 (3), 23 (4), 24-25 weekend, 26 (5), 27 (6)
    assert rules.session_n(entry, 5) == date(2026, 10, 26)
    assert rules.session_n(entry, 6) == date(2026, 10, 27)


def test_session_n_counts_only_trading_days():
    from swing_trade_ml.core.market_session import is_trading_day

    entry = date(2026, 10, 19)
    exit_day = rules.session_n(entry, 30)
    days = [entry]
    d = entry
    while d < exit_day:
        d = date.fromordinal(d.toordinal() + 1)
        if is_trading_day(d):
            days.append(d)
    assert len(days) == 30 and days[-1] == exit_day


def test_a_year_without_a_holiday_list_is_refused():
    with pytest.raises(rules.CalendarMissingError):
        rules.session_n(date(2030, 12, 20), 30)
    with pytest.raises(rules.CalendarMissingError):
        rules.entry_session(ist(2030, 1, 7, 8))


# ------------------------------------------------------------------- fills --


def test_protocol_v1_is_the_approved_one():
    p = PROTOCOL_V1
    assert p.code == "horizon-v1"
    assert p.horizons == (5, 30)
    assert p.notional_inr == 100_000
    assert p.slippage_bps == 10
    assert p.cutoff_ist == "09:00"
    assert p.dedupe_sessions == 30


def test_frozen_charges_match_todays_cost_model():
    for turnover in (10_000.0, 99_950.5):
        for side in ("BUY", "SELL"):
            assert frozen_charges(PROTOCOL_V1.costs, turnover, side) == pytest.approx(
                sum(compute_charges(turnover, side))
            )


def test_fill_whole_shares_slippage_and_costs():
    f = rules.simulate(entry_open=100.0, exit_close=110.0, protocol=PROTOCOL_V1)
    assert f is not None
    entry_fill, exit_fill = 100.0 * 1.001, 110.0 * 0.999
    qty = int(100_000 // entry_fill)
    assert f.qty == qty
    buy_cost = frozen_charges(PROTOCOL_V1.costs, qty * entry_fill, "BUY")
    sell_cost = frozen_charges(PROTOCOL_V1.costs, qty * exit_fill, "SELL")
    basis = qty * entry_fill + buy_cost
    assert f.gross_return == pytest.approx(0.10)
    assert f.net_return == pytest.approx((qty * exit_fill - sell_cost - basis) / basis)
    assert f.costs_inr == pytest.approx(buy_cost + sell_cost)
    assert f.slippage_inr == pytest.approx(qty * (entry_fill - 100.0) + qty * (110.0 - exit_fill))
    assert f.net_return < f.gross_return


def test_a_flat_trade_loses_money_after_costs():
    f = rules.simulate(entry_open=200.0, exit_close=200.0, protocol=PROTOCOL_V1)
    assert f is not None and f.net_return < 0


def test_a_price_above_the_notional_cannot_be_bought():
    assert rules.simulate(entry_open=150_000.0, exit_close=151_000.0, protocol=PROTOCOL_V1) is None


# ---------------------------------------------------------------- samples --


def test_independent_samples_drop_overlapping_holding_periods():
    windows = [
        (date(2026, 10, 19), date(2026, 10, 23)),
        (date(2026, 10, 20), date(2026, 10, 26)),  # overlaps the first
        (date(2026, 10, 27), date(2026, 10, 30)),
    ]
    assert rules.non_overlapping(windows) == 2


def test_bootstrap_range_is_deterministic_and_contains_the_mean():
    xs = [0.02, -0.01, 0.03, 0.0, -0.02, 0.05, 0.01]
    lo, hi = rules.bootstrap_mean_range(xs)
    assert lo <= sum(xs) / len(xs) <= hi
    assert rules.bootstrap_mean_range(xs) == (lo, hi)


def test_bootstrap_needs_at_least_two_values():
    assert rules.bootstrap_mean_range([0.01]) is None
