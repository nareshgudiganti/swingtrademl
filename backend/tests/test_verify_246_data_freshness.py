# ruff: noqa: E501  (long plain-English test text)
"""#246 Verify market data freshness and missing-data handling (parent #231).

Tests only. Nothing here changes ingestion, the scan, risk, orders or any frozen file. Each test says what the code is
EXPECTED to do and then checks what it OBSERVABLY does at the baseline commit. Where the code falls short, the test is a
strict expected failure (`xfail(strict=True, raises=AssertionError)`) with one line saying what is missing; if the code is
ever fixed the strict xfail turns red and must be removed on purpose.

Sections: (a) daily candle ingestion, (b) quotes, (c) the Brain's dated reader and M01, (d) the version-1 scan path.
The findings note is docs/verification/246-data-freshness.md. Needs the test database; every write rolls back.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlalchemy import select, text

import swing_trade_ml
from swing_trade_ml.brain.modules.m01_quality.quality import assess_bars, expected_bar_day
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.feeds import DailyDelivery, UpcomingEvent
from swing_trade_ml.db.models.market import Candle, CandleArrival, CandleCorrection, Instrument, Quote
from swing_trade_ml.services import ingestion
from swing_trade_ml.services.quote_snapshot import CandlePoint, candle_points

IST = ZoneInfo("Asia/Kolkata")
SRC = Path(swing_trade_ml.__file__).parent
REPO = Path(__file__).resolve().parents[2]
_tokens = iter(range(960_000, 960_900))

GAP = {"strict": True, "raises": AssertionError}


def ist_midnight(day: date) -> datetime:
    """How Kite stamps a daily bar: midnight IST (18:30 UTC the day before)."""
    return datetime.combine(day, time(0, 0), tzinfo=IST)


def trading_days(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if market_session.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def make_instrument(db, symbol: str, *, watchlisted: bool = False) -> Instrument:
    inst = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        exchange="NSE",
        instrument_type="EQ",
        is_active=True,
        is_watchlisted=watchlisted,
    )
    db.add(inst)
    db.flush()
    return inst


def add_bar(db, inst: Instrument, day: date, close: float = 100.0, volume: int = 1000) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=ist_midnight(day).astimezone(UTC),
            open=close,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=volume,
        )
    )
    db.flush()


def bar_dict(day: date, close: float) -> dict:
    return {
        "date": ist_midnight(day),
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1000,
    }


def db_is_utc(db) -> bool:
    return str(db.execute(text("SHOW TIME ZONE")).scalar()).upper() in {"UTC", "ETC/UTC", "GMT"}


# =================================================================================== (a) daily candle ingestion


def test_a1_a_late_bar_records_when_it_really_arrived_so_its_lateness_is_readable(db_session):
    """Expected: a bar for an old session that arrives now is stamped with TODAY as its arrival, so lateness can be told."""
    inst = make_instrument(db_session, "A1LATE")
    today = datetime.now(IST).date()
    session_day = today - timedelta(days=10)
    ingestion._upsert_candles(db_session, inst.id, "day", [bar_dict(session_day, 100.0)])
    arrival = db_session.scalar(select(CandleArrival).where(CandleArrival.instrument_id == inst.id))
    assert arrival is not None
    late_by = (arrival.received_at.astimezone(IST).date() - session_day).days
    assert late_by >= 10  # the session date and the arrival date are both kept: the lateness is derivable


def test_a2_a_changed_bar_is_a_logged_correction_and_an_unchanged_one_is_not(db_session):
    inst = make_instrument(db_session, "A2CORR")
    day = datetime.now(IST).date() - timedelta(days=3)
    ingestion._upsert_candles(db_session, inst.id, "day", [bar_dict(day, 100.0)])
    ingestion._upsert_candles(db_session, inst.id, "day", [bar_dict(day, 100.0)])  # the same bar again
    assert (
        db_session.scalar(select(CandleCorrection).where(CandleCorrection.instrument_id == inst.id)) is None
    )
    first_arrival = db_session.scalar(
        select(CandleArrival.received_at).where(CandleArrival.instrument_id == inst.id)
    )
    ingestion._upsert_candles(
        db_session, inst.id, "day", [bar_dict(day, 103.5)]
    )  # the provider restated the close
    fix = db_session.scalar(select(CandleCorrection).where(CandleCorrection.instrument_id == inst.id))
    assert (
        fix is not None and (fix.old_close, fix.new_close) == (100.0, 103.5) and fix.corrected_at is not None
    )
    stored = db_session.scalar(select(Candle.close).where(Candle.instrument_id == inst.id))
    assert stored == 103.5  # the newest value is what is read
    assert (
        db_session.scalar(select(CandleArrival.received_at).where(CandleArrival.instrument_id == inst.id))
        == first_arrival
    )


def test_a3_a_missed_day_shows_in_the_plain_status_sentence():
    from swing_trade_ml.api.v1.endpoints.system import _plain_status

    now = datetime(2026, 12, 1, 10, 0, tzinfo=IST)  # a Tuesday: the bar of Monday 30 Nov should be in

    def status(latest):
        return _plain_status(
            broker_authenticated=True,
            scheduler_running=True,
            latest_candle_date=latest,
            last_scan_at=None,
            now_ist=now,
            calendar_warning=None,
        )

    level, sentence = status(date(2026, 11, 27))  # Friday's bar is the newest: Monday's is missing
    assert level == "warning" and "hasn't updated since 27 Nov" in sentence
    assert "never" in status(None)[1]
    assert "hasn't updated" not in status(date(2026, 11, 30))[1]  # current: no data warning


def test_a4_the_daily_ingest_job_reports_a_failure_and_does_not_hide_it(monkeypatch):
    """Expected: when the day's ingest breaks, an error is reported (alert + Admin > Jobs), not swallowed silently."""
    from swing_trade_ml.workers import jobs

    reported = []
    monkeypatch.setattr(jobs, "_report_error", lambda context, exc: reported.append((context, str(exc))))

    class Boom:
        def __enter__(self):
            raise RuntimeError("provider down")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(jobs, "session_scope", lambda: Boom())
    jobs.job_daily_ingest()
    assert reported == [("daily_ingest", "provider down")]


def test_a5_daily_bars_are_dated_in_ist_where_it_matters():
    """Kite stamps a daily bar at IST midnight, which is the PREVIOUS day in UTC. These readers take the IST date."""
    day = date(2026, 12, 1)
    row = SimpleNamespace(ts=ist_midnight(day).astimezone(UTC), close=10.0)
    assert row.ts.date() == date(2026, 11, 30)  # what a careless .date() would give
    assert candle_points([row]) == [CandlePoint(day=day, close=10.0)]  # quote_snapshot.py:80
    # brain/reader.py:99, :186, :299, :311 and system.py:208 do the same; the reader ones are exercised in (c) below.


def test_a6_every_date_taken_from_a_candle_timestamp_is_in_ist_except_the_listed_gaps():
    """A source scan (read-only): a `.date()` on a candle `ts` that is not converted to IST is a finding.
    The known ones are pinned here so a new one cannot appear unseen; fixing one means deleting its line.
    Limit: the scan is name-based (a receiver named `ts` or `df['ts']`), so a `.date()` on a differently named variable
    holding a candle time would not be seen."""
    found = set()
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "date"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "dt"
            ):  # pandas: series.dt.date on a timestamp column that was not converted first
                text_ = ast.unparse(node.value.value)
                if "ts" in text_ and "tz_convert" not in text_ and "tz_localize" not in text_:
                    found.add((rel, ast.unparse(node)))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "date"
                and not node.args
            ):
                receiver = ast.unparse(
                    node.func.value
                )  # python: something.ts.date() with no astimezone before it
                if receiver.split(".")[-1] == "ts" or receiver.endswith('["ts"]'):
                    found.add((rel, ast.unparse(node)))
    backtest: set = set()  # gap a8 is fixed (#470): backtest dates are IST days now
    snapshots = {  # PortfolioSnapshot.ts, not a candle; written mid-afternoon IST, so its UTC and IST dates agree
        ("services/portfolio.py", "previous.ts.date()"),
        ("services/portfolio.py", "s.ts.date()"),
    }
    assert found == backtest | snapshots, sorted(found ^ (backtest | snapshots))


def test_a7_the_coverage_endpoint_names_the_ist_date_of_the_newest_bar(db_session):
    from swing_trade_ml.api.v1.endpoints.market_data import coverage

    if not db_is_utc(db_session):
        pytest.skip("the database session is not in UTC; the defect needs a UTC session")
    inst = make_instrument(db_session, "A7COV", watchlisted=True)
    add_bar(db_session, inst, date(2026, 12, 1))
    row = next(r for r in coverage(db_session, "day") if r["symbol"] == "A7COV")
    assert row["to"] == "2026-12-01", row  # market_data.py:250-251 gives "2026-11-30"


def test_a8_the_backtest_places_each_bar_on_its_ist_trading_day(db_session):
    from swing_trade_ml.ml.dataset import load_candles
    from swing_trade_ml.services.backtest import _last_close

    if not db_is_utc(db_session):
        pytest.skip("the database session is not in UTC; the defect needs a UTC session")
    inst = make_instrument(db_session, "A8BT")
    add_bar(db_session, inst, date(2026, 11, 30), close=100.0)
    add_bar(db_session, inst, date(2026, 12, 1), close=200.0)
    frame = load_candles(db_session, inst.id, "day")
    assert _last_close(frame, date(2026, 11, 30)) == 100.0  # backtest.py:109 returns 200.0 (Dec 1's bar)


# a9 closed by #565: services/admin_candle_log.py reads both tables for the admin screen.
def test_a9_late_and_corrected_candles_can_be_read_back_outside_the_writer():
    readers = set()
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in {"services/ingestion.py", "db/models/market.py", "db/models/__init__.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and any(
                a.name in {"CandleArrival", "CandleCorrection"} for a in node.names
            ):
                readers.add(rel)
    assert readers, "nothing outside the ingestion writer reads candle_arrivals or candle_corrections"


# ============================================================================================= (b) quotes


def _snapshot(db, symbol):
    from swing_trade_ml.api.v1.endpoints.market_data import get_price_snapshot

    return get_price_snapshot(symbol, db, "NSE")


def _quote(db, inst, price: float, ts: datetime) -> None:
    db.add(Quote(instrument_id=inst.id, last_price=price, close=price, ts=ts))
    db.flush()


def _two_recent_bars(db, inst):
    today = datetime.now(IST).date()
    d2, d1 = (
        market_session.previous_trading_day(market_session.previous_trading_day(today)),
        market_session.previous_trading_day(today),
    )
    add_bar(db, inst, d2, 90.0)
    add_bar(db, inst, d1, 100.0)
    return d1


def test_b1_a_stale_or_future_quote_is_never_shown_as_live(db_session):
    inst = make_instrument(db_session, "B1STALE")
    _two_recent_bars(db_session, inst)
    now = datetime.now(UTC)
    for label, ts in (
        ("3 hours old", now - timedelta(hours=3)),
        ("2 days old", now - timedelta(days=2)),
        ("in the future", now + timedelta(hours=1)),
    ):
        db_session.query(Quote).filter_by(instrument_id=inst.id).delete()
        _quote(db_session, inst, 555.0, ts)
        snap = _snapshot(db_session, "B1STALE")
        assert snap.state not in ("live", "delayed"), (label, snap.state)  # "stale", or "holiday"/"closed" on a market holiday
        assert snap.change_pct is None or snap.state != "live"


def test_b2_a_missing_quote_shows_the_last_close_with_its_own_date_and_never_a_live_state(db_session):
    inst = make_instrument(db_session, "B2NOQ")
    last_day = _two_recent_bars(db_session, inst)
    snap = _snapshot(db_session, "B2NOQ")
    assert snap.state in {"close_only", "closed", "holiday", "stale"} and snap.state not in {
        "live",
        "delayed",
    }
    assert (
        snap.price == 100.0 and snap.price_date == last_day and snap.price_ts is None
    )  # a close, labelled with its date
    assert snap.note  # says in words what the price is


def test_b3_no_quote_and_no_candle_is_no_data_not_a_price(db_session):
    make_instrument(db_session, "B3NONE")
    snap = _snapshot(db_session, "B3NONE")
    assert snap.state == "no_data" and snap.price is None


def test_b4_the_raw_quote_endpoint_returns_the_true_timestamp_or_a_404(db_session):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints.market_data import get_quote

    inst = make_instrument(db_session, "B4RAW")
    with pytest.raises(HTTPException) as caught:
        get_quote("B4RAW", db_session, "NSE")
    assert caught.value.status_code == 404
    old = datetime.now(UTC) - timedelta(days=4)
    _quote(db_session, inst, 77.0, old)
    row = get_quote("B4RAW", db_session, "NSE")
    assert (
        row.ts == old and row.last_price == 77.0
    )  # honest: its own age is carried, nothing relabels it as fresh


def test_b5_the_screens_ask_for_the_labelled_snapshot_and_not_the_raw_quote():
    client = (REPO / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    assert "/market-data/snapshot/" in client and "/market-data/quote/" not in client


def test_b6_an_old_cached_quote_does_not_beat_a_newer_close_for_a_paper_fill(db_session, monkeypatch):
    from swing_trade_ml.brokers.kite import kite_broker
    from swing_trade_ml.brokers.paper import PaperBroker

    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: False))
    inst = make_instrument(db_session, "B6OLDQ")
    _two_recent_bars(db_session, inst)  # the newest close is 100.0, from the last trading day
    _quote(db_session, inst, 500.0, datetime.now(UTC) - timedelta(days=5))
    price = PaperBroker()._reference_price("B6OLDQ", "NSE", db_session)
    assert price == 100.0, price  # brokers/paper.py:92-96 returns the 5-day-old 500.0


def test_b7_a_quote_with_no_price_is_not_stored_as_a_fresh_zero(db_session, monkeypatch):
    from swing_trade_ml.brokers.kite import kite_broker

    inst = make_instrument(db_session, "B7ZERO", watchlisted=True)
    monkeypatch.setattr(type(kite_broker), "is_authenticated", property(lambda self: True))
    monkeypatch.setattr(
        kite_broker,
        "get_quote",
        lambda keys, db: {inst.symbol_key: {"ohlc": {"close": 100.0}}},
        raising=False,
    )
    ingestion.refresh_quotes(db_session)
    stored = db_session.scalar(select(Quote).where(Quote.instrument_id == inst.id))
    assert stored is None or stored.last_price > 0, (
        stored.last_price
    )  # ingestion.py:603-617 stores 0.0 with ts=now


# ============================================================================ (c) the Brain's dated reader and M01


def _reader_world(db):
    inst = make_instrument(db, "RDR246")
    days = trading_days(date(2026, 11, 2), 6)
    for i, d in enumerate(days):
        add_bar(
            db, inst, d, close=100.0 + i if i < 4 else 99_999.0
        )  # D5 and D6 are poison: they are the future
    return inst, days


def test_c1_the_reader_never_returns_a_bar_after_as_of_and_dates_bars_in_ist(db_session):
    _, days = _reader_world(db_session)
    as_of = datetime.combine(days[3], time(18, 0), tzinfo=IST)  # after D4's close, before D5
    reader = DatedReader(db_session, as_of=as_of, live=False)
    assert reader.last_close("RDR246") == (days[3].isoformat(), 103.0)
    assert reader.ohlcv("RDR246")["close"].max() == 103.0 and len(reader.ohlcv("RDR246")) == 4
    assert (
        reader.dated_closes("RDR246").index.max() == days[3] and reader.dated_closes("RDR246").max() == 103.0
    )
    assert (
        reader.recent_bars("RDR246")["day"].iloc[-1] == days[3]
        and reader.dated_bars("RDR246")["close"].max() == 103.0
    )
    assert ist_midnight(days[3]).astimezone(UTC).date() == days[3] - timedelta(days=1)  # the trap this avoids


def test_c2_an_instant_before_a_bar_excludes_it_and_the_instant_of_the_bar_includes_it(db_session):
    _, days = _reader_world(db_session)
    before = ist_midnight(days[3]) - timedelta(seconds=1)
    assert DatedReader(db_session, as_of=before, live=False).last_close("RDR246")[0] == days[2].isoformat()
    at = ist_midnight(days[3])
    assert DatedReader(db_session, as_of=at, live=False).last_close("RDR246")[0] == days[3].isoformat()


def test_c3_observed_limit_a_daily_bar_counts_as_known_from_ist_midnight(db_session):
    """The bar of day D is stamped D 00:00 IST, so an as_of at 09:00 IST on D already sees it, six hours before its close.
    Harmless today (a live run follows the ingest and a same-day bar is not yet stored; replays use end of day), but it is
    the rule the reader enforces, so it is pinned. Callers must not pass an intraday as_of."""
    _, days = _reader_world(db_session)
    morning = datetime.combine(days[3], time(9, 0), tzinfo=IST)
    assert DatedReader(db_session, as_of=morning, live=False).last_close("RDR246")[0] == days[3].isoformat()


def test_c4_the_benchmark_series_is_cut_at_as_of_too(db_session):
    inst = make_instrument(db_session, settings.BENCHMARK_INDEX_SYMBOL)
    days = trading_days(date(2026, 11, 2), 5)
    for i, d in enumerate(days):
        add_bar(db_session, inst, d, close=25_000.0 + i if i < 3 else 1.0)
    as_of = datetime.combine(days[2], time(18, 0), tzinfo=IST)
    closes = DatedReader(db_session, as_of=as_of, live=False).index_closes()
    assert list(closes) == [25_000.0, 25_001.0, 25_002.0]


def test_c5_side_feeds_are_cut_by_when_they_were_stored_or_by_trading_day(db_session):
    _, days = _reader_world(db_session)
    as_of = datetime.combine(days[3], time(18, 0), tzinfo=IST)
    reader = DatedReader(db_session, as_of=as_of, live=False)
    db_session.add_all(
        [
            UpcomingEvent(
                symbol="FEED246",
                kind="results",
                event_date=days[5],
                detail="stored before",
                created_at=as_of - timedelta(days=1),
            ),
            UpcomingEvent(
                symbol="FEED246",
                kind="corporate_action",
                event_date=days[5],
                detail="stored after",
                created_at=as_of + timedelta(hours=1),
            ),
        ]
    )
    for d in (days[2], days[3], days[4]):
        db_session.add(DailyDelivery(symbol="FEED246", series="EQ", trade_date=d, delivery_pct=40.0))
    db_session.flush()
    assert [e.detail for e in reader.event_rows(["FEED246"])] == [
        "stored before"
    ]  # judged by created_at: later rows are the future
    assert [d for d, _ in reader.delivery_rows(["FEED246"])["FEED246"]] == [
        days[2],
        days[3],
    ]  # the next day's file is excluded


def test_c6_m01_flags_a_twelve_day_old_bar_and_a_stock_with_no_bars():
    """The same stale case as the v1 gap in (d): the Brain's quality gate sees it and marks the stock not fresh."""
    expected = date(2026, 12, 1)
    days = [d for d in trading_days(date(2026, 8, 3), 200) if d <= date(2026, 11, 19)]
    stale = pd.DataFrame(
        {"day": days, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}
    )
    verdict = assess_bars("OLD", stale, expected, set())
    assert (
        verdict.fresh is False
        and verdict.score < 0.6
        and any("trading days old" in i for i in verdict.issues)
    )
    none = assess_bars("NONE", stale.iloc[0:0], expected, set())
    assert (none.score, none.fresh, none.issues) == (0.0, False, ("No price data for this stock.",))


@pytest.mark.xfail(
    **GAP,
    reason="gap c7: M01 expects today's bar after 15:40 IST but /status and the v1 scan treat the previous day as the newest bar (#316/#353)",
)
def test_c7_m01_and_the_status_page_agree_on_which_bar_should_exist_at_four_pm():
    after_close = datetime(2026, 12, 1, 16, 0, tzinfo=IST)  # a trading Tuesday, after the 15:40 ingest
    from swing_trade_ml.api.v1.endpoints.system import _expected_latest_trading_day

    assert expected_bar_day(after_close) == _expected_latest_trading_day(after_close)


# ====================================================================================== (d) the v1 scan path


def test_d1_the_scan_job_is_a_separate_cron_job_with_no_link_to_the_ingest_result():
    scheduler = (SRC / "workers" / "scheduler.py").read_text(encoding="utf-8")
    assert 'id="daily_ingest"' in scheduler and 'id="signal_scan"' in scheduler
    jobs_src = (SRC / "workers" / "jobs.py").read_text(encoding="utf-8")
    scan = jobs_src.split("def job_signal_scan", 1)[1].split("\ndef ", 1)[0]
    for word in ("latest_candle", "expected_latest", "daily_ingest", "stale", "fresh"):
        assert word not in scan  # no freshness or ingest-status check inside the scan job


# Gap d2 closed by #316 (PR #548): the scan now waits for validated candles and does not run on a stale day.
def test_d2_no_scan_runs_when_the_candles_are_stale_and_the_ingest_failed(db_session, monkeypatch):
    from contextlib import contextmanager

    from swing_trade_ml.workers import jobs

    inst = make_instrument(db_session, "D2STALE", watchlisted=True)
    twelve_days_ago = datetime.now(IST).date() - timedelta(days=12)
    add_bar(
        db_session, inst, market_session.previous_trading_day(twelve_days_ago + timedelta(days=1))
    )  # the newest bar
    calls = []

    @contextmanager
    def scope():
        yield db_session

    quiet = SimpleNamespace(
        strategies_run=0, instruments_evaluated=0, signals_generated=0, buys=0, exits=0, executed=0, errors=[]
    )
    monkeypatch.setattr(jobs, "session_scope", scope)
    monkeypatch.setattr(
        jobs.engine, "run_all_active", lambda db, interval="day": calls.append(interval) or quiet
    )
    monkeypatch.setattr(jobs.held_read, "score_tester_positions", lambda db: None)
    monkeypatch.setattr(jobs.held_read, "score_tracked_stocks", lambda db: None)
    monkeypatch.setattr(jobs.heartbeat, "write_last_scan", lambda payload: None)
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda *a, **k: None)
    jobs._report_error("daily_ingest", RuntimeError("provider down"))  # today's ingest failed
    jobs.job_signal_scan()
    assert calls == [], "the v1 scan ran anyway (services/engine.py:136-140 then scores the old bar)"
