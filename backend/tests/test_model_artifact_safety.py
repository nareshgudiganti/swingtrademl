"""H1: model version allocation and artifact publishing are concurrency-safe, and a model file is checked
against its ml_models row before it can be activated. No schema change: the file hash lives in
metrics["artifact_sha256"], the key the model-registry screen already reads."""

from __future__ import annotations

import hashlib
import inspect

import joblib
import pytest
from sqlalchemy import text

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import registry

FEATURES = ["rsi_14", "macd"]


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    return tmp_path


def _row(db, name, version, **kw):
    kw.setdefault("status", ModelStatus.TRAINED)
    kw.setdefault("feature_names", FEATURES)
    m = MLModel(name=name, version=version, algorithm="lightgbm", **kw)
    db.add(m)
    db.flush()
    return m


def _published(db, name, features=FEATURES, **kw):
    """A row whose file was published the way the trainers publish it."""
    version = registry.next_version(db, name)
    path = registry.save_artifact(name, version, {"estimator": None, "feature_names": features})
    return _row(
        db,
        name,
        version,
        artifact_path=path,
        metrics={"artifact_sha256": registry.artifact_sha256(path)},
        **kw,
    )


# ------------------------------------------------------------------ version allocation


def test_a_deleted_middle_version_is_never_handed_out_again(db_session, model_dir):
    _row(db_session, "h1_model", "v1")
    _row(db_session, "h1_model", "v3")  # v2 was deleted; counting rows would say v3 again
    assert registry.next_version(db_session, "h1_model") == "v4"


def test_a_version_whose_file_is_already_on_disk_is_skipped(db_session, model_dir):
    _row(db_session, "h1_orphan", "v1")
    (model_dir / "h1_orphan_v2.joblib").write_bytes(
        b"left behind by a run that crashed before its row was saved"
    )
    assert registry.next_version(db_session, "h1_orphan") == "v3"


def test_odd_version_strings_never_lower_the_next_number(db_session, model_dir):
    _row(db_session, "h1_odd", "v1")
    _row(db_session, "h1_odd", "fold_2024")
    assert registry.next_version(db_session, "h1_odd") == "v3"


def test_the_version_lock_is_held_until_the_transaction_ends_and_only_for_that_name(
    db_session, db_engine, model_dir
):
    registry.next_version(db_session, "h1_locked")
    with db_engine.connect() as other:
        try:
            same = other.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": registry.name_lock_key("h1_locked")}
            ).scalar()
            different = other.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": registry.name_lock_key("h1_other")}
            ).scalar()
        finally:
            other.rollback()
    assert same is False, "a second trainer of the same name must wait for this one to commit"
    assert different is True


# ------------------------------------------------------------------ publishing the file


def test_an_existing_model_file_is_never_overwritten(db_session, model_dir):
    path = registry.save_artifact("h1_save", "v1", {"estimator": "first", "feature_names": FEATURES})
    with pytest.raises(FileExistsError):
        registry.save_artifact("h1_save", "v1", {"estimator": "second", "feature_names": FEATURES})
    assert joblib.load(path)["estimator"] == "first"
    assert sorted(p.name for p in model_dir.iterdir()) == ["h1_save_v1.joblib"], "no temp files left behind"


def test_the_saved_file_names_its_own_model_and_version(db_session, model_dir):
    path = registry.save_artifact("h1_ident", "v7", {"estimator": None, "feature_names": FEATURES})
    bundle = joblib.load(path)
    assert bundle["model_name"] == "h1_ident" and bundle["model_version"] == "v7"


def test_the_recorded_hash_is_the_sha256_of_the_file(db_session, model_dir):
    path = registry.save_artifact("h1_hash", "v1", {"estimator": None, "feature_names": FEATURES})
    with open(path, "rb") as fh:
        assert registry.artifact_sha256(path) == hashlib.sha256(fh.read()).hexdigest()


# ------------------------------------------------------------------ checking a file against its row


def test_a_matching_file_loads(db_session, model_dir):
    m = _published(db_session, "h1_ok")
    assert registry.load_model_artifact(m)["feature_names"] == FEATURES


def test_a_changed_file_is_refused(db_session, model_dir):
    m = _published(db_session, "h1_changed")
    joblib.dump(
        {"estimator": "swapped", "feature_names": FEATURES, "model_name": m.name, "model_version": m.version},
        m.artifact_path,
    )
    with pytest.raises(registry.ArtifactMismatchError, match="hash"):
        registry.load_model_artifact(m)


def test_a_missing_file_is_refused(db_session, model_dir):
    m = _published(db_session, "h1_missing")
    (model_dir / f"{m.name}_{m.version}.joblib").unlink()
    with pytest.raises(registry.ArtifactMismatchError, match="missing"):
        registry.load_model_artifact(m)


def test_a_row_without_a_file_path_is_refused(db_session, model_dir):
    m = _row(db_session, "h1_nopath", "v1", artifact_path=None)
    with pytest.raises(registry.ArtifactMismatchError, match="no model file"):
        registry.load_model_artifact(m)


def test_different_inputs_from_the_row_are_refused(db_session, model_dir):
    m = _published(db_session, "h1_inputs", features=["rsi_14"])
    with pytest.raises(registry.ArtifactMismatchError, match="inputs"):
        registry.load_model_artifact(m)


def test_a_file_that_names_another_version_is_refused(db_session, model_dir):
    path = registry.save_artifact("h1_wrong", "v9", {"estimator": None, "feature_names": FEATURES})
    m = _row(
        db_session,
        "h1_wrong",
        "v1",
        artifact_path=path,
        metrics={"artifact_sha256": registry.artifact_sha256(path)},
    )
    with pytest.raises(registry.ArtifactMismatchError, match="v9"):
        registry.load_model_artifact(m)


def test_an_older_model_without_a_recorded_hash_still_loads_so_rollback_keeps_working(db_session, model_dir):
    path = model_dir / "h1_legacy_v1.joblib"
    joblib.dump({"estimator": None, "scaler": None, "feature_names": FEATURES}, path)
    m = _row(db_session, "h1_legacy", "v1", artifact_path=str(path), metrics={"roc_auc": 0.6})
    assert registry.load_model_artifact(m)["feature_names"] == FEATURES


# ------------------------------------------------------------------ activation


def test_activation_refuses_a_bad_file_and_keeps_the_current_model_active(db_session, model_dir):
    current = _published(db_session, "h1_act", status=ModelStatus.ACTIVE)
    bad = _published(db_session, "h1_act")
    (model_dir / f"{bad.name}_{bad.version}.joblib").unlink()
    with pytest.raises(registry.ArtifactMismatchError):
        registry.activate_model(db_session, bad.id)
    db_session.refresh(current)
    db_session.refresh(bad)
    assert current.status == ModelStatus.ACTIVE and bad.status == ModelStatus.TRAINED


def test_activation_of_a_good_file_archives_the_previous_one(db_session, model_dir):
    old = _published(db_session, "h1_act2", status=ModelStatus.ACTIVE)
    new = _published(db_session, "h1_act2")
    registry.activate_model(db_session, new.id)
    db_session.refresh(old)
    assert new.status == ModelStatus.ACTIVE and old.status == ModelStatus.ARCHIVED


def test_activation_holds_the_same_name_lock_as_version_allocation(db_session, db_engine, model_dir):
    m = _published(db_session, "h1_actlock")
    db_session.commit = db_session.flush  # keep the transaction open so the lock can be observed
    registry.activate_model(db_session, m.id)
    with db_engine.connect() as other:
        try:
            got = other.execute(
                text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": registry.name_lock_key("h1_actlock")}
            ).scalar()
        finally:
            other.rollback()
    assert got is False


# ------------------------------------------------------------------ which trainers record the hash


def test_the_general_trainer_records_the_file_hash_on_its_row():
    from swing_trade_ml.ml.train import train_model

    src = inspect.getsource(train_model)
    assert 'metrics["artifact_sha256"]' in src and "artifact_sha256(path)" in src


@pytest.mark.parametrize(
    "module, func",
    [
        # Signed experiment protocols freeze these files byte-for-byte (fd-protocol-v1, sl-protocol-v1.1):
        # they must not be edited to record the hash. Their rows stay "no recorded hash", like older models.
        ("swing_trade_ml.brain.five_day_train", "train_endpoint_model"),
        ("swing_trade_ml.brain.selection_lab", "train_lab_model"),
    ],
)
def test_protocol_frozen_trainers_are_left_untouched(module, func):
    import importlib

    assert "artifact_sha256" not in inspect.getsource(getattr(importlib.import_module(module), func))


# ------------------------------------------------------------------ review fixes (Codex 2026-11-19)


def test_without_hard_links_saving_fails_clearly_and_never_creates_the_final_file(
    db_session, model_dir, monkeypatch
):
    # A copy-in fallback makes the final name visible while it is empty or half-written, and a process kill
    # mid-copy leaves a partial model under the real name (Codex follow-up review 2026-11-19, issue 4).
    # Without a one-step no-replace publish, saving must stop before the final name exists.
    target = model_dir / "h1_nolink_v1.joblib"

    def no_links(src, dst):
        raise PermissionError("hard links not supported")

    def replace_forbidden(*a, **k):
        raise AssertionError("os.replace can overwrite a file another writer just published")

    monkeypatch.setattr(registry.os, "link", no_links)
    monkeypatch.setattr(registry.os, "replace", replace_forbidden)
    with pytest.raises(registry.ArtifactPublishError, match="hard link"):
        registry.save_artifact("h1_nolink", "v1", {"estimator": "mine", "feature_names": FEATURES})
    assert not target.exists()
    assert list(model_dir.iterdir()) == []  # the temporary file is cleaned up too


def test_without_hard_links_an_existing_file_is_left_untouched(db_session, model_dir, monkeypatch):
    target = model_dir / "h1_race2_v1.joblib"
    target.write_bytes(b"the other writer's model")

    def no_links(src, dst):
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(registry.os, "link", no_links)
    with pytest.raises(registry.ArtifactPublishError):
        registry.save_artifact("h1_race2", "v1", {"estimator": "mine", "feature_names": FEATURES})
    assert target.read_bytes() == b"the other writer's model"
    assert [p.name for p in model_dir.iterdir()] == ["h1_race2_v1.joblib"]


def test_the_publish_error_is_an_oserror_so_existing_file_error_handling_still_applies():
    assert issubclass(registry.ArtifactPublishError, OSError)
    assert not issubclass(registry.ArtifactPublishError, FileExistsError)


def test_a_corrupt_older_file_is_refused_and_the_current_model_stays_active(db_session, model_dir):
    current = _published(db_session, "h1_corrupt", status=ModelStatus.ACTIVE)
    path = model_dir / "h1_corrupt_legacy.joblib"
    joblib.dump({"estimator": None, "feature_names": FEATURES}, path)
    path.write_bytes(path.read_bytes()[:20])  # truncated; no recorded hash, so only reading it can tell
    old = _row(db_session, "h1_corrupt", "v99", artifact_path=str(path), metrics={})
    with pytest.raises(registry.ArtifactMismatchError, match="could not be read"):
        registry.activate_model(db_session, old.id)
    db_session.refresh(current)
    assert current.status == ModelStatus.ACTIVE and old.status == ModelStatus.TRAINED


def test_the_activate_endpoint_turns_a_corrupt_file_into_a_400_not_a_server_error(
    db_session, model_dir, monkeypatch
):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    path = model_dir / "h1_corrupt_api.joblib"
    path.write_bytes(b"not a joblib file")
    m = _row(db_session, "h1_corrupt_api", "v1", artifact_path=str(path), metrics={})
    monkeypatch.setattr(ml_ep, "promotion_refusal", lambda: None)
    with pytest.raises(HTTPException) as exc:
        ml_ep.activate(m.id, db=db_session)
    assert exc.value.status_code == 400


# ------------------------------------------------------------------ a file that cannot be read (I/O error)


class _Row:
    """A plain stand-in for an ml_models row: load_model_artifact only reads these five attributes."""

    def __init__(self, path, *, sha="0" * 64):
        self.name, self.version = "h1_ioerr", "v1"
        self.artifact_path = str(path)
        self.metrics = {"artifact_sha256": sha}
        self.feature_names = FEATURES


def _denied(*args, **kwargs):
    raise PermissionError(13, "access denied", "C:/private/secret-folder/models/h1_ioerr_v1.joblib")


def test_an_io_error_while_hashing_is_refused_as_unreadable_not_raised(tmp_path, monkeypatch):
    path = tmp_path / "h1_ioerr_v1.joblib"
    path.write_bytes(b"x")
    monkeypatch.setattr(registry, "artifact_sha256", _denied)
    with pytest.raises(registry.ArtifactMismatchError, match="could not be read") as exc:
        registry.load_model_artifact(_Row(path))
    message = str(exc.value)
    assert "h1_ioerr_v1.joblib" in message  # the file name only
    assert str(tmp_path) not in message and "secret-folder" not in message and "access denied" not in message


def test_an_io_error_while_checking_the_file_is_refused_as_unreadable_not_raised(tmp_path, monkeypatch):
    path = tmp_path / "h1_ioerr_v1.joblib"
    path.write_bytes(b"x")
    with monkeypatch.context() as scoped:
        scoped.setattr(type(path), "is_file", _denied)
        with pytest.raises(registry.ArtifactMismatchError, match="could not be read") as exc:
            registry.load_model_artifact(_Row(path))
    assert "secret-folder" not in str(exc.value) and str(tmp_path) not in str(exc.value)


def test_activation_with_an_unreadable_file_keeps_the_incumbent_and_writes_nothing(
    db_session, model_dir, monkeypatch
):
    current = _published(db_session, "h1_ioerr_act", status=ModelStatus.ACTIVE)
    candidate = _published(db_session, "h1_ioerr_act")
    monkeypatch.setattr(registry, "artifact_sha256", _denied)
    with pytest.raises(registry.ArtifactMismatchError, match="could not be read"):
        registry.activate_model(db_session, candidate.id)
    db_session.refresh(current)
    db_session.refresh(candidate)
    assert current.status == ModelStatus.ACTIVE and candidate.status == ModelStatus.TRAINED
    assert candidate.activated_at is None


def test_the_activate_endpoint_turns_an_unreadable_file_into_a_400_and_writes_nothing(
    db_session, model_dir, monkeypatch
):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    current = _published(db_session, "h1_ioerr_api", status=ModelStatus.ACTIVE)
    candidate = _published(db_session, "h1_ioerr_api")
    monkeypatch.setattr(ml_ep, "promotion_refusal", lambda: None)
    monkeypatch.setattr(registry, "artifact_sha256", _denied)
    with pytest.raises(HTTPException) as exc:
        ml_ep.activate(candidate.id, db=db_session)
    assert exc.value.status_code == 400
    assert "could not be read" in exc.value.detail and "secret-folder" not in exc.value.detail
    db_session.refresh(current)
    db_session.refresh(candidate)
    assert current.status == ModelStatus.ACTIVE and candidate.status == ModelStatus.TRAINED
