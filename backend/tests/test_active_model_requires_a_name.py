"""Asking for "the" active model has no correct answer, so it must not invent one.

Three models are active at once, one per cap tier, each serving its own
strategy. `get_active_model(db, None)` ordered by activated_at and took the
newest, so on prod a 22-millisecond difference in activation time decided
which model answered a nameless lookup — and `real_trading`, which passes
model_name=None, was scoring real Zerodha holdings with the small-cap model
whatever the stock actually was.

The same defect was caught once before for predict_watchlist, whose code
comment records mid-cap silently shadowing large-cap from Aug 12 until someone
noticed. Fixing it at the source rather than at each caller is the point.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.registry import active_models, get_active_model

# The real activation timestamps from prod, 22ms apart.
ACTIVATED = {
    "swing_classifier": datetime(2026, 8, 28, 14, 8, 8, 757214, tzinfo=UTC),
    "swing_classifier_midcap": datetime(2026, 8, 28, 14, 8, 8, 770485, tzinfo=UTC),
    "swing_classifier_smallcap": datetime(2026, 8, 28, 14, 8, 8, 779490, tzinfo=UTC),
}


def _active(db_session, name: str, version: str) -> MLModel:
    model = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=ModelStatus.ACTIVE,
        artifact_path=f"/models/{name}_{version}.joblib",
        feature_names=["a", "b"],
        trained_at=datetime(2026, 8, 28, tzinfo=UTC),
        activated_at=ACTIVATED.get(name, datetime(2026, 8, 28, tzinfo=UTC)),
    )
    db_session.add(model)
    db_session.flush()
    return model


def test_a_nameless_lookup_does_not_pick_an_arbitrary_tier(db_session):
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_midcap", "v2")
    _active(db_session, "swing_classifier_smallcap", "v1")

    with pytest.raises(ValueError, match="names a model"):
        get_active_model(db_session)


def test_the_error_names_every_candidate_so_the_caller_can_choose(db_session):
    """A caller hitting this needs to know which names exist, not just that
    it was ambiguous."""
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_smallcap", "v1")

    with pytest.raises(ValueError) as exc:
        get_active_model(db_session)

    assert "swing_classifier" in str(exc.value)
    assert "swing_classifier_smallcap" in str(exc.value)


def test_a_named_lookup_still_returns_that_tier(db_session):
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_smallcap", "v1")

    assert get_active_model(db_session, "swing_classifier").version == "v2"
    assert get_active_model(db_session, "swing_classifier_smallcap").version == "v1"


def test_one_active_model_is_still_unambiguous(db_session):
    """A single-model install — and every existing test — must keep working.
    The lookup is only ambiguous when it actually is."""
    _active(db_session, "swing_classifier", "v2")

    assert get_active_model(db_session).name == "swing_classifier"


def test_no_active_model_returns_none_rather_than_raising(db_session):
    """Nothing trained yet is an ordinary startup state, not an error."""
    assert get_active_model(db_session) is None


def test_active_models_lists_every_tier(db_session):
    """What the status header actually wants: all of them, in a stable order,
    rather than one picked by a race."""
    _active(db_session, "swing_classifier_smallcap", "v1")
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_midcap", "v2")

    assert [m.name for m in active_models(db_session)] == [
        "swing_classifier",
        "swing_classifier_midcap",
        "swing_classifier_smallcap",
    ]


def test_archived_models_are_not_listed(db_session):
    _active(db_session, "swing_classifier", "v2")
    archived = _active(db_session, "swing_classifier_midcap", "v3")
    archived.status = ModelStatus.ARCHIVED
    db_session.flush()

    assert [m.name for m in active_models(db_session)] == ["swing_classifier"]
