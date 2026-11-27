"""#316 review: scans started by hand go through the same safeguards as the scheduled scan.

"Scan all" (API), the CLI `scan` command and "scan this strategy" used to run the strategies straight
away: on yesterday's bar while today's prices were missing, at the same time as the scheduled scan, or a
second time in a session that was already scanned (duplicate signals). Now they take the same claim, wait
for the same prices and respect the same once-per-session rule, and say in plain English why not.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time

import pytest
from sqlalchemy import text

from swing_trade_ml import cli
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import engine, scan_readiness
from swing_trade_ml.workers import jobs, scan_claim

API_KEY = {"X-API-Key": "test-api-key"}
FRIDAY = date(2026, 11, 13)


def at(hh: int, mm: int, day: date = FRIDAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


class World:
    """Stored scan record (in memory), prices in or not, a pinned clock, and what the engine was asked."""

    def __init__(self, monkeypatch, db_session):
        self.record: dict | None = None
        self.prices_in = False
        self.clock = at(16, 0)
        self.scans: list[str] = []
        self.held: list[str] = []

        @contextmanager
        def scope():
            yield db_session

        monkeypatch.setattr(jobs, "session_scope", scope)
        monkeypatch.setattr(jobs.heartbeat, "read_last_scan", lambda: self.record)
        monkeypatch.setattr(jobs.heartbeat, "write_last_scan", self._write)
        monkeypatch.setattr(jobs.scan_readiness, "check", self._check)
        monkeypatch.setattr(jobs.engine, "run_all_active", self._run_all)
        monkeypatch.setattr(jobs.engine, "run_strategy", self._run_one)
        monkeypatch.setattr(jobs.held_read, "score_tester_positions", lambda db: None)
        monkeypatch.setattr(jobs.held_read, "score_tracked_stocks", lambda db: None)
        monkeypatch.setattr(jobs.notifier, "send_sync", lambda *a, **k: True)
        monkeypatch.setattr(jobs, "_now_ist", lambda: self.clock)
        for name in jobs.FOLLOWUPS:
            monkeypatch.setitem(jobs.FOLLOWUP_BODIES, name, lambda name=name: self.held.append(name))

    def _write(self, data):
        self.record = dict(data)

    def _check(self, db, now=None):
        day = scan_readiness.target_session(now)
        if self.prices_in:
            return scan_readiness.Readiness(day, "complete", 2, 2, [])
        return scan_readiness.Readiness(
            day, "waiting", 2, 0, ["A", "B"], "the index has no 13 Nov candle yet"
        )

    def _run_all(self, db, interval="day"):
        assert self.record["status"] == "running"  # marked before any signal can be written
        self.scans.append("all")
        return engine.ScanResult(strategies_run=2, instruments_evaluated=10, signals_generated=3, buys=1)

    def _run_one(self, db, strategy, interval="day"):
        self.scans.append(strategy.name)
        return engine.ScanResult(strategies_run=1, instruments_evaluated=4, signals_generated=1)


@pytest.fixture()
def world(monkeypatch, db_session):
    return World(monkeypatch, db_session)


@contextmanager
def claim_held_elsewhere(db_session):
    holder = db_session.get_bind().engine.connect()
    assert holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": scan_claim.LOCK_KEY}).scalar()
    try:
        yield
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": scan_claim.LOCK_KEY})
        holder.close()


def _strategy(db_session, name: str, *, active: bool) -> Strategy:
    row = Strategy(name=name, strategy_type="ml_swing", mode="paper", is_active=active)
    db_session.add(row)
    db_session.flush()
    return row


# ------------------------------------------------------------------------------------- scan all --


def test_scan_all_waits_for_todays_prices(client, world):
    resp = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Waiting for today's prices: the index has no 13 Nov candle yet"
    assert world.scans == [] and world.record["status"] == "waiting"


def test_scan_all_runs_once_when_prices_are_in_and_refuses_a_second_time(client, world):
    world.prices_in = True
    resp = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["strategies_run"] == 2 and resp.json()["buys"] == 1
    assert world.record["status"] == "complete" and world.record["trigger"] == "manual"

    again = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert again.status_code == 409 and again.json()["detail"] == "Today's scan already ran"
    assert world.scans == ["all"]  # no duplicate signals

    assert jobs.run_daily_scan("retry", now=at(16, 5)) == "already_done"  # the scheduler agrees
    assert world.scans == ["all"]


def test_scan_all_refused_when_the_scheduled_scan_already_ran(client, world):
    world.prices_in = True
    world.clock = at(15, 45)
    assert jobs.run_daily_scan("scheduled", now=world.clock) == "complete"
    world.clock = at(16, 30)
    resp = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert resp.status_code == 409 and resp.json()["detail"] == "Today's scan already ran"
    assert world.scans == ["all"]


def test_scan_all_refused_while_another_scan_holds_the_claim(client, world, db_session):
    world.prices_in = True
    with claim_held_elsewhere(db_session):
        resp = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert resp.status_code == 409 and resp.json()["detail"] == "Another scan is running"
    assert world.scans == []


def test_scan_all_after_a_scan_cut_off_part_way_is_refused(client, world):
    world.prices_in = True
    world.record = {"status": "interrupted", "target_session": "2026-11-13", "attempts": 1}
    resp = client.post("/api/v1/strategies/scan-all", headers=API_KEY)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "The scan for 13 Nov stopped part-way; it is not re-run automatically"
    assert world.scans == []


def test_a_manual_scan_runs_the_jobs_held_for_it(world):
    world.prices_in = True
    world.record = {
        "status": "waiting",
        "target_session": "2026-11-13",
        "attempts": 3,
        "followups": {"brain_nightly": "deferred"},
    }
    scan = jobs.run_manual_scan()
    assert scan.ran and scan.outcome == "complete" and scan.result.strategies_run == 2
    assert world.held == ["brain_nightly"]


# -------------------------------------------------------------------------------------------- CLI --


def test_cli_scan_refused_returns_non_zero_and_says_why(world, capsys):
    code = cli.cmd_scan(argparse.Namespace(interval="day"))
    assert code != 0
    assert "Waiting for today's prices: the index has no 13 Nov candle yet" in capsys.readouterr().out
    assert world.scans == []


def test_cli_scan_runs_when_prices_are_in(world, capsys):
    world.prices_in = True
    assert cli.cmd_scan(argparse.Namespace(interval="day")) == 0
    assert "Scan complete" in capsys.readouterr().out
    assert cli.cmd_scan(argparse.Namespace(interval="day")) != 0  # once per session
    assert world.scans == ["all"]


# ------------------------------------------------------------------------------- scan one strategy --


def test_scan_one_waits_for_todays_prices(client, world, db_session):
    row = _strategy(db_session, "test-316-try-me", active=False)
    resp = client.post(f"/api/v1/strategies/{row.id}/scan", headers=API_KEY)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Waiting for today's prices: the index has no 13 Nov candle yet"
    assert world.scans == []


def test_scan_one_refused_for_an_active_strategy_after_the_session_scan(client, world, db_session):
    world.prices_in = True
    row = _strategy(db_session, "test-316-live-one", active=True)
    assert jobs.run_daily_scan("scheduled", now=at(15, 45)) == "complete"
    resp = client.post(f"/api/v1/strategies/{row.id}/scan", headers=API_KEY)
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("Active strategies are scanned by the daily scan")
    assert world.scans == ["all"]


def test_scan_one_refused_for_an_active_strategy_before_the_session_scan(client, world, db_session):
    # Run by hand at, say, 15:42, the daily scan would score it again and duplicate its signals.
    world.prices_in = True
    row = _strategy(db_session, "test-316-early", active=True)
    resp = client.post(f"/api/v1/strategies/{row.id}/scan", headers=API_KEY)
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith("Active strategies are scanned by the daily scan")
    assert world.scans == []


def test_scan_one_runs_an_inactive_strategy_once_prices_are_in(client, world, db_session):
    world.prices_in = True
    row = _strategy(db_session, "test-316-trial", active=False)
    assert jobs.run_daily_scan("scheduled", now=at(15, 45)) == "complete"
    resp = client.post(f"/api/v1/strategies/{row.id}/scan", headers=API_KEY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["strategies_run"] == 1
    assert world.scans == ["all", "test-316-trial"]
    assert world.record["status"] == "complete"  # testing a strategy never touches the session record


def test_scan_one_refused_while_another_scan_holds_the_claim(client, world, db_session):
    world.prices_in = True
    row = _strategy(db_session, "test-316-busy", active=False)
    with claim_held_elsewhere(db_session):
        resp = client.post(f"/api/v1/strategies/{row.id}/scan", headers=API_KEY)
    assert resp.status_code == 409 and resp.json()["detail"] == "Another scan is running"
    assert world.scans == []
