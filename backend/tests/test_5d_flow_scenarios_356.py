# ruff: noqa: E501  (long plain-English test text)
"""#356: test scenarios for the v1 5-day flow found missing by audit #217 (TS1-TS8; TS9-TS11 are not 5D-flow tests).

Tests only. Nothing here changes ingestion, the scan, risk, orders, stored predictions or any frozen file.
Each scenario states the REQUIRED behaviour from the decided requirements (#353 stale bar, #354 fill timing, #355 stored
predictions, #357 session expiry). Where the code already does it, the test passes. Where it does not (the bugs are
gated), the test is a strict expected failure naming the gap issue: it fails today and turns red the day the gap is
fixed, so the marker must be removed on purpose. No scenario is skipped.

Kite is never called: the broker is stubbed, model artifacts are stubbed, candles are fixtures. Needs the test database;
every write rolls back.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select

from swing_trade_ml.brokers import paper as paper_module
from swing_trade_ml.brokers.base import OrderRequest
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core import market_session
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.ml import predict
from swing_trade_ml.services import ingestion

IST = ZoneInfo("Asia/Kolkata")
_TOKEN = iter(range(356_000_000, 356_100_000))

GAP = {"strict": True, "raises": AssertionError}


# ------------------------------------------------------------------------------------------------ fixtures / helpers


def _stock(db, symbol: str, *, watchlisted: bool = True) -> Instrument:
    inst = Instrument(
        instrument_token=next(_TOKEN),
        tradingsymbol=symbol,
        exchange="NSE",
        instrument_type="EQ",
        is_active=True,
        is_watchlisted=watchlisted,
    )
    db.add(inst)
    db.flush()
    return inst


def _days_ending(last: date, n: int) -> list[date]:
    out = [last]
    while len(out) < n:
        out.append(market_session.previous_trading_day(out[-1]))
    return sorted(out)


def _bar_ts(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC)  # a daily bar is stamped IST midnight


def _history(db, inst: Instrument, last_day: date, n: int = 300, close: float = 100.0) -> None:
    for i, d in enumerate(_days_ending(last_day, n)):
        price = close + (i % 7) * 0.1
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=_bar_ts(d),
                open=price,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=500_000,
            )
        )
    db.flush()


def _sessions(now: datetime | None = None) -> tuple[date, date]:
    """(the newest finished session, the one before it). The first is "today's bar" for a scan after the close."""
    now = now or datetime.now(UTC)
    current = market_session.last_closed_trading_day(now)
    return current, market_session.previous_trading_day(current)


def _model(db, probability_tag: str = "t356") -> MLModel:
    model = MLModel(
        name="swing_classifier",
        version=probability_tag,
        algorithm="stub",
        status="ACTIVE",
        artifact_path=f"/nonexistent/{probability_tag}.joblib",
        activated_at=datetime.now(UTC),
    )
    db.add(model)
    db.flush()
    return model


@pytest.fixture()
def stub_model_world(monkeypatch):
    """No artifact, no index data: a fixed score of 0.9 and one feature, so only the CANDLE DATE decides what is scored."""
    monkeypatch.setattr(
        predict,
        "_get_bundle",
        lambda m: {
            "feature_names": ["f1"],
            "scaler": SimpleNamespace(transform=lambda x: x),
            "estimator": SimpleNamespace(predict_proba=lambda x: np.array([[0.1, 0.9]])),
        },
    )
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(predict, loader, lambda *a, **k: pd.DataFrame())

    def fake_features(df, *a, **k):
        out = df.copy()
        out["f1"] = 0.5
        return out

    monkeypatch.setattr(predict, "build_features", fake_features)


@pytest.fixture(autouse=True)
def _no_live_kite(monkeypatch):
    """Kite is logged out for every scenario here (the safe default): nothing can reach the real broker."""
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: False))
    monkeypatch.setattr(ingestion.time, "sleep", lambda s: None)


# ===================================================== TS1  one stock has no candle for today's session (#353 / #246)


@pytest.mark.xfail(
    **GAP,
    reason="gap #353 (TS1): predict_instrument scores featured.iloc[[-1]] whatever its date, so a stock whose newest bar is the previous session is scored as if it were today's",
)
def test_ts1_prediction_skips_a_stock_with_no_candle_for_the_current_session(db_session, stub_model_world):
    current, previous = _sessions()
    fresh = _stock(db_session, "TS1FRESH")
    stale = _stock(db_session, "TS1STALE")
    _history(db_session, fresh, current)
    _history(db_session, stale, previous)  # today's bar never arrived for this one
    _model(db_session)

    results = predict.predict_watchlist(db_session, persist=True)

    assert {r.symbol for r in results} == {"TS1FRESH"}, "the stale stock was scored as if its old bar were today's"
    stored = {
        s
        for (s,) in db_session.execute(
            select(Instrument.tradingsymbol).join(Prediction, Prediction.instrument_id == Instrument.id)
        )
    }
    assert stored == {"TS1FRESH"}


def test_ts1_control_a_stock_with_the_current_bar_is_scored(db_session, stub_model_world):
    """Passes today: the fixture itself works, so the xfail above fails for the stated reason and not a broken fixture."""
    current, _ = _sessions()
    fresh = _stock(db_session, "TS1CTRL")
    _history(db_session, fresh, current)
    _model(db_session)
    results = predict.predict_watchlist(db_session, persist=True)
    assert [r.symbol for r in results] == ["TS1CTRL"] and results[0].probability == pytest.approx(0.9)
    assert results[0].ts == _bar_ts(current)


@pytest.mark.xfail(
    **GAP,
    reason="gap #353 (TS1, scan side): MLSwingStrategy.evaluate decides on the newest stored bar whatever its date; a BUY on a previous-session bar is possible",
)
def test_ts1_the_scan_gives_no_signal_for_a_previous_session_bar(db_session, monkeypatch):
    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.db.models.trading import Strategy
    from swing_trade_ml.ml.dataset import load_candles
    from swing_trade_ml.strategies import ml_swing

    _, previous = _sessions()
    stale = _stock(db_session, "TS1SCAN")
    _history(db_session, stale, previous)
    _model(db_session)
    monkeypatch.setattr(
        ml_swing,
        "_get_bundle",
        lambda m: {
            "feature_names": ["f1"],
            "scaler": SimpleNamespace(transform=lambda x: x),
            "estimator": SimpleNamespace(predict_proba=lambda x: np.array([[0.05, 0.95]])),
        },
    )
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: pd.DataFrame())

    def fake_features(d, *a, **k):
        f = d.copy()
        f["nifty_trend_regime"] = 1.0
        f["f1"] = 0.5
        return f

    monkeypatch.setattr(ml_swing, "build_features", fake_features)

    strategy = ml_swing.MLSwingStrategy(
        Strategy(name="ts1", strategy_type="ml_swing", mode="paper", params={})
    )
    decision = strategy.evaluate(load_candles(db_session, stale.id, "day", limit=310), stale, db_session)
    assert decision is None or decision.signal != SignalType.BUY, (
        "a BUY was produced from the previous session's bar while today's bar is missing"
    )


# ============================================================ TS2  job_daily_ingest overruns past 15:42 / 15:45 (#353)


@pytest.mark.xfail(
    **GAP,
    reason="gap #353 (TS2): predict_watchlist/job_signal_scan have no link to the ingest result; a slow ingest leaves old bars that are scored anyway",
)
def test_ts2_an_ingest_that_overruns_leaves_no_previous_session_score(db_session, stub_model_world, monkeypatch):
    from swing_trade_ml.workers import jobs

    current, previous = _sessions()
    done = _stock(db_session, "TS2DONE")
    slow = _stock(db_session, "TS2SLOW")
    _history(db_session, done, previous)
    _history(db_session, slow, previous)
    _model(db_session)

    def overrunning_backfill(db, interval="day", days=None, incremental=True):
        # the slot ends with only the first symbol topped up; the second is still downloading
        _history_one = Candle(
            instrument_id=done.id,
            interval="day",
            ts=_bar_ts(current),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=500_000,
        )
        db.add(_history_one)
        db.flush()
        return {"TS2DONE": 1, "TS2SLOW": 0}

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)
    monkeypatch.setattr(ingestion, "backfill_watchlist", overrunning_backfill)
    monkeypatch.setattr(ingestion, "backfill_index", lambda db, interval="day", days=None: 0)
    monkeypatch.setattr(ingestion, "backfill_context_indices", lambda db, interval="day", days=None: {})
    import swing_trade_ml.services.watchlist_snapshots as snapshots

    monkeypatch.setattr(snapshots, "record_watchlist_snapshot", lambda db: None)
    monkeypatch.setattr(db_session, "commit", db_session.flush)  # the job commits; the test transaction must survive

    jobs.job_daily_ingest()
    results = predict.predict_watchlist(db_session, persist=True)  # 15:42 slot fires regardless

    assert "TS2SLOW" not in {r.symbol for r in results}, "the overrunning stock was scored from the previous session's bar"


# ====================================================================== TS3  v1 paper BUY decided at 15:45 IST (#354)

# Tuesday 1 Dec 2026, 15:45 IST: the market closed 15 minutes ago.
AFTER_CLOSE = datetime(2026, 12, 1, 15, 45, tzinfo=IST).astimezone(UTC)


def _buy(symbol: str) -> OrderRequest:
    return OrderRequest(
        tradingsymbol=symbol,
        exchange="NSE",
        transaction_type=TransactionType.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag="t356",
        own_funds=True,
    )


def _put_quote(db, inst, price: float, ts: datetime) -> None:
    db.add(Quote(instrument_id=inst.id, last_price=price, ts=ts))
    db.flush()


@pytest.mark.xfail(
    **GAP,
    reason="gap #354 (TS3): PaperBroker fills a BUY decided after the close at once, at the same close that produced the signal (brokers/paper.py:159-226); required is the next session's open, or an explicit close-fill label",
)
def test_ts3_a_buy_decided_after_the_close_does_not_fill_at_that_close(db_session, monkeypatch):
    monkeypatch.setattr(paper_module, "_utcnow", lambda: AFTER_CLOSE)
    inst = _stock(db_session, "TS3AFTER", watchlisted=False)
    _history(db_session, inst, date(2026, 12, 1), n=5, close=100.0)
    _put_quote(db_session, inst, 100.0, AFTER_CLOSE - timedelta(minutes=5))  # the closing print, 15:40

    result = PaperBroker().place_order(_buy("TS3AFTER"), db_session)

    labelled_close_fill = "close" in (result.message or "").lower()
    assert result.status != OrderStatus.COMPLETE or labelled_close_fill, (
        f"filled at {result.average_price} straight after the close with no 'next open' wait and no close-fill label"
    )


def test_ts3_next_open_is_the_next_trading_day_and_skips_a_holiday_or_weekend():
    """The date the fix must fill on. Passes today: the calendar helper already knows it."""
    friday = date(2026, 11, 27)
    assert market_session.next_trading_day(friday) == date(2026, 11, 30)  # Monday
    assert market_session.is_open(datetime(2026, 11, 28, 6, 0, tzinfo=UTC)) is False  # Saturday never opens


# ================================================== TS4  Kite logged out; cached quote is from an earlier session (#354)


def test_ts4_a_quote_from_an_earlier_session_is_never_a_paper_fill_price(db_session, monkeypatch):
    """Passes today (#471): with Kite out, a quote that is days old and has no newer close behind it is refused."""
    monkeypatch.setattr(paper_module, "_utcnow", lambda: AFTER_CLOSE)
    inst = _stock(db_session, "TS4OLDQ", watchlisted=False)
    _put_quote(db_session, inst, 500.0, AFTER_CLOSE - timedelta(days=4))

    result = PaperBroker().place_order(_buy("TS4OLDQ"), db_session)

    assert result.status == OrderStatus.REJECTED and result.filled_quantity == 0 and result.average_price is None
    assert "no paper fill was made" in result.message


def test_ts4_previous_session_quote_with_the_market_open_is_refused(db_session, monkeypatch):
    """Passes today: Wednesday 11:00 IST, the cached quote is from yesterday's close, the market is open: no fill."""
    open_wed = datetime(2026, 12, 2, 11, 0, tzinfo=IST).astimezone(UTC)
    monkeypatch.setattr(paper_module, "_utcnow", lambda: open_wed)
    inst = _stock(db_session, "TS4OPEN", watchlisted=False)
    _history(db_session, inst, date(2026, 12, 1), n=5, close=100.0)
    _put_quote(db_session, inst, 100.0, datetime(2026, 12, 1, 15, 30, tzinfo=IST).astimezone(UTC))

    result = PaperBroker().place_order(_buy("TS4OPEN"), db_session)

    assert result.status == OrderStatus.REJECTED and result.average_price is None


# ============================================ TS5  re-score an already-stored prediction with a different value (#355)


def _result(inst: Instrument, ts: datetime, probability: float, price: float) -> predict.PredictionResult:
    return predict.PredictionResult(
        instrument_id=inst.id,
        symbol=inst.tradingsymbol,
        probability=probability,
        predicted_class=int(probability >= 0.5),
        price=price,
        ts=ts,
        features={"f1": probability},
    )


@pytest.mark.xfail(
    **GAP,
    reason="gap #355 (TS5): _upsert_prediction is ON CONFLICT DO UPDATE and overwrites probability, class, price and features of the stored row",
)
def test_ts5_re_scoring_a_stored_prediction_with_a_different_value_leaves_the_stored_row_unchanged(db_session):
    inst = _stock(db_session, "TS5KEEP")
    model = _model(db_session, "ts5")
    ts = _bar_ts(date(2026, 12, 1))

    predict._upsert_prediction(db_session, model, _result(inst, ts, 0.80, 100.0))
    db_session.flush()
    predict._upsert_prediction(db_session, model, _result(inst, ts, 0.20, 90.0))  # the re-run, a different value
    db_session.flush()

    rows = db_session.execute(select(Prediction).where(Prediction.instrument_id == inst.id)).scalars().all()
    original = min(rows, key=lambda r: r.id) if rows else None  # the first-stored row
    assert original is not None
    assert (original.probability, original.predicted_class, original.price_at_prediction) == (0.80, 1, 100.0)
    assert original.features == {"f1": 0.80}


def test_ts5_control_the_same_value_twice_stays_one_row(db_session):
    """Passes today: an identical re-run does not duplicate (the idempotence the upsert was written for)."""
    inst = _stock(db_session, "TS5SAME")
    model = _model(db_session, "ts5same")
    ts = _bar_ts(date(2026, 12, 1))
    for _ in range(2):
        predict._upsert_prediction(db_session, model, _result(inst, ts, 0.80, 100.0))
        db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(Prediction).where(Prediction.instrument_id == inst.id)) == 1


# ================================================== TS6  backfill_watchlist with Kite errors for some symbols (mocked)


def _bars_for_today() -> list[dict]:
    d = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    return [{"date": d, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000}]


def _kite_with_failures(monkeypatch, failing_tokens: set[int], exc: Exception) -> None:
    def fake_historical(token, start, end, interval, db):
        if token in failing_tokens:
            raise exc
        return _bars_for_today()

    monkeypatch.setattr(kite_broker, "get_historical_data", fake_historical)


def test_ts6_other_symbols_still_ingest_and_a_failing_symbol_stores_no_partial_bar(db_session, monkeypatch):
    ok1, bad, ok2 = _stock(db_session, "TS6OK1"), _stock(db_session, "TS6BAD"), _stock(db_session, "TS6OK2")
    _kite_with_failures(monkeypatch, {bad.instrument_token}, RuntimeError("Kite 500"))

    results = ingestion.backfill_watchlist(db_session, interval="day", days=5, incremental=False)

    assert results["TS6OK1"] == 1 and results["TS6OK2"] == 1
    counts = {
        sym: db_session.scalar(select(func.count()).select_from(Candle).where(Candle.instrument_id == i.id))
        for sym, i in (("ok1", ok1), ("bad", bad), ("ok2", ok2))
    }
    assert counts == {"ok1": 1, "bad": 0, "ok2": 1}


@pytest.mark.xfail(
    **GAP,
    reason="ingestion orchestration (TS6): a symbol whose every Kite call failed is returned as 0 bars, the same as 'nothing new'; failures are logged but not counted or reported in the result",
)
def test_ts6_failures_are_counted_and_reported_apart_from_no_new_bars(db_session, monkeypatch):
    _stock(db_session, "TS6OKB")
    bad = _stock(db_session, "TS6BADB")
    _kite_with_failures(monkeypatch, {bad.instrument_token}, RuntimeError("Kite 500"))

    results = ingestion.backfill_watchlist(db_session, interval="day", days=5, incremental=False)

    # Required: the caller can tell "failed" from "0 new bars" (any shape: a failures key, a marker value, an exception summary).
    assert results.get("TS6BADB") != 0 or any("fail" in str(k).lower() for k in results), (
        f"a failed symbol is indistinguishable from 'no new bars': {results}"
    )


# ================================================= TS8  Kite session expires in the middle of job_daily_ingest (mocked)


@pytest.mark.xfail(
    **GAP,
    reason="gap #357 / #353 (TS8): a mid-run session expiry is swallowed per window (log only): symbols are not recorded as session_expired and no single admin alert is raised",
)
def test_ts8_a_session_that_expires_mid_ingest_is_recorded_and_alerted_once(db_session, monkeypatch):
    from swing_trade_ml.workers import jobs

    for i in range(3):
        _stock(db_session, f"TS8SYM{i}")
    calls = {"n": 0}

    def expiring(token, start, end, interval, db):
        calls["n"] += 1
        if calls["n"] > 1:  # the first symbol succeeds, then the token dies
            raise PermissionError("TokenException: session expired")
        return _bars_for_today()

    monkeypatch.setattr(kite_broker, "get_historical_data", expiring)

    @contextmanager
    def scope():
        yield db_session

    alerts: list[tuple[str, str]] = []
    monkeypatch.setattr(jobs, "session_scope", scope)
    monkeypatch.setattr(jobs, "_report_error", lambda context, exc: alerts.append((context, str(exc))))
    monkeypatch.setattr(ingestion, "backfill_index", lambda db, interval="day", days=None: 0)
    monkeypatch.setattr(ingestion, "backfill_context_indices", lambda db, interval="day", days=None: {})
    import swing_trade_ml.services.watchlist_snapshots as snapshots

    monkeypatch.setattr(snapshots, "record_watchlist_snapshot", lambda db: None)
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    jobs.job_daily_ingest()

    assert len(alerts) == 1 and "session" in alerts[0][1].lower(), f"expected one session-expired admin alert, got {alerts}"


def test_ts8_control_the_ingest_never_stores_a_bar_for_a_symbol_whose_call_failed(db_session, monkeypatch):
    """Passes today: whatever the alerting gap, a failed symbol gets no partial or invented bar."""
    ok, dead = _stock(db_session, "TS8OK"), _stock(db_session, "TS8DEAD")

    def fake(token, start, end, interval, db):
        if token == dead.instrument_token:
            raise PermissionError("TokenException: session expired")
        return _bars_for_today()

    monkeypatch.setattr(kite_broker, "get_historical_data", fake)
    ingestion.backfill_watchlist(db_session, interval="day", days=5, incremental=False)
    n = lambda i: db_session.scalar(select(func.count()).select_from(Candle).where(Candle.instrument_id == i.id))  # noqa: E731
    assert (n(ok), n(dead)) == (1, 0)


# ========================================== TS7  end-to-end: candles -> predict -> scan -> paper fill -> mark -> summary


def test_ts7_the_whole_5d_chain_runs_on_fixed_fixtures_with_no_kite(db_session, stub_model_world, monkeypatch):
    """One test for the chain: candle fixtures, `predict_watchlist`, `run_all_active`, the paper fill, `mark_to_market`,
    the daily summary job. Fixed bars and a fixed score; the broker is logged out, the model is a stub, Telegram is stubbed.
    It pins today's behaviour (including the same-close fill that #354 will change), so a change anywhere in the chain
    shows up here."""
    from swing_trade_ml.core.enums import PositionStatus
    from swing_trade_ml.db.models.trading import Position, Signal, Strategy
    from swing_trade_ml.services import engine, portfolio
    from swing_trade_ml.strategies import ml_swing
    from swing_trade_ml.workers import jobs

    current, _ = _sessions()
    inst = _stock(db_session, "TS7CHAIN")
    _history(db_session, inst, current, n=300, close=100.0)
    _model(db_session, "ts7")
    last_close = float(
        db_session.scalar(
            select(Candle.close).where(Candle.instrument_id == inst.id).order_by(Candle.ts.desc()).limit(1)
        )
    )
    _put_quote(db_session, inst, last_close, datetime.now(UTC))  # the live price, fresh by the app's own limit
    db_session.add(Strategy(name="ts7_ml_swing", strategy_type="ml_swing", mode="paper", params={}, is_active=True))
    db_session.flush()

    # --- the scan scores with the same stubs the watchlist prediction used
    monkeypatch.setattr(ml_swing, "_get_bundle", predict._get_bundle)
    monkeypatch.setattr(ml_swing, "build_features", lambda d, *a, **k: predict.build_features(d).assign(nifty_trend_regime=1.0))
    for loader in ("load_index_candles", "load_sector_candles", "load_vix_candles", "load_market_breadth"):
        monkeypatch.setattr(ml_swing, loader, lambda *a, **k: pd.DataFrame())
    monkeypatch.setattr(db_session, "commit", db_session.flush)  # the scan commits; the test transaction must survive

    # 1. watchlist prediction stores one row for the current bar
    scored = predict.predict_watchlist(db_session, persist=True)
    assert [r.symbol for r in scored] == ["TS7CHAIN"]
    row = db_session.execute(select(Prediction).where(Prediction.instrument_id == inst.id)).scalar_one()
    assert row.probability == pytest.approx(0.9) and row.ts == _bar_ts(current)

    # 2 + 3. the scan turns the score into a BUY and a paper fill
    result = engine.run_all_active(db_session)
    assert result.errors == [], result.errors
    assert result.buys == 1 and result.executed == 1
    signal = db_session.execute(select(Signal).where(Signal.instrument_id == inst.id)).scalars().one()
    assert signal.was_executed is True
    position = db_session.execute(select(Position).where(Position.instrument_id == inst.id)).scalar_one()
    assert position.status == PositionStatus.OPEN and position.entry_price == pytest.approx(last_close, rel=0.01)

    # 4. the price moves up 3%: mark_to_market carries it into the position
    quote = db_session.execute(select(Quote).where(Quote.instrument_id == inst.id)).scalar_one()
    quote.last_price = round(position.entry_price * 1.03, 2)
    db_session.flush()
    assert portfolio.mark_to_market(db_session) == 1
    db_session.refresh(position)
    assert position.current_price == pytest.approx(quote.last_price)
    assert position.unrealized_pnl == pytest.approx((quote.last_price - position.entry_price) * position.quantity)

    # 5. the daily summary job marks, snapshots and sends one digest carrying the open position's state
    sent: list[tuple] = []

    async def fake_notify(stats, mode, post_exit_watch=None):
        sent.append((stats, mode))

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)
    monkeypatch.setattr(jobs.notifier, "notify_daily_summary", fake_notify)
    jobs.job_daily_summary()
    assert len(sent) == 1 and sent[0][1] == "paper"
