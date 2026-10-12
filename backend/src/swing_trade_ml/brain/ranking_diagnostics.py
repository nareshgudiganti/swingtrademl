# backend/src/swing_trade_ml/brain/ranking_diagnostics.py
# ruff: noqa: E501 (long lines are report sentences)
"""Does the model's score rank stocks at all? (read-only diagnostics on DEVELOPMENT data)

Uses exactly the wf-protocol-v1 machinery: every fold trains a model that knows outcomes only up to
its cutoff, scores the stock-days after it, and each stock-day is scored with the strict rule
(next-day open, +8% / -4%, half out at +5%, 15 trading days, costs and slippage). Nothing is
retrained or tuned here. This is a diagnostic, not a pass or fail: it never touches the
confirmation sample and it registers only `wf_*` trial models locally, never activated.

Questions answered:
1. Do better scores come with better results? (quintiles inside each day, absolute score bands)
2. Does the score rank stocks on the same day? (daily rank correlation with a 15-day block interval)
3. Best 5 vs middle vs worst 5, and against random picks of 5 on the same days.
4. Does that hold in every fold and every market type?
5. Integrity: cutoffs, duplicates, ties, score coverage, survivorship, train vs test hit rate.
"""

from __future__ import annotations

import itertools
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET
from swing_trade_ml.brain.walk_forward import (
    BLOCK_DAYS,
    Fold,
    bootstrap_low,
    classify_regime,
    make_folds,
    outcomes_for,
)

QUINTILES = 5
BANDS = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0001)
MIN_BAND_CASES = 100  # a band with fewer finished ideas than this is shown but flagged thin
PROTECTED_START = date(2023, 7, 1)  # wf-protocol-v1 confirmation sample: pass/fail only, never diagnostics
PROTECTED_END = date(2025, 1, 31)
MIN_DAY_STOCKS = 10  # a day needs this many scored stocks to be ranked


def _frame(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["day", "symbol", "score", "ret", "hit", "fold"])


def with_quintiles(df: pd.DataFrame) -> pd.DataFrame:
    """Add `q` (1 = best fifth of that day's stocks by score, 5 = worst fifth). Ties share a rank
    by position, so a day where every score is equal is split arbitrarily; `tie_share` reports it."""
    out = df.copy()
    ok = out.groupby("day")["score"].transform("size") >= MIN_DAY_STOCKS
    out = out[ok].copy()
    rank = out.groupby("day")["score"].rank(method="first", ascending=False)
    n = out.groupby("day")["score"].transform("size")
    out["q"] = ((rank - 1) * QUINTILES // n).astype(int) + 1
    return out


def quintile_table(df: pd.DataFrame) -> list[dict]:
    q = with_quintiles(df)
    rows = []
    for k in range(1, QUINTILES + 1):
        g = q[q["q"] == k]
        rows.append(
            {
                "quintile": k,
                "ideas": len(g),
                "avg_net": float(g["ret"].mean()) if len(g) else None,
                "hit_rate": float(g["hit"].mean()) if len(g) else None,
            }
        )
    return rows


def band_table(df: pd.DataFrame, bands: Sequence[float] = BANDS) -> list[dict]:
    rows = []
    for lo, hi in itertools.pairwise(bands):
        g = df[(df["score"] >= lo) & (df["score"] < hi)]
        rows.append(
            {
                "band": f"{lo:.1f}-{min(hi, 1.0):.1f}",
                "ideas": len(g),
                "folds": int(g["fold"].nunique()) if len(g) else 0,
                "avg_net": float(g["ret"].mean()) if len(g) else None,
                "hit_rate": float(g["hit"].mean()) if len(g) else None,
                "thin": len(g) < MIN_BAND_CASES,
            }
        )
    return rows


def daily_rank_correlation(df: pd.DataFrame) -> pd.Series:
    """Per day: rank correlation between score and net result across that day's stocks.
    Above zero means that day's higher scores really did better. Indexed by day, in day order."""
    vals: dict[date, float] = {}
    for day, g in df.groupby("day"):
        if len(g) < MIN_DAY_STOCKS or g["score"].nunique() < 2 or g["ret"].nunique() < 2:
            continue
        r = g["score"].rank().corr(g["ret"].rank())
        if pd.notna(r):
            vals[day] = float(r)
    return pd.Series(vals).sort_index()


def topk_middle_bottom(df: pd.DataFrame, k: int = 5) -> dict:
    """Average result of each day's best k, middle k and worst k by score (day weighted)."""
    tops, mids, bots = [], [], []
    for _, g in df.groupby("day"):
        if len(g) < 3 * k:
            continue
        s = g.sort_values("score", ascending=False)["ret"].to_numpy()
        tops.append(s[:k].mean())
        m0 = (len(s) - k) // 2
        mids.append(s[m0 : m0 + k].mean())
        bots.append(s[-k:].mean())
    n = len(tops)
    return {
        "days": n,
        "best": sum(tops) / n if n else None,
        "middle": sum(mids) / n if n else None,
        "worst": sum(bots) / n if n else None,
    }


def random_percentile(df: pd.DataFrame, k: int = 5, draws: int = 500, seed: int = 7) -> dict:
    """Where does the model's best-k average sit among random picks of k from the same days?
    Share of random draws that did at least as well as the model (small = unlikely luck)."""
    by_day = {d: g for d, g in df.groupby("day") if len(g) >= 3 * k}
    if not by_day:
        return {"days": 0, "model": None, "random_mean": None, "share_random_at_least_as_good": None}
    model = sum(g.sort_values("score", ascending=False)["ret"].head(k).mean() for g in by_day.values()) / len(
        by_day
    )
    rng = random.Random(seed)
    arrs = {d: g["ret"].to_numpy() for d, g in by_day.items()}
    means = []
    for _ in range(draws):
        total = 0.0
        for a in arrs.values():
            total += sum(a[rng.randrange(len(a))] for _ in range(k)) / k
        means.append(total / len(arrs))
    return {
        "days": len(by_day),
        "model": model,
        "random_mean": sum(means) / len(means),
        "share_random_at_least_as_good": sum(m >= model for m in means) / draws,
    }


def per_fold(df: pd.DataFrame, regimes: dict[str, str]) -> list[dict]:
    out = []
    for fold, g in df.groupby("fold", sort=True):
        corr = daily_rank_correlation(g)
        q = quintile_table(g)
        out.append(
            {
                "fold": fold,
                "regime": regimes.get(fold, "unknown"),
                "ideas": len(g),
                "mean_rank_corr": float(corr.mean()) if len(corr) else None,
                "top_fifth": q[0]["avg_net"],
                "bottom_fifth": q[-1]["avg_net"],
                "spread": None
                if q[0]["avg_net"] is None or q[-1]["avg_net"] is None
                else q[0]["avg_net"] - q[-1]["avg_net"],
            }
        )
    return out


def by_regime(folds: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in folds:
        groups[f["regime"]].append(f)
    out = {}
    for label, fs in groups.items():
        corrs = [f["mean_rank_corr"] for f in fs if f["mean_rank_corr"] is not None]
        spreads = [f["spread"] for f in fs if f["spread"] is not None]
        out[label] = {
            "folds": len(fs),
            "mean_rank_corr": sum(corrs) / len(corrs) if corrs else None,
            "mean_spread": sum(spreads) / len(spreads) if spreads else None,
            "folds_with_positive_spread": sum(s > 0 for s in spreads),
        }
    return out


def integrity(
    df_all: pd.DataFrame, folds: Sequence[Fold], cutoffs_seen: dict[str, date | None], stocks: int
) -> dict:
    """Mechanical checks. `cutoffs_seen` is each fold's model's recorded as-of cutoff."""
    dup = int(df_all.duplicated(["symbol", "day"]).sum())
    ties = df_all.groupby("day")["score"].agg(lambda s: 1 - s.nunique() / len(s))
    bad_cutoff = [
        f.start.isoformat()
        for f in folds
        if cutoffs_seen.get(f.start.isoformat()) is None or cutoffs_seen[f.start.isoformat()] >= f.start
    ]
    return {
        "duplicate_stock_days": dup,
        "mean_tie_share_per_day": float(ties.mean()) if len(ties) else None,
        "folds_whose_model_cutoff_is_missing_or_not_before_the_fold": bad_cutoff,
        "stocks_in_universe": stocks,
        "survivorship": "universe is today's watchlist: stocks that were later dropped are absent",
        "train_vs_test_hit_rate": "see per-fold training positive rate in the run log; the test hit rate is in the quintile table",
    }


def run_diagnostics(
    db,
    *,
    first_start: date,
    last_end: date,
    test_days: int = 28,
    horizon: int = HORIZON_BARS,
    target: float = TARGET,
    stop: float = STOP,
    train_fn=None,
    score_fn=None,
) -> dict:
    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.walk_forward import _train
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.asof import asof_cutoff

    if train_fn is None:
        train_fn = _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn

    if first_start <= PROTECTED_END and last_end >= PROTECTED_START:
        raise ValueError(
            f"Requested window {first_start} to {last_end} overlaps the protected confirmation sample "
            f"{PROTECTED_START} to {PROTECTED_END} (wf-protocol-v1). Dates are not adjusted; pick a window "
            f"that starts after {PROTECTED_END}."
        )
    folds = make_folds(first_start, last_end, test_days)
    if not folds:
        raise ValueError("No test window fits between the start and end dates.")
    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {
        s: df
        for s, df in load_bars(
            db, [i.tradingsymbol for i in instruments], last_end + timedelta(days=60)
        ).items()
        if len(df)
    }
    rows: list[dict] = []
    regimes: dict[str, str] = {}
    cutoffs_seen: dict[str, date | None] = {}
    scored_cells = 0
    finished_cells = 0
    for fold in folds:
        days = sorted({d for df in bars.values() for d in df["day"] if fold.start <= d <= fold.end})
        if not days:
            continue
        key = fold.start.isoformat()
        regimes[key] = classify_regime(bars, fold.start, fold.end)["label"]
        outcomes = outcomes_for(bars, days, horizon, target, stop)
        model = train_fn(db, fold.cutoff, horizon, target, stop)
        cutoffs_seen[key] = asof_cutoff(model)
        for inst in instruments:
            for d, p in score_fn(db, inst, model, fold.cutoff).items():
                if not (fold.start <= d <= fold.end):
                    continue
                scored_cells += 1
                o = outcomes.get((inst.tradingsymbol, d))
                if o is None or o.net_return is None:
                    continue
                finished_cells += 1
                rows.append(
                    {
                        "day": d,
                        "symbol": inst.tradingsymbol,
                        "score": float(p),
                        "ret": float(o.net_return),
                        "hit": o.status == "target",
                        "fold": key,
                    }
                )
    df = _frame(rows)
    corr = daily_rank_correlation(df)
    folds_tbl = per_fold(df, regimes)
    return {
        "sample": {
            "first_start": first_start.isoformat(),
            "last_end": last_end.isoformat(),
            "folds": len(folds_tbl),
        },
        "rule": {"horizon": horizon, "target": target, "stop": stop},
        "coverage": {"scored_stock_days": scored_cells, "finished_stock_days": finished_cells},
        "every_stock": {
            "ideas": len(df),
            "avg_net": float(df["ret"].mean()),
            "hit_rate": float(df["hit"].mean()),
        },
        "quintiles": quintile_table(df),
        "bands": band_table(df),
        "rank_correlation": {
            "days": len(corr),
            "mean": float(corr.mean()) if len(corr) else None,
            "lower_bound_15_day_blocks": bootstrap_low(list(corr.values), block=BLOCK_DAYS)
            if len(corr)
            else None,
            "share_of_days_positive": float((corr > 0).mean()) if len(corr) else None,
        },
        "best_middle_worst_5": topk_middle_bottom(df),
        "vs_random_5": random_percentile(df),
        "folds": folds_tbl,
        "by_regime": by_regime(folds_tbl),
        "integrity": integrity(df, folds, cutoffs_seen, len(bars)),
    }


def _pct(x: float | None, d: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def plain_report(r: dict) -> str:
    s = r["sample"]
    rc = r["rank_correlation"]
    v = r["vs_random_5"]
    t = r["best_middle_worst_5"]
    lines = [
        "# Score ranking diagnostics (development data, not a pass or fail)",
        "",
        f"Test days {s['first_start']} to {s['last_end']}, {s['folds']} folds. Same rule and costs as "
        "wf-protocol-v1. Nothing was retrained or tuned. The confirmation sample is not used.",
        f"Every stock: {r['every_stock']['ideas']} finished stock-days, average {_pct(r['every_stock']['avg_net'])}, "
        f"hit {_pct(r['every_stock']['hit_rate'], 0)}.",
        "",
        "## 1. Do higher scores do better? (fifths of each day's stocks, 1 = best)",
        "| Fifth | Ideas | Average | Hit target |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {q['quintile']} | {q['ideas']} | {_pct(q['avg_net'])} | {_pct(q['hit_rate'], 0)} |"
        for q in r["quintiles"]
    ]
    lines += [
        "",
        "## 2. By absolute score",
        "| Score | Ideas | Folds | Average | Hit target | |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {b['band']} | {b['ideas']} | {b['folds']} | {_pct(b['avg_net'])} | {_pct(b['hit_rate'], 0)} | {'thin' if b['thin'] else ''} |"
        for b in r["bands"]
    ]
    lines += [
        "",
        "## 3. Does the score rank stocks on the same day?",
        f"Average daily rank correlation {rc['mean']:+.3f} over {rc['days']} days "
        f"(lower bound {rc['lower_bound_15_day_blocks']:+.3f} using 15-day blocks); "
        f"positive on {rc['share_of_days_positive']:.0%} of days. Zero means no ranking information."
        if rc["mean"] is not None and rc["lower_bound_15_day_blocks"] is not None
        else "Too few ranked days to say.",
        "",
        "## 4. Best 5, middle 5, worst 5 each day",
        f"Best {_pct(t['best'])} | middle {_pct(t['middle'])} | worst {_pct(t['worst'])} over {t['days']} days.",
        f"Random picks of 5 on the same days averaged {_pct(v['random_mean'])}; the model's best 5 averaged "
        f"{_pct(v['model'])}. Random did at least as well in "
        + (
            "n/a"
            if v["share_random_at_least_as_good"] is None
            else f"{v['share_random_at_least_as_good']:.0%}"
        )
        + " of draws.",
        "",
        "## 5. Each fold and market type",
        "| Fold start | Market | Ideas | Rank corr | Best fifth | Worst fifth | Spread |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in r["folds"]:
        corr = "n/a" if f["mean_rank_corr"] is None else f"{f['mean_rank_corr']:+.3f}"
        lines.append(
            f"| {f['fold']} | {f['regime']} | {f['ideas']} | {corr} | {_pct(f['top_fifth'])} | "
            f"{_pct(f['bottom_fifth'])} | {_pct(f['spread'])} |"
        )
    lines += [
        "",
        "| Market | Folds | Rank corr | Mean spread | Folds with positive spread |",
        "|---|---|---|---|---|",
    ]
    for label, g in sorted(r["by_regime"].items()):
        c = "n/a" if g["mean_rank_corr"] is None else f"{g['mean_rank_corr']:+.3f}"
        lines.append(
            f"| {label} | {g['folds']} | {c} | {_pct(g['mean_spread'])} | {g['folds_with_positive_spread']} |"
        )
    i = r["integrity"]
    lines += [
        "",
        "## 6. Integrity checks",
        f"- Duplicate stock-days: {i['duplicate_stock_days']}.",
        f"- Average share of tied scores per day: {_pct(i['mean_tie_share_per_day'])}.",
        f"- Folds whose model cutoff is missing or not before the fold: {i['folds_whose_model_cutoff_is_missing_or_not_before_the_fold'] or 'none'}.",
        f"- Scored stock-days {r['coverage']['scored_stock_days']}, with a finished outcome {r['coverage']['finished_stock_days']}; the rest are too recent to have finished.",
        f"- Universe: {i['stocks_in_universe']} stocks. Survivorship: {i['survivorship']}.",
    ]
    return "\n".join(lines) + "\n"


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    s = result["sample"]
    stem = f"ranking_diagnostics_{s['first_start']}_{s['last_end']}"
    md, js = directory / f"{stem}.md", directory / f"{stem}.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Score ranking diagnostics on development data (read-only)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--out", default="docs/brain/evidence/ranking_diag")
    a = p.parse_args(argv)
    with SessionLocal() as db:
        result = run_diagnostics(
            db, first_start=date.fromisoformat(a.start), last_end=date.fromisoformat(a.end)
        )
    md, js = write_report(result, Path(a.out))
    print(plain_report(result))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
