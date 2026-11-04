"""SX5/SX10: MDE_H justification, outcome-word probabilities, E* (economic floor) and SX10 duration (research; no model is fitted).

What this does (all synthetic except the measured inputs; no model is fitted, no holdout-period outcome is computed)
-------------------------------------------------------------------------------------------------------------------
1. ``simulate_outcomes``: re-runs the S-9 decision procedure of ``sx_power_analysis.py`` on the CORRECT counted series
   (folds 4-33 = 30 folds = 565 days; the earlier headline used all 34 folds = 642 days, which is not the series the
   verdict counts) and, per true edge delta on a grid, tallies the verdict code's outcome words:
   R2 (index-based one-sided lower bound of a moving-block bootstrap at 2.5% or 5%), R1 (>= 60% of counted folds with a
   positive mean paired difference), R4 (dev mean > 0 and holdout mean > 0), the 5% upper bound, and from them
   PASS / FAIL / INCONCLUSIVE for several MDE_H values (the order of ``ml/sx_verdict.compute_verdict``):
       R2 and R1  -> PASS if R4 else INCONCLUSIVE (the simulation always has a completed holdout);
       not R2 and upper95 < MDE_H -> FAIL;  otherwise INCONCLUSIVE.
2. Duration cells: the same procedure for a longer counted series (T days, no burn-in, no holdout: a forward design) to
   find how many trading days an 80%-power test needs at 0.05 / 0.10 / 0.13 pp.
3. ``measure_baselines`` (needs the local Docker Postgres, SELECT only, candle dates <= 2026-01-31 only): the gross raw
   h-session close-to-close return of buying every eligible stock on the counted development days, by cap group, and
   the sampling noise of a random-5 minus every-stock daily excess. Used for the E* arithmetic. No holdout-period bar
   and no model score is read.

Everything is deterministic given the seeds recorded in the output (MASTER_SEED and per-cell SeedSequence keys).
Format only this file; do not run ``ruff format`` on the package.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from statistics import NormalDist

import numpy as np

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("sx_power_analysis", _HERE / "sx_power_analysis.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["sx_power_analysis"] = S
_spec.loader.exec_module(S)  # type: ignore[union-attr]

MASTER_SEED = 20261104
BASELINE_SEED = 20261105
REPO = _HERE.parents[1]
EVID = REPO / "docs" / "brain" / "evidence" / "sector_prep"
DRAWS = 2000
IDX_LOWER_25, IDX_LOWER_5, IDX_UPPER_5 = 50, 100, 1899  # sx_verdict.lower_bound / upper_bound indices for 2000 draws
BURN_IN = 4
HOLDOUT_DAYS = 133
DELTAS = np.round(np.arange(0.0, 0.8001, 0.01), 4)  # true paired edge, percentage points per trade
MDES = (0.10, 0.13, 0.16, 0.18, 0.20, 0.25, 0.30)
CORNERS = {  # (phi, rho_AC): ASSUMED, as in the S-9 note
    "central": (0.5, 0.8),
    "optimistic": (0.0, 0.95),
    "pessimistic": (0.9, 0.5),
    "sticky_picks": (0.9, 0.8),
    "independent_picks": (0.0, 0.8),
}
# Cost model (brain/lanes/h05_protocol.py and docs/brain/COSTS-CHECK-2026-10.md)
BUY_BPS, SELL_BPS, DP_RS = 11.9, 10.4, 15.93
SLIPPAGE_BPS = {"large": 10.0, "mid": 20.0, "small": 25.0}


# ------------------------------------------------------------------------------------------------ pure helpers
def round_trip_cost_bps(
    group: str | None = None, *, notional: float = 100_000.0, slip_bps: float | None = None
) -> float:
    """Round-trip cost in bps of the amount invested: buy and sell taxes, the flat depository fee, slippage twice."""
    slip = SLIPPAGE_BPS[group] if slip_bps is None else slip_bps
    return BUY_BPS + SELL_BPS + 2.0 * slip + DP_RS / notional * 10_000.0


def analytic_mde(se: float, alpha: float = 0.025, power: float = 0.8) -> float:
    """Smallest true mean whose one-sided lower bound clears 0 with probability `power` (normal approximation)."""
    nd = NormalDist()
    return (nd.inv_cdf(1 - alpha) + nd.inv_cdf(power)) * se


def outcome_word(r2: bool, r1: bool, r4: bool, upper: float, mde: float) -> str:
    """Order of ml/sx_verdict.compute_verdict for a run whose holdout is COMPLETED (data checks assumed met)."""
    if r2 and r1:
        return "PASS" if r4 else "INCONCLUSIVE"
    if (not r2) and upper < mde:
        return "FAIL"
    return "INCONCLUSIVE"


def synthetic_fold_days(total_days: int, n_folds: int) -> list[int]:
    base, extra = divmod(total_days, n_folds)
    return [base + (1 if i < extra else 0) for i in range(n_folds)]


def interp_first_crossing(xs, ys, target: float):
    """Smallest x where the (running-max) curve reaches target, linear interpolation; None if never."""
    p = np.maximum.accumulate(np.asarray(ys, float))
    if p[-1] < target:
        return None
    j = int(np.argmax(p >= target))
    if j == 0:
        return float(xs[0])
    x0, x1, y0, y1 = xs[j - 1], xs[j], p[j - 1], p[j]
    return float(x0 + (target - y0) * (x1 - x0) / (y1 - y0)) if y1 > y0 else float(x1)


def read_fold_days_all(h: int) -> list[int]:
    """Development fold day counts (34), burn-in folds first."""
    days = []
    with open(EVID / f"sx{h}_fold_coverage_v3.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["fold"] != "holdout":
                days.append(int(row["test_days"]))
    return days


def estar_candidates(
    *, gross_every_stock_pct: float, edge_a_pct: float, cost_pct: float, se_mean_pp: float, mde80_pp: float
) -> dict:
    """E* candidates in percentage points per trade (labelled; the owner chooses).
    E_costs     = round-trip friction of one trade: the gain that merely pays for trading once.
    E_breakeven = cost - gross drift of the every-stock baseline - edge of A_53: the extra top-5 gain C must add for the
                  top-5 to earn zero net per trade.
    E_sd        = 1.645 x standard error of the counted-series mean of D_t: the smallest gain the experiment can separate
                  from zero at one-sided 5% in a typical sample (resolution, not value).
    E_mde80     = the power-based value (for comparison)."""
    return {
        "E_costs": cost_pct,
        "E_breakeven": cost_pct - gross_every_stock_pct - edge_a_pct,
        "E_sd": 1.645 * se_mean_pp,
        "E_mde80": mde80_pp,
    }


def independent_days_needed(sd_daily_pp: float, delta_pp: float, alpha: float = 0.025, power: float = 0.8) -> float:
    nd = NormalDist()
    return ((nd.inv_cdf(1 - alpha) + nd.inv_cdf(power)) * sd_daily_pp / delta_pp) ** 2


# ------------------------------------------------------------------------------------------------ the simulation
def simulate_outcomes(
    *,
    h: int,
    phi: float,
    rho_ac: float,
    n_sims: int,
    fold_days: list[int],
    burn_in: int,
    holdout_days: int,
    sd: np.ndarray,
    rho_c: float,
    df: float | None,
    seed_key: tuple,
    deltas: np.ndarray = DELTAS,
    mdes: tuple = MDES,
    master_seed: int = MASTER_SEED,
    draws: int = DRAWS,
) -> dict:
    """One (horizon, phi, rho_AC) cell. `fold_days` = ALL development folds (burn-in first); the counted series is
    fold_days[burn_in:]. The edge grid `deltas` (pp per trade) uses common random numbers (D_t is linear in delta).
    With holdout_days = 0 there is no R4 (a forward design): r4 is then reported True."""
    n = len(sd)
    counted = fold_days[burn_in:]
    off = sum(fold_days[:burn_in])
    n_c = int(sum(counted))
    t_dev = int(sum(fold_days))
    t_all = t_dev + holdout_days
    block = S.HORIZONS[h]["block"]
    m5 = S.expected_top_k_mean(n)
    thr = S.r1_threshold(len(counted))
    deltas = np.asarray(deltas, float)
    nd = len(deltas)
    child = np.random.SeedSequence([master_seed, *seed_key]).spawn(n_sims)
    keys = ("r2_25", "r2_5", "r1", "r4", "r1r2_25", "r1r2_5", "pass_25", "pass_5")
    tal = {k: np.zeros(nd) for k in keys}
    word = {m: {w: np.zeros(nd) for w in ("PASS", "FAIL", "INCONCLUSIVE")} for m in mdes}
    word5 = {m: {w: np.zeros(nd) for w in ("PASS", "FAIL", "INCONCLUSIVE")} for m in mdes}
    up_sum = np.zeros(nd)
    se_boot0 = 0.0
    mean0 = np.zeros(n_sims)
    var0 = np.zeros(n_sims)
    for s in range(n_sims):
        rng = np.random.default_rng(child[s])
        noise = S.simulate_noise_returns(rng, t_all, h, sd, rho_c, df, 0.0, None, 0.0)
        za = S.ar1_panel(rng, t_all, n, phi)
        zn = S.ar1_panel(rng, t_all, n, phi)
        zc = rho_ac * za + math.sqrt(1.0 - rho_ac**2) * zn
        d0 = S.top_k_mean(noise, zc) - S.top_k_mean(noise, za)
        g = (S.top_k_mean(zn, zc) - S.top_k_mean(zn, za)) / (m5 * math.sqrt(1.0 - rho_ac**2))
        a0, ag = d0[off : off + n_c], g[off : off + n_c]
        mean0[s], var0[s] = a0.mean(), a0.var()
        b0, bg = S.block_means_bootstrap([a0, ag], block, draws, rng)
        boot = b0[None, :] + deltas[:, None] * bg[None, :]
        part = np.partition(boot, [IDX_LOWER_25, IDX_LOWER_5, IDX_UPPER_5], axis=1)
        lo25, lo5, up = part[:, IDX_LOWER_25], part[:, IDX_LOWER_5], part[:, IDX_UPPER_5]
        se_boot0 += float(np.std(boot[0], ddof=1))
        f0, fg = S.fold_means(a0, counted), S.fold_means(ag, counted)
        pos = ((f0[None, :] + deltas[:, None] * fg[None, :]) > 0).sum(axis=1)
        r1 = pos >= thr
        dev_mean = a0.mean() + deltas * ag.mean()
        if holdout_days > 0:
            hold_mean = d0[t_dev:].mean() + deltas * g[t_dev:].mean()
            r4 = (dev_mean > 0) & (hold_mean > 0)
        else:
            r4 = np.ones(nd, bool)
        r2a, r2b = lo25 > 0, lo5 > 0
        tal["r2_25"] += r2a
        tal["r2_5"] += r2b
        tal["r1"] += r1
        tal["r4"] += r4
        tal["r1r2_25"] += r1 & r2a
        tal["r1r2_5"] += r1 & r2b
        tal["pass_25"] += r1 & r2a & r4
        tal["pass_5"] += r1 & r2b & r4
        up_sum += up
        win_ok = r1 & r4
        for m in mdes:
            for r2x, store in ((r2a, word), (r2b, word5)):
                ps = r2x & win_ok
                fl = (~r2x) & (up < m)
                store[m]["PASS"] += ps
                store[m]["FAIL"] += fl
                store[m]["INCONCLUSIVE"] += ~(ps | fl)
    out = {
        "h": h,
        "phi": phi,
        "rho_ac": rho_ac,
        "n_sims": n_sims,
        "counted_folds": len(counted),
        "counted_days": n_c,
        "r1_threshold": thr,
        "deltas": [float(x) for x in deltas],
        "seed_key": list(seed_key),
        "master_seed": master_seed,
        "se_mean_d_sims": float(np.std(mean0, ddof=1)),
        "sd_daily_d": float(math.sqrt(np.mean(var0))),
        "n_eff_variance_ratio": float(np.mean(var0) / np.var(mean0, ddof=1)),
        "mean_boot_se_at_delta0": se_boot0 / n_sims,
        "mean_upper95_by_delta": (up_sum / n_sims).tolist(),
        "tallies": {k: (v / n_sims).tolist() for k, v in tal.items()},
        "words_2_5": {str(m): {w: (a / n_sims).tolist() for w, a in d.items()} for m, d in word.items()},
        "words_5": {str(m): {w: (a / n_sims).tolist() for w, a in d.items()} for m, d in word5.items()},
    }
    out["mde"] = summarise_mde(deltas, out["tallies"], n_sims)
    return out


def summarise_mde(deltas: np.ndarray, tal: dict, n: int) -> dict:
    res = {}
    for key in ("r1r2_25", "r1r2_5", "pass_25", "pass_5", "r2_25", "r2_5"):
        p = np.asarray(tal[key])
        row = {}
        for tgt in (0.5, 0.8):
            lo = S.mde_from_curve(deltas, np.clip(p + 1.96 * np.sqrt(p * (1 - p) / n), 0, 1), tgt)
            hi = S.mde_from_curve(deltas, np.clip(p - 1.96 * np.sqrt(p * (1 - p) / n), 0, 1), tgt)
            row[f"@{int(tgt * 100)}"] = {"est": S.mde_from_curve(deltas, p, tgt), "mc_lo": lo, "mc_hi": hi}
        res[key] = row
    return res


def _cell_job(job: dict):
    kw = dict(job)
    kw["sd"] = np.asarray(kw["sd"])
    return kw.pop("_label"), simulate_outcomes(**kw)


# ------------------------------------------------------------------------------------------------ real data (dev only)
def load_groups() -> dict[str, str]:
    d = json.loads((EVID.parent / "lane_universe" / "lane_universe_v1.json").read_text())
    out = {s: "large" for s in d["large"]}
    out.update({s: "mid" for s in d["mid"]})
    return out


def counted_window_start(h: int) -> date:
    with open(EVID / f"sx{h}_fold_coverage_v3.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["fold"] != "holdout"]
    return date.fromisoformat(rows[BURN_IN]["test_start"])


def random5_excess_se(R: np.ndarray, draws: int, seed: int) -> dict:
    """R: days x stocks (NaN = not eligible). Per draw: mean over days of (mean of 5 random stocks - mean of all).
    The SD over draws is the sampling noise of the counted-series mean for a no-skill picker whose picks do not repeat."""
    rng = np.random.default_rng(seed)
    ok = ~np.isnan(R)
    base = np.nanmean(R, axis=1)
    means = []
    for _ in range(draws):
        sc = rng.random(R.shape)
        sc[~ok] = -1.0
        idx = np.argpartition(-sc, 4, axis=1)[:, :5]
        pk = np.take_along_axis(R, idx, axis=1)
        means.append(np.nanmean(np.nanmean(pk, axis=1) - base))
    return {"sd_of_mean_pp": float(np.std(means, ddof=1)), "draws": draws, "mean_of_means_pp": float(np.mean(means))}


def measure_baselines(draws: int = 400) -> dict:
    import pandas as pd

    groups = load_groups()
    out: dict = {"source": "candles <= 2026-01-31 via local Postgres SELECT; eligible rows from the signed v3 lists"}
    for h in (5, 10):
        elig = S.load_row_keys(EVID / f"sx{h}_47_rows_v3.txt.gz")
        syms = sorted({s for s, _ in elig})
        prices = S.fetch_prices(syms)
        start = counted_window_start(h)
        cols = {}
        for sym, g in prices.groupby("symbol"):
            g = g.sort_values("day").reset_index(drop=True)
            c = g["close"].to_numpy(float)
            d1 = np.concatenate([[np.nan], c[1:] / c[:-1] - 1.0])
            big = np.abs(np.nan_to_num(d1)) > 0.25
            fr = np.full(len(c), np.nan)
            fr[:-h] = (c[h:] / c[:-h] - 1.0) * 100.0
            bc = np.concatenate([[0], np.cumsum(big)])
            last = len(c) - 1
            bad = np.array(
                [(t + 1 <= min(t + h, last)) and bc[min(t + h, last) + 1] - bc[t + 1] > 0 for t in range(len(c))]
            )
            keep = np.array([((sym, d.isoformat()) in elig) and start <= d <= S.DEV_LAST_DAY for d in g["day"]])
            keep &= ~np.isnan(fr) & ~bad
            cols[sym] = pd.Series(fr[keep], index=g["day"][keep])
        R = pd.DataFrame(cols).sort_index()
        R = R[R.notna().sum(axis=1) >= 10]
        arr = R.to_numpy()
        per_group = {}
        for grp in ("large", "mid"):
            sel = [i for i, s in enumerate(R.columns) if groups.get(s) == grp]
            vals = arr[:, sel]
            per_group[grp] = {
                "stocks": len(sel),
                "stock_day_rows": int(np.sum(~np.isnan(vals))),
                "gross_mean_return_pct": float(np.nanmean(vals)) if vals.size and not np.all(np.isnan(vals)) else None,
            }
        flat = arr[~np.isnan(arr)]
        out[f"h{h}"] = {
            "counted_window_first_day": start.isoformat(),
            "decision_days": int(len(R)),
            "stock_day_rows": int(flat.size),
            "gross_mean_return_pct_every_stock": float(flat.mean()),
            "cross_sectional_sd_pct_avg_over_days": float(np.nanmean(np.nanstd(arr, axis=1))),
            "gross_by_group": per_group,
            "random5_vs_all": random5_excess_se(arr, draws, BASELINE_SEED + h),
        }
    return out


# ------------------------------------------------------------------------------------------------ derived tables
def days_needed_from_cells(cells: dict, prefix: str, h: int, corner: str, key: str, delta: float, days: list[int]):
    """Trading days at which the simulated power for `key` first reaches 80% at true edge `delta` (linear interpolation
    in T between simulated lengths). None if not reached by the longest simulated length."""
    xs, ys = [], []
    for T in days:
        c = cells.get(f"{prefix}|h{h}|{corner}|T{T}")
        if c is None:
            continue
        xs.append(T)
        ys.append(c["tallies"][key][c["deltas"].index(delta)])
    if len(xs) < 2:
        return None
    return interp_first_crossing(xs, ys, 0.8)


def analytic_days_r2_only(se_at_t0: float, t0: int, delta: float) -> float:
    """R2 alone, normal theory, SE falling as 1/sqrt(T): T80 = t0 x ((z_.975 + z_.8) x SE(t0) / delta)^2."""
    return t0 * (analytic_mde(se_at_t0) / delta) ** 2


def derive_summary(data: dict) -> dict:
    cells, base = data["cells"], data.get("baselines")
    out: dict = {"corrected_mde80": {}, "outcome_probabilities": {}, "tradeoff": {}, "duration": {}, "e_star": {}}
    deltas_report = (0.0, 0.05, 0.10, 0.16, 0.30)
    for h in (5, 10):
        for corner in ("central", "optimistic", "pessimistic"):
            row = {}
            for tag in ("counted30", "all34"):
                c = cells.get(f"main|h{h}|{corner}|rep0|{tag}")
                if c:
                    row[tag] = {k: c["mde"][k]["@80"] for k in ("r1r2_25", "r1r2_5", "pass_25", "r2_25")}
                    row[tag]["days"] = c["counted_days"]
                    row[tag]["se_mean_d"] = c["se_mean_d_sims"]
            out["corrected_mde80"][f"SX{h}|{corner}"] = row
            c = cells[f"main|h{h}|{corner}|rep0|counted30"]
            tab = {}
            for m in c["words_2_5"]:
                tab[m] = {
                    str(d): {w: c["words_2_5"][m][w][c["deltas"].index(d)] for w in ("PASS", "FAIL", "INCONCLUSIVE")}
                    for d in deltas_report
                }
            out["outcome_probabilities"][f"SX{h}|{corner}"] = tab
            trade = {}
            for m in (0.10, 0.16, 0.25, 0.30):
                i0, im = c["deltas"].index(0.0), c["deltas"].index(round(m, 2))
                w = c["words_2_5"][str(m)]
                trade[str(m)] = {
                    "P_FAIL_at_zero": w["FAIL"][i0],
                    "P_INCONCLUSIVE_at_zero": w["INCONCLUSIVE"][i0],
                    "P_PASS_at_edge_equal_MDE_H": w["PASS"][im],
                    "P_FAIL_at_edge_equal_MDE_H": w["FAIL"][im],
                    "P_INCONCLUSIVE_at_edge_equal_MDE_H": w["INCONCLUSIVE"][im],
                }
            out["tradeoff"][f"SX{h}|{corner}"] = trade
    days = sorted({int(k.split("|T")[1]) for k in cells if k.startswith("dur|h5|central")})
    for h in (5, 10):
        for corner in ("central", "optimistic", "pessimistic"):
            c565 = cells.get(f"dur|h{h}|{corner}|T565")
            rows = {}
            for delta in (0.05, 0.10, 0.13):
                rows[str(delta)] = {
                    "R2_only_sim": days_needed_from_cells(cells, "dur", h, corner, "r2_25", delta, days),
                    "R1_R2_19day_folds_sim": days_needed_from_cells(cells, "dur", h, corner, "r1r2_25", delta, days),
                    "R1_R2_30_folds_sim": days_needed_from_cells(cells, "dur30", h, corner, "r1r2_25", delta, days)
                    if corner != "pessimistic"
                    else None,
                    "R2_only_analytic": analytic_days_r2_only(c565["se_mean_d_sims"], 565, delta) if c565 else None,
                }
            out["duration"][f"SX{h}|{corner}"] = rows
    if base:
        cost_h05 = round_trip_cost_bps("large") / 100.0
        cost_fd = round_trip_cost_bps(slip_bps=5.0, notional=40_000.0) / 100.0
        for h in (5, 10):
            g = base[f"h{h}"]["gross_mean_return_pct_every_stock"]
            c = cells[f"main|h{h}|central|rep0|counted30"]
            sd_d, ratio = c["sd_daily_d"], c["n_eff_variance_ratio"] / c["counted_days"]
            e = {
                "cost_pct_h05_assumption": cost_h05,
                "cost_pct_fd_v1_style": cost_fd,
                "gross_every_stock_pct_counted_window": g,
                "net_every_stock_raw_hold_pct": g - cost_h05,
                "random5_se_pp": base[f"h{h}"]["random5_vs_all"]["sd_of_mean_pp"],
                "candidates_raw_hold": estar_candidates(
                    gross_every_stock_pct=g, edge_a_pct=0.0, cost_pct=cost_h05,
                    se_mean_pp=c["se_mean_d_sims"], mde80_pp=c["mde"]["pass_25"]["@80"]["est"],
                ),
                "sd_daily_d_pp": sd_d,
                "independent_days_over_trading_days": ratio,
            }
            e["days_to_confirm_80pct"] = {}
            for name, val in (
                ("E_sd", e["candidates_raw_hold"]["E_sd"]),
                ("E_mde80", e["candidates_raw_hold"]["E_mde80"]),
                ("0.25", 0.25),
                ("E_costs_fd", cost_fd),
                ("E_costs_h05", cost_h05),
                ("E_breakeven_traded_rule_0.37", 0.37),
            ):
                ind = independent_days_needed(sd_d, val)
                e["days_to_confirm_80pct"][name] = {"edge_pp": val, "independent_days": ind, "trading_days": ind / ratio}
            out["e_star"][f"SX{h}"] = e
    return out


# ------------------------------------------------------------------------------------------------ driver
def build_jobs(measured: dict, sims: int, dur_sims: int, dur_days: list[int]) -> list[dict]:
    jobs = []
    for h in (5, 10):
        m = measured[f"h{h}"]
        sd = np.array(list(m["daily_return_sd_pct_by_stock"].values()))
        kurt = max(m["daily_return_excess_kurtosis"], 0.5)
        df = 4.0 + 6.0 / kurt
        rho_c = max(m["cross_corr_daily_return"], 0.0)
        fd = read_fold_days_all(h)
        for ic, (name, (phi, rho)) in enumerate(CORNERS.items()):
            for rep in (0, 1) if name == "central" else (0,):
                jobs.append(
                    dict(
                        _label=f"main|h{h}|{name}|rep{rep}|counted30",
                        h=h, phi=phi, rho_ac=rho, n_sims=sims, fold_days=fd, burn_in=BURN_IN,
                        holdout_days=HOLDOUT_DAYS, sd=sd, rho_c=rho_c, df=df, seed_key=(1, h, ic, rep),
                        master_seed=MASTER_SEED + 1000 * rep,
                    )
                )
            if name in ("central", "optimistic", "pessimistic"):  # the uncorrected 34-fold / 642-day series
                jobs.append(
                    dict(
                        _label=f"main|h{h}|{name}|rep0|all34",
                        h=h, phi=phi, rho_ac=rho, n_sims=sims, fold_days=fd, burn_in=0,
                        holdout_days=HOLDOUT_DAYS, sd=sd, rho_c=rho_c, df=df, seed_key=(2, h, ic, 0),
                    )
                )
        for name in ("central", "optimistic", "pessimistic"):
            phi, rho = CORNERS[name]
            ic = list(CORNERS).index(name)
            for T in dur_days:
                nf = max(int(round(T / 19.0)), 4)
                jobs.append(
                    dict(
                        _label=f"dur|h{h}|{name}|T{T}",
                        h=h, phi=phi, rho_ac=rho, n_sims=dur_sims, fold_days=synthetic_fold_days(T, nf),
                        burn_in=0, holdout_days=0, sd=sd, rho_c=rho_c, df=df, seed_key=(3, h, ic, T),
                        deltas=np.round(np.arange(0.0, 0.4001, 0.01), 4), mdes=(0.10,),
                    )
                )
        # fixed 30 folds that grow with T (R1 then judges 30 folds, as in the development design)
        for name in ("central", "optimistic"):
            phi, rho = CORNERS[name]
            ic = list(CORNERS).index(name)
            for T in dur_days[1:]:
                jobs.append(
                    dict(
                        _label=f"dur30|h{h}|{name}|T{T}",
                        h=h, phi=phi, rho_ac=rho, n_sims=dur_sims, fold_days=synthetic_fold_days(T, 30),
                        burn_in=0, holdout_days=0, sd=sd, rho_c=rho_c, df=df, seed_key=(4, h, ic, T),
                        deltas=np.round(np.arange(0.0, 0.4001, 0.01), 4), mdes=(0.10,),
                    )
                )
    return jobs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument("--measured", type=Path, default=EVID / "sx_s9_power_v1.json", help="measured-dependence JSON (S-9)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--dur-sims", type=int, default=600)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--skip-baselines", action="store_true")
    ap.add_argument("--baselines", type=Path, help="reuse a previous output's baselines instead of querying")
    ap.add_argument("--days", type=int, nargs="*", default=[565, 1000, 1500, 2250, 3000, 4500, 6500])
    ap.add_argument("--derive", type=Path, help="read a finished output JSON, add the 'derived' block, rewrite it")
    args = ap.parse_args(argv)
    if args.derive:
        data = json.loads(args.derive.read_text())
        data["derived"] = derive_summary(data)
        args.out.write_text(json.dumps(data, indent=1))
        return
    measured = json.loads(args.measured.read_text())["measured"]
    jobs = build_jobs(measured, args.sims, args.dur_sims, args.days)
    results = {}
    payload = [{**j, "sd": j["sd"].tolist()} for j in jobs]
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for label, res in ex.map(_cell_job, payload):
            results[label] = res
            print("done", label, file=sys.stderr, flush=True)
    if args.baselines:
        baselines = json.loads(args.baselines.read_text())["baselines"]
    elif args.skip_baselines:
        baselines = None
    else:
        baselines = measure_baselines()
    meta = {
        "master_seed": MASTER_SEED,
        "baseline_seed": BASELINE_SEED,
        "bootstrap_draws": DRAWS,
        "bound_indices": {"lower_2_5": IDX_LOWER_25, "lower_5": IDX_LOWER_5, "upper_5": IDX_UPPER_5},
        "sims_main": args.sims,
        "sims_duration": args.dur_sims,
        "holdout_days_simulated": HOLDOUT_DAYS,
        "burn_in_folds": BURN_IN,
        "mdes": list(MDES),
        "corners_phi_rho": CORNERS,
        "measured_input": str(args.measured.name),
        "no_model_fitted": True,
        "holdout_period_outcomes_computed": False,
    }
    args.out.write_text(json.dumps({"meta": meta, "baselines": baselines, "cells": results}, indent=1))


if __name__ == "__main__":
    main()
