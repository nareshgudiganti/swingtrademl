# ruff: noqa: E501
"""#328 slice 2b: cards for the five-day and selection-lab paths, as sidecar files, protected code untouched."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest
from sklearn.linear_model import LogisticRegression

from swing_trade_ml.brain import card_trainers as ct
from swing_trade_ml.brain import five_day_train, selection_lab
from swing_trade_ml.ml.features import FEATURE_COLUMNS


def _fake_row(tmp_path, label_kind):
    path = tmp_path / "m_v1.joblib"
    joblib.dump({"estimator": LogisticRegression(), "feature_names": FEATURE_COLUMNS}, path)
    return SimpleNamespace(
        name="m", version="v1", algorithm="lightgbm", artifact_path=str(path),
        feature_names=FEATURE_COLUMNS, training_symbols=["B", "A"],
        train_start=datetime(2023, 1, 2, tzinfo=UTC), train_end=datetime(2023, 6, 1, tzinfo=UTC),
        n_samples=500, prediction_horizon_days=5, target_return_pct=0.02, stop_return_pct=None,
        label_kind=label_kind, metrics={"train_rows": 400, "asof_cutoff": "2023-06-30"},
    )


def test_card_contents_and_untouched_artifact(tmp_path):
    model = _fake_row(tmp_path, "endpoint")
    path = Path(model.artifact_path)
    data = path.read_bytes()
    card = ct.write_card(model, invoked_by="test", train_args={"name": "m"})
    side = ct.sidecar_path(path)
    assert side.is_file() and json.loads(side.read_text()) == card
    assert path.read_bytes() == data  # artifact bytes untouched
    assert card["artifact_sha256"] == hashlib.sha256(data).hexdigest()
    assert card["universe"]["symbols"] == ["A", "B"]
    assert card["data_window"]["test_start"] is None and card["training_matrix_sha256"] is None
    assert card["rows"] == {"dataset": 500, "train": 400, "test": None}
    assert card["training"]["estimator_class"].endswith("LogisticRegression")
    assert card["feature_names"] == FEATURE_COLUMNS
    with pytest.raises(FileExistsError):
        ct.write_card(model, invoked_by="test", train_args={})


def test_five_day_path_gets_a_card(monkeypatch, tmp_path):
    row = _fake_row(tmp_path, "endpoint")
    monkeypatch.setattr(five_day_train, "train_endpoint_model", lambda db, **kw: row)
    got = ct.train_endpoint_model_with_card(
        None, name="m", cutoff=date(2023, 6, 30), horizon_days=5, target_return=0.02, invoked_by="x"
    )
    assert got is row
    card = json.loads(ct.sidecar_path(row.artifact_path).read_text())
    assert card["label"]["kind"] == "endpoint" and card["training"]["args"]["horizon_days"] == 5
    assert card["training"]["invoked_by"] == "x" and card["asof_cutoff"] == "2023-06-30"


def test_selection_lab_path_gets_a_card(monkeypatch, tmp_path):
    row = _fake_row(tmp_path, "excess_top30")
    monkeypatch.setattr(selection_lab, "train_lab_model", lambda db, **kw: row)
    got = ct.train_lab_model_with_card(
        None, name="m", cutoff=date(2023, 6, 30), symbols=["A", "B"], candidates=["A"], bars={}
    )
    assert got is row
    card = json.loads(ct.sidecar_path(row.artifact_path).read_text())
    assert card["label"]["kind"] == "excess_top30"
    assert card["training"]["args"]["symbols_count"] == 2


def test_unknowns_are_null_when_the_file_is_missing(tmp_path):
    row = _fake_row(tmp_path, "endpoint")
    row.artifact_path = str(tmp_path / "gone.joblib")
    card = ct.card_from_record(row, invoked_by=None, train_args={})
    assert card["artifact_sha256"] is None and card["training"]["estimator_class"] is None


def test_protected_trainers_do_not_know_about_cards():
    """The protocol-frozen trainers are not edited by this feature; their pinned hashes are checked by the
    protocol tools and test_model_artifact_safety."""
    for module in (five_day_train, selection_lab):
        src = inspect.getsource(module)
        assert "card_trainers" not in src and "model_card" not in src


def test_no_card_is_written_when_the_artifact_file_is_missing(tmp_path):
    row = _fake_row(tmp_path, "endpoint")
    Path(row.artifact_path).unlink()
    assert ct.write_card(row, invoked_by=None, train_args={}) is None
    assert list(tmp_path.iterdir()) == []


def test_a_card_failure_never_fails_training_in_either_path(monkeypatch, tmp_path):
    row = _fake_row(tmp_path, "endpoint")
    monkeypatch.setattr(five_day_train, "train_endpoint_model", lambda db, **kw: row)
    monkeypatch.setattr(selection_lab, "train_lab_model", lambda db, **kw: row)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ct, "card_from_record", boom)
    got = ct.train_endpoint_model_with_card(
        None, name="m", cutoff=date(2023, 6, 30), horizon_days=5, target_return=0.02
    )
    assert got is row
    got = ct.train_lab_model_with_card(None, name="m", cutoff=date(2023, 6, 30), symbols=["A"], candidates=[], bars={})
    assert got is row
    assert not ct.sidecar_path(row.artifact_path).exists()
