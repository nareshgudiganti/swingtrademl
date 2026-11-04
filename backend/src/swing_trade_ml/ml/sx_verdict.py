"""SX5 / SX10 mechanical verdict (PROPOSED code; not signed).

Pure module. It reads ONLY the immutable per-arm per-fold records of the research walk-forward harness module
(plain dicts: `arm`, `fold{index,kind}`, `status`, `daily[]`) plus a signed `VerdictParams`, and returns
a deterministic verdict with every intermediate number. No database, no registry import, no file
reads, no clock, no global state. Nothing is chosen after results: every number is in `VerdictParams`.

Call order (documented, enforced by arguments):
  1. `compute_verdict(dev_records, params, ...)` with the development records only.
  2. Only after the holdout registry shows COMPLETED for the run, call again with
     `holdout_completed=True` and `holdout_records` (a list or a zero-argument loader). The holdout
     records are touched only if the outcome depends on R4 AND `holdout_completed` is true.
Spec: docs/superpowers/specs/2026-11-08-sx-verdict-code-spec.md
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

VERDICT_CODE_VERSION = "sx_verdict_v0_PROPOSED"
PRIMARY_ARM = "C_56"
REFERENCE_ARM = "A_53"

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"
PENDING_HOLDOUT = "PENDING_HOLDOUT"  # not a protocol word: dev signals are met, R4 cannot be read yet


class VerdictRefused(RuntimeError):
    """Parameters or inputs are not acceptable: there is NO result (void), never a guessed one."""


# ----------------------------------------------------------------------------------------------- parameters
@dataclass(frozen=True)
class VerdictParams:
    horizon: int  # 5 or 10 sessions
    mde_h: float  # minimum detectable paired edge in return fraction per day (S-9). REQUIRED, no default.
    holm_mode: str = "single_horizon"  # 'single_horizon' (2.5% bound, PROPOSED) or 'two_horizon'
    primary_arm: str = PRIMARY_ARM
    reference_arm: str = REFERENCE_ARM
    burn_in_folds: int = 4  # folds 0..burn_in-1 are reported, never counted; 0 counts all 34
    last_fold_index: int = 33  # 0-based, last development fold
    min_stocks: int = 10  # a day with fewer eligible stocks is left out
    top_k: int = 5
    block_multiple: int = 2  # block = block_multiple x horizon
    draws: int = 2000
    seed: int = 7
    alpha_strict: float = 0.025
    alpha_loose: float = 0.05
    fail_upper_alpha: float = 0.05
    min_eligible_folds: int = 12
    min_picks: int = 100
    min_days_multiple: int = 2  # |T| >= min_days_multiple x horizon
    min_fold_days: int = 10
    min_fold_picks: int = 20
    r1_share: float = 0.6

    def __post_init__(self) -> None:
        m = self.mde_h
        if m is None or isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or m <= 0:
            raise VerdictRefused("MDE_H (S-9) is missing or not a positive number: the verdict refuses to run")
        if self.horizon not in (5, 10):
            raise VerdictRefused("horizon must be 5 or 10")
        if self.holm_mode not in ("single_horizon", "two_horizon"):
            raise VerdictRefused("holm_mode must be 'single_horizon' or 'two_horizon'")
        if self.burn_in_folds < 0 or self.last_fold_index < self.burn_in_folds:
            raise VerdictRefused("burn_in_folds / last_fold_index are inconsistent")
        if self.draws < 100 or self.block_multiple < 1 or self.min_stocks < 1 or self.top_k < 1:
            raise VerdictRefused("draws / block_multiple / min_stocks / top_k out of range")
        if not (0 < self.alpha_strict <= self.alpha_loose < 1) or not (0 < self.fail_upper_alpha < 1):
            raise VerdictRefused("alphas out of range")

    @property
    def block(self) -> int:
        return self.block_multiple * self.horizon

    @property
    def counted_folds(self) -> tuple[int, ...]:
        return tuple(range(self.burn_in_folds, self.last_fold_index + 1))

    def canonical_json(self) -> str:
        d = asdict(self)
        d["code_version"] = VERDICT_CODE_VERSION
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def verdict_code_sha256(path: str | Path | None = None) -> str:
    """sha256 of this module file's bytes with CRLF/CR normalised to LF (so Windows and Linux agree)."""
    raw = Path(path or __file__).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------------------------------- bootstrap
def block_bootstrap_means(values: Sequence[float], block: int, draws: int, seed: int) -> list[float] | None:
    """Same convention as `brain.walk_forward.bootstrap_low`: non-circular runs of `block` consecutive
    days, ceil(n/block) runs per draw, start = rng.randrange(n - block + 1), one `random.Random(seed)`
    for all draws, mean of the picked values, returned SORTED ascending. None if n < max(5, 2*block)."""
    n = len(values)
    if n < max(5, 2 * block):
        return None
    rng = random.Random(seed)
    per_draw = -(-n // block)
    means = []
    for _ in range(draws):
        picked: list[float] = []
        for _ in range(per_draw):
            s = rng.randrange(n - block + 1)
            picked.extend(values[s : s + block])
        means.append(sum(picked) / len(picked))
    means.sort()
    return means


def lower_bound(sorted_means: Sequence[float], alpha: float) -> float:
    """One-sided lower bound at `alpha`: 0-based index floor(alpha x draws) (1-based m(floor+1))."""
    return sorted_means[int(alpha * len(sorted_means))]


def upper_bound(sorted_means: Sequence[float], alpha: float) -> float:
    """One-sided upper bound at `alpha`: 0-based index draws - floor(alpha x draws) - 1 (alpha .05 -> 1899)."""
    d = len(sorted_means)
    return sorted_means[d - int(alpha * d) - 1]


def p_value(sorted_means: Sequence[float]) -> float:
    """(1 + number of resampled means <= 0) / (draws + 1). Small p = the mean is credibly above 0."""
    return (1 + sum(1 for m in sorted_means if m <= 0)) / (len(sorted_means) + 1)


def _interval(values: Sequence[float], block: int, p: VerdictParams, alpha: float) -> dict:
    means = block_bootstrap_means(values, block, p.draws, p.seed)
    if means is None:
        return {"block": block, "computable": False}
    return {
        "block": block,
        "computable": True,
        "lower_at_alpha": lower_bound(means, alpha),
        "alpha": alpha,
        "upper_at_fail_alpha": upper_bound(means, p.fail_upper_alpha),
        "p_value": p_value(means),
    }


# ----------------------------------------------------------------------------------------------- inputs
def _index_records(records: Sequence[Mapping], kind: str, p: VerdictParams) -> dict[tuple[int, str], Mapping]:
    out: dict[tuple[int, str], Mapping] = {}
    for r in records:
        f = r.get("fold") or {}
        if f.get("kind") != kind:
            raise VerdictRefused(f"a record of kind {f.get('kind')!r} was passed as {kind!r}")
        key = (int(f["index"]), str(r["arm"]))
        if key in out:
            raise VerdictRefused(f"duplicate record for fold {key[0]} arm {key[1]}")
        out[key] = r
    return out


def _paired_days(rec_c: Mapping, rec_a: Mapping, p: VerdictParams, fold: int) -> list[tuple[str, float]]:
    dc = {d["date"]: d for d in (rec_c["daily"] or [])}
    da = {d["date"]: d for d in (rec_a["daily"] or [])}
    if set(dc) != set(da):
        raise VerdictRefused(f"fold {fold}: the two arms were evaluated on different days (R0 broken): void")
    out = []
    for date in sorted(dc):
        c, a = dc[date], da[date]
        if c["n_stocks"] != a["n_stocks"]:
            raise VerdictRefused(f"fold {fold} {date}: n_stocks differs between arms (R0 broken): void")
        if c["n_stocks"] < p.min_stocks:
            continue
        xc, xa = c.get("excess_vs_all"), a.get("excess_vs_all")
        if xc is None or xa is None or not math.isfinite(xc) or not math.isfinite(xa):
            raise VerdictRefused(f"fold {fold} {date}: excess_vs_all missing or not finite: void")
        out.append((date, xc - xa))
    return out


def _fold_table(records: Sequence[Mapping], kind: str, indices: Sequence[int] | None, p: VerdictParams):
    """Return (fold rows, flat date-ordered list of (date, D)). One row per fold index present."""
    idx = _index_records(records, kind, p)
    folds = sorted({k[0] for k in idx})
    if indices is not None:
        missing = [i for i in indices if (i, p.primary_arm) not in idx or (i, p.reference_arm) not in idx]
        if missing:
            raise VerdictRefused(f"records missing for counted folds {missing}: void")
        folds = list(indices)
    rows, flat, seen = [], [], set()
    for i in folds:
        rc, ra = idx.get((i, p.primary_arm)), idx.get((i, p.reference_arm))
        if rc is None or ra is None:
            raise VerdictRefused(f"fold {i}: primary or reference arm record missing: void")
        status = rc["status"] if rc["status"] == ra["status"] else "arms_disagree"
        if status == "arms_disagree":
            raise VerdictRefused(f"fold {i}: arms have different status: void")
        row: dict[str, Any] = {
            "fold": i,
            "status": status,
            "days": 0,
            "picks": 0,
            "mean_d": None,
            "eligible": False,
            "win": False,
        }
        if status == "ok":
            days = _paired_days(rc, ra, p, i)
            for date, _ in days:
                if date in seen:
                    raise VerdictRefused(f"date {date} appears in two folds: void")
                seen.add(date)
            picks = sum(
                min(len(d.get("top_symbols") or [None] * p.top_k), p.top_k)
                for d in (rc["daily"] or [])
                if d["n_stocks"] >= p.min_stocks
            )
            row["days"], row["picks"] = len(days), picks
            if days:
                row["mean_d"] = sum(v for _, v in days) / len(days)
            row["eligible"] = len(days) >= p.min_fold_days and picks >= p.min_fold_picks
            row["win"] = bool(row["eligible"] and row["mean_d"] is not None and row["mean_d"] > 0)
            flat.extend(days)
        rows.append(row)
    flat.sort(key=lambda t: t[0])
    return rows, flat


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


# ----------------------------------------------------------------------------------------------- verdict
def compute_verdict(
    dev_records: Sequence[Mapping],
    params: VerdictParams,
    *,
    other_horizon_p: float | None = None,
    holdout_records: Sequence[Mapping] | Callable[[], Sequence[Mapping]] | None = None,
    holdout_completed: bool | Callable[[], bool] = False,
) -> dict:
    """Deterministic verdict. Evaluation order (fixed):
      0 parameters (MDE_H required)  1 inputs (R0, completeness)  2 data sufficiency (R3)
      3 pooled paired series, bootstrap, Holm level (R2)  4 R1  5 FAIL test  6 R4 only if needed and COMPLETED.
    Dev records only unless `holdout_completed` is true AND the outcome depends on R4."""
    p = params
    if p.holm_mode == "two_horizon" and other_horizon_p is None:
        raise VerdictRefused("holm_mode 'two_horizon' needs the other horizon's p-value (other_horizon_p)")
    counted = p.counted_folds
    rows, series = _fold_table(dev_records, "dev", counted, p)
    d_vals = [v for _, v in series]
    n = len(d_vals)
    elig = [r for r in rows if r["eligible"]]
    wins = sum(1 for r in elig if r["win"])
    picks_e = sum(r["picks"] for r in elig)
    need = p.min_days_multiple * p.horizon
    ineligible = [r["fold"] for r in rows if not r["eligible"]]
    data_reasons = []
    if len(elig) < p.min_eligible_folds:
        data_reasons.append(f"eligible counted folds {len(elig)} < {p.min_eligible_folds}")
    if picks_e < p.min_picks:
        data_reasons.append(f"picks {picks_e} < {p.min_picks}")
    if n < need:
        data_reasons.append(f"paired days {n} < {need}")
    if len(rows) != len(counted) or any(r["status"] != "ok" for r in rows):
        data_reasons.append("some counted folds are not status ok")

    mean_d = _mean(d_vals)
    out: dict[str, Any] = {
        "verdict_code_version": VERDICT_CODE_VERSION,
        "params": asdict(p),
        "params_sha256": p.sha256(),
        "counted_folds": list(counted),
        "n_paired_days": n,
        "mean_d": mean_d,
        "folds": rows,
        "ineligible_folds": ineligible,
        "r3": {
            "met": not data_reasons,
            "eligible_folds": len(elig),
            "picks": picks_e,
            "days": n,
            "needed_days": need,
            "reasons": data_reasons,
        },
    }
    # Holm level and p-value (needs the pooled bootstrap, which exists when n >= 2b)
    primary_means = block_bootstrap_means(d_vals, p.block, p.draws, p.seed)
    p_this = p_value(primary_means) if primary_means is not None else None
    alpha, alpha_why = p.alpha_strict, "single_horizon: strict bound (PROPOSED)"
    if p.holm_mode == "two_horizon":
        if p_this is None:
            alpha, alpha_why = p.alpha_strict, "p not computable: strict bound"
        elif p_this < other_horizon_p or (p_this == other_horizon_p and p.horizon == 5):
            alpha, alpha_why = p.alpha_strict, "two_horizon: smaller p (ties: SX5) gets the strict bound"
        else:
            alpha, alpha_why = p.alpha_loose, "two_horizon: larger p gets the loose bound"
    out["holm"] = {
        "mode": p.holm_mode,
        "p_this_horizon": p_this,
        "p_other_horizon": other_horizon_p,
        "alpha": alpha,
        "why": alpha_why,
    }
    if primary_means is not None:
        lo, up = lower_bound(primary_means, alpha), upper_bound(primary_means, p.fail_upper_alpha)
        out["bootstrap"] = {
            "block": p.block,
            "draws": p.draws,
            "seed": p.seed,
            "lower": lo,
            "upper": up,
            "lower_5pct": lower_bound(primary_means, p.alpha_loose),
            "lower_2_5pct": lower_bound(primary_means, p.alpha_strict),
        }
    else:
        lo = up = None
        out["bootstrap"] = {"block": p.block, "computable": False}
    r2 = lo is not None and lo > 0
    need_r1 = math.ceil(round(p.r1_share * len(elig), 9))
    r1 = len(elig) > 0 and wins >= need_r1
    out["r2"] = {"met": r2, "lower_bound": lo, "alpha": alpha}
    out["r1"] = {"met": r1, "wins": wins, "eligible": len(elig), "needed": need_r1}
    out["r5_descriptive"] = {
        "no_weight": True,
        "fold_means": {str(r["fold"]): r["mean_d"] for r in rows},
        "min_fold_mean": min((r["mean_d"] for r in rows if r["mean_d"] is not None), default=None),
        "max_fold_mean": max((r["mean_d"] for r in rows if r["mean_d"] is not None), default=None),
    }
    out["sensitivity_NO_WEIGHT"] = {
        label: _interval(d_vals, b, p, alpha)
        for label, b in (("block_h", p.horizon), ("block_3h", 3 * p.horizon), ("day_iid", 1))
    }

    out["r4"] = {"met": None, "evaluated": False, "note": "holdout not read"}
    mde_straddle = up is not None and up >= p.mde_h
    # ---- outcome, in the fixed order
    if data_reasons:
        outcome, sub = INCONCLUSIVE, "data"
    elif r2 and r1:
        completed = holdout_completed() if callable(holdout_completed) else bool(holdout_completed)
        if not completed:
            outcome, sub = PENDING_HOLDOUT, "dev signals met; holdout not COMPLETED, R4 not read"
        else:
            hrecs = holdout_records() if callable(holdout_records) else holdout_records
            if not hrecs:
                raise VerdictRefused("holdout is COMPLETED but no holdout records were supplied")
            r4 = _r4(hrecs, p, mean_d, alpha)
            out["r4"] = r4
            outcome, sub = (PASS, "R1, R2, R4 met") if r4["met"] else (INCONCLUSIVE, "R4 not met: signals disagree")
    elif not r2 and not mde_straddle:
        outcome, sub = FAIL, "R2 not met and the 5% upper bound is below MDE_H"
    elif not r2:
        outcome, sub = INCONCLUSIVE, "R2 not met and the upper bound is at or above MDE_H"
    else:
        outcome, sub = INCONCLUSIVE, "R2 met but R1 not met: signals disagree"
    out["outcome"], out["outcome_detail"] = outcome, sub
    out["record_sha256"] = hashlib.sha256(_canon(out).encode("utf-8")).hexdigest()
    return out


def _r4(hrecs: Sequence[Mapping], p: VerdictParams, dev_mean: float | None, alpha: float) -> dict:
    rows, series = _fold_table(hrecs, "holdout", None, p)
    vals = [v for _, v in series]
    mean_h = _mean(vals)
    ok_status = bool(rows) and all(r["status"] == "ok" for r in rows)
    met = bool(ok_status and mean_h is not None and mean_h > 0 and dev_mean is not None and dev_mean > 0)
    return {
        "met": met,
        "evaluated": True,
        "holdout_days": len(vals),
        "holdout_mean_d": mean_h,
        "dev_mean_d": dev_mean,
        "all_status_ok": ok_status,
        "interval_reported_no_weight": _interval(vals, p.block, p, alpha),
    }


# ----------------------------------------------------------------------------------------------- rendering
def _canon(obj: Any) -> str:
    body = {k: v for k, v in obj.items() if k != "record_sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def render_json(verdict: Mapping, code_sha256: str | None = None) -> str:
    """Canonical JSON text of the verdict, with the verdict-code hash. Same input -> identical text."""
    rec = {**verdict, "verdict_code_sha256": code_sha256 if code_sha256 is not None else verdict_code_sha256()}
    return json.dumps(rec, sort_keys=True, indent=2)


def render_plain_english(verdict: Mapping) -> str:
    """A short paragraph. It never says a model 'works'; PASS only proposes a separate forward shadow test."""
    p = verdict["params"]
    h, n, o = p["horizon"], verdict["n_paired_days"], verdict["outcome"]
    mean = verdict["mean_d"]
    head = (
        f"{h}-day test, {n} test days counted. The new inputs ranked stocks "
        + (
            f"{mean * 100:+.3f} percentage points per day better than the old ones on average"
            if mean is not None
            else "with no measurable difference (no days)"
        )
        + " (top five picks against the average stock)."
    )
    if o == PASS:
        tail = (
            "All three agreement checks were met. This only proposes a separate, separately signed "
            "forward shadow test. It is not proof, nothing is switched on, and no model is promoted."
        )
    elif o == FAIL:
        tail = (
            "The data were large enough to see an edge of the size we planned for, and the best "
            "estimate stayed below it. Recorded with equal prominence; no promotion and no re-run."
        )
    elif o == PENDING_HOLDOUT:
        tail = "The development checks are met. The final answer waits for the holdout run to be recorded as completed."
    else:
        why = verdict["outcome_detail"]
        tail = (
            f"INCONCLUSIVE ({why}). The test cannot tell no effect from a useful effect, or its "
            "checks disagree. This is not read as 'no effect'; no promotion, no re-run on the same holdout."
        )
    return f"{head} Outcome: {o}. {tail}"


__all__ = [
    "VerdictParams",
    "VerdictRefused",
    "compute_verdict",
    "render_json",
    "render_plain_english",
    "verdict_code_sha256",
    "block_bootstrap_means",
    "lower_bound",
    "upper_bound",
    "p_value",
    "PASS",
    "FAIL",
    "INCONCLUSIVE",
    "PENDING_HOLDOUT",
]
