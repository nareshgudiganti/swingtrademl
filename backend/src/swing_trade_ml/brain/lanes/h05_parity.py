# backend/src/swing_trade_ml/brain/lanes/h05_parity.py
# ruff: noqa: N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Feature parity, not just feature names: does today's feature code, on each model's OWN training stocks and
period, reproduce the statistics the saved scaler learned?

A formula, lookback window, price basis or missing-value change shows up as a shift in an input's mean or
spread. Checked per input: |mean shift| in scaler standard deviations and the ratio of spreads. Read-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes.h05_features import old_obv_slope
from swing_trade_ml.brain.lanes.h05_models import VerifiedModel
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.ml.dataset import build_training_dataset, load_candles


def _old_obv_by_symbol(db: Session, symbols: list[str]) -> dict[str, pd.Series]:
    out = {}
    for sym in symbols:
        inst = db.scalar(
            select(Instrument).where(Instrument.exchange == "NSE", Instrument.tradingsymbol == sym)
        )
        if inst is None:
            continue
        c = load_candles(db, inst.id, "day")
        s = old_obv_slope(c["close"].astype(float), c["volume"].astype(float))
        out[sym] = pd.Series(s.to_numpy(), index=pd.to_datetime(c["ts"], utc=True))
    return out


def compare_window(window: pd.DataFrame, names: list[str], scaler) -> dict:
    """Pure: per input, how far this window's mean and spread sit from what the saved scaler learned.

    `window` holds the model's inputs as today's code builds them plus `obv_training` (obv_slope in the
    training formula). Two bases are compared: the PRIMARY one (training formula) and the production path."""

    def table(basis: str) -> dict:
        x = window[names].copy()
        if basis == P.PRIMARY_BASIS and "obv_slope" in names:
            x["obv_slope"] = window["obv_training"]
        arr = x.to_numpy(dtype=float)
        shift = (np.nanmean(arr, 0) - scaler.mean_) / scaler.scale_
        ratio = np.nanstd(arr, 0) / scaler.scale_
        lo, hi = P.PARITY_SD_RATIO_BAND
        bad = [
            {"input": n, "mean_shift_sd": round(float(a), 3), "sd_ratio": round(float(b), 3)}
            for n, a, b in zip(names, shift, ratio, strict=True)
            if abs(a) > P.PARITY_MEAN_SHIFT_MAX or not (lo <= b <= hi)
        ]
        return {
            "ok": not bad,
            "max_abs_mean_shift_sd": round(float(np.abs(shift).max()), 3),
            "sd_ratio_range": [round(float(ratio.min()), 3), round(float(ratio.max()), 3)],
            "inputs_failing": bad,
        }

    return {
        "rows_compared": len(window),
        "n_inputs": len(names),
        "order_matches_code": names == [n for n in _code_order() if n in names],
        P.PRIMARY_BASIS: table(P.PRIMARY_BASIS),
        P.DIAGNOSTIC_BASIS: table(P.DIAGNOSTIC_BASIS),
    }


def check_group(db: Session, model: VerifiedModel) -> dict:
    """One model, on its own training stocks and period."""
    bundle = model.bundle
    names = list(bundle["feature_names"])
    ds = build_training_dataset(
        db, symbols=sorted(model.training_symbols), horizon_days=P.HORIZON, target_return=P.LABEL_TARGET
    )
    ds["ts"] = pd.to_datetime(ds["ts"], utc=True)
    window = ds[(ds["ts"] >= pd.Timestamp(model.train_start)) & (ds["ts"] <= pd.Timestamp(model.train_end))]
    old = _old_obv_by_symbol(db, sorted(model.training_symbols))
    window = window.assign(
        obv_training=[
            old[s].get(t, np.nan) if s in old else np.nan
            for s, t in zip(window["symbol"], window["ts"], strict=True)
        ]
    )
    return compare_window(window, names, bundle["scaler"])


def _code_order() -> list[str]:
    from swing_trade_ml.ml.features import FEATURE_COLUMNS

    return list(FEATURE_COLUMNS)


def parity_report(db: Session, models: dict[str, VerifiedModel]) -> dict:
    """All three groups. `ok` is true only if every model reproduces its scaler on the PRIMARY basis."""
    groups = {g: check_group(db, m) for g, m in models.items()}
    return {
        "ok": all(v[P.PRIMARY_BASIS]["ok"] and v["order_matches_code"] for v in groups.values()),
        "thresholds": {
            "mean_shift_sd_max": P.PARITY_MEAN_SHIFT_MAX,
            "sd_ratio_band": list(P.PARITY_SD_RATIO_BAND),
        },
        "groups": groups,
    }
