"""Validation phase: the evidence report, validate-week, the WHY integrity
check and the rescore-learning watchdog. (The golden day is its own file.)"""

from __future__ import annotations

import argparse
import importlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from swing_trade_ml import cli
from swing_trade_ml.brain import validation
from swing_trade_ml.brain.replay_week import run_replay_week
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.workers import jobs

DAY = date(2026, 9, 25)
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def replayed(db_session):
    inst = Instrument(
        instrument_token=994001, tradingsymbol="VALID1", exchange="NSE", is_watchlisted=True, is_active=True
    )
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=AS_OF - timedelta(days=1),
            open=100.0,
            high=100.0,
            low=100.0,
            close=100.0,
            volume=1000,
        )
    )
    db_session.commit()
    return run_replay_week(db_session, start=DAY, end=DAY, symbols=["VALID1"])


def _report(db, results, compare=None):
    return validation.build_report(
        db, results, book="paper", start=DAY, end=DAY, compare_snapshot=compare, now=AS_OF
    )


# --- 1. the report ---------------------------------------------------------


def test_report_holds_runs_manifest_counts_checks_and_compare(db_session, replayed):
    report = _report(db_session, replayed, {"brain_finished": 0, "needed": 30})
    data = json.loads(json.dumps(report.to_dict(), default=str))
    assert data["schema_version"] == validation.SCHEMA_VERSION
    assert data["run_ids"] == [replayed[0].run_id]
    day = data["days"][0]
    assert day["counts"] == {"WAIT": 1}
    assert day["banner"] == replayed[0].banner
    assert "feature_set_version" in day["data_manifest"]
    assert day["constitution"]["every_stock_has_reason"] is True
    assert data["constitution_ok"] is True
    assert data["compare"] == {"brain_finished": 0, "needed": 30}
    assert any("Zero finished" in n for n in data["notes"])
    assert len(day["fingerprint"]) == 64


def test_constitution_checks_catch_a_trade_that_should_not_exist():
    run = SimpleNamespace(trace=[], banner_mode="NO_NEW_TRADES", quality={"stale": ["AAA"]})
    decisions = [
        SimpleNamespace(
            symbol="AAA", word="TRADE", reasons=["x"], downgraded_from=None, downgrade_reason=None
        ),
        SimpleNamespace(
            symbol="BBB", word="BOGUS", reasons=[], downgraded_from="TRADE", downgrade_reason=None
        ),
    ]
    checks = validation.constitution_checks(run, decisions, universe_size=3)
    assert not checks.ok
    assert not checks.no_trade_without_risk_gate
    assert not checks.no_trade_when_banner_blocks
    assert not checks.stale_data_never_trade
    assert not checks.vocabulary_valid
    assert not checks.every_stock_has_reason
    assert not checks.every_stock_decided
    assert not checks.downgrades_have_reason


def test_summary_is_plain_and_flags_broken_rules(db_session, replayed):
    report = _report(db_session, replayed)
    text = validation.plain_summary(report)
    assert "Safety rules: all held" in text
    report.days[0].constitution.problems.append("boom")
    assert "BROKEN" in validation.plain_summary(report)


# --- 2. validate-week ------------------------------------------------------


def test_validate_week_writes_the_report_file(db_session, replayed, tmp_path, capsys):
    out = tmp_path / "sub" / "week.json"
    args = argparse.Namespace(book="paper", out=str(out))
    code = cli._write_validation_report(db_session, args, replayed, DAY, DAY)
    assert code == 0
    assert json.loads(out.read_text("utf-8"))["days"][0]["run_id"] == replayed[0].run_id
    printed = capsys.readouterr().out
    assert "Validation: 1 trading day(s)" in printed and str(out) in printed


def test_validate_week_is_wired_into_the_parser():
    ns = cli.build_parser().parse_args(["brain", "validate-week", "--days", "3", "--out", "x.json"])
    assert (ns.brain_command, ns.days, ns.out, ns.func) == ("validate-week", 3, "x.json", cli.cmd_brain)


def test_default_report_path_is_under_evidence_dir(db_session, replayed, tmp_path):
    path = validation.default_report_path(_report(db_session, replayed), tmp_path)
    assert path == tmp_path / "validation_week_2026-09-25_2026-09-25.json"


# --- 4. WHY integrity ------------------------------------------------------


def test_why_agrees_with_the_stored_nightly_decision(db_session, replayed):
    result = validation.check_why_integrity(db_session, "VALID1")
    assert result.ok, result.problems
    assert result.stored_run_id == replayed[0].run_id
    assert result.stored_word == result.why_word == "WAIT"


def _stored(word="WAIT"):
    return SimpleNamespace(word=word)


def test_why_check_flags_a_different_word_an_empty_trace_and_invented_modules():
    trace = [{"module_id": "M07"}, {"module_id": "fallback"}]
    ok = validation.compare_why_to_stored(
        "x", {"decision": {"word": "WAIT"}, "trace": trace}, _stored(), "r1"
    )
    assert ok.ok

    other = validation.compare_why_to_stored(
        "x", {"decision": {"word": "TRADE"}, "trace": trace}, _stored(), "r1"
    )
    assert not other.ok and "TRADE" in other.problems[0]

    empty = validation.compare_why_to_stored(
        "x", {"decision": {"word": "WAIT"}, "trace": []}, _stored(), "r1"
    )
    assert not empty.ok

    fake = validation.compare_why_to_stored(
        "x", {"decision": {"word": "WAIT"}, "trace": [{"module_id": "M99"}]}, _stored(), "r1"
    )
    assert not fake.ok and "M99" in fake.problems[0]

    nothing = validation.compare_why_to_stored("x", {"decision": None, "trace": trace}, None, None)
    assert len(nothing.problems) == 2


# --- 5. rescore watchdog ---------------------------------------------------


@pytest.fixture()
def alerts(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(cli, "log", cli.log)  # keep the real logger
    from swing_trade_ml.notifications import notifier

    monkeypatch.setattr(notifier, "send_sync", lambda text, event="system": sent.append(text) or True)
    return sent


def _patch_learning(monkeypatch, fn):
    # `m09_learn.learn` is shadowed on the package, so reach the module itself.
    monkeypatch.setattr(
        importlib.import_module("swing_trade_ml.brain.modules.m09_learn.learn"), "run_learning", fn
    )


def _boom(*_a, **_k):
    raise RuntimeError("scoring blew up")


@pytest.mark.parametrize("command", ["rescore-learning", "learn"])
def test_failed_rescore_exits_nonzero_and_alerts_once(monkeypatch, alerts, capsys, command):
    _patch_learning(monkeypatch, _boom)
    args = argparse.Namespace(brain_command=command, since=None)
    assert cli.cmd_brain(args) == 1
    assert len(alerts) == 1 and "scoring blew up" in alerts[0] and command in alerts[0]
    assert "scoring blew up" in capsys.readouterr().err


def test_successful_rescore_exits_zero_and_sends_no_alert(monkeypatch, alerts):
    report = {
        "n_scored": 0, "n_new": 0, "new_proposals": [], "calibration": [], "by_word": [],
        "by_week": [], "failure_patterns": [], "drift_lines": [], "drift": [],
    }  # fmt: skip
    _patch_learning(monkeypatch, lambda db, since=None: report)
    monkeypatch.setattr(cli, "_print_learning_summary", lambda *a, **k: None)
    assert cli.cmd_brain(argparse.Namespace(brain_command="rescore-learning", since=None)) == 0
    assert alerts == []


def test_weekly_learning_job_logs_and_alerts_on_failure(monkeypatch, alerts):
    _patch_learning(monkeypatch, _boom)
    jobs.job_brain_learn()  # never raises
    assert len(alerts) == 1 and "brain_learn" in alerts[0]
