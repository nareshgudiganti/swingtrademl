"""Three trained model files were lost once. Nothing replaced them.

An MLModel row survives the loss of its artifact — it keeps the metrics, the
label triple and the feature list, and its artifact_path points at nothing. So
the registry looks intact right up to the moment something tries to score with
it. A second copy is the whole defence.

The backup is deliberately a plain directory copy rather than an upload: the
destination is configuration, so it can be a mounted volume, a synced folder
or an object-storage mount without this module knowing which.
"""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.backup import backup_model_artifacts


def _model(db_session, name: str, version: str, path, *, status: str = "ACTIVE") -> MLModel:
    model = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        artifact_path=str(path),
        feature_names=["a", "b"],
        trained_at=datetime.now(UTC),
    )
    db_session.add(model)
    db_session.flush()
    return model


def test_every_registered_artifact_is_copied(db_session, tmp_path):
    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    for name in ("swing_classifier_v3.joblib", "swing_classifier_midcap_v1.joblib"):
        (source / name).write_bytes(b"fitted-estimator")
    _model(db_session, "swing_classifier", "v3", source / "swing_classifier_v3.joblib")
    _model(db_session, "swing_classifier_midcap", "v1", source / "swing_classifier_midcap_v1.joblib")

    result = backup_model_artifacts(db_session, destination=destination)

    assert result["copied"] == 2
    assert result["missing"] == []
    assert (destination / "swing_classifier_v3.joblib").read_bytes() == b"fitted-estimator"


def test_an_artifact_that_has_already_vanished_is_reported_not_silently_skipped(db_session, tmp_path):
    """The one failure this job exists to catch. A missing file has to be
    loud, because the registry row alone gives no hint anything is wrong."""
    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    (source / "present_v1.joblib").write_bytes(b"ok")
    _model(db_session, "present", "v1", source / "present_v1.joblib")
    _model(db_session, "vanished", "v2", source / "vanished_v2.joblib")

    result = backup_model_artifacts(db_session, destination=destination)

    assert result["copied"] == 1
    assert result["missing"] == ["vanished:v2"]


def test_an_unchanged_artifact_is_not_recopied(db_session, tmp_path):
    """Artifacts are immutable once written, so a daily job should move no
    bytes on a day with no training."""
    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    (source / "stable_v1.joblib").write_bytes(b"fitted-estimator")
    _model(db_session, "stable", "v1", source / "stable_v1.joblib")

    backup_model_artifacts(db_session, destination=destination)
    second = backup_model_artifacts(db_session, destination=destination)

    assert second["copied"] == 0
    assert second["already_present"] == 1


def test_archived_versions_are_backed_up_too(db_session, tmp_path):
    """Rollback is the reason the registry keeps old versions at all. A backup
    that only held the active model would make rollback impossible after a
    disk loss, which is exactly when it is needed."""
    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    (source / "swing_classifier_v1.joblib").write_bytes(b"old")
    (source / "swing_classifier_v2.joblib").write_bytes(b"new")
    _model(db_session, "swing_classifier", "v1", source / "swing_classifier_v1.joblib", status="ARCHIVED")
    _model(db_session, "swing_classifier", "v2", source / "swing_classifier_v2.joblib")

    result = backup_model_artifacts(db_session, destination=destination)

    assert result["copied"] == 2


def test_no_destination_configured_is_a_no_op_that_says_so(db_session, tmp_path):
    """Disabled by default, because the destination is infrastructure this
    module cannot invent. It must not look like it succeeded."""
    source = tmp_path / "models"
    source.mkdir()
    (source / "m_v1.joblib").write_bytes(b"ok")
    _model(db_session, "m", "v1", source / "m_v1.joblib")

    result = backup_model_artifacts(db_session, destination=None)

    assert result["enabled"] is False
    assert result["copied"] == 0
