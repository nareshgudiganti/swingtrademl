# ruff: noqa: E501, N812  (long plain-English test text; short P alias as in the h05 tests)
"""#255 Verify the model scoreboard by horizon and cap group (parent #235).

Tests only. Nothing here changes a model, a model status, a threshold, the sealed trial or any frozen file. Each test
states what the code is EXPECTED to do and checks what it OBSERVABLY does at the baseline commit. A gap is a strict
expected failure (`xfail(strict=True, raises=AssertionError)`) with one line saying what is missing; if the code is fixed
the strict marker turns red and must be removed on purpose.

Surfaces covered: the horizon report and the lanes screen (shadow_lanes/horizon_report.py, api/v1/endpoints/lanes.py),
the weekly report (services/weekly_paper_report.py), the experiments report (services/experiments/report.py) and the
prediction accuracy route (api/v1/endpoints/ml.py; not in the plan rules, so owner-only with plans on, reachable by
unrestricted accounts such as testers while plans are off, and by service keys). The findings note is
docs/verification/255-model-scoreboard.md. Needs the test database; every write rolls back.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import swing_trade_ml
from swing_trade_ml.api.deps import require_owner
from swing_trade_ml.api.v1.endpoints import (
    experiments,
    h05,
    lane_picks,
    lanes,
    model_registry,
    weekly_report,
)
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.shadow_lanes import horizon_report as hr
from swing_trade_ml.shadow_lanes.lane_service import SLOTS
from test_lane_shadow_api import seed

SRC = Path(swing_trade_ml.__file__).parent
GAP = {"strict": True, "raises": AssertionError}


def _rows(db):
    return {r["key"]: r for r in hr.build(db)["horizons"]}


def _outcome(db, pick, net: float | None, status: str = "target") -> None:
    db.add(
        LaneOutcome(
            pick_id=pick.id,
            matured_day=pick.signal_day,
            status=status,
            net_return=net,
            baseline_net_return=0.0 if net is not None else None,
            excess_return=net,
        )
    )
    db.flush()


# =============================================================== (a) every number names its horizon and cap group


def test_a1_every_horizon_report_row_takes_its_horizon_and_cap_group_from_the_slot_table():
    from swing_trade_ml.brain.lanes import h05_protocol as P

    seen = []
    for key, horizon, group, source, slot in hr.ROWS:
        assert key == f"{horizon}d-{group}"  # the label says what the row is
        if source == "lanes":
            assert SLOTS[slot] == (horizon, group), (
                key,
                SLOTS[slot],
            )  # the lane's own horizon and size group
        else:
            assert (
                horizon == 5 and group in P.EXPECTED_MODELS
            )  # the h05 tables are the 5-day test, per size group
        seen.append((horizon, group))
    assert seen == [(5, "large"), (5, "mid"), (5, "small"), (10, "large"), (15, "large"), (15, "mid")]


def test_a2_two_lanes_with_different_results_never_mix_and_their_counts_match_the_stored_rows(db_session):
    seed(
        db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a"
    )  # 6 picks, 4 finished: +2%, -1%
    large = seed(db_session, slot="15d-large", group="large", horizon=15, name="sl1_S0_a")
    for o in db_session.scalars(
        select(LaneOutcome)
        .join(LanePick, LanePick.id == LaneOutcome.pick_id)
        .where(LanePick.slot_key == "15d-large")
    ):
        db_session.delete(o)
    db_session.flush()
    for pick in db_session.scalars(select(LanePick).where(LanePick.model_id == large.id)):
        _outcome(db_session, pick, -0.05, "stop")  # the large lane loses 5% on every pick
    rows = _rows(db_session)
    mid, big = rows["15d-mid"]["forward"], rows["15d-large"]["forward"]
    assert (mid["picks"], mid["finished"]) == (6, 4) and mid["net_per_trade"] == pytest.approx(0.005)
    assert (big["picks"], big["finished"]) == (6, 6) and big["net_per_trade"] == pytest.approx(-0.05)
    assert rows["10d-large"]["forward"]["picks"] == 0  # a lane with no rows is empty, not a copy of another
    for slot, key in (("15d-midcap", "15d-mid"), ("15d-large", "15d-large")):  # counts equal the stored rows
        stored = db_session.scalars(select(LanePick).where(LanePick.slot_key == slot)).all()
        assert rows[key]["forward"]["picks"] == len(stored)
        done = db_session.scalars(
            select(LaneOutcome)
            .join(LanePick, LanePick.id == LaneOutcome.pick_id)
            .where(LanePick.slot_key == slot, LaneOutcome.net_return.is_not(None))
        ).all()
        assert rows[key]["forward"]["finished"] == len(done)


def test_a3_the_small_mid_cap_warning_belongs_to_the_mid_lane_only():
    rows = [(SimplePick(date(2026, 9, 1), 1), SimpleOutcome(0.01, 0.01))]
    mid, _, _ = lanes.forward_view(rows, 15, "mid")
    large, _, _ = lanes.forward_view(rows, 15, "large")
    assert lanes.MID_WARNING in mid["sample_warning"] and lanes.MID_WARNING not in (
        large["sample_warning"] or ""
    )


class SimplePick:
    def __init__(self, signal_day, rank):
        self.signal_day, self.rank = signal_day, rank


class SimpleOutcome:
    def __init__(self, net, excess):
        self.net_return, self.excess_return = net, excess


@pytest.mark.xfail(
    **GAP,
    reason="gap a4: GET /ml/predictions/accuracy (owner; testers while plans are off; service keys) gives ONE accuracy over every model, whatever its horizon, and mixes the old endpoint-label era",
)
def test_a4_the_accuracy_route_does_not_pool_models_of_different_horizons(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    inst = Instrument(instrument_token=961_001, tradingsymbol="A4PRED", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    models = []
    for horizon, kind in ((5, "barrier"), (15, "barrier"), (5, "endpoint")):
        model = MLModel(
            name=f"a4_h{horizon}_{kind}",
            version="v1",
            algorithm="lightgbm",
            status="ACTIVE",
            prediction_horizon_days=horizon,
            feature_names=["a"],
            training_symbols=["X"],
        )
        db_session.add(model)
        db_session.flush()
        models.append(model)
        db_session.add(
            Prediction(
                model_id=model.id,
                instrument_id=inst.id,
                ts=datetime(2026, 9, 1, tzinfo=UTC),
                predicted_class=1,
                probability=0.7,
                price_at_prediction=100.0,
                label_kind=kind,
                actual_return=0.03,
                was_correct=True,
                evaluated_at=datetime(2026, 9, 10, tzinfo=UTC),
            )
        )
    db_session.flush()
    each = {m.id: prediction_accuracy(db_session, model_id=m.id) for m in models}
    pooled = prediction_accuracy(db_session)  # no model chosen
    assert all(one["evaluated_predictions"] == 1 for one in each.values())  # each model answers for itself
    # precondition (any other rows in a shared database only add to it): the pooled answer contains all three models
    assert pooled["evaluated_predictions"] >= sum(one["evaluated_predictions"] for one in each.values())
    # expected, independent of the total: a pooled answer names the horizon or splits by model or horizon
    named = {"horizon_days", "horizons", "by_horizon", "by_model", "label_kind"}
    assert named & set(pooled), sorted(
        pooled
    )  # api/v1/endpoints/ml.py:301-330 returns only five bare numbers


# ================================================== (b) research-only horizons appear only on owner routes


def test_b1_every_model_result_route_is_owner_only():
    for module in (lanes, lane_picks, h05, weekly_report, experiments, model_registry):
        routes = module.router.routes
        assert routes, module.__name__
        for route in routes:
            assert any(d.dependency is require_owner for d in route.dependencies), (
                module.__name__,
                route.path,
            )


def test_b2_only_the_owner_routers_import_the_lane_the_weekly_and_the_experiment_code():
    owner_files = {
        "api/v1/endpoints/lanes.py",
        "api/v1/endpoints/lane_picks.py",
        "api/v1/endpoints/weekly_report.py",
        "api/v1/endpoints/experiments.py",
    }
    watched = (
        "shadow_lanes",
        "db.models.lane_shadow",
        "weekly_paper_report",
        "services.experiments",
        "horizon_report",
    )
    importers = set()
    for path in (SRC / "api").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(w in n for n in names for w in watched):
                importers.add(path.relative_to(SRC).as_posix())
    assert importers <= owner_files, sorted(
        importers - owner_files
    )  # a member-visible route never reads them


@pytest.mark.xfail(
    **GAP,
    reason="gap b3: the 10-day and 15-day rows of the horizon report carry no research_only flag (the config marks both research-only)",
)
def test_b3_the_ten_and_fifteen_day_rows_are_marked_research_only_in_the_payload(db_session):
    rows = _rows(db_session)
    for key in ("10d-large", "15d-large", "15d-mid"):
        assert rows[key].get("research_only") is True, key  # horizon_report.py:_lane_row sets no such field
    assert rows["5d-large"].get("research_only") in (False, None)


def test_b4_the_words_on_the_report_already_say_test_records_not_trades():
    assert "not trades and not advice" in hr.NOTE and "Test records only" in hr.NOTE
    assert "Test picks only" in lanes.NOTE and "Not trades" in lanes.NOTE


# ====================================== (c) backtest, forward and paper results are never added into one figure


def test_c1_the_weekly_report_keeps_its_sources_apart_and_adds_no_grand_total(db_session):
    """A NAME check: none of a few total-like keys appears and the report says its sources are never added together.
    It is not proof that no code sums them; the weekly report's own tests cover the counting rules."""
    from swing_trade_ml.services import weekly_paper_report as wr

    report = wr.build_report(db_session, now=datetime(2026, 12, 4, 12, 0, tzinfo=UTC))
    assert "never added together" in report["separate_sources"]
    assert {"h05", "bot", "testing"} <= set(report)

    def names(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield str(k)
                yield from names(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from names(v)

    for section in ("h05", "bot", "testing"):
        bad = [
            n
            for n in names(report[section])
            if n.lower() in {"total_pnl", "combined", "grand_total", "all_books"}
        ]
        assert not bad, (section, bad)
    assert (
        set(report["horizons"]) == {"5D", "10D", "15D"}
        and "not part of this report" in report["horizons"]["15D"]
    )


def test_c2_a_five_day_lane_never_shows_a_ten_or_fifteen_day_history_test(tmp_path):
    (tmp_path / "td_v1").mkdir()
    (tmp_path / "td_v1" / "ten_day_1.json").write_text(
        '{"label": "10-day test", "pooled": {"model": {"avg_net": 0.01, "ideas": 40}, "every_stock": {"avg_net": 0.0}}}',
        encoding="utf-8",
    )
    five = next(k for k, (h, _) in SLOTS.items() if h == 5)
    assert lanes.history_for(five, tmp_path)["available"] is False  # lanes.py:129-130
    ten = lanes.history_for("10d-large", tmp_path)
    assert (
        ten["available"] and ten["after_cost"]["trades"] == 40
    )  # the 10-day history stays with the 10-day lane


def test_c3_history_and_forward_are_separate_blocks_of_one_lane(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    lane = next(
        entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap"
    )
    assert "history" in lane and "forward" in lane and lane["history"] is not lane["forward"]
    assert lane["forward"]["completed"] == 4  # computed from the stored forward rows only
    assert set(lane["history"]) >= {"available", "label", "ranking", "after_cost"}


def test_c4_the_horizon_report_forward_numbers_come_only_from_forward_rows():
    source = (SRC / "shadow_lanes" / "horizon_report.py").read_text(encoding="utf-8")
    lane_row = source.split("def _lane_row", 1)[1].split("\ndef ", 1)[0]
    assert "history_for(slot)" in lane_row  # history is read once, and only for the qualification text
    forward = lane_row.split('"forward": {', 1)[1].split('},\n        "verdict"', 1)[0]
    assert "history" not in forward


# ===================================================================== (d) too few results: says so, shows no rate


def test_d1_no_results_is_none_never_zero_and_says_it_is_too_early():
    view, _sessions, completed = lanes.forward_view([], 15, "large")
    assert (completed, view["hit_rate"], view["mean_net_return"], view["drawdown"]) == (0, None, None, None)
    assert view["uncertainty"] == {"low": None, "high": None} and lanes.SMALL_SAMPLE in view["sample_warning"]


@pytest.mark.xfail(
    **GAP,
    reason="gap d2: the lanes screen says 'too early to judge' but still prints a hit rate for 3 finished picks",
)
def test_d2_a_lane_with_too_few_finished_picks_shows_no_hit_rate():
    rows = [
        (SimplePick(date(2026, 9, 1) + timedelta(days=i), 1), SimpleOutcome(0.02, 0.02)) for i in range(3)
    ]
    view, _, completed = lanes.forward_view(rows, 15, "large")
    assert completed == 3 and lanes.SMALL_SAMPLE in view["sample_warning"]
    assert view["hit_rate"] is None, view["hit_rate"]  # lanes.py:202 gives 1.0 (100%)


@pytest.mark.xfail(
    **GAP,
    reason="gap d3: the horizon report says 'not enough days' but its rows still carry hit rate and net per trade",
)
def test_d3_a_horizon_row_that_is_not_enough_days_carries_no_hit_rate(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    row = _rows(db_session)["15d-mid"]
    assert row["verdict"]["state"] == "not_enough_days" and row["forward"]["finished"] == 4
    assert row["forward"]["hit_rate"] is None, row["forward"][
        "hit_rate"
    ]  # horizon_report.py:_lane_row gives 0.5


@pytest.mark.xfail(
    **GAP,
    reason="gap d4: GET /ml/predictions/accuracy answers 0.0 for accuracy, average probability and average return when nothing is evaluated",
)
def test_d4_no_evaluated_predictions_is_not_an_accuracy_of_zero(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    result = prediction_accuracy(db_session, model_id=-1)  # a model that does not exist: nothing evaluated
    assert result["evaluated_predictions"] == 0
    empty = {k: result[k] for k in ("accuracy", "avg_probability", "avg_actual_return")}
    assert empty == dict.fromkeys(empty), empty  # ml.py:325-330 gives 0.0 for all three


def test_d5_the_experiments_report_leaves_a_missing_mean_empty_and_never_calls_a_small_sample_proven(
    db_session,
):
    from swing_trade_ml.services.experiments import report

    out = report.build(db_session, today=date(2026, 12, 1))
    assert out["horizons"], "the protocol has horizons"
    for h in out["horizons"]:
        assert h["closed"] == 0 and h["mean_net_return"] is None and h["win_rate"] is None
        assert h["verdict"] == "Not proven" and h["minimum_needed"] > h["independent_samples"]


# ================================================================================ (e) counts reconcile with stored rows


@pytest.mark.xfail(
    **GAP,
    reason="gap e1: a pick whose outcome is 'unresolved' (no return) is in neither 'completed' nor 'open', so the lane counts do not add up",
)
def test_e1_picks_equal_completed_plus_open_plus_unresolved(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    pick = db_session.scalars(
        select(LanePick).where(LanePick.slot_key == "15d-midcap", LanePick.signal_day == date(2026, 9, 3))
    ).first()
    _outcome(db_session, pick, None, "unresolved")  # matured but no usable price: stored, with no return
    lane = next(
        entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap"
    )
    f = lane["forward"]
    assert f["picks"] == 6
    assert f["completed"] + f["open"] == f["picks"], (
        f
    )  # 4 + 1 != 6: the unresolved pick is not counted anywhere


def test_e2_without_unresolved_outcomes_the_lane_counts_add_up(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    lane = next(
        entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap"
    )
    f = lane["forward"]
    assert (f["picks"], f["completed"], f["open"]) == (6, 4, 2) and f["completed"] + f["open"] == f["picks"]
    assert lane["sessions_recorded"] == 3 and f["review"]["sessions_done"] == 3
