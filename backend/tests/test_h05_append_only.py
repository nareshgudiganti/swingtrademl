# ruff: noqa: E501, F811 (fixtures are imported by name; long test sentences)
"""5-day lane (h05): the database refuses to edit or delete a saved pick, while the lane's own writes still pass.

Software tests of storage rules. They say nothing about whether any model is good."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.brain.lanes import h05_service
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run, H05Signal

from test_h05_service import (  # noqa: F401  (fixture + helpers)
    NOW,
    SIGNAL,
    add_stock,
    future,
    lane,
    make_run,
    rows_of,
)

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261103_1500_h05_append_only.py"


def _mig():
    spec = importlib.util.spec_from_file_location("h05_ao", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _refused(db, sql):
    sp = db.begin_nested()
    with pytest.raises(DBAPIError) as exc:
        db.execute(text(sql))
    sp.rollback()
    assert "append-only" in str(exc.value), sql


@pytest.fixture()
def day(db_session, lane):
    """A scored day with every outcome filled, plus one stock whose outcome is still pending."""
    done = {"WIN": {"n2": (100, 103, 100, 102.5), "n5": (103, 103, 103, 103)}}
    for i, (s, bars) in enumerate(done.items()):
        inst = add_stock(db_session, s)
        lane.scores[s] = 0.9 - i / 10
        done[s] = (inst, bars)
    add_stock(db_session, "PEND")
    lane.scores["PEND"] = 0.1
    run = make_run(db_session, {"WIN": "large", "PEND": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    inst, bars = done["WIN"]
    future(db_session, inst, **bars)
    h05_service.evaluate(db_session, run)
    db_session.flush()
    return run


def test_every_column_of_the_signals_table_is_classified_so_a_new_column_forces_a_decision():
    m = _mig()
    classified = {c.strip('"') for c in (*m.SIGNAL_FROZEN, *m.SIGNAL_LABEL, *m.SIGNAL_TRADE, *m.SIGNAL_FREE)}
    assert classified == {c.name for c in H05Signal.__table__.columns}
    assert {c.name for c in H05Run.__table__.columns} == set(m.RUN_FROZEN) | {"status"}


def test_the_lane_still_runs_end_to_end_under_the_guards(db_session, day):
    # score_day, evaluate (both outcome blocks) and close_run all passed the triggers in the fixture
    h05_service.close_run(db_session, day)
    db_session.flush()
    assert day.status == "closed"
    assert db_session.scalar(select(func.count()).select_from(H05Signal)) == 2
    rows = rows_of(db_session, day)
    assert rows["WIN"].trade_status == "target" and rows["PEND"].trade_status != "pending"


def test_a_saved_score_rank_or_top_five_choice_cannot_be_edited(db_session, day):
    for col, val in (
        ("score", "0.01"),
        ("group_rank", "9"),
        ("selected", "NOT selected"),
        ("symbol", "'OTHER'"),
        ("signal_close", "1"),
        ("recorded_at", "now()"),
        ("repeat_blocked", "NOT repeat_blocked"),
    ):
        _refused(db_session, f"UPDATE h05_signals SET {col} = {val}")


def test_a_final_label_and_a_final_trade_outcome_cannot_be_changed(db_session, day):
    for sql in (
        "UPDATE h05_signals SET label_hit = 1 - label_hit WHERE symbol = 'WIN'",
        "UPDATE h05_signals SET net_return = 0.5 WHERE symbol = 'WIN'",
        "UPDATE h05_signals SET trade_status = 'stop' WHERE symbol = 'WIN'",
        "UPDATE h05_signals SET net_return_stress = 0.5 WHERE symbol = 'WIN'",
    ):
        _refused(db_session, sql)


def test_a_pending_outcome_can_still_be_filled_once_and_then_it_is_frozen(db_session, lane):
    inst = add_stock(db_session, "LATE")
    lane.scores["LATE"] = 0.5
    run = make_run(db_session, {"LATE": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    db_session.execute(
        text("UPDATE h05_signals SET label_status = 'final', label_hit = 1 WHERE symbol = 'LATE'")
    )  # first fill from pending is allowed
    _refused(db_session, "UPDATE h05_signals SET label_hit = 0 WHERE symbol = 'LATE'")
    assert inst is not None


def test_deleting_or_truncating_any_h05_table_is_refused(db_session, day):
    db_session.add(H05Event(run_id=day.id, signal_day=SIGNAL, kind="x", detail="y"))
    db_session.flush()  # a row-level DELETE guard only fires when there is a row to delete
    for table in ("h05_signals", "h05_group_days", "h05_events", "h05_runs"):
        _refused(db_session, f"DELETE FROM {table}")
        _refused(db_session, f"TRUNCATE {table} CASCADE")
    assert db_session.scalar(select(func.count()).select_from(H05Signal)) == 2


def test_group_days_and_events_cannot_be_updated_at_all(db_session, day):
    db_session.add(H05Event(run_id=day.id, signal_day=SIGNAL, kind="x", detail="y"))
    db_session.flush()
    assert db_session.scalar(select(func.count()).select_from(H05GroupDay)) > 0
    _refused(db_session, "UPDATE h05_group_days SET selected_n = 0")
    _refused(db_session, "UPDATE h05_events SET detail = 'edited'")


def test_a_run_may_only_go_from_active_to_closed_and_nothing_else_in_it_changes(db_session, day):
    _refused(db_session, "UPDATE h05_runs SET universe_hash = 'x'")
    _refused(db_session, "UPDATE h05_runs SET models = '{}'::jsonb")
    _refused(db_session, "UPDATE h05_runs SET status = 'weird'")
    h05_service.close_run(db_session, day)
    db_session.flush()
    _refused(db_session, "UPDATE h05_runs SET status = 'active'")


def test_upgrade_twice_is_safe_and_downgrade_removes_only_the_guards(db_session, day):
    m = _mig()
    conn = db_session.connection()
    m.install_triggers(conn)  # second install
    _refused(db_session, "DELETE FROM h05_signals")
    m.drop_triggers(conn)
    left = db_session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'trg_h05_%'"))
    assert left == 0
    assert db_session.scalar(select(func.count()).select_from(H05Signal)) == 2  # data untouched
