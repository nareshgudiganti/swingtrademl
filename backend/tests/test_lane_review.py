# ruff: noqa: E501 (long test sentences)
"""Shadow lanes: the 60 to 90 session review is read-only, descriptive, immutable and never a promotion."""

from __future__ import annotations

import ast
import importlib.util
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import swing_trade_ml.brain.ten_day  # noqa: F401  (first: replay_scoring has an import cycle that only resolves from here)

from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick  # isort: skip
from swing_trade_ml.db.models.ml import MLModel  # isort: skip
from swing_trade_ml.shadow_lanes import lane_review as R  # isort: skip  # noqa: N812

ROOT = Path(__file__).resolve().parents[1]
START = date(2027, 1, 4)


def _migration():
    spec = importlib.util.spec_from_file_location(
        "lane_migration", ROOT / "alembic" / "versions" / "20261102_1200_lane_shadow.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def db(db_session):
    _migration().install_triggers(db_session.connection())
    return db_session


def model(db, name="td_h10_r", horizon=10):
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
    return m


def fill(
    db,
    m,
    slot="10d-large",
    group="large",
    horizon=10,
    sessions=70,
    net=0.01,
    base=0.002,
    noise=0.004,
    done=None,
):
    """`sessions` signal days, 5 picks each; the first `done` days get outcomes (default: all but the last horizon)."""
    days, d = [], START
    while len(days) < sessions:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    done = sessions - horizon if done is None else done
    rnd = random.Random(11)
    for i, day in enumerate(days):
        for rk in range(1, 6):
            p = LanePick(
                model_id=m.id, slot_key=slot, horizon_days=horizon, cap_group=group, signal_day=day, symbol=f"S{rk}",
                rank=rk, score=0.5, model_version="v1", recorded_at=datetime(2027, 1, 1, tzinfo=UTC),
                entry_assumption={}, target_pct=0.06, stop_pct=0.035, flags={},
            )  # fmt: skip
            db.add(p)
            db.flush()
            if i < done:
                wiggle = noise * (rnd.random() * 2 - 1)
                n = net + wiggle
                db.add(
                    LaneOutcome(
                        pick_id=p.id, matured_day=day, status="timeout", net_return=n,
                        baseline_net_return=base, excess_return=n - base, ambiguous=False,
                    )
                )  # fmt: skip
    db.flush()
    return days


def test_the_checkpoint_and_state_follow_the_recorded_sessions():
    assert R.checkpoint_for(59) is None and R.checkpoint_for(60) == 60 and R.checkpoint_for(89) == 60
    assert R.checkpoint_for(90) == 90 and R.checkpoint_for(200) == 90
    assert R.state_for(59, 100) == "too_early" and R.state_for(70, 59) == "too_early"
    assert R.state_for(70, 61) == "first_review" and R.state_for(95, 100) == "extended_review"


def test_a_lane_with_few_sessions_reads_too_early(db):
    m = model(db)
    days = fill(db, m, sessions=20)
    r = R.build_review(db, "10d-large", days[-1])
    assert r["state"] == "too_early" and r["checkpoint"] is None and r["reading"].startswith("Too early")


def test_a_clearly_good_lane_is_worth_watching_but_never_approved(db):
    m = model(db)
    days = fill(db, m, sessions=80, net=0.02, base=0.002)
    r = R.build_review(db, "10d-large", days[-1])
    assert r["state"] == "first_review" and r["checkpoint"] == 60
    assert r["completed"] == 70 * 5 and r["hit_rate"] == 1.0
    assert r["net_range"]["low"] > 0 and r["excess_range"]["low"] > 0
    assert "Worth continuing" in r["reading"] and "not an approval" in r["reading"]
    assert r["group_average_stock_return"] == pytest.approx(0.002) and r["excess_over_group_average"] > 0
    assert r["pick_level_drawdown"] == 0.0 and r["cash_return"] == 0.0


def test_profit_that_the_market_explains_is_called_out(db):
    m = model(db)
    days = fill(db, m, sessions=80, net=0.02, base=0.02)
    r = R.build_review(db, "10d-large", days[-1])
    assert "not clearly better than the group's own average stock" in r["reading"]


def test_a_lane_with_no_edge_says_so(db):
    m = model(db)
    days = fill(db, m, sessions=80, net=-0.01, base=0.0)
    assert "No clear edge shown yet" in R.build_review(db, "10d-large", days[-1])["reading"]


def test_the_review_uses_only_picks_up_to_the_as_of_day(db):
    m = model(db)
    days = fill(db, m, sessions=80, net=0.02)
    r = R.build_review(db, "10d-large", days[39])
    assert r["sessions_recorded"] == 40 and r["state"] == "too_early"


def test_the_mid_cap_lane_carries_its_warning(db):
    m = model(db, name="sl1_S1M_x", horizon=15)
    days = fill(db, m, slot="15d-midcap", group="mid", horizon=15, sessions=80, net=0.02)
    r = R.build_review(db, "15d-midcap", days[-1])
    assert "Limited experiment" in r["sample_warning"]
    assert "Limited experiment" in R.render_markdown(r)


def test_the_markdown_is_plain_english_with_ranges_limits_and_the_policy(db):
    m = model(db)
    days = fill(db, m, sessions=80, net=0.02)
    text = R.render_markdown(R.build_review(db, "10d-large", days[-1]))
    for needle in (
        "Evidence checkpoint",
        "never promotes a model",
        "could be as low as",
        "Pick-level drawdown",
        "not a portfolio drawdown",
        "liquidity",
        "survivor bias",
    ):
        assert needle in text, needle
    assert "PASS" not in text and "approved." not in text.replace("not an approval.", "")


def test_a_review_file_exists_only_from_60_sessions_and_only_once_per_checkpoint(db, tmp_path):
    m = model(db)
    days = fill(db, m, sessions=30)
    with pytest.raises(R.ReviewError, match="exists only from 60"):
        R.write_review(db, "10d-large", days[-1], repo_root=tmp_path)
    db_days = fill(db, model(db, name="td_h10_r2"), slot="10d-large", sessions=5)  # keep slot busy; not used
    assert db_days


def test_write_review_is_immutable_atomic_and_one_per_checkpoint(db, tmp_path):
    m = model(db)
    days = fill(db, m, sessions=95, net=0.02)
    md, js = R.write_review(db, "10d-large", days[69], repo_root=tmp_path)  # 70 sessions -> checkpoint 60
    assert md.name == "10d-large_60sessions.md" and md.exists() and js.exists()
    assert not list(tmp_path.rglob("*.tmp"))
    with pytest.raises(R.ReviewError, match="already exists"):
        R.write_review(db, "10d-large", days[75], repo_root=tmp_path)
    md90, _ = R.write_review(db, "10d-large", days[-1], repo_root=tmp_path)  # 95 sessions -> checkpoint 90
    assert md90.name == "10d-large_90sessions.md"


def test_building_a_review_changes_nothing(db):
    m = model(db)
    days = fill(db, m, sessions=80)
    before = (db.query(LanePick).count(), db.query(LaneOutcome).count())
    R.build_review(db, "10d-large", days[-1])
    assert (db.query(LanePick).count(), db.query(LaneOutcome).count()) == before


def test_unknown_slot_is_refused(db):
    with pytest.raises(R.ReviewError, match="unknown slot"):
        R.build_review(db, "5d-large", START)


def test_the_review_module_is_read_only_and_isolated():
    src = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    banned = ("brain.modules", "services.risk", "execution", "brokers", "strategies", "h05", "workers")
    assert not [m for m in mods if any(b in m for b in banned)]
    assert "db.add(" not in src and "db.commit(" not in src and "db.delete(" not in src
    assert "promote" in src and "never promotes" in src
