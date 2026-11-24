# ruff: noqa: E501
"""Model card: the record of exactly how a saved model was made (issue #328, slice 1).

Written at training time into `ml_models.metrics["card"]` and into the artifact bundle under `card`.
Anything that cannot be determined is recorded as None, never guessed. Pure helpers; no database access.

The bundle's copy is written before the file exists, so its `artifact_sha256` is None (a file cannot hold
its own hash); the metrics copy carries the real hash.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from swing_trade_ml.core.config import settings
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features

CARD_VERSION = 1
_FEATURES_FILE = Path(__file__).with_name("features.py")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def synthetic_candles(seed_shift: float = 0.0, n: int = 400) -> pd.DataFrame:
    """Fixed OHLCV candles from plain arithmetic (no random generator, so identical on every machine and library)."""
    i = np.arange(n, dtype=np.float64)
    close = 100.0 + 0.08 * i + 6.0 * np.sin(i / 7.0 + seed_shift) + 2.5 * np.sin(i / 2.3 + 2 * seed_shift)
    open_ = close * (1 + 0.004 * np.sin(i * 1.7 + seed_shift))
    high = np.maximum(open_, close) * (1 + 0.006 + 0.004 * np.abs(np.sin(i * 0.9)))
    low = np.minimum(open_, close) * (1 - 0.006 - 0.004 * np.abs(np.cos(i * 1.3)))
    volume = np.round(500_000 + 200_000 * np.sin(i / 5.0 + seed_shift) + 50_000 * np.cos(i * 2.1))
    return pd.DataFrame(
        {
            "ts": pd.bdate_range("2024-01-01", periods=n, tz="UTC"),
            "open": open_, "high": high, "low": low, "close": close, "volume": volume,
        }
    )


def golden_fixture_frame() -> pd.DataFrame:
    """`build_features` run on the fixed fixture: stock, index, sector, VIX and breadth are all synthetic."""
    stock = synthetic_candles(0.0)
    index_df, sector_df = synthetic_candles(1.1), synthetic_candles(2.2)
    vix = synthetic_candles(3.3)[["ts", "close"]].assign(close=lambda d: 12 + d["close"] / 20)
    ts = stock["ts"]
    j = np.arange(len(ts), dtype=np.float64)
    breadth = pd.DataFrame(
        {
            "ts": ts,
            "breadth_pct_above_sma50": 0.5 + 0.3 * np.sin(j / 11.0),
            "breadth_advance_pct": 0.5 + 0.25 * np.cos(j / 6.0),
        }
    )
    return build_features(stock, index_df, sector_df, vix, breadth)


def golden_values(position: int = -1) -> dict[str, float | None]:
    """One row of the fixture (default the last), for every FEATURE_COLUMNS name; NaN as None; 10 significant digits."""
    row = golden_fixture_frame().iloc[position]
    out: dict[str, float | None] = {}
    for name in FEATURE_COLUMNS:
        v = float(row[name])
        out[name] = None if np.isnan(v) else float(f"{v:.10g}")
    return out


def golden_output_hash() -> str:
    """Hash of the feature builder's output on the fixture, at 6 decimals so float noise cannot change it."""
    rounded = {k: None if v is None else round(v, 6) for k, v in golden_values().items()}
    return _sha256_text(json.dumps(rounded, sort_keys=True))


def feature_fingerprint(names: list[str] | None = None) -> dict[str, str]:
    names = list(FEATURE_COLUMNS if names is None else names)
    names_sha = _sha256_text(json.dumps(names))
    golden = golden_output_hash()
    return {
        "names_sha256": names_sha,
        "golden_output_sha256": golden,
        "fingerprint_sha256": _sha256_text(names_sha + golden),
    }


def feature_code_sha256() -> str | None:
    try:
        return hashlib.sha256(_FEATURES_FILE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def git_state() -> dict[str, Any]:
    """HEAD sha and a dirty flag, or None for each when git is unavailable."""
    cwd = Path(__file__).resolve().parent

    def run(*args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=True
            )
            return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    sha = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {"sha": sha or None, "dirty": None if status is None else bool(status)}


def library_versions() -> dict[str, str | None]:
    def ver(pkg: str) -> str | None:
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return None

    return {
        "python": platform.python_version(),
        "lightgbm": ver("lightgbm"),
        "scikit-learn": ver("scikit-learn"),
        "numpy": ver("numpy"),
        "pandas": ver("pandas"),
    }


def _iso(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def matrix_sha256(frame: pd.DataFrame, columns: list[str]) -> str:
    """sha256 over the training matrix (inputs plus target), row order included."""
    hashed = pd.util.hash_pandas_object(frame[[*columns, "target"]].reset_index(drop=True), index=False)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()


def build_card(
    *,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    dataset: pd.DataFrame,
    feature_names: list[str],
    algorithm: str,
    train_args: dict[str, Any],
    horizon_days: int,
    target_return: float,
    stop_return: float,
    label_kind: str,
) -> dict[str, Any]:
    """The card before the file exists (artifact_sha256 is filled in after saving). JSON-serialisable."""
    symbols = sorted(dataset["symbol"].unique().tolist()) if "symbol" in dataset.columns else None
    fp = feature_fingerprint(feature_names)
    return {
        "card_version": CARD_VERSION,
        "feature_names": list(feature_names),
        "feature_fingerprint": fp,
        "input_formula_version": f"features-{fp['fingerprint_sha256'][:12]}",
        "feature_code_sha256": feature_code_sha256(),
        "git": git_state(),
        "training": {
            "entry_point": "swing_trade_ml.ml.train.train_model",
            "algorithm": algorithm,
            "args": train_args,
            "seed": settings.ML_RANDOM_SEED,
        },
        "libraries": library_versions(),
        "data_window": {
            "train_start": _iso(train_df["ts"].min()) if not train_df.empty else None,
            "train_end": _iso(train_df["ts"].max()) if not train_df.empty else None,
            "test_start": _iso(test_df["ts"].min()) if not test_df.empty else None,
            "test_end": _iso(test_df["ts"].max()) if not test_df.empty else None,
        },
        "universe": {
            "symbols": symbols,
            "symbols_sha256": None if symbols is None else _sha256_text("\n".join(symbols)),
        },
        "rows": {"dataset": len(dataset), "train": len(train_df), "test": len(test_df)},
        "training_matrix_sha256": matrix_sha256(train_df, list(feature_names)),
        "label": {
            "horizon_days": horizon_days,
            "target_return": target_return,
            "stop_return": stop_return,
            "kind": label_kind,
        },
        "artifact_sha256": None,
    }
