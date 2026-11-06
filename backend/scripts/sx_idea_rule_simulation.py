"""SX5/SX10: how often does the ideas-per-fold rule bind? A NEUTRAL simulation (no arm result is used).

Question (owner, 2026-11-04): the eligible-fold rule is ">= 10 test days and >= 20 ideas" and R3 needs ">= 12 eligible
folds, >= 100 ideas in total, >= 2h days". Does the rule, by itself and before any result, make INCONCLUSIVE likely?

Method. Real development calendar (days per fold from the signed fold-coverage CSVs, folds 4-33 = the 30 counted folds),
real eligible-stock count per day (test_rows / test_days of the same CSV, 45-47). NEUTRAL pick proxy: each day a score
for every eligible stock follows an AR(1) in time with persistence phi (marginally N(0,1)); the 'top 5' are the five
highest scores. No model, no return, no outcome is used: only which stock names are picked. phi = 0 / 0.5 / 0.9 are the
S-9 assumed persistence values (top-5 repeat share about 10% / 32% / 67% day to day).
The real function ``ml.sx_verdict.count_ideas`` counts the ideas (td-protocol-v1 rule 2 for ``no_repeat``).

No database, no price, no holdout-period outcome. Pure numpy. Format only this file.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[1]
EVID = REPO / "docs" / "brain" / "evidence" / "sector_prep"
sys.path.insert(0, str(REPO / "backend" / "src"))
from swing_trade_ml.ml import sx_verdict as sv  # noqa: E402

PERSISTENCE = (0.0, 0.5, 0.9)
MASTER_SEED = 20261104
RULE_VARIANTS = ("no_repeat", "raw_per_day", "days_only")
THRESHOLDS = (16, 20, 36)  # 16 = R1-share floor, 20 = current default, 36 = P(win at MDE) >= 0.65 (see the note)


def load_calendar(h: int, burn_in: int = 4) -> list[tuple[int, int]]:
    """[(test_days, eligible_stocks_per_day)] for the counted folds (0-based index >= burn_in), development only."""
    out = []
    with open(EVID / f"sx{h}_fold_coverage_v3.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["fold"] == "holdout":
                continue
            days, rows = int(row["test_days"]), int(row["test_rows"])
            out.append((days, max(1, round(rows / days))))
    return out[burn_in:]


def day_stock_counts(days: int, total_rows: int) -> list[int]:
    base, extra = divmod(total_rows, days)
    return [base + (1 if i < extra else 0) for i in range(days)]


def load_calendar_rows(h: int, burn_in: int = 4) -> list[list[int]]:
    """Per counted fold, the eligible-stock count of each day (rows spread evenly over the days)."""
    out = []
    with open(EVID / f"sx{h}_fold_coverage_v3.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["fold"] == "holdout":
                continue
            out.append(day_stock_counts(int(row["test_days"]), int(row["test_rows"])))
    return out[burn_in:]


def simulate_top_lists(n_days: int, n_stocks: int, phi: float, top_k: int, rng: np.random.Generator) -> np.ndarray:
    """(n_days, top_k) array of stock indices: the top-k of an AR(1)(phi) score. Names only; no returns."""
    z = np.empty((n_days, n_stocks))
    z[0] = rng.standard_normal(n_stocks)
    s = float(np.sqrt(1.0 - phi * phi))
    eps = rng.standard_normal((n_days, n_stocks))
    for t in range(1, n_days):
        z[t] = phi * z[t - 1] + s * eps[t]
    return np.argpartition(-z, top_k - 1, axis=1)[:, :top_k]


def fold_records(calendar_rows: list[list[int]], tops: np.ndarray, top_k: int) -> list[list[dict]]:
    """Cut the continuous top-list series into the folds as harness-style daily records (date, n_stocks, top_symbols)."""
    out, t = [], 0
    for fold_i, counts in enumerate(calendar_rows):
        daily = []
        for j, n in enumerate(counts):
            names = [f"S{int(x)}" for x in tops[t][:top_k]]
            daily.append({"date": f"f{fold_i:02d}d{j:02d}", "n_stocks": n, "top_symbols": names})
            t += 1
        out.append(daily)
    return out


def evaluate(
    h: int,
    phi: float,
    reps: int,
    seed: int,
    *,
    min_stocks: int = 10,
    top_k: int = 5,
    min_fold_days: int = 10,
    min_fold_picks: int = 20,
    min_eligible_folds: int = 12,
    min_picks: int = 100,
) -> dict:
    cal = load_calendar_rows(h)
    n_days = sum(len(c) for c in cal)
    n_stocks = max(max(c) for c in cal)
    rng = np.random.default_rng(np.random.SeedSequence([seed, h, int(round(phi * 100))]))
    fold_days = np.array([len(c) for c in cal])
    ideas_all = np.zeros((reps, len(cal)), dtype=int)
    raw_all = np.zeros((reps, len(cal)), dtype=int)
    for r in range(reps):
        tops = simulate_top_lists(n_days, n_stocks, phi, top_k, rng)
        recs = fold_records(cal, tops, top_k)
        for k, daily in enumerate(recs):
            ideas_all[r, k] = sv.count_ideas(daily, h, min_stocks, top_k, "no_repeat")
            raw_all[r, k] = sv.count_ideas(daily, h, min_stocks, top_k, "raw_per_day")
    days_ok = fold_days >= min_fold_days
    out: dict = {
        "h": h,
        "phi": phi,
        "reps": reps,
        "seed": seed,
        "n_counted_folds": len(cal),
        "fold_days": fold_days.tolist(),
        "mean_ideas_per_fold_no_repeat": [float(x) for x in ideas_all.mean(axis=0)],
        "new_idea_share_no_repeat": float(ideas_all.sum() / max(1, raw_all.sum())),
        "variants": {},
        "thresholds_no_repeat": {},
    }
    nominal19 = [k for k, d in enumerate(fold_days) if d == 19]
    for variant in RULE_VARIANTS:
        if variant == "no_repeat":
            ok = ideas_all >= min_fold_picks
            picks = ideas_all
        elif variant == "raw_per_day":
            ok = raw_all >= min_fold_picks
            picks = raw_all
        else:
            ok = np.ones_like(ideas_all, dtype=bool)
            picks = ideas_all
        elig = ok & days_ok[None, :]
        n_elig = elig.sum(axis=1)
        picks_e = (picks * elig).sum(axis=1)
        r3_fail = (n_elig < min_eligible_folds) | ((picks_e < min_picks) if variant != "days_only" else False)
        out["variants"][variant] = {
            "p_19day_fold_passes_ideas": float(ok[:, nominal19].mean()) if nominal19 else None,
            "p_last_fold_13_days_passes": float((ok[:, -1] & days_ok[-1]).mean()),
            "mean_eligible_folds": float(n_elig.mean()),
            "min_eligible_folds_seen": int(n_elig.min()),
            "p_fewer_than_12_eligible_folds": float((n_elig < min_eligible_folds).mean()),
            "p_R3_data_fail": float(np.mean(r3_fail)),
        }
    for thr in THRESHOLDS:
        ok = (ideas_all >= thr) & days_ok[None, :]
        n_elig = ok.sum(axis=1)
        out["thresholds_no_repeat"][str(thr)] = {
            "p_19day_fold_passes": float((ideas_all[:, nominal19] >= thr).mean()) if nominal19 else None,
            "mean_eligible_folds": float(n_elig.mean()),
            "p_fewer_than_12_eligible_folds": float((n_elig < min_eligible_folds).mean()),
        }
    # distribution of ideas in a 19-day fold
    if nominal19:
        x = ideas_all[:, nominal19].ravel()
        out["ideas_19day_fold"] = {"p05": float(np.percentile(x, 5)), "median": float(np.median(x)), "p95": float(np.percentile(x, 95))}
    return out


# ------------------------------------------------------------------------------------------------ derivation helpers
def phi_inv(p: float) -> float:
    from statistics import NormalDist

    return NormalDist().inv_cdf(p)


def min_independent_ideas(sigma_idea_pp: float, delta_pp: float, p_win: float) -> float:
    """Independent ideas N so that a fold mean has P(mean > 0 | true edge delta) = p_win:
    Phi(delta * sqrt(N) / sigma) = p_win  =>  N = (Phi^-1(p_win) * sigma / delta)^2.
    sigma = standard deviation of ONE idea's paired difference (pp); delta = true paired edge (pp per trade)."""
    if sigma_idea_pp <= 0 or delta_pp <= 0 or not 0.5 < p_win < 1:
        raise ValueError("sigma and delta must be positive and 0.5 < p_win < 1")
    return (phi_inv(p_win) * sigma_idea_pp / delta_pp) ** 2


def p_win_at(n_ideas: float, sigma_idea_pp: float, delta_pp: float) -> float:
    from statistics import NormalDist

    return NormalDist().cdf(delta_pp * (n_ideas**0.5) / sigma_idea_pp)


def net_minus_gross_pp(delta_share: float, round_trip_pct: float) -> float:
    """Gross paired difference minus net paired difference, in pp per trade-slot: (s_C - s_A) x round trip."""
    return delta_share * round_trip_pct


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=EVID / "sx_idea_rule_sim_v1.json")
    args = ap.parse_args(argv)
    res = {
        "meta": {
            "master_seed": MASTER_SEED,
            "reps": args.reps,
            "note": "neutral pick proxy (AR(1) scores, names only); no arm, no return, no holdout outcome used",
        },
        "cells": [],
    }
    for h in (5, 10):
        for phi in PERSISTENCE:
            res["cells"].append(evaluate(h, phi, args.reps, MASTER_SEED))
    args.out.write_text(json.dumps(res, indent=1))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
