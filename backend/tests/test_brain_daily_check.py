"""The daily brain check: after every trading day's nightly run, store one record of the brain's health,
its wiring (dropped modules, intraday too) and the trial so far, so any day can be looked up later."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from brain_m18_fixtures import DAY as M18_DAY
from brain_m18_fixtures import at, brain_strategy, candle, decision, instrument, no_broker
from brain_m18_fixtures import run as m18_run
from swing_trade_ml.db.models.brain import BrainDailyCheck, BrainRun
from swing_trade_ml.db.models.trading import Signal
from swing_trade_ml.services import brain_daily_check as daily
from swing_trade_ml.services import engine, execution
from swing_trade_ml.services.brain_golive import shadow
from swing_trade_ml.services.risk import RiskDecision
from swing_trade_ml.strategies import brain as brain_mod
from swing_trade_ml.workers import jobs

API_KEY = {"X-API-Key": "test-api-key"}
DAY = date(2026, 10, 14)  # a Wednesday, a trading day
NOW = datetime(2026, 10, 14, 10, 50, tzinfo=UTC)  # 16:20 IST


def _run(db, run_id, kind, trace, modules, started=NOW):
    db.add(
        BrainRun(
            id=run_id,
            kind=kind,
            status="done",
            live=True,
            book="paper",
            as_of=started,
            started_at=started,
            modules=modules,
            trace=trace,
            banner_mode="DEFENSIVE",
            ms=360000,
        )
    )
    db.flush()


def _ev(module_id, status, reason=""):
    return {"step": "x", "module_id": module_id, "status": status, "reason": reason, "ms": 1, "version": "1"}


def test_compute_has_checks_run_summary_and_trial(db_session, tmp_path):
    _run(db_session, "dc-n", "nightly", [_ev("M02", "used")], {"M02": "on"})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    assert r["day"] == DAY.isoformat() and r["status"] in ("ok", "check")
    assert any(c["name"] == "Modules ran" for c in r["checks"])
    assert r["run"]["run_id"] == "dc-n" and r["run"]["modules_dropped"] == []
    assert r["trial"]["start"] == "2026-10-14" and "gate" in r["trial"]


def test_intraday_drops_today_make_the_day_a_check(db_session, tmp_path):
    _run(db_session, "dc-n2", "nightly", [_ev("M02", "used")], {"M02": "on"})
    _run(db_session, "dc-i1", "intraday", [_ev("M08", "fallback", "too slow: 1.6 s")], {"M08": "on"})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    assert r["status"] == "check"
    assert {"module": "M08", "reason": "too slow: 1.6 s", "runs": 1} in r["intraday"]["dropped"]


def test_store_keeps_one_row_per_day(db_session, tmp_path):
    _run(db_session, "dc-n3", "nightly", [], {})
    first = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    daily.store(db_session, first)
    daily.store(db_session, {**first, "status": "check"})
    rows = db_session.query(BrainDailyCheck).filter(BrainDailyCheck.day == DAY).all()
    assert len(rows) == 1 and rows[0].status == "check"


def test_message_only_when_something_is_wrong():
    ok = {"day": "2026-10-14", "status": "ok", "checks": [], "intraday": {"dropped": []}}
    assert daily.message_if_problem(ok) is None
    bad = {
        "day": "2026-10-14",
        "status": "check",
        "checks": [{"name": "Modules ran", "ok": False, "detail": "M02 dropped"}],
        "intraday": {"dropped": [{"module": "M08", "reason": "too slow", "runs": 3}]},
    }
    text = daily.message_if_problem(bad)
    assert "Modules ran" in text and "M08" in text


def test_job_skips_days_without_trading(db_session, monkeypatch):
    monkeypatch.setattr(jobs, "_ist_today", lambda: date(2026, 10, 17))  # a Saturday
    called = []
    monkeypatch.setattr(daily, "compute", lambda *a, **k: called.append(1))
    jobs.job_brain_daily_check()
    assert called == []


def test_job_never_raises(monkeypatch):
    monkeypatch.setattr(jobs, "_ist_today", lambda: DAY)
    monkeypatch.setattr(daily, "compute", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    jobs.job_brain_daily_check()  # must not raise


def test_endpoints_list_and_latest(client, db_session, tmp_path):
    _run(db_session, "dc-n4", "nightly", [], {})
    daily.store(db_session, daily.compute(db_session, NOW, backup_dir=str(tmp_path)))
    latest = client.get("/api/v1/brain/daily-checks/latest", headers=API_KEY)
    assert latest.status_code == 200 and latest.json()["day"] == "2026-10-14"
    listed = client.get("/api/v1/brain/daily-checks?days=30", headers=API_KEY).json()
    assert [r["day"] for r in listed] == ["2026-10-14"]


# --- tv3: the daily trial-health checklist -------------------------------------------------------------


@pytest.fixture()
def safe_scan(monkeypatch):
    no_broker(monkeypatch)
    monkeypatch.setattr(brain_mod, "today_ist", lambda: M18_DAY)
    monkeypatch.setattr(engine, "_buy_slot_budget", lambda db, strategy, mode: 5)
    monkeypatch.setattr(execution, "portfolio_value_and_cash", lambda db, mode: (1_000_000.0, 1_000_000.0))
    monkeypatch.setattr(execution.risk, "check_entry", lambda **kw: RiskDecision(True, 10))


def _idea_day(db, symbol, token, run_id):
    inst = instrument(db, symbol, token)
    candle(db, inst, M18_DAY, 101.0)
    brain_strategy(db, symbols=[symbol])
    m18_run(db, run_id)
    decision(db, run_id, symbol, "TRADE")


def test_an_idea_that_never_reaches_the_counter_fails(db_session):
    _idea_day(db_session, "TVTHREEA", 930001, "tv3-a")  # the brain said TRADE; the strategy never ran
    c = daily.check_ideas_reached_counter(db_session, M18_DAY)
    assert not c["ok"] and c["level"] == "fail" and "none reached the practice record" in c["detail"]


def test_a_recorded_idea_passes_the_counter_check(db_session, safe_scan):
    _idea_day(db_session, "TVTHREEB", 930002, "tv3-b")
    shadow.run_brain_strategy(db_session)
    for sig in db_session.query(Signal).all():
        sig.generated_at = at(M18_DAY)
    db_session.flush()
    c = daily.check_ideas_reached_counter(db_session, M18_DAY)
    assert c["ok"] and c["level"] == "ok" and c["detail"].startswith("1 of 1")


def test_a_zero_idea_day_is_shown_not_failed(db_session):
    m18_run(db_session, "tv3-c")
    decision(db_session, "tv3-c", "TVTHREEC", "WAIT")
    c = daily.check_ideas_reached_counter(db_session, M18_DAY)
    assert c["ok"] and c["level"] == "info" and "Zero-idea day" in c["detail"]


def test_no_nightly_today_is_left_to_the_nightly_check(db_session):
    assert daily.check_ideas_reached_counter(db_session, M18_DAY) is None


@pytest.mark.parametrize(
    ("runs", "failed", "ok", "level"),
    [(0, 0, False, "fail"), (20, 2, False, "fail"), (5, 0, False, "warn"), (26, 0, True, "ok")],
)
def test_intraday_runs_missing_or_failed(runs, failed, ok, level):
    c = daily.check_intraday_runs({"runs": runs, "failed": failed, "dropped": []})
    assert (c["ok"], c["level"]) == (ok, level)


def test_stale_stocks_are_named_even_when_the_market_counts_as_fresh(db_session):
    stale = [f"S{i}" for i in range(7)]
    r = BrainRun(
        id="tv3-s",
        kind="nightly",
        status="done",
        live=True,
        book="paper",
        as_of=NOW,
        started_at=NOW,
        quality={"overall": {"fresh": True}, "stale": stale},
    )
    c = daily.check_stale_stocks(r)
    assert not c["ok"] and c["level"] == "warn" and "7 stock(s)" in c["detail"] and "2 more" in c["detail"]
    r.quality = {"overall": {"fresh": True}, "stale": []}
    assert daily.check_stale_stocks(r)["ok"]
    assert daily.check_stale_stocks(None) is None


def test_a_full_day_with_no_intraday_runs_is_a_check_with_a_message(db_session, tmp_path):
    _run(db_session, "dc-n5", "nightly", [_ev("M02", "used")], {"M02": "on"})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    names = {c["name"]: c for c in r["checks"]}
    assert not names["Intraday runs"]["ok"]
    assert r["status"] == "check" and "Intraday runs" in daily.message_if_problem(r)


def _model(name, kind, target, days, stop=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        name=name,
        label_kind=kind,
        target_return_pct=target,
        prediction_horizon_days=days,
        stop_return_pct=stop,
    )


def test_endpoint_models_do_not_match_the_plan_and_are_named():
    c = daily.check_model_question([_model("swing_classifier", "endpoint", 0.02, 5)])
    assert not c["ok"] and c["level"] == "info"
    assert "NOT matched" in c["detail"] and "swing_classifier" in c["detail"] and "+2%" in c["detail"]


def test_barrier_models_with_the_plan_numbers_match():
    c = daily.check_model_question([_model("swing_classifier_barrier", "barrier", 0.08, 15, 0.04)])
    assert c["ok"]
    assert not daily.check_model_question([_model("x", "barrier", 0.08, 15, 0.05)])["ok"]


def test_no_live_model_is_shown_not_failed():
    c = daily.check_model_question([])
    assert not c["ok"] and c["level"] == "info"


def test_the_model_check_never_makes_the_day_a_problem(db_session, tmp_path):
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    names = {c["name"]: c for c in r["checks"]}
    assert names["Score matches the trade plan"]["level"] == "info"
    assert "Score matches the trade plan" not in (daily.message_if_problem(r) or "")
