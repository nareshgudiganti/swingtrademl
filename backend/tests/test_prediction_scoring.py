"""Outcome scoring for Prediction rows.

Until the barrier label landed this path had no test at all, while carrying
the one mistake that matters most: scoring a barrier prediction with the old
close-only rule marks a trade correct that the risk engine had already stopped
out days earlier. These pin the branch that prevents it.

See the plan's Stage 1.4, and docs/superpowers/research/2026-09-14-quant-gap-roadmap-to-10L.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction

START = datetime(2026, 1, 5, tzinfo=UTC)


def _instrument(db_session, tradingsymbol="BARTEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _model(db_session, *, label_kind="barrier", horizon=3, target=0.08, stop=0.04) -> MLModel:
    model = MLModel(
        name=f"m_{label_kind}_{horizon}",
        version="v1",
        algorithm="lightgbm",
        status="ACTIVE",
        artifact_path="/tmp/none.joblib",
        prediction_horizon_days=horizon,
        target_return_pct=target,
        stop_return_pct=stop if label_kind == "barrier" else None,
        label_kind=label_kind,
    )
    db_session.add(model)
    db_session.flush()
    return model


def _bars(db_session, instrument_id, bars):
    """bars: list of (high, low, close), one trading day apart from START."""
    for i, (h, low, c) in enumerate(bars, start=1):
        db_session.add(
            Candle(
                instrument_id=instrument_id, interval="day",
                ts=START + timedelta(days=i),
                open=c, high=h, low=low, close=c, volume=100_000,
            )
        )
    db_session.flush()


def _prediction(db_session, model, instrument, *, predicted_class=1, probability=0.71) -> Prediction:
    pred = Prediction(
        model_id=model.id, instrument_id=instrument.id, ts=START,
        predicted_class=predicted_class, probability=probability,
        price_at_prediction=100.0, features={}, label_kind=model.label_kind,
    )
    db_session.add(pred)
    db_session.flush()
    return pred


# Barriers for an entry at 100: target 108, stop 96.
FLAT = (100.5, 99.5, 100.0)


def test_target_touched_first_is_a_win(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session)
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=1)
    _bars(db_session, inst.id, [FLAT, (109.0, 99.0, 108.5), (100.0, 90.0, 95.0)])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is True
    assert pred.actual_return == 0.08


def test_stop_touched_first_is_a_loss_even_if_it_recovers(db_session):
    """The failure the close-only rule could not see. Price breaks the stop,
    then rallies past the target inside the same window — the old evaluator
    would have called this prediction correct."""
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session)
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=1)
    _bars(db_session, inst.id, [FLAT, (100.0, 95.0, 96.0), (112.0, 100.0, 111.0)])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is False
    assert pred.actual_return == -0.04


def test_same_bar_touch_of_both_barriers_scores_as_a_stop(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session)
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=1)
    _bars(db_session, inst.id, [FLAT, (109.0, 95.0, 100.0), FLAT])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is False


def test_an_incomplete_window_is_not_scored_yet(db_session):
    """Only two of the three bars have traded, and neither barrier was
    touched, so the outcome is genuinely unknown. Dated recently, because a
    window that is merely young must stay open."""
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    recent = datetime.now(UTC) - timedelta(days=3)
    inst = _instrument(db_session, "YOUNGWINDOW")
    model = _model(db_session)
    pred = Prediction(
        model_id=model.id, instrument_id=inst.id, ts=recent,
        predicted_class=1, probability=0.7,
        price_at_prediction=100.0, features={}, label_kind="barrier",
    )
    db_session.add(pred)
    db_session.flush()
    for i, (h, low, c) in enumerate([FLAT, FLAT], start=1):
        db_session.add(
            Candle(
                instrument_id=inst.id, interval="day", ts=recent + timedelta(days=i),
                open=c, high=h, low=low, close=c, volume=100_000,
            )
        )
    db_session.flush()

    assert evaluate_pending_predictions(db_session) == 0
    db_session.refresh(pred)
    assert pred.evaluated_at is None


def test_a_long_stale_window_settles_rather_than_pending_forever(db_session):
    """A delisted or gappy instrument would otherwise leave rows unscored for
    good, quietly shrinking every accuracy figure's sample."""
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session, "STALEWINDOW")
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=1)
    # START is months back, and only two of three bars ever traded.
    _bars(db_session, inst.id, [FLAT, (101.0, 99.0, 100.5)])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is False
    assert pred.actual_return == 0.005


def test_expiry_without_a_touch_is_a_loss(db_session):
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session)
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=1)
    _bars(db_session, inst.id, [FLAT, FLAT, (101.0, 99.0, 100.5)])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is False
    assert pred.actual_return == 0.005


def test_predicting_no_move_is_correct_when_the_stop_is_hit(db_session):
    """`was_correct` is agreement with the predicted class, not a win flag —
    a 0 prediction that goes on to be stopped out was right."""
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session)
    model = _model(db_session)
    pred = _prediction(db_session, model, inst, predicted_class=0, probability=0.18)
    _bars(db_session, inst.id, [FLAT, (100.0, 95.0, 96.0), FLAT])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is True


def test_an_endpoint_model_still_uses_the_close_only_rule(db_session):
    """Old models keep their old scoring. A barrier rule applied to them
    would be just as wrong in the other direction."""
    from swing_trade_ml.ml.predict import evaluate_pending_predictions

    inst = _instrument(db_session, "ENDPOINTTEST")
    model = _model(db_session, label_kind="endpoint", horizon=3, target=0.02)
    pred = _prediction(db_session, model, inst, predicted_class=1)

    # Dips well below any barrier, then closes higher: a win under the
    # close-only rule, which is exactly what this model was trained on.
    _bars(db_session, inst.id, [(100.0, 85.0, 90.0), FLAT, (103.0, 99.0, 102.5)])

    assert evaluate_pending_predictions(db_session) == 1
    db_session.refresh(pred)
    assert pred.was_correct is True
