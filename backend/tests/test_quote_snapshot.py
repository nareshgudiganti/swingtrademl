"""Price snapshot: a live price and a last-close price are never mixed up.

Pure-function tests — no database. `build_snapshot` takes the stored quote and
the stored daily candles and says which one may be shown, as of when.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from swing_trade_ml.services.quote_snapshot import (
    CandlePoint,
    QuotePoint,
    SnapshotState,
    build_snapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def ist(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)


def candles(*pairs: tuple[date, float]) -> list[CandlePoint]:
    return [CandlePoint(day=d, close=c) for d, c in pairs]


# JAMNAAUTO case: Mon 26 Oct 2026 2:04 pm, market open, last bars 22 and 23 Oct.
D22, D23 = date(2026, 10, 22), date(2026, 10, 23)
BARS = candles((D22, 128.15), (D23, 123.57))
NOW = ist(2026, 10, 26, 14, 4)


def test_live_quote_beats_last_close_and_is_timestamped():
    q = QuotePoint(last_price=124.45, prev_close=123.57, ts=ist(2026, 10, 26, 14, 3))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.LIVE
    assert s.price == 124.45
    assert s.price_ts == q.ts
    assert s.prev_close == 123.57
    assert s.prev_close_date == D23
    assert round(s.change_pct, 2) == 0.71


def test_no_quote_during_session_falls_back_to_last_close_with_its_date():
    s = build_snapshot(NOW, None, BARS)
    assert s.state is SnapshotState.CLOSE_ONLY
    assert s.price == 123.57
    assert s.price_date == D23
    assert round(s.change_pct, 2) == -3.57


def test_stale_quote_from_previous_session_is_not_shown_as_live():
    q = QuotePoint(last_price=123.57, prev_close=128.15, ts=ist(2026, 10, 23, 15, 29))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.STALE
    assert s.change_pct is None


def test_stale_quote_same_day_older_than_fifteen_minutes():
    q = QuotePoint(last_price=124.0, prev_close=123.57, ts=ist(2026, 10, 26, 13, 30))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.STALE


def test_delayed_feed_is_flagged_but_still_shown_with_its_age():
    q = QuotePoint(last_price=124.0, prev_close=123.57, ts=ist(2026, 10, 26, 13, 56))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.DELAYED
    assert s.price == 124.0
    assert s.age_seconds == 8 * 60


def test_quote_in_the_future_is_treated_as_stale_not_live():
    q = QuotePoint(last_price=124.0, prev_close=123.57, ts=ist(2026, 10, 26, 14, 30))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.STALE


def test_mismatched_previous_close_hides_the_change_instead_of_guessing():
    # Quote says yesterday closed at 123.16; our candle says 123.57.
    q = QuotePoint(last_price=124.45, prev_close=123.16, ts=ist(2026, 10, 26, 14, 3))
    s = build_snapshot(NOW, q, BARS)
    assert s.prev_close_mismatch is True
    assert s.change_pct is None
    assert s.price == 124.45
    assert s.state is SnapshotState.LIVE


def test_mismatched_previous_close_date_missing_candle():
    # The 23 Oct bar is missing, so the reference day is not in our candles.
    q = QuotePoint(last_price=124.45, prev_close=123.57, ts=ist(2026, 10, 26, 14, 3))
    s = build_snapshot(NOW, q, candles((D22, 128.15)))
    assert s.prev_close_date is None
    assert s.change_pct is None


def test_market_closed_weekend_uses_friday_close():
    s = build_snapshot(ist(2026, 10, 25, 11, 0), None, BARS)
    assert s.state is SnapshotState.CLOSED
    assert s.price_date == D23
    assert s.prev_close_date == D22


def test_market_holiday_skips_the_holiday_for_previous_close():
    # Tue 20 Oct 2026 (Dussehra) was a holiday: Mon 19 Oct is the previous session.
    d16, d19, d21 = date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 21)
    bars = candles((d16, 100.0), (d19, 102.0), (d21, 99.0))
    s = build_snapshot(ist(2026, 10, 21, 18, 0), None, bars)
    assert s.state is SnapshotState.CLOSED
    assert s.price_date == d21
    assert s.prev_close_date == d19  # not 20 Oct
    assert round(s.change_pct, 2) == round((99 / 102 - 1) * 100, 2)


def test_holiday_today_shows_last_session_and_says_holiday():
    bars = candles((date(2026, 10, 16), 100.0), (date(2026, 10, 19), 102.0))
    s = build_snapshot(ist(2026, 10, 20, 11, 0), None, bars)
    assert s.state is SnapshotState.HOLIDAY
    assert s.price_date == date(2026, 10, 19)


def test_closed_but_latest_bar_missing_is_stale_and_names_the_date():
    # Tue 27 Oct evening, but the newest bar we hold is 23 Oct.
    s = build_snapshot(ist(2026, 10, 27, 18, 0), None, BARS)
    assert s.state is SnapshotState.STALE
    assert s.price_date == D23
    assert s.change_pct is None


def test_gap_between_last_two_bars_hides_change():
    # 21 Oct bar missing: 23 Oct vs 19 Oct is not a one-session move.
    bars = candles((date(2026, 10, 19), 102.0), (D23, 123.57))
    s = build_snapshot(ist(2026, 10, 24, 12, 0), None, bars)
    assert s.state is SnapshotState.CLOSED
    assert s.change_pct is None


def test_no_data_at_all():
    s = build_snapshot(NOW, None, [])
    assert s.state is SnapshotState.NO_DATA
    assert s.price is None


def test_old_stored_quote_does_not_hide_a_newer_close():
    # Prod case: a quote stored on 16 Oct while the daily close of 23 Oct is on file.
    q = QuotePoint(last_price=100.0, prev_close=99.0, ts=ist(2026, 10, 16, 12, 12))
    s = build_snapshot(NOW, q, BARS)
    assert s.state is SnapshotState.CLOSE_ONLY
    assert s.price == 123.57
    assert s.price_date == D23
    assert "Price on file is old" not in s.note
