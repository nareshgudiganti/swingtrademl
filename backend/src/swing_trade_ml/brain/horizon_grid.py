# backend/src/swing_trade_ml/brain/horizon_grid.py
"""Which target, stop and holding time earns the most? (read-only evidence tool)

For each setting (horizon in trading days, target, stop) it answers two questions on days a
model never saw:

1. What does taking every stock earn? This shows the setting's own economics, with real
   costs and slippage, and the win rate needed to break even.
2. Does a model trained for exactly that setting pick better than taking every stock? The
   model is trained with a cutoff (only rows whose outcome was known by it) and the best
   `top_k` stocks by its score are taken each day.

Nothing here changes a live rule or a model in use. It registers trial models in the database
(named `gridtest_*`, never activated).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.replay_score import load_bars
from swing_trade_ml.brain.replay_scoring import StrictOutcome, strict_score
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Setting:
    horizon: int  # trading days
    target: float
    stop: float

    @property
    def label(self) -> str:
        return f"{self.horizon}d +{self.target:.0%} / -{self.stop:.0%}"

    @property
    def breakeven(self) -> float:
        """Share of trades that must reach the target to break even, before costs."""
        return self.stop / (self.target + self.stop)


DEFAULT_GRID = tuple(
    Setting(h, t, s)
    for h in (5, 10, 15)
    for t, s in ((0.02, 0.02), (0.03, 0.03), (0.05, 0.03), (0.05, 0.04), (0.08, 0.04))
)


def summarise(by_day: dict[date, list[StrictOutcome]]) -> dict:
    """Hit rate and average result of the finished ideas. `avg_net` weighs every idea the
    same; `avg_net_by_day` weighs every day the same, so one crowded day cannot dominate."""
    finished = {d: [o for o in outs if o.net_return is not None] for d, outs in by_day.items()}
    finished = {d: outs for d, outs in finished.items() if outs}
    flat = [o for outs in finished.values() for o in outs]
    if not flat:
        return {"ideas": 0, "days": 0, "hit_rate": None, "avg_net": None, "avg_net_by_day": None}
    day_means = [sum(o.net_return for o in outs) / len(outs) for outs in finished.values()]
    return {
        "ideas": len(flat),
        "days": len(finished),
        "hit_rate": sum(o.status == "target" for o in flat) / len(flat),
        "avg_net": sum(o.net_return for o in flat) / len(flat),
        "avg_net_by_day": sum(day_means) / len(day_means),
    }


def outcome_for(bars: pd.DataFrame, start_idx: int, setting: Setting) -> StrictOutcome:
    """The idea's outcome: enter at the open of the bar at `start_idx` (the day after the decision)."""
    window = bars.iloc[start_idx : start_idx + setting.horizon]
    return strict_score(
        window, horizon=setting.horizon, target=setting.target, stop=setting.stop, half_out=None
    )


def _index_after(days: list[date], day: date) -> int | None:
    """Position of the first bar strictly after `day`, or None."""
    lo, hi = 0, len(days)
    while lo < hi:
        mid = (lo + hi) // 2
        if days[mid] <= day:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(days) else None


def all_stock_outcomes(
    bars: dict[str, pd.DataFrame], days: Sequence[date], setting: Setting
) -> dict[tuple[str, date], StrictOutcome]:
    out: dict[tuple[str, date], StrictOutcome] = {}
    for symbol, df in bars.items():
        bar_days = list(df["day"])
        have = set(bar_days)
        for day in days:
            if day not in have:
                continue
            k = _index_after(bar_days, day)
            if k is not None:
                out[(symbol, day)] = outcome_for(df, k, setting)
    return out


def top_k_by_day(scores: dict[str, dict[date, float]], days: Sequence[date], k: int) -> dict[date, list[str]]:
    picks: dict[date, list[str]] = {}
    for day in days:
        ranked = sorted(((s[day], sym) for sym, s in scores.items() if day in s), reverse=True)
        picks[day] = [sym for _, sym in ranked[:k]]
    return picks


def _group(
    picks: dict[date, list[str]], outcomes: dict[tuple[str, date], StrictOutcome]
) -> dict[date, list[StrictOutcome]]:
    grouped: dict[date, list[StrictOutcome]] = defaultdict(list)
    for day, symbols in picks.items():
        for sym in symbols:
            o = outcomes.get((sym, day))
            if o is not None:
                grouped[day].append(o)
    return grouped


def trading_days(bars: dict[str, pd.DataFrame], start: date, end: date) -> list[date]:
    seen = {d for df in bars.values() for d in df["day"] if start <= d <= end}
    return sorted(seen)


def run_grid(
    db: Session,
    *,
    cutoff: date,
    start: date,
    end: date,
    settings: Sequence[Setting] = DEFAULT_GRID,
    top_k: int = 5,
    train_fn=None,
    score_fn=None,
) -> dict:
    """`train_fn(db, cutoff, setting)` returns a model and `score_fn(db, instrument, model, after)`
    returns {day: score}. Both default to the real ones and are replaceable in tests."""
    if start <= cutoff:
        raise ValueError("The test window must start after the cutoff, or the model has seen it.")
    if train_fn is None:
        train_fn = _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn

    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    upto = end + timedelta(days=60)
    bars = {s: df for s, df in load_bars(db, [i.tradingsymbol for i in instruments], upto).items() if len(df)}
    days = trading_days(bars, start, end)
    rows = []
    for setting in settings:
        log.info("horizon_grid.setting", setting=setting.label)
        outcomes = all_stock_outcomes(bars, days, setting)
        everyone = {d: [s for (s, dd) in outcomes if dd == d] for d in days}
        row = {
            "setting": setting.label,
            "horizon": setting.horizon,
            "target": setting.target,
            "stop": setting.stop,
            "breakeven_before_costs": setting.breakeven,
            "all_stocks": summarise(_group(everyone, outcomes)),
        }
        model = train_fn(db, cutoff, setting)
        scores = {
            i.tradingsymbol: {d: p for d, p in score_fn(db, i, model, cutoff).items() if start <= d <= end}
            for i in instruments
        }
        picks = top_k_by_day(scores, days, top_k)
        row["model_top"] = summarise(_group(picks, outcomes))
        row["model_auc"] = getattr(model, "roc_auc", None)
        row["days_model_beat_all"] = _days_beaten(picks, everyone, outcomes)
        rows.append(row)
    return {
        "cutoff": cutoff.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "top_k": top_k,
        "stocks": len(bars),
        "days": len(days),
        "rows": rows,
    }


def _days_beaten(picks, everyone, outcomes) -> dict:
    wins = total = 0
    for day, symbols in picks.items():
        mine = [outcomes[(s, day)].net_return for s in symbols if (s, day) in outcomes]
        mine = [r for r in mine if r is not None]
        theirs = [outcomes[(s, day)].net_return for s in everyone.get(day, []) if (s, day) in outcomes]
        theirs = [r for r in theirs if r is not None]
        if mine and theirs:
            total += 1
            wins += (sum(mine) / len(mine)) > (sum(theirs) / len(theirs))
    return {"better": wins, "of": total}


def _train(db: Session, cutoff: date, setting: Setting):
    from swing_trade_ml.ml.train import train_model

    t, st = round(setting.target * 100), round(setting.stop * 100)
    name = f"gridtest_h{setting.horizon}_t{t}_s{st}_{cutoff:%Y%m%d}"
    return train_model(
        db,
        name=name,
        cutoff=cutoff,
        horizon_days=setting.horizon,
        target_return=setting.target,
        stop_return=setting.stop,
        auto_activate=False,
    )


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def plain_report(result: dict) -> str:
    lines = [
        f"# Horizon grid: {result['start']} to {result['end']}",
        "",
        f"Models trained only on outcomes known by {result['cutoff']}. {result['stocks']} stocks, "
        f"{result['days']} trading days. Costs and slippage included; no half-out; entry at the next open.",
        f"'Model top' = the best {result['top_k']} stocks a day by the model's score for that setting.",
        "",
        "| Setting | Break-even wins | Every stock: hit, avg | Model top: hit, avg "
        "| Days model beat every-stock | Model AUC |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(
        result["rows"], key=lambda r: (r["model_top"]["avg_net"] is None, -(r["model_top"]["avg_net"] or 0))
    ):
        a, m, d = r["all_stocks"], r["model_top"], r["days_model_beat_all"]
        auc = "n/a" if r["model_auc"] is None else f"{r['model_auc']:.3f}"
        lines.append(
            f"| {r['setting']} | {_pct(r['breakeven_before_costs'], 0)} | "
            f"{_pct(a['hit_rate'], 0)}, {_pct(a['avg_net'], 2)} | "
            f"{_pct(m['hit_rate'], 0)}, {_pct(m['avg_net'], 2)} | {d['better']} of {d['of']} | "
            f"{auc} |"
        )
    return "\n".join(lines) + "\n"


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"horizon_grid_{result['start']}_{result['end']}"
    md, js = directory / f"{stem}.md", directory / f"{stem}.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Which target / stop / horizon earns the most? (read-only)")
    p.add_argument("--cutoff", required=True, help="YYYY-MM-DD: last day whose outcome the models may use")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument(
        "--only", default=None, help="Comma list like 5:0.02:0.02,15:0.08:0.04 (default: full grid)"
    )
    p.add_argument("--out", default="docs/brain/evidence")
    a = p.parse_args(argv)
    settings = DEFAULT_GRID
    if a.only:
        settings = tuple(
            Setting(int(h), float(t), float(s)) for h, t, s in (x.split(":") for x in a.only.split(","))
        )
    with SessionLocal() as db:
        result = run_grid(
            db,
            cutoff=date.fromisoformat(a.cutoff),
            start=date.fromisoformat(a.start),
            end=date.fromisoformat(a.end),
            settings=settings,
            top_k=a.top_k,
        )
    md, js = write_report(result, Path(a.out))
    print(plain_report(result))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
