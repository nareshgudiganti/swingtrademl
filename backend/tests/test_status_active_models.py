"""/status lists EVERY active model, one per company size, not just the one
switched on last — production runs three at once (large, mid, small)."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.ml import MLModel

HEADERS = {"X-API-Key": "test-api-key"}


def _model(db, name: str, version: str, status: str, at: datetime) -> None:
    db.add(
        MLModel(
            name=name,
            version=version,
            algorithm="dummy",
            status=status,
            artifact_path=f"/tmp/{name}-{version}.joblib",
            feature_names=["x"],
            prediction_horizon_days=15,
            activated_at=at,
        )
    )
    db.flush()


def test_status_lists_every_active_model(db_session, client):
    at = datetime(2026, 8, 28, 14, 8, tzinfo=UTC)
    _model(db_session, "stat_large", "v2", "ACTIVE", at)
    _model(db_session, "stat_small", "v1", "ACTIVE", at)
    _model(db_session, "stat_old", "v9", "ARCHIVED", at)
    db_session.commit()

    models = client.get("/api/v1/status", headers=HEADERS).json()["active_models"]

    assert "stat_large:v2" in models and "stat_small:v1" in models
    assert "stat_old:v9" not in models
    assert models == sorted(models)
