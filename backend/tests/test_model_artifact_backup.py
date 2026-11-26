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


def test_every_run_leaves_a_record_even_when_nothing_new_was_copied(db_session, tmp_path):
    """Artifacts never change, so most days copy nothing. The record is how the health check
    knows the job still ran (found on prod 2026-10-14: a false "backup may have stopped")."""
    from swing_trade_ml.ml.backup import read_run_record

    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    (source / "m_v1.joblib").write_bytes(b"ok")
    _model(db_session, "m", "v1", source / "m_v1.joblib")

    backup_model_artifacts(db_session, destination=destination)
    backup_model_artifacts(db_session, destination=destination)

    record = read_run_record(destination)
    assert record is not None
    assert record["copied"] == 0 and record["already_present"] == 1 and record["missing"] == []


# ------------------------------------------------------- #328: model cards travel with their model file


def _carded_model(db_session, source, name="lab", version="v1", card=b'{"artifact_sha256": "x"}'):
    artifact = source / f"{name}_{version}.joblib"
    artifact.write_bytes(b"fitted-estimator-" + name.encode())
    (source / f"{artifact.name}.card.json").write_bytes(card)
    return _model(db_session, name, version, artifact), artifact


def test_a_model_card_is_backed_up_beside_its_model_file(db_session, tmp_path):
    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    _carded_model(db_session, source)
    (source / "plain_v1.joblib").write_bytes(b"no card")
    _model(db_session, "plain", "v1", source / "plain_v1.joblib")

    result = backup_model_artifacts(db_session, destination=destination)

    assert result["copied"] == 2 and result["cards_copied"] == 1
    assert (destination / "lab_v1.joblib.card.json").read_bytes() == b'{"artifact_sha256": "x"}'
    assert not (destination / "plain_v1.joblib.card.json").exists()


def test_rerunning_the_backup_never_duplicates_a_card_and_recopies_a_repaired_one(db_session, tmp_path):
    from swing_trade_ml.ml.backup import read_run_record

    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    _carded_model(db_session, source)
    backup_model_artifacts(db_session, destination=destination)
    second = backup_model_artifacts(db_session, destination=destination)
    assert second["cards_copied"] == 0 and second["cards_present"] == 1
    names = sorted(p.name for p in destination.iterdir())
    assert names == ["lab_v1.joblib", "lab_v1.joblib.card.json", "last-run.json"]

    # A repaired card (same size, different bytes) replaces the old copy; the model file is never recopied.
    (source / "lab_v1.joblib.card.json").write_bytes(b'{"artifact_sha256": "y"}')
    third = backup_model_artifacts(db_session, destination=destination)
    assert third["cards_copied"] == 1 and third["copied"] == 0
    assert (destination / "lab_v1.joblib.card.json").read_bytes() == b'{"artifact_sha256": "y"}'
    assert read_run_record(destination)["cards_copied"] == 1


def test_restoring_from_the_backup_brings_back_model_file_and_card_with_matching_sha256(db_session, tmp_path):
    """The round trip: record (manifest) -> back up -> lose the model folder -> restore from the backup ->
    every model file and every card hash-verifies against the record, and the card names the restored file."""
    import hashlib
    import json
    import shutil

    from swing_trade_ml.ml import backup_manifest as bm

    source, destination = tmp_path / "models", tmp_path / "backup"
    source.mkdir()
    artifact = source / "lab_v1.joblib"
    artifact.write_bytes(b"fitted-estimator-lab")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (source / "lab_v1.joblib.card.json").write_text(json.dumps({"artifact_sha256": sha}), encoding="utf-8")
    general = source / "gen_v2.joblib"
    general.write_bytes(b"general")
    gen_sha = hashlib.sha256(b"general").hexdigest()
    lab = _model(db_session, "lab", "v1", artifact)
    gen = _model(db_session, "gen", "v2", general)
    gen.metrics = {"card": {"artifact_sha256": gen_sha}}  # ml/train.py keeps its card in the row
    rows = [
        {
            "id": m.id,
            "name": m.name,
            "version": m.version,
            "status": m.status,
            "artifact_path": m.artifact_path,
            "card_artifact_sha256": (m.metrics or {}).get("card", {}).get("artifact_sha256"),
        }
        for m in (lab, gen)
    ]
    manifest = bm.build_manifest(rows, source)
    assert [c["file"] for c in manifest["cards"]] == ["lab_v1.joblib.card.json"]

    backup_model_artifacts(db_session, destination=destination)
    before = bm.hash_folder(source)
    shutil.rmtree(source)  # the disk is lost
    restored = tmp_path / "restored"
    restored.mkdir()
    for p in destination.iterdir():
        if p.name != "last-run.json":
            shutil.copy2(p, restored / p.name)

    assert bm.hash_folder(restored) == before
    report = bm.compare(manifest, rows, bm.hash_folder(restored))
    assert report["ok"], report["problems"]
    assert report["files_verified"] == 3  # two model files + one card
    card = json.loads((restored / "lab_v1.joblib.card.json").read_text(encoding="utf-8"))
    assert card["artifact_sha256"] == hashlib.sha256((restored / "lab_v1.joblib").read_bytes()).hexdigest()
