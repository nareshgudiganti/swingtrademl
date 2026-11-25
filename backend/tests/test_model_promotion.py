"""#328: what model serves changes only through ml/promotion.py: a designated, signed-in owner records an
approval (verdict PASS, evidence files with hashes checked on disk), and it is spent once within 7 days by
promote / rollback / the M06 switch / a strategy model change, each with its own audit row."""

from __future__ import annotations

import argparse
import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.session import User
from swing_trade_ml.ml import promotion, registry

FEATURES = ["rsi_14", "macd"]
OWNER = "boss328"


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    folder = tmp_path / "models"
    folder.mkdir()
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(folder))
    return folder


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A stand-in repository root holding one evidence report."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "report.md").write_text(
        "h05 same-rows report: challenger beats champion\n", encoding="utf-8"
    )
    monkeypatch.setattr(promotion, "REPO_ROOT", root)
    return root


@pytest.fixture()
def switch_on(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)


@pytest.fixture(autouse=True)
def designated(monkeypatch):
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", OWNER)


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(repo):
    return [{"path": "docs/report.md", "sha256": _sha(repo / "docs" / "report.md")}, {"pr": 496}]


def _user(db, username=OWNER, role="owner"):
    u = User(username=username, hashed_password="x", role=role, email=f"{username}@example.invalid")
    db.add(u)
    db.flush()
    return u


def _model(db, name, *, card=True, status=ModelStatus.TRAINED):
    """A row published the way the general trainer publishes it: file hash plus a model card naming it."""
    version = registry.next_version(db, name)
    path = registry.save_artifact(name, version, {"estimator": None, "feature_names": FEATURES})
    sha = registry.artifact_sha256(path)
    metrics = {"artifact_sha256": sha}
    if card:
        metrics["card"] = {"artifact_sha256": sha, "code_git_sha": "abc123"}
    m = MLModel(
        name=name, version=version, algorithm="lightgbm", feature_names=FEATURES,
        artifact_path=path, metrics=metrics, status=status,
    )  # fmt: skip
    if status == ModelStatus.ACTIVE:
        from datetime import UTC, datetime

        m.activated_at = datetime.now(UTC)
    db.add(m)
    db.flush()
    return m


def _approve(db, user, repo, kind, target, sha, **kw) -> int:
    args = {
        "kind": kind,
        "target": target,
        "reason": "Beat the incumbent on the same rows in the h05 report",
        "evidence": _evidence(repo),
        "protocol_verdict": "PASS",
        "artifact_sha256": sha,
    }
    args.update(kw)
    return promotion.record_approval(db, user, **args).id


def _audit(db, action=None):
    stmt = select(AuditLog).order_by(AuditLog.id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(db.execute(stmt).scalars())


def _uses(db):
    return [r for r in _audit(db) if r.action in promotion.USE_ACTIONS]


# ------------------------------------------------------------------ recording an approval


def test_recording_writes_an_approval_row_with_who_and_evidence(db_session, model_dir, repo):
    owner = _user(db_session)
    new = _model(db_session, "p_rec")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    row = db_session.get(AuditLog, aid)
    assert row.action == promotion.APPROVAL_ACTION and row.actor_user_id == owner.id
    assert row.target_type == "ml_model" and row.target_id == str(new.id)
    assert row.after["approver_email"] == f"{OWNER}@example.invalid"
    assert row.after["protocol_verdict"] == "PASS" and row.after["evidence"][1] == {"pr": 496}


@pytest.mark.parametrize(
    "who, match",
    [(None, "API key"), ("tester", "owner login"), ("otherowner", "designated owner")],
)
def test_only_the_designated_owner_can_record(db_session, model_dir, repo, who, match):
    user = None
    if who == "tester":
        user = _user(db_session, "tester328", role="tester")
    elif who == "otherowner":
        user = _user(db_session, "owner2_328", role="owner")
    with pytest.raises(promotion.PromotionError, match=match):
        _approve(db_session, user, repo, "promote", 1, "a" * 64)
    assert _audit(db_session, promotion.APPROVAL_ACTION) == []


@pytest.mark.parametrize("verdict", [None, "FAIL", "INCONCLUSIVE", "pass"])
def test_the_protocol_verdict_must_be_pass(db_session, model_dir, repo, verdict):
    owner = _user(db_session)
    with pytest.raises(promotion.PromotionError, match="PASS"):
        _approve(db_session, owner, repo, "promote", 1, "a" * 64, protocol_verdict=verdict)


@pytest.mark.parametrize(
    "evidence, match",
    [
        ([], "1 to"),
        ([{"pr": 496}], "repo file"),
        ([{"path": "docs/missing.md", "sha256": "a" * 64}], "not found"),
        ([{"path": "docs/report.md", "sha256": "b" * 64}], "changed"),
        ([{"path": "../outside.md", "sha256": "a" * 64}], "inside the repository"),
        ([{"path": "C:/x/report.md", "sha256": "a" * 64}], "inside the repository"),
        (["free text"], "path"),
    ],
)
def test_evidence_must_be_checkable(db_session, model_dir, repo, evidence, match):
    owner = _user(db_session)
    with pytest.raises(promotion.PromotionError, match=match):
        _approve(db_session, owner, repo, "promote", 1, "a" * 64, evidence=evidence)


# ------------------------------------------------------------------ promote


def test_promote_activates_archives_the_incumbent_and_audits(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    old = _model(db_session, "p_ok", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_ok")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    promotion.promote(db_session, new.id, aid, invoked_by="test")
    db_session.refresh(old)
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE and old.status == ModelStatus.ARCHIVED
    (row,) = _audit(db_session, promotion.PROMOTE_ACTION)
    assert row.actor_user_id == owner.id and row.target_id == str(new.id)
    assert row.before["active_model_id"] == old.id
    assert row.before["active_artifact_sha256"] == old.metrics["artifact_sha256"]
    assert row.after["approval_id"] == aid and row.after["approver_email"] == f"{OWNER}@example.invalid"
    assert (
        row.after["artifact_sha256"] == new.metrics["artifact_sha256"] and row.after["invoked_by"] == "test"
    )


def _refused(db, model_id, approval_id, match, fn=promotion.promote):
    with pytest.raises(ValueError, match=match):
        fn(db, model_id, approval_id, invoked_by="test")
    assert _uses(db) == []


def test_switch_off_refuses(db_session, model_dir, repo, monkeypatch):
    owner = _user(db_session)
    new = _model(db_session, "p_off")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    _refused(db_session, new.id, aid, "ALLOW_MODEL_PROMOTION")


def test_no_approval_id_refuses(db_session, model_dir, repo, switch_on):
    new = _model(db_session, "p_none")
    _refused(db_session, new.id, None, "approval")


def test_an_approval_for_another_model_or_kind_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    a, b = _model(db_session, "p_other"), _model(db_session, "p_other")
    for_a = _approve(db_session, owner, repo, "promote", a.id, a.metrics["artifact_sha256"])
    rollback_b = _approve(db_session, owner, repo, "rollback", b.id, b.metrics["artifact_sha256"])
    _refused(db_session, b.id, for_a, "not this")
    _refused(db_session, b.id, rollback_b, "not this")
    _refused(db_session, b.id, 987654321, "not found")


def test_an_approval_is_used_once(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_once")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    promotion.promote(db_session, new.id, aid, invoked_by="test")
    newer = _model(db_session, "p_once")
    with pytest.raises(promotion.PromotionError):
        promotion.promote(db_session, newer.id, aid, invoked_by="test")
    new.status = ModelStatus.ARCHIVED  # even for the same model
    db_session.flush()
    with pytest.raises(promotion.PromotionError, match="already been used"):
        promotion.promote(db_session, new.id, aid, invoked_by="test")


def test_an_approval_older_than_7_days_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_old")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    row = db_session.get(AuditLog, aid)
    row.ts = row.ts - timedelta(days=8)
    db_session.flush()
    _refused(db_session, new.id, aid, "older than 7 days")


def test_an_approver_who_lost_owner_rights_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_demoted")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    owner.role = "member"
    db_session.flush()
    _refused(db_session, new.id, aid, "owner")


def test_evidence_changed_after_approval_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_evchg")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    (repo / "docs" / "report.md").write_text("rewritten after approval\n", encoding="utf-8")
    _refused(db_session, new.id, aid, "changed since")


def test_a_model_without_a_card_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    old = _model(db_session, "p_nocard", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_nocard", card=False)
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    _refused(db_session, new.id, aid, "model card")
    db_session.refresh(old)
    assert old.status == ModelStatus.ACTIVE


def test_an_approved_hash_that_is_not_the_cards_file_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_otherhash")
    aid = _approve(db_session, owner, repo, "promote", new.id, "0" * 64)
    _refused(db_session, new.id, aid, "model card describes")


def test_a_swapped_file_on_disk_refuses_by_recomputing_its_hash(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    old = _model(db_session, "p_swap", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_swap")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    with open(new.artifact_path, "ab") as fh:
        fh.write(b"tampered")
    _refused(db_session, new.id, aid, "not the file that was approved")
    db_session.refresh(old)
    assert old.status == ModelStatus.ACTIVE and new.status == ModelStatus.TRAINED


def test_a_missing_file_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    new = _model(db_session, "p_missing")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    (model_dir / f"{new.name}_{new.version}.joblib").unlink()
    _refused(db_session, new.id, aid, "missing")


def test_an_already_active_model_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    cur = _model(db_session, "p_again", status=ModelStatus.ACTIVE)
    aid = _approve(db_session, owner, repo, "promote", cur.id, cur.metrics["artifact_sha256"])
    _refused(db_session, cur.id, aid, "status")


# ------------------------------------------------------------------ rollback


def _promoted(db, owner, repo, name, *, old_card=True):
    old = _model(db, name, card=old_card, status=ModelStatus.ACTIVE)
    new = _model(db, name)
    promotion.promote(
        db,
        new.id,
        _approve(db, owner, repo, "promote", new.id, new.metrics["artifact_sha256"]),
        invoked_by="t",
    )
    return old, new


def test_rollback_restores_the_previous_model_with_its_own_audit_row(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    old, new = _promoted(db_session, owner, repo, "p_rb", old_card=False)  # older models have no card
    promoted = _audit(db_session, promotion.PROMOTE_ACTION)[0]
    aid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    promotion.rollback(db_session, old.id, aid, invoked_by="test")
    db_session.refresh(old)
    db_session.refresh(new)
    assert old.status == ModelStatus.ACTIVE and new.status == ModelStatus.ARCHIVED
    (row,) = _audit(db_session, promotion.ROLLBACK_ACTION)
    assert row.before["active_model_id"] == new.id and row.after["undoes_audit_id"] == promoted.id
    assert row.after["approval_id"] == aid


def test_rollback_takes_the_lock_before_checking(db_session, model_dir, repo, switch_on, monkeypatch):
    owner = _user(db_session)
    old, _ = _promoted(db_session, owner, repo, "p_rb_lock")
    aid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    order: list[str] = []
    real_lock, real_use = registry.lock_model_name, promotion.use_approval
    monkeypatch.setattr(registry, "lock_model_name", lambda db, n: (order.append("lock"), real_lock(db, n)))
    monkeypatch.setattr(
        promotion, "use_approval", lambda *a, **k: (order.append("check"), real_use(*a, **k))[1]
    )
    promotion.rollback(db_session, old.id, aid, invoked_by="test")
    assert order[:2] == ["lock", "check"]


def test_rollback_needs_the_switch(db_session, model_dir, repo, switch_on, monkeypatch):
    owner = _user(db_session)
    old, new = _promoted(db_session, owner, repo, "p_rb_off")
    aid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    with pytest.raises(promotion.PromotionError, match="ALLOW_MODEL_PROMOTION"):
        promotion.rollback(db_session, old.id, aid, invoked_by="test")
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE


def test_rollback_only_to_the_model_the_last_promotion_replaced(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    a = _model(db_session, "p_rb_who", status=ModelStatus.ARCHIVED)
    _promoted(db_session, owner, repo, "p_rb_who")
    aid = _approve(db_session, owner, repo, "rollback", a.id, a.metrics["artifact_sha256"])
    with pytest.raises(promotion.PromotionError, match="replaced"):
        promotion.rollback(db_session, a.id, aid, invoked_by="test")


def test_rollback_without_any_recorded_promotion_refuses(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    a = _model(db_session, "p_rb_never", status=ModelStatus.ARCHIVED)
    _model(db_session, "p_rb_never", status=ModelStatus.ACTIVE)
    aid = _approve(db_session, owner, repo, "rollback", a.id, a.metrics["artifact_sha256"])
    with pytest.raises(promotion.PromotionError, match="no recorded promotion"):
        promotion.rollback(db_session, a.id, aid, invoked_by="test")


def test_rollback_refuses_a_previous_file_that_changed_since(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    old, new = _promoted(db_session, owner, repo, "p_rb_swap")
    aid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    with open(old.artifact_path, "ab") as fh:
        fh.write(b"tampered")
    with pytest.raises(promotion.PromotionError, match="not the file that was approved"):
        promotion.rollback(db_session, old.id, aid, invoked_by="test")
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE


def test_rollback_refuses_when_the_active_model_changed_outside_the_gate(
    db_session, model_dir, repo, switch_on
):
    owner = _user(db_session)
    old, new = _promoted(db_session, owner, repo, "p_rb_drift")
    aid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    new.status = ModelStatus.ARCHIVED  # someone changed the active model without promote()
    db_session.flush()
    with pytest.raises(promotion.PromotionError, match="changed"):
        promotion.rollback(db_session, old.id, aid, invoked_by="test")


def test_last_change_filters_by_name_in_sql(db_session, model_dir, repo, switch_on):
    owner = _user(db_session)
    _promoted(db_session, owner, repo, "p_lc_a")
    _, new_b = _promoted(db_session, owner, repo, "p_lc_b")
    assert promotion.last_change(db_session, "p_lc_a").after["name"] == "p_lc_a"
    assert promotion.last_change(db_session, "p_lc_b").after["model_id"] == new_b.id
    assert promotion.last_change(db_session, "p_lc_none") is None


# ------------------------------------------------------------------ train.py auto_activate


def test_auto_activate_is_refused_before_any_training():
    from swing_trade_ml.ml import train

    with pytest.raises(ValueError, match="not allowed"):
        train.train_model(None, name="x", auto_activate=True)  # type: ignore[arg-type]


# ------------------------------------------------------------------ API


def _principal(user=None, api_key=False):
    from swing_trade_ml.api.deps import Principal

    return Principal(user=user, via_api_key=api_key)


def _approval_body(repo, kind, target, sha, **kw):
    from swing_trade_ml.api.v1.endpoints.ml import ApprovalRequest

    body = {
        "kind": kind, "target": str(target), "reason": "Beat the incumbent on the same rows",
        "evidence": _evidence(repo), "protocol_verdict": "PASS", "artifact_sha256": sha,
    }  # fmt: skip
    body.update(kw)
    return ApprovalRequest(**body)


def test_api_records_then_activates_with_the_signed_in_owner(
    db_session, model_dir, repo, switch_on, monkeypatch
):
    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    monkeypatch.setattr(ml_ep.predict_service, "clear_cache", lambda: None)
    owner = _user(db_session)
    new = _model(db_session, "p_api")
    rec = ml_ep.record_approval(
        _approval_body(repo, "promote", new.id, new.metrics["artifact_sha256"]), db=db_session,
        principal=_principal(owner),
    )  # fmt: skip
    ml_ep.activate(new.id, db=db_session, principal=_principal(owner), payload=ml_ep.UseApproval(**rec))
    db_session.refresh(new)
    assert new.status == ModelStatus.ACTIVE
    (row,) = _audit(db_session, promotion.PROMOTE_ACTION)
    assert row.actor_user_id == owner.id and row.after["invoked_by"] == "api"


def test_api_key_cannot_record_or_use_an_approval(db_session, model_dir, repo, switch_on):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    new = _model(db_session, "p_api_key")
    with pytest.raises(HTTPException) as e:
        ml_ep.record_approval(
            _approval_body(repo, "promote", new.id, new.metrics["artifact_sha256"]), db=db_session,
            principal=_principal(api_key=True),
        )  # fmt: skip
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        ml_ep.activate(
            new.id,
            db=db_session,
            principal=_principal(api_key=True),
            payload=ml_ep.UseApproval(approval_id=1),
        )
    assert e.value.status_code == 403


def test_api_activate_without_an_approval_body_is_refused(db_session, model_dir, repo, switch_on):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    owner = _user(db_session)
    new = _model(db_session, "p_api_nobody")
    with pytest.raises(HTTPException) as e:
        ml_ep.activate(new.id, db=db_session, principal=_principal(owner), payload=None)
    assert e.value.status_code == 400 and "approval" in e.value.detail


def test_http_member_gets_403_on_every_approval_route(db_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from swing_trade_ml.api.deps import get_db, get_principal
    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    member = _user(db_session, "member328", role="member")
    app = FastAPI()
    app.include_router(ml_ep.router)
    app.dependency_overrides[get_principal] = lambda: _principal(member)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    assert client.post("/ml/approvals", json={}).status_code in (403, 422)
    for path in ("/ml/models/1/activate", "/ml/models/1/rollback"):
        assert client.post(path, json={"approval_id": 1}).status_code == 403, path
    body = {
        "kind": "promote", "target": "1", "reason": "Beat the incumbent", "evidence": [{"pr": 1}],
        "protocol_verdict": "PASS", "artifact_sha256": "a" * 64,
    }  # fmt: skip
    assert client.post("/ml/approvals", json=body).status_code == 403


def test_api_train_with_auto_activate_is_refused_even_when_switch_on(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from swing_trade_ml.api.v1.endpoints import ml as ml_ep

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    monkeypatch.setattr(ml_ep.train_service, "train_model", lambda *a, **k: pytest.fail("trained"))
    app = FastAPI()
    app.include_router(ml_ep.router)
    r = TestClient(app).post("/ml/train", json={"name": "m", "auto_activate": True})
    assert r.status_code == 403 and "approval" in r.json()["detail"]


# ------------------------------------------------------------------ M06 switch


@pytest.fixture()
def combiner(monkeypatch):
    monkeypatch.setattr(promotion, "newest_combiner_sha", lambda: "c" * 64)
    return "c" * 64


def _m06(db, principal, approval_id=None, mode="on"):
    from swing_trade_ml.api.v1.endpoints import brain as brain_ep

    return brain_ep.switch_module(
        "M06", brain_ep.ModeUpdate(mode=mode, approval_id=approval_id), db, principal
    )


def test_m06_on_needs_a_recorded_approval_of_the_served_combiner(db_session, repo, switch_on, combiner):
    from fastapi import HTTPException

    from swing_trade_ml.brain import service
    from swing_trade_ml.db.models.brain import BrainModuleSetting

    owner = _user(db_session)
    with pytest.raises(HTTPException) as e:
        _m06(db_session, _principal(owner))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        _m06(db_session, _principal(api_key=True), 1)
    assert e.value.status_code == 403
    wrong = _approve(db_session, owner, repo, "brain_module_on", "M06", "d" * 64)
    with pytest.raises(HTTPException) as e:
        _m06(db_session, _principal(owner), wrong)
    assert e.value.status_code == 400 and "not the file" in e.value.detail
    aid = _approve(db_session, owner, repo, "brain_module_on", "M06", combiner)
    assert _m06(db_session, _principal(owner), aid)["mode"] == "on"
    row = db_session.get(BrainModuleSetting, "M06")
    assert row.changed_by == OWNER  # from the credential, never the body
    (use,) = _audit(db_session, promotion.M06_ON_ACTION)
    assert use.after["approval_id"] == aid and use.after["artifact_sha256"] == combiner
    assert service.load_modes(db_session)["M06"].value == "on"


def test_m06_on_refused_while_the_switch_is_off(db_session, repo, combiner, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", False)
    owner = _user(db_session)
    with pytest.raises(HTTPException) as e:
        _m06(db_session, _principal(owner), 1)
    assert e.value.status_code == 403


def test_m06_to_shadow_needs_no_approval_and_records_the_real_caller(db_session):
    from swing_trade_ml.api.v1.endpoints import brain as brain_ep
    from swing_trade_ml.db.models.brain import BrainModuleSetting

    payload = brain_ep.ModeUpdate(mode="shadow", by="someone-else")
    brain_ep.switch_module("M06", payload, db_session, _principal(api_key=True))
    assert db_session.get(BrainModuleSetting, "M06").changed_by == "api-key"


def test_a_learning_proposal_cannot_switch_m06_on(db_session):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import brain as brain_ep
    from swing_trade_ml.db.models.brain import BrainProposal

    p = BrainProposal(kind="module_mode", title="t", evidence="e", change={"module": "M06", "mode": "on"})
    db_session.add(p)
    db_session.flush()
    with pytest.raises(HTTPException) as e:
        brain_ep.accept_proposal(p.id, brain_ep.ProposalDecision(), db_session, _principal(api_key=True))
    assert e.value.status_code == 409
    db_session.refresh(p)
    assert p.status == "open"


def test_cli_brain_set_m06_on_needs_an_approval(db_session, switch_on, combiner, monkeypatch, capsys):
    from swing_trade_ml import cli

    _cli_scope(db_session, monkeypatch)
    args = argparse.Namespace(brain_command="set", module_id="M06", mode="on", approval_id=None)
    assert cli.cmd_brain(args) == 1
    assert "approval" in capsys.readouterr().err


# ------------------------------------------------------------------ strategy model selector


def _strategy(db, model_name="swing_classifier"):
    from swing_trade_ml.db.models.trading import Strategy

    s = Strategy(name=f"s328_{model_name}", strategy_type="ml_swing", params={"model_name": model_name})
    db.add(s)
    db.flush()
    return s


def test_strategy_model_change_needs_an_approval(db_session, model_dir, repo, switch_on):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import strategies as st_ep
    from swing_trade_ml.schemas import StrategyUpdate

    owner = _user(db_session)
    target = _model(db_session, "p_strat_mid", status=ModelStatus.ACTIVE)
    s = _strategy(db_session)
    update = StrategyUpdate(params={"model_name": "p_strat_mid"})
    with pytest.raises(HTTPException) as e:
        st_ep.update_strategy(s.id, update, db_session, _principal(owner), approval_id=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        st_ep.update_strategy(s.id, update, db_session, _principal(api_key=True), approval_id=None)
    assert e.value.status_code == 403
    aid = _approve(
        db_session,
        owner,
        repo,
        "strategy_model",
        s.id,
        target.metrics["artifact_sha256"],
        model_name="p_strat_mid",
    )
    st_ep.update_strategy(s.id, update, db_session, _principal(owner), approval_id=aid)
    db_session.refresh(s)
    assert s.params["model_name"] == "p_strat_mid"
    (use,) = _audit(db_session, promotion.STRATEGY_MODEL_ACTION)
    assert use.after["previous_model_name"] == "swing_classifier" and use.after["model_id"] == target.id


def test_strategy_edits_that_keep_the_model_need_no_approval(db_session):
    from swing_trade_ml.api.v1.endpoints import strategies as st_ep
    from swing_trade_ml.schemas import StrategyUpdate

    s = _strategy(db_session)
    update = StrategyUpdate(params={"model_name": "swing_classifier", "threshold": 0.7})
    st_ep.update_strategy(s.id, update, db_session, _principal(api_key=True), approval_id=None)
    db_session.refresh(s)
    assert s.params["threshold"] == 0.7


def test_creating_a_strategy_on_a_non_default_model_is_refused(db_session):
    from fastapi import HTTPException

    from swing_trade_ml.api.v1.endpoints import strategies as st_ep
    from swing_trade_ml.schemas import StrategyCreate

    payload = StrategyCreate(name="s328_new", strategy_type="ml_swing", params={"model_name": "other_model"})
    with pytest.raises(HTTPException) as e:
        st_ep.create_strategy(payload, db_session)
    assert e.value.status_code == 403


# ------------------------------------------------------------------ CLI


def _cli_scope(db, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def scope():
        yield db

    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", scope)


def test_cli_promote_and_rollback_spend_recorded_approvals(
    db_session, model_dir, repo, switch_on, monkeypatch
):
    from swing_trade_ml import cli

    _cli_scope(db_session, monkeypatch)
    owner = _user(db_session)
    old = _model(db_session, "p_cli", status=ModelStatus.ACTIVE)
    new = _model(db_session, "p_cli")
    aid = _approve(db_session, owner, repo, "promote", new.id, new.metrics["artifact_sha256"])
    assert cli.cmd_promote(argparse.Namespace(model_id=new.id, approval_id=aid)) == 0
    (row,) = _audit(db_session, promotion.PROMOTE_ACTION)
    assert row.actor_user_id == owner.id and row.after["invoked_by"] == "cli"
    rid = _approve(db_session, owner, repo, "rollback", old.id, old.metrics["artifact_sha256"])
    assert cli.cmd_rollback(argparse.Namespace(model_id=old.id, approval_id=rid)) == 0
    db_session.refresh(old)
    assert old.status == ModelStatus.ACTIVE


def test_cli_promote_refuses_without_a_valid_approval(db_session, model_dir, switch_on, monkeypatch, capsys):
    from swing_trade_ml import cli

    _cli_scope(db_session, monkeypatch)
    new = _model(db_session, "p_cli_bad")
    assert cli.cmd_promote(argparse.Namespace(model_id=new.id, approval_id=123456789)) == 1
    assert "not found" in capsys.readouterr().out


def test_cli_train_activate_is_refused_even_when_switch_on(monkeypatch, capsys):
    from swing_trade_ml import cli

    monkeypatch.setattr(settings, "ALLOW_MODEL_PROMOTION", True)
    monkeypatch.setattr("swing_trade_ml.ml.train.train_model", lambda *a, **k: pytest.fail("trained"))
    assert cli.cmd_train(argparse.Namespace(activate=True)) == 1
    assert "swingtrade promote" in capsys.readouterr().out
