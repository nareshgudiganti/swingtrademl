"""Model Lab's walk-forward card could never render, in any deployment.

The page reads `metrics.walk_forward` off every row of `GET /ml/models`
(frontend/src/pages/ModelLab.tsx) and hides the card when it finds none — but
`MLModelOut`, the schema that endpoint returns, has no `metrics` field at all.
Only `MLModelDetail` (`/ml/models/{id}`) carries it. So the strongest evidence
the product has about a model — that it was tested on time periods it never
trained on — was serialized away before it reached the browser, and the card
vanished silently rather than saying anything.

Found while explaining the page to the user, who could not work out why it
showed nothing. Silence looked identical to "no folds exist".
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.ml import MLModel

FOLD = {
    "fold": 1,
    "test_start": "2026-01-01T00:00:00Z",
    "test_end": "2026-03-31T00:00:00Z",
    "metrics": {
        "roc_auc": 0.58,
        "precision_at_threshold": 0.41,
        "confident_signal_count": 84,
    },
}


def _model(db_session, **overrides) -> MLModel:
    model = MLModel(
        name="swing_classifier",
        version="v9",
        algorithm="lightgbm",
        status=ModelStatus.ACTIVE,
        artifact_path="/app/data/models/swing_classifier_v9.joblib",
        trained_at=datetime(2026, 9, 1, tzinfo=UTC),
        activated_at=datetime(2026, 9, 2, tzinfo=UTC),
        **overrides,
    )
    db_session.add(model)
    db_session.commit()
    return model


def test_models_list_exposes_walk_forward_folds(client, db_session):
    """The list endpoint is the only call Model Lab makes, so the folds have to
    survive it."""
    _model(db_session, metrics={"walk_forward": [FOLD], "roc_auc": 0.56})

    rows = client.get("/api/v1/ml/models", headers={"X-API-Key": "test-api-key"}).json()

    assert len(rows) == 1
    folds = rows[0]["metrics"]["walk_forward"]
    assert len(folds) == 1
    assert folds[0]["metrics"]["roc_auc"] == 0.58


def test_a_model_without_folds_reports_empty_metrics_rather_than_omitting_them(
    client, db_session
):
    """An older model trained before walk-forward existed must still serialize,
    and must be distinguishable from one whose folds were dropped in transit."""
    _model(db_session, metrics={})

    rows = client.get("/api/v1/ml/models", headers={"X-API-Key": "test-api-key"}).json()

    assert rows[0]["metrics"] == {}
