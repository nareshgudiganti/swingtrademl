# ruff: noqa: E501, N812, F811 (fixtures are imported by name; long test sentences)
"""h05 daily job: disabled by default, one record per session, missed sessions reported once, outcomes matured."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.brain.lanes import h05_job, h05_report, h05_service
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal
from test_h05_service import (
    SESSIONS,
    SIGNAL,
    add_candle,
    add_stock,
    after,
    future,
    lane,  # noqa: F401  (fixture)
    make_run,
)

EVENING = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)  # 18:30 IST on the signal day (a Wednesday), after the close
NEXT_MORNING_8 = datetime(2026, 10, 15, 2, 30, tzinfo=UTC)  # 08:00 IST: before the 09:00 cut-off
NEXT_MORNING_10 = datetime(2026, 10, 15, 4, 30, tzinfo=UTC)  # 10:00 IST: after the cut-off
GROUPS = {"LRG1": "large", "MID1": "mid", "SML1": "small"}


def _world(db, lane, stocks=GROUPS):
    insts = {}
    for i, s in enumerate(stocks):
        insts[s] = add_stock(db, s)
        lane.scores[s] = 0.9 - i / 10
    run = make_run(db, dict(stocks))
    return run, insts


def _count(db, model, run):
    return db.scalar(select(func.count()).select_from(model).where(model.run_id == run.id))


def _events(db, run, kind):
    return list(db.scalars(select(H05Event).where(H05Event.run_id == run.id, H05Event.kind == kind)))


# ----------------------------------------------------------------- disabled by default


def test_the_job_is_disabled_by_default_and_writes_nothing(db_session):
    out = h05_job.run_daily(db_session, EVENING)
    assert out["state"] == "disabled" and "disabled" in out["reason"]
    assert db_session.scalar(select(func.count()).select_from(H05Run)) == 0


def test_the_scheduler_gets_the_job_only_when_enabled_and_accepted(monkeypatch):
    def with_settings(enabled, hash_):
        monkeypatch.setattr(
            P, "H05Settings", lambda: SimpleNamespace(ENABLED=enabled, ACCEPTED_PROTOCOL_HASH=hash_)
        )
        sched = BackgroundScheduler()
        return h05_job.register(sched), [j.id for j in sched.get_jobs()], sched

    assert with_settings(False, "")[:2] == (False, [])
    assert with_settings(True, "")[:2] == (False, [])  # enabled, protocol not accepted
    assert with_settings(False, P.protocol_hash())[:2] == (False, [])  # accepted, but switched off
    assert with_settings(True, "0" * 64)[:2] == (False, [])  # a hash of another protocol
    added, ids, sched = with_settings(True, P.protocol_hash())
    assert added is True and ids == ["h05_daily"]
    trigger = sched.get_job("h05_daily").trigger
    assert "mon-sat" in str(trigger) and str(trigger.timezone) == "Asia/Kolkata"


def _settings(monkeypatch, enabled, hash_):
    monkeypatch.setattr(P, "H05Settings", lambda: SimpleNamespace(ENABLED=enabled, ACCEPTED_PROTOCOL_HASH=hash_))


def test_disabled_startup_adds_no_job_and_imports_nothing_from_the_lane():
    """Run in a clean interpreter with the default (disabled) settings, as the worker starts."""
    import subprocess
    import sys

    code = "; ".join(
        [
            "import sys",
            "from apscheduler.schedulers.background import BackgroundScheduler",
            "import importlib; w = importlib.import_module('swing_trade_ml.workers.scheduler')",
            "t = BackgroundScheduler()",
            "assert w.add_h05_job(t) is False and t.get_jobs() == []",
            "assert 'swing_trade_ml.brain.lanes.h05_job' not in sys.modules",
            "assert 'swing_trade_ml.brain.lanes.h05_service' not in sys.modules",
            "print('clean')",
        ]
    )
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("LANE_H05_")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False)
    assert out.returncode == 0 and "clean" in out.stdout, out.stderr[-600:]


def test_the_scheduler_wiring_registers_only_when_enabled_and_accepted_and_never_raises(monkeypatch):
    import importlib

    worker = importlib.import_module("swing_trade_ml.workers.scheduler")

    def run(enabled, hash_):
        _settings(monkeypatch, enabled, hash_)
        sched = BackgroundScheduler()
        return worker.add_h05_job(sched), [j.id for j in sched.get_jobs()]

    assert run(False, "") == (False, [])
    assert run(False, P.protocol_hash()) == (False, [])
    assert run(True, "") == (False, [])  # enabled, hash not accepted
    assert run(True, "1" * 64) == (False, [])
    assert run(True, P.protocol_hash()) == (True, ["h05_daily"])
    monkeypatch.setattr(h05_job, "register", lambda target: 1 / 0)
    assert run(True, P.protocol_hash()) == (False, [])  # a failure is logged, startup goes on


# ----------------------------------------------------------------- recording and duplicate prevention


def test_the_latest_closed_session_is_recorded_once_and_a_second_pass_adds_nothing(db_session, lane):
    run, _ = _world(db_session, lane)
    first = h05_job.run_daily(db_session, EVENING)
    assert first["actions"][0]["state"] == "recorded"
    assert first["actions"][0]["selected"] == {"large": ["LRG1"], "mid": ["MID1"], "small": ["SML1"]}
    signals, group_days = _count(db_session, H05Signal, run), _count(db_session, H05GroupDay, run)
    assert (signals, group_days) == (3, 3)
    second = h05_job.run_daily(db_session, EVENING.replace(hour=15))
    assert second["actions"][0]["state"] == "already_recorded"
    assert (_count(db_session, H05Signal, run), _count(db_session, H05GroupDay, run)) == (signals, group_days)


def test_a_second_writer_is_stopped_by_the_unique_keys(db_session, lane, monkeypatch):
    run, _ = _world(db_session, lane)

    def boom(*a, **k):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(h05_service, "score_day", boom)
    out = h05_job.run_daily(db_session, EVENING)
    assert out["actions"][0]["state"] == "already_recorded"
    assert _count(db_session, H05Signal, run) == 0


def test_another_pass_holding_the_lock_makes_this_one_stand_aside(db_session, lane):
    _world(db_session, lane)
    other = db_session.get_bind().engine.connect()
    try:
        other.execute(text("select pg_advisory_lock(:k)"), {"k": h05_job.LOCK_KEY})
        out = h05_job.run_daily(db_session, EVENING)
        assert out["state"] == "busy"
    finally:
        other.execute(text("select pg_advisory_unlock(:k)"), {"k": h05_job.LOCK_KEY})
        other.close()


def test_without_a_run_the_job_never_starts_one(db_session, lane):
    assert h05_job.run_daily(db_session, EVENING)["state"] == "no_run"
    assert db_session.scalar(select(func.count()).select_from(H05Run)) == 0


# ----------------------------------------------------------------- waiting for data, then the cut-off


def test_incomplete_data_waits_and_is_recorded_once_the_data_arrives(db_session, lane):
    run, _ = _world(db_session, lane)
    # two of the three stocks have no candle on the signal session yet (33% < 90%)
    for sym in ("MID1", "SML1"):
        inst = db_session.scalar(select(h05_service.Instrument).where(h05_service.Instrument.tradingsymbol == sym))
        db_session.execute(
            text("delete from candles where instrument_id = :i and ts = :t"),
            {"i": inst.id, "t": datetime(2026, 10, 14, tzinfo=h05_service.IST)},
        )
    out = h05_job.run_daily(db_session, EVENING)
    assert out["actions"][0]["state"] == "waiting_for_data" and out["actions"][0]["data"]["with_candle"] == 1
    h05_job.run_daily(db_session, EVENING.replace(hour=15))
    assert len(_events(db_session, run, "data_not_ready")) == 1  # said once, not every pass
    assert _count(db_session, H05Signal, run) == 0
    for sym in ("MID1", "SML1"):
        inst = db_session.scalar(select(h05_service.Instrument).where(h05_service.Instrument.tradingsymbol == sym))
        add_candle(db_session, inst, SIGNAL, (100, 100, 100, 100))
    done = h05_job.run_daily(db_session, NEXT_MORNING_8)
    assert done["actions"][0]["state"] == "recorded"  # still before the 09:00 cut-off


def test_after_the_cutoff_an_unrecorded_session_is_missed_reported_once_and_never_scored_late(db_session, lane):
    run, _ = _world(db_session, lane)
    run.start_day = SIGNAL
    db_session.flush()
    out = h05_job.run_daily(db_session, NEXT_MORNING_10)
    assert out["actions"][0]["newly_missed_sessions"] == [str(SIGNAL)]
    assert _count(db_session, H05Signal, run) == 0  # not scored late
    again = h05_job.run_daily(db_session, NEXT_MORNING_10.replace(hour=6))
    assert again["actions"][0]["newly_missed_sessions"] == []
    missed = _events(db_session, run, "missed_session")
    assert len(missed) == 1 and "did not run" in missed[0].detail and "not extended" in missed[0].detail


def test_a_lane_stop_is_retried_until_the_cutoff_then_reported_as_the_reason_for_the_miss(
    db_session, lane, monkeypatch
):
    from swing_trade_ml.brain.lanes import h05_protocol

    run, _ = _world(db_session, lane)
    run.start_day = SIGNAL
    db_session.flush()

    def broken(db):
        raise h05_protocol.ProtocolError("model 16 sha256 differs from the frozen one")

    monkeypatch.setattr(h05_service, "verify_models", broken)
    out = h05_job.run_daily(db_session, EVENING)
    assert out["actions"][0]["state"] == "lane_stopped"
    later = h05_job.run_daily(db_session, NEXT_MORNING_10)
    assert later["actions"][0]["newly_missed_sessions"] == [str(SIGNAL)]
    detail = _events(db_session, run, "missed_session")[0].detail
    assert "lane stopped by a frozen-model check" in detail and "model 16" in detail
    assert _count(db_session, H05Signal, run) == 0


def test_every_unrecorded_session_of_the_window_is_reported_with_the_report_listing_them(db_session, lane):
    run, _ = _world(db_session, lane)
    run.start_day = date(2026, 10, 12)  # Monday; Tuesday and Wednesday follow
    db_session.flush()
    h05_job.run_daily(db_session, EVENING)  # Wednesday recorded; Monday and Tuesday were never recorded
    missed = sorted(e.signal_day for e in _events(db_session, run, "missed_session"))
    assert missed == [date(2026, 10, 12), date(2026, 10, 13)]
    report = h05_report.build_report(db_session, now=EVENING)
    rep = report["runs"][0]
    assert rep["days_missed"] == ["2026-10-12", "2026-10-13"] and len(rep["missed_sessions"]) == 2
    assert "MISSED 2026-10-12" in h05_report.render_markdown(report)


# ----------------------------------------------------------------- maturation and closing


def test_outcomes_mature_on_later_passes_and_the_run_closes_after_its_last_session(db_session, lane):
    run, insts = _world(db_session, lane)
    run.start_day = run.end_day = SIGNAL
    db_session.flush()
    h05_job.run_daily(db_session, EVENING)
    assert _count(db_session, H05Signal, run) == 3
    assert db_session.scalar(select(H05Run.status).where(H05Run.id == run.id)) == "closed"  # one-session run
    assert len(_events(db_session, run, "run_closed")) == 1
    assert {s.label_status for s in db_session.scalars(select(H05Signal))} == {"pending"}

    for inst in insts.values():
        future(db_session, inst, n1=(100, 103, 100, 102), n5=(103, 103, 103, 103))
    later = datetime(after(SIGNAL, 6).year, after(SIGNAL, 6).month, after(SIGNAL, 6).day, 13, tzinfo=UTC)
    out = h05_job.run_daily(db_session, later)
    assert out["state"] == "no_active_run" and "run 2 is not started" in out["reason"]
    assert out["maturation"][1] == {"pending_before": 3, "pending_after": 0, "label": 3, "trade": 3}
    statuses = {(s.label_status, s.trade_status) for s in db_session.scalars(select(H05Signal))}
    assert statuses == {("evaluated", "target")}
    # a matured outcome is final: another pass changes nothing
    assert h05_job.run_daily(db_session, later)["maturation"][1]["pending_before"] == 0


def test_a_run_is_not_closed_while_its_last_session_can_still_be_recorded(db_session, lane):
    run, _ = _world(db_session, lane)
    run.end_day = SIGNAL
    db_session.flush()
    # data incomplete at 18:30 on the last session: waiting, so the run stays open
    for sym in ("MID1", "SML1"):
        inst = db_session.scalar(select(h05_service.Instrument).where(h05_service.Instrument.tradingsymbol == sym))
        db_session.execute(
            text("delete from candles where instrument_id = :i and ts = :t"),
            {"i": inst.id, "t": datetime(2026, 10, 14, tzinfo=h05_service.IST)},
        )
    h05_job.run_daily(db_session, EVENING)
    assert db_session.scalar(select(H05Run.status).where(H05Run.id == run.id)) == "active"
    h05_job.run_daily(db_session, NEXT_MORNING_10)  # cut-off passed: missed, then the run closes
    assert db_session.scalar(select(H05Run.status).where(H05Run.id == run.id)) == "closed"
    assert len(_events(db_session, run, "missed_session")) >= 1


def test_the_job_id_is_stable():
    assert h05_job.JOB_ID == "h05_daily"


def test_collection_ends_after_the_last_session_but_the_verdict_waits_for_every_outcome(db_session, lane, monkeypatch):
    """Item: a run closes for COLLECTION after its final signal session; FINALISATION waits for the five-session
    outcomes. Unresolved trades and not-evaluated labels are final states that never block it."""
    monkeypatch.setattr(P, "accepted", lambda settings=None: True)
    run, insts = _world(db_session, lane)
    run.start_day = run.end_day = SIGNAL
    db_session.flush()
    h05_job.run_daily(db_session, EVENING)
    assert db_session.scalar(select(H05Run.status).where(H05Run.id == run.id)) == "closed"  # collection ended
    waiting = h05_report.build_report(db_session, now=EVENING)["verdict"]["large"]["runs"][1]
    assert waiting["final"] is False and "1 outcomes not matured" in waiting["why"]  # per group: one stock each

    # the exchange calendar only has sessions that happened: four of the five later sessions so far
    known = {"through": after(SIGNAL, 4)}
    monkeypatch.setattr(
        h05_service, "market_sessions", lambda db: [d for d in SESSIONS if d <= known["through"]]
    )
    for k in range(1, 5):
        for inst in insts.values():
            add_candle(db_session, inst, after(SIGNAL, k), (100, 100, 100, 100))
    after4 = datetime.combine(after(SIGNAL, 4), datetime.min.time(), tzinfo=UTC).replace(hour=13)
    out = h05_job.run_daily(db_session, after4)
    assert out["maturation"][1]["pending_after"] == 3

    # session 5 arrives for two stocks; MID1 has no candle on session 5 -> its label is NOT EVALUATED, its trade UNRESOLVED
    for sym in ("LRG1", "SML1"):
        add_candle(db_session, insts[sym], after(SIGNAL, 5), (100, 100, 100, 100))
    add_candle(db_session, insts["MID1"], after(SIGNAL, 6), (100, 100, 100, 100))
    day5 = after(SIGNAL, 6)
    known["through"] = day5
    out = h05_job.run_daily(db_session, datetime.combine(day5, datetime.min.time(), tzinfo=UTC).replace(hour=13))
    assert out["maturation"][1]["pending_after"] == 0  # nothing waits any more
    mid = db_session.scalar(select(h05_service.H05Signal).where(h05_service.H05Signal.symbol == "MID1"))
    assert (mid.label_status, mid.trade_status) == ("not_evaluated", "unresolved")
    final = h05_report.build_report(db_session, now=EVENING)
    assert final["verdict"]["large"]["runs"][1]["final"] is True  # finalised despite the unresolved outcome
    assert final["runs"][0]["groups"]["mid"]["shadow_trade"]["baseline_every_eligible_stock"]["unresolved"] == 1
