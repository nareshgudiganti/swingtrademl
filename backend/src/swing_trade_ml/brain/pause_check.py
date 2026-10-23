# backend/src/swing_trade_ml/brain/pause_check.py
# ruff: noqa: E501  (plain-English report tables are long lines)
"""A8 pause-number check (protocol `pause-check-v1`): would the provisional performance pauses fire by
bad luck alone, and do they come before the account-wide 15% drawdown halt?

Offline research module. Not imported by live code; it changes no setting and no pause number.
Rules checked (amendment 1, A8, provisional):
1. 8 losing finished ideas in a row;
2. two calendar months below the every-stock baseline, after costs;
3. the brain's own book 8% below its peak.

Strategies of known edge are made on real days from each day's every-stock list: plain random picks
(no edge) or picks weighted by exp(theta x real outcome), a deliberate look-ahead used only to
manufacture a known edge. The pure helpers at the top are tested in tests/test_brain_pause_check.py.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time as _time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from swing_trade_ml.brain.portfolio_sim import Book, Pick
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

PROTOCOL = "pause-check-v1"
STREAK = 8  # rule 1 (provisional)
BOOK_FALL = 0.08  # rule 3 (provisional)
HALT = 0.15  # account-wide halt (MAX_PORTFOLIO_DRAWDOWN_PCT), pinned like portfolio_sim
CAPITAL = 979_792.0
SEED = 20261022
EDGES = (-0.01, -0.005, 0.0, 0.003, 0.01)
PACES = (5.0, 0.64)
FIRST_DAY, LAST_DECISION = date(2022, 1, 3), date(2026, 8, 14)
FIRST_START_MONTH, LAST_START_MONTH = (2022, 1), (2025, 8)
WF_WINDOWS = ((date(2023, 7, 1), date(2025, 1, 31)), (date(2025, 10, 1), date(2026, 8, 15)))
MONTHS = (3, 6, 12)


@dataclass(frozen=True, slots=True)
class Idea:
    day: date  # decision day
    symbol: str
    exit_day: date
    net: float  # after-cost result


# ---------------------------------------------------------------- pure helpers (tested)


def add_months(d: date, n: int) -> date:
    """First day of the month n months after d's month, if d is a month's first trading day; in general
    the same day-of-month clipped to the month's length."""
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def streak_fire(ideas: Sequence[Idea], n: int = STREAK) -> date | None:
    """Exit day of the n-th loss in a row (ordered by exit day, then decision day, then stock).
    A result of zero or more resets the count."""
    run = 0
    for i in sorted(ideas, key=lambda x: (x.exit_day, x.day, x.symbol)):
        run = run + 1 if i.net < 0 else 0
        if run >= n:
            return i.exit_day
    return None


def month_verdicts(
    ideas: Sequence[Idea], every_avg: dict[date, float]
) -> list[tuple[tuple[int, int], bool, date]]:
    """Per decision month that had ideas: (month, below every stock?, day the verdict is known).
    The baseline is the every-stock average of the same decision days, weighted like the ideas."""
    by_month: dict[tuple[int, int], list[Idea]] = {}
    for i in ideas:
        by_month.setdefault((i.day.year, i.day.month), []).append(i)
    out = []
    for m in sorted(by_month):
        xs = by_month[m]
        mine = sum(i.net for i in xs) / len(xs)
        base = sum(every_avg[i.day] for i in xs) / len(xs)
        out.append((m, mine < base, max(i.exit_day for i in xs)))
    return out


def _next_month(m: tuple[int, int]) -> tuple[int, int]:
    return (m[0] + 1, 1) if m[1] == 12 else (m[0], m[1] + 1)


def two_months_fire(
    verdicts: Sequence[tuple[tuple[int, int], bool, date]], consecutive: bool = True
) -> date | None:
    """Day the second below-baseline month becomes known. `consecutive`: the two months must be
    neighbouring calendar months (a month with no ideas breaks the run)."""
    prev: tuple[tuple[int, int], bool] | None = None
    below = 0
    for m, is_below, known in verdicts:
        if consecutive:
            if is_below and prev is not None and prev[1] and _next_month(prev[0]) == m:
                return known
        elif is_below:
            below += 1
            if below >= 2:
                return known
        prev = (m, is_below)
    return None


def drawdown_fire(curve: Sequence[tuple[date, float]], fall: float) -> date | None:
    """First day the closing value is `fall` or more below its running peak."""
    peak = None
    for d, v in curve:
        peak = v if peak is None else max(peak, v)
        if peak > 0 and (peak - v) / peak >= fall - 1e-12:
            return d
    return None


def pick_day(rng: random.Random, outcomes: Sequence[tuple[str, float]], k: int, theta: float) -> list[str]:
    """k stocks without replacement; weights exp(theta x outcome) (Efraimidis-Spirakis keys)."""
    k = min(k, len(outcomes))
    if k <= 0:
        return []
    if theta == 0.0:
        return [s for s, _ in rng.sample(list(outcomes), k)]
    top = max(r for _, r in outcomes)
    keyed = [(math.log(rng.random() or 1e-300) / math.exp(theta * (r - top)), s) for s, r in outcomes]
    keyed.sort(reverse=True)
    return [s for _, s in keyed[:k]]


def ideas_today(rng: random.Random, pace: float) -> int:
    """Whole paces are that many ideas a day; a pace under one is one idea with that probability."""
    if pace >= 1:
        return int(pace)
    return 1 if rng.random() < pace else 0


def share_within(fires: Sequence[date | None], start_of: Sequence[date], months: int) -> float:
    hits = sum(1 for f, s in zip(fires, start_of, strict=True) if f is not None and f < add_months(s, months))
    return hits / len(fires) if fires else 0.0


def median_months(fires: Sequence[date | None], start_of: Sequence[date], cap: int = 12) -> float | None:
    """Median months to the first fire, None when under half the paths fire within `cap` months."""
    ms = []
    for f, s in zip(fires, start_of, strict=True):
        ms.append((f - s).days / 30.44 if f is not None and f < add_months(s, cap) else math.inf)
    ms.sort()
    mid = statistics.median_low(ms) if ms else math.inf
    return None if math.isinf(mid) else round(mid, 1)


def tilt_theta_iid(values: np.ndarray, edge: float) -> float:
    """theta so the exp-tilted mean of `values` is `edge` above their plain mean (bisection)."""
    if edge == 0:
        return 0.0
    base = float(values.mean())

    def tilted(t: float) -> float:
        w = np.exp(t * (values - values.max()))
        return float((w * values).sum() / w.sum()) - base

    lo, hi = (-500.0, 0.0) if edge < 0 else (0.0, 500.0)
    for _ in range(80):
        mid = (lo + hi) / 2
        if tilted(mid) < edge:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def iid_streak_and_months(
    values: np.ndarray, theta: float, pace: float, *, paths: int, days: int = 252, seed: int = SEED
) -> dict:
    """Shuffled Monte Carlo (no market clustering): ideas drawn independently from the tilted pool.
    Returns the share of paths where rule 1 and rule 2 fire within 3 / 6 / 12 months (21 trading days
    a month), and the median months to the first fire."""
    rng = np.random.default_rng(seed)
    w = np.exp(theta * (values - values.max()))
    p = w / w.sum()
    base = float(values.mean())
    n_per_day = rng.binomial(1, pace, size=(paths, days)) if pace < 1 else np.full((paths, days), int(pace))
    total = int(n_per_day.sum(axis=1).max())
    draws = values[rng.choice(len(values), size=(paths, total), p=p)]
    streak_day = np.full(paths, np.inf)
    month_fire = np.full(paths, np.inf)
    run = np.zeros(paths, dtype=int)
    pos = np.zeros(paths, dtype=int)
    m_sum = np.zeros(paths)
    m_n = np.zeros(paths)
    prev_below = np.zeros(paths, dtype=bool)
    rows = np.arange(paths)
    for d in range(days):
        n_today = n_per_day[:, d]
        for j in range(int(n_today.max())):
            has = n_today > j
            r = draws[rows, np.minimum(pos, total - 1)]
            loss = has & (r < 0)
            run = np.where(has, np.where(loss, run + 1, 0), run)
            streak_day = np.where((run >= STREAK) & np.isinf(streak_day), d, streak_day)
            m_sum = m_sum + np.where(has, r, 0.0)
            m_n = m_n + has
            pos = pos + has
        if (d + 1) % 21 == 0:
            month_mean = np.divide(m_sum, m_n, out=np.zeros(paths), where=m_n > 0)
            below = (m_n > 0) & (month_mean < base)
            month_fire = np.where(below & prev_below & np.isinf(month_fire), d, month_fire)
            prev_below = below
            m_sum[:] = 0
            m_n[:] = 0

    def summary(fire_day: np.ndarray) -> dict:
        out = {f"within_{m}m": float((fire_day < 21 * m).mean()) for m in MONTHS}
        med = float(np.median(fire_day))
        out["median_months"] = None if math.isinf(med) else round(med / 21, 1)
        return out

    return {"rule1": summary(streak_day), "rule2": summary(month_fire), "paths": paths}


# ---------------------------------------------------------------- data on real days


@dataclass(slots=True)
class Market:
    """Every-stock strict outcomes on real decision days."""

    days: list[date]  # decision days with outcomes, ascending
    per_day: dict[date, list[tuple[str, float]]]  # finished outcomes per decision day
    exit_of: dict[tuple[str, date], date]
    every_avg: dict[date, float]

    def idea(self, sym: str, day: date) -> Idea:
        return Idea(day, sym, self.exit_of[(sym, day)], dict(self.per_day[day])[sym])


def build_market(outcomes: dict) -> Market:
    per_day: dict[date, list[tuple[str, float]]] = {}
    exit_of: dict[tuple[str, date], date] = {}
    for (sym, day), o in outcomes.items():
        if o.net_return is None or o.exit_day is None:
            continue
        per_day.setdefault(day, []).append((sym, o.net_return))
        exit_of[(sym, day)] = o.exit_day
    for xs in per_day.values():
        xs.sort()
    every = {d: sum(r for _, r in xs) / len(xs) for d, xs in per_day.items()}
    return Market(sorted(per_day), per_day, exit_of, every)


def draw_ideas(
    market: Market, days: Sequence[date], theta: float, pace: float, rng: random.Random
) -> list[Idea]:
    out = []
    for d in days:
        for s in pick_day(rng, market.per_day[d], ideas_today(rng, pace), theta):
            out.append(market.idea(s, d))
    return out


def realised_edge(ideas: Sequence[Idea], market: Market) -> float | None:
    if not ideas:
        return None
    return sum(i.net - market.every_avg[i.day] for i in ideas) / len(ideas)


def calibrate_theta(market: Market, edge: float, pace: float, *, draws: int = 20, seed: int = SEED) -> float:
    """theta so the pooled edge of `draws` seeded runs over all days equals `edge` (common random numbers)."""
    if edge == 0:
        return 0.0

    def measured(theta: float) -> float:
        vals = []
        for n in range(draws):
            got = draw_ideas(market, market.days, theta, pace, random.Random(seed + n))
            vals.append(realised_edge(got, market) or 0.0)
        return sum(vals) / len(vals)

    lo, hi = (-400.0, 0.0) if edge < 0 else (0.0, 400.0)
    for _ in range(22):
        mid = (lo + hi) / 2
        if measured(mid) < edge:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def month_starts(market: Market) -> list[date]:
    out = []
    y, m = FIRST_START_MONTH
    while (y, m) <= LAST_START_MONTH:
        first = next((d for d in market.days if (d.year, d.month) == (y, m)), None)
        if first is not None:
            out.append(first)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def window(market: Market, start: date, months: int = 12) -> list[date]:
    end = add_months(start, months)
    return [d for d in market.days if start <= d < end]


def path_seed(edge_i: int, pace_i: int, start_i: int, draw: int) -> int:
    return SEED + 1000 * edge_i + 100_000 * pace_i + 100 * start_i + draw


def idea_rules(ideas: Sequence[Idea], market: Market) -> dict[str, date | None]:
    v = month_verdicts(ideas, market.every_avg)
    return {
        "rule1": streak_fire(ideas),
        "rule2": two_months_fire(v),
        "rule2_any": two_months_fire(v, consecutive=False),
    }


def summarise_fires(fires: Sequence[date | None], starts: Sequence[date]) -> dict:
    out = {f"within_{m}m": round(share_within(fires, starts, m), 4) for m in MONTHS}
    out["median_months"] = median_months(fires, starts)
    out["paths"] = len(fires)
    return out


# ---------------------------------------------------------------- accounts (rule 3 and the 15% halt)


def run_accounts(
    bars: dict[str, pd.DataFrame],
    days: Sequence[date],
    brain: Sequence[Pick],
    other: Sequence[Pick] | None = None,
    *,
    capital: float = CAPITAL,
) -> dict:
    """The brain book alone (Case A) or next to a second book with half the money each (Case B).
    The 15% halt reads the whole account's closing value; while on, neither book buys at the next open.
    Each Book's own halt is switched off so only the account-wide one acts."""
    share = capital if other is None else capital / 2
    books = [Book(bars, capital=share, max_drawdown_pct=2.0)]
    if other is not None:
        books.append(Book(bars, capital=share, max_drawdown_pct=2.0))
    picks = [brain] + ([other] if other is not None else [])
    by_day: list[dict] = [{} for _ in picks]
    for bd, ps in zip(by_day, picks, strict=True):
        for p in ps:
            bd.setdefault(p.day, []).append(p)
    account: list[tuple[date, float]] = []
    peak = capital
    halted = False
    halt_day = None
    halted_days = 0
    for i, day in enumerate(days):
        prev = days[i - 1] if i else None
        if halted:
            halted_days += 1
        for b, bd in zip(books, by_day, strict=True):
            b.step(day, [] if halted or prev is None else bd.get(prev, []))
        value = sum(b.equity for b in books)
        account.append((day, value))
        peak = max(peak, value)
        halted = (peak - value) / peak >= HALT - 1e-12
        if halted and halt_day is None:
            halt_day = day
    brain_curve = books[0].curve
    return {
        "brain_fall_day": drawdown_fire(brain_curve, BOOK_FALL),
        "halt_day": halt_day,
        "halted_days": halted_days,
        "brain_max_fall": books[0].max_dd,
        "account_max_fall": _max_fall(account),
        "brain_trades": len(books[0].closed),
    }


def _max_fall(curve: Sequence[tuple[date, float]]) -> float:
    peak, worst = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak:
            worst = max(worst, (peak - v) / peak)
    return worst


def order_vs_halt(rows: Sequence[dict]) -> dict:
    """For paths where the halt fired: did rule 3 fire before, the same day, after, or never?
    And fires of rules 1-3 after the halt day (pointless: buying had already stopped)."""
    out = {
        "paths": len(rows),
        "halt_fired": 0,
        "rule3_before": 0,
        "rule3_same_day": 0,
        "rule3_after": 0,
        "rule3_never": 0,
    }
    for k in ("rule1", "rule2", "rule3"):
        out[f"{k}_only_after_halt"] = 0
    for r in rows:
        h = r["halt_day"]
        if h is None:
            continue
        out["halt_fired"] += 1
        b = r["brain_fall_day"]
        if b is None:
            out["rule3_never"] += 1
        elif b < h:
            out["rule3_before"] += 1
        elif b == h:
            out["rule3_same_day"] += 1
        else:
            out["rule3_after"] += 1
        for k, f in (("rule1", r.get("rule1")), ("rule2", r.get("rule2")), ("rule3", b)):
            if f is not None and f > h:
                out[f"{k}_only_after_halt"] += 1
    return out


def picks_for(ideas: Sequence[Idea], buckets: dict[str, str | None], rng: random.Random) -> list[Pick]:
    return [Pick(i.day, i.symbol, rng.random(), buckets.get(i.symbol)) for i in ideas]


# ---------------------------------------------------------------- the run (needs the local database)


def _model_for(db, cutoff: date):
    from sqlalchemy import select

    from swing_trade_ml.brain.walk_forward import _train
    from swing_trade_ml.db.models.ml import MLModel

    row = (
        db.execute(
            select(MLModel)
            .where(
                MLModel.name == f"wf_h15_{cutoff:%Y%m%d}",
                MLModel.prediction_horizon_days == 15,
                MLModel.target_return_pct == 0.08,
                MLModel.stop_return_pct == 0.04,
                MLModel.artifact_path.is_not(None),
            )
            .order_by(MLModel.id.desc())
        )
        .scalars()
        .first()
    )
    if row is not None and Path(row.artifact_path).exists():
        return row, "reused"
    return _train(db, cutoff, 15, 0.08, 0.04), "trained"


def model_stream(
    db, instruments, first_start: date, last_end: date, days_all: Sequence[date]
) -> tuple[dict, dict]:
    """Walk-forward best 5 a day, fold by fold (same folds and models as walk_forward.py)."""
    from swing_trade_ml.brain.horizon_grid import top_k_by_day
    from swing_trade_ml.brain.walk_forward import make_folds
    from swing_trade_ml.ml.asof import score_series

    picks: dict[date, list[str]] = {}
    how: dict[str, int] = {"reused": 0, "trained": 0}
    for fold in make_folds(first_start, last_end, 28):
        fold_days = [d for d in days_all if fold.start <= d <= fold.end]
        if not fold_days:
            continue
        model, kind = _model_for(db, fold.cutoff)
        how[kind] += 1
        scores = {
            i.tradingsymbol: {
                d: p
                for d, p in score_series(db, i, model, fold.cutoff).items()
                if fold.start <= d <= fold.end
            }
            for i in instruments
        }
        picks.update(top_k_by_day(scores, fold_days, 5))
    return picks, how


def _fmt(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def run(db, *, progress: Callable[[str], None] = print) -> dict:
    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.walk_forward import outcomes_for
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    t0 = _time.time()
    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {
        s: df
        for s, df in load_bars(db, [i.tradingsymbol for i in instruments], date(2026, 9, 7)).items()
        if len(df)
    }
    buckets = {s: get_sector_bucket(s) for s in bars}
    all_days = sorted({d for df in bars.values() for d in df["day"]})
    decision_days = [d for d in all_days if FIRST_DAY <= d <= LAST_DECISION]
    market = build_market(outcomes_for(bars, decision_days, 15, 0.08, 0.04))
    progress(
        f"market: {len(market.days)} days, {sum(len(v) for v in market.per_day.values())} outcomes ({_time.time() - t0:.0f}s)"
    )
    starts = month_starts(market)
    pooled = np.array([r for d in market.days for _, r in market.per_day[d]])
    result: dict = {
        "protocol": PROTOCOL,
        "label": "Diagnostic on development data, not proof.",
        "stocks": len(bars),
        "decision_days": [market.days[0].isoformat(), market.days[-1].isoformat(), len(market.days)],
        "every_stock": {
            "ideas": len(pooled),
            "avg_net": float(pooled.mean()),
            "loss_share": float((pooled < 0).mean()),
        },
        "starts": [s.isoformat() for s in starts],
        "rules": {"streak": STREAK, "book_fall": BOOK_FALL, "halt": HALT},
    }
    # 1. calibrate the manufactured edges
    thetas: dict[str, float] = {}
    for pace in PACES:
        for e in EDGES:
            thetas[f"{e}|{pace}"] = calibrate_theta(market, e, pace)
            progress(
                f"theta edge {e:+.3f} pace {pace}: {thetas[f'{e}|{pace}']:.2f} ({_time.time() - t0:.0f}s)"
            )
    result["thetas"] = thetas

    # 2. rules 1 and 2 on real days
    real_days: dict = {}
    for pi, pace in enumerate(PACES):
        for ei, e in enumerate(EDGES):
            theta = thetas[f"{e}|{pace}"]
            fires = {"rule1": [], "rule2": [], "rule2_any": []}
            start_of, edges_seen = [], []
            for si, s in enumerate(starts):
                wdays = window(market, s)
                for n in range(50):
                    ideas = draw_ideas(market, wdays, theta, pace, random.Random(path_seed(ei, pi, si, n)))
                    for k, f in idea_rules(ideas, market).items():
                        fires[k].append(f)
                    start_of.append(s)
                    edges_seen.append(realised_edge(ideas, market) or 0.0)
            real_days[f"{e}|{pace}"] = {
                "edge": e,
                "pace": pace,
                "realised_edge": sum(edges_seen) / len(edges_seen),
                **{k: summarise_fires(v, start_of) for k, v in fires.items()},
            }
            progress(f"real days edge {e:+.3f} pace {pace} done ({_time.time() - t0:.0f}s)")
    result["real_days"] = real_days

    # 3. shuffled Monte Carlo
    shuffled: dict = {}
    for pi, pace in enumerate(PACES):
        for ei, e in enumerate(EDGES):
            th = tilt_theta_iid(pooled, e)
            shuffled[f"{e}|{pace}"] = {
                "edge": e,
                "pace": pace,
                **iid_streak_and_months(pooled, th, pace, paths=20_000, seed=SEED + 10 * ei + pi),
            }
    progress(f"shuffled done ({_time.time() - t0:.0f}s)")
    result["shuffled"] = shuffled

    # 4. accounts
    draws = 10
    timed = _time.time()
    trial = 0
    accounts: dict = {}
    plan = [("A", e, p, False) for p in PACES for e in EDGES] + [
        ("B", e, 5.0, True) for e in (-0.01, 0.0, 0.003)
    ]
    for case, e, pace, with_other in plan:
        ei, pi = EDGES.index(e), PACES.index(pace)
        theta = thetas[f"{e}|{pace}"]
        rows, start_of = [], []
        for si, s in enumerate(starts):
            wdays = window(market, s)
            acct_days = [d for d in all_days if s <= d < add_months(s, 12)]
            for n in range(draws):
                rng = random.Random(path_seed(ei, pi, si, n) + 7)
                ideas = draw_ideas(market, wdays, theta, pace, rng)
                other = None
                if with_other:
                    o_rng = random.Random(path_seed(EDGES.index(0.0), 0, si, n) + 9_000_000)
                    other = picks_for(draw_ideas(market, wdays, 0.0, 5.0, o_rng), buckets, o_rng)
                r = run_accounts(bars, acct_days, picks_for(ideas, buckets, rng), other)
                r.update(idea_rules(ideas, market))
                rows.append(r)
                start_of.append(s)
                trial += 1
                if trial == 20 and draws == 10:
                    per = (_time.time() - timed) / 20
                    total_runs = sum(len(starts) * draws * (2 if w else 1) for *_, w in plan)
                    if per * total_runs > 3600:
                        draws = 5
                        progress(f"fallback: {per:.2f}s an account, draws cut to 5 per start")
        key = f"{case}|{e}|{pace}"
        accounts[key] = {
            "case": case,
            "edge": e,
            "pace": pace,
            "draws_per_start": draws,
            "rule3": summarise_fires([r["brain_fall_day"] for r in rows], start_of),
            "halt": summarise_fires([r["halt_day"] for r in rows], start_of),
            "order": order_vs_halt(rows),
            "brain_max_fall_median": statistics.median(r["brain_max_fall"] for r in rows),
            "account_max_fall_worst": max(r["account_max_fall"] for r in rows),
            "brain_trades_median": statistics.median(r["brain_trades"] for r in rows),
        }
        progress(f"accounts {key} done ({_time.time() - t0:.0f}s)")
    result["accounts"] = accounts
    result["account_draws_per_start"] = draws

    # 5. real model stream
    streams = []
    for first, last in WF_WINDOWS:
        picks, how = model_stream(db, instruments, first, last, all_days)
        ideas = [
            market.idea(s, d) for d, syms in sorted(picks.items()) for s in syms if (s, d) in market.exit_of
        ]
        acct_days = [d for d in all_days if first <= d <= last + timedelta(days=30)]
        acc = run_accounts(bars, acct_days, picks_for(ideas, buckets, random.Random(SEED)))
        rules = idea_rules(ideas, market)
        verdicts = month_verdicts(ideas, market.every_avg)
        streams.append(
            {
                "window": [first.isoformat(), last.isoformat()],
                "models": how,
                "ideas": len(ideas),
                "avg_net": sum(i.net for i in ideas) / len(ideas) if ideas else None,
                "edge": realised_edge(ideas, market),
                "months_below": sum(1 for _, b, _ in verdicts if b),
                "months": len(verdicts),
                "longest_losing_run": _longest_run(ideas),
                "rule1": _fmt(rules["rule1"]),
                "rule2": _fmt(rules["rule2"]),
                "rule2_any": _fmt(rules["rule2_any"]),
                "rule3": _fmt(acc["brain_fall_day"]),
                "halt": _fmt(acc["halt_day"]),
                "book_max_fall": acc["brain_max_fall"],
                "book_trades": acc["brain_trades"],
            }
        )
        progress(f"model stream {first}..{last} done ({_time.time() - t0:.0f}s)")
    result["model_streams"] = streams
    result["seconds"] = round(_time.time() - t0)
    return result


def _longest_run(ideas: Sequence[Idea]) -> int:
    best = run_ = 0
    for i in sorted(ideas, key=lambda x: (x.exit_day, x.day, x.symbol)):
        run_ = run_ + 1 if i.net < 0 else 0
        best = max(best, run_)
    return best


# ---------------------------------------------------------------- plain report


def _pc(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def _months(x: float | None) -> str:
    return "more than 12" if x is None else f"{x:.1f}"


def _word_false(p: float) -> str:
    return "rarely by chance" if p < 0.10 else "sometimes" if p <= 0.33 else "often by chance"


def _word_catch(p6: float, p12: float) -> str:
    return "catches it quickly" if p6 >= 0.8 else "catches it slowly" if p12 >= 0.8 else "may miss it"


def readings(result: dict) -> dict:
    """The fixed reading rule (PROTOCOL.md) applied to rules 1-3 at 5 ideas a day, real days / Case A."""
    rd, ac = result["real_days"], result["accounts"]
    out = {}
    for rule in ("rule1", "rule2"):
        zero, good, bad = rd["0.0|5.0"][rule], rd["0.003|5.0"][rule], rd["-0.01|5.0"][rule]
        out[rule] = (zero["within_12m"], good["within_12m"], bad["within_6m"], bad["within_12m"])
    a = (ac["A|0.0|5.0"]["rule3"], ac["A|0.003|5.0"]["rule3"], ac["A|-0.01|5.0"]["rule3"])
    out["rule3"] = (a[0]["within_12m"], a[1]["within_12m"], a[2]["within_6m"], a[2]["within_12m"])
    words = {}
    for rule, (z, g, b6, b12) in out.items():
        fa, catch = _word_false(z), _word_catch(b6, b12)
        rec = (
            "consider loosening"
            if fa == "often by chance"
            else "consider tightening"
            if catch == "may miss it"
            else "keep"
        )
        words[rule] = {
            "false_alarm": fa,
            "stops_good": _word_false(g),
            "catches_bad": catch,
            "recommendation": rec,
        }
    return words


def plain_report(result: dict) -> str:
    rd, sh, ac = result["real_days"], result["shuffled"], result["accounts"]
    words = result.get("readings") or readings(result)
    ev = result["every_stock"]
    lines = [
        "# Pause-number check (A8): would the pauses fire by bad luck?",
        "",
        f"Protocol `{result['protocol']}`. **Diagnostic on development data, not proof** (EXPOSURE-LEDGER.md).",
        "The pause numbers are the owner's provisional ones and are **not changed** by this report.",
        "",
        f"Data: {result['stocks']} watchlist stocks, decision days {result['decision_days'][0]} to "
        f"{result['decision_days'][1]} ({result['decision_days'][2]} days). Every idea is scored with the "
        "settled rule (next-day open, +8% / -4%, half out at +5%, 15 trading days, real costs). "
        f"Buying every stock every day averaged {100 * ev['avg_net']:+.2f}% a trade after costs and "
        f"{100 * ev['loss_share']:.0f}% of such trades lost money.",
        "",
        "How to read the tables: we made pretend strategies on the real days, from plain random picks (no "
        "skill, bad luck only) to picks that are a little better or worse than buying every stock. "
        f"{len(result['starts'])} different 12-month stretches, many random draws each. "
        "'Fires within 3 / 6 / 12 months' = the share of stretches where the pause would have switched on.",
        "",
    ]

    def row(label: str, s: dict) -> str:
        return f"| {label} | {_pc(s['within_3m'])} | {_pc(s['within_6m'])} | {_pc(s['within_12m'])} | {_months(s['median_months'])} |"

    head = [
        "| Strategy | Fires within 3 months | 6 months | 12 months | Median months to first pause |",
        "|---|---|---|---|---|",
    ]
    names = {
        -0.01: "Clearly bad (-1.0% a trade)",
        -0.005: "Bad (-0.5%)",
        0.0: "**No skill (bad luck only)**",
        0.003: "Slightly good (+0.3%)",
        0.01: "Good (+1.0%)",
    }
    for rule, title in (
        ("rule1", "Rule 1: 8 losing finished ideas in a row"),
        ("rule2", "Rule 2: two months in a row below every stock"),
    ):
        lines += [f"## {title}", ""]
        for pace in PACES:
            lines += [f"**{pace:g} ideas a day** (real days, market ups and downs kept)", "", *head]
            lines += [row(names[e], rd[f"{e}|{pace}"][rule]) for e in EDGES]
            lines += [""]
        lines += [
            "Shuffled (ideas drawn independently, no market ups and downs), 5 a day: no skill fires within 12 months in "
            f"{_pc(sh['0.0|5.0'][rule]['within_12m'])}; +0.3% in {_pc(sh['0.003|5.0'][rule]['within_12m'])}; "
            f"-1.0% in {_pc(sh['-0.01|5.0'][rule]['within_12m'])}. At 0.64 a day: "
            f"{_pc(sh['0.0|0.64'][rule]['within_12m'])} / {_pc(sh['0.003|0.64'][rule]['within_12m'])} / "
            f"{_pc(sh['-0.01|0.64'][rule]['within_12m'])}.",
            "",
        ]
        if rule == "rule2":
            z = rd["0.0|5.0"]["rule2_any"]
            lines += [
                f"If 'two months' meant any two months, not two in a row: no skill fires within 12 months in {_pc(z['within_12m'])} (5 a day).",
                "",
            ]
        w = words[rule]
        lines += [
            f"Reading (fixed rule, 5 a day): false alarms **{w['false_alarm']}**; a slightly good strategy is stopped "
            f"**{w['stops_good']}**; a clearly bad one: **{w['catches_bad']}**.",
            "",
        ]

    lines += ["## Rule 3: the brain's own book falls 8% from its peak", ""]
    lines += [
        "Case A: the brain is the whole account (₹9,79,792). Case B: the account is split half and half with a "
        "second book of random picks (a stand-in for the v1 bot). The 15% halt reads the whole account.",
        "",
    ]
    lines += [
        "| Account | Strategy | Ideas a day | Fires within 3 months | 6 months | 12 months | Median months | 15% halt within 12 months | Median worst fall of the book |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in ac.values():
        s = a["rule3"]
        lines.append(
            f"| {a['case']} | {names[a['edge']]} | {a['pace']:g} | {_pc(s['within_3m'])} | {_pc(s['within_6m'])} | "
            f"{_pc(s['within_12m'])} | {_months(s['median_months'])} | {_pc(a['halt']['within_12m'])} | {_pc(a['brain_max_fall_median'])} |"
        )
    w = words["rule3"]
    lines += [
        "",
        f"Reading (fixed rule, Case A, 5 a day): false alarms **{w['false_alarm']}**; a slightly good strategy "
        f"is stopped **{w['stops_good']}**; a clearly bad one: **{w['catches_bad']}**.",
        "",
    ]

    lines += [
        "## Order with the 15% halt",
        "",
        "| Account | Strategy | Ideas a day | Accounts | Halt fired | Book 8% came first | Same day | After | Never | Rule 1 only after halt | Rule 2 only after halt |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in ac.values():
        o = a["order"]
        lines.append(
            f"| {a['case']} | {names[a['edge']]} | {a['pace']:g} | {o['paths']} | {o['halt_fired']} | {o['rule3_before']} | "
            f"{o['rule3_same_day']} | {o['rule3_after']} | {o['rule3_never']} | {o['rule1_only_after_halt']} | {o['rule2_only_after_halt']} |"
        )
    lines += [
        "",
        "A pause and the halt can never give opposite orders: both only stop new buys. The only possible "
        "'conflict' is a pause that comes too late to matter (after the halt already stopped buying) or that "
        "the halt makes impossible (while halted the book buys nothing new, so it can only fall further on "
        "positions it already holds).",
        "",
    ]

    lines += [
        "## Our real model's picks (walk-forward, best 5 a day)",
        "",
        "| Window | Ideas | Avg after costs | Edge vs every stock | Longest losing run | Rule 1 fires | Rule 2 fires | Book 8% fall | 15% halt | Book worst fall |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in result["model_streams"]:
        lines.append(
            f"| {s['window'][0]} to {s['window'][1]} | {s['ideas']} | {100 * (s['avg_net'] or 0):+.2f}% | {100 * (s['edge'] or 0):+.2f}% | "
            f"{s['longest_losing_run']} | {s['rule1'] or 'never'} | {s['rule2'] or 'never'} | {s['rule3'] or 'never'} | {s['halt'] or 'never'} | {_pc(s['book_max_fall'])} |"
        )
    lines += [""]
    if result.get("reproduction"):
        lines += [result["reproduction"], ""]
    lines += result.get("what_this_means", [])
    lines += [
        "",
        "## Limits",
        "",
        "- Survivor bias: today's 49 watchlist stocks; today's sector map.",
        "- Accounts run every day as NORMAL (no replayed banner); DEFENSIVE days would buy less, so real books fall more slowly.",
        "- The 'slightly good' and 'bad' strategies are manufactured from real prices with a known edge; they are not real strategies.",
        "- Case B's second book is random picks, not the real v1 bot.",
        f"- Account runs used {result['account_draws_per_start']} draws per start month; run time {result['seconds']} s.",
    ]
    return "\n".join(lines) + "\n"


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md, js = directory / "pause_check.md", directory / "pause_check.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="A8 pause-number check (offline, development data)")
    p.add_argument("--out", default="../docs/brain/evidence/pause_check")
    p.add_argument("--render-only", action="store_true", help="rewrite pause_check.md from the stored .json")
    a = p.parse_args(argv)
    if a.render_only:
        stored = json.loads((Path(a.out) / "pause_check.json").read_text(encoding="utf-8"))
        md, js = write_report(stored, Path(a.out))
        print(f"Written: {md} and {js}")
        return 0
    with SessionLocal() as db:
        result = run(db)
    result["readings"] = readings(result)
    md, js = write_report(result, Path(a.out))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
