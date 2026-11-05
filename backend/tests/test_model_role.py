# ruff: noqa: N812 (S and F are the module aliases the lane tests use)
"""Model role (fold / final / prod): the registry tells evaluation folds apart from frozen final models, and a
shadow lane refuses anything that is not a frozen final model.

These are software tests of the bookkeeping. They say nothing about whether any model works."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services.model_registry import model_view, role_of
from swing_trade_ml.shadow_lanes import lane_freeze as F
from swing_trade_ml.shadow_lanes import lane_job
from swing_trade_ml.shadow_lanes import lane_service as S


def m(name, role=None, horizon=15, id_=1):
    return SimpleNamespace(id=id_, name=name, model_role=role, prediction_horizon_days=horizon)


# ---------------------------------------------------------------- role_of


def test_stored_role_wins():
    assert role_of(m("sl1_S1_lane_20261205", "final")) == {"role": "final", "recorded": True}
    assert role_of(m("swing_classifier", "prod")) == {"role": "prod", "recorded": True}


@pytest.mark.parametrize(
    "name", ["sl1_S1_20230701", "sl1_S0M_20260815", "sl1_S2_20240102", "td_h10_20250101"]
)
def test_unmarked_fold_style_name_is_shown_as_fold_but_not_recorded(name):
    assert role_of(m(name)) == {"role": "fold", "recorded": False}


@pytest.mark.parametrize("name", ["sl1_S1_lane_20261205", "td_h10_lane_20261205", "swing_classifier", "x"])
def test_other_unmarked_names_are_unmarked(name):
    assert role_of(m(name)) == {"role": "unmarked", "recorded": False}


def test_unknown_stored_value_is_not_trusted():
    assert role_of(m("sl1_S1_lane_20261205", "winner"))["role"] == "unmarked"


# ---------------------------------------------------------------- the lane gate


def test_fold_model_is_refused():
    with pytest.raises(S.LaneError, match="fold"):
        lane_job.require_eligible_role(m("sl1_S1_20230701"), "15d-large")


def test_fold_model_even_if_someone_marked_it_fold_is_refused():
    with pytest.raises(S.LaneError, match="fold"):
        lane_job.require_eligible_role(m("sl1_S1_20230701", "fold"), "15d-large")


def test_final_looking_name_without_a_recorded_role_is_refused():
    with pytest.raises(S.LaneError, match="not marked"):
        lane_job.require_eligible_role(m("sl1_S1_lane_20261205"), "15d-large")


def test_legacy_unmarked_row_is_refused():
    with pytest.raises(S.LaneError, match="not marked"):
        lane_job.require_eligible_role(m("td_h10_t1", None, 10), "10d-large")


def test_final_is_accepted():
    lane_job.require_eligible_role(m("sl1_S1_lane_20261205", "final"), "15d-large")


def test_prod_is_refused_where_the_slot_does_not_allow_it_and_accepted_where_it_does(monkeypatch):
    prod = m("swing_classifier", "prod", 15)
    with pytest.raises(S.LaneError):
        lane_job.require_eligible_role(prod, "15d-large")
    monkeypatch.setattr(lane_job, "PROD_ALLOWED_SLOTS", frozenset({"15d-large"}))
    lane_job.require_eligible_role(prod, "15d-large")


def _patch_run(monkeypatch, model, calls):
    monkeypatch.setattr(lane_job.lane_universe, "load_universe", lambda *a, **k: {"sha256": "u"})
    monkeypatch.setattr(lane_job.lane_universe, "group_symbols", lambda u, g: ["A"])
    monkeypatch.setattr(lane_job, "model_conflict", lambda db, k: None)
    monkeypatch.setattr(lane_job, "lane_model_for", lambda db, k: model)
    monkeypatch.setattr(S, "evaluate_matured", lambda db, day: {})

    def record_day(db, mdl, slot_key, *a, **k):
        calls.append(slot_key)
        return "recorded"

    monkeypatch.setattr(S, "record_day", record_day)


def test_run_daily_refuses_a_fold_and_records_nothing(monkeypatch):
    calls: list[str] = []
    _patch_run(monkeypatch, m("sl1_S1_20230701"), calls)
    out = lane_job.run_daily(None)
    assert calls == []
    assert all(v.startswith("not_recorded: ") and "fold" in v for v in out["slots"].values())


def test_run_daily_records_a_final_model(monkeypatch):
    calls: list[str] = []
    _patch_run(monkeypatch, m("sl1_S1_lane_20261205", "final"), calls)
    out = lane_job.run_daily(None)
    assert sorted(calls) == sorted(S.SLOTS)
    assert set(out["slots"].values()) == {"recorded"}


def test_one_slot_refusal_does_not_stop_the_others(monkeypatch):
    calls: list[str] = []
    final = m("sl1_S1_lane_20261205", "final")
    fold = m("sl1_S1_20230701")
    _patch_run(monkeypatch, final, calls)
    keys = list(S.SLOTS)
    monkeypatch.setattr(lane_job, "lane_model_for", lambda db, k: fold if k == keys[0] else final)
    out = lane_job.run_daily(None)
    assert out["slots"][keys[0]].startswith("not_recorded")
    assert [out["slots"][k] for k in keys[1:]] == ["recorded"] * (len(keys) - 1)


# ---------------------------------------------------------------- freezing marks the model final


def test_mark_final_records_role_and_qualification_without_touching_status():
    model = SimpleNamespace(id=7, name="sl1_S1_lane_20261205", status="TRAINED", metrics={"auc": 0.6})
    F._mark_final(None, model, "15d-large", "S1", Path("rep.json"), "2026-12-08T10:00:00")
    assert model.model_role == "final" and model.status == "TRAINED"
    assert model.metrics["auc"] == 0.6
    assert model.metrics["qualification"] == {
        "slot_key": "15d-large",
        "candidate": "S1",
        "history_report": "rep.json",
        "frozen_at": "2026-12-08T10:00:00",
    }


# ---------------------------------------------------------------- the database column and the API view


def test_role_is_stored_and_exposed_in_the_registry_view(db_session):
    model = MLModel(
        name="sl1_S1_lane_20261205",
        version="v1",
        algorithm="lightgbm",
        status="TRAINED",
        prediction_horizon_days=15,
        feature_names=["a"],
        training_symbols=["X"],
        model_role="final",
    )
    legacy = MLModel(
        name="sl1_S1_20230701",
        version="v1",
        algorithm="lightgbm",
        status="TRAINED",
        prediction_horizon_days=15,
        feature_names=["a"],
        training_symbols=["X"],
    )
    db_session.add_all([model, legacy])
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(MLModel, model.id).model_role == "final"
    assert db_session.get(MLModel, legacy.id).model_role is None
    assert model_view(model, {})["role"] == {"role": "final", "recorded": True}
    assert model_view(legacy, {})["role"] == {"role": "fold", "recorded": False}
    # same slot, different roles: the registry no longer lets them look alike
    assert model_view(model, {})["slot"] == model_view(legacy, {})["slot"] == "15d-large"
