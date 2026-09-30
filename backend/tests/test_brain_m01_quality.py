"""M01's pure quality assessor: is this stock's price data fresh, complete
and believable, and is the market's data as a whole good enough to trade on?"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from swing_trade_ml.brain.contracts import DataQuality
from swing_trade_ml.brain.modules.m01_quality.quality import (
    assess_bars,
    expected_bar_day,
    summarise,
    trading_days_between,
)
from swing_trade_ml.core.holidays import is_trading_holiday


def _trading_days_ending(last: date, n: int) -> list[date]:
    days, d = [], last
    while len(days) < n:
        if d.weekday() < 5 and not is_trading_holiday(d):
            days.append(d)
        d -= timedelta(days=1)
    return sorted(days)


def _bars(last: date, n: int = 250, close: float = 100.0, edits: dict | None = None) -> pd.DataFrame:
    days = _trading_days_ending(last, n)
    df = pd.DataFrame(
        {
            "day": days,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        }
    )
    for (i, col), value in (edits or {}).items():
        df.loc[len(df) + i if i < 0 else i, col] = value
    return df


FRI = date(2026, 9, 25)  # a normal trading Friday
MON = date(2026, 9, 28)


# --- expected bar day ----------------------------------------------------------


def test_after_ingest_todays_bar_is_expected():
    assert expected_bar_day(datetime(2026, 9, 28, 16, 0, tzinfo=UTC) + timedelta(hours=0)) == MON


def test_before_ingest_the_previous_trading_days_bar_is_expected():
    # 09:00 IST on Monday = 03:30 UTC
    assert expected_bar_day(datetime(2026, 9, 28, 3, 30, tzinfo=UTC)) == FRI


def test_on_a_holiday_the_last_trading_day_is_expected():
    # 2 Oct 2026 (Friday) is Gandhi Jayanti; evening of that day
    assert expected_bar_day(datetime(2026, 10, 2, 14, 0, tzinfo=UTC)) == date(2026, 10, 1)


def test_weekends_and_holidays_are_not_trading_days():
    assert trading_days_between(FRI, MON) == 1
    assert trading_days_between(date(2026, 10, 1), date(2026, 10, 5)) == 1  # Fri 2 Oct holiday + weekend
    assert trading_days_between(MON, MON) == 0


# --- one stock ----------------------------------------------------------------


def test_a_fresh_clean_stock_scores_full_marks():
    q = assess_bars("ABC", _bars(MON), MON, set())
    assert q.score == 1.0 and q.fresh and q.issues == ()
    assert q.last_bar_date == "2026-09-28"


def test_one_trading_day_behind_is_not_fresh_and_says_so():
    q = assess_bars("ABC", _bars(FRI), MON, set())
    assert not q.fresh and q.score == pytest.approx(0.5)
    assert "25 Sep 2026" in q.issues[0] and "1 trading day" in q.issues[0]


def test_many_days_behind_scores_low():
    q = assess_bars("ABC", _bars(date(2026, 9, 7)), MON, set())
    assert q.score == pytest.approx(0.2) and not q.fresh


def test_a_split_on_its_ex_date_is_not_a_spike():
    bars = _bars(MON, edits={(-1, "close"): 50.0, (-1, "open"): 50.0, (-1, "high"): 51.0, (-1, "low"): 49.0})
    assert assess_bars("ABC", bars, MON, {MON}).fresh
    assert assess_bars("ABC", bars, MON, set()).score == pytest.approx(0.7)


def test_an_unexplained_big_jump_is_flagged():
    bars = _bars(MON, edits={(-3, "close"): 125.0, (-3, "high"): 126.0})
    q = assess_bars("ABC", bars, MON, set())
    assert any("moved 25%" in i for i in q.issues)


def test_zero_volume_is_flagged():
    q = assess_bars("ABC", _bars(MON, edits={(-2, "volume"): 0.0}), MON, set())
    assert q.score == pytest.approx(0.8) and any("volume" in i for i in q.issues)


def test_an_impossible_bar_is_flagged():
    q = assess_bars("ABC", _bars(MON, edits={(-4, "high"): 90.0}), MON, set())
    assert any("impossible" in i for i in q.issues)


def test_short_history_is_flagged():
    q = assess_bars("ABC", _bars(MON, n=100), MON, set())
    assert q.score == pytest.approx(0.7) and any("100 days of history" in i for i in q.issues)


def test_a_gap_in_recent_bars_is_flagged():
    bars = _bars(MON)
    bars = bars.drop(index=range(len(bars) - 20, len(bars) - 15)).reset_index(drop=True)
    q = assess_bars("ABC", bars, MON, set())
    assert any("gap" in i for i in q.issues)


def test_no_bars_at_all_scores_zero():
    q = assess_bars("ABC", _bars(MON).iloc[0:0], MON, set())
    assert q.score == 0.0 and not q.fresh and q.issues == ("No price data for this stock.",)


def test_penalties_never_push_the_score_below_zero():
    bars = _bars(date(2026, 9, 1), n=50, edits={(-1, "volume"): 0.0, (-2, "high"): 1.0})
    assert assess_bars("ABC", bars, MON, set()).score == 0.0


# --- the whole market ----------------------------------------------------------


def _q(symbol, fresh=True, score=1.0):
    return DataQuality(symbol=symbol, score=score, fresh=fresh)


def test_market_is_fresh_when_benchmark_and_most_stocks_are():
    stocks = [_q(f"S{i}") for i in range(9)] + [_q("S9", fresh=False, score=0.5)]
    overall = summarise(stocks, _q("NIFTY 50"), {})
    assert overall.symbol == "*" and overall.fresh and overall.score == pytest.approx(0.95)


def test_market_is_not_fresh_when_the_benchmark_is_stale():
    overall = summarise([_q("S1")], _q("NIFTY 50", fresh=False, score=0.2), {})
    assert not overall.fresh and any("NIFTY" in i for i in overall.issues)


def test_market_is_not_fresh_when_too_many_stocks_are_stale():
    stocks = [_q("S1"), _q("S2", fresh=False, score=0.2), _q("S3", fresh=False, score=0.2)]
    overall = summarise(stocks, _q("NIFTY 50"), {})
    assert not overall.fresh and any("2 of 3" in i for i in overall.issues)


def test_missing_benchmark_is_not_fresh():
    assert not summarise([_q("S1")], None, {}).fresh


def test_late_feeds_are_reported_but_do_not_stop_trading_alone():
    overall = summarise([_q("S1")], _q("NIFTY 50"), {"delivery": 3})
    assert overall.fresh and any("delivery" in i and "3 trading days" in i for i in overall.issues)
