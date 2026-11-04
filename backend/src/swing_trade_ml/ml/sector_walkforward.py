"""RESEARCH-ONLY walk-forward harness for the sector experiments SX5 and SX10 (harness only: no model recipe).

NOT production. Nothing in the app imports it (a test enforces that). It is isolated from production scoring
(ml/predict.py), the h05 lane, the brain, the strategies and paper orders, and writes nothing to the database.

What it does, and what it refuses
  * Three ARMS on IDENTICAL rows, folds, costs and metrics (owner decision 2026-11-05):
      A_53  the 53 existing inputs (ml/features.FEATURE_COLUMNS)           primary matched baseline
      R_37  model 2's 37-input configuration (a SUBSET of the 53)          separate production-reference benchmark
      C_57  the 53 plus the four sector inputs                              the challenger
  * Chronological, label-purged folds. A training row is used only if its whole label window ends before the
    test window starts (purge) AND its decision day is at least `embargo` sessions before the test start
    (embargo = the horizon). Training is an expanding window, retrained once per fold.
  * The model is NEVER defined here. `fit_fn` is injected by the caller (a stub in tests; the signed protocol's
    recipe later). The harness ships no default recipe.
  * It REFUSES to run unless the approval-file mechanism of sector_research is satisfied for this exact
    `DatasetSpec`; only data that did NOT come from the database may be run without it, and only when the caller
    says `synthetic=True`.
  * The holdout is scored at most once per candidate: a marker file is created (exclusive create) before the first
    holdout fit and a second holdout run is refused, even if the first one crashed.
  * Every (arm, fold) result is an immutable JSON record (exclusive create, read-only) carrying the sha256 of the
    dataset, the row list, the fold definitions, the feature list and the configuration, plus the code version
    string the caller passes in.

Metrics (identical code for every arm; see `evaluate_fold`): daily rank IC, top-5 hit rate, top-5 minus every
eligible stock, top-5 minus random-5 (200 seeded draws), and net-after-costs ONLY through an injected `net_fn`
(None unless the protocol permits it). Nothing here judges by accuracy.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from swing_trade_ml.ml.sector_reconcile import keys_sha256

HARNESS_VERSION = "sector_walkforward_v0"
PINNED_SEED = 42  # the drafts' recipe seed; a real run refuses any other
ARM_A, ARM_R, ARM_C = "A_53", "R_37", "C_57"
ARM_IDS = (ARM_A, ARM_R, ARM_C)

# Folds of the drafts (wf-protocol-v1 windows): 28-day back-to-back tests, then one holdout.
TEST_DAYS = 28
DEV_FIRST_START = date(2023, 7, 1)
DEV_LAST_END = date(2026, 1, 31)
HOLDOUT_START = date(2026, 2, 1)
HOLDOUT_END = date(2026, 8, 15)

TOP_K = 5
MIN_STOCKS = 10  # a day with fewer eligible stocks is left out of every metric (selection_lab.daily_ic rule)
RANDOM_DRAWS = 200
RANDOM_SEED = 7
MIN_TRAIN_ROWS = 100

# Model 2's 37 inputs. DERIVED (not read from the prod artifact): the 37 columns of the very first
# FEATURE_COLUMNS (git 7da460c^), which equal the 53 minus the 16 inputs that docs/superpowers/specs/
# 2026-10-30-model-facts-corrections.md (C1) says the large-cap model lacks. The count agrees (53 - 16 = 37).
# The exact saved list is UNVERIFIED without reading the prod model row: pass `reference_columns=` to override.
_NOT_IN_MODEL_2 = frozenset(
    {
        "days_since_52w_high",
        "days_since_52w_low",
        "streak",
        "volatility_percentile_rank",
        "cmf_20",
        "relative_strength_5d",
        "relative_strength_20d",
        "nifty_volatility_20",
        "nifty_trend_regime",
        "sector_relative_strength_5d",
        "sector_relative_strength_20d",
        "sector_trend_regime",
        "vix_change_5d",
        "vix_percentile_rank",
        "breadth_pct_above_sma50",
        "breadth_advance_pct",
    }
)
REFERENCE_37_COLUMNS: tuple[str, ...] = tuple(c for c in FEATURE_COLUMNS if c not in _NOT_IN_MODEL_2)

FitFn = Callable[..., Callable[[pd.DataFrame], np.ndarray]]
NetFn = Callable[[str, date], "float | None"]


class HarnessRefused(RuntimeError):
    """A rule of the harness stopped the run before any model was fitted."""


class HoldoutAlreadyUsed(HarnessRefused):
    """The holdout of this candidate was already scored (or started): it is scored once."""


class ArmMismatch(RuntimeError):
    """The arms did not receive identical rows or folds (a bug: never ignored)."""


# ---------------------------------------------------------------------------------------------------- folds
@dataclass(frozen=True)
class Fold:
    index: int
    kind: str  # "dev" | "holdout"
    cutoff: date  # last day before the test window
    test_start: date
    test_end: date


def make_folds(first_start: date, last_end: date, test_days: int = TEST_DAYS) -> list[Fold]:
    """Back-to-back calendar test windows (the same windows as brain/selection_lab.make_folds; a test compares
    them). A window past `last_end` is cut short; one under a week is dropped."""
    out: list[Fold] = []
    start, i = first_start, 0
    while start <= last_end:
        end = min(start + timedelta(days=test_days - 1), last_end)
        if (end - start).days >= 6:
            out.append(Fold(i, "dev", start - timedelta(days=1), start, end))
            i += 1
        start += timedelta(days=test_days)
    return out


def default_folds(include_holdout: bool = False) -> list[Fold]:
    folds = make_folds(DEV_FIRST_START, DEV_LAST_END)
    if include_holdout:
        folds.append(
            Fold(len(folds), "holdout", HOLDOUT_START - timedelta(days=1), HOLDOUT_START, HOLDOUT_END)
        )
    return folds


def label_end_dates(matrix: pd.DataFrame) -> pd.Series:
    """IST calendar date of the bar that closes each row's label window."""
    return sr._ist_date(matrix["label_end_ts"])


@dataclass(frozen=True)
class Split:
    train: pd.Index
    test: pd.Index
    n_purged_overlap: int  # decision before the test start, label window reaching into it
    n_embargo_removed: int  # clear of the test window, but inside the embargo


def split_for_fold(matrix: pd.DataFrame, fold: Fold, embargo: int) -> Split:
    """Train/test row positions of one fold.

    test  = decision day inside [test_start, test_end].
    train = decision day < test_start AND label window ended < test_start (purge: no overlap with the test
            window) AND decision day not among the last `embargo` sessions before test_start (embargo).
    A session is a distinct decision day of the panel."""
    dd, le = matrix["decision_date"], label_end_dates(matrix)
    ts, te = pd.Timestamp(fold.test_start), pd.Timestamp(fold.test_end)
    test = (dd >= ts) & (dd <= te)
    before = dd < ts
    overlap = before & (le >= ts)
    cal = np.sort(dd[before].unique())
    if embargo > 0 and len(cal):
        keep_until = cal[-embargo - 1] if len(cal) > embargo else None
        embargoed = before & ~overlap & ((dd > keep_until) if keep_until is not None else True)
    else:
        embargoed = pd.Series(False, index=matrix.index)
    train = before & ~overlap & ~embargoed
    return Split(matrix.index[train], matrix.index[test], int(overlap.sum()), int(embargoed.sum()))


def inner_chronological_split(
    meta: pd.DataFrame, test_size: float, embargo: int
) -> tuple[pd.Index, pd.Index]:
    """Helper for a fit_fn that holds out the last `test_size` of its training days as an internal check (as
    ml/dataset.chronological_split does). Cut on a day boundary; training rows whose label window reaches the
    internal-check window, or lie within `embargo` sessions of it, are dropped. `meta` has decision_date and
    label_end_date."""
    days = np.sort(meta["decision_date"].unique())
    if len(days) < 2:
        return meta.index[:0], meta.index[:0]
    cut = days[min(len(days) - 1, max(1, int(len(days) * (1 - test_size))))]
    inner_test = meta["decision_date"] >= cut
    before_days = days[days < cut]
    last_ok = before_days[-embargo - 1] if embargo > 0 and len(before_days) > embargo else None
    ok = (meta["decision_date"] < cut) & (meta["label_end_date"] < cut)
    if embargo > 0:
        ok &= (meta["decision_date"] <= last_ok) if last_ok is not None else False
    return meta.index[ok], meta.index[inner_test]


def folds_sha256(folds: Sequence[Fold], embargo: int, horizon: int) -> str:
    body = {
        "harness": HARNESS_VERSION,
        "embargo_sessions": embargo,
        "horizon": horizon,
        "rule": "train: decision<test_start, label_end<test_start, decision not in last `embargo` sessions",
        "folds": [
            {k: (v.isoformat() if isinstance(v, date) else v) for k, v in asdict(f).items()} for f in folds
        ],
    }
    return _sha(body)


# ------------------------------------------------------------------------------------------------------ arms
def build_arms(reference_columns: Sequence[str] = REFERENCE_37_COLUMNS) -> dict[str, tuple[str, ...]]:
    ref = tuple(reference_columns)
    if not set(ref) <= set(FEATURE_COLUMNS) or len(set(ref)) != len(ref):
        raise HarnessRefused("R_37 must be distinct columns, all among the 53 existing inputs")
    return {ARM_A: tuple(FEATURE_COLUMNS), ARM_R: ref, ARM_C: tuple(sr.RESEARCH_COLUMNS)}


def _check_arms(arms: Mapping[str, Sequence[str]]) -> None:
    if set(arms) != set(ARM_IDS):
        raise HarnessRefused(f"arms must be exactly {list(ARM_IDS)}")
    if tuple(arms[ARM_A]) != tuple(FEATURE_COLUMNS):
        raise HarnessRefused("A_53 must be exactly the 53 existing inputs")
    if tuple(arms[ARM_C]) != tuple(sr.RESEARCH_COLUMNS):
        raise HarnessRefused("C_57 must be the 53 existing inputs plus the four sector inputs")
    if not set(arms[ARM_R]) <= set(arms[ARM_A]):
        raise HarnessRefused("R_37 must be a subset of the 53")


def feature_list_sha256(columns: Sequence[str]) -> str:
    return _sha(list(columns))


# --------------------------------------------------------------------------------------------------- metrics
def _day_metrics(g: pd.DataFrame, top_k: int, draws: int, net_fn: NetFn | None) -> dict:
    g = g.sort_values(["symbol"], kind="mergesort")  # deterministic order, then rank by score
    top = g.sort_values("score", ascending=False, kind="mergesort").head(top_k)
    ret = g["forward_return"].to_numpy("float64")
    s, r = g["score"], g["forward_return"]
    ic = None
    if s.nunique() >= 2 and r.nunique() >= 2:
        v = float(s.rank().corr(r.rank()))
        ic = v if np.isfinite(v) else None
    day = g["decision_date"].iloc[0]
    rng = np.random.default_rng([RANDOM_SEED, int(pd.Timestamp(day).toordinal())])
    k = min(top_k, len(g))
    pick = np.stack([rng.choice(len(g), size=k, replace=False) for _ in range(draws)])
    top_ret, all_ret = float(top["forward_return"].mean()), float(ret.mean())
    rand_ret = float(ret[pick].mean())
    out = {
        "date": pd.Timestamp(day).date().isoformat(),
        "n_stocks": int(len(g)),
        "ic": ic,
        "top_symbols": [str(x) for x in top["symbol"]],
        "top_hit": float(top["target"].mean()),
        "all_hit": float(g["target"].mean()),
        "top_return": top_ret,
        "all_return": all_ret,
        "random_return": rand_ret,
        "excess_vs_all": top_ret - all_ret,
        "excess_vs_random": top_ret - rand_ret,
        "net_top": None,
        "net_all": None,
        "net_excess_vs_all": None,
    }
    if net_fn is not None:
        d = pd.Timestamp(day).date()
        nt = [net_fn(str(sym), d) for sym in top["symbol"]]
        na = [net_fn(str(sym), d) for sym in g["symbol"]]
        nt, na = [x for x in nt if x is not None], [x for x in na if x is not None]
        if nt and na:
            out["net_top"], out["net_all"] = float(np.mean(nt)), float(np.mean(na))
            out["net_excess_vs_all"] = out["net_top"] - out["net_all"]
    return out


def _mean(xs: Sequence) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(np.mean(xs)) if xs else None


def evaluate_fold(
    test: pd.DataFrame,
    *,
    top_k: int = TOP_K,
    min_stocks: int = MIN_STOCKS,
    draws: int = RANDOM_DRAWS,
    net_fn: NetFn | None = None,
) -> tuple[dict, list[dict]]:
    """`test` has symbol, decision_date, score, forward_return, target. Same code for every arm.
    Returns (fold aggregates, per-day rows)."""
    daily = []
    for _, g in test.groupby("decision_date", sort=True):
        if len(g) >= min_stocks:
            daily.append(_day_metrics(g, top_k, draws, net_fn))
    agg = {
        "n_days": len(daily),
        "n_ideas": int(sum(len(d["top_symbols"]) for d in daily)),
        "mean_ic": _mean([d["ic"] for d in daily]),
        "top_hit_rate": _mean([d["top_hit"] for d in daily]),
        "all_hit_rate": _mean([d["all_hit"] for d in daily]),
        "mean_top_return": _mean([d["top_return"] for d in daily]),
        "mean_excess_vs_all": _mean([d["excess_vs_all"] for d in daily]),
        "mean_excess_vs_random": _mean([d["excess_vs_random"] for d in daily]),
        "mean_net_top": _mean([d["net_top"] for d in daily]),
        "mean_net_excess_vs_all": _mean([d["net_excess_vs_all"] for d in daily]),
        "net_after_costs": "reported" if net_fn is not None else "not permitted / no net_fn supplied",
    }
    return agg, daily


# ------------------------------------------------------------------------------------------------- plumbing
def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _keys(df: pd.DataFrame) -> list[str]:
    return (df["symbol"] + "|" + df["decision_date"].dt.strftime("%Y-%m-%d")).tolist()


def rows_sha256(df: pd.DataFrame) -> str:
    """The canonical row-list hash (sector_reconcile.keys_sha256): sorted SYMBOL|YYYY-MM-DD, newline separated."""
    return keys_sha256(_keys(df))


def _scores_sha256(scores: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(scores, dtype="<f8").tobytes()).hexdigest()


def _validate_matrix(spec: sr.DatasetSpec, matrix: pd.DataFrame) -> None:
    need = {*sr.RESEARCH_COLUMNS, "target", "forward_return", "label_end_ts", "symbol", "decision_date"}
    miss = need - set(matrix.columns)
    if miss:
        raise HarnessRefused(f"matrix lacks columns {sorted(miss)}")
    if matrix.empty:
        raise HarnessRefused("empty matrix")
    if (
        matrix[list(sr.RESEARCH_COLUMNS)].isna().to_numpy().any()
        or matrix[["target", "forward_return"]].isna().to_numpy().any()
    ):
        raise HarnessRefused("the eligible rows must have all 57 inputs, the label and the forward return")
    if matrix.duplicated(["symbol", "decision_date"]).any():
        raise HarnessRefused("duplicate (symbol, decision_date) rows")
    if not matrix.index.equals(pd.RangeIndex(len(matrix))):
        raise HarnessRefused("matrix must have a fresh RangeIndex (use assemble_training_matrix output)")


def _guard(spec, matrix, *, synthetic, seed, approval_path, code_version) -> str:
    if not isinstance(code_version, str) or not code_version.strip():
        raise HarnessRefused("code_version (a git commit string) is required")
    from_db = matrix.attrs.get("inputs_source") == "database"
    if synthetic:
        if from_db:
            raise HarnessRefused("synthetic=True refused: this matrix was built from database data")
        return "synthetic (no approval needed, nothing real is touched)"
    ok, why = sr._approval_valid(spec, approval_path)
    if not ok:
        raise sr.ResearchApprovalRequired(why)
    if seed != PINNED_SEED:
        raise HarnessRefused(f"seed must be {PINNED_SEED} on a real run, got {seed}")
    return why


def _marker_path(marker_dir: Path, candidate: str) -> Path:
    return marker_dir / f"{candidate}.holdout_used.json"


def write_immutable_json(path: Path, obj: dict) -> None:
    """Exclusive create (never overwrites), then read-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=1, sort_keys=True))
    os.chmod(path, stat.S_IREAD)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_dir: Path
    manifest: dict
    records: tuple[dict, ...]


def _seal(body: dict) -> dict:
    return {**body, "record_sha256": _sha(body)}


def run_walkforward(
    spec: sr.DatasetSpec,
    matrix: pd.DataFrame,
    *,
    fit_fn: FitFn,
    code_version: str,
    reference_columns: Sequence[str] = REFERENCE_37_COLUMNS,
    seed: int = PINNED_SEED,
    folds: Sequence[Fold] | None = None,
    include_holdout: bool = False,
    out_root: str | Path | None = None,
    marker_dir: str | Path | None = None,
    approval_path: str | Path | None = None,
    synthetic: bool = False,
    net_fn: NetFn | None = None,
    embargo: int | None = None,
    min_train_rows: int = MIN_TRAIN_ROWS,
) -> RunResult:
    """Run all three arms over all folds and write one immutable record per (arm, fold).

    `fit_fn(X, y, meta, *, seed) -> predict` where X holds ONLY the arm's columns, y the label, meta has
    symbol / decision_date / label_end_date; `predict(X_test) -> 1-D scores`."""
    _validate_matrix(spec, matrix)
    approval = _guard(
        spec, matrix, synthetic=synthetic, seed=seed, approval_path=approval_path, code_version=code_version
    )
    arms = build_arms(reference_columns)
    _check_arms(arms)
    root = sr._check_out_root(Path(out_root) if out_root else sr.RESEARCH_ROOT / "walkforward")
    markers = Path(marker_dir) if marker_dir else root / "_holdout_markers"
    embargo = spec.horizon_days if embargo is None else embargo
    fold_list = list(folds) if folds is not None else default_folds(include_holdout)
    has_holdout = any(f.kind == "holdout" for f in fold_list)
    if has_holdout and _marker_path(markers, spec.candidate).exists():
        raise HoldoutAlreadyUsed(
            f"{spec.candidate}: the holdout was already used (marker exists); it is scored once"
        )

    matrix = matrix.copy()
    matrix["label_end_date"] = label_end_dates(matrix)
    ds_sha, all_rows_sha = sr.matrix_sha256(matrix), rows_sha256(matrix)
    fold_sha = folds_sha256(fold_list, embargo, spec.horizon_days)
    harness_cfg = {
        "harness": HARNESS_VERSION,
        "top_k": TOP_K,
        "min_stocks": MIN_STOCKS,
        "random_draws": RANDOM_DRAWS,
        "random_seed": RANDOM_SEED,
        "min_train_rows": min_train_rows,
        "embargo": embargo,
        "seed": seed,
        "net_fn": net_fn is not None,
    }
    harness_cfg_sha = _sha(harness_cfg)
    common = {
        "schema": "sector_walkforward_record_v1",
        "harness_version": HARNESS_VERSION,
        "candidate": spec.candidate,
        "dataset_sha256": ds_sha,
        "rows_sha256": all_rows_sha,
        "fold_definition_sha256": fold_sha,
        "code_version": code_version,
        "config_sha256": spec.config_sha256(),
        "harness_config_sha256": harness_cfg_sha,
        "seed": seed,
        "synthetic": bool(synthetic),
    }
    run_id = _sha({**common, "arms": {a: feature_list_sha256(c) for a, c in arms.items()}})[:16]
    run_dir = root / spec.candidate / f"run_{run_id}"
    if run_dir.exists():
        raise HarnessRefused(f"{run_dir.name} already exists: records are immutable, never overwritten")

    records: list[dict] = []
    marker_written = False
    for fold in fold_list:
        sp = split_for_fold(matrix, fold, embargo)
        if fold.kind == "holdout" and not marker_written:
            write_immutable_json(
                _marker_path(markers, spec.candidate),
                {
                    "candidate": spec.candidate,
                    "run_id": run_id,
                    "dataset_sha256": ds_sha,
                    "config_sha256": spec.config_sha256(),
                    "code_version": code_version,
                    "note": "holdout started; scored once. A crash does not reset this: the owner decides.",
                },
            )
            marker_written = True
        train_all, test_df = matrix.loc[sp.train], matrix.loc[sp.test]
        fold_info = {
            "index": fold.index,
            "kind": fold.kind,
            "cutoff": fold.cutoff.isoformat(),
            "test_start": fold.test_start.isoformat(),
            "test_end": fold.test_end.isoformat(),
        }
        split_info = {
            "n_train": int(len(train_all)),
            "n_test": int(len(test_df)),
            "n_purged_overlap": sp.n_purged_overlap,
            "n_embargo_removed": sp.n_embargo_removed,
            "last_train_decision_date": (
                train_all["decision_date"].max().date().isoformat() if len(train_all) else None
            ),
            "train_rows_sha256": rows_sha256(train_all) if len(train_all) else None,
            "test_rows_sha256": rows_sha256(test_df) if len(test_df) else None,
            "train_label_rate": float(train_all["target"].mean()) if len(train_all) else None,
        }
        status = "ok"
        if len(test_df) == 0:
            status = "skipped_no_test_rows"
        elif len(train_all) < min_train_rows or train_all["target"].nunique() < 2:
            status = "skipped_not_enough_training_rows"
        for arm in ARM_IDS:
            cols = list(arms[arm])
            body = {
                **common,
                "arm": arm,
                "fold": fold_info,
                "status": status,
                **split_info,
                "feature_count": len(cols),
                "feature_list_sha256": feature_list_sha256(cols),
                "approval": approval,
                "metrics": None,
                "daily": None,
                "predictions_sha256": None,
            }
            if status == "ok":
                meta = train_all[["symbol", "decision_date", "label_end_date"]]
                predict = fit_fn(train_all[cols], train_all["target"], meta, seed=seed)
                scores = np.asarray(predict(test_df[cols]), dtype="float64")
                if scores.shape != (len(test_df),) or not np.isfinite(scores).all():
                    raise HarnessRefused(
                        f"{arm} fold {fold.index}: predict must return one finite score per test row"
                    )
                scored = test_df[["symbol", "decision_date", "forward_return", "target"]].assign(score=scores)
                body["metrics"], body["daily"] = evaluate_fold(scored, net_fn=net_fn)
                body["predictions_sha256"] = _scores_sha256(scores)
            records.append(_seal(body))
    assert_identical_across_arms(records)

    manifest = {
        **common,
        "run_id": run_id,
        "arms": {
            a: {"columns": list(c), "feature_list_sha256": feature_list_sha256(c)} for a, c in arms.items()
        },
        "folds": [fold_sha, len(fold_list)],
        "n_records": len(records),
        "approval": approval,
        "holdout_included": has_holdout,
    }
    for rec in records:
        f = rec["fold"]
        write_immutable_json(run_dir / f"{f['kind']}_{f['index']:03d}_{rec['arm']}.json", rec)
    write_immutable_json(run_dir / "manifest.json", _seal(manifest))
    return RunResult(run_id, run_dir, manifest, tuple(records))


def plan_folds(
    matrix: pd.DataFrame,
    folds: Sequence[Fold],
    embargo: int,
    reference_columns: Sequence[str] = REFERENCE_37_COLUMNS,
    top_k: int = TOP_K,
    min_stocks: int = MIN_STOCKS,
) -> list[dict]:
    """Row counts per fold and per arm. NO model, NO fit_fn, NO scores, NO writes: it only applies the split rule,
    so it can show that the three arms get identical rows before anything is approved. Every arm of a fold has
    the same n_train / n_test / n_days; only the number of input columns differs."""
    arms = build_arms(reference_columns)
    dd = matrix["decision_date"]
    out = []
    for f in folds:
        sp = split_for_fold(matrix, f, embargo)
        test = matrix.loc[sp.test]
        day_n = test.groupby("decision_date").size()
        days = int((day_n >= min_stocks).sum())
        out.append(
            {
                "index": f.index,
                "kind": f.kind,
                "test_start": f.test_start.isoformat(),
                "test_end": f.test_end.isoformat(),
                "n_train": int(len(sp.train)),
                "n_test": int(len(sp.test)),
                "test_days": int(day_n.shape[0]),
                "days_with_enough_stocks": days,
                "max_ideas": days * top_k,
                "n_purged_overlap": sp.n_purged_overlap,
                "n_embargo_removed": sp.n_embargo_removed,
                "arms": {
                    a: {"rows_train": int(len(sp.train)), "rows_test": int(len(sp.test)), "columns": len(c)}
                    for a, c in arms.items()
                },
                "rows_available_before_test": int((dd < pd.Timestamp(f.test_start)).sum()),
            }
        )
    return out


def assert_identical_across_arms(records: Sequence[dict]) -> None:
    """Every arm of a fold must have been given the same train rows, test rows, folds and days."""
    by_fold: dict[tuple, list[dict]] = {}
    for r in records:
        by_fold.setdefault((r["fold"]["kind"], r["fold"]["index"]), []).append(r)
    keys = (
        "rows_sha256",
        "dataset_sha256",
        "fold_definition_sha256",
        "harness_config_sha256",
        "config_sha256",
        "train_rows_sha256",
        "test_rows_sha256",
        "n_train",
        "n_test",
        "status",
        "last_train_decision_date",
        "n_purged_overlap",
        "n_embargo_removed",
        "train_label_rate",
        "code_version",
    )
    for fk, rs in by_fold.items():
        if sorted(r["arm"] for r in rs) != sorted(ARM_IDS):
            raise ArmMismatch(f"fold {fk}: arms present {[r['arm'] for r in rs]}")
        for k in keys:
            if len({json.dumps(r[k], sort_keys=True) for r in rs}) != 1:
                raise ArmMismatch(f"fold {fk}: arms differ in {k}")
        days = {json.dumps([(d["date"], d["n_stocks"]) for d in (r["daily"] or [])]) for r in rs}
        if len(days) != 1:
            raise ArmMismatch(f"fold {fk}: arms were evaluated on different days")


__all__ = [
    "ARM_IDS",
    "REFERENCE_37_COLUMNS",
    "Fold",
    "HarnessRefused",
    "HoldoutAlreadyUsed",
    "ArmMismatch",
    "make_folds",
    "default_folds",
    "split_for_fold",
    "run_walkforward",
    "evaluate_fold",
    "build_arms",
    "assert_identical_across_arms",
    "plan_folds",
    "rows_sha256",
    "inner_chronological_split",
]
