"""Split and walk-forward tests.

These guard the evaluation itself. A split that shares a day between train and
test, or trains on labels whose outcome window reaches into the test period,
produces a score that looks fine and means nothing — and every model decision
downstream is made on that score.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml.dataset import chronological_split
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from swing_trade_ml.ml.train import fit_and_score, walk_forward

SYMBOLS = ["AAA", "BBB", "CCC", "DDD"]


def _pooled(n_dates: int = 100, seed: int = 7) -> pd.DataFrame:
    """Several symbols sharing the same bar dates, sorted by ts like the real frame."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_dates, tz="UTC")
    rows = len(dates) * len(SYMBOLS)
    frame = pd.DataFrame(rng.normal(size=(rows, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    frame["ts"] = np.repeat(dates, len(SYMBOLS))
    frame["symbol"] = SYMBOLS * len(dates)
    # Loosely tied to the first feature so the fit has something to find.
    frame["target"] = (frame[FEATURE_COLUMNS[0]] + rng.normal(0, 1, rows) > 0.5).astype(int)
    return frame.sort_values("ts", kind="stable").reset_index(drop=True)


def _distinct(ts: pd.Series) -> list:
    return sorted(ts.drop_duplicates())


def test_split_never_puts_one_date_on_both_sides():
    dataset = _pooled(n_dates=37)
    # 37 dates x 4 symbols = 148 rows; 0.2 lands a row-count cut mid-date.
    assert int(len(dataset) * 0.8) % len(SYMBOLS) != 0

    train, test = chronological_split(dataset, 0.2)

    assert set(train["ts"]).isdisjoint(set(test["ts"]))
    assert train["ts"].max() < test["ts"].min()
    assert len(train) + len(test) == len(dataset)
    # Every date keeps all of its symbols on whichever side it landed.
    assert (test.groupby("ts").size() == len(SYMBOLS)).all()


def test_split_keeps_positional_signature():
    dataset = _pooled(n_dates=50)
    train, test = chronological_split(dataset, 0.2)
    assert not train.empty and not test.empty


def test_embargo_drops_exactly_the_last_dates_before_test():
    dataset = _pooled(n_dates=60)
    embargo = 5

    plain_train, plain_test = chronological_split(dataset, 0.25)
    train, test = chronological_split(dataset, 0.25, embargo_days=embargo)

    pd.testing.assert_frame_equal(test, plain_test)
    plain_dates, train_dates = _distinct(plain_train["ts"]), _distinct(train["ts"])
    assert train_dates == plain_dates[:-embargo]
    assert len(plain_train) - len(train) == embargo * len(SYMBOLS)

    # No training row's date is within `embargo` trading dates of test start.
    all_dates = _distinct(dataset["ts"])
    test_start_idx = all_dates.index(test["ts"].min())
    last_train_idx = all_dates.index(train["ts"].max())
    assert test_start_idx - last_train_idx > embargo


def test_embargo_longer_than_training_empties_it():
    dataset = _pooled(n_dates=10)
    train, test = chronological_split(dataset, 0.5, embargo_days=50)
    assert train.empty
    assert not test.empty


def test_walk_forward_folds_are_ordered_non_overlapping_and_embargoed():
    dataset = _pooled(n_dates=120)
    embargo = 3

    folds = walk_forward(dataset, 4, embargo_days=embargo, algorithm="logistic_regression")

    assert [f["fold"] for f in folds] == [1, 2, 3, 4]
    assert all(not f["skipped"] for f in folds)

    all_dates = _distinct(dataset["ts"])
    idx = {pd.Timestamp(d).isoformat(): i for i, d in enumerate(all_dates)}
    previous_test_end = None
    previous_n_train = 0
    for f in folds:
        assert f["test_start"] <= f["test_end"]
        assert f["train_end"] < f["test_start"]
        assert idx[f["test_start"]] - idx[f["train_end"]] > embargo
        if previous_test_end is not None:
            assert f["test_start"] > previous_test_end
        # Expanding window: training only grows.
        assert f["n_train"] > previous_n_train
        assert f["n_test"] > 0
        assert 0.0 <= f["test_positive_rate"] <= 1.0
        assert "precision_at_threshold" in f["metrics"]
        previous_test_end, previous_n_train = f["test_end"], f["n_train"]


def test_walk_forward_skips_degenerate_fold_instead_of_crashing():
    dataset = _pooled(n_dates=100)
    dates = _distinct(dataset["ts"])
    # 3 folds -> 4 blocks of 25 dates; make the last test block all negatives.
    dataset.loc[dataset["ts"] >= dates[75], "target"] = 0

    folds = walk_forward(dataset, 3, embargo_days=2, algorithm="logistic_regression")

    assert len(folds) == 3
    assert folds[-1]["skipped"] is True
    assert "one class" in folds[-1]["reason"]
    assert "metrics" not in folds[-1]
    assert all(not f["skipped"] for f in folds[:-1])


def test_walk_forward_skips_fold_emptied_by_embargo():
    dataset = _pooled(n_dates=40)
    # 10-date blocks; a 15-date embargo wipes fold 1's training entirely.
    folds = walk_forward(dataset, 3, embargo_days=15, algorithm="logistic_regression")
    assert folds[0]["skipped"] is True
    assert folds[0]["n_train"] == 0
    assert "empty" in folds[0]["reason"]


def test_walk_forward_rejects_zero_folds():
    with pytest.raises(ValueError):
        walk_forward(_pooled(n_dates=20), 0, embargo_days=0)


def test_fit_and_score_is_deterministic():
    dataset = _pooled(n_dates=60)
    train, test = chronological_split(dataset, 0.25, embargo_days=3)

    _, _, first = fit_and_score(train, test, "logistic_regression")
    _, _, second = fit_and_score(train, test, "logistic_regression")

    assert first == second
    assert first["train_rows"] == len(train)
    assert first["test_rows"] == len(test)


def test_train_model_stores_folds_and_writes_one_version(monkeypatch):
    """Walk-forward must ride along on one training run, not multiply it."""
    import swing_trade_ml.ml.train as train_module

    dataset = _pooled(n_dates=80)
    versions: list[str] = []
    artifacts: list[str] = []

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

    def fake_next_version(db, name):
        versions.append(name)
        return "v1"

    def fake_save_artifact(name, version, payload):
        artifacts.append(version)
        return "memory://artifact"

    monkeypatch.setattr(train_module, "next_version", fake_next_version)
    monkeypatch.setattr(train_module, "save_artifact", fake_save_artifact)

    db = _FakeSession()
    record = train_module.train_model(
        db, algorithm="logistic_regression", horizon_days=4, walk_forward_folds=3,
    )

    assert len(versions) == 1 and len(artifacts) == 1 and len(db.added) == 1
    folds = record.metrics["walk_forward"]
    assert len(folds) == 3
    assert record.metrics["embargo_days"] == 4
    # Lands in a JSON column — must serialise as-is.
    json.dumps(record.metrics)
