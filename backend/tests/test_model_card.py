# ruff: noqa: E501
"""Model card at training (#328 slice 1): the card is built from real inputs, stored twice, and honest about gaps."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

import swing_trade_ml.ml.train as train_module
from swing_trade_ml.ml import model_card as mc
from swing_trade_ml.ml.features import FEATURE_COLUMNS

SYMBOLS = ["AAA", "BBB", "CCC", "DDD"]


def _pooled(n_dates: int = 100, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_dates, tz="UTC")
    rows = len(dates) * len(SYMBOLS)
    frame = pd.DataFrame(rng.normal(size=(rows, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    frame["ts"] = np.repeat(dates, len(SYMBOLS))
    frame["symbol"] = SYMBOLS * len(dates)
    frame["target"] = (frame[FEATURE_COLUMNS[0]] + rng.normal(0, 1, rows) > 0.5).astype(int)
    return frame.sort_values("ts", kind="stable").reset_index(drop=True)


def test_fingerprint_is_stable_and_sensitive_to_names():
    a = mc.feature_fingerprint()
    assert a == mc.feature_fingerprint()
    assert a["names_sha256"] != mc.feature_fingerprint(FEATURE_COLUMNS[:-1])["names_sha256"]
    assert a["golden_output_sha256"] == mc.golden_output_hash()


def test_card_fields_and_missing_values_are_null(monkeypatch):
    monkeypatch.setattr(mc, "git_state", lambda: {"sha": None, "dirty": None})
    data = _pooled(n_dates=60)
    train_df, test_df = data.iloc[:200], data.iloc[200:]
    card = mc.build_card(
        train_df=train_df, test_df=test_df, dataset=data, feature_names=FEATURE_COLUMNS,
        algorithm="logistic_regression", train_args={"name": "x"}, horizon_days=5,
        target_return=0.02, stop_return=-0.04, label_kind="barrier",
    )
    json.dumps(card)
    assert card["feature_names"] == FEATURE_COLUMNS
    assert card["git"] == {"sha": None, "dirty": None}  # unknown stays null, not guessed
    assert card["artifact_sha256"] is None
    assert card["universe"]["symbols"] == sorted(SYMBOLS)
    assert card["rows"] == {"dataset": len(data), "train": 200, "test": len(data) - 200}
    assert card["label"] == {"horizon_days": 5, "target_return": 0.02, "stop_return": -0.04, "kind": "barrier"}
    assert set(card["libraries"]) == {"python", "lightgbm", "scikit-learn", "numpy", "pandas"}
    assert card["data_window"]["train_start"] == pd.Timestamp(train_df["ts"].min()).isoformat()
    assert card["input_formula_version"].startswith("features-")
    # the matrix hash follows the data
    changed = train_df.copy()
    changed.loc[changed.index[0], FEATURE_COLUMNS[0]] += 1.0
    assert mc.matrix_sha256(changed, FEATURE_COLUMNS) != card["training_matrix_sha256"]


def test_train_model_stores_card_in_metrics_and_bundle(monkeypatch, tmp_path):
    dataset = _pooled(n_dates=80)

    class _FakeSession:
        def __init__(self):
            self.added: list = []

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            pass

        def refresh(self, obj):
            pass

    monkeypatch.setattr(train_module, "build_training_dataset", lambda db, **kw: dataset)
    monkeypatch.setattr(train_module, "next_version", lambda db, name: "v1")
    monkeypatch.setattr(
        train_module, "save_artifact",
        lambda name, version, bundle: _save(tmp_path, name, version, bundle),
    )
    record = train_module.train_model(_FakeSession(), algorithm="logistic_regression", horizon_days=4)

    card = record.metrics["card"]
    json.dumps(record.metrics)
    path = record.artifact_path
    assert card["artifact_sha256"] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert card["artifact_sha256"] == record.metrics["artifact_sha256"]
    assert card["label"]["horizon_days"] == 4
    assert card["training"]["args"]["algorithm"] == "logistic_regression"
    bundle = joblib.load(path)
    bundle_card = bundle["card"]
    expected = copy.deepcopy(card)
    expected["artifact_sha256"] = None  # a file cannot contain its own hash
    assert bundle_card == expected
    assert bundle["feature_names"] == FEATURE_COLUMNS


def _save(tmp_path, name, version, bundle):
    p = tmp_path / f"{name}_{version}.joblib"
    joblib.dump(bundle, p)
    return str(p)


@pytest.mark.parametrize("bad", [None])
def test_git_failure_gives_nulls(monkeypatch, bad):
    def boom(*a, **k):
        raise OSError("no git")

    monkeypatch.setattr(mc.subprocess, "run", boom)
    assert mc.git_state() == {"sha": None, "dirty": None}
