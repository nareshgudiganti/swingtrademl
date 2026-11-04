"""S-9: minimum detectable edge for SX5 and SX10 (research power analysis; no model is fitted).

What this does
--------------
1. ``measure``: reads DEVELOPMENT-period prices only (candle dates <= 2026-01-31, so no holdout-period bar is read),
   restricted to the signed eligible-row lists, and measures the dependence that matters: per-stock label and
   return autocorrelation, same-day cross-stock correlation, daily-mean autocorrelation, effective days, daily
   volatility and tails. It also measures the day-to-day persistence of the stored production score (model 2) on
   post-holdout days (2026-08-16 or later) as the only real analogue of pick persistence. No label or return is
   computed for any holdout-period day.
2. ``simulate``: simulates the exact decision procedure on SYNTHETIC data with that dependence:
   R1 (>= 60% of folds with a positive mean paired difference), R2 (one-sided lower bound of the moving-block
   bootstrap of D_t above 0 at 2.5% or 5%: Holm over the two primaries), R4 (holdout sign).

Synthetic model (all of it is an assumption except the measured inputs)
-----------------------------------------------------------------------
* Daily returns r[s,i] = sd_i * (sqrt(rho_c) m_s + sqrt(1-rho_c) e[s,i]), Student-t tails, iid in time (optionally a
  common volatility multiplier that clusters in time: regime dependence). The h-day forward return of day t is the
  rolling sum of the next h daily returns, which reproduces the overlap of consecutive outcomes by construction.
* Scores are AR(1) in time with persistence phi (marginally N(0,1)). Arm A's score is zA. Arm C's score is
  zC = rho_AC * zA + sqrt(1 - rho_AC^2) * zN. The true expected return is mu = bN * zN, so only the part of C's score
  that A does not see carries information (A has no edge: the repo's evidence for A-like models is a null).
* D_t = (mean R over C's top 5) - (mean R over A's top 5): the every-stock mean cancels in the paired series.
* Because mu is linear in bN, D_t(delta) = D0_t + delta * g_t exactly, so one set of draws gives the whole power curve
  with common random numbers (power is monotone in delta by construction up to Monte Carlo noise).
  delta = the true expected paired edge in percentage points of the top-5 excess (equal to the edge per trade).

Everything is deterministic given the seeds printed in the output (MASTER_SEED and the per-cell SeedSequence).
Format only this file; do not run ``ruff format`` on the package.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

MASTER_SEED = 20261108
BOOTSTRAP_SEED = (
    7  # the protocol's seed (S-3); used by `real_analysis_bootstrap`, simulations use spawned seeds
)
DRAWS = 2000
TOP_K = 5
R1_SHARE = 0.60
HOLDOUT_DAYS = 133
DEV_LAST_DAY = date(2026, 1, 31)
DEV_FIRST_DAY = date(2023, 7, 1)
BURN_IN_FOLDS = 4  # B2: folds 0-3 reported but excluded (folds 4-33 counted)
ALPHA_HOLM_FIRST = 0.025
ALPHA_HOLM_SECOND = 0.05
HORIZONS = {5: {"block": 10}, 10: {"block": 20}}
REPO = Path(__file__).resolve().parents[2]
EVID = REPO / "docs" / "brain" / "evidence" / "sector_prep"


# --------------------------------------------------------------------------------------------- small pure helpers
def expected_top_k_mean(n: int, k: int = TOP_K, draws: int = 200_000, seed: int = 11) -> float:
    """E[mean of the k largest of n iid N(0,1)] by Monte Carlo (fixed seed)."""
    x = np.random.default_rng(seed).standard_normal((draws, n))
    return float(np.sort(x, axis=1)[:, -k:].mean())


def ar1_panel(rng: np.random.Generator, t: int, n: int, phi: float) -> np.ndarray:
    """(t, n) stationary AR(1) in time, marginally N(0,1), independent across columns."""
    eps = rng.standard_normal((t, n))
    if phi == 0.0:
        return eps
    s = math.sqrt(1.0 - phi * phi)
    x = eps.copy()
    x[0] = eps[0] / s  # so that the first output equals eps[0] (a stationary start)
    return lfilter([s], [1.0, -phi], x, axis=0)


def grouped_ar1_panel(
    rng: np.random.Generator, t: int, n: int, phi: float, groups: np.ndarray | None, share: float
) -> np.ndarray:
    """Like ar1_panel, but a share `share` of each score's variance is common to the stock's group (picks cluster)."""
    z = ar1_panel(rng, t, n, phi)
    if groups is None or share <= 0.0:
        return z
    zg = ar1_panel(rng, t, int(groups.max()) + 1, phi)[:, groups]
    return math.sqrt(1.0 - share) * z + math.sqrt(share) * zg


def top_k_mean(values: np.ndarray, scores: np.ndarray, k: int = TOP_K) -> np.ndarray:
    """Per row: mean of `values` over the k highest `scores` (ties are measure-zero for continuous scores)."""
    idx = np.argpartition(-scores, k - 1, axis=1)[:, :k]
    return np.take_along_axis(values, idx, axis=1).mean(axis=1)


def top_k_sets(scores: np.ndarray, k: int = TOP_K) -> np.ndarray:
    return np.argpartition(-scores, k - 1, axis=1)[:, :k]


def pick_repeat_share(scores: np.ndarray, k: int = TOP_K) -> float:
    """Average share of today's top-k that is still in tomorrow's top-k."""
    sets = top_k_sets(scores, k)
    shares = [len(set(a) & set(b)) / k for a, b in zip(sets[:-1], sets[1:])]
    return float(np.mean(shares))


def rolling_forward_sum(daily: np.ndarray, h: int, t: int) -> np.ndarray:
    """Row t of the result = sum of daily[t+1 .. t+h]. `daily` needs t + h + 1 rows (row 0 is unused)."""
    cs = np.cumsum(daily, axis=0)
    return cs[h + 0 : h + t] - cs[0:t]


def simulate_noise_returns(
    rng: np.random.Generator,
    t: int,
    h: int,
    sd: np.ndarray,
    rho_c: float,
    df: float | None,
    vol_cluster: float = 0.0,
    groups: np.ndarray | None = None,
    group_var: float = 0.0,
) -> np.ndarray:
    """(t, n) forward h-day returns in percent from iid-in-time daily returns (optionally with clustered volatility).
    `groups` (length n, ints) and `group_var` add a sector-style factor: share `group_var` of each stock's variance is
    common to its group (ASSUMED structure; the one-factor base case has group_var = 0)."""
    n = len(sd)
    rows = t + h + 1

    def draw(shape):
        if df is None:
            return rng.standard_normal(shape)
        return rng.standard_t(df, size=shape) / math.sqrt(df / (df - 2.0))

    m = draw((rows, 1))
    e = draw((rows, n))
    if groups is not None and group_var > 0.0:
        ng = int(groups.max()) + 1
        f = draw((rows, ng))[:, groups]
        r = sd[None, :] * (
            math.sqrt(rho_c) * m + math.sqrt(group_var) * f + math.sqrt(1.0 - rho_c - group_var) * e
        )
    else:
        r = sd[None, :] * (math.sqrt(rho_c) * m + math.sqrt(1.0 - rho_c) * e)
    if vol_cluster > 0.0:  # common log-volatility, AR(1) persistence 0.98, stationary sd = vol_cluster
        ar = 0.98
        eta = rng.standard_normal(rows)
        eta[0] = eta[0] / math.sqrt(1 - ar * ar)
        lv = lfilter([math.sqrt(1 - ar * ar) * vol_cluster], [1.0, -ar], eta)
        mult = np.exp(lv - 0.5 * vol_cluster**2)  # mean one
        r = r * mult[:, None]
    return rolling_forward_sum(r, h, t)


def block_means_bootstrap(
    ds: list[np.ndarray], block: int, draws: int, rng: np.random.Generator
) -> list[np.ndarray]:
    """Moving-block bootstrap (S-3): non-circular blocks of `block` consecutive days, ceil(n/block) blocks per draw.
    The same block starts are applied to every series in `ds` (common random numbers). Returns one array of
    `draws` bootstrap means per series."""
    n = len(ds[0])
    block = min(block, n)
    nb = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(draws, nb))
    out = []
    for d in ds:
        cs = np.concatenate([[0.0], np.cumsum(d)])
        bm = (cs[block:] - cs[:-block]) / block  # mean of each window; index = start
        out.append(bm[starts].mean(axis=1))
    return out


def r1_threshold(n_folds: int, share: float = R1_SHARE) -> int:
    """Smallest fold count k with k / n_folds >= share (34 folds -> 21, 30 folds -> 18)."""
    return math.ceil(share * n_folds - 1e-9)


def fold_means(d: np.ndarray, fold_days: list[int]) -> np.ndarray:
    ends = np.cumsum(fold_days)
    starts = ends - np.asarray(fold_days)
    cs = np.concatenate([[0.0], np.cumsum(d)])
    return (cs[ends] - cs[starts]) / np.asarray(fold_days)


def effective_n_acf(x: np.ndarray, max_lag: int) -> float:
    """n_eff = n / (1 + 2 * sum_{k=1..K} (1 - k/(K+1)) * rho_k)  (Bartlett taper; K = max_lag), clipped to [1, n]."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)
    den = float(np.dot(x, x))
    if den == 0.0:
        return float(n)
    rho = np.array([np.dot(x[:-k], x[k:]) / den for k in range(1, max_lag + 1)])
    w = 1.0 - np.arange(1, max_lag + 1) / (max_lag + 1.0)
    inflation = 1.0 + 2.0 * float(np.sum(w * rho))
    return float(min(max(n / max(inflation, 1e-9), 1.0), n))


def mde_from_curve(deltas: np.ndarray, power: np.ndarray, target: float) -> float | None:
    """Smallest delta where the (monotone-smoothed) power curve reaches `target`; linear interpolation; None if never."""
    p = np.maximum.accumulate(np.asarray(power, dtype=float))
    if p[-1] < target:
        return None
    j = int(np.argmax(p >= target))
    if j == 0:
        return float(deltas[0])
    x0, x1, y0, y1 = deltas[j - 1], deltas[j], p[j - 1], p[j]
    return float(x0 + (target - y0) * (x1 - x0) / (y1 - y0)) if y1 > y0 else float(x1)


def mc_se(p: float, n: int) -> float:
    return math.sqrt(max(p * (1 - p), 0.0) / n)


# ----------------------------------------------------------------------------------------------- the simulation
def simulate_cell(
    *,
    h: int,
    phi: float,
    rho_ac: float,
    mode: str,
    n_sims: int,
    fold_days: list[int],
    holdout_days: int,
    sd: np.ndarray,
    rho_c: float,
    df: float | None,
    vol_cluster: float,
    seed_key: tuple,
    n_groups: int = 0,
    group_var: float = 0.0,
    group_score_share: float = 0.0,
    n_grid: int = 41,
    grid_max_se: float = 5.0,
    draws: int = DRAWS,
) -> dict:
    """Power curves for one (horizon, phi, rho_AC) cell. mode = 'paired' (C_56 - A_53) or 'single' (A_53 - every stock).
    Returns tallies per variant ('f34' = all folds, 'f30' = folds 4-33 only) over a grid of true edges `deltas`."""
    n = len(sd)
    t_dev = int(sum(fold_days))
    t_all = t_dev + holdout_days
    block = HORIZONS[h]["block"]
    m5 = expected_top_k_mean(n)
    root = np.random.SeedSequence([MASTER_SEED, *seed_key])
    child = root.spawn(n_sims + 1)

    groups = (np.arange(n) % n_groups) if n_groups > 0 else None

    def one(rng):
        noise = simulate_noise_returns(rng, t_all, h, sd, rho_c, df, vol_cluster, groups, group_var)
        za = grouped_ar1_panel(rng, t_all, n, phi, groups, group_score_share)
        if mode == "paired":
            zn = grouped_ar1_panel(rng, t_all, n, phi, groups, group_score_share)
            zc = rho_ac * za + math.sqrt(1.0 - rho_ac**2) * zn
            d0 = top_k_mean(noise, zc) - top_k_mean(noise, za)
            g = (top_k_mean(zn, zc) - top_k_mean(zn, za)) / (m5 * math.sqrt(1.0 - rho_ac**2))
            return d0, g, zc
        d0 = top_k_mean(noise, za) - noise.mean(axis=1)
        g = (top_k_mean(za, za) - za.mean(axis=1)) / m5
        return d0, g, za

    # pilot (separate stream, discarded) to size the grid: sd of the 642-day mean of D0
    pil, pil_g = [], []
    prng = np.random.default_rng(child[-1])
    for _ in range(100 if n_groups == 0 else 200):
        d0p, gp, _sc = one(prng)
        pil.append(d0p[:t_dev].mean())
        pil_g.append(gp[:t_dev].mean())
    se = float(np.std(pil, ddof=1))
    # With clustered scores the expected top-5 gain per unit of signal is no longer the iid-normal m5: rescale g so that
    # E[g] = 1 (the true paired edge is then exactly delta). Not applied (scale 1) in the base cases.
    gscale = 1.0 / float(np.mean(pil_g)) if n_groups > 0 else 1.0
    deltas = np.linspace(0.0, grid_max_se * se, n_grid)

    variants = {"f34": (0, fold_days), "f30": (sum(fold_days[:BURN_IN_FOLDS]), fold_days[BURN_IN_FOLDS:])}
    tal = {
        v: {k: np.zeros(n_grid) for k in ("r1", "p25", "p5", "r4", "r1p25", "r1p5", "r1p25r4", "r1p5r4")}
        for v in variants
    }
    null_flags = {v: np.zeros((n_sims, 4), dtype=bool) for v in variants}  # r1, p25, p5, r4 at delta=0
    mean0 = np.zeros(n_sims)
    var0 = np.zeros(n_sims)
    repeat = []
    for s in range(n_sims):
        rng = np.random.default_rng(child[s])
        d0, g, score = one(rng)
        g = g * gscale
        if s < 20:
            repeat.append(pick_repeat_share(score[:t_dev]))
        mean0[s] = d0[:t_dev].mean()
        var0[s] = d0[:t_dev].var()
        hold0, holdg = d0[t_dev:].mean(), g[t_dev:].mean()
        r4 = (hold0 + deltas * holdg) > 0
        for v, (off, fdays) in variants.items():
            n_v = int(sum(fdays))
            a0, ag = d0[off : off + n_v], g[off : off + n_v]
            b0, bg = block_means_bootstrap([a0, ag], block, draws, rng)
            boot = b0[None, :] + deltas[:, None] * bg[None, :]
            lo25 = np.quantile(boot, 0.025, axis=1) > 0
            lo5 = np.quantile(boot, 0.05, axis=1) > 0
            f0, fg = fold_means(a0, fdays), fold_means(ag, fdays)
            pos = ((f0[None, :] + deltas[:, None] * fg[None, :]) > 0).sum(axis=1)
            r1 = pos >= r1_threshold(len(fdays))
            t = tal[v]
            t["r1"] += r1
            t["p25"] += lo25
            t["p5"] += lo5
            t["r4"] += r4
            t["r1p25"] += r1 & lo25
            t["r1p5"] += r1 & lo5
            t["r1p25r4"] += r1 & lo25 & r4
            t["r1p5r4"] += r1 & lo5 & r4
            null_flags[v][s] = (r1[0], lo25[0], lo5[0], r4[0])
    out = {
        "h": h,
        "phi": phi,
        "rho_ac": rho_ac,
        "mode": mode,
        "n_sims": n_sims,
        "deltas": deltas.tolist(),
        "se_642d_mean_pilot": se,
        "d0_mean_se_all_sims": float(np.std(mean0, ddof=1)),
        "n_eff_variance_ratio": float(np.mean(var0) / np.var(mean0, ddof=1)),
        "n_days_dev": t_dev,
        "top5_repeat_share_next_day": float(np.mean(repeat)),
        "variants": {},
    }
    for v in variants:
        out["variants"][v] = {k: (x / n_sims).tolist() for k, x in tal[v].items()}
        out["variants"][v]["null_flags"] = null_flags[v]
    return out


def summarise_cell(cell: dict) -> dict:
    """Minimum detectable edges and null rates from a cell's tallies (null_flags stay out of the JSON)."""
    deltas = np.asarray(cell["deltas"])
    n = cell["n_sims"]
    res = {k: cell[k] for k in cell if k not in ("variants", "deltas")}
    res["variants"] = {}
    for v, d in cell["variants"].items():
        nf = d["null_flags"]
        entry = {"null": {}, "mde": {}, "power_at_grid": {}}
        for key in ("r1", "p25", "p5", "r4", "r1p25", "r1p5", "r1p25r4", "r1p5r4"):
            entry["null"][key] = d[key][0]
        entry["null_mc_se_r1p25"] = mc_se(d["r1p25"][0], n)
        entry["null_mc_se_r1p5"] = mc_se(d["r1p5"][0], n)
        for key in ("r1p25", "r1p5", "p25", "p5", "r1p25r4", "r1p5r4", "r1", "r4"):
            p = np.asarray(d[key])
            for tgt in (0.5, 0.8):
                est = mde_from_curve(deltas, p, tgt)
                lo = mde_from_curve(deltas, np.clip(p + 1.96 * np.sqrt(p * (1 - p) / n), 0, 1), tgt)
                hi = mde_from_curve(deltas, np.clip(p - 1.96 * np.sqrt(p * (1 - p) / n), 0, 1), tgt)
                entry["mde"][f"{key}@{int(tgt * 100)}"] = {"est": est, "mc_lo": lo, "mc_hi": hi}
            entry["power_at_grid"][key] = p.tolist()
        entry["null_flags_for_holm"] = nf
        res["variants"][v] = entry
    res["deltas"] = deltas.tolist()
    return res


def holm_family_false_pass(flags_a: np.ndarray, flags_b: np.ndarray, with_r4: bool) -> float:
    """Two independent null runs (SX5, SX10); per sim flags columns r1,p25,p5,r4. A horizon passes when R1 (and R4)
    hold and its p-value clears 2.5%, or clears 5% while the other horizon clears 2.5%. Returns P(any pass)."""
    k = min(len(flags_a), len(flags_b))
    a, b = flags_a[:k], flags_b[:k]

    def final(x, y):
        ok = x[:, 0] & ((x[:, 1]) | (x[:, 2] & y[:, 1]))
        return ok & x[:, 3] if with_r4 else ok

    return float(np.mean(final(a, b) | final(b, a)))


# -------------------------------------------------------------------------------------- measurement of real data
def barrier_label(close, high, low, horizon, target, stop):
    """td-protocol-v1 barrier label (same convention as ml.features.build_label): 1 if +target is touched strictly before
    -stop within `horizon` bars; a same-bar touch is a stop; the last `horizon` rows are dropped (returned shorter)."""
    n = len(close)
    never = horizon + 1
    ht = np.full(n, never)
    hs = np.full(n, never)
    up, lo = close * (1 + target), close * (1 - stop)
    for off in range(1, horizon + 1):
        fh = np.full(n, np.nan)
        fl = np.full(n, np.nan)
        fh[: n - off] = high[off:]
        fl[: n - off] = low[off:]
        ht[(fh >= up) & (ht == never)] = off
        hs[(fl <= lo) & (hs == never)] = off
    return (ht < hs).astype(int)[: n - horizon]


def per_stock_acf(series_by_stock: list[np.ndarray], max_lag: int) -> np.ndarray:
    """Mean over stocks of the lag-k autocorrelation, k = 1..max_lag (each stock demeaned on its own)."""
    out = []
    for x in series_by_stock:
        x = np.asarray(x, float)
        x = x - x.mean()
        den = float(np.dot(x, x))
        if den > 0 and len(x) > max_lag + 1:
            out.append([np.dot(x[:-k], x[k:]) / den for k in range(1, max_lag + 1)])
    return np.mean(out, axis=0)


def mean_pairwise_corr(panel) -> float:
    c = panel.corr(min_periods=100).to_numpy()
    iu = np.triu_indices_from(c, k=1)
    return float(np.nanmean(c[iu]))


def load_row_keys(path: Path) -> set[tuple[str, str]]:
    with gzip.open(path, "rt") as f:
        return {tuple(line.strip().split("|")) for line in f if line.strip()}


def psql(sql: str) -> str:
    cmd = [
        "docker",
        "exec",
        "stml-postgres",
        "psql",
        "-U",
        "swingtrade",
        "-d",
        "swing_trade_ml",
        "-At",
        "-F",
        ",",
        "-c",
        sql,
    ]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120).stdout


def fetch_prices(symbols: list[str]):
    import pandas as pd

    q = (
        "select i.tradingsymbol, (c.ts at time zone 'Asia/Kolkata')::date, c.close, c.high, c.low from candles c "
        "join instruments i on i.id=c.instrument_id where c.interval='day' and "
        f"(c.ts at time zone 'Asia/Kolkata')::date <= '{DEV_LAST_DAY.isoformat()}' and i.tradingsymbol in ("
        + ",".join(f"'{s}'" for s in symbols)
        + ") order by 1,2"
    )
    df = pd.read_csv(io.StringIO(psql(q)), names=["symbol", "day", "close", "high", "low"])
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return df.drop_duplicates(["symbol", "day"])


def measure_dependence(prices, eligible: set[tuple[str, str]], h: int, max_jump: float = 0.25) -> dict:
    """All inputs are development-period prices (<= 2026-01-31) of the signed eligible rows. Pure given `prices`."""
    import pandas as pd

    rets, labs, fwd, daily_ret = {}, {}, {}, {}
    dropped = 0
    kept_days = 0
    for sym, g in prices.groupby("symbol"):
        g = g.sort_values("day").reset_index(drop=True)
        c, hi, lo = g["close"].to_numpy(float), g["high"].to_numpy(float), g["low"].to_numpy(float)
        d1 = np.concatenate([[np.nan], c[1:] / c[:-1] - 1.0])
        big = np.abs(np.nan_to_num(d1)) > max_jump
        fr = np.full(len(c), np.nan)
        fr[:-h] = c[h:] / c[:-h] - 1.0
        if h == 5:
            lab = (fr >= 0.02).astype(float)
            lab[np.isnan(fr)] = np.nan
        else:
            lab = np.full(len(c), np.nan)
            lab[: len(c) - h] = barrier_label(c, hi, lo, h, 0.06, 0.035)
        # a window containing a likely unadjusted corporate action (one-day jump) is dropped
        bigc = np.concatenate([[0], np.cumsum(big)])
        bad = np.zeros(len(c), bool)
        for t in range(len(c)):
            lo_i, hi_i = t + 1, min(t + h, len(c) - 1)
            bad[t] = lo_i <= hi_i and bigc[hi_i + 1] - bigc[lo_i] > 0
        keys = [(sym, d.isoformat()) in eligible and DEV_FIRST_DAY <= d <= DEV_LAST_DAY for d in g["day"]]
        sel = np.array(keys) & ~np.isnan(fr) & ~bad
        dropped += int((np.array(keys) & ~np.isnan(fr) & bad).sum())
        kept_days += int(sel.sum())
        days = g["day"][sel]
        rets[sym] = pd.Series(fr[sel] * 100, index=days)
        labs[sym] = pd.Series(lab[sel], index=days)
        daily_ret[sym] = pd.Series(d1[sel] * 100, index=days)
        fwd[sym] = (fr[sel], lab[sel])
    R = pd.DataFrame(rets).sort_index()
    L = pd.DataFrame(labs).sort_index()
    Dd = pd.DataFrame(daily_ret).sort_index()
    nstock = R.notna().sum(axis=1)
    lag = 3 * h
    out = {
        "h": h,
        "stocks": int(R.shape[1]),
        "decision_days": int(len(R)),
        "stock_day_rows": kept_days,
        "windows_dropped_for_jump_over_25pct": dropped,
        "eligible_stocks_per_day": {
            "min": int(nstock.min()),
            "median": float(nstock.median()),
            "max": int(nstock.max()),
        },
        "daily_return_sd_pct_by_stock": {k: float(v) for k, v in Dd.std().items()},
        "daily_return_excess_kurtosis": float(np.nanmean(Dd.kurt())),
        "forward_return_sd_pct": float(np.nanmean(R.std())),
        "label_base_rate": float(np.nanmean(L.mean())),
        "cross_corr_forward_return": mean_pairwise_corr(R),
        "cross_corr_label": mean_pairwise_corr(L),
        "cross_corr_daily_return": mean_pairwise_corr(Dd),
        "per_stock_acf_forward_return_lags_1_to_2h": per_stock_acf(
            [x[0][~np.isnan(x[0])] for x in fwd.values()], 2 * h
        ).tolist(),
        "per_stock_acf_label_lags_1_to_2h": per_stock_acf(
            [x[1][~np.isnan(x[1])] for x in fwd.values()], 2 * h
        ).tolist(),
    }
    dm = R.mean(axis=1).to_numpy()
    dl = L.mean(axis=1).to_numpy()
    for name, x in (("daily_mean_return", dm), ("daily_mean_label", dl)):
        xc = x - x.mean()
        out[f"{name}_acf_lags_1_to_{2 * h}"] = [
            float(np.dot(xc[:-k], xc[k:]) / np.dot(xc, xc)) for k in range(1, 2 * h + 1)
        ]
        out[f"{name}_n_days"] = int(len(x))
        out[f"{name}_n_eff_bartlett_K{lag}"] = effective_n_acf(x, lag)
    return out


def measure_score_persistence() -> dict:
    """Stored production score (model 2) on post-holdout days only: day-to-day rank correlation and top-5 repeat share
    between consecutive stored days no more than 3 calendar days apart. Tiny sample; an analogue, not a calibration."""
    import pandas as pd

    q = (
        "select (p.ts at time zone 'Asia/Kolkata')::date, i.tradingsymbol, p.probability from predictions p "
        "join instruments i on i.id=p.instrument_id where p.model_id=2 and p.ts >= '2026-08-16' order by 1,2"
    )
    df = pd.read_csv(io.StringIO(psql(q)), names=["day", "symbol", "prob"])
    piv = df.pivot_table(index="day", columns="symbol", values="prob")
    days = list(piv.index)
    rc, rep, used = [], [], []
    for a, b in zip(days[:-1], days[1:]):
        gap = (pd.Timestamp(b) - pd.Timestamp(a)).days
        if gap > 3:
            continue
        x, y = piv.loc[a].dropna(), piv.loc[b].dropna()
        both = x.index.intersection(y.index)
        rc.append(float(x[both].rank().corr(y[both].rank())))
        rep.append(len(set(x.nlargest(TOP_K).index) & set(y.nlargest(TOP_K).index)) / TOP_K)
        used.append(f"{a}->{b}")
    return {
        "source": "predictions, model_id 2, post-holdout days only (>= 2026-08-16)",
        "days_available": [str(d) for d in days],
        "pairs_used": used,
        "mean_rank_correlation": float(np.mean(rc)) if rc else None,
        "rank_correlations": rc,
        "mean_top5_repeat_share": float(np.mean(rep)) if rep else None,
        "n_pairs": len(rc),
    }


def read_fold_days(h: int) -> list[int]:
    name = "sx5_fold_coverage_v3.csv" if h == 5 else "sx10_fold_coverage_v3.csv"
    days = []
    with open(EVID / name, newline="") as f:
        for row in csv.DictReader(f):
            if date.fromisoformat(row["test_end"]) <= DEV_LAST_DAY:
                days.append(int(row["test_days"]))
    return days


# ------------------------------------------------------------------------------------------------------- driver
def run_measure() -> dict:
    out = {}
    for h in (5, 10):
        elig = load_row_keys(EVID / f"sx{h}_47_rows_v3.txt.gz")
        syms = sorted({s for s, _ in elig})
        out[f"h{h}"] = measure_dependence(fetch_prices(syms), elig, h)
    out["score_persistence"] = measure_score_persistence()
    return out


def _dependence_inputs(measured: dict, h: int, *, df_override="measured"):
    m = measured[f"h{h}"]
    sd = np.array(list(m["daily_return_sd_pct_by_stock"].values()))
    kurt = max(m["daily_return_excess_kurtosis"], 0.5)
    df = 4.0 + 6.0 / kurt if df_override == "measured" else df_override
    rho_c = max(m["cross_corr_daily_return"], 0.0)
    return sd, df, rho_c


def run_simulate(measured: dict, n_sims: int, phis, rhos, sens_sims: int | None = None) -> dict:
    """Main grid (paired, both horizons), the single-arm benchmark reference, sensitivities, Holm family check."""
    sens_sims = sens_sims or n_sims
    out: dict = {"grid": [], "single_arm": [], "sensitivity": [], "holm": []}
    nullflags: dict = {}
    for h in (5, 10):
        sd, df, rho_c = _dependence_inputs(measured, h)
        fold_days = read_fold_days(h)
        for ip, phi in enumerate(phis):
            for ir, rho in enumerate(rhos):
                cell = simulate_cell(
                    h=h,
                    phi=phi,
                    rho_ac=rho,
                    mode="paired",
                    n_sims=n_sims,
                    fold_days=fold_days,
                    holdout_days=HOLDOUT_DAYS,
                    sd=sd,
                    rho_c=rho_c,
                    df=df,
                    vol_cluster=0.0,
                    seed_key=(h, ip, ir, 1),
                )
                res = summarise_cell(cell)
                for v in res["variants"]:
                    nullflags[(h, phi, rho, v)] = res["variants"][v].pop("null_flags_for_holm")
                out["grid"].append(res)
                print(f"paired h{h} phi{phi} rho{rho}", file=sys.stderr, flush=True)
            cell = simulate_cell(
                h=h,
                phi=phi,
                rho_ac=0.0,
                mode="single",
                n_sims=n_sims,
                fold_days=fold_days,
                holdout_days=HOLDOUT_DAYS,
                sd=sd,
                rho_c=rho_c,
                df=df,
                vol_cluster=0.0,
                seed_key=(h, ip, 9, 2),
            )
            res = summarise_cell(cell)
            for v in res["variants"]:
                res["variants"][v].pop("null_flags_for_holm")
            out["single_arm"].append(res)
            print(f"single h{h} phi{phi}", file=sys.stderr, flush=True)
        # sensitivities at the central cell (phi 0.9, rho 0.8): normal tails, regime-clustered volatility, measured tails
        for tag, kw in (
            ("normal_tails", dict(df=None, vol_cluster=0.0)),
            ("heavy_tails_df4", dict(df=4.0, vol_cluster=0.0)),
            ("volatility_regimes", dict(df=df, vol_cluster=0.4)),
            (
                "sector_clusters_10_groups",
                dict(df=df, vol_cluster=0.0, n_groups=10, group_var=0.10, group_score_share=0.3),
            ),
        ):
            base = dict(df=df, vol_cluster=0.0)
            base.update(kw)
            cell = simulate_cell(
                h=h,
                phi=0.9,
                rho_ac=0.8,
                mode="paired",
                n_sims=sens_sims,
                fold_days=fold_days,
                holdout_days=HOLDOUT_DAYS,
                sd=sd,
                rho_c=rho_c,
                seed_key=(h, 7, len(out["sensitivity"]), 3),
                **base,
            )
            res = summarise_cell(cell)
            for v in res["variants"]:
                res["variants"][v].pop("null_flags_for_holm")
            res["sensitivity"] = tag
            out["sensitivity"].append(res)
            print(f"sens {tag} h{h}", file=sys.stderr, flush=True)
    for phi in phis:
        for rho in rhos:
            for v in ("f34", "f30"):
                fa, fb = nullflags[(5, phi, rho, v)], nullflags[(10, phi, rho, v)]
                out["holm"].append(
                    {
                        "phi": phi,
                        "rho_ac": rho,
                        "variant": v,
                        "family_false_pass_r1_r2": holm_family_false_pass(fa, fb, with_r4=False),
                        "family_false_pass_r1_r2_r4": holm_family_false_pass(fa, fb, with_r4=True),
                        "n_pairs": int(min(len(fa), len(fb))),
                    }
                )
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])
    ap.add_argument(
        "--measured", type=Path, help="reuse a measured-dependence JSON instead of querying the database"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--sens-sims", type=int, default=1000)
    args = ap.parse_args(argv)
    if args.measured:
        measured = json.loads(args.measured.read_text())["measured"]
    else:
        measured = run_measure()
    sim = run_simulate(measured, args.sims, (0.0, 0.5, 0.9), (0.5, 0.8, 0.95), args.sens_sims)
    meta = {
        "master_seed": MASTER_SEED,
        "bootstrap_seed_protocol": BOOTSTRAP_SEED,
        "bootstrap_draws": DRAWS,
        "sims_per_cell": args.sims,
        "sens_sims_per_cell": args.sens_sims,
        "holdout_days": HOLDOUT_DAYS,
        "r1_share": R1_SHARE,
        "horizons": HORIZONS,
        "dev_window": [DEV_FIRST_DAY.isoformat(), DEV_LAST_DAY.isoformat()],
    }
    args.out.write_text(
        json.dumps({"meta": meta, "measured": measured, **sim}, indent=1, default=lambda o: o.tolist())
    )


if __name__ == "__main__":
    main()
