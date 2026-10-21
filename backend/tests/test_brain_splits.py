# backend/tests/test_brain_splits.py
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd

from swing_trade_ml.brain import splits
from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D = date(2026, 1, 5)


def _o(status, net):
    return StrictOutcome(status, net, None if net is None else 5, False, False, None if net is None else D)


WIN, LOSS, OPEN = _o("target", 0.06), _o("stop", -0.045), _o("open", None)


def test_split_counts_and_averages_only_finished_ideas():
    out = splits.split(
        [("rising", "A", WIN), ("rising", "B", LOSS), ("rising", "A", OPEN), ("falling", "C", LOSS)]
    )
    assert list(out) == ["falling", "rising"]
    r = out["rising"]
    assert (r["ideas"], r["finished"], r["stocks"]) == (3, 2, 2)
    assert r["hit_rate"] == 0.5 and abs(r["avg_net"] - 0.0075) < 1e-12


def test_counts_only_never_carries_a_result():
    out = splits.split([("rising", "A", WIN), ("rising", "B", LOSS)], results=False)
    assert out["rising"] == {"ideas": 2, "stocks": 2}


def test_market_types_list_every_window_type_even_without_ideas():
    out = splits.by_market_type([("rising", "A", WIN)], ["rising", "rising", "falling"])
    assert out["rising"]["windows"] == 2
    assert out["falling"] == {
        "ideas": 0,
        "stocks": 0,
        "finished": 0,
        "hit_rate": None,
        "avg_net": None,
        "windows": 1,
    }


def test_sector_rows_use_the_sector_map_and_unmapped_gets_its_own_row():
    out = splits.by_sector(
        [("A", WIN), ("B", LOSS), ("C", WIN)], sector=lambda s: {"A": "BANK", "B": "BANK"}.get(s, "unmapped")
    )
    assert out["BANK"]["finished"] == 2 and out["unmapped"]["stocks"] == 1
    assert splits.sector_of("NOT_A_REAL_STOCK_XYZ") == splits.UNMAPPED


def test_weak_market_type_needs_enough_windows_and_a_bad_average():
    types = {
        "falling": {"windows": 3, "avg_net": -0.02},
        "rising": {"windows": 5, "avg_net": 0.01},
        "sideways": {"windows": 2, "avg_net": -0.05},  # too few windows to judge
    }
    assert splits.weak_market_types(types) == ["falling"]


class _FakeDb:
    def __init__(self, instruments):
        self._instruments = instruments

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: iter(self._instruments))


def _bars(closes):
    return pd.DataFrame(
        [
            {"day": D + timedelta(days=i), "open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
            for i, c in enumerate(closes)
        ]
    )


def test_walk_forward_reports_both_splits_for_model_and_every_stock(monkeypatch):
    bars = {
        "UP": _bars([100.0 + 0.8 * i for i in range(200)]),
        "DOWN": _bars([300.0 - 0.8 * i for i in range(200)]),
    }
    monkeypatch.setattr(wf, "load_bars", lambda db, symbols, upto: bars)
    instruments = [SimpleNamespace(tradingsymbol="UP"), SimpleNamespace(tradingsymbol="DOWN")]
    res = wf.run_walk_forward(
        _FakeDb(instruments),
        first_start=D + timedelta(days=40),
        last_end=D + timedelta(days=130),
        top_k=1,
        train_fn=lambda *a: SimpleNamespace(roc_auc=None),
        score_fn=lambda db, inst, model, after: {
            D + timedelta(days=i): 1.0 if inst.tradingsymbol == "UP" else 0.0 for i in range(200)
        },
    )
    sp = res["splits"]
    total_windows = sum(r["windows"] for r in sp["model"]["by_market_type"].values())
    assert total_windows == len(res["folds"])
    assert sum(r["finished"] for r in sp["model"]["by_sector"].values()) == res["pooled"]["model"]["ideas"]
    assert (
        sum(r["finished"] for r in sp["every_stock"]["by_sector"].values())
        == res["pooled"]["every_stock"]["ideas"]
    )
    text = wf.plain_report(res)
    assert "## Result by market type" in text and "## Result by sector" in text
