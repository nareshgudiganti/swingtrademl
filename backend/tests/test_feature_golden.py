"""Golden-output tests (#328 slice 1): every FEATURE_COLUMNS formula is pinned on a fixed candle fixture.

If a same-name formula changes, a value here moves and CI fails. Regenerate the stored values only with the
owner's approval of the formula change (see fixtures/feature_golden_values.json, made by
ml.model_card.golden_values). The fixture uses plain arithmetic, no random generator.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.brain.lanes.h05_features import old_obv_slope
from swing_trade_ml.ml import model_card as mc
from swing_trade_ml.ml.features import FEATURE_COLUMNS, on_balance_volume

GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "feature_golden_values.json").read_text())


def test_golden_file_covers_exactly_the_feature_list():
    for key, row in GOLDEN.items():
        if key == "down_regimes":
            continue
        assert list(row) == FEATURE_COLUMNS


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return mc.golden_fixture_frame()


@pytest.mark.parametrize("position", [-1, -60])
@pytest.mark.parametrize("name", FEATURE_COLUMNS)
def test_feature_matches_golden(frame, name, position):
    expected = GOLDEN[f"row_{position}"][name]
    actual = float(frame.iloc[position][name])
    assert expected is not None, f"{name} has no golden value"
    assert actual == pytest.approx(expected, rel=1e-6, abs=1e-9), f"{name} formula output changed"


def test_golden_hash_is_the_hash_of_the_stored_values():
    import hashlib

    rounded = {k: None if v is None else round(v, 6) for k, v in GOLDEN["row_-1"].items()}
    assert mc.golden_output_hash() == hashlib.sha256(json.dumps(rounded, sort_keys=True).encode()).hexdigest()


def test_two_obv_slope_definitions_differ_on_the_fixture(frame):
    """Records the known mismatch (#272): models 2/16/17 were trained with the old formula (OBV-level
    denominator, brain/lanes/h05_features.old_obv_slope); today's ml/features.py divides by typical volume.
    This test documents that they differ; it does not decide which one is right."""
    stock = mc.synthetic_candles(0.0)
    old = old_obv_slope(stock["close"].astype(float), stock["volume"].astype(float))
    current = frame["obv_slope"]
    both = pd.concat([old, current], axis=1, keys=["old", "current"]).dropna()
    assert len(both) > 100
    assert not np.allclose(both["old"], both["current"], rtol=1e-6)
    # and the shared numerator (10-day OBV change) is the same, so only the denominator differs
    obv = on_balance_volume(stock["close"], stock["volume"])
    assert (old * obv.rolling(20).mean().abs()).dropna().iloc[-1] == pytest.approx(
        obv.diff(10).iloc[-1]
    )
    assert float(current.iloc[-1]) == pytest.approx(GOLDEN["row_-1"]["obv_slope"], rel=1e-6)
    assert float(old.iloc[-1]) != pytest.approx(float(current.iloc[-1]), rel=1e-3)


def test_regime_features_hit_both_sides_of_their_threshold():
    """The main fixture is an uptrend (regimes = 1). A falling index/sector must give -1, so a change to
    the sma50/sma200 sign rule fails here."""
    up = mc.golden_fixture_frame().iloc[-1]
    down = mc.golden_fixture_frame(index_slope=-0.25).iloc[-1]
    assert up["nifty_trend_regime"] == 1.0 and up["sector_trend_regime"] == 1.0
    assert down["nifty_trend_regime"] == -1.0 and down["sector_trend_regime"] == -1.0
    for name in ("nifty_trend_regime", "sector_trend_regime"):
        assert GOLDEN["down_regimes"][name] == down[name]
    # flat index (zero slope, no wiggle) -> exactly 0
    flat = mc.golden_fixture_frame(index_slope=0.0, index_wiggle=False).iloc[-1]
    assert flat["nifty_trend_regime"] == 0.0 and flat["sector_trend_regime"] == 0.0
