# backend/src/swing_trade_ml/brain/five_day.py
# ruff: noqa: E501 (long lines are report sentences)
"""Five-day strategy protocol (fd-protocol-v1), layer 1: the 5-day model judged on history.

Spec: `docs/superpowers/specs/2026-10-24-five-day-protocol.md` (signed 2026-10-24). Read-only evidence
tool, the 5-day twin of `walk_forward` (wf-protocol-v1, which stays exactly as it was):

- The model's question and the trade are kept apart. Each fold's model learns the ENDPOINT question
  the active prod models (ids 2, 16, 17) were trained on: is the close 5 trading days later at least
  +2% above today's close? (`ml/train.train_model(label_kind="endpoint")`.) Every trade is scored as
  prod runs it (D1), on daily bars:
  enter at the next day's open; target +2% and stop -4% from the decision day's close (as
  `strategies/ml_swing.py` sets them); stop checked before target, so a day touching both is the
  stop; prod's trailing stop; no half-out (the +2% target always comes first); sold at the next open
  after a close where the fold model scores the stock at or below ML_EXIT_CONFIDENCE (0.35); time
  stop at the open of the first trading day on or after entry + 30 calendar days (prod's first exit
  check once 30 days have passed), from the days the market really traded; costs and slippage.
  Every choice is written in the protocol's "Clarifications recorded before the tag".
- The same trade sold at the close of day 5 at the latest is reported alongside, never counted.
- Two pick modes (owner decision D2): the best 5 by model score for the skill part; the prod buy rule
  of `strategies/ml_swing.py` (score >= ML_MIN_CONFIDENCE, +0.10 when NIFTY is in a downtrend, the
  liquidity, volatility and falling-knife filters, all point-in-time) for the money part.
- The decision rule is wf-protocol-v1's (same thresholds, D4), with confidence blocks of 21 trading
  days for the 30-calendar-day hold and 5 for the day-5 variant. Benchmarks are the
  evidence-defs-v2 set reused from `phase_b` (every stock, random 5, 200 random-5 accounts, 5
  strongest 20-day risers, NIFTY held, cash). "Rules only" waits for tv7.

GUARD. A real run refuses unless the git tag `fd-protocol-v1` is in HEAD's history and this file and
the protocol are unchanged since the tag, and it runs once (an existing report blocks it). Layer 2
(the forward test) is not built: D6 waits for tv22. Nothing here is imported by live code.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.horizon_grid import _group, _index_after, summarise, top_k_by_day
from swing_trade_ml.brain.replay_scoring import NORMAL, CostStress, StrictOutcome
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.services.exit_policy import DEFAULT_TIME_STOP_DAYS

log = get_logger(__name__)

PROTOCOL_VERSION = "fd-protocol-v1"
TAG = PROTOCOL_VERSION  # the owner tags the merge commit with this name; no real run before it
SPEC = "docs/superpowers/specs/2026-10-24-five-day-protocol.md"
# Must equal the tagged version: the tool, the protocol, and the trainer that builds the endpoint label.
FROZEN_FILES = (
    "backend/src/swing_trade_ml/brain/five_day.py",
    SPEC,
    "backend/src/swing_trade_ml/ml/train.py",
)
CONFIRMATION = (date(2023, 7, 1), date(2025, 1, 31))  # section 5: the only pass-or-fail sample
OUT_DIR = "docs/brain/evidence/fd_v1"

LABEL_HORIZON = 5  # trading days the model's question looks ahead
TARGET = 0.02  # pinned: a local .env must not change a result
STOP = 0.04
DAY5_BARS = 5  # the reported-only variant: the trade closed at the end of day 5
TOP_K = 5
HOLD_BLOCK = 21  # trading days per bootstrap block for the 30-calendar-day hold (section 3)
DAY5_BLOCK = 5  # ... and for the day-5 variant
LOAD_EXTRA_DAYS = 60  # calendar days of prices loaded after the last test day so its trades can finish
PORTFOLIO_CAPITAL = 1_000_000.0  # as phase_b (evidence-defs-v2)
RULES_ONLY_MISSING = "missing: waits for tv7 to name the official 'rules only' yardstick (D5)"


TIME_STOP_DAYS = DEFAULT_TIME_STOP_DAYS  # 30 calendar days, the settled rule prod runs


# ---------------------------------------------------------------- the prod buy rule (ml_swing)


@dataclass(frozen=True, slots=True)
class BuyRule:
    """`strategies/ml_swing.py` BUY conditions, read from the strategy itself, not copied."""

    min_confidence: float
    bear_boost: float
    min_avg_volume: float
    max_volatility: float
    falling_knife: float
    min_bars: int


def prod_buy_rule() -> BuyRule:
    """The class defaults of `MLSwingStrategy` and the code default of ML_MIN_CONFIDENCE (0.60), so a
    local .env cannot move the line. A prod strategy row may override them; the protocol fixes 60%."""
    from swing_trade_ml.core.config import Settings
    from swing_trade_ml.strategies.ml_swing import MLSwingStrategy

    p = MLSwingStrategy.default_params
    return BuyRule(
        min_confidence=float(p["min_confidence"] or Settings.model_fields["ML_MIN_CONFIDENCE"].default),
        bear_boost=float(p["bear_market_confidence_boost"]),
        min_avg_volume=float(p["min_avg_volume"]),
        max_volatility=float(p["max_volatility"]),
        falling_knife=float(p["falling_knife_return_5d_pct"]),
        min_bars=MLSwingStrategy.min_bars_required(None),  # `self` is not used by it
    )


def nifty_downtrend(nifty: pd.DataFrame) -> dict[date, bool]:
    """Per day: is NIFTY in a downtrend at that day's close (SMA50 below SMA200)? The model feature
    `nifty_trend_regime` the strategy reads, from `ml/features._index_context_frame`; rolling
    averages only look back, so each day's value uses that day's close and earlier ones only."""
    from swing_trade_ml.ml.features import _index_context_frame

    if nifty is None or nifty.empty:
        return {}
    ctx = _index_context_frame(nifty.rename(columns={"day": "ts"})[["ts", "close"]])
    return {d: float(v) < 0 for d, v in zip(ctx["ts"], ctx["nifty_trend_regime"], strict=True)}


def stock_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Per bar, the strategy's filter inputs known at that close: 20-day average volume, 20-day
    volatility of daily returns, 14-day ATR, 5-day return and how many bars exist so far."""
    from swing_trade_ml.ml.features import atr

    close = df["close"].astype(float)
    return pd.DataFrame(
        {
            "day": df["day"],
            "avg_volume": df["volume"].astype(float).rolling(20).mean(),
            "daily_vol": close.pct_change().rolling(20).std(),
            "atr": atr(df["high"].astype(float), df["low"].astype(float), close, 14),
            "ret5": close.pct_change(5),
            "bars": range(1, len(df) + 1),
        }
    )


def passes_buy_rule(score: float, f: Mapping, *, bear: bool, rule: BuyRule) -> bool:
    """The strategy's BUY test, in its order and with its comparisons (a missing value blocks
    nothing, exactly as there)."""
    if f["bars"] < rule.min_bars:
        return False
    if score < rule.min_confidence + (rule.bear_boost if bear else 0.0):
        return False
    blocked = (
        f["avg_volume"] < rule.min_avg_volume
        or f["daily_vol"] > rule.max_volatility
        or f["atr"] <= 0
        or f["ret5"] <= rule.falling_knife
    )
    return not blocked


def buy_rule_picks(
    scores: Mapping[str, Mapping[date, float]],
    bars: Mapping[str, pd.DataFrame],
    nifty: pd.DataFrame,
    days: Sequence[date],
    rule: BuyRule | None = None,
) -> tuple[dict[date, list[str]], dict]:
    """Every stock the prod buy rule would buy on each day, best score first. A day whose NIFTY
    trend is unknown counts as a downtrend (the cautious reading). Returns (picks, day counts)."""
    rule = rule or prod_buy_rule()
    bear = nifty_downtrend(nifty)
    filt = {s: stock_filters(df).set_index("day") for s, df in bars.items() if "volume" in df}
    picks: dict[date, list[str]] = {}
    unknown = bear_days = 0
    for d in days:
        is_bear = bear.get(d)
        if is_bear is None:
            unknown += 1
            is_bear = True
        bear_days += 1 if is_bear else 0
        ranked = []
        for sym, per in scores.items():
            if d not in per or sym not in filt or d not in filt[sym].index:
                continue
            if passes_buy_rule(per[d], filt[sym].loc[d], bear=is_bear, rule=rule):
                ranked.append((per[d], sym))
        picks[d] = [s for _, s in sorted(ranked, key=lambda x: (-x[0], x[1]))]
    return picks, {"days": len(days), "bear_days": bear_days, "nifty_unknown_days": unknown}


# ---------------------------------------------------------------- holding time and outcomes (as prod runs)

OPEN = StrictOutcome("open", None, None, False, False, None)


@dataclass(frozen=True, slots=True)
class Exit:
    day: date
    price: float  # before the sell's slippage and charges
    reason: str  # target | stop | timeout (time stop) | confidence (model score fell)


def prod_exit_confidence() -> float:
    """The score at or below which prod's ml_swing sells a held stock: `exit_policy.exit_confidence_for`
    -> `real_question.exit_confidence()` -> ML_EXIT_CONFIDENCE with the real-question switch off (prod),
    read as the code default (0.35) so a local .env cannot move it. Prod strategy rows set no override."""
    from swing_trade_ml.core.config import Settings

    return float(Settings.model_fields["ML_EXIT_CONFIDENCE"].default)


def trading_calendar(bars: Mapping[str, pd.DataFrame], *extra: pd.DataFrame) -> list[date]:
    """The days the market really traded: every day any loaded stock or index has a bar. (The app's
    NSE holiday list starts in 2025, so it cannot serve 2023-2024.)"""
    seen = {d for df in (*bars.values(), *extra) if df is not None for d in df["day"]}
    return sorted(seen)


def time_stop_day(entry: date, calendar: Sequence[date], days: int = TIME_STOP_DAYS) -> date | None:
    """Prod's time stop: the first exit check once `days` calendar days have passed since the buy,
    i.e. the first trading day on or after `entry` + `days`; the sale is at that day's open. None
    while the calendar does not reach that far."""
    i = bisect.bisect_left(calendar, entry + timedelta(days=days))
    return calendar[i] if i < len(calendar) else None


def weak_days(scores: Mapping[str, Mapping[date, float]], line: float | None = None) -> dict[str, set[date]]:
    """Per stock, the days whose close-of-day model score is at or below the exit line."""
    line = prod_exit_confidence() if line is None else line
    return {s: {d for d, p in per.items() if p <= line} for s, per in scores.items()}


def score_trade(
    df: pd.DataFrame,
    k: int,
    *,
    ref_close: float,
    sell_open_at: int | None = None,
    open_reason: str = "timeout",
    sell_close_at: int | None = None,
    stress: CostStress = NORMAL,
    trail: bool = True,
) -> tuple[StrictOutcome, Exit | None]:
    """One trade as prod manages it, on daily bars. Buy at the open of bar `k` (the day after the
    decision). Levels come from the decision day's close (`ref_close`), as `strategies/ml_swing.py`
    sets them: target +2%, stop -4%. Each bar, in prod's order (`services/execution.check_exits`):
    the stop (a gap fills at the open), then the target; a bar touching both is the stop. Then the
    trailing stop (`execution.trail_stop`): it rises to the highest price so far minus the starting
    distance (fill - first stop). A daily bar cannot say whether its low came before its high, so a
    raised stop counts as hit that day only when the close is at or below it (certain), and from the
    next day otherwise. `sell_open_at`: sell everything at that bar's open (time stop or confidence
    exit; reported as stop or target if the open is already past one). `sell_close_at`: sell at that
    bar's close (the day-5 variant). Neither reached before the data ends = still open."""
    from swing_trade_ml.brain.replay_scoring import POSITION_INR, _sell
    from swing_trade_ml.services.costs import apply_slippage, compute_charges

    fill = apply_slippage(float(df.iloc[k]["open"]), "BUY") * (1 + stress.extra_slip)
    qty = POSITION_INR / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    cash_in = fill * qty + (brokerage + taxes) * stress.charges_x
    stop_px, target_px = ref_close * (1 - STOP), ref_close * (1 + TARGET)
    distance = fill - stop_px
    highest = fill

    def done(status: str, price: float, i: int, gap: bool) -> tuple[StrictOutcome, Exit]:
        day = df.iloc[i]["day"]
        net = _sell(price, qty, stress) / cash_in - 1.0
        return StrictOutcome(status, net, i - k + 1, False, gap, day), Exit(day, price, status)

    for i in range(k, len(df)):
        row = df.iloc[i]
        o, h, lo, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if sell_open_at is not None and i == sell_open_at and i > k:
            status = "stop" if o <= stop_px else "target" if o >= target_px else open_reason
            return done(status, o, i, status != open_reason)
        if lo <= stop_px:
            return done("stop", o if o <= stop_px else stop_px, i, o <= stop_px)
        if h >= target_px:
            return done("target", o if o >= target_px else target_px, i, o >= target_px)
        if trail and distance > 0:
            highest = max(highest, h)
            if highest - distance > stop_px:
                stop_px = highest - distance
                if c <= stop_px:
                    return done("stop", stop_px, i, False)
        if sell_close_at is not None and i == sell_close_at:
            return done("timeout", c, i, False)
    return OPEN, None


def _first_weak(bar_days: Sequence[date], k: int, weak: set[date], upto: int) -> int | None:
    """First bar index from `k` (before `upto`) whose close scored at or below the exit line."""
    for i in range(k, min(upto, len(bar_days))):
        if bar_days[i] in weak:
            return i
    return None


def outcomes_prod(
    bars: Mapping[str, pd.DataFrame],
    days: Sequence[date],
    calendar: Sequence[date],
    weak: Mapping[str, set[date]],
    *,
    variant: str = "hold",
    stress: CostStress = NORMAL,
) -> tuple[dict[tuple[str, date], StrictOutcome], dict[tuple[str, date], Exit]]:
    """Every stock and decision day. `variant="hold"`: prod's trade, up to the 30-calendar-day time
    stop (sold at the open of the first trading day on or after entry + 30) or the model-confidence
    exit (sold at the next open after a close scoring at or below 0.35), whichever comes first.
    `variant="day5"`: the same trade, sold at the close of day 5 at the latest (reported only)."""
    outs: dict[tuple[str, date], StrictOutcome] = {}
    exits: dict[tuple[str, date], Exit] = {}
    for sym, df in bars.items():
        bar_days = list(df["day"])
        pos = {d: i for i, d in enumerate(bar_days)}
        w = weak.get(sym, set())
        for day in days:
            if day not in pos:
                continue
            k = _index_after(bar_days, day)
            if k is None:
                continue
            ref = float(df.iloc[pos[day]]["close"])
            if variant == "day5":
                last = k + DAY5_BARS - 1
                j = _first_weak(bar_days, k, w, last)
                if j is not None:
                    o, e = score_trade(
                        df, k, ref_close=ref, sell_open_at=j + 1, open_reason="confidence", stress=stress
                    )
                else:
                    o, e = score_trade(df, k, ref_close=ref, sell_close_at=last, stress=stress)
            else:
                t = time_stop_day(bar_days[k], calendar)
                jt = bisect.bisect_left(bar_days, t) if t is not None else None
                if jt is not None and jt >= len(bar_days):
                    jt = None
                j = _first_weak(bar_days, k, w, jt if jt is not None else len(bar_days))
                if j is not None and (jt is None or j + 1 < jt):
                    o, e = score_trade(
                        df, k, ref_close=ref, sell_open_at=j + 1, open_reason="confidence", stress=stress
                    )
                else:
                    o, e = score_trade(df, k, ref_close=ref, sell_open_at=jt, stress=stress)
            outs[(sym, day)] = o
            if e is not None:
                exits[(sym, day)] = e
    return outs, exits


def breakeven_hit_rate(stress: CostStress = NORMAL) -> dict:
    """Share of trades that must reach +2% (the rest hitting -4%) to break even: before costs, and
    after costs and slippage at the cost model's rates."""

    def one(high: float, low: float) -> float:
        df = pd.DataFrame(
            [
                {"day": date(2024, 1, 1), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
                {"day": date(2024, 1, 2), "open": 100.0, "high": high, "low": low, "close": 100.0},
            ]
        )
        return score_trade(df, 1, ref_close=100.0, stress=stress, trail=False)[0].net_return

    win, loss = one(110.0, 99.9), one(100.0, 90.0)
    return {
        "before_costs": STOP / (TARGET + STOP),
        "after_costs": -loss / (win - loss),
        "win_net": win,
        "loss_net": loss,
    }


# ---------------------------------------------------------------- the decision rule (section 6)


def fold_eligible(days: int, trades: int) -> bool:
    return days >= wf.MIN_FOLD_DAYS and trades >= wf.MIN_FOLD_IDEAS


def decide(
    *,
    skill_eligible: int,
    skill_wins: int,
    skill_trades: int,
    edge_low: float | None,
    money_eligible: int,
    money_wins: int,
    money_trades: int,
    money_avg_per_trade: float | None,
) -> dict:
    """Two answers, each from its own pick mode, with wf-protocol-v1's thresholds (D4). Fewer than
    12 eligible folds or 100 finished trades in a part, or a missing check value: 'insufficient'."""
    skill = wf._part(
        skill_eligible,
        skill_wins,
        None if (edge_low is None or skill_trades < wf.MIN_IDEAS) else edge_low > 0,
        f"lower bound of the 5-day daily edge over every stock above zero ({HOLD_BLOCK}-trading-day blocks)",
    )
    money = wf._part(
        money_eligible,
        money_wins,
        None if (money_avg_per_trade is None or money_trades < wf.MIN_IDEAS) else money_avg_per_trade > 0,
        "5-day average per trade after costs over all folds above zero",
    )
    skill["trades"], money["trades"] = skill_trades, money_trades
    table = {
        ("pass", "pass"): "Layer 1 passes both parts. Not proven: layer 2 (forward) must pass too.",
        ("pass", "fail"): "Picks beat every stock, but the prod buy rule's trades do not make money.",
        ("fail", "pass"): "The prod buy rule's trades made money, but the picks did not beat every stock.",
        ("fail", "fail"): "No evidence of skill and no profit for the 5-day strategy.",
    }
    return {
        "predictive": skill,
        "economic": money,
        "reading": table.get(
            (skill["word"], money["word"]), "Not enough data for a full answer (insufficient)."
        ),
    }


# ---------------------------------------------------------------- evaluation (pure)


@dataclass
class Inputs:
    bars: dict[str, pd.DataFrame]  # day, open, high, low, close, volume per stock
    nifty: pd.DataFrame  # day, open, high, low, close
    scores: dict[str, dict[date, float]]  # each day scored by its own fold's model only
    folds: list[wf.Fold]
    models: list[dict] = field(default_factory=list)  # per fold: name, cutoff, auc
    buckets: dict[str, str | None] = field(default_factory=dict)


def _on(picks: Mapping[date, list[str]], days: Iterable[date]) -> dict[date, list[str]]:
    keep = set(days)
    return {d: list(s) for d, s in picks.items() if d in keep}


def _in(picks: Mapping[date, list[str]], fold: wf.Fold) -> dict[date, list[str]]:
    return {d: list(s) for d, s in picks.items() if fold.start <= d <= fold.end}


def _with_picks(picks: Mapping[date, list[str]]) -> list[date]:
    return sorted(d for d, s in picks.items() if s)


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _avg_day(s: dict) -> float | None:
    return s["avg_net_by_day"]


def _part_block(
    picks, everyone, momentum, hold, d5, everyone5, nifty, *, draws: int, block_days: bool
) -> dict:
    """One pick mode against the benchmarks on its own days. `block_days`: compare on the days the
    mode picked something (the buy rule); otherwise on every day (best 5)."""
    from swing_trade_ml.brain.phase_b import nifty_matched, random5_trade

    days = _with_picks(picks) if block_days else sorted(picks)
    every, every5, mom = _on(everyone, days), _on(everyone5, days), _on(momentum, days)
    model = summarise(_group(picks, hold))
    edges = wf.daily_edge(picks, everyone, hold)
    edges5 = wf.daily_edge(picks, everyone5, d5)
    out = {
        "model": model,
        "every_stock": summarise(_group(every, hold)),
        "momentum": summarise(_group(mom, hold)),
        "random_5": random5_trade(days, everyone, hold, candidate_avg=model["avg_net"], draws=draws),
        "nifty_matched": nifty_matched(picks, hold, nifty),
        "cash": {"avg_net": 0.0},
        "rules_only": RULES_ONLY_MISSING,
        "edge_per_day": _mean(edges),
        "edge_low": wf.bootstrap_low(edges, block=HOLD_BLOCK),
        "edge_days": len(edges),
        "day5": {
            "model": summarise(_group(picks, d5)),
            "every_stock": summarise(_group(every5, d5)),
            "edge_per_day": _mean(edges5),
            "edge_low": wf.bootstrap_low(edges5, block=DAY5_BLOCK),
            "note": "reported only, never in pass or fail",
        },
        "days_with_picks": len(_with_picks(picks)),
    }
    return out


def _fold_part(picks, everyone, momentum, hold, d5, everyone5, nifty, *, block_days: bool) -> dict:
    from swing_trade_ml.brain.phase_b import nifty_matched

    days = _with_picks(picks) if block_days else sorted(picks)
    return {
        "model": summarise(_group(picks, hold)),
        "every_stock": summarise(_group(_on(everyone, days), hold)),
        "momentum": summarise(_group(_on(momentum, days), hold)),
        "nifty_matched": nifty_matched(picks, hold, nifty)["avg_net"],
        "day5_model": summarise(_group(picks, d5)),
        "day5_every_stock": summarise(_group(_on(everyone5, days), d5)),
    }


def _account(picks: Mapping[date, list[str]], scores, bars, pdays, buckets, exits, *, seed_picks=None):
    """One account (portfolio_sim) whose positions leave exactly when the per-idea scoring says."""
    from swing_trade_ml.brain.phase_b import _risk
    from swing_trade_ml.brain.portfolio_sim import Pick, simulate

    chosen = seed_picks
    if chosen is None:
        chosen = [
            Pick(d, s, float(scores.get(s, {}).get(d, len(syms) - i)), buckets.get(s))
            for d, syms in sorted(picks.items())
            for i, s in enumerate(syms)
        ]

    def plan(sym: str, day: date):
        e = exits.get((sym, day))
        return None if e is None else (e.day, e.price, e.reason)

    r = simulate(chosen, dict(bars), list(pdays), capital=PORTFOLIO_CAPITAL, exit_plan=plan)
    return _risk(r)


def portfolio_level(
    inp: Inputs, top5, rule, momentum, everyone, days, calendar, exits, *, draws: int
) -> dict:
    """Reported only: each pick mode and the evidence-defs-v2 accounts through one account each
    (ladder limits, sector cap, top-5-a-day, 15% halt, costs), with the 5-day trade rule."""
    import statistics

    from swing_trade_ml.brain.phase_b import CASH, RANDOM_SEED, _quantile, nifty_buy_and_hold
    from swing_trade_ml.brain.portfolio_sim import random_picks

    pdays = [d for d in calendar if d >= days[0]]
    pool = {d: everyone[d] for d in days if everyone.get(d)}
    runs = [
        _account(
            {},
            {},
            inp.bars,
            pdays,
            inp.buckets,
            exits,
            seed_picks=random_picks(pool, dict.fromkeys(pool, TOP_K), RANDOM_SEED + n, dict(inp.buckets)),
        )
        for n in range(draws)
    ]
    rets = [r["final_net_return"] for r in runs]
    return {
        "best_5": _account(top5, inp.scores, inp.bars, pdays, inp.buckets, exits),
        "buy_rule": _account(rule, inp.scores, inp.bars, pdays, inp.buckets, exits),
        "momentum_5": _account(momentum, {}, inp.bars, pdays, inp.buckets, exits),
        "random_5_accounts": {
            "runs": draws,
            "final_net_return_median": statistics.median(rets) if rets else None,
            "p5": _quantile(rets, 0.05),
            "p95": _quantile(rets, 0.95),
            "max_drawdown_median": statistics.median(r["max_drawdown"] for r in runs) if runs else None,
            "halt_triggered_runs": sum(r["halt_triggered"] for r in runs),
        },
        "nifty_held": nifty_buy_and_hold(inp.nifty, pdays) if not inp.nifty.empty else None,
        "cash": dict(CASH),
        "rules_only": RULES_ONLY_MISSING,
    }


def evaluate(
    inp: Inputs,
    *,
    random_draws: int | None = None,
    portfolio_draws: int | None = None,
    stresses: Sequence[CostStress] | None = None,
    sample: str | None = None,
) -> dict:
    """Score both pick modes per fold and overall, apply the decision rule. Pure: no database."""
    from swing_trade_ml.brain.phase_b import PORTFOLIO_DRAWS, RANDOM_DRAWS

    random_draws = RANDOM_DRAWS if random_draws is None else random_draws
    portfolio_draws = PORTFOLIO_DRAWS if portfolio_draws is None else portfolio_draws
    if stresses is None:
        from swing_trade_ml.brain.cost_stress import STRESSES

        stresses = STRESSES
    first, last = inp.folds[0].start, inp.folds[-1].end
    days = sorted({d for df in inp.bars.values() for d in df["day"] if first <= d <= last})
    calendar = trading_calendar(inp.bars, inp.nifty)
    weak = weak_days(inp.scores)
    hold, exits = outcomes_prod(inp.bars, days, calendar, weak)
    d5, _ = outcomes_prod(inp.bars, days, calendar, weak, variant="day5")
    everyone = {d: sorted(s for (s, dd) in hold if dd == d) for d in days}
    everyone5 = {d: sorted(s for (s, dd) in d5 if dd == d) for d in days}
    top5 = top_k_by_day(inp.scores, days, TOP_K)
    rule, rule_days = buy_rule_picks(inp.scores, inp.bars, inp.nifty, days)
    momentum = top_k_by_day(wf.momentum_scores(inp.bars, days), days, TOP_K)

    fold_rows = []
    for fold in inp.folds:
        fdays = [d for d in days if fold.start <= d <= fold.end]
        if not fdays:
            continue
        regime = wf.classify_regime(inp.bars, fold.start, fold.end)
        args = (everyone, momentum, hold, d5, everyone5, inp.nifty)
        fold_rows.append(
            {
                "start": fold.start.isoformat(),
                "end": fold.end.isoformat(),
                "cutoff": fold.cutoff.isoformat(),
                "days": len(fdays),
                "regime": regime,
                "skill": _fold_part(_in(top5, fold), *args, block_days=False),
                "money": _fold_part(_in(rule, fold), *args, block_days=True),
                "model_auc": next(
                    (m.get("auc") for m in inp.models if m.get("cutoff") == fold.cutoff.isoformat()), None
                ),
            }
        )
    for r in fold_rows:
        s, m = r["skill"], r["money"]
        r["skill"]["eligible"] = fold_eligible(r["days"], s["model"]["ideas"])
        r["skill"]["won"] = (
            _avg_day(s["model"]) is not None
            and _avg_day(s["every_stock"]) is not None
            and _avg_day(s["model"]) > _avg_day(s["every_stock"])
        )
        r["money"]["eligible"] = fold_eligible(r["days"], m["model"]["ideas"])
        r["money"]["won"] = _avg_day(m["model"]) is not None and _avg_day(m["model"]) > 0

    args = (everyone, momentum, hold, d5, everyone5, inp.nifty)
    skill = _part_block(top5, *args, draws=random_draws, block_days=False)
    money = _part_block(rule, *args, draws=random_draws, block_days=True)
    money["days"] = rule_days
    s_el = [r for r in fold_rows if r["skill"]["eligible"]]
    m_el = [r for r in fold_rows if r["money"]["eligible"]]
    verdict = decide(
        skill_eligible=len(s_el),
        skill_wins=sum(r["skill"]["won"] for r in s_el),
        skill_trades=skill["model"]["ideas"],
        edge_low=skill["edge_low"],
        money_eligible=len(m_el),
        money_wins=sum(r["money"]["won"] for r in m_el),
        money_trades=money["model"]["ideas"],
        money_avg_per_trade=money["model"]["avg_net"],
    )

    def worst(rows, key):
        vals = [
            (_avg_day(r[key]["model"]), r["start"]) for r in rows if _avg_day(r[key]["model"]) is not None
        ]
        return None if not vals else {"avg_net_by_day": min(vals)[0], "fold_start": min(vals)[1]}

    stress_rows = []
    for st in stresses:
        h = hold if st == NORMAL else outcomes_prod(inp.bars, days, calendar, weak, stress=st)[0]
        stress_rows.append(
            {
                "costs": st.label,
                "best_5": summarise(_group(top5, h))["avg_net"],
                "every_stock": summarise(_group(everyone, h))["avg_net"],
                "buy_rule": summarise(_group(rule, h))["avg_net"],
            }
        )
    confirmation = (first, last) == CONFIRMATION
    return {
        "protocol": PROTOCOL_VERSION,
        "horizon": "5-day",
        "sample": sample
        or (
            "confirmation (pass or fail, layer 1)"
            if confirmation
            else "not the confirmation sample: reported only, never pass or fail"
        ),
        "counts_for_pass_fail": confirmation,
        "window": [first.isoformat(), last.isoformat()],
        "rule": {
            "label": f"endpoint: close {LABEL_HORIZON} trading days later at least +{TARGET:.0%} above the decision day's close (as prod models 2, 16, 17)",
            "trade": (
                f"next open; +{TARGET:.0%} target / -{STOP:.0%} stop from the decision day's close; trailing stop; "
                f"no half-out; sold at the next open after a close scoring at or below {prod_exit_confidence():.2f}; "
                f"time stop at the open of the first trading day on or after entry + {TIME_STOP_DAYS} calendar days; "
                "costs and slippage"
            ),
            "variant": f"the same trade sold at the close of day {DAY5_BARS} at the latest (reported only)",
            "same_day": "target and stop on the same day count as the stop",
            "blocks": {"hold": HOLD_BLOCK, "day5": DAY5_BLOCK},
            "buy_rule": _rule_dict(prod_buy_rule()),
        },
        "stocks": len(inp.bars),
        "models": inp.models,
        "folds": fold_rows,
        "skill": skill,
        "money": money,
        "verdict": verdict,
        "worst_fold": {"skill": worst(s_el, "skill"), "money": worst(m_el, "money")},
        "breakeven": breakeven_hit_rate(),
        "cost_stress": stress_rows,
        "portfolio": portfolio_level(
            inp, top5, rule, momentum, everyone, days, calendar, exits, draws=portfolio_draws
        ),
        "exit_reasons": _reasons(top5, rule, hold),
        "layer2": "not built: the forward test waits for the owner's D6 / tv22 decision",
    }


def _reasons(top5, rule, hold) -> dict:
    """How the finished trades ended, per pick mode (target, stop, timeout, confidence)."""
    from collections import Counter

    out = {}
    for name, picks in (("best_5", top5), ("buy_rule", rule)):
        c = Counter(hold[(s, d)].status for d, syms in picks.items() for s in syms if (s, d) in hold)
        out[name] = dict(sorted(c.items()))
    return out


def _rule_dict(r: BuyRule) -> dict:
    return {k: getattr(r, k) for k in r.__slots__}


# ---------------------------------------------------------------- report (section 7)

LIMITS = (
    "Sample (section 5): 'never scored with a 5-day rule' is not 'never seen'. The confirmation period "
    "2023-07-01 to 2025-01-31 was studied for the 15-day brain (walk-forward, bad-market windows, cost stress).",
    "Survivor bias: the universe is today's 49 model stocks; stocks delisted or dropped earlier are missing.",
    "Daily candles cannot say whether target or stop came first on the same day: counted as the stop.",
    "Layer 1 has no account: every buy-rule idea is scored on its own (no slot limit, no 'already held', "
    "no risk sizing). The account replay below is reported only.",
    "Daily candles only: prod checks exits every minute; here a raised trailing stop counts on the day it "
    "rises only when the close is at or below it, and exits at an open use the open price.",
    "Prod scores with 3 cap-tier models (main, midcap, smallcap); this tool trains one endpoint model per "
    "fold on the 49 stocks, like the 15-day protocol. It is not the exact model in prod.",
    "A trade decided near a fold's end is watched for the confidence exit by the next fold's model (the "
    "last fold's model after the sample ends), as prod watches with whichever model is active.",
    "The v1 bot and the brain share the paper account's slots, so forward results are not independent until D6.",
    "A pass never justifies live trading. Layer 2, manual approval and the owner's go-live call come first.",
)


def _pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def plain_report(result: dict, manifest: dict | None = None) -> str:
    v, sk, mo = result["verdict"], result["skill"], result["money"]
    be = result["breakeven"]
    lines = [
        f"# 5-day strategy, layer 1 ({result['protocol']})",
        "",
        "Every number on this page is a **5-day** figure (the 5-day v1 strategy). None is a 15-day figure; "
        "never add or compare them with the 15-day brain's numbers without the label.",
        "",
        f"Protocol: {result['protocol']} (`{SPEC}`). Sample: {result['window'][0]} to {result['window'][1]}, "
        f"{result['sample']}. {result['stocks']} stocks.",
        f"5-day model question: {result['rule']['label']}. 5-day trade scored: {result['rule']['trade']}. "
        f"{result['rule']['same_day'].capitalize()}.",
        "",
    ]
    if manifest:
        lines += ["## Manifest", "", "| Item | Value |", "|---|---|"]
        lines += [f"| {k} | {val} |" for k, val in manifest.items()]
        lines.append("")
    lines += [
        f"## 5-day verdict: {v['reading']}",
        "",
        ""
        if result["counts_for_pass_fail"]
        else "**Not the confirmation sample: these words are not a verdict.**",
        "| Part (5-day) | Picks | Answer | Folds won | Finished trades | Also needed |",
        "|---|---|---|---|---|---|",
        f"| Predictive skill | best {TOP_K} by score | {v['predictive']['word']} | {v['predictive']['folds_won']} of "
        f"{v['predictive']['eligible_folds']} | {v['predictive']['trades']} | {v['predictive']['check']} |",
        f"| Economic value | prod buy rule | {v['economic']['word']} | {v['economic']['folds_won']} of "
        f"{v['economic']['eligible_folds']} | {v['economic']['trades']} | {v['economic']['check']} |",
        f"| Beats the benchmarks (layer 2) | the v1 paper bot | not started | | | {result['layer2']} |",
        "",
        f"Rule: an eligible fold has at least {wf.MIN_FOLD_DAYS} test days and {wf.MIN_FOLD_IDEAS} finished trades of "
        f"that part's picks; a part needs at least {wf.MIN_FOLDS} eligible folds and {wf.MIN_IDEAS} finished trades, "
        f"else 'insufficient'; at least {wf.FOLDS_SHARE:.0%} of eligible folds won. Both layers must pass before the "
        "5-day strategy counts as proven.",
        "",
        f"5-day hit rate needed to break even: {_pct(be['before_costs'], 1)} before costs, {_pct(be['after_costs'], 1)} "
        f"after costs (a +2% win nets {_pct(be['win_net'])}, a -4% loss nets {_pct(be['loss_net'])}).",
        "",
    ]
    wk = result["worst_fold"]
    for name, key in (("best 5", "skill"), ("buy rule", "money")):
        w = wk[key]
        lines.append(
            f"Worst eligible fold, {name}, 5-day average per day: "
            + ("n/a" if w is None else f"{_pct(w['avg_net_by_day'])} (from {w['fold_start']})")
            + "."
        )
    port = result["portfolio"]
    lines += [
        f"Worst fall in the account replay (5-day, reported only): best 5 {_pct(port['best_5']['max_drawdown'], 1)}, "
        f"buy rule {_pct(port['buy_rule']['max_drawdown'], 1)}.",
        "",
        "## All folds together (5-day, after costs)",
        "",
        "| 5-day | Best 5: trades | hit rate | avg per trade | Buy rule: trades | hit rate | avg per trade |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, key in (
        ("Picks", "model"),
        ("Every stock (same days)", "every_stock"),
        ("5 strongest 20-day risers", "momentum"),
    ):
        a, b = sk[key], mo[key]
        lines.append(
            f"| {label} | {a['ideas']} | {_pct(a['hit_rate'], 0)} | {_pct(a['avg_net'])} | {b['ideas']} | "
            f"{_pct(b['hit_rate'], 0)} | {_pct(b['avg_net'])} |"
        )
    lines += [
        f"| Random 5 ({sk['random_5']['draws']} draws, mean) | | | {_pct(sk['random_5']['avg_net_mean'])} | | | {_pct(mo['random_5']['avg_net_mean'])} |",
        f"| NIFTY 50, same holding periods | {sk['nifty_matched']['ideas']} | | {_pct(sk['nifty_matched']['avg_net'])} | "
        f"{mo['nifty_matched']['ideas']} | | {_pct(mo['nifty_matched']['avg_net'])} |",
        "| Cash | | | 0.00% | | | 0.00% |",
        f"| Rules only | | | {RULES_ONLY_MISSING} | | | |",
        "",
        f"5-day daily edge of the best 5 over every stock: {_pct(sk['edge_per_day'], 3)} "
        f"(lower bound {_pct(sk['edge_low'], 3)}, {HOLD_BLOCK}-day blocks, {sk['edge_days']} days). "
        f"Buy rule: {mo['days_with_picks']} days with picks; {mo['days']['bear_days']} of {mo['days']['days']} "
        f"days with the +10-point NIFTY downtrend boost ({mo['days']['nifty_unknown_days']} with NIFTY unknown, counted as downtrend).",
        "",
        "How the finished 5-day trades ended (target / stop incl. trailing / time stop / confidence exit): "
        f"best 5 {result['exit_reasons']['best_5']}; buy rule {result['exit_reasons']['buy_rule']}.",
        "",
        "## Reported only: the same 5-day trade sold at the close of day 5 at the latest (never in pass or fail)",
        "",
        "| 5-day, closed at day 5 | Picks: trades | avg per trade | Every stock avg | Edge per day | Lower bound (5-day blocks) |",
        "|---|---|---|---|---|---|",
    ]
    for name, part in (("Best 5", sk), ("Buy rule", mo)):
        d = part["day5"]
        lines.append(
            f"| {name} | {d['model']['ideas']} | {_pct(d['model']['avg_net'])} | {_pct(d['every_stock']['avg_net'])} | "
            f"{_pct(d['edge_per_day'], 3)} | {_pct(d['edge_low'], 3)} |"
        )
    lines += [
        "",
        "## Each fold (5-day, after costs; average per trade)",
        "",
        "| Test days | Days | Market | AUC | Best 5: trades / hit / avg | Every stock | Risers | NIFTY same periods | Skill fold won | "
        "Buy rule: trades / hit / avg | Money fold won | Day-5 close: best 5 / buy rule |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for f in result["folds"]:
        s, m = f["skill"], f["money"]
        auc = "n/a" if f["model_auc"] is None else f"{f['model_auc']:.3f}"

        def won(p):
            return ("yes" if p["won"] else "no") if p["eligible"] else "not eligible"

        lines.append(
            f"| {f['start']} to {f['end']} | {f['days']} | {f['regime']['label']} ({_pct(f['regime']['avg_move'], 1)}) | {auc} | "
            f"{s['model']['ideas']} / {_pct(s['model']['hit_rate'], 0)} / {_pct(s['model']['avg_net'])} | "
            f"{_pct(s['every_stock']['avg_net'])} | {_pct(s['momentum']['avg_net'])} | {_pct(s['nifty_matched'])} | {won(s)} | "
            f"{m['model']['ideas']} / {_pct(m['model']['hit_rate'], 0)} / {_pct(m['model']['avg_net'])} | {won(m)} | "
            f"{_pct(s['day5_model']['avg_net'])} / {_pct(m['day5_model']['avg_net'])} |"
        )
    lines += [
        "",
        "## Account replay (5-day, reported only; Rs 10 lakh, ladder limits, sector cap, 5 new a day, 15% halt)",
        "",
        "| 5-day account | Final result | Worst fall | Halt triggered |",
        "|---|---|---|---|",
    ]
    for name, key in (("Best 5", "best_5"), ("Buy rule", "buy_rule"), ("5 strongest risers", "momentum_5")):
        r = port[key]
        lines.append(
            f"| {name} | {_pct(r['final_net_return'])} | {_pct(r['max_drawdown'], 1)} | {r['halt_triggered']} |"
        )
    ra = port["random_5_accounts"]
    lines.append(
        f"| Random 5 ({ra['runs']} accounts): median (5th to 95th) | {_pct(ra['final_net_return_median'])} "
        f"({_pct(ra['p5'])} to {_pct(ra['p95'])}) | {_pct(ra['max_drawdown_median'], 1)} median | {ra['halt_triggered_runs']} runs |"
    )
    nh = port["nifty_held"] or {}
    lines += [
        f"| NIFTY 50 held | {_pct(nh.get('final_net_return'))} | {_pct(nh.get('max_drawdown'), 1)} | n/a |",
        "| Cash | 0.00% | 0.0% | no |",
        f"| Rules only | {RULES_ONLY_MISSING} | | |",
        "",
        "## Side report: dearer costs (5-day, average per trade; picks unchanged)",
        "",
        "| Costs | Best 5 | Every stock | Buy rule |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r['costs']} | {_pct(r['best_5'])} | {_pct(r['every_stock'])} | {_pct(r['buy_rule'])} |"
        for r in result["cost_stress"]
    ]
    lines += ["", "## Limits", ""] + [f"- {x}" for x in LIMITS] + ["", f"Layer 2: {result['layer2']}."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the guard


class RunRefusedError(RuntimeError):
    """A real fd-protocol-v1 run was asked for before it is allowed."""


def refusal_reasons(
    *, tag_on_head: bool, changed_since_tag: Sequence[str], already_ran: Sequence[str]
) -> list[str]:
    """Every reason a real run may not start now; an empty list means it may."""
    reasons: list[str] = []
    if not tag_on_head:
        reasons.append(
            f"The git tag {TAG} is not in this commit's history: the protocol is not frozen yet. "
            "The owner tags the merge commit first; only then does the one confirmation run happen."
        )
    for path in changed_since_tag:
        reasons.append(
            f"{path} differs from the tagged version: a changed setting is {PROTOCOL_VERSION.replace('v1', 'v2')}, not v1."
        )
    for path in already_ran:
        reasons.append(f"{path} already exists: layer 1 runs once, with no re-runs.")
    return reasons


def git_guard_state(repo_root: Path) -> tuple[bool, list[str]]:
    """(tag is in HEAD's history, frozen files that differ from the tag in the working tree)."""
    import subprocess

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo_root), *a], capture_output=True, text=True, check=False)

    on_head = TAG in git("tag", "--merged", "HEAD", "-l", TAG).stdout.split()
    if not on_head:
        return False, []
    changed = git("diff", "--name-only", TAG, "--", *FROZEN_FILES).stdout.split()
    return True, changed


def output_paths(out_dir: Path, first: date, last: date) -> tuple[Path, Path]:
    stem = f"five_day_{first.isoformat()}_{last.isoformat()}"
    return out_dir / f"{stem}.md", out_dir / f"{stem}.json"


def check_run_allowed(
    out_dir: Path, first: date, last: date, *, state: tuple[bool, list[str]] | None = None
) -> None:
    from swing_trade_ml.core.config import REPO_ROOT

    tag_on_head, changed = state if state is not None else git_guard_state(REPO_ROOT)
    ran = [str(p) for p in output_paths(out_dir, first, last) if p.exists()]
    reasons = refusal_reasons(tag_on_head=tag_on_head, changed_since_tag=changed, already_ran=ran)
    if reasons:
        raise RunRefusedError(
            f"{PROTOCOL_VERSION} refused: nothing was scored and no result was produced.\n"
            + "\n".join(f"- {r}" for r in reasons)
            + "\nUse --dry-run to see the folds and settings without scoring anything."
        )


# ---------------------------------------------------------------- the real run (database)


def load_bars_with_volume(db, symbols: Sequence[str], upto: date) -> dict[str, pd.DataFrame]:
    """Daily bars with volume per symbol, ascending, IST trading days, up to and including `upto`."""
    from collections import defaultdict
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from swing_trade_ml.db.models.market import Candle, Instrument

    ist = ZoneInfo("Asia/Kolkata")
    if not symbols:
        return {}
    ceiling = datetime.combine(upto + timedelta(days=1), time(0, 0), tzinfo=ist)
    rows = db.execute(
        select(
            Instrument.tradingsymbol,
            Candle.ts,
            Candle.open,
            Candle.high,
            Candle.low,
            Candle.close,
            Candle.volume,
        )
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol.in_(list(symbols)), Candle.interval == "day", Candle.ts < ceiling)
        .order_by(Instrument.tradingsymbol, Candle.ts.asc())
    ).all()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for sym, ts, o, h, lo, c, v in rows:
        grouped[sym].append(
            {
                "day": ts.astimezone(ist).date(),
                "open": float(o),
                "high": float(h),
                "low": float(lo),
                "close": float(c),
                "volume": float(v or 0),
            }
        )
    cols = ["day", "open", "high", "low", "close", "volume"]
    return {s: pd.DataFrame(r, columns=cols) for s, r in grouped.items()}


def _train(db, cutoff: date):
    from swing_trade_ml.ml.train import train_model

    return train_model(
        db,
        name=f"fd_h{LABEL_HORIZON}_{cutoff:%Y%m%d}",
        cutoff=cutoff,
        horizon_days=LABEL_HORIZON,
        target_return=TARGET,
        stop_return=None,
        auto_activate=False,
        label_kind="endpoint",
    )


def collect(
    db,
    first_start: date,
    last_end: date,
    *,
    train_fn: Callable | None = None,
    score_fn: Callable | None = None,
) -> Inputs:
    """Prices, NIFTY, and per fold a model trained only on outcomes known by its cutoff, scoring only
    that fold's days. Registers `fd_h5_*` trial models (never activated)."""
    from sqlalchemy import select

    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    train_fn = train_fn or _train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn
    folds = wf.make_folds(first_start, last_end)
    if not folds:
        raise ValueError("No test window fits between the start and end dates.")
    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    upto = last_end + timedelta(days=LOAD_EXTRA_DAYS)
    bars = {
        s: df
        for s, df in load_bars_with_volume(db, [i.tradingsymbol for i in instruments], upto).items()
        if len(df)
    }
    bench = settings.BENCHMARK_INDEX_SYMBOL
    nifty = load_bars_with_volume(db, [bench], upto).get(bench)
    if nifty is None:
        nifty = pd.DataFrame(columns=["day", "open", "high", "low", "close", "volume"])
    scores: dict[str, dict[date, float]] = {
        i.tradingsymbol: {} for i in instruments if i.tradingsymbol in bars
    }
    models = []
    for fold in folds:
        log.info("five_day.fold", cutoff=fold.cutoff.isoformat(), start=fold.start.isoformat())
        model = train_fn(db, fold.cutoff)
        models.append(
            {
                "name": getattr(model, "name", None),
                "cutoff": fold.cutoff.isoformat(),
                "auc": getattr(model, "roc_auc", None),
            }
        )
        for i in instruments:
            if i.tradingsymbol not in scores:
                continue
            # Picks use only the fold's own days. The last fold's model also scores the days after
            # the sample, so trades still open then can meet the confidence exit as in prod.
            hi = fold.end if fold is not folds[-1] else upto
            for d, p in score_fn(db, i, model, fold.cutoff).items():
                if fold.start <= d <= hi:
                    scores[i.tradingsymbol][d] = p
    return Inputs(
        bars=bars,
        nifty=nifty,
        scores=scores,
        folds=folds,
        models=models,
        buckets={s: get_sector_bucket(s) for s in bars},
    )


def _commit() -> tuple[str, bool]:
    from swing_trade_ml.brain.phase_b import git_commit

    return git_commit()


LEDGER_MARKER = "fd-protocol-v1 layer 1, {first} to {last}"


def ledger_row(first: date, last: date, *, run_day: date, report_name: str) -> str:
    return (
        f"| {first.isoformat()} to {last.isoformat()} (49 stocks) | "
        f"{LEDGER_MARKER.format(first=first, last=last)}: 5-day model (endpoint label) and prod trade rule, "
        "best 5 and prod buy rule, benchmarks; run once | Owner's decision: to be written after reading | "
        f"{run_day.isoformat()} | `fd_v1/{report_name}` |"
    )


def add_ledger_row(path: Path, first: date, last: date, *, run_day: date, report_name: str) -> None:
    """Add the run's row to the ledger's local-data table before any result exists (protocol C13).
    A window that already has a row has had its one run: refuse."""
    text = path.read_text(encoding="utf-8")
    if LEDGER_MARKER.format(first=first, last=last) in text:
        raise RunRefusedError(
            f"{PROTOCOL_VERSION} refused: {first} to {last} already has a row in the exposure ledger, "
            "so it has had its one run."
        )
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Local data"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last_row = max(i for i in range(start, end) if lines[i].startswith("|"))
    lines.insert(last_row + 1, ledger_row(first, last, run_day=run_day, report_name=report_name))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(
    db,
    *,
    first_start: date,
    last_end: date,
    out_dir: Path,
    ledger_path: Path | None = None,
    state: tuple[bool, list[str]] | None = None,
    collect_fn: Callable = collect,
    commit_fn: Callable = _commit,
    today: date | None = None,
    **eval_kw,
) -> tuple[Path, Path]:
    """The one real run: guard, data and fold models, the exposure-ledger row, and only then the
    scoring and the report."""
    from swing_trade_ml.brain.phase_b import ist_today
    from swing_trade_ml.core.config import REPO_ROOT

    check_run_allowed(out_dir, first_start, last_end, state=state)
    ledger_path = ledger_path or REPO_ROOT / "docs" / "brain" / "EXPOSURE-LEDGER.md"
    if LEDGER_MARKER.format(first=first_start, last=last_end) in ledger_path.read_text(encoding="utf-8"):
        raise RunRefusedError(
            f"{PROTOCOL_VERSION} refused: the exposure ledger shows this window already ran."
        )
    inp = collect_fn(db, first_start, last_end)
    md_name = output_paths(out_dir, first_start, last_end)[0].name
    add_ledger_row(ledger_path, first_start, last_end, run_day=today or ist_today(), report_name=md_name)
    result = evaluate(inp, **eval_kw)
    commit, dirty = commit_fn()
    manifest = {
        "Protocol": PROTOCOL_VERSION,
        "Tag": f"{TAG} (in this commit's history)",
        "Code commit": commit + (" (uncommitted changes present)" if dirty else ""),
        "Sample": result["sample"],
        "Folds": f"{len(inp.folds)} of 28 calendar days, model retrained once per fold",
        "Universe": f"{len(inp.bars)} watchlisted stocks (today's list: survivor bias)",
    }
    result["manifest"] = manifest
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = output_paths(out_dir, first_start, last_end)
    md.write_text(plain_report(result, manifest), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def dry_run_plan(
    first_start: date, last_end: date, *, state: tuple[bool, list[str]] | None = None, out_dir: Path
) -> str:
    """The folds and settings, and whether a real run would be allowed. Scores nothing."""
    from swing_trade_ml.core.config import REPO_ROOT

    tag_on_head, changed = state if state is not None else git_guard_state(REPO_ROOT)
    ran = [str(p) for p in output_paths(out_dir, first_start, last_end) if p.exists()]
    reasons = refusal_reasons(tag_on_head=tag_on_head, changed_since_tag=changed, already_ran=ran)
    folds = wf.make_folds(first_start, last_end)
    lines = [
        f"{PROTOCOL_VERSION} dry run (nothing scored).",
        f"Sample {first_start} to {last_end}: "
        + (
            "the confirmation sample (pass or fail)."
            if (first_start, last_end) == CONFIRMATION
            else "not the confirmation sample (reported only)."
        ),
        f"{len(folds)} folds: " + ", ".join(f"{f.start}..{f.end}" for f in folds),
        f"Label (endpoint): close {LABEL_HORIZON} trading days later at least +{TARGET:.0%} above today's close. "
        f"Trade +{TARGET:.0%} / -{STOP:.0%} from the decision close, trailing stop, confidence exit at or below "
        f"{prod_exit_confidence():.2f}, time stop at the open on or after entry + {TIME_STOP_DAYS} calendar days; "
        f"day-{DAY5_BARS} close reported only.",
        f"Buy rule: {_rule_dict(prod_buy_rule())}",
        "A real run is "
        + ("allowed." if not reasons else "refused:\n" + "\n".join(f"- {r}" for r in reasons)),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.core.config import REPO_ROOT

    p = argparse.ArgumentParser(
        description=f"{PROTOCOL_VERSION}: the 5-day strategy, layer 1 (read-only evidence)"
    )
    p.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD: first test day")
    p.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD: last test day")
    p.add_argument(
        "--dry-run", action="store_true", help="print the plan and the guard's answer; score nothing"
    )
    a = p.parse_args(argv)
    first, last = date.fromisoformat(a.start), date.fromisoformat(a.end)
    out_dir = REPO_ROOT / OUT_DIR
    if a.dry_run:
        print(dry_run_plan(first, last, out_dir=out_dir))
        return 0
    try:
        check_run_allowed(out_dir, first, last)
    except RunRefusedError as e:
        print(e)
        return 2
    from swing_trade_ml.db.session import SessionLocal

    with SessionLocal() as db:
        md, js = run(db, first_start=first, last_end=last, out_dir=out_dir)
    print(md.read_text(encoding="utf-8"))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
