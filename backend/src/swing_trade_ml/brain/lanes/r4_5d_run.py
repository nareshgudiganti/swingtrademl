# backend/src/swing_trade_ml/brain/lanes/r4_5d_run.py
# ruff: noqa: E501, N812
"""Runner for the #219 R4 research run. Reads the LOCAL dev database through a read-only session; writes only to a
local output folder (gitignored). Never registers, activates or deploys a model; never writes to any database.

    python -m swing_trade_ml.brain.lanes.r4_5d_run fingerprint            # before training: print the fingerprints
    python -m swing_trade_ml.brain.lanes.r4_5d_run run --out DIR --prereg FILE --model2 FILE

The database URL comes from the environment variable R219_DATABASE_URL (never printed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import r4_5d as X

IST = ZoneInfo("Asia/Kolkata")
FINISHED = {"target", "stop", "expiry"}
CODE_FILES = ("brain/lanes/r4_5d.py", "brain/lanes/r4_5d_run.py")
PACKAGE = Path(__file__).resolve().parents[2]


def code_sha256() -> dict[str, str]:
    return {
        rel: hashlib.sha256((PACKAGE / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for rel in CODE_FILES
    }


# ------------------------------------------------------------------ loading (read-only)


def readonly_session(url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    return Session(engine)


def _day(ts) -> date:
    return pd.Timestamp(ts).tz_convert(IST).date() if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts).date()


@dataclass
class Inputs:
    sessions: list[date]
    candles: dict[str, pd.DataFrame]
    index_df: pd.DataFrame
    vix_df: pd.DataFrame
    breadth_df: pd.DataFrame
    sector_of: dict[str, str]
    sector_dfs: dict[str, pd.DataFrame]
    missing: list[str] = field(default_factory=list)

    def frames(self) -> dict[str, pd.DataFrame]:
        out = {f"stock:{s}": f for s, f in self.candles.items()}
        out |= {f"sector:{s}": f for s, f in self.sector_dfs.items()}
        out |= {"index": self.index_df, "vix": self.vix_df, "breadth": self.breadth_df}
        out["sector_map"] = pd.DataFrame(sorted(self.sector_of.items()), columns=["symbol", "sector"])
        return out


def load_inputs(db) -> Inputs:
    from sqlalchemy import select

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.dataset import load_candles
    from swing_trade_ml.ml.market_context import (
        load_index_candles,
        load_market_breadth,
        load_sector_candles,
        load_vix_candles,
    )
    from swing_trade_ml.ml.sector_map import get_sector_index

    index_df = load_index_candles(db, "day")
    sessions = sorted({_day(t) for t in index_df["ts"]})
    candles, missing, sector_of, sector_dfs = {}, [], {}, {}
    for sym in X.UNIVERSE:
        inst = db.execute(select(Instrument).where(Instrument.tradingsymbol == sym)).scalars().first()
        if inst is None:
            missing.append(sym)
            continue
        candles[sym] = load_candles(db, inst.id, "day")
        sector_of[sym] = get_sector_index(sym)
        if sector_of[sym] not in sector_dfs:
            sector_dfs[sector_of[sym]] = load_sector_candles(db, sector_of[sym], "day")
    inputs = Inputs(
        sessions,
        candles,
        index_df,
        load_vix_candles(db, "day"),
        load_market_breadth(db, "day"),
        sector_of,
        sector_dfs,
        missing,
    )
    db.rollback()
    return inputs


# ------------------------------------------------------------------ panel


@dataclass
class Stock:
    features: pd.DataFrame  # index = IST day, columns = FEATURE_NAMES
    bars: dict[date, tuple[float, float, float, float]]
    closes: dict[date, float]
    nbars: dict[date, int]


def build_panel(inp: Inputs) -> dict[str, Stock]:
    panel = {}
    for sym, df in inp.candles.items():
        if df.empty:
            continue
        feat = X.research_features(
            df, inp.index_df, inp.sector_dfs[inp.sector_of[sym]], inp.vix_df, inp.breadth_df
        )
        days = [_day(t) for t in df["ts"]]
        feat.index = days
        o, h, lo, c = (df[k].astype(float).to_numpy() for k in ("open", "high", "low", "close"))
        bars = {d: (o[i], h[i], lo[i], c[i]) for i, d in enumerate(days)}
        panel[sym] = Stock(
            feat[list(X.FEATURE_NAMES)].astype(float),
            bars,
            {d: b[3] for d, b in bars.items()},
            {d: i + 1 for i, d in enumerate(days)},
        )
    return panel


def eligible(stock: Stock, day: date) -> bool:
    if day not in stock.bars or stock.nbars[day] < X.MIN_BARS:
        return False
    return bool(np.isfinite(stock.features.loc[day].to_numpy()).all())


def pools_for(panel: dict[str, Stock], days: Sequence[date]) -> dict[date, list[str]]:
    return {d: sorted(s for s, st in panel.items() if eligible(st, d)) for d in days}


def outcomes_for(panel, sessions, pools) -> dict[tuple[date, str], X.Outcome]:
    out = {}
    for d, syms in pools.items():
        for s in syms:
            st = panel[s]
            t = R.simulate_trade(st.bars, sessions, d, st.closes[d], X.GROUP)
            ts = R.simulate_trade(st.bars, sessions, d, st.closes[d], X.GROUP, stress=True)
            out[(d, s)] = X.Outcome(
                t.net_return if t.status in FINISHED else None,
                ts.net_return if ts.status in FINISHED else None,
                X.endpoint_label(st.closes, sessions, d),
                tuple(t.flags) + ((t.status,) if t.status not in FINISHED else ()),
            )
    return out


def training_frame(panel, sessions, last_idx: int) -> pd.DataFrame:
    """Every labelled, fully-finite row with signal index <= last_idx, sorted by (day, symbol)."""
    allowed = set(sessions[: last_idx + 1])
    rows = []
    for sym in sorted(panel):
        st = panel[sym]
        f = st.features[st.features.index.isin(allowed)]
        f = f[np.isfinite(f.to_numpy()).all(axis=1)]
        f = f[[st.nbars[d] >= X.MIN_BARS for d in f.index]]
        labels = [X.endpoint_label(st.closes, sessions, d) for d in f.index]
        f = f.assign(target=labels, symbol=sym, day=list(f.index))
        rows.append(f[f["target"].notna()])
    frame = (
        pd.concat(rows, ignore_index=True)
        .sort_values(["day", "symbol"], kind="mergesort")
        .reset_index(drop=True)
    )
    frame["target"] = frame["target"].astype(int)
    frame["ts"] = pd.to_datetime(frame["day"])
    return frame


def score_rows(panel, pools, days, names, fn) -> dict[date, dict[str, float]]:
    out = {}
    for d in days:
        syms = pools[d]
        if not syms:
            out[d] = {}
            continue
        x = np.vstack([panel[s].features.loc[d, list(names)].to_numpy(dtype=np.float64) for s in syms])
        out[d] = dict(zip(syms, map(float, fn(x)), strict=True))
    return out


# ------------------------------------------------------------------ evaluation of one window


def _auc(scores: dict[date, dict[str, float]], outcomes) -> float | None:
    from sklearn.metrics import roc_auc_score

    ys, ps = [], []
    for d, row in scores.items():
        for s, p in row.items():
            lab = outcomes[(d, s)].label
            if lab is not None:
                ys.append(lab)
                ps.append(p)
    return float(roc_auc_score(ys, ps)) if len(set(ys)) == 2 else None


def _r(rng):
    return None if rng is None else [round(rng[0], 6), round(rng[1], 6)]


def summarise(res: dict[str, Any]) -> dict[str, Any]:
    dec = X.run_verdict(res)
    rand = R.random_k_distribution(res["random_pools"])
    pick_mean = X.safe_mean(res["picks_net"])
    return {
        "matured_days": res["matured_days"],
        "counted_picks": res["counted_picks"],
        "unresolved_counted": res["unresolved_counted"],
        "flagged_counted": res["flagged_counted"],
        "blocked_repeats": res["blocked_repeats"],
        "shortfall_day_share": round(res["shortfall_day_share"], 4),
        "selection": dec["selection"]["verdict"],
        "selection_range": _r(dec["selection"].get("range")),
        "label_veto": dec["selection"].get("label_veto", False),
        "economic": dec["economic"]["verdict"],
        "economic_range": _r(dec["economic"].get("range")),
        "why": dec["why"],
        "unresolved_warning": dec["unresolved_warning"],
        "mean_picks_net": pick_mean,
        "mean_pool_net": X.safe_mean(res["pool_net"]),
        "mean_trade_edge": X.safe_mean(res["trade_edge"]),
        "mean_label_edge": X.safe_mean(res["label_edge"]),
        "stress_mean_picks_net": X.safe_mean(res["picks_net_stress"]),
        "stress_range": _r(X.block_range(res["picks_net_stress"])),
        "random5_mean": X.safe_mean(rand),
        "random5_share_at_or_above_picks": None
        if pick_mean is None
        else sum(v >= pick_mean for v in rand) / len(rand),
    }


def evaluate_window(name, runs, sessions, panel, pools, outcomes, scorers) -> dict[str, Any]:
    """scorers: {cid: fn(run_index, run_days) -> {day: {sym: score}}}. Returns per-candidate per-run and combined."""
    out: dict[str, Any] = {"runs": [[r[0].isoformat(), r[-1].isoformat()] for r in runs], "candidates": {}}
    daily: dict[str, dict[date, float]] = {}
    for cid, scorer in scorers.items():
        per_run, pooled = [], {k: [] for k in ("trade_edge", "picks_net", "picks_net_stress", "label_edge")}
        daily[cid] = {}
        all_scores: dict[date, dict[str, float]] = {}
        for k, days in enumerate(runs):
            scores = scorer(k, days)
            all_scores |= scores
            picks = {d: X.top_k(scores[d])[0] for d in days}
            res = X.evaluate_run(days, sessions, {d: pools[d] for d in days}, picks, outcomes)
            s = summarise(res)
            s["auc"] = None if cid == "MOM" else _auc(scores, outcomes)
            per_run.append(s)
            for key in pooled:
                pooled[key].extend(res[key])
            daily[cid] |= dict(zip(res["days"], res["picks_net"], strict=True))
        out["candidates"][cid] = {
            "per_run": per_run,
            "combined": {
                "selection": X.combine_runs([r["selection"] for r in per_run], pooled["trade_edge"]),
                "economic": X.combine_runs([r["economic"] for r in per_run], pooled["picks_net"]),
            },
            "pooled": {
                "days": len(pooled["picks_net"]),
                "mean_picks_net": X.safe_mean(pooled["picks_net"]),
                "picks_net_range": _r(X.block_range(pooled["picks_net"])),
                "mean_trade_edge": X.safe_mean(pooled["trade_edge"]),
                "trade_edge_range": _r(X.block_range(pooled["trade_edge"])),
                "mean_label_edge": X.safe_mean(pooled["label_edge"]),
                "label_edge_range": _r(X.block_range(pooled["label_edge"])),
                "stress_mean_picks_net": X.safe_mean(pooled["picks_net_stress"]),
                "stress_range": _r(X.block_range(pooled["picks_net_stress"])),
                "auc": None if cid == "MOM" else _auc(all_scores, outcomes),
            },
        }
        for c in out["candidates"][cid]["combined"].values():
            c["pooled_range"] = _r(c.get("pooled_range"))
    comparisons = {}
    for cid in daily:
        for ref in ("MOM", "C1"):
            if cid != ref and ref in daily:
                diff = X.paired_difference(daily[cid], daily[ref])
                comparisons[f"{cid}_minus_{ref}"] = {
                    "days": len(diff),
                    "mean": X.safe_mean(diff),
                    "range": _r(X.block_range(diff)),
                }
    out["comparisons"] = comparisons
    return out


# ------------------------------------------------------------------ the experiment


def fingerprints(inp: Inputs) -> dict[str, Any]:
    return {
        "experiment": X.EXPERIMENT,
        "feature_set": X.feature_set_fingerprint(),
        "config_sha256": {cid: X.config_fingerprint(cid) for cid in X.CANDIDATES},
        "data_snapshot_sha256": X.snapshot_sha256(inp.frames()),
        "code_sha256": code_sha256(),
        "universe_sha256": X.COMMON["universe_sha256"],
        "rule_sha256": X.COMMON["rule_sha256"],
        "newest_session": inp.sessions[-1].isoformat(),
        "missing_symbols": inp.missing,
    }


def _load_model2(path: Path) -> dict:
    import joblib

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if sha != X.CANDIDATES["C1"]["artifact_sha256"]:
        raise SystemExit("model 2 artifact sha256 differs from the frozen hash")
    return joblib.load(path)


def run(inp: Inputs, out_dir: Path, model2_path: Path) -> dict[str, Any]:
    import joblib

    from swing_trade_ml.ml import model_card

    fps = fingerprints(inp)
    sessions = inp.sessions
    panel = build_panel(inp)
    bundle = _load_model2(model2_path)
    m2_names = list(bundle["feature_names"])
    if not set(m2_names) <= set(X.FEATURE_NAMES):
        raise SystemExit("model 2 inputs are not a subset of the feature set")

    windows = {
        "W_M2": X.signal_days(sessions, X.window_start_after(sessions, X.MODEL2_LAST_TRAIN_DAY)),
        "W_FULL": X.signal_days(sessions, X.W_FULL_START),
    }
    result: dict[str, Any] = {"fingerprints": fps, "windows": {}, "artifacts": []}
    art_dir = out_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    for wname, days in windows.items():
        runs, leftover = X.make_runs(days)
        all_days = [d for r in runs for d in r]
        pools = pools_for(panel, all_days)
        outcomes = outcomes_for(panel, sessions, pools)
        fitted: dict[tuple[str, int], tuple] = {}

        def trained(cid, wname=wname, runs=runs, pools=pools, fitted=fitted):
            def scorer(k, run_days):
                if (cid, k) not in fitted:
                    last = X.last_training_index(sessions, runs[k][0])
                    tr = training_frame(panel, sessions, last)
                    x, y = tr[list(X.FEATURE_NAMES)].to_numpy(np.float64), tr["target"].to_numpy()
                    scaler, est = X.fit_candidate(cid, x, y)
                    fitted[(cid, k)] = (scaler, est)
                    test = pd.DataFrame(
                        [{"ts": pd.Timestamp(d), "symbol": s} for d in run_days for s in pools[d]]
                    )
                    card = model_card.build_card(
                        train_df=tr, test_df=test, dataset=pd.concat([tr[["ts", "symbol"]], test]),
                        feature_names=list(X.FEATURE_NAMES), algorithm=X.CANDIDATES[cid]["algorithm"],
                        train_args=X.CANDIDATES[cid]["params"], horizon_days=X.HORIZON,
                        target_return=X.LABEL_TARGET, stop_return=None, label_kind="endpoint",
                    )  # fmt: skip
                    card["training"]["entry_point"] = "swing_trade_ml.brain.lanes.r4_5d_run.run"
                    card["training"]["seed"] = X.CANDIDATES[cid]["params"]["random_state"]
                    card["feature_set"] = fps["feature_set"]
                    card["candidate"] = {
                        "id": cid,
                        "config_sha256": fps["config_sha256"][cid],
                        "window": wname,
                        "run": k,
                    }
                    card["data_snapshot_sha256"] = fps["data_snapshot_sha256"]
                    card["status"] = "research only: never registered, never activated"
                    path = art_dir / f"{wname}_{cid}_run{k + 1}.joblib"
                    joblib.dump(
                        {
                            "estimator": est,
                            "scaler": scaler,
                            "feature_names": list(X.FEATURE_NAMES),
                            "card": card,
                        },
                        path,
                    )
                    card["artifact_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    card["train_positive_rate"] = float(y.mean())
                    result["artifacts"].append({"path": path.name, "card": card})
                scaler, est = fitted[(cid, k)]
                return score_rows(
                    panel, pools, run_days, X.FEATURE_NAMES, lambda x: X.predict(scaler, est, x)
                )

            return scorer

        def model2(k, run_days, pools=pools):
            return score_rows(
                panel,
                pools,
                run_days,
                m2_names,
                lambda x: bundle["estimator"].predict_proba(bundle["scaler"].transform(x))[:, 1],
            )

        def momentum(k, run_days, pools=pools):
            return {
                d: X.momentum_scores({s: panel[s].bars for s in pools[d]}, d, pools[d])[0] for d in run_days
            }

        scorers = {"C1": model2, "C2": trained("C2"), "C3": trained("C3"), "MOM": momentum}
        res = evaluate_window(wname, runs, sessions, panel, pools, outcomes, scorers)
        sizes = [len(pools[d]) for d in all_days]
        res["leftover_sessions"] = (
            [leftover[0].isoformat(), leftover[-1].isoformat(), len(leftover)] if leftover else None
        )
        res["pool_size"] = {"min": min(sizes), "median": float(np.median(sizes)), "max": max(sizes)}
        res["never_eligible"] = sorted(set(X.UNIVERSE) - {s for d in all_days for s in pools[d]})
        res["flagged_pool_trades"] = sum(
            1 for (d, s), o in outcomes.items() if "possible_corporate_action" in o.flags
        )
        res["unresolved_pool_trades"] = sum(1 for o in outcomes.values() if o.net is None)
        res["pool_trades"] = len(outcomes)
        result["windows"][wname] = res
    metrics = {"windows": result["windows"]}
    result["metrics_sha256"] = hashlib.sha256(
        json.dumps(metrics, sort_keys=True, default=str).encode()
    ).hexdigest()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="r4_5d_run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fingerprint")
    rp = sub.add_parser("run")
    rp.add_argument("--out", required=True, type=Path)
    rp.add_argument("--prereg", required=True, type=Path)
    rp.add_argument("--model2", required=True, type=Path)
    args = ap.parse_args(argv)
    url = os.environ.get("R219_DATABASE_URL")
    if not url:
        print("R219_DATABASE_URL is not set", file=sys.stderr)
        return 2
    with readonly_session(url) as db:
        inp = load_inputs(db)
    if args.cmd == "fingerprint":
        print(json.dumps(fingerprints(inp), indent=2, sort_keys=True))
        return 0
    pre = json.loads(args.prereg.read_text(encoding="utf-8"))
    now = fingerprints(inp)
    keys = (
        "feature_set",
        "config_sha256",
        "data_snapshot_sha256",
        "code_sha256",
        "universe_sha256",
        "rule_sha256",
    )
    diff = [k for k in keys if pre.get(k) != now.get(k)]
    if diff:
        print(f"refusing to run: fingerprints differ from the pre-registration: {diff}", file=sys.stderr)
        return 3
    result = run(inp, args.out, args.model2)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    print(result["metrics_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
