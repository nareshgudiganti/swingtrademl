"""Calibration report — does a shown confidence match the realised hit rate?

The traps these pin: a boundary value landing in the wrong bucket, a stop or
expiry counted as a win, `was_correct` leaking into the prediction report, and
the endpoint and barrier eras being averaged together. See the plan's Stage 1.6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.trading import Signal, Strategy

HEADERS = {"X-API-Key": "test-api-key"}
START = datetime(2026, 1, 5, tzinfo=UTC)


def _instrument(db_session, tradingsymbol="CALTEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session, name="cal_strategy") -> Strategy:
    strat = Strategy(name=name, strategy_type="ml_swing", mode="paper")
    db_session.add(strat)
    db_session.flush()
    return strat


def _signal(db_session, strat, inst, confidence, outcome="TARGET_HIT", outcome_pct=0.08, *,
            mode="paper", generated_at=START) -> Signal:
    sig = Signal(
        strategy_id=strat.id, instrument_id=inst.id, signal_type=SignalType.BUY,
        mode=mode, price=100.0, confidence=confidence, stop_loss=96.0, take_profit=108.0,
        horizon_days=15, outcome=outcome, outcome_pct=outcome_pct, generated_at=generated_at,
    )
    db_session.add(sig)
    return sig


def _model(db_session, *, label_kind="barrier", name="cal_model", target=0.08) -> MLModel:
    model = MLModel(
        name=name, version="v1", algorithm="lightgbm", status="ACTIVE",
        artifact_path="/tmp/none.joblib", prediction_horizon_days=15,
        target_return_pct=target, stop_return_pct=0.04 if label_kind == "barrier" else None,
        label_kind=label_kind,
    )
    db_session.add(model)
    db_session.flush()
    return model


_ts_counter = iter(range(100_000))


def _prediction(db_session, model, inst, probability, actual_return, *, was_correct=None,
                predicted_class=1, label_kind=None, evaluated=True) -> Prediction:
    pred = Prediction(
        model_id=model.id, instrument_id=inst.id,
        # Unique per row: (model, instrument, ts) is a unique constraint.
        ts=START + timedelta(minutes=next(_ts_counter)),
        predicted_class=predicted_class, probability=probability, price_at_prediction=100.0,
        features={}, label_kind=label_kind or model.label_kind,
        actual_return=actual_return if evaluated else None,
        was_correct=was_correct, evaluated_at=START + timedelta(days=30) if evaluated else None,
    )
    db_session.add(pred)
    return pred


def _by_lower(report):
    return {b.lower: b for b in report.buckets}


# ------------------------------------------------------------------ buckets --


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.549, None), (0.55, 0), (0.5999, 0), (0.60, 1), (0.6999, 1),
        (0.70, 2), (0.80, 3), (0.95, 3), (1.0, 3),
    ],
)
def test_bucket_boundaries(confidence, expected):
    from swing_trade_ml.ml.calibration import bucket_index

    assert bucket_index(confidence) == expected


def test_boundary_values_land_in_the_right_bucket(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    for conf in (0.549, 0.55, 0.60, 0.70, 0.80, 1.0):
        _signal(db_session, strat, inst, conf)
    db_session.flush()

    report = signal_calibration(db_session, strategy_id=strat.id)
    buckets = _by_lower(report)
    assert [b.n for b in report.buckets] == [1, 1, 1, 2]
    assert buckets[0.80].upper == 1.0
    assert report.excluded_below_min == 1
    assert report.total_scored == 6
    assert sum(b.n for b in report.buckets) + report.excluded_below_min == report.total_scored


# ------------------------------------------------------------------ signals --


def test_only_target_hit_is_a_win(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    _signal(db_session, strat, inst, 0.72, "TARGET_HIT", 0.08)
    _signal(db_session, strat, inst, 0.74, "STOP_LOSS_HIT", -0.04)
    _signal(db_session, strat, inst, 0.76, "EXPIRED_NO_HIT", 0.05)
    _signal(db_session, strat, inst, 0.78, "EXPIRED_NO_HIT", -0.01)
    db_session.flush()

    bucket = _by_lower(signal_calibration(db_session, strategy_id=strat.id))[0.70]
    assert bucket.n == 4
    assert bucket.wins == 1
    assert bucket.observed_rate == pytest.approx(0.25)
    assert bucket.mean_confidence == pytest.approx(0.75)
    assert bucket.calibration_gap == pytest.approx(-0.50)
    assert bucket.mean_outcome_pct == pytest.approx(0.02)
    assert bucket.worst_outcome_pct == pytest.approx(-0.04)
    assert bucket.meaningful is False


def test_unscored_and_confidence_less_signals_are_ignored(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    _signal(db_session, strat, inst, 0.65, outcome=None, outcome_pct=None)
    _signal(db_session, strat, inst, None, "TARGET_HIT")
    _signal(db_session, strat, inst, 0.65, "TARGET_HIT")
    db_session.flush()

    report = signal_calibration(db_session, strategy_id=strat.id)
    assert report.total_scored == 1
    assert _by_lower(report)[0.60].n == 1


def test_meaningful_flips_at_thirty(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    for _ in range(29):
        _signal(db_session, strat, inst, 0.62)
    db_session.flush()
    assert _by_lower(signal_calibration(db_session, strategy_id=strat.id))[0.60].meaningful is False

    _signal(db_session, strat, inst, 0.62)
    db_session.flush()
    bucket = _by_lower(signal_calibration(db_session, strategy_id=strat.id))[0.60]
    assert bucket.n == 30
    assert bucket.meaningful is True


def test_signal_filters_on_mode_and_since(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    _signal(db_session, strat, inst, 0.65, mode="paper", generated_at=START)
    _signal(db_session, strat, inst, 0.65, mode="live", generated_at=START)
    _signal(db_session, strat, inst, 0.65, mode="paper", generated_at=START + timedelta(days=10))
    db_session.flush()

    assert signal_calibration(db_session, strategy_id=strat.id).total_scored == 2
    assert signal_calibration(db_session, strategy_id=strat.id, mode="live").total_scored == 1
    later = signal_calibration(db_session, strategy_id=strat.id, since=START + timedelta(days=1))
    assert later.total_scored == 1
    assert later.since == START + timedelta(days=1)


def test_brier_score_over_included_rows_only(db_session):
    from swing_trade_ml.ml.calibration import signal_calibration

    strat, inst = _strategy(db_session), _instrument(db_session)
    _signal(db_session, strat, inst, 0.80, "TARGET_HIT")  # (0.8-1)^2 = 0.04
    _signal(db_session, strat, inst, 0.60, "STOP_LOSS_HIT", -0.04)  # 0.36
    _signal(db_session, strat, inst, 0.10, "TARGET_HIT")  # excluded
    db_session.flush()

    report = signal_calibration(db_session, strategy_id=strat.id)
    assert report.brier_score == pytest.approx(0.20)


def test_empty_data_returns_empty_buckets(db_session):
    from swing_trade_ml.ml.calibration import prediction_calibration, signal_calibration

    strat = _strategy(db_session)
    report = signal_calibration(db_session, strategy_id=strat.id)
    assert report.total_scored == 0
    assert report.excluded_below_min == 0
    assert report.brier_score is None
    assert len(report.buckets) == 4
    for bucket in report.buckets:
        assert bucket.n == 0
        assert bucket.observed_rate is None
        assert bucket.calibration_gap is None
        assert bucket.meaningful is False

    model = _model(db_session)
    preds = prediction_calibration(db_session, model_id=model.id)
    assert preds.total_scored == 0
    assert all(b.observed_rate is None for b in preds.buckets)


# -------------------------------------------------------------- predictions --


def test_prediction_report_ignores_was_correct(db_session):
    """was_correct disagrees with the real outcome on every row here; the
    report must follow actual_return against the model's target."""
    from swing_trade_ml.ml.calibration import prediction_calibration

    model, inst = _model(db_session), _instrument(db_session)
    # Target hit, but a class-0 call so was_correct is False — still a win.
    _prediction(db_session, model, inst, 0.58, 0.08 + 1e-12, was_correct=False, predicted_class=0)
    # Stopped out, class-0 call so was_correct is True — still a loss.
    _prediction(db_session, model, inst, 0.57, -0.04, was_correct=True, predicted_class=0)
    # Went nowhere, flagged correct — a loss.
    _prediction(db_session, model, inst, 0.56, 0.01, was_correct=True, predicted_class=0)
    # Low-probability class-0 row that went nowhere: "correct", but excluded.
    _prediction(db_session, model, inst, 0.15, 0.0, was_correct=True, predicted_class=0)
    # Not yet evaluated: ignored entirely.
    _prediction(db_session, model, inst, 0.59, None, evaluated=False)
    db_session.flush()

    report = prediction_calibration(db_session, model_id=model.id)
    assert report.source == "predictions"
    assert report.total_scored == 4
    assert report.excluded_below_min == 1
    bucket = _by_lower(report)[0.55]
    assert bucket.n == 3
    assert bucket.wins == 1
    assert bucket.observed_rate == pytest.approx(1 / 3)
    assert bucket.worst_outcome_pct == pytest.approx(-0.04)


def test_win_uses_the_owning_models_target(db_session):
    from swing_trade_ml.ml.calibration import prediction_calibration

    inst = _instrument(db_session)
    wide = _model(db_session, name="wide", target=0.10)
    _prediction(db_session, wide, inst, 0.65, 0.08, was_correct=True)
    db_session.flush()

    assert _by_lower(prediction_calibration(db_session, model_id=wide.id))[0.60].wins == 0


def test_endpoint_and_barrier_rows_never_mix(db_session):
    from swing_trade_ml.ml.calibration import prediction_calibration

    inst = _instrument(db_session)
    barrier = _model(db_session, name="cal_barrier", label_kind="barrier")
    endpoint = _model(db_session, name="cal_endpoint", label_kind="endpoint")
    _prediction(db_session, barrier, inst, 0.65, 0.08)
    _prediction(db_session, barrier, inst, 0.66, -0.04)
    _prediction(db_session, endpoint, inst, 0.75, 0.09)
    # An old endpoint-era row written by the barrier model's id still counts
    # as endpoint: the row's recorded question wins, not the model's.
    _prediction(db_session, barrier, inst, 0.85, 0.12, label_kind="endpoint")
    db_session.flush()

    b = prediction_calibration(db_session, label_kind="barrier")
    assert b.label_kind == "barrier"
    assert [x.n for x in b.buckets] == [0, 2, 0, 0]

    e = prediction_calibration(db_session, label_kind="endpoint")
    assert [x.n for x in e.buckets] == [0, 0, 1, 1]
    assert e.total_scored == 2


# ---------------------------------------------------------------------- api --


def test_calibration_endpoint_signals(client, db_session):
    strat, inst = _strategy(db_session), _instrument(db_session)
    _signal(db_session, strat, inst, 0.72, "TARGET_HIT")
    _signal(db_session, strat, inst, 0.50, "STOP_LOSS_HIT", -0.04)
    db_session.flush()

    resp = client.get(f"/api/v1/ml/calibration?strategy_id={strat.id}", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "signals"
    assert body["mode"] == "paper"
    assert body["strategy_id"] == strat.id
    assert body["total_scored"] == 2
    assert body["excluded_below_min"] == 1
    assert len(body["buckets"]) == 4
    top = next(b for b in body["buckets"] if b["lower"] == 0.70)
    assert top["n"] == 1
    assert top["observed_rate"] == 1.0
    assert top["meaningful"] is False
    assert set(top) >= {
        "lower", "upper", "n", "wins", "observed_rate", "mean_confidence",
        "calibration_gap", "mean_outcome_pct", "worst_outcome_pct", "meaningful",
    }


def test_calibration_endpoint_predictions(client, db_session):
    model, inst = _model(db_session), _instrument(db_session)
    _prediction(db_session, model, inst, 0.81, 0.08, was_correct=False)
    db_session.flush()

    resp = client.get(
        f"/api/v1/ml/calibration?source=predictions&model_id={model.id}&label_kind=barrier",
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "predictions"
    assert body["model_id"] == model.id
    assert body["label_kind"] == "barrier"
    assert body["buckets"][3]["wins"] == 1


def test_calibration_endpoint_rejects_unknown_source(client):
    resp = client.get("/api/v1/ml/calibration?source=trades", headers=HEADERS)
    assert resp.status_code == 422


def test_calibration_endpoint_requires_api_key(client):
    resp = client.get("/api/v1/ml/calibration")
    assert resp.status_code in (401, 403)
