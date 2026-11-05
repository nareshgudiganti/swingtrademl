# ruff: noqa: E501, E402, F811, I001, N812 (long test sentences; S is the service alias; `db` is an imported fixture;
# the ten_day import must come first because replay_scoring has an import cycle that only resolves from there)
"""Shadow-lane daily job: guarded scheduler wiring, one failing slot never stops the others, no overlapping runs.

These are software tests of plumbing. They say nothing about whether any model is good."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

import swing_trade_ml.brain.ten_day  # noqa: F401  (first: replay_scoring has an import cycle that only resolves from here)

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.lane_shadow import LanePick
from swing_trade_ml.shadow_lanes import lane_job
from swing_trade_ml.shadow_lanes import lane_service as S

sched_mod = importlib.import_module(
    "swing_trade_ml.workers.scheduler"
)  # the package also exports a `scheduler` object

from test_lane_shadow_service import db, fake_scorer, instrument, ml_model  # noqa: F401  (db is a fixture)

NOW = datetime(2026, 12, 8, 14, 0, tzinfo=UTC)
LARGE = [f"L{i}" for i in range(5)]
MID = [f"M{i}" for i in range(5)]


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, *a, **k):
        self.jobs.append((a, k))


# ---------------------------------------------------------------- scheduler wiring


def test_wiring_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LANE_SHADOW_ENABLED", False)
    called = []
    monkeypatch.setattr(lane_job, "register", lambda t: called.append(t) or True)
    s = FakeScheduler()
    assert sched_mod.add_lane_job(s) is False
    assert s.jobs == [] and called == []


def test_wiring_registers_one_job_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "LANE_SHADOW_ENABLED", True)
    s = FakeScheduler()
    assert sched_mod.add_lane_job(s) is True
    assert len(s.jobs) == 1 and s.jobs[0][1]["id"] == lane_job.JOB_ID and s.jobs[0][1]["max_instances"] == 1


def test_wiring_never_raises_even_if_registration_breaks(monkeypatch):
    monkeypatch.setattr(settings, "LANE_SHADOW_ENABLED", True)

    def boom(_):
        raise RuntimeError("scheduler refused")

    monkeypatch.setattr(lane_job, "register", boom)
    assert sched_mod.add_lane_job(FakeScheduler()) is False


def test_the_setting_still_defaults_to_off():
    assert settings.__class__.model_fields["LANE_SHADOW_ENABLED"].default is False


# ---------------------------------------------------------------- per-slot isolation


def _setup(db, monkeypatch):
    m10 = ml_model(db, name="td_h10_a", horizon=10)
    m15 = ml_model(db, name="sl1_S1_a", horizon=15)
    mmid = ml_model(db, name="sl1_S1M_a", horizon=15)
    for m in (m10, m15, mmid):
        m.model_role = "final"  # a lane scores only a frozen final model
    for sym in LARGE + MID:
        instrument(db, sym)
    monkeypatch.setattr(
        settings,
        "LANE_SHADOW_MODELS",
        json.dumps({"10d-large": m10.id, "15d-large": m15.id, "15d-midcap": mmid.id}),
    )
    monkeypatch.setattr(
        lane_job.lane_universe,
        "load_universe",
        lambda: {"large": LARGE, "mid": MID, "sha256": "abc"},
    )
    scores = {s: 0.5 + i / 100 for i, s in enumerate(LARGE + MID)}
    real = S.record_day

    def record_with_fake_scorer(db_, model, slot, groups, signal_day, moment, **kw):
        return real(db_, model, slot, groups, signal_day, moment, scorer=fake_scorer(scores), **kw)

    return record_with_fake_scorer


def _slots_with_picks(db) -> set[str]:
    return set(db.scalars(select(LanePick.slot_key).distinct()))


@pytest.mark.parametrize("failing", ["generic", "database"])
def test_one_slot_failing_does_not_stop_the_others(db, monkeypatch, failing):
    ok = _setup(db, monkeypatch)

    def flaky(db_, model, slot, groups, signal_day, moment, **kw):
        if slot == "10d-large":
            if failing == "generic":
                raise RuntimeError("scoring blew up")
            db_.execute(text("SELECT * FROM table_that_does_not_exist"))  # a real database error
        return ok(db_, model, slot, groups, signal_day, moment, **kw)

    monkeypatch.setattr(lane_job.S, "record_day", flaky)
    out = lane_job.run_daily(db, now=NOW)
    assert out["slots"]["10d-large"].startswith("error:")
    assert out["slots"]["15d-large"]["recorded"] == 5 and out["slots"]["15d-midcap"]["recorded"] == 5
    assert _slots_with_picks(db) == {"15d-large", "15d-midcap"}  # the failed slot wrote nothing
    assert db.scalar(select(func.count()).select_from(LanePick)) == 10
    assert db.scalar(text("SELECT 1")) == 1  # the transaction is still usable (nothing left aborted)
    assert not isinstance(out["outcomes"], str)  # outcome scoring still ran


def test_a_failing_last_slot_keeps_the_picks_already_recorded(db, monkeypatch):
    ok = _setup(db, monkeypatch)

    def flaky(db_, model, slot, groups, signal_day, moment, **kw):
        if slot == "15d-midcap":
            db_.execute(text("SELECT * FROM table_that_does_not_exist"))
        return ok(db_, model, slot, groups, signal_day, moment, **kw)

    monkeypatch.setattr(lane_job.S, "record_day", flaky)
    out = lane_job.run_daily(db, now=NOW)
    assert out["slots"]["15d-midcap"].startswith("error:")
    assert _slots_with_picks(db) == {"10d-large", "15d-large"}


def test_a_failure_in_outcome_scoring_never_undoes_the_new_picks(db, monkeypatch):
    ok = _setup(db, monkeypatch)
    monkeypatch.setattr(lane_job.S, "record_day", ok)

    def bad_outcomes(db_, as_of):
        db_.execute(text("SELECT * FROM table_that_does_not_exist"))

    monkeypatch.setattr(lane_job.S, "evaluate_matured", bad_outcomes)
    out = lane_job.run_daily(db, now=NOW)
    assert out["outcomes"].startswith("error:")
    assert _slots_with_picks(db) == {"10d-large", "15d-large", "15d-midcap"}


def test_a_duplicate_run_is_idempotent(db, monkeypatch):
    ok = _setup(db, monkeypatch)
    monkeypatch.setattr(lane_job.S, "record_day", ok)
    first = lane_job.run_daily(db, now=NOW)
    n = db.scalar(select(func.count()).select_from(LanePick))
    second = lane_job.run_daily(db, now=NOW)
    assert n == 15 and db.scalar(select(func.count()).select_from(LanePick)) == 15
    assert all(v["recorded"] == 5 for v in first["slots"].values())
    assert all(v == {"recorded": 0, "skipped": True, "groups": {}} for v in second["slots"].values())


# ---------------------------------------------------------------- no overlapping runs


def test_a_second_run_skips_while_another_run_holds_the_lock(db, db_engine, monkeypatch):
    ok = _setup(db, monkeypatch)
    monkeypatch.setattr(lane_job.S, "record_day", ok)
    other = db_engine.connect()
    tx = other.begin()
    try:
        assert other.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lane_job.LOCK_KEY}).scalar()
        out = lane_job.run_daily(db, now=NOW)
        assert out["skipped"] == "another_run_active" and out["slots"] == {}
        assert db.scalar(select(func.count()).select_from(LanePick)) == 0
    finally:
        tx.rollback()
        other.close()
    after = lane_job.run_daily(db, now=NOW)  # lock released: the next run proceeds
    assert "skipped" not in after and after["slots"]["10d-large"]["recorded"] == 5
