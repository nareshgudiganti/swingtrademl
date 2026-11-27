"""#316 slice 1: the daily scan waits for the session's candles instead of scanning yesterday's.

Before this, a 15:45 scan that ran before the day's daily candles arrived treated yesterday's bar as
the latest one and could signal (and paper-buy) on it, with nothing re-scanning after the data landed.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from itertools import count

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import scan_readiness
from swing_trade_ml.workers import jobs

FRIDAY = date(2026, 11, 13)  # a trading day
AFTER_CLOSE = datetime.combine(FRIDAY, time(15, 45), tzinfo=IST)
BENCH = "TEST BENCH 316"
_tokens = count(316_000)


@pytest.fixture(autouse=True)
def _bench(monkeypatch):
    monkeypatch.setattr(settings, "BENCHMARK_INDEX_SYMBOL", BENCH)


def _inst(db, symbol: str, *, watch: bool = True, active: bool = True) -> Instrument:
    inst = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        exchange="NSE",
        is_watchlisted=watch,
        is_active=active,
    )
    db.add(inst)
    db.flush()
    return inst


def _bar(db, inst: Instrument, day: date) -> None:
    # Daily candles are stamped IST midnight.
    ts = datetime.combine(day, time(0, 0), tzinfo=IST)
    db.add(Candle(instrument_id=inst.id, interval="day", ts=ts, open=1, high=1, low=1, close=1, volume=1))
    db.flush()


def _bench_inst(db, *, today: bool = True) -> Instrument:
    bench = _inst(db, BENCH, watch=False)
    _bar(db, bench, FRIDAY - timedelta(days=1))
    if today:
        _bar(db, bench, FRIDAY)
    return bench


# ------------------------------------------------------------------ the check


def test_target_session_is_today_after_the_bar_is_final_and_the_last_trading_day_otherwise():
    assert scan_readiness.target_session(AFTER_CLOSE) == FRIDAY
    before_final = datetime.combine(FRIDAY, time(15, 35), tzinfo=IST)
    assert scan_readiness.target_session(before_final) == date(2026, 11, 12)
    saturday = datetime.combine(FRIDAY + timedelta(days=1), time(16, 0), tzinfo=IST)
    assert scan_readiness.target_session(saturday) == FRIDAY


def test_ready_and_complete_when_the_benchmark_and_every_stock_have_the_session_bar(db_session):
    _bench_inst(db_session)
    for sym in ("AAA", "BBB"):
        _bar(db_session, _inst(db_session, sym), FRIDAY)

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert r.ready and r.status == "complete"
    assert (r.target_session, r.required, r.arrived, r.missing) == (FRIDAY, 2, 2, [])


def test_waits_when_the_benchmark_bar_has_not_arrived(db_session):
    _bench_inst(db_session, today=False)
    _bar(db_session, _inst(db_session, "AAA"), FRIDAY)

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert not r.ready and r.status == "waiting"
    assert BENCH in r.reason


def test_waits_when_no_stock_has_the_session_bar_yet(db_session):
    _bench_inst(db_session)
    for sym in ("AAA", "BBB"):
        _bar(db_session, _inst(db_session, sym), FRIDAY - timedelta(days=1))  # yesterday only

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert not r.ready and r.status == "waiting"
    assert "0 of 2" in r.reason
    assert r.missing == ["AAA", "BBB"]


def test_some_stocks_missing_still_scans_but_is_labelled_partial_with_their_names(db_session):
    _bench_inst(db_session)
    _bar(db_session, _inst(db_session, "AAA"), FRIDAY)
    _bar(db_session, _inst(db_session, "CCC"), FRIDAY - timedelta(days=1))
    _inst(db_session, "BBB")  # no candles at all

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert r.ready and r.status == "partial"
    assert (r.required, r.arrived, r.missing) == (3, 1, ["BBB", "CCC"])


def test_unwatched_and_inactive_stocks_are_not_required(db_session):
    _bench_inst(db_session)
    _bar(db_session, _inst(db_session, "AAA"), FRIDAY)
    _inst(db_session, "OFFLIST", watch=False)
    _inst(db_session, "DELISTED", active=False)

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert r.status == "complete" and r.required == 1


def test_the_record_lists_at_most_twenty_missing_names_but_counts_them_all(db_session):
    _bench_inst(db_session)
    _bar(db_session, _inst(db_session, "HAS"), FRIDAY)
    for i in range(25):
        _inst(db_session, f"M{i:02d}")

    rec = scan_readiness.check(db_session, AFTER_CLOSE).record()

    assert rec["missing_count"] == 25 and len(rec["missing_symbols"]) == 20
    assert rec["target_session"] == "2026-11-13" and rec["status"] == "partial"


def _strategy(db, name: str, symbols: list[str], *, active: bool = True) -> None:
    db.add(Strategy(name=name, strategy_type="ml_swing", mode="paper", is_active=active, symbols=symbols))
    db.flush()


def test_a_strategy_only_stock_without_its_bar_makes_the_scan_partial(db_session):
    # The scan also scores each active strategy's own list (e.g. mid/small-cap stocks off the watchlist).
    _bench_inst(db_session)
    _bar(db_session, _inst(db_session, "AAA"), FRIDAY)
    _inst(db_session, "MIDCAP316", watch=False)  # on no watchlist, no bar today
    _strategy(db_session, "test-316-midcap", ["midcap316", "AAA"])

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert r.status == "partial" and "MIDCAP316" in r.missing
    assert (r.required, r.arrived) == (2, 1)


def test_an_inactive_strategys_stocks_and_index_rows_are_not_required(db_session):
    _bench_inst(db_session)
    _bar(db_session, _inst(db_session, "AAA"), FRIDAY)
    _inst(db_session, "PARKED316", watch=False)
    _strategy(db_session, "test-316-parked", ["PARKED316"], active=False)
    index = _inst(db_session, "INDEX316")  # watchlisted, but an index is never a stock
    index.instrument_type = "INDEX"
    _strategy(db_session, "test-316-index", ["INDEX316"])
    db_session.flush()

    r = scan_readiness.check(db_session, AFTER_CLOSE)

    assert r.status == "complete" and r.required == 1
    stocks = set(scan_readiness.scan_stocks(db_session).values())
    assert "AAA" in stocks and not {"PARKED316", "INDEX316"} & stocks


# ------------------------------------------------------------------ the scan job


def _use_test_session(monkeypatch, db_session) -> None:
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)


class _Result:
    strategies_run, instruments_evaluated, signals_generated = 1, 2, 0
    buys = exits = executed = 0
    errors = ()


def _wire(monkeypatch, db_session, readiness):
    written, scans = [], []
    _use_test_session(monkeypatch, db_session)
    monkeypatch.setattr(jobs.scan_readiness, "check", lambda db, now=None: readiness)
    monkeypatch.setattr(
        jobs.engine, "run_all_active", lambda db, interval="day": scans.append(1) or _Result()
    )
    monkeypatch.setattr(jobs.held_read, "score_tester_positions", lambda db: None)
    monkeypatch.setattr(jobs.held_read, "score_tracked_stocks", lambda db: None)
    monkeypatch.setattr(jobs.heartbeat, "write_last_scan", written.append)
    monkeypatch.setattr(jobs.heartbeat, "read_last_scan", lambda: None)  # no scan recorded yet today
    monkeypatch.setattr(jobs.notifier, "send_sync", lambda *a, **k: True)
    return written, scans


def _readiness(status: str, missing=()) -> scan_readiness.Readiness:
    return scan_readiness.Readiness(
        target_session=FRIDAY,
        status=status,
        required=3,
        arrived=3 - len(missing),
        missing=list(missing),
        reason="today's prices have not arrived yet" if status == "waiting" else "",
    )


def test_a_waiting_scan_does_not_run_the_strategies_and_records_why(db_session, monkeypatch):
    written, scans = _wire(monkeypatch, db_session, _readiness("waiting", ["A", "B", "C"]))

    jobs.run_daily_scan("scheduled", now=AFTER_CLOSE)

    assert scans == []  # no signals, no orders from yesterday's bar
    [rec] = written
    assert rec["status"] == "waiting" and rec["target_session"] == "2026-11-13"
    assert rec["waiting_reason"] == "today's prices have not arrived yet"
    # The page reads these counts on every record, so a waiting record carries zeros, not gaps.
    assert (rec["strategies_run"], rec["buys"], rec["executed"], rec["errors"]) == (0, 0, 0, 0)


def test_a_partial_scan_runs_and_names_the_missing_stocks(db_session, monkeypatch):
    written, scans = _wire(monkeypatch, db_session, _readiness("partial", ["BBB"]))

    jobs.run_daily_scan("scheduled", now=AFTER_CLOSE)

    assert scans == [1]
    marker, rec = written  # "running" is recorded before the strategies run
    assert marker["status"] == "running"
    assert rec["status"] == "partial" and rec["missing_symbols"] == ["BBB"] and rec["missing_count"] == 1
    assert rec["strategies_run"] == 1


def test_a_complete_scan_runs_and_says_so(db_session, monkeypatch):
    written, scans = _wire(monkeypatch, db_session, _readiness("complete"))

    jobs.run_daily_scan("scheduled", now=AFTER_CLOSE)

    assert scans == [1]
    assert [w["status"] for w in written] == ["running", "complete"]
    assert written[-1]["missing_count"] == 0
