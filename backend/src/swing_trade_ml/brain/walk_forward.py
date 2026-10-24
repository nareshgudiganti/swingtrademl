# backend/src/swing_trade_ml/brain/walk_forward.py
"""Walk-forward back-test: does the model's pick beat simple alternatives, window after window?

Each fold trains a model that only knows outcomes up to a cutoff, then scores the days after it
and moves on to the next window (the way the live bot retrains as time passes). The model's
best `top_k` stocks per day are compared with two baselines on the same days:

- every stock (a random pick has exactly this average result, so it is also the random baseline);
- the `top_k` strongest recent risers (a simple rule that needs no model).

Every idea is scored with the settled rule (next-day open, +8% / -4%, half out at +5%, 15 trading
days, real costs and slippage), the same strict scoring replay-score uses. Read-only evidence
tool: it registers trial models in the database (`wf_*`, never activated) and changes nothing live.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import splits
from swing_trade_ml.brain.horizon_grid import _days_beaten, _group, _index_after, summarise, top_k_by_day
from swing_trade_ml.brain.replay_score import load_bars
from swing_trade_ml.brain.replay_scoring import (
    HORIZON_BARS,
    NORMAL,
    STOP,
    TARGET,
    CostStress,
    StrictOutcome,
    strict_score,
)
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument

log = get_logger(__name__)

MOMENTUM_BARS = 20  # the "strongest risers" rule looks back this many trading days
RISING_OVER = 0.03  # a window where the average stock gained more than this is "rising"
FALLING_UNDER = -0.03
PROTOCOL_VERSION = "wf-protocol-v1"  # docs/superpowers/specs/2026-10-12-walk-forward-protocol.md
MIN_IDEAS = 100  # fewer finished model ideas than this is too little to conclude anything
MIN_FOLDS = 12  # fewer eligible folds than this is too little to conclude anything
MIN_FOLD_IDEAS = 20  # a fold needs this many finished model ideas to count ...
MIN_FOLD_DAYS = 10  # ... and this many test days
FOLDS_SHARE = 0.6  # provisional: share of eligible folds that must meet each part's criterion
BLOCK_DAYS = 15  # trades last up to 15 days, so days closer than this are not independent
SETTLE_DAYS = 25  # calendar days a pick needs to finish (15 trading days) before it can be scored


@dataclass(frozen=True, slots=True)
class Fold:
    cutoff: date  # last day whose outcome the model may learn from
    start: date  # first test day
    end: date  # last test day


def make_folds(first_start: date, last_end: date, test_days: int = 28) -> list[Fold]:
    """Back-to-back test windows of `test_days` calendar days from `first_start`. A window that
    would run past `last_end` is cut short; a window under a week long is dropped."""
    folds: list[Fold] = []
    start = first_start
    while start <= last_end:
        end = min(start + timedelta(days=test_days - 1), last_end)
        if (end - start).days >= 6:
            folds.append(Fold(cutoff=start - timedelta(days=1), start=start, end=end))
        start = start + timedelta(days=test_days)
    return folds


def latest_scoreable_end(upto: date) -> date:
    """The last test day whose picks have all had time to finish."""
    return upto - timedelta(days=SETTLE_DAYS)


def classify_regime(bars: dict[str, pd.DataFrame], start: date, end: date) -> dict:
    """Describe the window afterwards: how did the average stock move from its first to last bar?"""
    moves = []
    for df in bars.values():
        w = df[(df["day"] >= start) & (df["day"] <= end)]
        if len(w) >= 2 and float(w.iloc[0]["close"]) > 0:
            moves.append(float(w.iloc[-1]["close"]) / float(w.iloc[0]["close"]) - 1.0)
    if not moves:
        return {"label": "unknown", "avg_move": None}
    avg = sum(moves) / len(moves)
    label = "rising" if avg > RISING_OVER else "falling" if avg < FALLING_UNDER else "sideways"
    return {"label": label, "avg_move": avg}


def momentum_scores(bars: dict[str, pd.DataFrame], days: Sequence[date]) -> dict[str, dict[date, float]]:
    """Trailing `MOMENTUM_BARS`-bar gain, known at the close of each day (no later data)."""
    out: dict[str, dict[date, float]] = {}
    wanted = set(days)
    for sym, df in bars.items():
        closes = [float(c) for c in df["close"]]
        bar_days = list(df["day"])
        per: dict[date, float] = {}
        for i, d in enumerate(bar_days):
            if d in wanted and i >= MOMENTUM_BARS and closes[i - MOMENTUM_BARS] > 0:
                per[d] = closes[i] / closes[i - MOMENTUM_BARS] - 1.0
        out[sym] = per
    return out


def outcomes_for(
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    horizon: int,
    target: float,
    stop: float,
    stress: CostStress = NORMAL,
) -> dict[tuple[str, date], StrictOutcome]:
    """Strict outcome of deciding on `day` (enter the next bar's open), for every stock and day."""
    out: dict[tuple[str, date], StrictOutcome] = {}
    for sym, df in bars.items():
        bar_days = list(df["day"])
        have = set(bar_days)
        for day in days:
            if day not in have:
                continue
            k = _index_after(bar_days, day)
            if k is not None:
                out[(sym, day)] = strict_score(
                    df.iloc[k : k + horizon], horizon=horizon, target=target, stop=stop, stress=stress
                )
    return out


def daily_edge(
    picks: dict[date, list[str]],
    everyone: dict[date, list[str]],
    outcomes: dict[tuple[str, date], StrictOutcome],
) -> list[float]:
    """Per day: the picks' average net return minus the every-stock average, finished ideas only."""
    diffs: list[float] = []
    for day, syms in picks.items():
        mine = [outcomes[(s, day)].net_return for s in syms if (s, day) in outcomes]
        mine = [r for r in mine if r is not None]
        theirs = [outcomes[(s, day)].net_return for s in everyone.get(day, []) if (s, day) in outcomes]
        theirs = [r for r in theirs if r is not None]
        if mine and theirs:
            diffs.append(sum(mine) / len(mine) - sum(theirs) / len(theirs))
    return diffs


def bootstrap_low(
    values: Sequence[float], block: int = BLOCK_DAYS, draws: int = 2000, seed: int = 7
) -> float | None:
    """Lower end (5th percentile) of the average of `values` (in day order), by resampling runs of
    `block` consecutive days. Single days would treat overlapping 15-day trades as independent
    and make the edge look surer than it is. If even this bound is above zero, the edge is
    unlikely to be luck of the draw."""
    n = len(values)
    if n < max(5, 2 * block):
        return None
    rng = random.Random(seed)
    per_draw = -(-n // block)  # blocks needed to rebuild a series of about n days
    means = []
    for _ in range(draws):
        picked = []
        for _ in range(per_draw):
            s = rng.randrange(n - block + 1)
            picked.extend(values[s : s + block])
        means.append(sum(picked) / len(picked))
    means.sort()
    return means[int(0.05 * draws)]


def is_eligible(row: dict) -> bool:
    """A fold counts toward the share only if it had enough days and finished model ideas."""
    return row["days"] >= MIN_FOLD_DAYS and row["model"]["ideas"] >= MIN_FOLD_IDEAS


def _part(eligible: int, wins: int, extra_ok: bool | None, extra_why: str) -> dict:
    share = wins / eligible if eligible else 0.0
    if eligible < MIN_FOLDS or extra_ok is None:
        word = "insufficient"
    else:
        word = "pass" if (share >= FOLDS_SHARE and extra_ok) else "fail"
    return {"word": word, "eligible_folds": eligible, "folds_won": wins, "share": share, "check": extra_why}


def verdict(
    *,
    model_ideas: int,
    eligible: int,
    predictive_wins: int,
    economic_wins: int,
    edge_low: float | None,
    pooled_avg_net: float | None,
) -> dict:
    """The decision rule, fixed in advance. Two independent answers.

    Predictive skill: the model beat every-stock in at least `FOLDS_SHARE` of eligible folds and
    the block-bootstrap lower bound of its daily edge is above zero.
    Economic value: the model's average result after costs was above zero in at least
    `FOLDS_SHARE` of eligible folds and above zero overall.
    Either part is 'insufficient' with fewer than MIN_FOLDS eligible folds or MIN_IDEAS ideas."""
    enough = model_ideas >= MIN_IDEAS
    predictive = _part(
        eligible,
        predictive_wins,
        None if (edge_low is None or not enough) else edge_low > 0,
        "lower bound of the daily edge over every-stock is above zero",
    )
    economic = _part(
        eligible,
        economic_wins,
        None if (pooled_avg_net is None or not enough) else pooled_avg_net > 0,
        "average result per trade after costs is above zero overall",
    )
    table = {
        ("pass", "pass"): "Strongest evidence that the model is useful.",
        ("pass", "fail"): "Picks beat random, but the trades do not make money.",
        ("fail", "pass"): "Trades made money, but beating random is not shown.",
        ("fail", "fail"): "No evidence of skill and no profit.",
    }
    key = (predictive["word"], economic["word"])
    return {
        "predictive": predictive,
        "economic": economic,
        "reading": table.get(key, "Not enough data for a full answer."),
    }


def _train(db: Session, cutoff: date, horizon: int, target: float, stop: float):
    from swing_trade_ml.ml.train import train_model

    return train_model(
        db,
        name=f"wf_h{horizon}_{cutoff:%Y%m%d}",
        cutoff=cutoff,
        horizon_days=horizon,
        target_return=target,
        stop_return=stop,
        auto_activate=False,
    )


def run_walk_forward(
    db: Session,
    *,
    first_start: date,
    last_end: date,
    test_days: int = 28,
    top_k: int = 5,
    horizon: int = HORIZON_BARS,
    target: float = TARGET,
    stop: float = STOP,
    train_fn=None,
    score_fn=None,
    stress: CostStress = NORMAL,
) -> dict:
    """`train_fn(db, cutoff, horizon, target, stop)` returns a model; `score_fn(db, instrument,
    model, after)` returns {day: score}. Both default to the real ones and are replaceable in tests.
    `stress` scores every idea (and the baselines) at dearer costs; picks do not depend on it."""
    if train_fn is None:
        train_fn = _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn

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

    fold_rows: list[dict] = []
    pooled: dict[str, dict[date, list[StrictOutcome]]] = {"model": {}, "momentum": {}, "every": {}}
    pooled_diffs = {"model": [], "momentum": []}
    split_rows: dict[str, list[tuple[str, str, StrictOutcome]]] = {"model": [], "every_stock": []}
    window_labels: list[str] = []
    for fold in folds:
        days = sorted({d for df in bars.values() for d in df["day"] if fold.start <= d <= fold.end})
        if not days:
            continue
        log.info("walk_forward.fold", cutoff=fold.cutoff.isoformat(), start=fold.start.isoformat())
        outcomes = outcomes_for(bars, days, horizon, target, stop, stress)
        everyone = {d: [s for (s, dd) in outcomes if dd == d] for d in days}
        model = train_fn(db, fold.cutoff, horizon, target, stop)
        scores = {
            i.tradingsymbol: {
                d: p for d, p in score_fn(db, i, model, fold.cutoff).items() if fold.start <= d <= fold.end
            }
            for i in instruments
        }
        picks = {
            "model": top_k_by_day(scores, days, top_k),
            "momentum": top_k_by_day(momentum_scores(bars, days), days, top_k),
        }
        grouped = {name: _group(p, outcomes) for name, p in picks.items()}
        grouped["every"] = _group(everyone, outcomes)
        for name, g in grouped.items():
            pooled[name].update(g)
        for name in ("model", "momentum"):
            pooled_diffs[name].extend(daily_edge(picks[name], everyone, outcomes))
        regime = classify_regime(bars, fold.start, fold.end)
        window_labels.append(regime["label"])
        for name, chosen in (("model", picks["model"]), ("every_stock", everyone)):
            split_rows[name].extend(
                (regime["label"], s, outcomes[(s, d)])
                for d, syms in chosen.items()
                for s in syms
                if (s, d) in outcomes
            )
        fold_rows.append(
            {
                "cutoff": fold.cutoff.isoformat(),
                "start": fold.start.isoformat(),
                "end": fold.end.isoformat(),
                "days": len(days),
                "regime": regime,
                "model": summarise(grouped["model"]),
                "momentum": summarise(grouped["momentum"]),
                "every_stock": summarise(grouped["every"]),
                "model_days_better": _days_beaten(picks["model"], everyone, outcomes),
                "model_auc": getattr(model, "roc_auc", None),
            }
        )

    eligible_rows = [r for r in fold_rows if is_eligible(r)]
    model_all = summarise(pooled["model"])
    edge_low = bootstrap_low(pooled_diffs["model"])
    by_regime: dict[str, dict] = defaultdict(lambda: {"folds": 0, "better": 0})
    for r in fold_rows:
        b = by_regime[r["regime"]["label"]]
        b["folds"] += 1
        b["better"] += 1 if _fold_better(r) else 0
    return {
        "protocol": PROTOCOL_VERSION,
        "top_k": top_k,
        "rule": {"horizon": horizon, "target": target, "stop": stop},
        "costs": stress.label,
        "stocks": len(bars),
        "folds": fold_rows,
        "pooled": {
            "model": model_all,
            "momentum": summarise(pooled["momentum"]),
            "every_stock": summarise(pooled["every"]),
            "model_edge_per_day": _mean(pooled_diffs["model"]),
            "model_edge_low": edge_low,
            "momentum_edge_per_day": _mean(pooled_diffs["momentum"]),
        },
        "by_regime": dict(by_regime),
        "splits": {
            name: {
                "by_market_type": splits.by_market_type(rows, window_labels),
                "by_sector": splits.by_sector((s, o) for _, s, o in rows),
            }
            for name, rows in split_rows.items()
        },
        "worst_fold_avg": min(
            (r["model"]["avg_net_by_day"] for r in eligible_rows if r["model"]["avg_net_by_day"] is not None),
            default=None,
        ),
        "verdict": verdict(
            model_ideas=model_all["ideas"],
            eligible=len(eligible_rows),
            predictive_wins=sum(1 for r in eligible_rows if _fold_better(r)),
            economic_wins=sum(1 for r in eligible_rows if _fold_profitable(r)),
            edge_low=edge_low,
            pooled_avg_net=model_all["avg_net"],
        ),
    }


def _fold_better(row: dict) -> bool:
    m, a = row["model"]["avg_net_by_day"], row["every_stock"]["avg_net_by_day"]
    return m is not None and a is not None and m > a


def _fold_profitable(row: dict) -> bool:
    m = row["model"]["avg_net_by_day"]
    return m is not None and m > 0


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def split_lines(sp: dict | None) -> list[str]:
    """Result per trade by market type and by sector, model next to every stock (ps8)."""
    if not sp:
        return []
    m, e = sp["model"], sp["every_stock"]

    def row(name: str, mr: dict, er: dict | None, extra: str = "") -> str:
        er = er or {}
        return (
            f"| {name}{extra} | {mr['finished']} | {_pct(mr['hit_rate'], 0)} | {_pct(mr['avg_net'])} | "
            f"{er.get('finished', 0)} | {_pct(er.get('avg_net'))} |"
        )

    head = (
        "| {} | Model finished | Model hit target | Model average "
        "| Every stock finished | Every stock average |"
    )
    lines = ["", "## Result by market type (after costs)", head.format("Market"), "|---|---|---|---|---|---|"]
    for label, r in m["by_market_type"].items():
        lines.append(row(label, r, e["by_market_type"].get(label), f" ({r.get('windows', 0)} windows)"))
    weak = splits.weak_market_types(m["by_market_type"])
    lines += [
        "",
        f"Market types below {splits.WEAK_TYPE_LIMIT:.0%} per trade (seen in at least "
        f"{splits.WEAK_TYPE_MIN_FOLDS} windows): {', '.join(weak) if weak else 'none'}.",
        "",
        "## Result by sector (after costs; today's sector map)",
        head.format("Sector"),
        "|---|---|---|---|---|---|",
    ]
    for label, r in m["by_sector"].items():
        lines.append(row(label, r, e["by_sector"].get(label), f" ({r['stocks']} stocks)"))
    return lines


def plain_report(result: dict) -> str:
    r = result["rule"]
    p = result["pooled"]
    v = result["verdict"]
    lines = [
        "# Walk-forward back-test",
        "",
        f"Rule: enter next open, +{r['target']:.0%} / -{r['stop']:.0%}, {r['horizon']} trading days, "
        f"costs and slippage included. {result['stocks']} stocks. "
        f"Model and 'strongest risers' each take the best {result['top_k']} per day.",
        "A random pick averages the same as 'every stock', so that column is also the random baseline.",
        "",
        f"Protocol: {result.get('protocol', 'unversioned')}. Provisional rule: at least "
        f"{FOLDS_SHARE:.0%} of eligible folds (at least {MIN_FOLD_DAYS} days and {MIN_FOLD_IDEAS} finished "
        "model ideas each).",
        "",
        f"## Verdict: {v['reading']}",
        "| Part | Answer | Folds won | Also needed |",
        "|---|---|---|---|",
        f"| Predictive skill (beat every-stock) | {v['predictive']['word']} | "
        f"{v['predictive']['folds_won']} of {v['predictive']['eligible_folds']} | "
        f"{v['predictive']['check']} |",
        f"| Economic value (profit after costs) | {v['economic']['word']} | "
        f"{v['economic']['folds_won']} of {v['economic']['eligible_folds']} | {v['economic']['check']} |",
        "",
        f"Worst eligible fold, average per day: {_pct(result.get('worst_fold_avg'))}. "
        "This is not a drawdown: layer 1 has no account simulation.",
        "",
        "## All windows together (average result per trade, after costs)",
        "| | Ideas | Hit target | Average |",
        "|---|---|---|---|",
    ]
    for label, key in (("Model", "model"), ("Strongest risers", "momentum"), ("Every stock", "every_stock")):
        s = p[key]
        lines.append(f"| {label} | {s['ideas']} | {_pct(s['hit_rate'], 0)} | {_pct(s['avg_net'])} |")
    lines += [
        "",
        f"Model minus every-stock, per day: {_pct(p['model_edge_per_day'])} "
        f"(lower bound {_pct(p['model_edge_low'])}). "
        f"Strongest risers minus every-stock: {_pct(p['momentum_edge_per_day'])}.",
        "",
        "## Each window",
        "| Test days | Market | Model | Strongest risers | Every stock | Days model won | AUC |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in result["folds"]:
        d = f["model_days_better"]
        auc = "n/a" if f["model_auc"] is None else f"{f['model_auc']:.3f}"
        lines.append(
            f"| {f['start']} to {f['end']} | {f['regime']['label']} ({_pct(f['regime']['avg_move'], 1)}) | "
            f"{_pct(f['model']['avg_net'])} | {_pct(f['momentum']['avg_net'])} | "
            f"{_pct(f['every_stock']['avg_net'])} | {d['better']} of {d['of']} | {auc} |"
        )
    lines += ["", "## By market type", "| Market | Windows | Model beat every-stock |", "|---|---|---|"]
    for label, b in sorted(result["by_regime"].items()):
        lines.append(f"| {label} | {b['folds']} | {b['better']} |")
    lines += split_lines(result.get("splits"))
    return "\n".join(lines) + "\n"


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    first, last = result["folds"][0]["start"], result["folds"][-1]["end"]
    stem = f"walk_forward_{first}_{last}"
    md, js = directory / f"{stem}.md", directory / f"{stem}.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    from datetime import UTC, datetime

    from swing_trade_ml.core.market_session import last_closed_trading_day
    from swing_trade_ml.db.session import SessionLocal

    # `--protocol fd-protocol-v1` hands over to the 5-day protocol's own tool (brain/five_day.py).
    # Without it nothing changes: this stays the frozen wf-protocol-v1 run.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--protocol", default=PROTOCOL_VERSION, choices=(PROTOCOL_VERSION, "fd-protocol-v1"))
    known, argv = pre.parse_known_args(argv)
    if known.protocol == "fd-protocol-v1":
        from swing_trade_ml.brain import five_day

        return five_day.main(argv)

    p = argparse.ArgumentParser(description="Walk-forward back-test of the model (read-only evidence)")
    p.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD: first test day")
    p.add_argument(
        "--to", dest="end", default=None, help="YYYY-MM-DD (default: latest day whose picks have finished)"
    )
    p.add_argument("--test-days", type=int, default=28, help="calendar days per test window")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--out", default="docs/brain/evidence")
    a = p.parse_args(argv)
    end = (
        date.fromisoformat(a.end)
        if a.end
        else latest_scoreable_end(last_closed_trading_day(datetime.now(UTC)))
    )
    with SessionLocal() as db:
        result = run_walk_forward(
            db, first_start=date.fromisoformat(a.start), last_end=end, test_days=a.test_days, top_k=a.top_k
        )
    md, js = write_report(result, Path(a.out))
    print(plain_report(result))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
