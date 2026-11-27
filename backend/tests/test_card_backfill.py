# ruff: noqa: E501
"""#328: model cards stay correct when training is re-run or stops half way, and missing cards can be repaired.

- Re-running never duplicates or replaces a good card (`ensure_card`).
- A stop between saving the model file and writing its card leaves no card and no half-written card; the
  backfill finds that model and writes the card. The model file is only ever read.
- A card that no longer matches its model file is reported, and only replaced when asked (`repair=True`),
  with the old card kept beside it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import joblib
import pytest
from sklearn.linear_model import LogisticRegression

from swing_trade_ml.brain import card_trainers as ct
from swing_trade_ml.ml import backup_manifest as bm
from swing_trade_ml.ml.features import FEATURE_COLUMNS


def _row(folder: Path, name: str = "m", version: str = "v1", metrics: dict | None = None):
    path = folder / f"{name}_{version}.joblib"
    joblib.dump({"estimator": LogisticRegression(), "feature_names": FEATURE_COLUMNS}, path)
    return SimpleNamespace(
        name=name,
        version=version,
        algorithm="lightgbm",
        artifact_path=str(path),
        feature_names=FEATURE_COLUMNS,
        training_symbols=["A"],
        train_start=datetime(2023, 1, 2, tzinfo=UTC),
        train_end=datetime(2023, 6, 1, tzinfo=UTC),
        n_samples=10,
        prediction_horizon_days=15,
        target_return_pct=0.08,
        stop_return_pct=0.04,
        label_kind="excess_top30",
        metrics=dict(metrics or {}),
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_card_suffix_is_the_one_the_backup_looks_for():
    assert ct.CARD_SUFFIX == bm.CARD_SUFFIX


def test_ensure_card_writes_once_and_rerunning_changes_nothing(tmp_path):
    row = _row(tmp_path)
    assert ct.card_state(row.artifact_path) == "missing"
    assert ct.ensure_card(row, invoked_by="t", train_args={}) == "written"
    side = ct.sidecar_path(row.artifact_path)
    first = side.read_bytes()
    assert ct.card_state(row.artifact_path) == "ok"
    assert ct.ensure_card(row, invoked_by="again", train_args={"x": 1}) == "present"
    assert side.read_bytes() == first  # never rewritten
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m_v1.joblib", "m_v1.joblib.card.json"]


def test_a_card_that_no_longer_matches_its_file_is_reported_and_left_alone(tmp_path):
    row = _row(tmp_path)
    side = ct.sidecar_path(row.artifact_path)
    side.write_text(json.dumps({"artifact_sha256": "0" * 64}), encoding="utf-8")
    assert ct.card_state(row.artifact_path) == "mismatch"
    assert ct.ensure_card(row, invoked_by="t", train_args={}) == "mismatch"
    assert json.loads(side.read_text())["artifact_sha256"] == "0" * 64
    side.write_text("{not json", encoding="utf-8")
    assert ct.card_state(row.artifact_path) == "mismatch"


def test_no_artifact_means_no_card(tmp_path):
    row = _row(tmp_path)
    Path(row.artifact_path).unlink()
    assert ct.card_state(row.artifact_path) == "no_artifact"
    assert ct.ensure_card(row, invoked_by="t", train_args={}) == "no_artifact"
    assert list(tmp_path.iterdir()) == []


def test_a_stop_while_writing_the_card_leaves_no_card_and_no_temp_file_then_backfill_repairs_it(
    tmp_path, monkeypatch
):
    row = _row(tmp_path)
    before = _digest(Path(row.artifact_path))

    def crash(src, dst):
        raise OSError("power cut")

    monkeypatch.setattr(ct.os, "link", crash)
    with pytest.raises(OSError):
        ct.write_card(row, invoked_by="t", train_args={})
    monkeypatch.undo()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["m_v1.joblib"]  # detectable: no card at all

    found = ct.backfill_missing_cards([row], dry_run=True)
    assert found["missing"] == ["m v1"] and found["written"] == []
    assert not ct.sidecar_path(row.artifact_path).exists()  # a dry run writes nothing

    done = ct.backfill_missing_cards([row])
    assert done["written"] == ["m v1"]
    card = json.loads(ct.sidecar_path(row.artifact_path).read_text())
    assert card["artifact_sha256"] == before
    assert card["source"] == "backfilled_from_saved_row_and_file"
    assert card["training"]["invoked_by"] == "backfill"
    assert _digest(Path(row.artifact_path)) == before  # model file only read


def test_backfill_is_idempotent_and_skips_rows_that_already_carry_a_card(tmp_path):
    general = _row(tmp_path, "swing", "v3", metrics={"card": {"artifact_sha256": "abc"}})
    lab = _row(tmp_path, "sl1_S1", "v1")
    gone = _row(tmp_path, "gone", "v1")
    Path(gone.artifact_path).unlink()
    first = ct.backfill_missing_cards([general, lab, gone])
    assert first["written"] == ["sl1_S1 v1"]
    assert first["card_in_row"] == ["swing v3"]  # ml/train.py rows keep their card in metrics["card"]
    assert first["no_artifact"] == ["gone v1"]
    assert not ct.sidecar_path(general.artifact_path).exists()
    card_bytes = ct.sidecar_path(lab.artifact_path).read_bytes()

    second = ct.backfill_missing_cards([general, lab, gone])
    assert second["written"] == [] and second["present"] == ["sl1_S1 v1"]
    assert ct.sidecar_path(lab.artifact_path).read_bytes() == card_bytes


def test_repair_keeps_the_old_card_beside_the_new_one(tmp_path):
    row = _row(tmp_path)
    side = ct.sidecar_path(row.artifact_path)
    side.write_text(json.dumps({"artifact_sha256": "0" * 64}), encoding="utf-8")
    report = ct.backfill_missing_cards([row])
    assert report["mismatch"] == ["m v1"] and report["repaired"] == []
    assert json.loads(side.read_text())["artifact_sha256"] == "0" * 64

    report = ct.backfill_missing_cards([row], repair=True)
    assert report["repaired"] == ["m v1"]
    assert json.loads(side.read_text())["artifact_sha256"] == _digest(Path(row.artifact_path))
    kept = [p for p in tmp_path.iterdir() if ".card.json.bad-" in p.name]
    assert len(kept) == 1 and json.loads(kept[0].read_text())["artifact_sha256"] == "0" * 64


def test_leftover_temp_files_from_a_killed_writer_are_found_and_cleared(tmp_path):
    row = _row(tmp_path)
    stale = tmp_path / f".m_v1.joblib.card.json.{'a' * 32}.tmp"
    stale.write_text("{half", encoding="utf-8")
    other = tmp_path / "keep.tmp"
    other.write_text("not ours", encoding="utf-8")
    dry = ct.backfill_missing_cards([row], dry_run=True)
    assert dry["stale_temp_files"] == [stale.name] and stale.exists()
    ct.backfill_missing_cards([row])
    assert not stale.exists() and other.exists()


def test_backfill_from_db_reads_every_registered_row(db_session, tmp_path):
    from swing_trade_ml.db.models.ml import MLModel

    path = tmp_path / "dbm_v1.joblib"
    joblib.dump({"estimator": LogisticRegression(), "feature_names": ["a"]}, path)
    db_session.add(
        MLModel(
            name="dbm",
            version="v1",
            algorithm="lightgbm",
            status="TRAINED",
            artifact_path=str(path),
            feature_names=["a"],
            trained_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    report = ct.backfill_from_db(db_session)
    assert "dbm v1" in report["written"]
    assert ct.card_state(path) == "ok"
