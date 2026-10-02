"""M15 trade tracker: day-by-day status against the band of similar trades."""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.brain.modules.m15_tracker.track import track

BAND = tuple((d, -0.01 * d / 5, 0.004 * d, 0.01 * d) for d in range(1, 16))  # widening band


def _closes(*rets, entry=100.0):
    return [(date(2026, 9, 1 + i), entry * (1 + r)) for i, r in enumerate(rets, start=1)]


def test_inside_the_band_is_on_track():
    t = track("ABC", 100.0, _closes(0.005, 0.01, 0.012), stop=96.0, band=BAND, atr_pct=0.02)
    assert t.status == "on track" and t.day_n == 3 and t.ret == pytest.approx(0.012)
    assert t.reason.startswith("Day 3 of up to 15: +1.2%, inside the usual range of similar trades")


def test_below_the_band_but_above_the_stop_is_drift():
    t = track("ABC", 100.0, _closes(0.0, -0.01, -0.02), stop=96.0, band=BAND, atr_pct=0.02)
    assert t.status == "drift" and "below the usual range" in t.reason and "above the stop" in t.reason


def test_well_below_the_band_is_breakdown():
    t = track("ABC", 100.0, _closes(-0.01, -0.02, -0.035), stop=96.0, band=BAND, atr_pct=0.01)
    assert t.status == "breakdown"


def test_at_or_below_the_stop_is_stop_hit_with_no_choice():
    t = track("ABC", 100.0, _closes(-0.01, -0.045), stop=96.0, band=BAND, atr_pct=0.02)
    assert t.status == "stop hit" and t.reason.startswith("Stop hit at ₹96")
    assert "?" not in t.reason and "consider" not in t.reason.lower()


def test_bought_today_is_on_track_without_a_band():
    t = track("ABC", 100.0, [], stop=96.0, band=BAND, atr_pct=0.02)
    assert t.status == "on track" and t.day_n == 0 and t.band_low is None


def test_past_the_horizon_says_so():
    t = track("ABC", 100.0, _closes(*([-0.03] * 17)), stop=96.0, band=BAND, atr_pct=0.01)
    assert t.status == "past horizon" and "30 calendar days" in t.reason
