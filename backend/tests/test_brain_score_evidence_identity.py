"""Issue #377: a measured hit rate belongs to the one model (and protocol) it was measured on.

Two models that only share the target, stop and horizon must never share a hit rate, and a stored
historical card keeps the evidence of the model that produced its score, whatever is active later.
Display only: stored scores and decisions are never touched.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import score_evidence
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.data_manifest import build_data_manifest
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.ml import MLModel

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
PROTOCOL = "walk-forward test, 28-day windows, +8% before -4% within 15 trading days"


def _rows() -> list[dict]:
    rng = random.Random(7)
    rows = []
    for w in range(5):
        start = datetime(2026, 1, 1) + timedelta(days=28 * w)
        for i in range(400):
            rows.append(
                {
                    "fold": start.date().isoformat(),
                    "end": (start + timedelta(days=27)).date().isoformat(),
                    "day": (start + timedelta(days=i % 20)).date().isoformat(),
                    "p": rng.random(),
                    "hit": int(rng.random() < 0.14),
                }
            )
    return rows


@pytest.fixture(scope="module")
def raw_evidence() -> dict:
    return score_evidence.build(_rows(), "2026-10-12")


def _model(db=None, **kw) -> MLModel:
    base = {
        "name": "swing_classifier",
        "version": "v9",
        "algorithm": "lightgbm",
        "status": ModelStatus.ACTIVE,
        "artifact_path": "/nowhere/model.joblib",
        "activated_at": AS_OF,
        "label_kind": "barrier",
        "prediction_horizon_days": 15,
        "target_return_pct": 0.08,
        "stop_return_pct": 0.04,
        "feature_names": ["rsi_14", "atr_14"],
        "metrics": {},
    }
    base.update(kw)
    m = MLModel(**base)
    if db is not None:
        db.add(m)
        db.flush()
    return m


def _measured_on(model: MLModel, **kw) -> dict:
    ident = score_evidence.model_identity(model)
    return {
        "model_id": ident["model_id"],
        "name": ident["name"],
        "version": ident["version"],
        "artifact_sha256": ident["artifact_sha256"],
        "inputs_fingerprint": ident["inputs_fingerprint"],
        "protocol": PROTOCOL,
        **kw,
    }


def _evidence_for(raw: dict, model: MLModel, **kw) -> dict:
    return {**raw, "measured_on": _measured_on(model, **kw)}


# --- unit: which evidence a model may use -------------------------------------------------------


def test_build_records_the_model_it_was_measured_on(raw_evidence):
    m = _model(id=11)
    ev = score_evidence.build(_rows(), "2026-10-12", measured_on=_measured_on(m))
    assert ev["measured_on"]["name"] == "swing_classifier" and ev["measured_on"]["model_id"] == 11
    assert ev["measured_on"]["protocol"] == PROTOCOL
    assert ev["bands"] == raw_evidence["bands"]  # identity never changes the measured numbers


def test_same_target_different_model_gets_no_hit_rate(raw_evidence):
    measured = _model(id=1, version="v9")
    other = _model(id=2, version="v10")  # same +8% / -4% / 15-day question, different model
    ev = _evidence_for(raw_evidence, measured)
    assert score_evidence.choose(score_evidence.model_identity(measured), ev).status == "match"
    choice = score_evidence.choose(score_evidence.model_identity(other), ev)
    assert choice.status == "other_model" and choice.evidence is None
    out = score_evidence.present(0.55, choice.evidence, reason=choice.status)
    assert out["status"] == "not_measured" and "honest_chance" not in out and "track_record" not in out


def test_same_name_and_version_but_other_id_is_another_model(raw_evidence):
    ev = _evidence_for(raw_evidence, _model(id=1))
    assert score_evidence.choose(score_evidence.model_identity(_model(id=3)), ev).status == "other_model"


def test_artifact_hash_mismatch_gets_no_hit_rate(raw_evidence):
    measured = _model(id=1, metrics={"artifact_sha256": "a" * 64})
    ev = _evidence_for(raw_evidence, measured)
    assert score_evidence.choose(score_evidence.model_identity(measured), ev).status == "match"
    swapped = _model(id=1, metrics={"artifact_sha256": "b" * 64})  # same row, different file
    assert score_evidence.choose(score_evidence.model_identity(swapped), ev).status == "other_model"
    unknown = _model(id=1, metrics={})  # the evidence names a file the model cannot vouch for
    choice = score_evidence.choose(score_evidence.model_identity(unknown), ev)
    assert choice.status == "unverified_evidence" and choice.evidence is None


def test_inputs_mismatch_gets_no_hit_rate(raw_evidence):
    ev = _evidence_for(raw_evidence, _model(id=1))
    changed = _model(id=1, feature_names=["rsi_14", "atr_14", "obv_slope"])
    assert score_evidence.choose(score_evidence.model_identity(changed), ev).status == "other_model"


def test_no_recorded_hash_matches_by_name_version_and_id(raw_evidence):
    """Production models predate artifact hashes: identity is (name, version, id), hash 'not recorded'."""
    m = _model(id=5, metrics={})
    ev = _evidence_for(raw_evidence, m)
    assert ev["measured_on"]["artifact_sha256"] is None
    choice = score_evidence.choose(score_evidence.model_identity(m), ev)
    assert choice.status == "match"
    out = score_evidence.present(0.55, choice.evidence, reason=choice.status, scored_by=choice.identity)
    assert out["status"] == "measured"
    assert out["scored_by"]["artifact_sha256"] == "not recorded"
    assert out["measured_on"]["protocol"] == PROTOCOL


def test_evidence_without_recorded_identity_is_unverified_never_a_match(raw_evidence):
    assert "measured_on" not in raw_evidence
    choice = score_evidence.choose(score_evidence.model_identity(_model(id=1)), raw_evidence)
    assert choice.status == "unverified_evidence" and choice.evidence is None
    out = score_evidence.present(0.55, None, reason=choice.status)
    assert out["status"] == "unverified" and "honest_chance" not in out and out["note"]


def test_the_shipped_evidence_file_is_not_given_to_any_registered_model():
    """It was measured on walk-forward fold models (docs/brain/evidence/score_reliability.py) and
    records no single model, so no registered model may quote it."""
    ev = score_evidence.load()
    assert ev is not None
    choice = score_evidence.choose(score_evidence.model_identity(_model(id=1)), ev)
    assert choice.evidence is None and choice.status == "unverified_evidence"


def test_unknown_scoring_model_is_unverified(raw_evidence):
    choice = score_evidence.choose(None, _evidence_for(raw_evidence, _model(id=1)))
    assert choice.status == "unverified_model" and choice.evidence is None
    out = score_evidence.present(0.55, None, reason=choice.status)
    assert out["status"] == "unverified" and "could not confirm which model" in out["note"]


def test_another_question_keeps_the_not_trained_note(raw_evidence):
    endpoint = _model(
        id=9, label_kind="endpoint", prediction_horizon_days=5, target_return_pct=0.02, stop_return_pct=None
    )
    choice = score_evidence.choose(
        score_evidence.model_identity(endpoint), _evidence_for(raw_evidence, endpoint)
    )
    assert choice.status == "other_question"
    assert "not trained on the +8%" in score_evidence.present(0.55, None, reason=choice.status)["note"]


# --- the scoring model is recorded with each new run ------------------------------------------


def test_scoring_model_is_the_live_model_the_reader_used():
    m = _model(id=4)
    live = SimpleNamespace(live=True, asof_model=None, _model=m, _model_loaded=True)
    assert score_evidence.scoring_model(live) is m
    never_asked = SimpleNamespace(live=True, asof_model=None, _model=None, _model_loaded=False)
    assert score_evidence.scoring_model(never_asked) is None
    replay = SimpleNamespace(live=False, asof_model=m, _model=None, _model_loaded=False)
    assert score_evidence.scoring_model(replay) is m
    assert score_evidence.scoring_model(object()) is None


def test_data_manifest_records_the_scoring_model_identity(db_session):
    m = _model(db_session, id=None, metrics={"artifact_sha256": "c" * 64})
    reader = SimpleNamespace(live=True, asof_model=None, _model=m, _model_loaded=True)
    req = c.RunRequest(run_id="dm-run", kind="nightly", as_of=AS_OF, universe=("AAA",))
    manifest = build_data_manifest(
        db_session, req, BrainContext.start(req, SimpleNamespace(holdings=lambda b: []))
    )
    assert manifest["score_model"] is None  # this context's reader never scored anything
    manifest = build_data_manifest(db_session, req, BrainContext(request=req, reader=reader))
    rec = manifest["score_model"]
    assert rec["model_id"] == m.id and rec["name"] == m.name and rec["version"] == m.version
    assert rec["artifact_sha256"] == "c" * 64 and rec["inputs_fingerprint"]


# --- API: historical cards keep their own model's evidence -------------------------------------


def _run(db, run_id: str, decisions: list[dict], context: dict | None = None) -> str:
    db.add(
        BrainRun(
            id=run_id, kind="nightly", as_of=AS_OF, book="paper", live=True, started_at=AS_OF, context=context
        )
    )
    db.flush()
    for d in decisions:
        db.add(BrainDecision(run_id=run_id, word="WATCH", **{"reasons": ["r"], **d}))
    db.flush()
    return run_id


def _idea(symbol: str = "S0", p: float = 0.55, reasons: list[str] | None = None) -> dict:
    return {
        "symbol": symbol,
        "kind": "idea",
        "confidence": p,
        "score_source": "model",
        "reasons": reasons or ["r"],
    }


def _activate(db, old: MLModel, new: MLModel) -> None:
    old.status = ModelStatus.ARCHIVED
    new.status = ModelStatus.ACTIVE
    db.flush()


def _card(client, run_id: str) -> dict:
    return client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()["decisions"][0]["honest_score"]


def test_historical_card_keeps_its_model_evidence_after_another_activation(
    client, db_session, monkeypatch, raw_evidence
):
    a = _model(db_session, version="v9")
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: _evidence_for(raw_evidence, a))
    ctx = {"data_manifest": {"score_model": score_evidence.model_identity(a)}}
    run_id = _run(db_session, "hist-a", [_idea()], ctx)
    before = _card(client, run_id)
    assert before["status"] == "measured" and before["scored_by"]["model_id"] == a.id

    b = _model(db_session, version="v10", status=ModelStatus.TRAINED)  # same question, another model
    _activate(db_session, a, b)
    after = _card(client, run_id)
    assert after == before  # the stored card did not change with the activation

    # a new run scored by B gets no hit rate: the evidence was measured on A only
    ctx_b = {"data_manifest": {"score_model": score_evidence.model_identity(b)}}
    new = _card(client, _run(db_session, "new-b", [_idea()], ctx_b))
    assert new["status"] == "not_measured" and "honest_chance" not in new


def test_activation_does_not_hand_a_historical_card_the_new_models_evidence(
    client, db_session, monkeypatch, raw_evidence
):
    a = _model(db_session, version="v9")
    run_id = _run(
        db_session, "hist-a2", [_idea()], {"data_manifest": {"score_model": score_evidence.model_identity(a)}}
    )
    b = _model(db_session, version="v10", status=ModelStatus.TRAINED)
    _activate(db_session, a, b)
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: _evidence_for(raw_evidence, b))
    card = _card(client, run_id)
    assert card["status"] == "not_measured" and "honest_chance" not in card


def test_old_run_identity_is_read_from_the_stored_reason_text(client, db_session, monkeypatch, raw_evidence):
    a = _model(db_session, version="v9")
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: _evidence_for(raw_evidence, a))
    reason = "The active model (swing_classifier v9) scores this stock 55%; its buy level is 50%."
    run_id = _run(db_session, "old-a", [_idea("S0", 0.55, [reason, "Plan: ..."]), _idea("S1", 0.4)])
    b = _model(db_session, version="v10", status=ModelStatus.TRAINED)
    _activate(db_session, a, b)
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()["decisions"]
    for d in body:  # one run, one scoring model: every model score in it came from A
        assert d["honest_score"]["status"] == "measured"
        assert d["honest_score"]["scored_by"]["source"] == "reason_text"


def test_old_run_without_any_identity_is_unverified_not_the_active_model(
    client, db_session, monkeypatch, raw_evidence
):
    a = _model(db_session, version="v9")  # active now, and the evidence is A's...
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: _evidence_for(raw_evidence, a))
    card = _card(client, _run(db_session, "old-none", [_idea()]))  # ...but the run never said who scored it
    assert card["status"] == "unverified" and "honest_chance" not in card
    assert "could not confirm which model" in card["note"]


def test_stored_scores_and_words_are_untouched(client, db_session, monkeypatch, raw_evidence):
    a = _model(db_session, version="v9")
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: _evidence_for(raw_evidence, a))
    run_id = _run(db_session, "keep", [_idea("S0", 0.61)], {"data_manifest": {"score_model": None}})
    d = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()["decisions"][0]
    assert d["confidence"] == 0.61 and d["word"] == "WATCH"
    assert d["honest_score"]["status"] == "unverified"


def test_no_evidence_file_says_so_without_blaming_the_model():
    choice = score_evidence.choose(score_evidence.model_identity(_model(id=1)), None)
    assert choice.status == "none"
    out = score_evidence.present(0.55, None, reason=choice.status)
    assert out["status"] == "not_measured" and "not trained" not in out["note"]
