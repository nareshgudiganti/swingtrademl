"""No look-ahead: the brain's answer for a past day must not depend on the future.

Every historical test of the brain (replays, backtests) is only worth something
if a run "as of" day X cannot see anything that happened after X. This proves it
the direct way:

  1. replay day X on a market that ends on X                       -> answer A
  2. add wild price bars for the days AFTER X and replay X again   -> answer B
  3. A must equal B, down to the recorded quality, context, levels and reasons.

A control proves the test can see: changing a bar BEFORE X must change the
answer. Without the control, "A == B" could just mean the comparison sees nothing.

No production data: every stock and bar is built here, in the test database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlalchemy import select

from swing_trade_ml.brain import service
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.replay_week import run_replay_week
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 25)  # a Friday, not a holiday

# name, token, start price, daily drift
STOCKS = [
    ("LOOKUP", 994001, 100.0, 0.004),
    ("LOOKFLAT", 994002, 200.0, 0.0),
    ("LOOKDOWN", 994003, 300.0, -0.004),
]
BENCH = (settings.BENCHMARK_INDEX_SYMBOL, 994099, 20000.0, 0.001)
SYMBOLS = [s[0] for s in STOCKS]


def _stamp(day: date) -> datetime:
    """Daily candles are stamped IST midnight (stored as 18:30 UTC the day before)."""
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)


def _add_bar(db, inst: Instrument, day: date, price: float, volume: int = 100_000) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=_stamp(day),
            open=price,
            high=price * 1.005,
            low=price * 0.995,
            close=price,
            volume=volume,
        )
    )


def _build_market(db) -> dict[str, Instrument]:
    """Sixty calendar days of bars per stock, ending on DAY (nothing after it)."""
    out: dict[str, Instrument] = {}
    for symbol, token, start, drift in [*STOCKS, BENCH]:
        inst = Instrument(
            instrument_token=token,
            tradingsymbol=symbol,
            exchange="NSE",
            is_watchlisted=symbol != BENCH[0],
            is_active=True,
        )
        db.add(inst)
        db.flush()
        out[symbol] = inst
        price = start
        for i in range(60, -1, -1):
            day = DAY - timedelta(days=i)
            if day.weekday() >= 5:
                continue
            price *= 1 + drift
            _add_bar(db, inst, day, price)
    db.commit()
    return out


def _add_wild_future(db, insts: dict[str, Instrument]) -> int:
    """Three weeks of absurd bars after DAY: the winner crashes, the loser soars,
    the index halves, volume explodes. If any of it leaks into DAY, A != B."""
    moves = {SYMBOLS[0]: 0.30, SYMBOLS[1]: 2.0, SYMBOLS[2]: 4.0, BENCH[0]: 0.50}
    start = {s[0]: s[2] for s in [*STOCKS, BENCH]}
    n = 0
    for offset in range(1, 22):
        day = DAY + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for symbol, inst in insts.items():
            _add_bar(db, inst, day, start[symbol] * moves[symbol], volume=50_000_000)
            n += 1
    db.commit()
    return n


def _replay_day(db) -> str:
    (row,) = run_replay_week(db, start=DAY, end=DAY, symbols=SYMBOLS)
    return row.run_id


def _observed(db, run_id: str) -> dict:
    """Everything the run recorded about DAY, with nothing that legitimately differs
    between two runs (ids, timestamps, durations)."""
    run = db.get(BrainRun, run_id)
    decisions = sorted(
        (
            d.symbol,
            d.kind,
            d.word,
            d.confidence,
            d.entry_low,
            d.entry_high,
            d.target,
            d.stop,
            d.qty,
            tuple(d.reasons or ()),
            d.evidence_text,
            d.downgraded_from,
            d.downgrade_reason,
        )
        for d in service.decisions_for(db, run_id)
    )
    return {
        "banner": (run.banner_mode, run.banner_headline),
        "quality": repr(sorted((run.quality or {}).items())),
        "context": repr(sorted((run.context or {}).items())),
        "decisions": decisions,
    }


@pytest.fixture()
def market(db_session):
    return _build_market(db_session)


def test_the_comparison_can_see_a_change_in_the_past(db_session, market):
    """Control: move yesterday's bar and the recorded answer must change. If it did
    not, the no-look-ahead check below would pass for the wrong reason."""
    before = _observed(db_session, _replay_day(db_session))
    yesterday = DAY - timedelta(days=1)
    bar = db_session.execute(
        select(Candle).where(Candle.instrument_id == market[SYMBOLS[0]].id, Candle.ts == _stamp(yesterday))
    ).scalar_one()
    bar.close *= 0.5
    bar.low = bar.close * 0.995
    bar.high = bar.close * 1.005
    db_session.commit()
    after = _observed(db_session, _replay_day(db_session))
    assert before != after, "changing a past bar changed nothing, so the comparison is blind"


def test_future_prices_do_not_change_a_past_days_answer(db_session, market):
    answer_a = _observed(db_session, _replay_day(db_session))
    assert answer_a["decisions"] and answer_a["quality"], "the replay recorded nothing to compare"

    added = _add_wild_future(db_session, market)
    assert added > 0

    answer_b = _observed(db_session, _replay_day(db_session))
    for part in answer_a:
        assert answer_a[part] == answer_b[part], (
            f"'{part}' for {DAY} changed after adding bars dated after {DAY}: the brain is "
            f"reading the future.\nbefore: {answer_a[part]}\nafter:  {answer_b[part]}"
        )


def _reader_view(db, symbol: str) -> dict:
    """What the reader hands every module for one stock, as of the end of DAY."""
    reader = DatedReader(db, datetime.combine(DAY, time(23, 59), tzinfo=IST).astimezone(UTC), live=False)
    return {
        "last_close": reader.last_close(symbol),
        "ohlcv": reader.ohlcv(symbol).to_json(),
        "recent_bars": reader.recent_bars(symbol).to_json(),
        "dated_bars": reader.dated_bars(symbol).to_json(),
        "dated_closes": reader.dated_closes(symbol).to_json(),
        "index_closes": reader.index_closes().to_json(),
    }


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_the_reader_never_hands_a_module_a_bar_after_the_day(db_session, market, symbol):
    """The simplest leak: 'latest close' or a price history picking up a later bar.
    Every candle reader must return the same thing before and after the future exists,
    and its last bar must be DAY's own."""
    before = _reader_view(db_session, symbol)
    last_day, last_close = before["last_close"]
    assert str(last_day) == DAY.isoformat(), f"the latest close is dated {last_day}, not {DAY}"

    _add_wild_future(db_session, market)
    after = _reader_view(db_session, symbol)
    for name in before:
        assert before[name] == after[name], f"{name} for {symbol} changed once bars after {DAY} existed"
    assert after["last_close"] == (last_day, last_close)

    # Control: a reader standing in the future DOES see those bars, so "unchanged"
    # above means the cutoff held, not that the bars never got stored.
    later = DatedReader(
        db_session,
        datetime.combine(DAY + timedelta(days=30), time(23, 59), tzinfo=IST).astimezone(UTC),
        live=False,
    )
    assert later.last_close(symbol) != after["last_close"], "the future bars are not visible to anyone"


# --- the as-of model score -----------------------------------------------------------------


class _FeatureEstimator:
    """A probability that really depends on the features, so a leak of future data into a
    feature changes the score. (A constant estimator would make this test blind.)"""

    def predict_proba(self, x):
        p = 1.0 / (1.0 + np.exp(-np.nanmean(x[:, :10], axis=1)))
        return np.column_stack([1 - p, p])


class _Identity:
    def transform(self, x):
        return x


def _long_series(db, symbol, token, start_price, seed, *, watch=True):
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
    )
    db.add(inst)
    db.flush()
    rng = np.random.default_rng(seed)
    price, day = start_price, DAY - timedelta(days=640)
    while day <= DAY:
        if day.weekday() < 5:
            price *= 1 + rng.normal(0.0005, 0.012)
            _add_bar(db, inst, day, price, volume=int(100_000 + rng.integers(0, 50_000)))
        day += timedelta(days=1)
    db.commit()
    return inst


def test_the_asof_score_for_a_day_does_not_change_when_future_bars_appear(db_session, monkeypatch):
    from swing_trade_ml.ml import asof, market_context
    from swing_trade_ml.ml.features import FEATURE_COLUMNS

    market_context.clear_cache()
    asof.clear_cache()
    inst = _long_series(db_session, "ASOFLOOK", 994201, 100.0, 11)
    others = {
        BENCH[0]: _long_series(db_session, BENCH[0], 994299, 20000.0, 12, watch=False),
        "INDIA VIX": _long_series(db_session, "INDIA VIX", 994298, 15.0, 13, watch=False),
        "ASOFLOOK": inst,
    }
    monkeypatch.setattr(
        asof,
        "_get_bundle",
        lambda m: {"feature_names": FEATURE_COLUMNS, "scaler": _Identity(), "estimator": _FeatureEstimator()},
    )
    model = SimpleNamespace(id=7001, name="m", version="1", metrics={"asof_cutoff": "2026-01-01"})

    before = asof.score_series(db_session, inst, model, after=date(2026, 1, 1))
    assert DAY in before, "no score for the day, so the check below would prove nothing"

    for offset in range(1, 22):  # wild bars after DAY
        d = DAY + timedelta(days=offset)
        if d.weekday() < 5:
            for symbol, other in others.items():
                _add_bar(db_session, other, d, 1.0 if symbol != "INDIA VIX" else 90.0, volume=50_000_000)
    db_session.commit()
    market_context.clear_cache()
    asof.clear_cache()

    after = asof.score_series(db_session, inst, model, after=date(2026, 1, 1))
    assert max(after) > DAY, "the future bars were not scored, so the check proves nothing"
    assert after[DAY] == pytest.approx(before[DAY]), "the score for DAY changed once later bars existed"
    market_context.clear_cache()
    asof.clear_cache()
