"""#328: a model becomes active only through ml/promotion.py, with a recorded owner approval, validated
evidence (the model card names the exact file on disk), an audit_log row, and a rollback through the
same gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import promotion, registry

FEATURES = ["rsi_14", "macd"]


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def switch_on(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)


def _model(db, name, *, card=True, status=ModelStatus.TRAINED, **kw):
    """A row published the way the general trainer publishes it: file hash plus a model card naming it."""
    version = registry.next_version(db, name)
    path = registry.save_artifact(name, version, {"estimator": None, "feature_names": FEATURES})
    sha = registry.artifact_sha256(path)
    metrics = {"artifact_sha256": sha}
    if card:
        metrics["card"] = {"artifact_sha256": sha, "code_git_sha": "abc123"}
    m = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        feature_names=FEATURES,
        artifact_path=path,
        metrics=metrics,
        status=status,
        **kw,
    )
    if status == ModelStatus.ACTIVE:
        m.activated_at = datetime.now(UTC)
    db.add(m)
    db.flush()
    return m


def _approval(model, **kw):
    base = {
        "approver": "owner",
        "reason": "Beat the incumbent on the same rows in the h05 report",
        "evidence": ("docs/brain/evidence/report.md@abc123",),
        "artifact_sha256": model.metrics["artifact_sha256"],
        "approved_at": datetime.now(UTC),
        "protocol_verdict": "PASS",
    }
    base.update(kw)
    return promotion.Approval(**base)


def _audit_rows(db, action=None):
    stmt = select(AuditLog).where(AuditLog.target_type == "ml_model").order_by(AuditLog.id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(db.execute(stmt).scalars())


# ------------------------------------------------------------------ the happy path


def test_promote_activates_archives_the_incumbent_and_writes_one_audit_row(db_session, model_dir, switch_on):
    old = _model(db_session, "p_ok", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_ok")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    db_session.refresh(old)
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE and old.status == ModelStatus.ARCHIVED
    (row,) = _audit_rows(db_session, "model.promote")
    assert row.actor_label == "owner" and row.target_id == str(new.id)
    assert row.before["active_model_id"] == old.id
    assert row.before["active_artifact_sha256"] == old.metrics["artifact_sha256"]
    assert row.after["model_id"] == new.id and row.after["name"] == "p_ok"
    assert row.after["artifact_sha256"] == new.metrics["artifact_sha256"]
    assert row.after["reason"].startswith("Beat") and row.after["evidence"] == [
        "docs/brain/evidence/report.md@abc123"
    ]
    assert row.after["protocol_verdict"] == "PASS" and row.after["invoked_by"] == "test"


def test_first_promotion_of_a_name_records_no_incumbent(db_session, model_dir, switch_on):
    new = _model(db_session, "p_first")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    (row,) = _audit_rows(db_session, "model.promote")
    assert row.before["active_model_id"] is None


# ------------------------------------------------------------------ refusals: nothing changes


def _assert_unchanged(db, *models, statuses):
    for m, s in zip(models, statuses, strict=True):
        db.refresh(m)
        assert m.status == s
    assert _audit_rows(db) == []


def test_switch_off_refuses(db_session, model_dir, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    new = _model(db_session, "p_off")
    with pytest.raises(promotion.PromotionError, match="ALLOW_MODEL_PROMOTION"):
        promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


def test_no_approval_refuses(db_session, model_dir, switch_on):
    new = _model(db_session, "p_none")
    with pytest.raises(promotion.PromotionError, match="approval"):
        promotion.promote(db_session, new.id, None, invoked_by="test")  # type: ignore[arg-type]
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


@pytest.mark.parametrize(
    "change, match",
    [
        ({"approver": "  "}, "approver"),
        ({"reason": "ok"}, "reason"),
        ({"evidence": ()}, "evidence"),
        ({"evidence": ("",)}, "evidence"),
        ({"artifact_sha256": "not-a-hash"}, "sha256"),
        ({"approved_at": datetime(2026, 1, 1)}, "time zone"),
        ({"approved_at": datetime.now(UTC) + timedelta(hours=1)}, "future"),
        ({"approved_at": datetime.now(UTC) - timedelta(days=8)}, "older"),
    ],
)
def test_an_incomplete_approval_refuses(db_session, model_dir, switch_on, change, match):
    new = _model(db_session, "p_bad_appr")
    with pytest.raises(promotion.PromotionError, match=match):
        promotion.promote(db_session, new.id, _approval(new, **change), invoked_by="test")
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


def test_a_model_without_a_card_refuses(db_session, model_dir, switch_on):
    old = _model(db_session, "p_nocard", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_nocard", card=False)
    with pytest.raises(promotion.PromotionError, match="model card"):
        promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    _assert_unchanged(db_session, old, new, statuses=[ModelStatus.ACTIVE, ModelStatus.TRAINED])


def test_a_card_without_a_file_hash_refuses(db_session, model_dir, switch_on):
    new = _model(db_session, "p_cardnohash")
    new.metrics = {**new.metrics, "card": {"code_git_sha": "abc"}}
    db_session.flush()
    with pytest.raises(promotion.PromotionError, match="model card"):
        promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


def test_an_approval_for_a_different_file_refuses(db_session, model_dir, switch_on):
    new = _model(db_session, "p_otherfile")
    with pytest.raises(promotion.PromotionError, match="approved file"):
        promotion.promote(db_session, new.id, _approval(new, artifact_sha256="0" * 64), invoked_by="test")
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


def test_a_swapped_file_on_disk_refuses(db_session, model_dir, switch_on):
    old = _model(db_session, "p_swap", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_swap")
    with open(new.artifact_path, "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(promotion.PromotionError, match="file on disk"):
        promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    _assert_unchanged(db_session, old, new, statuses=[ModelStatus.ACTIVE, ModelStatus.TRAINED])


def test_a_missing_file_refuses(db_session, model_dir, switch_on):
    new = _model(db_session, "p_missing")
    (model_dir / f"{new.name}_{new.version}.joblib").unlink()
    with pytest.raises(promotion.PromotionError, match="file on disk"):
        promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    _assert_unchanged(db_session, new, statuses=[ModelStatus.TRAINED])


def test_an_unknown_model_refuses(db_session, model_dir, switch_on):
    probe = _model(db_session, "p_unknown")
    with pytest.raises(promotion.PromotionError, match="not found"):
        promotion.promote(db_session, 987654321, _approval(probe), invoked_by="test")


def test_an_already_active_model_refuses(db_session, model_dir, switch_on):
    cur = _model(db_session, "p_again", status=ModelStatus.ACTIVE)
    with pytest.raises(ValueError, match="status"):
        promotion.promote(db_session, cur.id, _approval(cur), invoked_by="test")
    assert _audit_rows(db_session) == []


# ------------------------------------------------------------------ rollback


def test_rollback_restores_the_previous_model_with_its_own_audit_row(db_session, model_dir, switch_on):
    old = _model(db_session, "p_rb", card=False, status=ModelStatus.ACTIVE)  # older models have no card
    new = _model(db_session, "p_rb")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    promoted = _audit_rows(db_session, "model.promote")[0]
    promotion.rollback(
        db_session, old.id, _approval(old, reason="New model misbehaved in practice"), invoked_by="test"
    )
    db_session.refresh(old)
    db_session.refresh(new)
    assert old.status == ModelStatus.ACTIVE and new.status == ModelStatus.ARCHIVED
    (row,) = _audit_rows(db_session, "model.rollback")
    assert row.target_id == str(old.id) and row.before["active_model_id"] == new.id
    assert row.after["undoes_audit_id"] == promoted.id and row.after["reason"].startswith("New model")


def test_rollback_needs_the_switch(db_session, model_dir, switch_on, monkeypatch):
    old = _model(db_session, "p_rb_off", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_rb_off")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    with pytest.raises(promotion.PromotionError, match="ALLOW_MODEL_PROMOTION"):
        promotion.rollback(db_session, old.id, _approval(old), invoked_by="test")
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE


def test_rollback_only_to_the_model_the_last_promotion_replaced(db_session, model_dir, switch_on):
    a = _model(db_session, "p_rb_who", status=ModelStatus.ARCHIVED)
    b = _model(db_session, "p_rb_who", status=ModelStatus.ACTIVE)
    c = _model(db_session, "p_rb_who")
    promotion.promote(db_session, c.id, _approval(c), invoked_by="test")
    with pytest.raises(promotion.PromotionError, match="replaced"):
        promotion.rollback(db_session, a.id, _approval(a), invoked_by="test")
    db_session.refresh(c)
    assert c.status == ModelStatus.ACTIVE and b.id  # b is the only allowed rollback target


def test_rollback_without_any_recorded_promotion_refuses(db_session, model_dir, switch_on):
    a = _model(db_session, "p_rb_never", status=ModelStatus.ARCHIVED)
    _model(db_session, "p_rb_never", status=ModelStatus.ACTIVE)
    with pytest.raises(promotion.PromotionError, match="no recorded promotion"):
        promotion.rollback(db_session, a.id, _approval(a), invoked_by="test")


def test_rollback_refuses_a_previous_file_that_changed_since(db_session, model_dir, switch_on):
    old = _model(db_session, "p_rb_swap", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_rb_swap")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    with open(old.artifact_path, "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(promotion.PromotionError, match="file on disk"):
        promotion.rollback(db_session, old.id, _approval(old), invoked_by="test")
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE


def test_rollback_refuses_when_the_active_model_changed_outside_the_gate(db_session, model_dir, switch_on):
    old = _model(db_session, "p_rb_drift", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_rb_drift")
    promotion.promote(db_session, new.id, _approval(new), invoked_by="test")
    new.status = ModelStatus.ARCHIVED  # someone changed the active model without promote()
    db_session.flush()
    with pytest.raises(promotion.PromotionError, match="changed"):
        promotion.rollback(db_session, old.id, _approval(old), invoked_by="test")


# ------------------------------------------------------------------ train.py auto_activate


def test_auto_activate_without_approval_refuses_before_training(monkeypatch):
    from swing_trade_ml.ml import train

    monkeypatch.setattr(train, "build_training_set", lambda *a, **k: pytest.fail("trained"), raising=False)
    with pytest.raises(ValueError, match="approval"):
        train.train_model(None, name="x", auto_activate=True)  # type: ignore[arg-type]


def test_auto_activate_goes_through_promote(monkeypatch):
    import inspect

    from swing_trade_ml.ml import train

    src = inspect.getsource(train.train_model)
    assert "promote(" in src and "activate_model" not in src


# ------------------------------------------------------------------ API


class _User:
    id = None
    username = "owner"
    role = "owner"


def _owner():
    from swing_trade_ml.api.deps import Principal

    return Principal(user=_User())  # type: ignore[arg-type]


def _request(model, **kw):
    from swing_trade_ml.api.v1.endpoints.ml import PromotionRequest

    base = {
        "reason": "Beat the incumbent on the same rows",
        "evidence": ["docs/report.md@abc"],
        "artifact_sha256": model.metrics["artifact_sha256"],
    }
    base.update(kw)
    return PromotionRequest(**base)


def test_api_activate_promotes_with_the_signed_in_owner_as_approver(
    db_session, model_dir, switch_on, monkeypatch
):
    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    monkeypatch.setattr(ml_ep.predict_service, "clear_cache", lambda: None)
    new = _model(db_session, "p_api")
    ml_ep.activate(new.id, payload=_request(new), db=db_session, principal=_owner())
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE
    (row,) = _audit_rows(db_session, "model.promote")
    assert row.actor_label == "owner" and row.after["invoked_by"] == "api"


def test_api_activate_refuses_missing_evidence_with_400(db_session, model_dir, switch_on):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    new = _model(db_session, "p_api_bad", card=False)
    with pytest.raises(HTTPException) as e:
        ml_ep.activate(new.id, payload=_request(new), db=db_session, principal=_owner())
    assert e.value.status_code == 400 and "model card" in e.value.detail


def test_api_activate_without_an_approval_body_is_refused(db_session, model_dir, switch_on):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    new = _model(db_session, "p_api_nobody")
    with pytest.raises(HTTPException) as e:
        ml_ep.activate(new.id, payload=None, db=db_session, principal=_owner())
    assert e.value.status_code == 400 and "approval" in e.value.detail
    db_session.refresh(new)
    assert new.status == ModelStatus.TRAINED


def test_api_activate_route_requires_owner_and_a_body():
    from swing_trade_ml.api.deps import require_owner
    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    for path in ("/ml/models/{model_id}/activate", "/ml/models/{model_id}/rollback"):
        (route,) = [r for r in ml_ep.router.routes if getattr(r, "path", None) == path]
        deps = [d.call for d in route.dependant.dependencies]
        assert require_owner in deps
        assert route.body_field is not None


def test_api_rollback_restores_previous(db_session, model_dir, switch_on, monkeypatch):
    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    monkeypatch.setattr(ml_ep.predict_service, "clear_cache", lambda: None)
    old = _model(db_session, "p_api_rb", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_api_rb")
    ml_ep.activate(new.id, payload=_request(new), db=db_session, principal=_owner())
    ml_ep.rollback(
        old.id, payload=_request(old, reason="Roll back after review"), db=db_session, principal=_owner()
    )
    db_session.refresh(old)
    assert old.status == ModelStatus.ACTIVE


def test_api_train_with_auto_activate_is_refused_even_when_switch_on(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    monkeypatch.setattr(ml_ep.train_service, "train_model", lambda *a, **k: pytest.fail("trained"))
    app = FastAPI()
    app.include_router(ml_ep.router)
    r = TestClient(app).post("/ml/train", json={"name": "m", "auto_activate": True})
    assert r.status_code == 403 and "approve" in r.json()["detail"]


# ------------------------------------------------------------------ CLI


def _cli_args(model, **kw):
    base = {
        "model_id": model.id,
        "approver": "boss",
        "reason": "Beat the incumbent on the same rows",
        "evidence": ["docs/report.md@abc"],
        "artifact_sha256": model.metrics["artifact_sha256"],
        "protocol_verdict": None,
    }
    base.update(kw)
    return argparse.Namespace(**base)


@pytest.fixture()
def cli_db(db_session, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", scope)
    return db_session


def _user(db, username, role):
    from swing_trade_ml.db.models.session import User

    u = User(username=username, hashed_password="x", role=role)
    db.add(u)
    db.flush()
    return u


def test_cli_promote_needs_an_owner_login_as_approver(cli_db, model_dir, switch_on, capsys):
    from swing_trade_ml import cli

    _user(cli_db, "tester1", "tester")
    new = _model(cli_db, "p_cli_role")
    assert cli.cmd_promote(_cli_args(new, approver="tester1")) == 1
    assert "owner" in capsys.readouterr().out
    cli_db.refresh(new)
    assert new.status == ModelStatus.TRAINED


def test_cli_promote_and_rollback(cli_db, model_dir, switch_on):
    from swing_trade_ml import cli

    owner = _user(cli_db, "boss", "owner")
    old = _model(cli_db, "p_cli", status=ModelStatus.ACTIVE)
    new = _model(cli_db, "p_cli")
    assert cli.cmd_promote(_cli_args(new)) == 0
    (row,) = _audit_rows(cli_db, "model.promote")
    assert row.actor_user_id == owner.id and row.after["invoked_by"] == "cli"
    assert cli.cmd_rollback(_cli_args(old, model_id=old.id)) == 0
    cli_db.refresh(old)
    assert old.status == ModelStatus.ACTIVE


def test_cli_train_activate_is_refused_even_when_switch_on(monkeypatch, capsys):
    from swing_trade_ml import cli

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    monkeypatch.setattr("swing_trade_ml.ml.train.train_model", lambda *a, **k: pytest.fail("trained"))
    assert cli.cmd_train(argparse.Namespace(activate=True)) == 1
    assert "swingtrade promote" in capsys.readouterr().out
