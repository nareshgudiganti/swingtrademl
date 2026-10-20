# backend/src/swing_trade_ml/brain/bad_market.py
"""Bad-market test (ps2, read-only evidence tool): did the brain turn careful in time?

Windows are chosen by a fixed rule, never by hand: the `WORST_N` worst NIFTY falls over
`FALL_BARS` trading days (no two overlapping) and the longest NIFTY fall (most trading days from a
peak to its lowest close before NIFTY made a new high). For each window:

1. Banner: the market judge (M10, `m10_market.judge`) is replayed day by day on NIFTY, India VIX and
   watchlist breadth cut at that day (no later data). When did it first leave NORMAL, how far had
   NIFTY fallen by then, and how many of the falling days were careful?
2. Account: a model trained only on data before the report period picks its best 5 a day; the picks
   run through one ₹10 lakh account (`portfolio_sim.simulate`, 15% halt, sector cap) twice: with the
   replayed banner and with "always NORMAL". Worst fall vs the 15% halt; the difference is what the
   banner did.
3. Ideas on careful days, scored on their own: hit the stop (losses avoided) vs hit +8% (gains missed).

All local data is development data, so this is a diagnostic. It registers trial models (`wf_*`, never
activated) and changes nothing live.

Run (backend/): python -m swing_trade_ml.brain.bad_market
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.horizon_grid import top_k_by_day
from swing_trade_ml.brain.modules.m10_market.judge import MarketInputs, judge
from swing_trade_ml.brain.portfolio_sim import MAX_DRAWDOWN, NORMAL_MAX_NEW, Pick, simulate
from swing_trade_ml.brain.replay_scoring import HORIZON_BARS, STOP, TARGET, StrictOutcome
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

PROTOCOL_ID = "ps2-bad-market-v1"
WORST_N = 4  # worst NIFTY falls over FALL_BARS trading days ...
FALL_BARS = 20
MIN_HISTORY_BARS = (
    220  # ... only where the judge has its 200-day average (otherwise it is careful by default)
)
PAD_BEFORE = 20  # report period: this many trading days before the peak ...
PAD_AFTER = 30  # ... to this many after the trough
CAPITAL = 1_000_000.0
NORMAL = "NORMAL"
SETTLE_BARS = HORIZON_BARS + 10  # the account runs this long after the last pick, so picks can finish
IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class Window:
    kind: str  # "20-day fall" or "longest fall"
    peak: date
    trough: date
    fall: float  # trough close / peak close - 1 (negative)
    bars: int  # trading days from peak to trough


def _window(kind: str, days: list[date], closes: list[float], lo: int, hi: int) -> Window:
    """Peak = highest close in [lo, hi]; trough = lowest close after that peak, up to hi."""
    p = max(range(lo, hi + 1), key=lambda i: (closes[i], -i))
    t = min(range(p, hi + 1), key=lambda i: (closes[i], i))
    return Window(kind, days[p], days[t], closes[t] / closes[p] - 1.0, t - p)


def worst_falls(
    nifty: pd.Series, n: int = WORST_N, bars: int = FALL_BARS, min_history: int = MIN_HISTORY_BARS
) -> list[Window]:
    """The `n` worst `bars`-day NIFTY moves whose spans do not overlap, worst first.
    `nifty`: closes indexed by trading day, ascending."""
    days, closes = list(nifty.index), [float(c) for c in nifty]
    moves = sorted(
        (closes[t] / closes[t - bars] - 1.0, t) for t in range(max(bars, min_history), len(closes))
    )
    chosen: list[int] = []
    for _, t in moves:
        if all(abs(t - u) > bars for u in chosen):
            chosen.append(t)
        if len(chosen) == n:
            break
    return [_window(f"{bars}-day fall", days, closes, t - bars, t) for t in chosen]


def longest_fall(nifty: pd.Series, min_history: int = MIN_HISTORY_BARS) -> Window | None:
    """The fall that took the most trading days from a peak to its lowest close before a new high."""
    days, closes = list(nifty.index), [float(c) for c in nifty]
    best: tuple[int, int, int] | None = None  # (bars, peak index, trough index)
    peak = 0
    trough = 0
    for i in range(1, len(closes) + 1):
        if i == len(closes) or closes[i] > closes[peak]:
            if trough > peak and peak >= min_history and (best is None or trough - peak > best[0]):
                best = (trough - peak, peak, trough)
            if i < len(closes):
                peak = trough = i
        elif closes[i] < closes[trough]:
            trough = i
    if best is None:
        return None
    _, p, t = best
    return Window("longest fall", days[p], days[t], closes[t] / closes[p] - 1.0, t - p)


def choose_windows(nifty: pd.Series) -> list[Window]:
    """The locked rule. The longest fall is kept even if it overlaps a 20-day one (a different kind)."""
    out = worst_falls(nifty)
    lf = longest_fall(nifty)
    if lf is not None and all((lf.peak, lf.trough) != (w.peak, w.trough) for w in out):
        out.append(lf)
    return out


def replay_modes(
    index: pd.Series, vix: pd.Series, breadth: pd.Series, days: Sequence[date]
) -> dict[date, str]:
    """The market judge's mode on each day, with every input cut at that day. Series are indexed by
    trading day. FII flows are left out (no local history); that rule only ever adds caution."""
    out: dict[date, str] = {}
    for d in days:
        inputs = MarketInputs(
            index_close=index[index.index <= d].reset_index(drop=True),
            vix_close=vix[vix.index <= d].reset_index(drop=True),
            breadth=breadth[breadth.index <= d].reset_index(drop=True),
            fii_net=[],
        )
        out[d] = judge(inputs).mode.value
    return out


def banner_timing(modes: dict[date, str], w: Window, nifty: pd.Series) -> dict:
    """When the banner first left NORMAL between the peak and the trough, and what share of the fall
    had already happened by then (0% = careful at the peak, 100% = only at the bottom)."""
    falling = [d for d in nifty.index if w.peak <= d <= w.trough]
    peak_px = float(nifty[w.peak])

    def first(pred) -> dict | None:
        for i, d in enumerate(falling):
            if d in modes and pred(modes[d]):
                fell = float(nifty[d]) / peak_px - 1.0
                return {
                    "day": d.isoformat(),
                    "days_after_peak": i,
                    "nifty_fall_by_then": fell,
                    "share_of_fall_by_then": fell / w.fall if w.fall else None,
                }
        return None

    careful = sum(1 for d in falling if modes.get(d, NORMAL) != NORMAL)
    return {
        "mode_at_peak": modes.get(w.peak),
        "first_careful": first(lambda m: m != NORMAL),
        "first_no_new_trades": first(lambda m: m == "NO_NEW_TRADES"),
        "careful_days": careful,
        "falling_days": len(falling),
    }


def careful_day_ideas(
    picks: Sequence[Pick], modes: dict[date, str], outcomes: dict[tuple[str, date], StrictOutcome]
) -> dict:
    """The model's picks on days the banner was not NORMAL, each scored on its own."""
    rows = [outcomes.get((p.symbol, p.day)) for p in picks if modes.get(p.day, NORMAL) != NORMAL]
    done = [o for o in rows if o is not None and o.net_return is not None]
    return {
        "ideas": len(rows),
        "finished": len(done),
        "hit_target": sum(o.status == "target" for o in done),  # gains the banner gave up
        "hit_stop": sum(o.status == "stop" for o in done),  # losses the banner avoided
        "avg_net": sum(o.net_return for o in done) / len(done) if done else None,
    }


def _dated(series_rows: list[tuple[date, float]]) -> pd.Series:
    if not series_rows:
        return pd.Series(dtype=float)
    days, vals = zip(*series_rows, strict=True)
    return pd.Series(list(vals), index=list(days), dtype=float)


def load_market(db: Session, upto: date) -> tuple[pd.Series, pd.Series, pd.Series]:
    """NIFTY closes, India VIX closes and watchlist breadth, each indexed by IST trading day."""
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.ml import market_context

    idx = load_bars(db, [settings.BENCHMARK_INDEX_SYMBOL, "INDIA VIX"], upto)
    nifty = idx.get(settings.BENCHMARK_INDEX_SYMBOL, pd.DataFrame(columns=["day", "close"]))
    vix = idx.get("INDIA VIX", pd.DataFrame(columns=["day", "close"]))
    frame = market_context.load_market_breadth(db)
    breadth_rows = []
    for ts, v in zip(frame["ts"], frame["breadth_pct_above_sma50"], strict=True):
        if pd.isna(v):
            continue
        t = pd.Timestamp(ts)
        day = (t.tz_convert(IST) if t.tzinfo else t).date()
        if day <= upto:
            breadth_rows.append((day, float(v)))
    return (
        _dated(list(zip(nifty["day"], nifty["close"], strict=True))),
        _dated(list(zip(vix["day"], vix["close"], strict=True))),
        _dated(breadth_rows),
    )


def run_window(
    db: Session,
    w: Window,
    *,
    nifty: pd.Series,
    vix: pd.Series,
    breadth: pd.Series,
    instruments,
    bars: dict[str, pd.DataFrame],
    train_fn,
    score_fn,
) -> dict:
    from swing_trade_ml.brain.walk_forward import outcomes_for
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    all_days = list(nifty.index)
    p, t = all_days.index(w.peak), all_days.index(w.trough)
    start = all_days[max(0, p - PAD_BEFORE)]
    end = all_days[min(len(all_days) - 1, t + PAD_AFTER)]
    report_days = [d for d in all_days if start <= d <= end]
    modes = replay_modes(nifty, vix, breadth, report_days)

    cutoff = start - timedelta(days=1)
    model = train_fn(db, cutoff, HORIZON_BARS, TARGET, STOP)
    scores = {
        i.tradingsymbol: {d: s for d, s in score_fn(db, i, model, cutoff).items() if start <= d <= end}
        for i in instruments
    }
    top = top_k_by_day(scores, report_days, NORMAL_MAX_NEW)
    picks = [
        Pick(d, sym, scores[sym][d], get_sector_bucket(sym)) for d in report_days for sym in top.get(d, [])
    ]
    later = sorted({d for df in bars.values() for d in df["day"] if d >= start})
    sim_days = [d for d in later if d <= end] + [d for d in later if d > end][:SETTLE_BARS]
    with_banner = simulate(picks, bars, sim_days, capital=CAPITAL, modes=modes)
    always_normal = simulate(picks, bars, sim_days, capital=CAPITAL, modes=None)
    outcomes = outcomes_for(bars, report_days, HORIZON_BARS, TARGET, STOP)
    return {
        "window": {**asdict(w), "peak": w.peak.isoformat(), "trough": w.trough.isoformat()},
        "report": {"from": start.isoformat(), "to": end.isoformat(), "model_cutoff": cutoff.isoformat()},
        "modes": {m: sum(v == m for v in modes.values()) for m in ("NORMAL", "DEFENSIVE", "NO_NEW_TRADES")},
        "banner": banner_timing(modes, w, nifty),
        "account": {"with_banner": with_banner.summary(), "always_normal": always_normal.summary()},
        "careful_day_ideas": careful_day_ideas(picks, modes, outcomes),
        "model_auc": getattr(model, "roc_auc", None),
    }


def run(db: Session, *, upto: date, train_fn=None, score_fn=None) -> dict:
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.walk_forward import _train
    from swing_trade_ml.db.models.market import Instrument

    if train_fn is None:
        train_fn = _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn
    nifty, vix, breadth = load_market(db, upto)
    windows = choose_windows(nifty)
    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {s: df for s, df in load_bars(db, [i.tradingsymbol for i in instruments], upto).items() if len(df)}
    rows = []
    for w in windows:
        log.info("bad_market.window", kind=w.kind, peak=w.peak.isoformat(), trough=w.trough.isoformat())
        rows.append(
            run_window(
                db,
                w,
                nifty=nifty,
                vix=vix,
                breadth=breadth,
                instruments=instruments,
                bars=bars,
                train_fn=train_fn,
                score_fn=score_fn,
            )
        )
    return {
        "protocol": PROTOCOL_ID,
        "data_to": upto.isoformat(),
        "nifty_days": len(nifty),
        "stocks": len(bars),
        "windows": rows,
    }


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def _fall(x: float | None) -> str:
    return "n/a" if x is None else ("0.0%" if x <= 0 else f"-{x * 100:.1f}%")


def plain_report(result: dict) -> str:
    lines = [
        "# Bad-market test (ps2)",
        "",
        f"Protocol: `{result['protocol']}`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md). "
        f"{result['stocks']} watchlist stocks, NIFTY data to {result['data_to']}.",
        f"Windows chosen by rule: the {WORST_N} worst {FALL_BARS}-day NIFTY falls (not overlapping) and the "
        "longest NIFTY fall.",
        "",
        "## Did the banner turn careful in time?",
        "",
        "| Window | NIFTY fall | Banner at the peak | First careful day | Fall by then | First NO NEW TRADES "
        "| Careful falling days |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["windows"]:
        w, b = r["window"], r["banner"]
        fc, nn = b["first_careful"], b["first_no_new_trades"]
        lines.append(
            f"| {w['kind']}: {w['peak']} to {w['trough']} ({w['bars']} days) | {_pct(w['fall'])} | "
            f"{b['mode_at_peak'] or 'n/a'} | "
            + ("never" if fc is None else f"{fc['day']} (day {fc['days_after_peak']})")
            + " | "
            + (
                "-"
                if fc is None
                else f"{_pct(fc['nifty_fall_by_then'])} ({fc['share_of_fall_by_then']:.0%} of it)"
            )
            + " | "
            + ("never" if nn is None else nn["day"])
            + f" | {b['careful_days']} of {b['falling_days']} |"
        )
    lines += [
        "",
        f"## One ₹{CAPITAL:,.0f} account, model's best 5 a day: with the banner vs always NORMAL",
        "",
        "| Window | Worst fall (banner) | Worst fall (always NORMAL) | Return (banner) "
        "| Return (always NORMAL) | Trades (banner / NORMAL) | 15% halt reached |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["windows"]:
        w, a, n = r["window"], r["account"]["with_banner"], r["account"]["always_normal"]
        halt = "yes" if max(a["max_drawdown"], n["max_drawdown"]) >= MAX_DRAWDOWN else "no"
        lines.append(
            f"| {w['peak']} to {w['trough']} | {_fall(a['max_drawdown'])} | {_fall(n['max_drawdown'])} | "
            f"{_pct(a['total_return'])} | {_pct(n['total_return'])} | "
            f"{a['trades']} / {n['trades']} | {halt} |"
        )
    lines += [
        "",
        "## Ideas on careful days, each scored on its own",
        "",
        "| Window | Ideas | Hit the stop (losses avoided) | Hit +8% (gains missed) | Average result |",
        "|---|---|---|---|---|",
    ]
    for r in result["windows"]:
        w, c = r["window"], r["careful_day_ideas"]
        lines.append(
            f"| {w['peak']} to {w['trough']} | {c['finished']} | {c['hit_stop']} | {c['hit_target']} | "
            f"{_pct(c['avg_net'], 2)} |"
        )
    lines += [
        "",
        "## Limits",
        "",
        "- Development data only: a good result here is not evidence; a bad one is a real warning.",
        "- FII flows have no local history before 28 Sep 2026, so the FII rule (which only adds caution) "
        "is off: the live banner can be more careful than this replay.",
        "- The banner is the market judge (M10) alone. If M10 fails live, a backup judges instead; the "
        "4 'bolder on bad data' bugs found in qa6 were fixed in PR #33.",
        "- One model per window, trained before the report period starts, so it is older by the end.",
        "- Universe is today's watchlist (survivor bias); shares are whole; ₹10 lakh account.",
    ]
    return "\n".join(lines) + "\n"


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md, js = directory / "bad_market.md", directory / "bad_market.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Bad-market test: banner timing and account falls (ps2)")
    p.add_argument("--upto", default="2026-09-07", help="YYYY-MM-DD: last day of local data used")
    p.add_argument("--windows-only", action="store_true", help="only print the windows the rule picks")
    p.add_argument("--out", default="../docs/brain/evidence/bad_market")
    a = p.parse_args(argv)
    upto = date.fromisoformat(a.upto)
    with SessionLocal() as db:
        if a.windows_only:
            nifty, _, _ = load_market(db, upto)
            for w in choose_windows(nifty):
                print(f"{w.kind}: {w.peak} to {w.trough}, {w.bars} days, {w.fall:+.1%}")
            return 0
        result = run(db, upto=upto)
    md, js = write_report(result, Path(a.out))
    print(plain_report(result))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
