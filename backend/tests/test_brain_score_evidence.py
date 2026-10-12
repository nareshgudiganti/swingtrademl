"""Idea cards show what a score really meant on unseen days, never the raw model score as a chance.

Display only: the stored `confidence` (which decisions, the buy level and orders read) must not change.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.brain import score_evidence
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.ml import MLModel

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _rows(n_per_window: int = 400, windows: int = 5) -> list[dict]:
    """Scores spread over 0..1 that really hit only ~14% of the time, whatever they said."""
    rng = random.Random(3)
    rows = []
    for w in range(windows):
        start = datetime(2026, 1, 1) + timedelta(days=28 * w)
        for i in range(n_per_window):
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
def evidence() -> dict:
    return score_evidence.build(_rows(), "2026-10-12")


def _model(db=None, **kw) -> MLModel:
    """A model row; saved only when a session is given (one ACTIVE per name)."""
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
    }
    base.update(kw)
    m = MLModel(**base)
    if db is not None:
        db.add(m)
        db.flush()
    return m


def _run_with(db, decisions: list[dict]) -> str:
    db.add(BrainRun(id="ev-run", kind="nightly", as_of=AS_OF, book="paper", live=True, started_at=AS_OF))
    db.flush()
    for d in decisions:
        db.add(BrainDecision(run_id="ev-run", reasons=["r"], word="WATCH", **d))
    db.flush()
    return "ev-run"


def test_a_55_percent_score_is_shown_as_what_it_really_was(evidence):
    out = score_evidence.present(0.55, evidence)
    assert out["status"] == "measured"
    assert 0.08 < out["honest_chance"] < 0.22  # about the 14% it really hit, never 55%
    tr = out["track_record"]
    assert tr["enough_evidence"] and tr["n"] >= score_evidence.MIN_BAND_CASES
    assert "about 1 in" in tr["text"] and "ideas the model scored 50% to 60%" in tr["text"]
    assert out["period"]["from"] <= out["period"]["to"] and out["caveat"]


def test_the_honest_chance_never_passes_its_ceiling(evidence):
    ceiling = evidence["honesty"]["ceiling"]
    for raw in (0.3, 0.6, 0.85, 0.99):
        assert score_evidence.present(raw, evidence)["honest_chance"] <= ceiling + 1e-9


def test_too_few_cases_gives_no_track_record(evidence):
    thin = {**evidence, "bands": [{**b, "n": 20} for b in evidence["bands"]]}
    assert score_evidence.present(0.55, thin)["track_record"] == {"enough_evidence": False}


def test_a_model_on_another_question_gets_no_number():
    out = score_evidence.present(0.55, None)
    assert out["status"] == "not_measured" and "honest_chance" not in out


def test_only_a_barrier_model_on_the_real_question_matches():
    assert score_evidence.model_matches(_model())
    assert not score_evidence.model_matches(_model(label_kind="endpoint", stop_return_pct=None))
    assert not score_evidence.model_matches(_model(prediction_horizon_days=5))
    assert not score_evidence.model_matches(None)


def test_the_shipped_evidence_file_loads_and_is_conservative():
    ev = score_evidence.load()
    assert ev is not None and ev["applies_to"] == score_evidence.APPLIES_TO
    assert ev["honesty"]["ceiling"] < 0.35  # no idea may be shown with a high chance
    assert score_evidence.present(0.55, ev)["honest_chance"] < 0.3


def test_every_idea_card_shows_the_honest_score_and_stored_confidence_is_untouched(
    client, db_session, monkeypatch, evidence
):
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: evidence)
    _model(db_session)
    raws = [0.35, 0.55, 0.65, 0.9]
    run_id = _run_with(
        db_session,
        [
            {"symbol": f"S{i}", "kind": "idea", "confidence": p, "score_source": "model"}
            for i, p in enumerate(raws)
        ],
    )
    body = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()
    assert len(body["decisions"]) == len(raws)
    for d in body["decisions"]:
        expected = score_evidence.present(d["confidence"], evidence)
        assert d["honest_score"] == expected  # the shown score IS the calibrated one
        assert d["honest_score"]["honest_chance"] < d["confidence"]  # never the raw model number
    assert sorted(d["confidence"] for d in body["decisions"]) == sorted(raws)  # stored score unchanged


def test_endpoint_model_scores_are_not_presented_as_chances(client, db_session, evidence, monkeypatch):
    monkeypatch.setattr(score_evidence, "load", lambda *_a, **_k: evidence)
    _model(
        db_session,
        label_kind="endpoint",
        prediction_horizon_days=5,
        target_return_pct=0.02,
        stop_return_pct=None,
    )
    run_id = _run_with(
        db_session, [{"symbol": "S0", "kind": "idea", "confidence": 0.7, "score_source": "model"}]
    )
    d = client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()["decisions"][0]
    assert d["honest_score"]["status"] == "not_measured"
    assert "honest_chance" not in d["honest_score"]


def test_combined_scores_pass_through_and_holdings_have_none(client, db_session):
    run_id = _run_with(
        db_session,
        [
            {"symbol": "C0", "kind": "idea", "confidence": 0.31, "score_source": "combined"},
            {"symbol": "H0", "kind": "holding", "confidence": 0.8, "score_source": "model"},
        ],
    )
    got = {
        d["symbol"]: d["honest_score"]
        for d in client.get(f"/api/v1/brain/runs/{run_id}", headers=HEADERS).json()["decisions"]
    }
    assert got["C0"] == {"status": "calibrated", "honest_chance": 0.31}
    assert got["H0"] is None
