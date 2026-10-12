"""Ranking diagnostics: pure table builders and one run on fake data."""

from __future__ import annotations

import random
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from swing_trade_ml.brain import ranking_diagnostics as rd
from swing_trade_ml.brain import walk_forward as wf

D0 = date(2026, 1, 1)


def _rows(n_days=30, n_stocks=20, signal=1.0, seed=3):
    """Score i/n; result = signal * score + noise, so signal=0 is a score with no information."""
    rng = random.Random(seed)
    out = []
    for d in range(n_days):
        for i in range(n_stocks):
            score = i / n_stocks
            ret = signal * (score - 0.5) * 0.1 + rng.gauss(0, 0.02)
            out.append(
                {
                    "day": D0 + timedelta(days=d),
                    "symbol": f"S{i}",
                    "score": score,
                    "ret": ret,
                    "hit": ret > 0.05,
                    "fold": "f1",
                }
            )
    return pd.DataFrame(out)


def test_quintile_one_is_the_best_fifth_of_each_day():
    q = rd.with_quintiles(_rows(n_days=2, n_stocks=20))
    top = q[q["q"] == 1]
    assert set(top["score"]) == {0.95, 0.9, 0.85, 0.8}
    assert q.groupby(["day", "q"]).size().eq(4).all()


def test_an_informative_score_orders_the_quintiles_and_a_blind_one_does_not():
    good = rd.quintile_table(_rows(signal=1.0))
    assert good[0]["avg_net"] > good[-1]["avg_net"]
    blind = rd.quintile_table(_rows(signal=0.0))
    assert abs(blind[0]["avg_net"] - blind[-1]["avg_net"]) < 0.01


def test_rank_correlation_is_positive_for_signal_and_near_zero_without():
    assert rd.daily_rank_correlation(_rows(signal=1.0)).mean() > 0.3
    assert abs(rd.daily_rank_correlation(_rows(signal=0.0, n_days=60)).mean()) < 0.1


def test_days_with_too_few_stocks_or_identical_scores_are_not_ranked():
    df = _rows(n_days=3, n_stocks=5)
    assert rd.daily_rank_correlation(df).empty
    flat = _rows(n_days=3, n_stocks=20).assign(score=0.5)
    assert rd.daily_rank_correlation(flat).empty


def test_best_middle_worst_follow_the_score():
    t = rd.topk_middle_bottom(_rows(signal=1.0), k=5)
    assert t["best"] > t["middle"] > t["worst"]
    assert t["days"] == 30


def test_random_percentile_is_small_for_signal_and_large_for_none():
    assert (
        rd.random_percentile(_rows(signal=1.0, n_days=40), draws=200)["share_random_at_least_as_good"] < 0.1
    )
    assert (
        rd.random_percentile(_rows(signal=0.0, n_days=40), draws=200)["share_random_at_least_as_good"] > 0.05
    )


def test_thin_bands_are_flagged():
    bands = rd.band_table(_rows(n_days=2, n_stocks=20))
    assert all(b["thin"] for b in bands)


def test_integrity_flags_a_missing_or_late_cutoff_and_duplicates():
    df = _rows(n_days=2, n_stocks=20)
    folds = [wf.Fold(date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 9))]
    ok = rd.integrity(df, folds, {"2026-01-02": date(2026, 1, 1)}, 20)
    assert (
        ok["duplicate_stock_days"] == 0
        and ok["folds_whose_model_cutoff_is_missing_or_not_before_the_fold"] == []
    )
    bad = rd.integrity(pd.concat([df, df.head(1)]), folds, {"2026-01-02": None}, 20)
    assert bad["duplicate_stock_days"] == 1
    assert bad["folds_whose_model_cutoff_is_missing_or_not_before_the_fold"] == ["2026-01-02"]


class _FakeDb:
    def __init__(self, instruments):
        self._i = instruments

    def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: iter(self._i))


def test_full_run_on_fake_data_reads_the_signal_and_records_each_cutoff(monkeypatch):
    start = date(2026, 1, 1)
    n = 200
    syms = [f"S{i}" for i in range(12)]
    # stock i drifts by i basis points a day: a higher index really does better
    bars = {
        s: pd.DataFrame(
            [
                {"day": start + timedelta(days=k), "open": c, "high": c * 1.001, "low": c * 0.999, "close": c}
                for k in range(n)
                for c in [100.0 * (1 + 0.0005 * i) ** k]
            ]
        )
        for i, s in enumerate(syms)
    }
    monkeypatch.setattr("swing_trade_ml.brain.replay_score.load_bars", lambda db, symbols, upto: bars)
    instruments = [SimpleNamespace(tradingsymbol=s) for s in syms]
    rank = {s: i / 12 for i, s in enumerate(syms)}

    res = rd.run_diagnostics(
        _FakeDb(instruments),
        first_start=start + timedelta(days=40),
        last_end=start + timedelta(days=130),
        train_fn=lambda db, cutoff, h, t, s: SimpleNamespace(metrics={"asof_cutoff": cutoff.isoformat()}),
        score_fn=lambda db, inst, model, after: {
            start + timedelta(days=k): rank[inst.tradingsymbol] for k in range(n)
        },
    )
    assert res["rank_correlation"]["mean"] > 0
    assert res["quintiles"][0]["avg_net"] > res["quintiles"][-1]["avg_net"]
    assert res["integrity"]["folds_whose_model_cutoff_is_missing_or_not_before_the_fold"] == []
    assert "Score ranking diagnostics" in rd.plain_report(res)


def test_no_window_is_an_error():
    with pytest.raises(ValueError):
        rd.run_diagnostics(None, first_start=date(2026, 6, 1), last_end=date(2026, 6, 3))


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2023, 7, 1), date(2025, 1, 31)),  # the whole protected sample
        (date(2024, 3, 1), date(2024, 6, 1)),  # inside it
        (date(2025, 1, 31), date(2025, 6, 1)),  # touches the last protected day
        (date(2022, 1, 1), date(2023, 7, 1)),  # touches the first protected day
    ],
)
def test_protected_confirmation_dates_are_rejected_not_adjusted(start, end):
    with pytest.raises(ValueError, match="protected confirmation"):
        rd.run_diagnostics(None, first_start=start, last_end=end)


@pytest.mark.parametrize(
    "start,end",
    [(date(2025, 2, 1), date(2025, 2, 2)), (date(2022, 1, 1), date(2022, 1, 3))],
)
def test_development_dates_pass_the_guard(start, end):
    # passes the guard; fails later only because this short window holds no whole fold
    with pytest.raises(ValueError, match="No test window"):
        rd.run_diagnostics(None, first_start=start, last_end=end)
