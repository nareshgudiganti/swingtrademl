"""M15 trade tracker: day-by-day status against the band of similar trades."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, registry
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, MarketMode
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m05_memory.recall import similar_cases
from swing_trade_ml.brain.modules.m08_decide.engine import HoldingFacts, decide_holding
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m15_tracker.module import Tracker
from swing_trade_ml.brain.modules.m15_tracker.track import after_first_target, track
from swing_trade_ml.brain.runner import execute

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


# --- similar cases and the first-target evidence ------------------------------------------------


def _case(outcome, peak, n):
    path = [peak * (d + 1) / 15 for d in range(15)]
    return pd.DataFrame({"outcome": [outcome] * n, "path": [path] * n})


def test_similar_cases_returns_the_matches_and_what_was_dropped():
    cases = pd.DataFrame(
        {
            "market": ["up-trend"] * 40,
            "stock": ["up"] * 40,
            "trend": ["rising"] * 40,
            "vol": ["high"] * 40,
            "outcome_day": [date(2026, 1, 1)] * 40,
        }
    )
    key = {"market": "up-trend", "stock": "up", "trend": "rising", "vol": "normal"}
    found, dropped = similar_cases(cases, key, date(2026, 9, 1))
    assert len(found) == 40 and dropped == ("vol",)


def test_after_the_first_target_says_how_many_went_on_to_eight():
    cases = pd.concat([_case("target", 0.09, 18), _case("timeout", 0.06, 22), _case("stop", 0.02, 50)])
    assert after_first_target(cases) == "Of 40 similar trades that reached +5%, 45% went on to reach +8%."


def test_too_few_similar_trades_reached_five_percent_says_nothing():
    assert after_first_target(_case("target", 0.09, 10)) is None


# --- the module --------------------------------------------------------------------------------

ENTRY = date(2026, 8, 3)


def _stock_bars(n_before=260, after=(0.01, 0.02, 0.025)):
    days = list(pd.bdate_range(end=ENTRY, periods=n_before).date)
    closes = list(100 * (1.002 ** np.arange(n_before)))
    entry_close = closes[-1]
    days += list(pd.bdate_range(ENTRY, periods=len(after) + 1).date[1:])
    closes += [entry_close * (1 + r) for r in after]
    closes = np.asarray(closes)
    return pd.DataFrame(
        {
            "day": days,
            "open": closes,
            "high": closes * 1.01,
            "low": closes * 0.99,
            "close": closes,
            "volume": 1e5,
        }
    ), float(entry_close)


def _known_cases(n=40, stock="up", trend="rising"):
    return pd.DataFrame(
        {
            "market": ["up-trend"] * n,
            "stock": [stock] * n,
            "trend": [trend] * n,
            "vol": ["normal"] * n,
            "outcome": ["timeout"] * n,
            "exit_return": [0.01] * n,
            "days": [15] * n,
            "outcome_day": [date(2026, 1, 1)] * n,
            "path_day": [date(2026, 1, 1)] * n,
            "path": [[0.002 * (d + 1) for d in range(15)]] * n,
        }
    )


class TrackReader(FakeReader):
    def __init__(self, bars, cases, **kw):
        super().__init__(**kw)
        self.as_of = datetime(2026, 8, 6, 12, tzinfo=UTC)
        self._b, self._cases = bars, cases

    def dated_bars(self, symbol):
        return self._b

    def dated_closes(self, symbol):
        return pd.Series(100 * (1.001 ** np.arange(300)), index=pd.bdate_range(end=ENTRY, periods=300).date)

    def experience(self):
        return self._cases


def _track_run(reader, holding):
    reader._holdings = (holding,)
    req = c.RunRequest(run_id="t", kind="intraday", as_of=reader.as_of, universe=(), live=True)
    return execute(req, reader, registry(Tracker), {"M15": Mode.ON})


def test_m15_is_a_state_plugin_that_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M15") is Tracker
    assert Tracker.manifest.step is Step.STATE and Tracker.manifest.default_mode is Mode.ON


def test_a_holding_is_tracked_against_the_band_of_its_entry_day_situation():
    bars, entry = _stock_bars()
    holding = c.Holding(symbol="ABC", qty=10, avg_price=entry, stop=entry * 0.96, opened_on=ENTRY)
    ctx = _track_run(TrackReader(bars, _known_cases()), holding)
    t = ctx.tracks["ABC"]
    assert t.day_n == 3 and t.status == "on track" and t.band_low == pytest.approx(0.006)
    assert len(t.band) == 15


def test_without_similar_cases_the_overall_path_is_used():
    bars, entry = _stock_bars()
    holding = c.Holding(symbol="ABC", qty=10, avg_price=entry, stop=entry * 0.96, opened_on=ENTRY)
    ctx = _track_run(TrackReader(bars, _known_cases(stock="down", trend="falling hard")), holding)
    t = ctx.tracks["ABC"]
    assert t.band and "compared with all past trades" in t.reason


def test_a_holding_without_entry_date_is_skipped():
    bars, entry = _stock_bars()
    ctx = _track_run(TrackReader(bars, _known_cases()), c.Holding(symbol="ABC", qty=10, avg_price=entry))
    assert ctx.tracks == {}


def test_at_the_first_target_the_evidence_is_attached():
    bars, entry = _stock_bars(after=(0.02, 0.04, 0.06))
    holding = c.Holding(symbol="ABC", qty=10, avg_price=entry, stop=entry * 0.96, opened_on=ENTRY)
    cases = _known_cases()
    cases["path"] = [[0.006 * (d + 1) for d in range(15)]] * len(cases)  # all reached +5%
    cases.loc[:19, "outcome"] = "target"
    t = _track_run(TrackReader(bars, cases), holding).tracks["ABC"]
    assert t.first_target_note == "Of 40 similar trades that reached +5%, 50% went on to reach +8%."


# --- holding words in the decision engine ------------------------------------------------------


def _facts(point, gain=0.01, mode=MarketMode.NORMAL, trend="up", scaled=False, notes=()):
    h = c.Holding(symbol="ABC", qty=10, avg_price=100.0, stop=96.0, scaled_out=scaled, opened_on=ENTRY)
    snap = c.Snapshot(symbol="ABC", as_of="d", close=100.0 * (1 + gain))
    return HoldingFacts(
        holding=h,
        snapshot=snap,
        stock=c.StockState(symbol="ABC", trend=trend),
        market_mode=mode,
        notes=notes,
        track=point,
    )


def _point(status, reason, **kw):
    return c.TrackPoint(symbol="ABC", day_n=4, ret=kw.pop("ret", 0.01), status=status, reason=reason, **kw)


def test_on_track_stays_hold_and_shows_the_day_count():
    d = decide_holding(
        _facts(_point("on track", "Day 4 of up to 15: +1.0%, inside the usual range.")), DecidePolicy()
    )
    assert d.word is HoldingWord.HOLD and "Day 4 of up to 15" in d.reasons[-1]


def test_drift_is_monitor_and_says_what_changed():
    point = _point(
        "drift", "Day 4 of up to 15: -2.0%, below the usual range of similar trades but above the stop."
    )
    d = decide_holding(
        _facts(
            point,
            gain=-0.02,
            mode=MarketMode.DEFENSIVE,
            trend="down",
            notes=("Sector: IT, ranked 15 of 15, lagging (weaker than NIFTY).",),
        ),
        DecidePolicy(),
    )
    assert d.word is HoldingWord.MONITOR and d.reasons[0].startswith("Day 4 of up to 15: -2.0%")
    assert (
        "What has changed: the market is careful (DEFENSIVE); its own trend has turned down; "
        "its sector is lagging NIFTY." in d.reasons[0]
    )


def test_drift_with_nothing_obvious_says_so():
    point = _point("breakdown", "Day 4 of up to 15: -3.5%, well below the usual range of similar trades.")
    d = decide_holding(_facts(point, gain=-0.035), DecidePolicy())
    assert d.word is HoldingWord.MONITOR and "nothing obvious in the market or its sector" in d.reasons[0]


def test_at_the_first_target_the_evidence_joins_the_reduce_reason():
    note = "Of 40 similar trades that reached +5%, 50% went on to reach +8%."
    point = _point(
        "on track", "Day 4 of up to 15: +6.0%, inside the usual range.", ret=0.06, first_target_note=note
    )
    d = decide_holding(_facts(point, gain=0.06), DecidePolicy())
    assert d.word is HoldingWord.REDUCE and note in d.reasons[0]
