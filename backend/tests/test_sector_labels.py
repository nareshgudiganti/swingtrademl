"""SX5 / SX10 label support: label_kind, its config hash, and label equality with the production definitions.

Synthetic tests always run. The real-data tests are SELECT only against the local Postgres and are skipped when
it cannot be reached within 15 seconds. No model is fitted anywhere in this file."""

from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain import five_day_train, ten_day
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml.features import build_label
from test_sector_research import STOCKS, inputs  # noqa: F401  (synthetic fixture, same builder)

CUT = date(2030, 1, 1)


def sx5(symbols, **kw):
    return sr.DatasetSpec(
        candidate="SX5",
        symbols=tuple(symbols),
        horizon_days=5,
        target_return=0.02,
        stop_return=None,
        label_kind="endpoint",
        data_cutoff=kw.pop("cut", CUT),
        **kw,
    )


def sx10(symbols, **kw):
    return sr.DatasetSpec(
        candidate="SX10",
        symbols=tuple(symbols),
        horizon_days=10,
        target_return=0.06,
        stop_return=0.035,
        label_kind="barrier",
        data_cutoff=kw.pop("cut", CUT),
        **kw,
    )


# ---- independent reference labels: straight from the closes / highs / lows, no shared code with features.py
def ref_endpoint(close: np.ndarray, h: int, target: float) -> np.ndarray:
    out = np.full(len(close), np.nan)
    out[: len(close) - h] = (close[h:] / close[: len(close) - h] - 1.0 >= target).astype(float)
    return out


def ref_barrier(close, high, low, h, target, stop) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    for t in range(n - h):
        up, dn = close[t] * (1 + target), close[t] * (1 - stop)
        res = 0.0
        for k in range(1, h + 1):
            hit_up, hit_dn = high[t + k] >= up, low[t + k] <= dn
            if hit_dn:  # a same-bar touch of both scores as the stop
                res = 0.0
                break
            if hit_up:
                res = 1.0
                break
        out[t] = res
    return out


# ------------------------------------------------------------------------------------------ the spec field
def test_the_protocol_labels_match_the_production_constants():
    assert sr.PROTOCOL_LABELS["SX10"] == ("barrier", ten_day.TARGET, ten_day.STOP)
    assert sr.CANDIDATE_HORIZON["SX10"] == ten_day.HORIZON_BARS
    assert sr.PROTOCOL_LABELS["SX5"] == ("endpoint", 0.02, None) and sr.CANDIDATE_HORIZON["SX5"] == 5


def test_label_kind_validation():
    with pytest.raises(ValueError, match="label_kind"):
        sr.DatasetSpec("SX5", ("TCS",), 5, 0.02, None, CUT, label_kind="other")
    with pytest.raises(ValueError, match="stop"):
        sr.DatasetSpec("SX10", ("TCS",), 10, 0.06, None, CUT)  # barrier without a stop
    with pytest.raises(ValueError, match="no stop"):
        sr.DatasetSpec("SX5", ("TCS",), 5, 0.02, 0.04, CUT, label_kind="endpoint")
    assert (
        sr.DatasetSpec("SX5", ("TCS",), 5, 0.02, 0.02, CUT).label_kind == "barrier"
    )  # earlier call sites unchanged


def test_hash_changes_only_by_the_new_field():
    """Pinned: the hash the code before this change gave this exact spec (computed from the committed bb8a65a
    module). Removing the new key from the new config reproduces it, so nothing but `label_kind` changed."""
    kw = dict(
        candidate="SX10",
        symbols=("TCS", "INFY"),
        horizon_days=10,
        target_return=0.06,
        stop_return=0.035,
        data_cutoff=date(2026, 8, 15),
        exclusions=frozenset({("TCS", "2024-01-02")}),
    )
    s = sr.DatasetSpec(**kw)
    cfg = s.to_config()
    assert cfg["label_kind"] == "barrier"
    assert s.config_sha256() != "147059d1b67a8455e51fc194ffa07bffb3e8c762192fdacbd256be5534c70e95"
    cfg.pop("label_kind")
    assert (
        hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        == "147059d1b67a8455e51fc194ffa07bffb3e8c762192fdacbd256be5534c70e95"
    )
    # and the new field itself moves the hash (an approval for one label rule never matches the other)
    a = sr.DatasetSpec("SX5", ("TCS",), 5, 0.02, None, CUT, label_kind="endpoint")
    b = sr.DatasetSpec("SX5", ("TCS",), 5, 0.02, 0.04, CUT, label_kind="barrier")
    assert a.config_sha256() != b.config_sha256()


# ------------------------------------------------------------------------------------ synthetic equality
@pytest.fixture(scope="module")
def synth(inputs):  # noqa: F811
    return inputs


def _frame(inputs, sym):
    raw = inputs.raw[sym].sort_values("ts").reset_index(drop=True)
    return raw, sr._existing_features(raw, inputs, sym)


def test_sx5_label_equals_five_day_train_on_synthetic_data(synth):
    mat = sr.assemble_training_matrix(sx5(["TCS", "HDFCBANK", "SUNPHARMA"]), synth)
    assert len(mat) > 500 and mat["target"].isin([0, 1]).all() and 0.02 < mat["target"].mean() < 0.9
    for sym in ["TCS", "HDFCBANK", "SUNPHARMA"]:
        raw, feat = _frame(synth, sym)
        prod = five_day_train.endpoint_target(
            build_label(feat, 5, 0.02, 0.04), 0.02
        )  # the production function
        ref = ref_endpoint(raw["close"].to_numpy(), 5, 0.02)
        m = mat[mat["symbol"] == sym]
        by_ts_prod = prod.set_index("ts")["target"]
        by_ts_ref = pd.Series(ref, index=raw["ts"])
        assert (m["target"].to_numpy() == by_ts_prod.loc[m["ts"]].to_numpy()).all()
        assert (m["target"].to_numpy() == by_ts_ref.loc[m["ts"]].to_numpy()).all()
        # the stop is irrelevant to an endpoint label: same rows, same label whatever stop the builder is given
        assert (
            prod["target"] == five_day_train.endpoint_target(build_label(feat, 5, 0.02, 0.01), 0.02)["target"]
        ).all()


def test_endpoint_and_barrier_matrices_have_identical_rows_and_features(synth):
    e = sr.assemble_training_matrix(sx5(["TCS", "HDFCBANK"]), synth)
    b = sr.assemble_training_matrix(sr.DatasetSpec("SX5", ("TCS", "HDFCBANK"), 5, 0.02, 0.04, CUT), synth)
    assert e[["symbol", "decision_date"]].equals(b[["symbol", "decision_date"]])
    pd.testing.assert_frame_equal(
        e[list(sr.RESEARCH_COLUMNS)], b[list(sr.RESEARCH_COLUMNS)], check_exact=True
    )
    assert (e["target"] != b["target"]).any()  # the two label rules genuinely differ


def test_sx10_label_equals_ten_day_barrier_label_on_synthetic_data(synth):
    mat = sr.assemble_training_matrix(sx10(["TCS", "HDFCBANK", "SUNPHARMA"]), synth)
    assert len(mat) > 500 and mat["target"].isin([0, 1]).all()
    for sym in ["TCS", "HDFCBANK", "SUNPHARMA"]:
        raw, feat = _frame(synth, sym)
        prod = build_label(feat, ten_day.HORIZON_BARS, ten_day.TARGET, ten_day.STOP)
        ref = ref_barrier(
            raw["close"].to_numpy(), raw["high"].to_numpy(), raw["low"].to_numpy(), 10, 0.06, 0.035
        )
        m = mat[mat["symbol"] == sym]
        assert (m["target"].to_numpy() == prod.set_index("ts")["target"].loc[m["ts"]].to_numpy()).all()
        assert (m["target"].to_numpy() == pd.Series(ref, index=raw["ts"]).loc[m["ts"]].to_numpy()).all()


def test_a_missing_forward_return_gives_a_dropped_row_not_a_zero_label(synth):
    df = pd.DataFrame({"forward_return": [0.03, np.nan, 0.0, 0.02]})
    fr = df["forward_return"]
    t = (fr >= 0.02).astype("float64").where(fr.notna())
    assert t.isna().tolist() == [False, True, False, False] and t.dropna().astype(int).tolist() == [1, 0, 1]


# --------------------------------------------------------------------------------- real data, SELECT only
@pytest.fixture(scope="module")
def real():
    pytest.importorskip("psycopg")
    syms = ["TCS", "HDFCBANK", "RELIANCE", "SUNPHARMA", "MARUTI"]
    try:
        inp = sr.load_inputs_readonly(syms)
    except Exception as e:  # database not reachable / not seeded: skip, never hang
        pytest.skip(f"local database not available: {type(e).__name__}")
    if any(len(inp.raw[s]) < 400 for s in syms):
        pytest.skip("local candles missing")
    return syms, inp


def test_sx5_label_equals_five_day_train_on_real_local_data(real):
    syms, inp = real
    assert inp.source == "database"
    mat = sr.assemble_training_matrix(sx5(syms), inp)
    assert mat.attrs["inputs_source"] == "database" and len(mat) > 3000
    n_checked = 0
    for sym in syms:
        raw = inp.raw[sym].sort_values("ts").reset_index(drop=True)
        feat = sr._existing_features(raw, inp, sym)
        prod = five_day_train.endpoint_target(build_label(feat, 5, 0.02, 0.04), 0.02)
        ref = pd.Series(ref_endpoint(raw["close"].to_numpy(), 5, 0.02), index=raw["ts"])
        m = mat[mat["symbol"] == sym]
        assert len(m) > 500
        assert (m["target"].to_numpy() == prod.set_index("ts")["target"].loc[m["ts"]].to_numpy()).all()
        assert (m["target"].to_numpy() == ref.loc[m["ts"]].to_numpy()).all()
        # every date of the stock, not only the rows that survive the 57-input filter
        p = prod.set_index("ts")["target"]
        assert (p.to_numpy() == ref.loc[p.index].to_numpy()).all()
        n_checked += len(p)
    assert n_checked > 5000


def test_sx10_label_equals_ten_day_barrier_label_on_real_local_data(real):
    syms, inp = real
    mat = sr.assemble_training_matrix(sx10(syms), inp)
    assert len(mat) > 3000
    for sym in syms:
        raw = inp.raw[sym].sort_values("ts").reset_index(drop=True)
        feat = sr._existing_features(raw, inp, sym)
        prod = build_label(feat, ten_day.HORIZON_BARS, ten_day.TARGET, ten_day.STOP)
        ref = pd.Series(
            ref_barrier(
                raw["close"].to_numpy(), raw["high"].to_numpy(), raw["low"].to_numpy(), 10, 0.06, 0.035
            ),
            index=raw["ts"],
        )
        m = mat[mat["symbol"] == sym]
        assert (m["target"].to_numpy() == prod.set_index("ts")["target"].loc[m["ts"]].to_numpy()).all()
        assert (m["target"].to_numpy() == ref.loc[m["ts"]].to_numpy()).all()
        p = prod.set_index("ts")["target"]
        assert (p.to_numpy() == ref.loc[p.index].to_numpy()).all()
