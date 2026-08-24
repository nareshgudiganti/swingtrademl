"""Regression test for a real incident: POST /ml/predict silently scored the
large-cap watchlist with whichever model was most recently activated across
EVERY tier, because the endpoint's own `model_name` default (None) shadowed
predict_watchlist()'s safe default ("swing_classifier") — a caller passing an
explicit None does not fall back to the callee's default. A mid/small-cap
promotion after this file's absence went undetected for roughly a day of live
use before it was caught by manual inspection, not by any test.

This only needs to prove which model_name predict_watchlist() gets called
with — running real inference would need a fitted model artifact and years of
candles, neither of which this bug lives in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.ml import MLModel


def _make_model(db_session, *, name: str, version: str, activated_at) -> MLModel:
    model = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status="ACTIVE",
        artifact_path=f"/app/data/models/{name}_{version}.joblib",
        activated_at=activated_at,
    )
    db_session.add(model)
    db_session.commit()
    return model


def test_predict_endpoint_uses_large_cap_model_even_when_a_smaller_tier_was_promoted_more_recently(
    client, db_session, monkeypatch,
):
    now = datetime.now(UTC)
    _make_model(db_session, name="swing_classifier", version="v2", activated_at=now - timedelta(days=10))
    _make_model(
        db_session, name="swing_classifier_smallcap", version="v1", activated_at=now - timedelta(hours=1)
    )

    captured: dict[str, object] = {}

    def fake_predict_watchlist(db, model_name=None, interval="day", persist=True):
        captured["model_name"] = model_name
        return []

    # api/v1/endpoints/ml.py calls `predict_service.predict_watchlist(...)` —
    # patching the attribute on the same module object it holds a reference to.
    import swing_trade_ml.ml.predict as predict_service

    monkeypatch.setattr(predict_service, "predict_watchlist", fake_predict_watchlist)

    client.post("/api/v1/ml/predict", headers={"X-API-Key": "test-api-key"})

    assert captured["model_name"] == "swing_classifier", (
        "the endpoint passed model_name through as None (or omitted it becoming None), "
        "which resolves to \"whichever model was activated most recently, across every "
        "tier\" — exactly the incident this test pins down"
    )


def test_predict_endpoint_honors_an_explicit_model_name(client, db_session, monkeypatch):
    """Sanity check alongside the above: passing a real model_name through
    still works, so the fix above is a narrower default, not a hardcode."""
    captured: dict[str, object] = {}

    def fake_predict_watchlist(db, model_name=None, interval="day", persist=True):
        captured["model_name"] = model_name
        return []

    import swing_trade_ml.ml.predict as predict_service

    monkeypatch.setattr(predict_service, "predict_watchlist", fake_predict_watchlist)

    client.post(
        "/api/v1/ml/predict",
        params={"model_name": "swing_classifier_midcap"},
        headers={"X-API-Key": "test-api-key"},
    )

    assert captured["model_name"] == "swing_classifier_midcap"
