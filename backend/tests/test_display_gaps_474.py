# ruff: noqa: E501 (long plain-English test text)
"""#474: results screens and reports must not show a number where "not enough data" is the honest answer.

Display only: no report number's definition, no trial file and no stored row changes. Each case below was written to fail first.

1. GET /ml/predictions/accuracy answers per model (name, version, horizon, label kind) and says null, not 0.0, when nothing was evaluated.
2. A lane or horizon row that is "too early to judge" / "not enough days" shows no hit rate and no net per trade.
3. The 10-day and 15-day rows carry research_only from core/research_config.
4. A matured pick with no usable price is counted as unresolved: picks = completed + open + unresolved.
5. The empty-week Telegram message says "no trades this week", not zeros.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.api.v1.endpoints import lanes
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.services import weekly_paper_report as weekly
from swing_trade_ml.shadow_lanes import horizon_report as hr
from swing_trade_ml.shadow_lanes import lane_review
from test_lane_shadow_api import seed


class _Pick:
    def __init__(self, day, rank):
        self.signal_day, self.rank = day, rank


class _Out:
    def __init__(self, net, excess=None):
        self.net_return, self.excess_return = net, net if excess is None else excess


def _rows(db):
    return {r["key"]: r for r in hr.build(db)["horizons"]}


# ------------------------------------------------------------------------------- 1. accuracy per model, null when empty


def _model_with_prediction(db, inst, horizon, kind, *, correct=True, evaluated=True, probability=0.7, ret=0.03):
    model = MLModel(
        name=f"g474_h{horizon}_{kind}", version="v1", algorithm="lightgbm", status="ACTIVE",
        prediction_horizon_days=horizon, label_kind=kind, feature_names=["a"], training_symbols=["X"],
    )
    db.add(model)
    db.flush()
    db.add(
        Prediction(
            model_id=model.id, instrument_id=inst.id, ts=datetime(2026, 9, 1, tzinfo=UTC), predicted_class=1,
            probability=probability, price_at_prediction=100.0, label_kind=kind,
            actual_return=ret if evaluated else None, was_correct=correct if evaluated else None,
            evaluated_at=datetime(2026, 9, 10, tzinfo=UTC) if evaluated else None,
        )
    )
    db.flush()
    return model


def test_accuracy_is_given_per_model_with_its_horizon_and_label_kind(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    inst = Instrument(instrument_token=962_001, tradingsymbol="G474PRED", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    five = _model_with_prediction(db_session, inst, 5, "barrier", correct=True)
    fifteen = _model_with_prediction(db_session, inst, 15, "barrier", correct=False, ret=-0.04)
    old = _model_with_prediction(db_session, inst, 5, "endpoint", correct=True)
    out = prediction_accuracy(db_session)
    by_model = {row["model_id"]: row for row in out["by_model"]}
    assert {five.id, fifteen.id, old.id} <= set(by_model)
    assert (by_model[five.id]["name"], by_model[five.id]["version"], by_model[five.id]["horizon_days"], by_model[five.id]["label_kind"]) == (
        "g474_h5_barrier", "v1", 5, "barrier"
    )
    assert by_model[five.id]["accuracy"] == 1.0 and by_model[fifteen.id]["accuracy"] == 0.0
    assert by_model[fifteen.id]["horizon_days"] == 15 and by_model[old.id]["label_kind"] == "endpoint"
    assert by_model[fifteen.id]["avg_actual_return"] == pytest.approx(-0.04)
    assert "all models together" in out["overall_note"]  # the pooled figure, if kept, says what it is


def test_a_chosen_model_answers_for_itself_only(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    inst = Instrument(instrument_token=962_002, tradingsymbol="G474ONE", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    a = _model_with_prediction(db_session, inst, 5, "barrier")
    _model_with_prediction(db_session, inst, 15, "barrier", correct=False)
    out = prediction_accuracy(db_session, model_id=a.id)
    assert [row["model_id"] for row in out["by_model"]] == [a.id]
    assert out["evaluated_predictions"] == 1 and out["accuracy"] == 1.0


def test_nothing_evaluated_is_null_not_zero(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    out = prediction_accuracy(db_session, model_id=-1)
    assert out["evaluated_predictions"] == 0 and out["correct"] == 0
    assert out["accuracy"] is None and out["avg_probability"] is None and out["avg_actual_return"] is None
    assert out["by_model"] == []


def test_a_model_with_predictions_but_none_evaluated_shows_null_for_that_model(db_session):
    from swing_trade_ml.api.v1.endpoints.ml import prediction_accuracy

    inst = Instrument(instrument_token=962_003, tradingsymbol="G474NONE", exchange="NSE", is_active=True)
    db_session.add(inst)
    db_session.flush()
    waiting = _model_with_prediction(db_session, inst, 5, "barrier", evaluated=False)
    out = prediction_accuracy(db_session, model_id=waiting.id)
    assert out["evaluated_predictions"] == 0 and out["accuracy"] is None


# ------------------------------------------------------------------------------- 2. no rate on too little data


def test_the_lanes_view_shows_no_hit_rate_or_net_per_trade_below_the_review_sample():
    rows = [(_Pick(date(2026, 9, 1) + timedelta(days=i), 1), _Out(0.02)) for i in range(3)]
    view, _, completed = lanes.forward_view(rows, 15, "large")
    assert completed == 3 and lanes.SMALL_SAMPLE in view["sample_warning"]
    assert view["hit_rate"] is None and view["mean_net_return"] is None
    assert view["benchmark_excess"] is None and view["drawdown"] is None  # the same floor for every figure drawn from the picks
    assert view["completed"] == 3 and view["picks"] == 3  # the counts stay


def test_the_lanes_view_shows_the_rates_once_the_sample_is_large_enough():
    rows = [(_Pick(date(2026, 1, 1) + timedelta(days=i // 2), i % 2 + 1), _Out(0.02 if i % 4 else -0.01)) for i in range(lanes.REVIEW_AFTER)]
    view, _, completed = lanes.forward_view(rows, 15, "large")
    assert completed == lanes.REVIEW_AFTER and lanes.SMALL_SAMPLE not in (view["sample_warning"] or "")
    assert view["hit_rate"] == pytest.approx(45 / 60) and view["mean_net_return"] is not None
    assert view["benchmark_excess"] is not None and view["drawdown"] is not None


def test_a_horizon_row_that_is_not_enough_days_carries_no_hit_rate_or_net_per_trade(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    row = _rows(db_session)["15d-mid"]
    assert row["verdict"]["state"] == "not_enough_days"
    f = row["forward"]
    assert f["finished"] == 4 and f["picks"] == 6  # the counts stay
    assert f["hit_rate"] is None and f["net_per_trade"] is None and f["edge_vs_every_stock"] is None
    assert "not enough" in f["rates_note"].lower()


def test_a_horizon_row_that_has_enough_days_shows_its_rates(db_session, monkeypatch):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    monkeypatch.setattr(lane_review, "CHECKPOINTS", (2, *lane_review.CHECKPOINTS[1:]))
    row = _rows(db_session)["15d-mid"]
    assert row["verdict"]["state"] == "reading"
    assert row["forward"]["hit_rate"] == pytest.approx(0.5) and row["forward"]["net_per_trade"] == pytest.approx(0.005)
    assert row["forward"]["edge_vs_every_stock"] == pytest.approx(0.005)
    assert row["forward"]["rates_note"] is None


def test_the_five_day_rows_with_too_few_days_also_carry_no_rates(db_session):
    for row in (r for r in _rows(db_session).values() if r["horizon_days"] == 5):
        assert row["verdict"]["state"] == "not_enough_days"
        assert row["forward"]["hit_rate"] is None and row["forward"]["net_per_trade"] is None
        assert row["forward"]["edge_vs_every_stock"] is None


# ------------------------------------------------------------------------------- 3. research_only on the rows


def test_ten_and_fifteen_day_rows_say_research_only_and_the_five_day_rows_do_not(db_session):
    rows = _rows(db_session)
    for key in ("10d-large", "15d-large", "15d-mid"):
        assert rows[key]["research_only"] is True, key
    for key in ("5d-large", "5d-mid", "5d-small"):
        assert rows[key]["research_only"] is False, key


def test_the_flag_comes_from_the_research_config(db_session):
    from swing_trade_ml.core.research_config import is_research_only

    rows = _rows(db_session)
    for key, row in rows.items():
        assert row["research_only"] is is_research_only(row["horizon_days"]), key


def test_the_lanes_screen_rows_carry_the_flag_too(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    lane = next(entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap")
    assert lane["research_only"] is True


# ------------------------------------------------------------------------------- 4. unresolved picks are counted


def _unresolve_one(db):
    pick = db.scalars(select(LanePick).where(LanePick.slot_key == "15d-midcap", LanePick.signal_day == date(2026, 9, 3))).first()
    db.add(LaneOutcome(pick_id=pick.id, matured_day=pick.signal_day, status="unresolved", net_return=None, baseline_net_return=None, excess_return=None))
    db.flush()


def test_picks_equal_completed_plus_open_plus_unresolved(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    _unresolve_one(db_session)
    lane = next(entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap")
    f = lane["forward"]
    assert (f["picks"], f["completed"], f["open"], f["unresolved"]) == (6, 4, 1, 1)
    assert f["completed"] + f["open"] + f["unresolved"] == f["picks"]


def test_the_horizon_report_counts_the_unresolved_pick_too(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    _unresolve_one(db_session)
    f = _rows(db_session)["15d-mid"]["forward"]
    assert (f["picks"], f["finished"], f["unresolved"]) == (6, 4, 1)


def test_without_unresolved_picks_the_new_count_is_zero_and_nothing_else_moves(db_session):
    seed(db_session, slot="15d-midcap", group="mid", horizon=15, name="sl1_S0M_a")
    lane = next(entry for entry in lanes.build_lanes(db_session)["lanes"] if entry["slot_key"] == "15d-midcap")
    f = lane["forward"]
    assert (f["picks"], f["completed"], f["open"], f["unresolved"]) == (6, 4, 2, 0)


# ------------------------------------------------------------------------------- 5. the empty-week message


def test_the_empty_week_message_says_no_trades_not_zeros(db_session):
    message = weekly.format_message(weekly.build_report(db_session, datetime(2026, 11, 3, 5, 0, tzinfo=UTC)))
    assert "no trades this week" in message.lower()
    assert "0 buys, 0 sells" not in message and "realized ₹0" not in message


def test_a_week_with_trades_keeps_its_numbers_in_the_message():
    book = {
        "buys": {"orders": 2}, "sells": {"orders": 1, "partial": 0},
        "realized_pnl": {"net": 123.0}, "unrealized_pnl": {"amount": 10.0}, "data_status": "activity recorded",
        "reconciliation": {"sell_orders_equal_trade_rows": True, "exit_reasons_add_up": True},
    }
    report = {
        "window": {"from": "2026-10-27", "to": "2026-11-02"}, "h05": {"active": False},
        "bot": book, "testing": {**book, "buys": {"orders": 0}, "sells": {"orders": 0, "partial": 0}, "realized_pnl": {"net": 0.0},
                                  "unrealized_pnl": {"amount": 0.0}, "data_status": "no buys or sells this week"},
        "jobs_and_data": {"problems": [], "stale_data": []},
    }
    message = weekly.format_message(report)
    assert "2 buys, 1 sells" in message and "₹123" in message
    assert "Testing (paper): no trades this week" in message


# ------------------------------------------------------------------------------- 6. review follow-ups (#474)


def test_a_model_with_no_checkable_predictions_gives_null_at_a_horizon_not_zero(client, db_session):
    model = MLModel(
        name="g474_empty", version="v1", algorithm="lightgbm", status="ACTIVE", prediction_horizon_days=5,
        feature_names=["a"], training_symbols=["X"],
    )
    db_session.add(model)
    db_session.flush()
    body = client.get("/api/v1/ml/predictions/accuracy/horizon", params={"horizon_days": 5, "model_id": model.id}, headers={"X-API-Key": "test-api-key"}).json()
    assert body["evaluable"] == 0 and body["accuracy"] is None and body["avg_actual_return"] is None


def test_the_daily_summary_says_no_finished_trades_instead_of_a_zero_win_rate():
    import asyncio

    from swing_trade_ml.notifications.telegram import TelegramNotifier

    sent: list[str] = []

    async def capture(text, *args, **kwargs):
        sent.append(text)
        return True

    notifier = TelegramNotifier()
    notifier.send = capture  # type: ignore[method-assign]
    asyncio.run(notifier.notify_daily_summary({"total_value": 1.0, "total_trades": 0}, "paper", []))
    asyncio.run(notifier.notify_daily_summary({"total_value": 1.0, "total_trades": 5, "win_rate": 0.6}, "paper", []))
    assert "no finished trades yet" in sent[0].lower() and "0.0%" not in sent[0] and "Win rate" not in sent[0]
    assert "Win rate: 60.0%" in sent[1] and "no finished trades yet" not in sent[1].lower()


def test_the_h05_trade_counts_add_up_to_the_counted_picks():
    from swing_trade_ml.brain.lanes.h05_report import _trade

    def pick(status, net=None):
        return {"trade_status": status, "net_return": net, "ambiguous": False, "gap_fill": False, "trade_flags": []}

    counted = [pick("target", 0.02), pick("stop", -0.04), pick("expiry", 0.01), pick("unresolved"), pick("unresolved"), pick("pending")]
    trade = _trade(counted)
    assert (trade["finished"], trade["unresolved"], trade["pending"]) == (3, 2, 1)
    assert trade["finished"] + trade["unresolved"] + trade["pending"] == len(counted)


def test_the_h05_row_takes_its_unresolved_count_from_the_same_counted_picks_as_its_pick_total(db_session):
    from swing_trade_ml.brain.lanes import h05_protocol as protocol

    group = "large"
    trade = {"finished": 3, "unresolved": 2, "pending": 1, "mean_net_return": 0.01, "win_rate": 0.66}
    report = {
        "runs": [{
            "run_no": 1,
            "groups": {group: {"counted_selections": 6, "shadow_trade": {"counted_picks": trade, "daily_edge_vs_baseline": {"days": 3, "mean": 0.004}}}},
        }],
        "protocol_accepted": False,
    }
    row = hr._h05_row(db_session, "5d-large", 5, group, report, {}, protocol, {})
    f = row["forward"]
    assert (f["picks"], f["finished"], f["unresolved"], f["open"]) == (6, 3, 2, 1)
    assert f["finished"] + f["open"] + f["unresolved"] == f["picks"]


def test_the_lane_picks_summary_shows_an_average_only_from_the_review_floor():
    from swing_trade_ml.api.v1.endpoints.lane_picks import REVIEW_FLOOR, summarise

    assert lane_review.CHECKPOINTS[0] == REVIEW_FLOOR  # the one floor, not a second number

    def rows(n):
        return [{"status": "hit" if i % 2 else "stopped", "net_return": 0.02 if i % 2 else -0.01} for i in range(n)]

    below = summarise(rows(lane_review.CHECKPOINTS[0] - 1))
    assert below["finished"] == lane_review.CHECKPOINTS[0] - 1 and below["mean_net_return"] is None and "not enough" in below["rates_note"].lower()
    at = summarise(rows(lane_review.CHECKPOINTS[0]))
    assert at["mean_net_return"] == pytest.approx(0.005) and at["rates_note"] is None
    assert summarise([])["mean_net_return"] is None
