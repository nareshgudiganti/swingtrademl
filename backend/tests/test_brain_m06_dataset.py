"""M06 dataset builder and artifact store, with tiny stand-in base models."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import joblib
import numpy as np
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.preprocessing import StandardScaler

from swing_trade_ml.brain.modules.m01_quality.quality import IST, is_trading_day
from swing_trade_ml.brain.modules.m06_reason import artifact
from swing_trade_ml.brain.modules.m06_reason.dataset import build_dataset, score_bundle
from swing_trade_ml.brain.modules.m06_reason.trainer import Combiner
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml import market_context
from swing_trade_ml.ml.features import FEATURE_COLUMNS

LAST = date(2026, 6, 30)


def _bundle(prior: float):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(50, len(FEATURE_COLUMNS)))
    y = (rng.uniform(size=50) < prior).astype(int)
    return {
        "estimator": DummyClassifier(strategy="prior").fit(x, y),
        "scaler": StandardScaler().fit(x),
        "feature_names": list(FEATURE_COLUMNS),
    }


def _model(db, tmp_path, name, prior, train_end):
    path = tmp_path / f"{name}.joblib"
    joblib.dump(_bundle(prior), path)
    m = MLModel(
        name=name,
        version="v1",
        algorithm="dummy",
        status="ACTIVE",
        artifact_path=str(path),
        feature_names=list(FEATURE_COLUMNS),
        train_end=train_end,
        prediction_horizon_days=15,
    )
    db.add(m)
    db.flush()
    return m


def _series(db, symbol, token, *, watch, seed, start, n=420):
    inst = db.query(Instrument).filter_by(tradingsymbol=symbol).one_or_none()
    if inst is None:
        inst = Instrument(
            instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
        )
        db.add(inst)
        db.flush()
    rng = np.random.default_rng(seed)
    days, d = [], LAST
    while len(days) < n:
        if is_trading_day(d):
            days.append(d)
        d -= timedelta(days=1)
    closes = start * np.cumprod(1 + 0.0005 + rng.normal(0, 0.02, n))
    for day, close in zip(sorted(days), closes, strict=True):
        db.add(
            Candle(
                instrument_id=inst.id,
                interval="day",
                ts=datetime.combine(day, time(0, 0), tzinfo=IST),
                open=close,
                high=close * 1.02,
                low=close * 0.98,
                close=close,
                volume=100_000,
            )
        )


@pytest.fixture()
def world(db_session, tmp_path):
    market_context.clear_cache()
    _series(db_session, "M06STOCK", 998001, watch=True, seed=31, start=500.0)
    _series(db_session, settings.BENCHMARK_INDEX_SYMBOL, 998002, watch=False, seed=32, start=25_000.0)
    _series(db_session, "INDIA VIX", 998003, watch=False, seed=33, start=14.0)
    train_end = datetime(2025, 12, 31, tzinfo=UTC)
    barrier = _model(db_session, tmp_path, "test_barrier", 0.2, train_end)
    swing = _model(db_session, tmp_path, "test_swing", 0.3, train_end - timedelta(days=30))
    db_session.commit()
    yield barrier, swing
    market_context.clear_cache()


def test_the_dataset_holds_only_unseen_labelled_rows_with_both_scores(db_session, world):
    barrier, swing = world
    frame = build_dataset(db_session, barrier, swing, ["M06STOCK"])
    assert len(frame) > 0
    assert frame["day"].min() > np.datetime64("2026-01-20")  # after train_end + 15 trading days
    assert set(frame["target"].unique()) <= {0, 1}
    assert frame["p_barrier"].between(0, 1).all() and frame["p_swing"].between(0, 1).all()
    for col in ("nifty_trend_regime", "breadth_pct_above_sma50", "relative_strength_20d", "high_52w_dist"):
        assert col in frame


def test_score_bundle_reads_a_feature_mapping():
    p = score_bundle(_bundle(0.25), dict.fromkeys(FEATURE_COLUMNS, 0.0))
    assert p == pytest.approx(0.25, abs=0.05)
    assert score_bundle(_bundle(0.25), {"rsi_14": 50.0}) is None  # missing features: no score


def test_artifacts_are_versioned_and_the_newest_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    import pandas as pd

    frame = pd.DataFrame(
        {
            "p_barrier": np.linspace(0.05, 0.5, 200),
            "target": [0, 1] * 100,
            "day": pd.bdate_range("2026-01-01", periods=200),
        }
    )
    combiner = Combiner.fit(frame, "calibrated_barrier")
    first = artifact.save(combiner, {"chosen": "calibrated_barrier"}, base_models={"barrier": "b v1"})
    second = artifact.save(combiner, {"chosen": "calibrated_barrier"}, base_models={"barrier": "b v1"})
    assert first.name == "brain_meta_v1.joblib" and second.name == "brain_meta_v2.joblib"
    assert (tmp_path / "brain_meta_v2.json").exists()
    loaded = artifact.load_latest()
    assert loaded["version"] == "v2" and loaded["combiner"].kind == "calibrated_barrier"


def test_no_artifact_loads_as_none(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path))
    assert artifact.load_latest() is None


def test_training_refuses_models_that_rank_nothing(db_session, world, tmp_path, monkeypatch):
    """The stand-in models give every stock the same score, so no combiner can
    rank better than chance: nothing is adopted or saved, and the reason says so."""
    from swing_trade_ml.brain.modules.m06_reason.training import TrainingError, train_and_save

    monkeypatch.setattr(settings, "MODEL_ARTIFACT_DIR", str(tmp_path / "out"))
    barrier, swing = world
    with pytest.raises(TrainingError, match="better than chance"):
        train_and_save(db_session, barrier.name, swing.name, symbols=["M06STOCK"])
    assert artifact.load_latest() is None


def test_training_without_the_models_says_what_is_missing(db_session):
    from swing_trade_ml.brain.modules.m06_reason.training import TrainingError, train_and_save

    with pytest.raises(TrainingError, match="no active model named 'nope'"):
        train_and_save(db_session, "nope", "nope_either")
