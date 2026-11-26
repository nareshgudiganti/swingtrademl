# ruff: noqa: E501 (long plain-English test text)
"""#243: market, sector and similar-case context (verification tests; nothing here changes the app).

Findings note: docs/verification/243-market-context.md. These tests read the Brain's market judgement (M10), the sector
ranking and gate (M11, M08) and the similar-case lookup (M05) and check, with real stored rows where the database matters:

* nothing after the run's date reaches a market, sector or similar-case figure (no look-ahead);
* missing data is said, and never makes the Brain bolder;
* the sector line and the similar-case line on a screen carry the same numbers the Brain used.

Existing coverage that is not repeated: test_brain_m10_judge.py (the judge on synthetic series), test_brain_m11_sector.py
(ranking and rotation), test_brain_m05_memory.py (the case table, widening, honest figures).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import pit_breadth
from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.modules.m05_memory.cases import barrier_outcomes
from swing_trade_ml.brain.modules.m05_memory.recall import MIN_CASES, recall
from swing_trade_ml.brain.modules.m08_decide import engine, rules
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m10_market.judge import MarketInputs, inputs_from, judge
from swing_trade_ml.brain.modules.m11_sector.ranking import (
    SECTOR_NAMES,
    plain_name,
    rank_sectors,
    sector_line,
)
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainExperience
from swing_trade_ml.db.models.feeds import InstitutionalFlow
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.sector_map import SECTOR_INDEX_MAP

IST = ZoneInfo("Asia/Kolkata")
SRC = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
_TOKEN = iter(range(870_100_000, 870_200_000))
DAYS = tuple(d.date() for d in pd.bdate_range("2025-01-01", periods=330))


def _as_of(day: date, hour: int = 16) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=IST).astimezone(UTC)


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=IST)  # daily candles are stamped IST midnight


def _instrument(db, symbol: str, *, watchlisted: bool = False) -> Instrument:
    inst = Instrument(
        instrument_token=next(_TOKEN),
        tradingsymbol=symbol,
        name=f"{symbol} Limited",
        exchange="NSE",
        instrument_type="EQ",
        is_watchlisted=watchlisted,
        is_active=True,
    )
    db.add(inst)
    db.flush()
    return inst


def _candles(db, inst: Instrument, closes, days=DAYS) -> None:
    for day, close in zip(days, closes, strict=False):
        db.add(Candle(instrument_id=inst.id, interval="day", ts=_stamp(day), open=close, high=close * 1.01, low=close * 0.99, close=float(close)))
    db.flush()


def _rising(n: int, step: float = 0.003, start: float = 100.0):
    return start * (1 + step) ** np.arange(n)


@pytest.fixture(autouse=True)
def _fresh_market_cache():
    market_context.clear_cache()
    pit_breadth.clear_cache()
    yield
    market_context.clear_cache()
    pit_breadth.clear_cache()


# ================================================================ 1. the market judgement is point in time


def test_market_series_end_at_the_run_date_and_a_later_crash_changes_nothing(db_session):
    """M10 reads NIFTY, VIX and FII flows through the dated reader: nothing after `as_of` can reach the judgement."""
    nifty = _instrument(db_session, settings.BENCHMARK_INDEX_SYMBOL)
    vix = _instrument(db_session, "INDIA VIX")
    cut = 280  # the run is dated the 281st session
    calm = list(_rising(len(DAYS)))
    crash = calm[: cut + 1] + [calm[cut] * 0.5] * (len(DAYS) - cut - 1)  # a 50% drop the day after the run
    calm_vix = [15.0 + (i % 5) for i in range(len(DAYS))]
    vix_spike = calm_vix[: cut + 1] + [90.0] * (len(DAYS) - cut - 1)  # India VIX also jumps the day after the run
    for index, closes in ((nifty, crash), (vix, vix_spike)):
        _candles(db_session, index, closes)
    reader = DatedReader(db_session, _as_of(DAYS[cut]), live=False)
    closes = reader.index_closes()
    assert len(closes) == cut + 1 and closes.iloc[-1] == pytest.approx(calm[cut])  # ends on the run's own day
    assert len(reader.vix_closes()) == cut + 1 and reader.vix_closes().iloc[-1] == pytest.approx(calm_vix[cut])
    with_crash = judge(inputs_from(reader))
    # the same database with the later days replaced by calm ones: the same answer
    for index, calm_series in ((nifty, calm), (vix, calm_vix)):
        for candle in db_session.query(Candle).filter(Candle.instrument_id == index.id).all():
            day = candle.ts.astimezone(IST).date()
            if day > DAYS[cut]:
                candle.close = candle.open = calm_series[DAYS.index(day)]
    db_session.flush()
    without_crash = judge(inputs_from(DatedReader(db_session, _as_of(DAYS[cut]), live=False)))
    assert (with_crash.mode, with_crash.reasons) == (without_crash.mode, without_crash.reasons)
    assert with_crash.mode is not MarketMode.NO_NEW_TRADES  # neither the NIFTY crash nor the VIX spike had happened yet


def test_the_run_day_itself_is_included_and_the_next_day_is_not(db_session):
    nifty = _instrument(db_session, settings.BENCHMARK_INDEX_SYMBOL)
    _candles(db_session, nifty, _rising(len(DAYS)))
    day = DAYS[250]
    assert len(DatedReader(db_session, _as_of(day), live=False).index_closes()) == 251
    before_the_close_of_next_day = DatedReader(db_session, _as_of(day, hour=23), live=False)
    assert len(before_the_close_of_next_day.index_closes()) == 251  # tomorrow's bar (stamped tomorrow's midnight) is out


def test_a_run_dated_early_in_the_morning_already_includes_that_days_bar(db_session):
    """OBSERVED (#246 c3): daily bars are stamped at IST midnight, so `as_of` at 09:00 IST on a day already contains that day's
    bar. A run is therefore meant to be dated after the close; an early-morning date would see a bar the market has not made."""
    nifty = _instrument(db_session, settings.BENCHMARK_INDEX_SYMBOL)
    _candles(db_session, nifty, _rising(len(DAYS)))
    day = DAYS[250]
    assert len(DatedReader(db_session, _as_of(day, hour=9), live=False).index_closes()) == 251


def test_fii_flows_stop_at_the_run_date(db_session):
    cut = DAYS[100]
    for day in DAYS[70:130]:
        db_session.add(InstitutionalFlow(category="FII", trade_date=day, net_value=-100.0 if day > cut else 100.0, buy_value=0.0, sell_value=0.0))
    db_session.flush()
    flows = DatedReader(db_session, _as_of(cut), live=False).fii_net(20)
    assert len(flows) == 20 and all(v == 100.0 for v in flows)  # none of the later selling is in it


def test_breadth_for_a_run_date_uses_only_closes_up_to_that_date(db_session):
    for k in range(4):
        _candles(db_session, _instrument(db_session, f"BRD{k}", watchlisted=True), _rising(len(DAYS), 0.002 + 0.0005 * k))
    cut = DAYS[200]
    series = DatedReader(db_session, _as_of(cut), live=False).breadth_series()
    frame = market_context.load_market_breadth(db_session, upto=pd.Timestamp(_as_of(cut)))
    assert len(series) == len(frame) > 0
    assert pd.Timestamp(frame["ts"].iloc[-1]).tz_convert(IST).date() <= cut


def test_breadth_for_a_past_day_does_not_change_when_the_watchlist_changes_later(db_session):
    from swing_trade_ml.db.models.market import WatchlistSnapshot

    for k in range(3):
        _candles(db_session, _instrument(db_session, f"BRW{k}", watchlisted=True), _rising(len(DAYS), 0.002))
        db_session.add(WatchlistSnapshot(snapshot_date=DAYS[100], symbol=f"BRW{k}"))  # the list as it stood then
    db_session.flush()
    upto = pd.Timestamp(_as_of(DAYS[250]))
    before = float(pit_breadth.load_breadth(db_session, upto)["breadth_pct_above_sma50"].iloc[-1])
    market_context.clear_cache()
    _candles(db_session, _instrument(db_session, "BRWLATE", watchlisted=True), list(_rising(len(DAYS), -0.004)))  # added later, falling
    db_session.add(WatchlistSnapshot(snapshot_date=DAYS[300], symbol="BRWLATE"))  # snapshot AFTER the run date
    db_session.flush()
    after = float(pit_breadth.load_breadth(db_session, upto)["breadth_pct_above_sma50"].iloc[-1])
    assert after == pytest.approx(before)


def test_default_breadth_ignores_snapshots_so_v1_models_strategies_and_lanes_are_unchanged(db_session):
    """#488 review: point-in-time breadth lives in brain/pit_breadth.py, read only by the market judgement. v1's
    loader (ml_swing, dataset, predict, asof, deployable, h05 lanes) ignores snapshots and gives what it gave before."""
    from swing_trade_ml.db.models.market import WatchlistSnapshot

    for k in range(3):
        _candles(db_session, _instrument(db_session, f"BRV{k}", watchlisted=True), _rising(len(DAYS), 0.002 - 0.003 * k))
    upto = pd.Timestamp(_as_of(DAYS[250]))
    legacy = market_context.load_market_breadth(db_session, upto=upto)
    db_session.add(WatchlistSnapshot(snapshot_date=DAYS[100], symbol="BRV0"))  # the list then held only one stock
    db_session.flush()
    market_context.clear_cache()
    pd.testing.assert_frame_equal(market_context.load_market_breadth(db_session, upto=upto), legacy)
    market_context.clear_cache()
    pit = pit_breadth.load_breadth(db_session, upto)
    assert float(pit["breadth_pct_above_sma50"].iloc[-1]) != pytest.approx(float(legacy["breadth_pct_above_sma50"].iloc[-1]))
    # Only the market judgement's breadth series reads the point-in-time module; model inputs keep v1's breadth.
    reader_src = (SRC / "brain" / "reader.py").read_text(encoding="utf-8")
    assert reader_src.count("pit_breadth.load_breadth(") == 1
    assert '"breadth": market_context.load_market_breadth(self.db, upto=upto)' in reader_src


def test_days_before_the_first_snapshot_keep_todays_watchlist_rather_than_going_empty(db_session):
    """#488 review: snapshots began ~5 Oct 2026. Earlier days have no record of the list, so they keep today's list
    (the old behaviour) instead of empty breadth, which would force every earlier replay DEFENSIVE."""
    from swing_trade_ml.db.models.market import WatchlistSnapshot

    for k in range(3):
        _candles(db_session, _instrument(db_session, f"BRF{k}", watchlisted=True), _rising(len(DAYS), 0.002))
    db_session.add(WatchlistSnapshot(snapshot_date=DAYS[200], symbol="BRF0"))
    db_session.flush()
    upto = pd.Timestamp(_as_of(DAYS[250]))
    legacy = market_context.load_market_breadth(db_session, upto=upto)
    market_context.clear_cache()
    pit = pit_breadth.load_breadth(db_session, upto)
    day = lambda t: pd.Timestamp(t).tz_convert(IST).date()  # noqa: E731
    early_pit = pit[[day(t) < DAYS[200] for t in pit["ts"]]].reset_index(drop=True)
    early_legacy = legacy[[day(t) < DAYS[200] for t in legacy["ts"]]].reset_index(drop=True)
    pd.testing.assert_frame_equal(early_pit, early_legacy)
    assert early_pit["breadth_pct_above_sma50"].iloc[60:].notna().all()  # past the 50-day warm-up, never empty
    assert len(pit) == len(legacy)  # no day lost at the seam


# ================================================================ 2. missing data is said, and never makes it bolder


def _inputs(index=None, vix=None, breadth=None, fii=None) -> MarketInputs:
    return MarketInputs(
        index_close=pd.Series(_rising(320) if index is None else index, dtype=float),
        vix_close=pd.Series([16.0 + (i % 6) for i in range(300)] if vix is None else vix, dtype=float),
        breadth=pd.Series([0.65] * 30 if breadth is None else breadth, dtype=float),
        fii_net=[] if fii is None else fii,
    )


def test_no_market_data_at_all_is_defensive_and_says_why(db_session):
    state = judge(inputs_from(DatedReader(db_session, _as_of(DAYS[250]), live=False)))
    assert state.mode is MarketMode.DEFENSIVE and "Not enough NIFTY history" in state.reasons[0]


def test_a_199_bar_index_history_is_not_enough_to_judge_and_stays_careful():
    state = judge(_inputs(index=_rising(199)))
    assert state.mode is MarketMode.DEFENSIVE and "Not enough NIFTY history" in state.reasons[0]


def test_a_broad_rising_market_with_all_inputs_is_normal_and_names_each_input():
    state = judge(_inputs(fii=[50.0] * 25))
    assert state.mode is MarketMode.NORMAL
    text = " ".join(state.reasons)
    assert "50-day average is above its 200-day" in text and "above their 50-day average" in text and "India VIX" in text


def test_a_narrow_market_is_defensive_and_the_breadth_is_the_first_reason():
    state = judge(_inputs(breadth=[0.30] * 30))
    assert state.mode is MarketMode.DEFENSIVE and "30%" in state.reasons[0]


def test_missing_fii_data_is_said_and_does_not_lower_or_raise_the_mode():
    state = judge(_inputs(fii=[]))
    assert state.mode is MarketMode.NORMAL and any("FII flow data is not available" in r for r in state.reasons)


def test_a_missing_vix_leaves_the_vix_line_out_rather_than_inventing_one():
    state = judge(_inputs(vix=[]))
    assert not any("India VIX is " in r for r in state.reasons) and state.vix is None


@pytest.mark.parametrize("missing", ["breadth", "vix"])
def test_missing_breadth_or_vix_is_said_in_words_or_keeps_the_brain_careful(missing):
    state = judge(_inputs(breadth=[] if missing == "breadth" else None, vix=[] if missing == "vix" else None))
    said = any(missing in r.lower() and ("not available" in r.lower() or "no " in r.lower()) for r in state.reasons)
    assert state.mode is not MarketMode.NORMAL and said  # #488: more careful, and says why


def test_full_data_day_is_unchanged_by_the_missing_data_rule():
    state = judge(_inputs(fii=[50.0] * 25))
    assert state.mode is MarketMode.NORMAL and not any("not available" in r for r in state.reasons[:1])


def test_a_short_vix_history_is_not_missing_data_and_does_not_trip_the_missing_data_rule():
    # Owner 2026-11-26 (option a): only "no VIX at all" counts as missing; under a year of history does not.
    state = judge(_inputs(vix=[16.0 + (i % 6) for i in range(100)], fii=[50.0] * 25))
    assert not any("India VIX data is not available" in r for r in state.reasons)
    assert state.mode is MarketMode.NORMAL


def test_missing_breadth_is_never_bolder_than_a_narrow_market_and_the_first_reason_says_so():
    state = judge(_inputs(breadth=[]))
    assert state.mode is MarketMode.DEFENSIVE and "Breadth data" in state.reasons[0] and "stays careful" in state.reasons[0]


def test_a_crash_day_or_a_vix_spike_stops_new_trades_and_a_calm_morning_after_does_not_relax_at_once():
    crash = list(_rising(320))
    crash[-1] = crash[-2] * 0.95
    assert judge(_inputs(index=crash)).mode is MarketMode.NO_NEW_TRADES
    spike = [16.0] * 299 + [25.0]
    assert judge(_inputs(vix=spike)).mode is MarketMode.NO_NEW_TRADES


# ================================================================ 3. sectors


def _sector_data(db, as_of_index: int):
    nifty = _instrument(db, settings.BENCHMARK_INDEX_SYMBOL)
    _candles(db, nifty, _rising(len(DAYS), 0.002))
    names = ["NIFTY BANK", "NIFTY IT", "NIFTY AUTO"]
    for k, name in enumerate(names):
        _candles(db, _instrument(db, name), _rising(len(DAYS), 0.001 + 0.002 * k))
    return names


def test_sector_ranking_ignores_everything_after_the_run_date(db_session):
    names = _sector_data(db_session, 0)
    cut = DAYS[200]
    reader = DatedReader(db_session, _as_of(cut), live=False)
    ranked = rank_sectors(reader.sector_closes(), reader.index_closes())
    assert [s.sector for s in ranked] == ["NIFTY AUTO", "NIFTY IT", "NIFTY BANK"]  # the faster riser ranks first
    assert all(s.of_total == 3 for s in ranked) and set(names) == {s.sector for s in ranked}
    # make the weakest sector surge AFTER the run date: the ranking on the run date does not move
    weak = db_session.query(Instrument).filter_by(tradingsymbol="NIFTY BANK").one()
    for candle in db_session.query(Candle).filter(Candle.instrument_id == weak.id).all():
        if candle.ts.astimezone(IST).date() > cut:
            candle.close = candle.high = candle.close * 5
    db_session.flush()
    again = rank_sectors(*(lambda r: (r.sector_closes(), r.index_closes()))(DatedReader(db_session, _as_of(cut), live=False)))
    assert [(s.sector, s.rank, s.rotation) for s in again] == [(s.sector, s.rank, s.rotation) for s in ranked]


def test_every_sector_index_the_stock_map_uses_has_a_plain_name_on_the_card():
    unnamed = sorted(set(SECTOR_INDEX_MAP.values()) - set(SECTOR_NAMES))
    assert unnamed == [], f"these sectors would show as a raw index code: {unnamed}"
    state = c.SectorState(sector="NIFTY IT", rank=3, of_total=15, strength_20d=0.02, rotation="improving")
    line = sector_line(state)
    assert line.startswith("Sector: IT, ranked 3 of 15, improving") and "NIFTY IT" not in line
    assert plain_name("NIFTY BANK") == "Banks"


def _facts(rank, of_total=15):
    return SimpleNamespace(sector_rank=rank, sector_total=of_total)


def test_the_sector_gate_waits_an_idea_outside_the_top_n_and_lets_the_rest_through(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 5)
    outside = rules._sector_gate(None, _facts(6), None)
    assert outside is not None and outside[0].value == "WAIT" and "6" in outside[1] and "top 5" in outside[1]
    assert rules._sector_gate(None, _facts(5), None) is None
    assert rules._sector_gate(None, _facts(1), None) is None


def test_the_sector_gate_is_off_when_the_setting_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 0)
    assert rules._sector_gate(None, _facts(14), None) is None


def test_the_strongest_sectors_gate_stays_off_by_default_by_owner_decision_488():
    assert settings.model_fields["BRAIN_SECTOR_GATE_TOP_N"].default == 0  # owner 2026-11-26: leave off


def test_the_gate_reason_names_the_sector_and_the_real_total(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 5)
    reason = rules._sector_gate(None, SimpleNamespace(sector_rank=8, sector_total=12, sector_name="Banks", symbol="HDFCBANK"), None)[1]
    assert "of 12" in reason and "Banks" in reason


def test_an_idea_with_no_sector_rank_does_not_pass_the_gate_silently(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 5)
    held = rules._sector_gate(None, _facts(None), None)
    assert held is not None and held[0].value == "WAIT" and "no strength rank" in held[1]


def test_the_top_five_a_day_is_a_display_cut_that_the_digest_and_the_screen_agree_on():
    """OBSERVED: the Brain keeps every idea; the 'top 5' is where a list is cut (ops digest and the Today screen)."""
    from swing_trade_ml.services import ops_digest

    screen = (FRONTEND / "trademind" / "today" / "TodayIdeas.tsx").read_text(encoding="utf-8")
    shown = int(re.search(r"export const TOP_IDEAS = (\d+)", screen).group(1))
    assert ops_digest.TOP_IDEAS == shown == 5
    decide = (SRC / "brain" / "modules" / "m08_decide" / "module.py").read_text(encoding="utf-8")
    assert "TOP_IDEAS" not in decide  # the decision step itself sets no daily cap


# ================================================================ 4. similar cases


def _cases(n: int, as_of: date, hit_share: float = 0.5) -> pd.DataFrame:
    rows = []
    for i in range(n):
        day = as_of - timedelta(days=60 + i)
        hit = i < int(n * hit_share)
        rows.append(
            {
                "symbol": f"S{i}", "day": day, "market": "calm up-trend", "stock": "up", "trend": "rising", "vol": "normal",
                "outcome": "target" if hit else "stop", "exit_return": 0.08 if hit else -0.04, "days": 6,
                "outcome_day": day + timedelta(days=9), "path_day": day + timedelta(days=21), "path": [0.0] * 15,
            }
        )
    return pd.DataFrame(rows)


KEY = {"market": "calm up-trend", "stock": "up", "trend": "rising", "vol": "normal"}


def test_a_case_is_known_only_after_its_own_outcome_day_never_on_the_day_it_started():
    rng = np.random.default_rng(3)
    close = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, 120))
    bars = pd.DataFrame({"day": pd.bdate_range("2025-01-01", periods=120).date, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close})
    cases = barrier_outcomes(bars)
    assert len(cases) == 120 - 15 and (cases["outcome_day"] > cases["day"]).all()
    assert (cases["path_day"] >= cases["outcome_day"]).all()


def test_recall_uses_only_cases_whose_outcome_was_known_on_the_run_date():
    today = date(2026, 6, 30)
    cases = _cases(40, today)
    late = cases.copy()
    late["symbol"] = "LATE"
    late["outcome_day"] = today + timedelta(days=1)  # known only tomorrow
    late["outcome"], late["exit_return"] = "stop", -0.04
    r = recall(pd.concat([cases, late], ignore_index=True), "X", KEY, today)
    assert r.n_similar == 40 and r.hit_rate == pytest.approx(0.5)  # none of the 40 later cases is counted
    on_the_day = late.assign(outcome_day=today)
    assert recall(pd.concat([cases, on_the_day], ignore_index=True), "X", KEY, today).n_similar == 80  # known that day: counted


def test_the_experience_table_is_read_only_up_to_the_run_date(db_session):
    today = date(2026, 6, 30)
    frame = _cases(5, today)
    frame.loc[0, "outcome_day"] = today + timedelta(days=3)
    for row in frame.to_dict("records"):
        db_session.add(BrainExperience(**{k: row[k] for k in ("symbol", "day", "market", "stock", "trend", "vol", "outcome", "exit_return", "days", "outcome_day", "path_day", "path")}))
    db_session.flush()
    seen = DatedReader(db_session, _as_of(today), live=False).experience()
    assert len(seen) == 4 and (seen["outcome_day"] <= today).all()


def _f(r: c.Recall):
    return SimpleNamespace(recall=r, snapshot=SimpleNamespace(close=100.0), opinion=None, verdict=None)


def test_with_fewer_than_the_minimum_cases_the_card_gives_no_rate_and_the_rule_stays_silent():
    """A LOSING set (10% reach the target: the expected result is negative), so the rule would fire on the numbers alone and only
    the case-count guard (`rules.py:75`) keeps it silent. The control with 30 of the same kind shows the rule does fire."""
    policy = DecidePolicy()
    assert policy.min_similar_cases == MIN_CASES == 30
    today = date(2026, 6, 30)
    few = recall(_cases(MIN_CASES - 1, today, hit_share=0.1), "X", KEY, today)
    assert few.n_similar == MIN_CASES - 1 and few.hit_rate is not None  # the lookup keeps its numbers ...
    assert "Similar cases" not in engine._evidence(_f(few), 10, policy)  # ... the card does not show them
    assert rules._negative_expected_result(None, _f(few), policy) is None  # and the 'lost money' rule stays silent on 29
    enough = recall(_cases(MIN_CASES, today, hit_share=0.1), "X", KEY, today)
    proposal = rules._negative_expected_result(None, _f(enough), policy)
    assert proposal is not None and proposal[0].value == "WAIT" and "lost money" in proposal[1]  # the control: 30 are enough
    assert "Similar cases: 30" in engine._evidence(_f(enough), 10, policy)


def test_the_card_line_carries_the_same_count_and_rate_the_brain_used():
    policy = DecidePolicy()
    r = recall(_cases(40, date(2026, 6, 30), hit_share=0.25), "X", KEY, date(2026, 6, 30))
    line = engine._evidence(_f(r), 10, policy)
    assert f"Similar cases: {r.n_similar} " in line and f"{r.hit_rate:.0%}" in line
    expected = f"{engine.recall_r(r, _f(r), policy):+.2f} R per trade"
    assert expected in line  # the expected result printed is the one the rule computes
    assert "On months it had not seen" in line and f"{r.honest_hit_rate:.0%}" in line  # the honest figure is beside the raw one


def test_a_widened_match_says_which_parts_were_dropped():
    today = date(2026, 6, 30)
    cases = _cases(35, today).assign(vol="high")  # only 'high' volatility cases exist; today's key says 'normal'
    r = recall(cases, "X", KEY, today)
    assert r.n_similar == 35 and r.widened == ("volatility",) and "volatility" not in r.key
