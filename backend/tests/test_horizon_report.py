# ruff: noqa: N812 (long test sentences; short P alias as in the h05 tests)
"""Unified 5/10/15-day forward report: shape, honest labels, NIFTY yardstick, owner-only, read-only.

These are software tests of the report. They say nothing about whether any model is good."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from test_lane_shadow_api import headers, seed

from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.shadow_lanes import horizon_report as hr

URL = "/api/v1/research/lanes/horizon-report"


def get(client, db_session, role="owner"):
    return client.get(URL, headers=headers(db_session, role))


def row_of(client, db_session, key):
    return next(r for r in get(client, db_session).json()["horizons"] if r["key"] == key)


def test_owner_only(client, db_session):
    assert client.get(URL).status_code in (401, 403)
    for role in ("member", "tester"):
        assert get(client, db_session, role).status_code == 403, role
    assert get(client, db_session).status_code == 200


def test_window_return_and_next_session_are_exact():
    bars = {date(2026, 9, 1): (100.0, 101.0), date(2026, 9, 4): (103.0, 110.0)}
    assert hr.window_return(bars, date(2026, 9, 1), date(2026, 9, 4)) == pytest.approx(0.10)
    assert (
        hr.window_return(bars, date(2026, 9, 1), date(2026, 9, 9)) is None
    )  # exit bar missing: never invented
    assert hr.window_return(bars, None, date(2026, 9, 4)) is None
    sessions = [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 4)]
    assert hr.next_session(sessions, date(2026, 9, 2)) == date(2026, 9, 4)
    assert hr.next_session(sessions, date(2026, 9, 4)) is None


def test_nifty_summary_says_plainly_when_unavailable():
    out = hr.nifty_summary([(date(2026, 9, 1), date(2026, 9, 4))], {})
    assert out["available"] is False and out["mean_return"] is None and "not available" in out["note"]
    bars = {date(2026, 9, 1): (100.0, 100.0), date(2026, 9, 4): (100.0, 105.0)}
    ok = hr.nifty_summary([(date(2026, 9, 1), date(2026, 9, 4)), (None, None)], bars)
    assert ok["available"] and ok["windows"] == 1 and ok["mean_return"] == pytest.approx(0.05)


def test_empty_state_has_six_rows_and_honest_words(client, db_session):
    out = get(client, db_session).json()
    assert set(out) == {"note", "nifty_note", "edge_notes", "fold_model_note", "horizons"}
    assert "does not prove a model works" in out["note"]
    assert [(r["key"], r["horizon_days"], r["cap_group"]) for r in out["horizons"]] == [
        ("5d-large", 5, "large"),
        ("5d-mid", 5, "mid"),
        ("5d-small", 5, "small"),
        ("10d-large", 10, "large"),
        ("15d-large", 15, "large"),
        ("15d-mid", 15, "mid"),
    ]
    for r in out["horizons"]:
        assert r["verdict"]["state"] == "not_enough_days"
        assert r["verdict"]["text"] == "Not enough days to judge."
        assert r["qualification"]["state"] in ("not_qualified", "not_run")
        f = r["forward"]
        assert f["finished"] == 0 and f["net_per_trade"] is None and f["hit_rate"] is None
    for r in out["horizons"]:
        if r["horizon_days"] == 15 and r["qualification"]["state"] == "not_run":
            assert "5 Dec 2026" in r["qualification"]["text"]


def test_fold_model_is_never_shown_as_a_live_model(client, db_session):
    m = seed(db_session, name="sl1_S0M_20230701")  # a lab fold name
    out = get(client, db_session).json()
    row = next(r for r in out["horizons"] if r["key"] == "15d-mid")
    assert row["model"]["id"] == m.id
    assert row["model"]["role"] == "fold"
    assert row["model"]["role_label"] == "Evaluation fold model - not used for daily picks"
    assert row["model"]["daily_picks_allowed"] is False
    assert row["qualification"]["state"] != "qualified"
    assert "fold" in out["fold_model_note"]


def test_final_model_needs_the_recorded_qualification_to_count_as_qualified(client, db_session):
    m = seed(db_session, name="sl1_S0M_lane_20261205")
    m.model_role = "final"
    m.metrics = {"qualification": {"candidate": "S0M", "frozen_at": "2026-12-06", "history_report": "x"}}
    db_session.flush()
    row = row_of(client, db_session, "15d-mid")
    assert row["model"]["role_label"] == "Final model" and row["model"]["daily_picks_allowed"] is True
    assert row["qualification"]["state"] == "qualified"
    m.metrics = {}  # a final label alone, without the recorded qualification, is not enough
    db_session.flush()
    assert row_of(client, db_session, "15d-mid")["qualification"]["state"] != "qualified"


def test_lane_numbers_and_nifty_yardstick_over_the_same_windows(client, db_session):
    seed(db_session, name="sl1_S0M_a")
    inst = Instrument(instrument_token=999001, tradingsymbol="NIFTY 50", exchange="NSE")
    db_session.add(inst)
    db_session.flush()
    d0 = date(2026, 9, 1)
    for i in range(12):
        day = d0 + timedelta(days=i)
        ts = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=5, minutes=30)
        db_session.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=ts,
                open=100 + i,
                high=110 + i,
                low=90 + i,
                close=101 + i,
                volume=1,
            )
        )
    for o in db_session.query(LaneOutcome).all():
        o.exit_day = d0 + timedelta(days=5)
    db_session.flush()
    row = row_of(client, db_session, "15d-mid")
    f = row["forward"]
    assert (f["picks"], f["finished"], f["matured_days"]) == (6, 4, 2)
    assert f["net_per_trade"] == pytest.approx(0.005) and f["hit_rate"] == pytest.approx(0.5)
    assert f["edge_vs_every_stock"] == pytest.approx(0.005)
    n = f["nifty"]
    assert n["available"] and n["windows"] == 4 and n["mean_return"] is not None
    assert row["verdict"]["state"] == "not_enough_days" and row["verdict"]["needed_days"] == 60


def test_report_writes_nothing(client, db_session):
    seed(db_session, name="sl1_S0M_a")

    def counts():
        return (
            db_session.query(LanePick).count(),
            db_session.query(LaneOutcome).count(),
            db_session.query(MLModel).count(),
        )

    before = counts()
    get(client, db_session)
    assert counts() == before


def test_five_day_row_reads_the_h05_tables_and_stays_not_enough_days(client, db_session):
    from swing_trade_ml.brain.lanes import h05_protocol as P
    from swing_trade_ml.db.models.lanes import H05Run, H05Signal

    run = H05Run(
        run_no=1,
        protocol_code=P.PROTOCOL_CODE,
        protocol_hash=P.protocol_hash(),
        status="active",
        start_day=date(2026, 11, 2),
        end_day=date(2027, 1, 28),
        models={},
        universe={"groups": {}, "excluded": {}},
        universe_hash="u1",
    )
    db_session.add(run)
    db_session.flush()
    for i, (net, sel) in enumerate([(0.02, True), (-0.01, True), (0.00, False)]):
        db_session.add(
            H05Signal(
                run_id=run.id,
                signal_day=date(2026, 11, 2),
                symbol=f"S{i}",
                group="large",
                status="scored",
                score=0.5,
                selected=sel,
                repeat_blocked=False,
                label_status="pending",
                trade_status="target" if net > 0 else "stop",
                net_return=net,
                entry_day=date(2026, 11, 3),
                exit_day=date(2026, 11, 6),
            )
        )
    db_session.flush()
    row = row_of(client, db_session, "5d-large")
    assert row["source"] == "h05" and row["run_no"] == 1
    if (
        row["model"] is None
    ):  # the expected prod model id is not in this test database: shown as none, not invented
        db_session.add(
            MLModel(
                id=P.EXPECTED_MODELS["large"]["id"],
                name="swing_classifier",
                version="v2",
                algorithm="lightgbm",
                status="ACTIVE",
                prediction_horizon_days=5,
                feature_names=["a"],
                training_symbols=["X"],
            )
        )
        db_session.flush()
        row = row_of(client, db_session, "5d-large")
    assert row["model"]["role"] in ("prod", "unmarked") and row["model"]["daily_picks_allowed"] is False
    assert row["qualification"]["state"] == "not_qualified" and "history test" in row["qualification"]["text"]
    assert row["forward"]["picks"] == 2
    assert row["verdict"]["state"] == "not_enough_days" and row["verdict"]["needed_days"] == 40
