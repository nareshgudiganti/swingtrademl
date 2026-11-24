# ruff: noqa: E501 (long plain-English test text)
"""#239: the stock filters and pattern tags on the Discover and picks screens return what they say they return.

Verification only: nothing here changes behaviour. Findings: docs/verification/239-discover-filters.md.

The oracle is an independent Python filter over the rows each test creates (never the endpoint's own query).
Fixed rows use a private symbol prefix so nothing else in the test database can match. Every write rolls back.

Covered here: GET /instruments (search, watchlist, exchange, active), GET /signals (type, executed, age, limit),
GET /signals/top-picks (confidence floor, small-cap switch, budget, held stocks, count, practice evidence),
GET /signals/picks (age window, one row per stock, the signal's own horizon), and the setup tags read from stored
candles (point in time, IST midnight stamp, absent with too little data).

Cited, not re-tested: plan access (#335/#458, test_plans.py), lane filters (test_lane_picks_filters.py),
the Discover word/sector/search filters (frontend newLookW2.test.tsx), identity for a stock added from Discover
(#456/#476), the 15-day label on 5-day scores (#385, test_brain_evidence_verification.py).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pytest

from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy

API = "/api/v1"
KEY = {"X-API-Key": "test-api-key"}
_tokens = iter(range(985_000, 985_900))


def inst(db, symbol, *, name=None, exchange="NSE", active=True, watchlisted=False) -> Instrument:
    row = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        name=name or f"{symbol} Ltd",
        exchange=exchange,
        is_active=active,
        is_watchlisted=watchlisted,
    )
    db.add(row)
    db.flush()
    return row


def strat(db, name, model_name=None) -> Strategy:
    row = Strategy(
        name=name,
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        params={"model_name": model_name} if model_name else {},
    )
    db.add(row)
    db.flush()
    return row


def signal(db, strategy, row, *, kind="BUY", conf=0.8, price=100.0, stop=95.0, age_days=0.0, executed=False, features=None, horizon=None) -> Signal:
    sig = Signal(
        strategy_id=strategy.id,
        instrument_id=row.id,
        signal_type=kind,
        mode="paper",
        price=price,
        confidence=conf,
        stop_loss=stop,
        take_profit=price * 1.08,
        was_executed=executed,
        features=features or {},
        horizon_days=horizon,
        generated_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    db.add(sig)
    db.flush()
    return sig


def get(client, path, **params):
    response = client.get(f"{API}{path}", params=params, headers=KEY)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================ GET /instruments


@pytest.fixture()
def stocks(db_session):
    rows = {
        "ZQ239ALPHA": inst(db_session, "ZQ239ALPHA", name="Alpha Works"),
        "ZQ239ALPHAETF": inst(db_session, "ZQ239ALPHAETF", name="Alpha Gold Fund"),
        "BETAZQ239": inst(db_session, "BETAZQ239", name="Zq239 Beta Industries"),
        "ZQ239WATCH": inst(db_session, "ZQ239WATCH", name="Watched Co", watchlisted=True),
        "ZQ239GONE": inst(db_session, "ZQ239GONE", name="Gone Co", active=False),
        "ZQ239BSE": inst(db_session, "ZQ239BSE", name="Bombay Co", exchange="BSE"),
    }
    return rows


def _symbols(rows):
    return [r["tradingsymbol"] for r in rows]


def test_search_matches_symbol_or_name_substring_ignoring_case_and_hides_inactive_and_other_exchanges(client, stocks):
    got = _symbols(get(client, "/instruments", search="zq239"))
    oracle = {s for s, r in stocks.items() if r.is_active and r.exchange == "NSE" and "ZQ239" in (s + " " + r.name).upper()}
    assert set(got) == oracle == {"ZQ239ALPHA", "ZQ239ALPHAETF", "BETAZQ239", "ZQ239WATCH"}
    assert _symbols(get(client, "/instruments", search="zq239", exchange="BSE")) == ["ZQ239BSE"]


def test_search_ranks_the_exact_symbol_first_then_watchlisted_prefix_then_prefix_then_watchlisted(client, stocks):
    assert _symbols(get(client, "/instruments", search="zq239alpha"))[:2] == ["ZQ239ALPHA", "ZQ239ALPHAETF"]
    got = _symbols(get(client, "/instruments", search="ZQ239"))
    # a watchlisted prefix match first, then the other prefix matches (alphabetical), then the rest
    assert got == ["ZQ239WATCH", "ZQ239ALPHA", "ZQ239ALPHAETF", "BETAZQ239"]


def test_the_watchlist_filter_returns_exactly_the_watchlisted_active_stocks_and_the_limit_is_honoured(client, stocks, db_session):
    got = set(_symbols(get(client, "/instruments", watchlisted_only=True)))
    oracle = {r.tradingsymbol for r in db_session.query(Instrument).filter_by(is_watchlisted=True, is_active=True, exchange="NSE")}
    assert got == oracle and "ZQ239WATCH" in got and "ZQ239GONE" not in got
    assert len(get(client, "/instruments", search="ZQ239", limit=2)) == 2


def test_a_search_with_no_match_is_an_empty_list_not_an_error(client, stocks):
    assert get(client, "/instruments", search="NOSUCHSTOCK239") == []


# ============================================================================ GET /signals


@pytest.fixture()
def signal_book(db_session):
    s = strat(db_session, "s239_signals")
    rows = {k: inst(db_session, f"SG239{k}") for k in "ABCDE"}
    made = {
        "A": signal(db_session, s, rows["A"], kind="BUY", age_days=1, executed=True),
        "B": signal(db_session, s, rows["B"], kind="SELL", age_days=2),
        "C": signal(db_session, s, rows["C"], kind="BUY", age_days=10),
        "D": signal(db_session, s, rows["D"], kind="HOLD", age_days=29.5),
        "E": signal(db_session, s, rows["E"], kind="BUY", age_days=31),  # outside the default 30 days
    }
    return made


def _ours(rows):
    return {r["tradingsymbol"][-1] for r in rows if r["tradingsymbol"].startswith("SG239")}


def test_signals_filter_by_type_executed_flag_and_age_window_against_an_independent_filter(client, signal_book):
    window = {k for k, s in signal_book.items() if s.generated_at >= datetime.now(UTC) - timedelta(days=30)}
    assert _ours(get(client, "/signals")) == window == set("ABCD")
    assert _ours(get(client, "/signals", signal_type="buy")) == {k for k in window if signal_book[k].signal_type == "BUY"} == {"A", "C"}
    assert _ours(get(client, "/signals", executed_only=True)) == {"A"}
    assert _ours(get(client, "/signals", days=3)) == {"A", "B"}
    assert _ours(get(client, "/signals", days=365)) == set("ABCDE")


def test_signals_come_newest_first_and_the_limit_keeps_the_newest(client, signal_book):
    rows = [r for r in get(client, "/signals", days=365, limit=1000) if r["tradingsymbol"].startswith("SG239")]
    assert [r["tradingsymbol"][-1] for r in rows] == list("ABCDE")
    newest = get(client, "/signals", days=365, limit=1)
    assert [r["tradingsymbol"] for r in newest] == ["SG239A"]  # the newest of the five, not just any one row


def test_signals_with_nothing_in_the_window_are_an_empty_list(client, signal_book):
    assert [r for r in get(client, "/signals", signal_type="EXIT") if r["tradingsymbol"].startswith("SG239")] == []


# ============================================================================ GET /signals/top-picks


@pytest.fixture()
def shortlist(db_session):
    large = strat(db_session, "s239_large")
    small = strat(db_session, "s239_small", model_name="swing_classifier_smallcap")
    rows = {k: inst(db_session, f"TP239{k}") for k in "ABCDEFGH"}
    made = {
        "A": signal(db_session, large, rows["A"], conf=0.90),
        "B": signal(db_session, large, rows["B"], conf=0.70),  # exactly on the floor: kept (>=)
        "C": signal(db_session, large, rows["C"], conf=0.6999),  # just under
        "D": signal(db_session, small, rows["D"], conf=0.95),  # small-cap: off by default
        "E": signal(db_session, large, rows["E"], conf=0.85, price=30_000.0),  # dearer than the whole budget
        "F": signal(db_session, large, rows["F"], conf=0.85, kind="HOLD"),
        "G": signal(db_session, large, rows["G"], conf=0.85, features={"blocked_by_risk_limit": True}),
        "H": signal(db_session, large, rows["H"], conf=0.80),
    }
    return made


def _picks(rows):
    return {r["symbol"][-1] for r in rows if r["symbol"].startswith("TP239")}


def test_top_picks_keep_confidence_at_or_above_the_floor_and_drop_small_caps_dear_shares_and_non_buys(client, shortlist):
    got = get(client, "/signals/top-picks", budget=25_000, max_picks=20)
    oracle = {
        k
        for k, s in shortlist.items()
        if s.signal_type == "BUY" and s.confidence >= 0.70 and k != "D" and s.price <= 25_000
    }
    # G (practice evidence) is dropped by the code's own marker; check it is the one extra the oracle has to know about
    assert _picks(got) == oracle - {"G"} == {"A", "B", "H"}


def test_top_picks_small_caps_come_back_when_switched_on_and_the_floor_moves_with_the_parameter(client, shortlist):
    assert "D" in _picks(get(client, "/signals/top-picks", budget=25_000, max_picks=20, include_smallcap=True))
    assert _picks(get(client, "/signals/top-picks", budget=25_000, max_picks=20, min_confidence=0.75)) == {"A", "H"}
    assert _picks(get(client, "/signals/top-picks", budget=25_000, max_picks=20, min_confidence=0.6999)) >= {"B", "C"}


def test_top_picks_hide_stocks_already_held_and_honour_the_count(client, shortlist, db_session):
    held = db_session.query(Instrument).filter_by(tradingsymbol="TP239A").one()
    db_session.add(Position(strategy_id=shortlist["A"].strategy_id, instrument_id=held.id, mode="paper", status="OPEN", quantity=1, entry_price=100.0, entry_at=datetime.now(UTC)))
    db_session.flush()
    assert "A" not in _picks(get(client, "/signals/top-picks", budget=25_000, max_picks=20))
    one = get(client, "/signals/top-picks", budget=25_000, max_picks=1)
    assert [r["symbol"] for r in one] == ["TP239H"]  # the best score among the rest (A is held): the count keeps the best


def test_top_picks_say_nothing_when_nothing_qualifies(client, shortlist):
    assert get(client, "/signals/top-picks", budget=25_000, min_confidence=0.99) == []


def test_every_top_pick_carries_a_size_that_buys_at_least_one_share_and_its_cap_tier(client, shortlist):
    rows = [r for r in get(client, "/signals/top-picks", budget=25_000, max_picks=20, include_smallcap=True) if r["symbol"].startswith("TP239")]
    assert rows and all(r["suggested_quantity"] >= 1 and r["cap_tier"] in {"large", "midcap", "smallcap"} for r in rows)
    assert {r["symbol"][-1]: r["cap_tier"] for r in rows}["D"] == "smallcap"


def test_top_picks_do_not_list_a_buy_signal_that_is_weeks_old(client, db_session):
    row = inst(db_session, "TP239OLD")
    signal(db_session, strat(db_session, "s239_old"), row, conf=0.9, age_days=40)
    assert "TP239OLD" not in {r["symbol"] for r in get(client, "/signals/top-picks", budget=25_000)}


def test_buy_list_control_a_fresh_buy_is_listed_a_later_hold_from_the_same_strategy_drops_it_and_a_held_stock_is_excluded(client, db_session):
    s = strat(db_session, "s239_bl")
    keep, dropped, held = inst(db_session, "BL239KEEP"), inst(db_session, "BL239DROP"), inst(db_session, "BL239HELD")
    signal(db_session, s, keep, conf=0.8, age_days=1)
    signal(db_session, s, dropped, conf=0.8, age_days=3)
    signal(db_session, s, dropped, kind="HOLD", conf=0.5, age_days=1)  # a later scan no longer says BUY
    signal(db_session, s, held, conf=0.9)
    db_session.add(Position(strategy_id=s.id, instrument_id=held.id, mode="paper", status="OPEN", quantity=1, entry_price=100.0, entry_at=datetime.now(UTC)))
    db_session.flush()
    assert {r["symbol"] for r in get(client, "/signals/buy-list") if r["symbol"].startswith("BL239")} == {"BL239KEEP"}


def test_buy_list_drops_a_stock_whose_newest_signal_from_any_strategy_is_not_a_buy(client, db_session):
    old_buyer, newer_holder = strat(db_session, "s239_bl_a"), strat(db_session, "s239_bl_b")
    row = inst(db_session, "BL239MIX")
    signal(db_session, old_buyer, row, conf=0.9, age_days=3)
    signal(db_session, newer_holder, row, kind="HOLD", conf=0.5, age_days=1)
    assert "BL239MIX" not in {r["symbol"] for r in get(client, "/signals/buy-list")}


def test_buy_list_does_not_list_a_buy_signal_that_is_weeks_old(client, db_session):
    row = inst(db_session, "BL239OLD")
    signal(db_session, strat(db_session, "s239_old2"), row, conf=0.9, age_days=40)
    assert "BL239OLD" not in {r["symbol"] for r in get(client, "/signals/buy-list")}


# ============================================================================ GET /signals/picks


def test_picks_use_a_five_day_window_one_row_per_stock_the_best_confidence_and_the_signals_own_horizon(client, db_session):
    a, b = strat(db_session, "s239_pa"), strat(db_session, "s239_pb")
    fresh, edge, old = inst(db_session, "PK239FRESH"), inst(db_session, "PK239EDGE"), inst(db_session, "PK239OLD")
    signal(db_session, a, fresh, conf=0.72, horizon=5)
    signal(db_session, b, fresh, conf=0.91, horizon=15)  # same stock, more confident, another model
    signal(db_session, a, edge, conf=0.8, age_days=4.9, horizon=5)
    signal(db_session, a, old, conf=0.99, age_days=5.2, horizon=5)
    rows = {r["symbol"]: r for r in get(client, "/signals/picks") if r["symbol"].startswith("PK239")}
    assert set(rows) == {"PK239FRESH", "PK239EDGE"}  # the 5.2-day-old one is outside the window
    assert rows["PK239FRESH"]["confidence"] == 0.91 and rows["PK239FRESH"]["strategy_name"] == "s239_pb"
    assert rows["PK239FRESH"]["horizon_days"] == 15 and rows["PK239EDGE"]["horizon_days"] == 5  # each pick says its own horizon


def test_picks_are_highest_confidence_first(client, db_session):
    s = strat(db_session, "s239_order")
    for sym, conf in (("PK239L", 0.61), ("PK239H", 0.93), ("PK239M", 0.77)):
        signal(db_session, s, inst(db_session, sym), conf=conf)
    got = [r["symbol"] for r in get(client, "/signals/picks") if r["symbol"].startswith("PK239")]
    assert got == ["PK239H", "PK239M", "PK239L"]


# ============================================================================ setup tags from stored candles


def _store_candles(db, symbol, closes, *, volumes=None, end_day: date = date(2026, 10, 9)):
    """Daily candles stamped IST midnight (18:30 UTC the day before), the way the data feed stores them."""
    row = inst(db, symbol)
    days = []
    d = end_day
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    volumes = volumes if volumes is not None else [100_000.0] * len(closes)
    for day, close, volume in zip(days, closes, volumes, strict=True):
        ts = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=5, minutes=30)
        db.add(Candle(instrument_id=row.id, interval="day", ts=ts, open=close, high=close * 1.01, low=close * 0.99, close=close, volume=volume))
    db.flush()
    return days


def _reader(db, day: date):
    from swing_trade_ml.brain.reader import DatedReader
    from swing_trade_ml.brain.replay_week import as_of_end_of_ist_day

    return DatedReader(db, as_of_end_of_ist_day(day), live=False)


def _breakout_series(n=90):
    close = list(100 * 1.002 ** np.arange(n - 1))
    close.append(close[-1] * 1.08)  # today well above the 20-day high
    volume = [100_000.0] * (n - 1) + [400_000.0]  # on 4x the usual volume
    return close, volume


def test_a_breakout_is_tagged_from_stored_candles_as_of_that_evening_and_the_line_names_what_it_saw(db_session):
    from swing_trade_ml.brain.modules.m12_stock.setups import find_setups

    close, volume = _breakout_series()
    days = _store_candles(db_session, "SU239BRK", close, volumes=volume)
    found = {s.label: s for s in find_setups(_reader(db_session, days[-1]).ohlcv("SU239BRK", 300))}
    assert "breakout" in found and found["breakout"].confirming is True
    assert "breakout above the 20-day high" in found["breakout"].line and "4.0x" in found["breakout"].line
    assert "breakdown" not in found  # a rise is never called a breakdown


def test_the_tag_for_an_earlier_evening_ignores_later_candles_and_does_not_show_the_later_breakout(db_session):
    from swing_trade_ml.brain.modules.m12_stock.setups import find_setups

    close, volume = _breakout_series()
    days = _store_candles(db_session, "SU239PIT", close, volumes=volume)
    day_before = days[-2]
    bars = _reader(db_session, day_before).ohlcv("SU239PIT", 300)
    assert len(bars) == len(close) - 1  # the breakout day's bar is not visible
    assert "breakout" not in [s.label for s in find_setups(bars)]
    assert bars["ts"].iloc[-1].tz_convert("Asia/Kolkata").date() == day_before  # dated by the India trading day


def test_the_evening_boundary_includes_that_days_bar_and_excludes_the_next_days_bar(db_session):
    days = _store_candles(db_session, "SU239EDGE", list(100 * 1.001 ** np.arange(70)))
    last = _reader(db_session, days[-1]).ohlcv("SU239EDGE", 300)
    assert last["ts"].iloc[-1].tz_convert("Asia/Kolkata").date() == days[-1]
    earlier = _reader(db_session, days[-5]).ohlcv("SU239EDGE", 300)
    assert earlier["ts"].iloc[-1].tz_convert("Asia/Kolkata").date() == days[-5] and len(earlier) == len(last) - 4


def test_too_little_history_or_no_candles_gives_no_tag_rather_than_a_guess(db_session):
    from swing_trade_ml.brain.modules.m12_stock.setups import MIN_BARS, find_setups

    days = _store_candles(db_session, "SU239SHORT", list(100 * 1.002 ** np.arange(MIN_BARS - 1)))
    assert find_setups(_reader(db_session, days[-1]).ohlcv("SU239SHORT", 300)) == []
    assert len(_reader(db_session, date(2026, 10, 9)).ohlcv("NOSUCH239", 300)) == 0
    assert find_setups(_reader(db_session, date(2026, 10, 9)).ohlcv("NOSUCH239", 300)) == []


def test_only_breakout_and_breakdown_need_volume_a_zero_volume_stock_can_still_be_tagged_a_base(db_session):
    from swing_trade_ml.brain.modules.m12_stock.setups import find_setups

    close = list(100 * 1.005 ** np.arange(60)) + [100 * 1.005**59] * 60  # a long rise, then 60 quiet days
    days = _store_candles(db_session, "SU239ZBASE", close, volumes=[0.0] * len(close))
    labels = [s.label for s in find_setups(_reader(db_session, days[-1]).ohlcv("SU239ZBASE", 300))]
    assert "base" in labels and "breakout" not in labels and "breakdown" not in labels  # explicit: base needs no volume


def test_a_tag_that_needs_volume_is_absent_for_a_stock_with_no_traded_volume(db_session):
    from swing_trade_ml.brain.modules.m12_stock.setups import find_setups

    close, _ = _breakout_series()
    days = _store_candles(db_session, "SU239ZERO", close, volumes=[0.0] * len(close))
    labels = [s.label for s in find_setups(_reader(db_session, days[-1]).ohlcv("SU239ZERO", 300))]
    assert "breakout" not in labels and "breakdown" not in labels


@pytest.mark.parametrize(
    ("which", "label", "confirming"),
    [("pullback", "pullback in up-trend", True), ("base", "base", True), ("breakdown", "breakdown", False)],
)
def test_the_other_tags_are_named_as_the_code_defines_them_and_only_a_breakdown_argues_against_buying(db_session, which, label, confirming):
    from swing_trade_ml.brain.modules.m12_stock.setups import find_setups

    n = 120
    close = list(100 * 1.005 ** np.arange(n))
    volume = [100_000.0] * n
    if which == "pullback":
        close = [*close[:-1], sum(close[-20:-1]) / 19]  # a dip back to the 20-day average inside a rising trend
    elif which == "base":
        close = close[:60] + [close[59]] * 60
    else:
        close = [*close[:-1], min(close[-21:-1]) * 0.9]
        volume[-1] = 500_000.0
    days = _store_candles(db_session, f"SU239{which.upper()}", close, volumes=volume)
    found = {s.label: s for s in find_setups(_reader(db_session, days[-1]).ohlcv(f"SU239{which.upper()}", 300))}
    assert label in found, sorted(found)
    assert found[label].confirming is confirming
    assert all(s.confirming for k, s in found.items() if k != "breakdown")
