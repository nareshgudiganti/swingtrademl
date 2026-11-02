"""Selection lab (design rev 3): fold training, the chronology check, never-activated registration."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from swing_trade_ml.brain import selection_lab as sl
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.features import FEATURE_COLUMNS

IST = "Asia/Kolkata"


def synth(n_days=320, n_syms=8, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    d0 = date(2022, 1, 3)
    days = [d0 + timedelta(days=i) for i in range(n_days)]
    for s in range(n_syms):
        for d in days:
            ts = pd.Timestamp(d, tz=IST).tz_convert("UTC")
            x = rng.normal(size=len(FEATURE_COLUMNS))
            target = int(x[0] + rng.normal(scale=0.5) > 0.4)
            rows.append(
                {
                    "symbol": f"S{s}",
                    "ts": ts,
                    "label_end_ts": ts + pd.Timedelta(days=15),
                    "target": target,
                    **dict(zip(FEATURE_COLUMNS, x, strict=True)),
                }
            )
    return pd.DataFrame(rows)


def test_fit_fold_trains_on_the_earlier_rows_and_purges_overlapping_labels():
    fit = sl.fit_fold(synth())
    test_start = fit.test_df["ts"].min()
    assert fit.train_df["label_end_ts"].max() < test_start
    assert fit.train_df["ts"].max() < test_start
    assert 0.5 < fit.metrics["roc_auc"] <= 1.0
    assert fit.metrics["embargo_days"] == 15 and fit.metrics["label"].startswith("excess")


def test_fit_fold_refuses_a_single_class_frame():
    with pytest.raises(ValueError, match="both classes"):
        sl.fit_fold(synth().assign(target=0))


def test_chronology_check_passes_for_a_clean_fold_and_names_each_violation():
    frame = synth(120)
    cutoff = frame["ts"].min().tz_convert(IST).date() + timedelta(days=60)
    start = cutoff + timedelta(days=1)
    clean = frame[frame["label_end_ts"].dt.tz_convert(IST).dt.date <= cutoff]
    assert sl.chronology_violations(clean, cutoff, start) == []
    late = pd.concat([clean, frame.iloc[[-1]]])
    problems = sl.chronology_violations(late, cutoff, start)
    assert any("label ends after the cutoff" in p for p in problems)
    assert any("dated on or after the first test day" in p for p in problems)


def test_the_fold_trainer_registers_a_trained_never_activated_model(db_session, monkeypatch, tmp_path):
    frame = synth()
    cutoff = date(2022, 11, 20)
    frame = frame[frame["label_end_ts"].dt.tz_convert(IST).dt.date <= cutoff].reset_index(drop=True)
    monkeypatch.setattr(
        "swing_trade_ml.ml.dataset.build_training_dataset", lambda *a, **k: frame.drop(columns=["target"])
    )
    monkeypatch.setattr(
        sl,
        "label_frame",
        lambda ds, bars, cand: (
            ds.assign(day=_days(ds), target=frame["target"].to_numpy()),
            {"rows_in": len(ds)},
        ),
    )
    monkeypatch.setattr(
        sl,
        "apply_gate",
        lambda fr, bars, rec, **k: (
            fr,
            {"rows_in": len(fr), "rows_out": len(fr), "stock_years_left_out": []},
        ),
    )
    monkeypatch.setattr(
        "swing_trade_ml.ml.registry.save_artifact", lambda name, version, bundle: str(tmp_path / "m.joblib")
    )
    rec = sl.train_lab_model(
        db_session,
        name="sl1_S2_20221120",
        cutoff=cutoff,
        symbols=[f"S{i}" for i in range(8)],
        candidates=["S0"],
        bars={},
    )
    row = db_session.scalars(select(MLModel).where(MLModel.id == rec.id)).one()
    assert row.status == "TRAINED" and row.label_kind == "excess_top30" and row.stop_return_pct is None
    assert row.prediction_horizon_days == 15 and "S0" in row.training_symbols
    assert row.metrics["label_report"]["rows_in"] > 0 and row.metrics["gate_report"]["rows_out"] > 0


def _days(ds):
    return [t.tz_convert(IST).date() for t in ds["ts"]]


def test_symbols_must_be_given_explicitly():
    with pytest.raises(ValueError, match="explicit"):
        sl.train_lab_model(None, name="x", cutoff=date(2022, 1, 1), symbols=[], candidates=[], bars={})


def test_the_fold_trainer_never_activates_anything():
    import inspect

    src = inspect.getsource(sl.train_lab_model)
    assert "ModelStatus.TRAINED" in src
    assert "ModelStatus.ACTIVE" not in src and "activate_model" not in src and "auto_activate" not in src
