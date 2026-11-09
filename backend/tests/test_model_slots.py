# ruff: noqa: E501 (long test sentences)
"""The slot map matches the code, and promoting a model in one slot cannot change another slot's model."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from swing_trade_ml.core.plans import BASE_MODEL
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.registry import activate_model, get_active_model
from swing_trade_ml.services import model_slots as slots
from swing_trade_ml.shadow_lanes.lane_universe import MID_MODEL_NAME

PKG = Path(slots.__file__).resolve().parents[1]


def _model(db, name, version, status="TRAINED", activated_at=None):
    m = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        prediction_horizon_days=15,
        feature_names=["a"],
        activated_at=activated_at,
    )
    db.add(m)
    db.flush()
    return m


def test_names_in_the_map_equal_the_names_the_code_uses():
    assert slots.SLOT_MODEL_NAME["large"] == BASE_MODEL == "swing_classifier"
    assert slots.SLOT_MODEL_NAME["midcap"] == MID_MODEL_NAME
    reader = (PKG / "brain" / "reader.py").read_text("utf-8")
    assert re.search(r'FALLBACK_MODEL_NAME\s*=\s*"%s"' % re.escape(slots.SLOT_MODEL_NAME["large"]), reader)
    jobs = (PKG / "workers" / "jobs.py").read_text("utf-8")
    assert f'model_name="{slots.SLOT_MODEL_NAME["large"]}"' in jobs  # the daily watchlist scoring job
    predict = (PKG / "ml" / "predict.py").read_text("utf-8")
    assert f'model_name: str | None = "{slots.SLOT_MODEL_NAME["large"]}"' in predict
    brain_training = (PKG / "brain" / "modules" / "m06_reason" / "training.py").read_text("utf-8")
    assert f'barrier_name: str = "{slots.BARRIER_MODEL_NAME}"' in brain_training


def test_slot_names_are_distinct_and_resolve_back():
    names = list(slots.SLOT_MODEL_NAME.values())
    assert len(set(names)) == len(names)
    for tier, name in slots.SLOT_MODEL_NAME.items():
        assert slots.slot_for_model_name(name) == tier
    assert slots.slot_for_model_name("something_else") is None


def test_promoting_one_slot_leaves_every_other_slot_unchanged(db_session):
    now = datetime.now(UTC)
    before = {}
    for i, name in enumerate(slots.SLOT_MODEL_NAME.values()):
        before[name] = _model(db_session, name, "v1", "ACTIVE", now - timedelta(days=10 + i))
    new_mid = _model(db_session, slots.SLOT_MODEL_NAME["midcap"], "v2")
    seen_before = {n: get_active_model(db_session, n).id for n in slots.SLOT_MODEL_NAME.values()}

    activate_model(db_session, new_mid.id)

    for tier, name in slots.SLOT_MODEL_NAME.items():
        got = get_active_model(db_session, name)
        if tier == "midcap":
            assert got.id == new_mid.id
        else:
            assert got.id == seen_before[name] == before[name].id


def test_unnamed_lookup_follows_the_newest_active_model_of_any_name_known_gap(db_session):
    """Characterisation of gap G5: a name-less lookup returns the newest ACTIVE model whatever its slot.
    If this test starts failing, the behaviour changed on purpose: update docs/brain/ACTIVATION-READINESS.md."""
    now = datetime.now(UTC)
    large = _model(db_session, slots.SLOT_MODEL_NAME["large"], "v1", "ACTIVE", now - timedelta(days=5))
    mid = _model(db_session, slots.SLOT_MODEL_NAME["midcap"], "v1", "TRAINED")
    assert get_active_model(db_session).id == large.id
    activate_model(db_session, mid.id)
    assert get_active_model(db_session).id == mid.id  # the name-less caller now sees the mid-cap model
    assert get_active_model(db_session, slots.SLOT_MODEL_NAME["large"]).id == large.id  # named callers do not


def test_unnamed_lookup_list_is_real():
    for rel in slots.UNNAMED_LOOKUPS:
        text = (PKG / rel).read_text("utf-8")
        assert re.search(r"get_active_model\(\s*db\s*\)", text), f"{rel} no longer calls get_active_model(db) without a name"
