# ruff: noqa: E501 (long test sentences)
"""Shared shadow lanes API: exact JSON shape, fractions, owner-only, read-only, history from stored reports."""

from __future__ import annotations

import json
from datetime import date, timedelta
from itertools import count

import pytest

from swing_trade_ml.api.v1.endpoints import lanes
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.session import User

URL = "/api/v1/research/lanes"
LANE_KEYS = {
    "slot_key",
    "horizon_days",
    "cap_group",
    "model",
    "status",
    "started_on",
    "sessions_recorded",
    "history",
    "forward",
}
FORWARD_KEYS = {
    "picks",
    "completed",
    "open",
    "hit_rate",
    "mean_net_return",
    "benchmark_excess",
    "drawdown",
    "uncertainty",
    "sample_warning",
    "review",
}
HISTORY_KEYS = {"available", "label", "ranking", "after_cost", "benchmark_excess", "drawdown", "note"}


_n = count()


def headers(db, role):
    u = User(
        username=f"ln-{role}-{next(_n)}",
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="pro",
        role=role,
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def seed(db, slot="15d-midcap", group="mid", horizon=15, n_days=3, name="sl1_S0M_a"):
    m = MLModel(
        name=name,
        version="v1",
        algorithm="lightgbm",
        status="TRAINED",
        prediction_horizon_days=horizon,
        feature_names=["a"],
        training_symbols=["X"],
    )
    db.add(m)
    db.flush()
    d0 = date(2026, 9, 1)
    for i in range(n_days):
        for rank in (1, 2):
            p = LanePick(
                model_id=m.id,
                slot_key=slot,
                horizon_days=horizon,
                cap_group=group,
                signal_day=d0 + timedelta(days=i),
                symbol=f"S{rank}",
                rank=rank,
                score=0.5,
                model_version="v1",
                entry_assumption={},
                target_pct=0.08,
                stop_pct=0.04,
            )
            db.add(p)
            db.flush()
            if i < 2:
                net = 0.02 if rank == 1 else -0.01
                db.add(
                    LaneOutcome(
                        pick_id=p.id,
                        matured_day=d0,
                        status="target" if net > 0 else "stop",
                        net_return=net,
                        baseline_net_return=0.0,
                        excess_return=net,
                    )
                )
    db.flush()
    return m


def test_owner_only(client, db_session):
    assert client.get(URL).status_code in (401, 403)
    for role in ("member", "tester"):
        assert client.get(URL, headers=headers(db_session, role)).status_code == 403, role
        assert client.get(f"{URL}/10d-large/picks", headers=headers(db_session, role)).status_code == 403, (
            role
        )
    assert client.get(URL, headers=headers(db_session, "owner")).status_code == 200


def test_empty_state_has_the_three_lanes_with_nulls(client, db_session):
    out = client.get(URL, headers=headers(db_session, "owner")).json()
    assert set(out) == {"note", "lanes"} and isinstance(out["note"], str)
    assert [(ln["slot_key"], ln["horizon_days"], ln["cap_group"]) for ln in out["lanes"]] == [
        ("10d-large", 10, "large"),
        ("15d-large", 15, "large"),
        ("15d-midcap", 15, "mid"),
    ]
    for ln in out["lanes"]:
        assert (
            set(ln) == LANE_KEYS and set(ln["history"]) == HISTORY_KEYS and set(ln["forward"]) == FORWARD_KEYS
        )
        assert ln["status"] == "history_only" and ln["started_on"] is None and ln["sessions_recorded"] == 0
        f = ln["forward"]
        assert f["picks"] == 0 and f["hit_rate"] is None and f["drawdown"] is None
        assert f["uncertainty"] == {"low": None, "high": None}
        assert f["review"] == {"due_after_sessions": 60, "sessions_done": 0, "state": "not_due"}
        assert "Fewer than 60 completed picks: too early to judge." in f["sample_warning"]
    mid = out["lanes"][2]["forward"]["sample_warning"]
    assert "Limited experiment: about 14 mid-cap stocks." in mid
    assert "Limited experiment" not in out["lanes"][0]["forward"]["sample_warning"]


def test_forward_numbers_are_fractions_and_drawdown_is_pick_level(client, db_session):
    m = seed(db_session)
    out = client.get(URL, headers=headers(db_session, "owner")).json()
    ln = out["lanes"][2]
    assert ln["model"] == {"id": m.id, "name": "sl1_S0M_a", "version": "v1"}
    assert (
        ln["status"] == "forward_watching"
        and ln["started_on"] == "2026-09-01"
        and ln["sessions_recorded"] == 3
    )
    f = ln["forward"]
    assert (f["picks"], f["completed"], f["open"]) == (6, 4, 2)
    assert f["hit_rate"] == pytest.approx(0.5)
    assert f["mean_net_return"] == pytest.approx(0.005)  # 0.5%, as a fraction
    assert f["benchmark_excess"] == pytest.approx(0.005)
    assert f["drawdown"] == pytest.approx(-0.01)  # +0.02, -0.01, +0.02, -0.01: largest fall 1%
    assert f["uncertainty"] == {"low": None, "high": None}  # fewer than 30 completed
    assert "NOT a portfolio drawdown" in out["note"]
    # other lanes untouched
    assert out["lanes"][0]["forward"]["picks"] == 0


def test_picks_endpoint_rows_and_unknown_slot(client, db_session):
    seed(db_session)
    h = headers(db_session, "owner")
    rows = client.get(f"{URL}/15d-midcap/picks?limit=100", headers=h).json()
    assert len(rows) == 6
    assert set(rows[0]) == {
        "signal_day",
        "symbol",
        "cap_group",
        "rank",
        "score",
        "model_version",
        "recorded_at",
        "status",
        "net_return",
        "excess_return",
    }
    assert (
        rows[0]["signal_day"] == "2026-09-03"
        and rows[0]["status"] == "open"
        and rows[0]["net_return"] is None
    )
    assert {r["status"] for r in rows} == {"open", "target", "stop"}
    assert len(client.get(f"{URL}/15d-midcap/picks?limit=2", headers=h).json()) == 2
    assert client.get(f"{URL}/nope/picks", headers=h).status_code == 404


def test_router_is_get_only():
    assert all(list(r.methods) == ["GET"] for r in lanes.router.routes)


def test_review_states_and_status():
    assert lanes.lane_status(0, 0) == "history_only"
    assert lanes.lane_status(10, 0) == "forward_watching"
    assert lanes.lane_status(60, 60) == "review_due"
    assert lanes.lane_status(60, 10) == "inconclusive"


def test_bootstrap_and_drawdown_helpers():
    assert lanes.pick_drawdown([]) is None
    assert lanes.pick_drawdown([0.01, 0.02]) == 0.0
    assert lanes.pick_drawdown([0.05, -0.02, -0.03, 0.01]) == pytest.approx(-0.05)
    few = [[0.01]] * 10
    assert lanes.bootstrap_interval(few, 10) is None
    many = [[0.01, 0.03] for _ in range(40)]
    lo, hi = lanes.bootstrap_interval(many, 10)
    assert lo == pytest.approx(0.02) and hi == pytest.approx(0.02)
    assert lanes.bootstrap_interval(many, 10) == (lo, hi)  # seed 7: deterministic


def test_history_read_from_stored_reports_and_absent_files(tmp_path):
    assert lanes.history_for("10d-large", tmp_path)["available"] is False
    td = tmp_path / "td_v1"
    td.mkdir()
    (td / "ten_day_2026-10-30.json").write_text(
        json.dumps(
            {
                "label": "10-day model",
                "pooled": {"model": {"avg_net": 0.004, "ideas": 120}, "every_stock": {"avg_net": 0.001}},
                "benchmarks": {"accounts": {"best_5": {"max_drawdown": -0.08}}},
                "verdict": {"economic": {"word": "No"}},
            }
        ),
        encoding="utf-8",
    )
    h = lanes.history_for("10d-large", tmp_path)
    assert h["available"] and h["after_cost"] == {"mean_net_return": 0.004, "trades": 120}
    assert h["benchmark_excess"] == pytest.approx(0.003) and h["drawdown"] == -0.08 and h["note"] == "No"
    for name in ("S0", "S0M"):
        d = tmp_path / "sl_v1" / name
        d.mkdir(parents=True)
        (d / "metrics.json").write_text(
            json.dumps({"r1": {"mean_ic": 0.03 if name == "S0" else 0.05, "lower_bound": 0.01, "days": 250}}),
            encoding="utf-8",
        )
    assert lanes.history_for("15d-large", tmp_path)["ranking"] == {
        "mean_ic": 0.03,
        "lower_bound": 0.01,
        "days": 250,
    }
    assert lanes.history_for("15d-midcap", tmp_path)["ranking"]["mean_ic"] == 0.05
    (tmp_path / "sl_v1" / "S0" / "metrics.json").write_text("{not json", encoding="utf-8")
    assert lanes.history_for("15d-large", tmp_path)["available"] is False
