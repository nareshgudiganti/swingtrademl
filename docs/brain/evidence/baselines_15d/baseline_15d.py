# ruff: noqa: E501
"""15-day baselines and lab-structure counts on LOCAL history, OUTSIDE the lab's development window.

Run (from backend/): python -I ../docs/brain/evidence/baselines_15d/baseline_15d.py   (local DB only; reads, never writes)

What it does, and the one rule it keeps:
  * Outcome figures (the +8% / -4% / 15-day rule with half out at +5% and Zerodha-checked costs, the label share,
    random-5 and strongest-riser benchmarks) are computed ONLY on decision days whose whole 15-day window ends on or
    before 2023-06-30, i.e. before the lab's development window (sl-protocol-v1, 2023-07-01 to 2026-08-15). Bars are cut
    at that date before any return is computed, and the code asserts it.
  * For the development window it counts STRUCTURE only (how many stocks qualify as the reference group each day).
    No forward return, outcome or label value is computed there.
  * No model is trained or scored. The held-back 129 stocks are never loaded.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "backend" / "src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import swing_trade_ml.services.risk  # noqa: E402, F401  (load order only)
from swing_trade_ml.brain import selection_lab as sl  # noqa: E402
from swing_trade_ml.brain import selection_lab_run as slr  # noqa: E402
from swing_trade_ml.brain.five_day import load_bars_with_volume  # noqa: E402
from swing_trade_ml.brain.horizon_grid import _index_after  # noqa: E402
from swing_trade_ml.brain.replay_scoring import strict_score  # noqa: E402
from swing_trade_ml.core.enums import ModelStatus  # noqa: E402
from swing_trade_ml.db.models.ml import MLModel  # noqa: E402

CUTOFF = date(2023, 6, 30)  # every price used for an outcome is on or before this day
DEV_START = slr.DEV_WINDOW[0]
DEV_END = slr.DEV_WINDOW[1]
DB_URL = "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml"  # local Docker, not a secret
DRAWS = 1000
SEED = 7
OUT = Path(__file__).parent


def ist_days(df):
    return list(df["day"])


def load(db):
    used, extra, _sha = slr.load_split(REPO)
    held = slr.load_held_back(REPO)
    model = (
        db.execute(
            select(MLModel)
            .where(MLModel.name == slr.MID_MODEL_NAME, MLModel.status == ModelStatus.ACTIVE)
            .order_by(MLModel.trained_at.desc())
        )
        .scalars()
        .first()
    )
    mid = sl.mid_group_from(model.training_symbols or [], held, used)
    sl.assert_no_held_back(held, used=used, mid=mid)
    bars = {s: d for s, d in load_bars_with_volume(db, sorted({*used, *mid}), DEV_END).items() if len(d)}
    return bars, list(used), mid, model.id


def structure(bars, group):
    """Reference-group size per decision day over the development window. No returns are looked at."""
    cal = sorted({d for s in group if s in bars for d in ist_days(bars[s]) if DEV_START <= d <= DEV_END})
    counts = [len(sl.reference_for_day(d, group, bars)) for d in cal]
    short = sum(1 for c in counts if c < sl.MIN_REFERENCE)
    return {
        "group_size": len(group),
        "stocks_with_any_bars": sum(1 for s in group if s in bars),
        "trading_days": len(cal),
        "days_with_fewer_than_10_reference_stocks": short,
        "share_of_days_without_labels": round(short / len(cal), 4) if cal else None,
        "reference_per_day_min": min(counts) if counts else None,
        "reference_per_day_median": statistics.median(counts) if counts else None,
        "reference_per_day_max": max(counts) if counts else None,
    }


def outcome_tables(bars, group):
    cut = {s: bars[s][bars[s]["day"] <= CUTOFF].reset_index(drop=True) for s in group if s in bars}
    assert all(df["day"].max() <= CUTOFF for df in cut.values())
    cal = sorted({d for df in cut.values() for d in ist_days(df)})
    rows = {}  # (sym, day) -> (status, net)
    for s, df in cut.items():
        days = ist_days(df)
        have = set(days)
        for d in cal:
            k = _index_after(days, d)
            if k is None or d not in have:
                continue
            o = strict_score(df.iloc[k : k + sl.HORIZON_BARS])
            if o.status != "open":
                rows[(s, d)] = (o.status, o.net_return)
    return cut, cal, rows


def run_group(bars, group):
    cut, cal, rows = outcome_tables(bars, group)
    by_day = defaultdict(list)
    ref_by_day = {}
    for d in cal:
        ref = sl.reference_for_day(d, group, cut)
        if len(ref) >= sl.MIN_REFERENCE:
            ref_by_day[d] = ref
    for (s, d), v in rows.items():
        if d in ref_by_day and s in ref_by_day[d]:
            by_day[d].append((s, v))
    days = sorted(by_day)
    first, last = days[0], days[-1]
    folds = sl.make_folds(first, last)
    regime_of = {}
    for f in folds:
        lab = sl.market_label(cut, f.start, f.end)
        for d in days:
            if f.start <= d <= f.end:
                regime_of[d] = lab

    def stats(items):
        n = len(items)
        if not n:
            return None
        nets = [v[1] for _s, v in items]
        st = [v[0] for _s, v in items]
        return {
            "stock_days": n,
            "hit_target": round(st.count("target") / n, 4),
            "hit_stop": round(st.count("stop") / n, 4),
            "timeout": round(st.count("timeout") / n, 4),
            "made_money": round(sum(1 for x in nets if x > 0) / n, 4),
            "avg_net_per_trade": round(float(np.mean(nets)), 5),
        }

    allitems = [it for d in days for it in by_day[d]]
    per_regime = defaultdict(list)
    for d in days:
        per_regime[regime_of.get(d, "unlabelled")].extend(by_day[d])
    regimes = {k: {"decision_days": sum(1 for d in days if regime_of.get(d, "unlabelled") == k), **stats(v)} for k, v in sorted(per_regime.items())}

    # label share (excess-top30), by construction ~30% of the reference group
    ones = tot = 0
    for d in days:
        rets = {}
        for s in ref_by_day[d]:
            r = sl.forward_return(cut[s], d)
            if r is not None:
                rets[s] = r
        got = sl.excess_labels(rets, ref_by_day[d])
        if got:
            labels, _c = got
            ones += sum(labels.values())
            tot += len(labels)

    # random-5 per day, one trade per 15th decision day (non-overlapping), 1000 draws
    rng = np.random.RandomState(SEED)
    pick_days = days[:: sl.HORIZON_BARS]
    means = []
    for _ in range(DRAWS):
        nets = []
        for d in pick_days:
            pool = by_day[d]
            idx = rng.choice(len(pool), size=min(5, len(pool)), replace=False)
            nets += [pool[i][1][1] for i in idx]
        means.append(float(np.mean(nets)))
    # strongest 20-day risers, top 5 each day
    mom = sl.momentum_scores(cut, days)
    top = []
    for d in days:
        pool = [(mom.get(s, {}).get(d), s) for s, _v in by_day[d]]
        pool = sorted([p for p in pool if p[0] is not None], reverse=True)[:5]
        net = {s: v[1] for s, v in by_day[d]}
        top += [net[s] for _m, s in pool]
    return {
        "group_size": len(group),
        "decision_days": len(days),
        "first_day": str(first),
        "last_day": str(last),
        "break_even_hit_rate_note": "about 33% for +8/-4 before half-out; costs are in the figures",
        "every_eligible_stock": stats(allitems),
        "by_market_type": regimes,
        "label_excess_top30": {"ones": ones, "labelled_stock_days": tot, "share": round(ones / tot, 4) if tot else None},
        "random_5_per_day_avg_net_per_trade": {
            "draws": DRAWS,
            "trade_days_per_draw": len(pick_days),
            "mean": round(float(np.mean(means)), 5),
            "p5": round(float(np.percentile(means, 5)), 5),
            "p95": round(float(np.percentile(means, 95)), 5),
        },
        "strongest_20d_risers_top5_avg_net_per_trade": round(float(np.mean(top)), 5) if top else None,
    }


def main():
    engine = create_engine(DB_URL)
    with Session(engine) as db:
        bars, large, mid, mid_model_id = load(db)
        out = {
            "rule": "+8% target / -4% stop / 15 trading days, half out at +5%, entry at next open, Zerodha-checked costs and 5 bps slippage per leg (replay_scoring.strict_score)",
            "outcome_window": f"decision days whose 15-day window ends on or before {CUTOFF} (before the lab window {DEV_START} to {DEV_END})",
            "mid_model_id": mid_model_id,
            "large_49": {"structure_in_dev_window": structure(bars, large), "outcomes_before_dev_window": run_group(bars, large)},
            "mid_14": {"symbols": mid, "structure_in_dev_window": structure(bars, mid), "outcomes_before_dev_window": run_group(bars, mid)},
        }
    (OUT / "baseline_15d.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
