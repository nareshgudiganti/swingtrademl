"""M02's pure snapshot builder: the model's own features, plus a few plain
facts, from bars that end at the run's date."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.modules.m02_perception.snapshot import (
    ContextFrames,
    feature_set_version,
    snapshot_from,
)
from swing_trade_ml.ml.features import FEATURE_COLUMNS


def synthetic_bars(n: int = 400, seed: int = 7, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    ts = [datetime(2025, 1, 1, 18, 30, tzinfo=UTC) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(ts, utc=True),
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(50_000, 150_000, n).astype(float),
        }
    )


def synthetic_frames(n: int = 400) -> ContextFrames:
    index = synthetic_bars(n, seed=1, start=20_000.0)
    vix = synthetic_bars(n, seed=2, start=14.0)
    breadth = pd.DataFrame(
        {
            "ts": index["ts"],
            "breadth_pct_above_sma50": np.linspace(0.4, 0.6, n),
            "breadth_advance_pct": np.linspace(0.45, 0.55, n),
        }
    )
    return ContextFrames(
        index=index, sector=synthetic_bars(n, seed=3, start=30_000.0), vix=vix, breadth=breadth
    )


def test_a_snapshot_carries_every_model_feature():
    snap = snapshot_from("ABC", synthetic_bars(), synthetic_frames(), feature_set_version())
    assert snap is not None
    names = [name for name, _ in snap.features]
    assert names == list(FEATURE_COLUMNS)
    assert all(np.isfinite(value) for _, value in snap.features)


def test_plain_facts_come_from_the_same_bars():
    bars = synthetic_bars()
    snap = snapshot_from("ABC", bars, synthetic_frames(), feature_set_version())
    assert snap.close == pytest.approx(bars["close"].iloc[-1])
    assert snap.as_of == bars["ts"].iloc[-1].tz_convert("Asia/Kolkata").date().isoformat()
    tail = bars.tail(20)
    assert snap.adv_inr_20 == pytest.approx((tail["close"] * tail["volume"]).mean())
    assert snap.atr_14 > 0


def test_feature_set_version_is_short_and_stable():
    v = feature_set_version()
    assert len(v) == 12 and v == feature_set_version()
    assert snapshot_from("ABC", synthetic_bars(), synthetic_frames(), v).feature_set_version == v


def test_too_little_history_gives_no_snapshot():
    assert snapshot_from("ABC", synthetic_bars(120), synthetic_frames(), feature_set_version()) is None


def test_no_bars_gives_no_snapshot():
    assert snapshot_from("ABC", synthetic_bars().iloc[0:0], synthetic_frames(), feature_set_version()) is None
