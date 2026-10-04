"""M11 sector brain: ranking sectors against NIFTY, rotation, and the module."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from brain_fakes import FakeReader, registry, request
from swing_trade_ml.brain.module import REGISTRY, Mode, Step
from swing_trade_ml.brain.modules.m11_sector.module import SectorBrain
from swing_trade_ml.brain.modules.m11_sector.ranking import (
    TILT,
    rank_sectors,
    relative_strength,
    rotation,
    sector_line,
)
from swing_trade_ml.brain.runner import execute


def _series(daily: float, n: int = 120, late: float | None = None, late_days: int = 20) -> pd.Series:
    """A price path growing `daily` a day, switching to `late` for the last `late_days`."""
    rates = np.full(n, daily)
    if late is not None:
        rates[-late_days:] = late
    return pd.Series(100 * np.cumprod(1 + rates))


FLAT = _series(0.0)


def test_relative_strength_is_the_sector_return_minus_nifty():
    assert relative_strength(_series(0.01), FLAT, 20) == pytest.approx(1.01**20 - 1, rel=1e-6)
    assert relative_strength(_series(0.01, n=15), FLAT, 20) is None


@pytest.mark.parametrize(
    ("rs20", "rs60", "label"),
    [
        (0.02, 0.05, "leading"),
        (0.02, -0.05, "improving"),
        (-0.02, 0.05, "weakening"),
        (-0.02, -0.05, "lagging"),
    ],
)
def test_rotation_comes_from_the_20_and_60_day_signs(rs20, rs60, label):
    assert rotation(rs20, rs60) == label


def test_stronger_sectors_rank_first_with_their_rotation():
    closes = {
        "NIFTY IT": _series(0.004),  # up over both windows
        "NIFTY BANK": _series(-0.004, late=0.01, late_days=15),  # weak for months, strong lately
        "NIFTY METAL": _series(-0.004),  # down over both
    }
    ranked = rank_sectors(closes, FLAT)
    assert [s.sector for s in ranked] == ["NIFTY BANK", "NIFTY IT", "NIFTY METAL"]
    assert [s.rank for s in ranked] == [1, 2, 3] and {s.of_total for s in ranked} == {3}
    assert [s.rotation for s in ranked] == ["improving", "leading", "lagging"]
    assert ranked[0].strength_20d > 0


def test_short_history_sectors_are_left_out():
    ranked = rank_sectors({"NIFTY IT": _series(0.004), "NIFTY NEW": _series(0.01, n=40)}, FLAT)
    assert [s.sector for s in ranked] == ["NIFTY IT"] and ranked[0].of_total == 1


def test_each_index_is_ranked_once():
    ranked = rank_sectors({"NIFTY COMMODITIES": _series(0.001), "NIFTY IT": _series(0.002)}, FLAT)
    assert len(ranked) == 2


def test_no_nifty_history_ranks_nothing():
    assert rank_sectors({"NIFTY IT": _series(0.004)}, pd.Series(dtype=float)) == []


def test_tilts_are_small_and_follow_rotation():
    assert TILT == {"leading": 0.1, "improving": 0.05, "weakening": -0.05, "lagging": -0.1}


def test_the_card_line_uses_plain_names():
    (it,) = rank_sectors({"NIFTY IT": _series(0.004)}, FLAT)
    assert sector_line(it) == "Sector: IT, ranked 1 of 1, leading (stronger than NIFTY over 1 and 3 months)."


# --- the module -----------------------------------------------------------------------


class SectorReader(FakeReader):
    def __init__(self, sectors=None, **kw):
        super().__init__(**kw)
        self._sectors = (
            sectors
            if sectors is not None
            else {
                "NIFTY IT": _series(0.004),
                "NIFTY BANK": _series(-0.004),
            }
        )

    def sector_closes(self):
        return self._sectors

    def index_closes(self):
        return FLAT


def _run(reader, universe=("INFY", "HDFCBANK", "BHARTIARTL"), kind="nightly"):
    return execute(request(kind=kind, universe=universe), reader, registry(SectorBrain), {"M11": Mode.ON})


def test_m11_is_a_state_plugin_that_starts_on():
    import swing_trade_ml.brain.modules  # noqa: F401

    assert REGISTRY.get("M11") is SectorBrain
    m = SectorBrain.manifest
    assert m.step is Step.STATE and m.kind == "plugin" and m.default_mode is Mode.ON


def test_the_run_holds_the_sector_table_and_a_tilt_per_mapped_stock():
    ctx = _run(SectorReader())
    assert [ctx.sectors[k].rank for k in ("NIFTY IT", "NIFTY BANK")] == [1, 2]
    tilts = {o.symbol: o for o in ctx.opinions if o.source == "sector"}
    assert tilts["INFY"].stance == 0.1 and tilts["HDFCBANK"].stance == -0.1
    assert tilts["INFY"].reasons[0].startswith("Sector: IT, ranked 1 of 2, leading")


def test_unmapped_stocks_get_no_tilt():
    ctx = _run(SectorReader())
    assert "BHARTIARTL" not in {o.symbol for o in ctx.opinions}


def test_a_stock_whose_sector_could_not_be_ranked_gets_no_tilt():
    ctx = _run(SectorReader(sectors={"NIFTY IT": _series(0.004)}))
    assert {o.symbol for o in ctx.opinions if o.source == "sector"} == {"INFY"}


def test_no_sector_data_means_no_contribution():
    ctx = _run(SectorReader(sectors={}))
    assert not ctx.sectors and not ctx.opinions


def test_intraday_runs_skip_sectors():
    ctx = _run(SectorReader(), kind="intraday")
    assert not ctx.sectors
