# backend/src/swing_trade_ml/brain/phase_b.py
# ruff: noqa: E501 (long lines are report sentences)
"""Phase B of the evidence plan: run each of the three candidates once, on development data.

Plan: `docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md` sections 3 and 3a, amended by
`2026-10-21-evidence-plan-amendment-1.md` (A1 labels, A2 comparisons, A5 counts and confidence, A6
manifest, A7 one horizon). Exactly three candidates, fixed settings, one run each, no retuning:

- B1  trade only on high score: every stock whose score is at least 0.80; no trade on other days.
- B2  wider training set: models trained on the 49 + the 128 extra stocks (177), scoring the same
      49 on the same dates (the model's best 5 a day). The 129-stock reject set never enters training.
- B3  buy only after market weakness: the model's best 5, only on days when under 30% of the 49 close
      above their own 50-day average (point-in-time breadth from the 49).

Every candidate gets the 3a matched baselines (every stock, random 5, momentum, NIFTY matched, cash),
the 3a equal-capital portfolio comparison with its risk report, the A2 comparisons (rules-only,
model-only, risk-matched random; mid/small-cap index = NOT TESTABLE), the reject-set robustness check
(it can only reject), A1 labels (on development data the best is "NO WARNING (diagnostic)", never
PASS), counts and confidence on every number, and the A6 manifest at the top of its output file.

Backtesting is reused, not rebuilt: folds, outcomes, momentum, daily edge and the block bootstrap
come from `walk_forward`; trade scoring from `replay_scoring`; the account from `portfolio_sim`; the
rules-only replay from `module_ablation`. Offline research only: nothing here is imported by live
decision, order or risk code.

GUARD. Phase B runs from 2026-11-09 (IST), once, after the rules are locked. A real run refuses
unless the date has come, the git tags `evidence-defs-v1`, `evidence-defs-v2` and `phase-b-settings`
exist, and the stock split file matches its recorded SHA-256. `--dry-run` prints the plan and scores nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from swing_trade_ml.brain.horizon_grid import top_k_by_day
from swing_trade_ml.brain.stock_split import FILE_NAME as SPLIT_FILE
from swing_trade_ml.brain.stock_split import NOTE_NAME as SPLIT_NOTE
from swing_trade_ml.brain.stock_split import file_sha256

IST = ZoneInfo("Asia/Kolkata")

PROTOCOL_ID = "evidence-plan-phase-b"
PROTOCOL_VERSION = "1"
DEFS_VERSION = "evidence-defs-v2"  # amendment 1; it builds on evidence-defs-v1 (plan section 3a)
SETTINGS_TAG = "phase-b-settings"  # B1-B3 settings, docs/superpowers/specs/2026-10-22-phase-b-settings.md
REQUIRED_TAGS = ("evidence-defs-v1", "evidence-defs-v2", SETTINGS_TAG)
PHASE_B_START = date(2026, 11, 9)  # no real run, and no result, before this IST day
DEV_START = date(2025, 2, 1)  # development data: the "seen" sample, plan section 3
DEV_END = date(2026, 8, 15)
HORIZON = 15  # trading days (+8% / -4%, half out at +5%); A7: never mixed with 5 or 30
SCORE_LINE = 0.80  # B1
TOP_K = 5  # B2, B3, model-only, momentum, random 5
WEAK_BREADTH = 0.30  # B3: market-weak = under this share of the 49 above their 50-day average
BREADTH_SMA = 50
RANDOM_DRAWS = 1000  # 3a random 5 and A2 risk-matched random
RANDOM_SEED = 7
PORTFOLIO_DRAWS = 200  # 3a portfolio-level random 5
MIN_DAYS = 30  # fewer trading days with ideas = INCONCLUSIVE (3a, A1, A5)

NO_WARNING = "NO WARNING (diagnostic)"
FAIL = "FAIL"
INCONCLUSIVE = "INCONCLUSIVE"
NOT_TESTABLE = "NOT TESTABLE"


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    name: str
    setting: str
    extra: str


CANDIDATES: dict[str, Candidate] = {
    "B1": Candidate(
        "B1",
        "Trade only on high score",
        f"every one of the 49 stocks whose model score is at least {SCORE_LINE:.2f}; no trade on other days",
        "ideas per week (coverage)",
    ),
    "B2": Candidate(
        "B2",
        "Wider training set",
        "models trained on the 49 + the 128 extra stocks (177); the model's best 5 of the same 49 "
        "each day; the 129-stock reject set never enters training",
        "data quality, survivorship note, leakage check (no reject-set stock in any training fold)",
    ),
    "B3": Candidate(
        "B3",
        "Buy only after market weakness",
        f"the model's best {TOP_K}, only on days when under {WEAK_BREADTH:.0%} of the 49 close above "
        f"their own {BREADTH_SMA}-day average; otherwise no new trades",
        "losses avoided and profitable trades missed on the other days; trading days a year",
    ),
}


# ---------------------------------------------------------------- the guard


class RealRunRefusedError(RuntimeError):
    """A real Phase B run was asked for before it is allowed."""


class LeakageError(RuntimeError):
    """A reject-set stock reached a model's training data."""


def ist_today(now: datetime | None = None) -> date:
    from datetime import UTC

    return (now or datetime.now(UTC)).astimezone(IST).date()


def recorded_split_hash(split_dir: Path) -> str | None:
    note = split_dir / SPLIT_NOTE
    if not note.exists():
        return None
    m = re.search(r"SHA-256 of file \| `([0-9a-f]{64})`", note.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def refusal_reasons(*, today: date, tags: Iterable[str], split_dir: Path) -> list[str]:
    """Every reason a real run may not start now; an empty list means it may."""
    reasons: list[str] = []
    if today < PHASE_B_START:
        reasons.append(
            f"Today is {today:%d %B %Y} (India time). Phase B may not run on real data before "
            f"{PHASE_B_START.day} November 2026, so nobody sees a result before the rules are locked."
        )
    have = set(tags)
    for tag in REQUIRED_TAGS:
        if tag not in have:
            what = "the candidate settings are" if tag == SETTINGS_TAG else "the definitions are"
            reasons.append(f"The git tag {tag} does not exist yet: {what} not locked.")
    js = split_dir / SPLIT_FILE
    if not js.exists():
        reasons.append(f"The stock split file is missing ({js}).")
    else:
        want = recorded_split_hash(split_dir)
        if want is None:
            reasons.append(f"The stock split note has no recorded hash ({split_dir / SPLIT_NOTE}).")
        elif file_sha256(js) != want:
            reasons.append(
                "The stock split file does not match its recorded hash: it was edited after it was locked."
            )
    return reasons


def git_tags(repo_root: Path) -> set[str]:
    import subprocess

    out = subprocess.run(
        ["git", "-C", str(repo_root), "tag", "-l", *REQUIRED_TAGS],
        capture_output=True,
        text=True,
        check=False,
    )
    return {t.strip() for t in out.stdout.splitlines() if t.strip()}


def check_real_run_allowed(
    *, today: date | None = None, tags: Iterable[str] | None = None, split_dir: Path | None = None
) -> None:
    """Raise `RealRunRefusedError` with a plain-English message unless a real run may start."""
    from swing_trade_ml.core.config import REPO_ROOT

    split_dir = split_dir or default_split_dir()
    reasons = refusal_reasons(
        today=today or ist_today(),
        tags=git_tags(REPO_ROOT) if tags is None else tags,
        split_dir=split_dir,
    )
    if reasons:
        raise RealRunRefusedError(
            "Phase B refused: it will not run on real market data yet, and no result was produced.\n"
            + "\n".join(f"- {r}" for r in reasons)
            + "\nUse --dry-run to see the plan (dates, stocks, manifest) without scoring anything."
        )


def default_split_dir() -> Path:
    from swing_trade_ml.core.config import REPO_ROOT

    return REPO_ROOT / "docs" / "brain" / "evidence" / "stock_split"


# ---------------------------------------------------------------- the split and leakage


def load_split(split_dir: Path) -> dict:
    """The locked split, after checking the file against its recorded hash."""
    import json

    js = split_dir / SPLIT_FILE
    want = recorded_split_hash(split_dir)
    got = file_sha256(js)
    if want != got:
        raise ValueError(f"{js} does not match its recorded SHA-256 ({want} vs {got})")
    data = json.loads(js.read_text(encoding="utf-8"))
    data["sha256"] = got
    return data


def _candidate(candidate_id: str) -> Candidate:
    if candidate_id not in CANDIDATES:
        raise ValueError(f"Unknown candidate {candidate_id!r}: Phase B has exactly B1, B2 and B3.")
    return CANDIDATES[candidate_id]


def training_symbols(candidate_id: str, split: Mapping) -> list[str]:
    """The stocks a candidate's models learn from. Only B2 adds the 128 extra stocks."""
    _candidate(candidate_id)
    if candidate_id == "B2":
        out = sorted(set(split["used_49"]) | set(split["extra_training_set"]))
    else:
        out = list(split["used_49"])
    assert_no_leakage(out, reject=split["reject_set"], where=f"{candidate_id} training list")
    return out


def assert_no_leakage(trained_on: Iterable[str], *, reject: Iterable[str], where: str) -> None:
    leaked = sorted(set(trained_on) & set(reject))
    if leaked:
        raise LeakageError(f"Reject-set stocks in training data ({where}): {', '.join(leaked)}")


# ---------------------------------------------------------------- breadth and selection


def breadth_by_day(bars: Mapping[str, pd.DataFrame], days: Sequence[date]) -> dict[date, float | None]:
    """At each day's close: the share of stocks closing above their own 50-day simple average of
    closes, counting only stocks with a bar that day and at least 50 closes up to it."""
    per_stock: list[dict[date, bool]] = []
    for df in bars.values():
        closes = df["close"].astype(float)
        sma = closes.rolling(BREADTH_SMA, min_periods=BREADTH_SMA).mean()
        above = {d: bool(c > s) for d, c, s in zip(df["day"], closes, sma, strict=True) if not pd.isna(s)}
        per_stock.append(above)
    out: dict[date, float | None] = {}
    for d in days:
        votes = [s[d] for s in per_stock if d in s]
        out[d] = sum(votes) / len(votes) if votes else None
    return out


def _non_empty(picks: dict[date, list[str]]) -> dict[date, list[str]]:
    return {d: syms for d, syms in picks.items() if syms}


def select_b1(scores: Mapping[str, Mapping[date, float]], days: Sequence[date]) -> dict[date, list[str]]:
    out: dict[date, list[str]] = {}
    for d in days:
        ranked = sorted(
            ((s[d], sym) for sym, s in scores.items() if d in s and s[d] >= SCORE_LINE), reverse=True
        )
        out[d] = [sym for _, sym in ranked]
    return _non_empty(out)


def select_top_k(
    scores: Mapping[str, Mapping[date, float]], days: Sequence[date], k: int = TOP_K
) -> dict[date, list[str]]:
    return _non_empty(top_k_by_day(dict(scores), days, k))


def select_b3(
    scores: Mapping[str, Mapping[date, float]],
    days: Sequence[date],
    breadth: Mapping[date, float | None],
) -> dict[date, list[str]]:
    weak = [d for d in days if breadth.get(d) is not None and breadth[d] < WEAK_BREADTH]
    return select_top_k(scores, weak)


# ---------------------------------------------------------------- labels (amendment A1)


def label(ok: bool | None) -> str:
    """Development data: the best possible label is NO WARNING (diagnostic), never PASS."""
    if ok is None:
        return INCONCLUSIVE
    return NO_WARNING if ok else FAIL


def label_from_range(low: float | None, high: float | None, line: float = 0.0) -> str:
    """Above the line only if the whole confidence range is; spanning it is INCONCLUSIVE."""
    if low is None or high is None:
        return INCONCLUSIVE
    if low > line:
        return NO_WARNING
    if high < line:
        return FAIL
    return INCONCLUSIVE


# ---------------------------------------------------------------- trade level (3a, A2, A5)


def _done(o) -> bool:
    return o is not None and o.net_return is not None


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def confidence_range(values: Sequence[float]) -> tuple[float | None, float | None]:
    """5th and 95th percentile of the mean, by the 3a block bootstrap (15-day blocks, 2,000 draws,
    seed 7, `walk_forward.bootstrap_low`). The upper end is the same bootstrap on the negated values."""
    from swing_trade_ml.brain.walk_forward import bootstrap_low

    low = bootstrap_low(list(values))
    if low is None:
        return None, None
    return low, -bootstrap_low([-v for v in values])


def _in_order(picks: Mapping[date, list[str]]) -> dict[date, list[str]]:
    return {d: list(picks[d]) for d in sorted(picks)}


def day_results(picks: Mapping[date, list[str]], outcomes: Mapping) -> list[float]:
    """3a daily aggregation: per day, the average net result of that day's finished ideas."""
    out = []
    for d, syms in _in_order(picks).items():
        rs = [outcomes[(s, d)].net_return for s in syms if _done(outcomes.get((s, d)))]
        if rs:
            out.append(sum(rs) / len(rs))
    return out


def trade_summary(
    picks: Mapping[date, list[str]], outcomes: Mapping, everyone: Mapping[date, list[str]]
) -> dict:
    """Counts, hit rate and average per trade after costs, with the day edge over every-stock and
    the 3a confidence range on both the day result and the day edge (A5)."""
    from swing_trade_ml.brain.horizon_grid import _group, summarise
    from swing_trade_ml.brain.walk_forward import daily_edge

    ordered = _in_order(picks)
    s = summarise(_group(ordered, dict(outcomes)))
    results = day_results(ordered, outcomes)
    edges = daily_edge(ordered, dict(everyone), dict(outcomes))
    s["day_result_low"], s["day_result_high"] = confidence_range(results)
    s["edge_per_day"] = _mean(edges)
    s["edge_low"], s["edge_high"] = confidence_range(edges)
    s["edge_days"] = len(edges)
    days_with = [d for d in ordered if any(_done(outcomes.get((x, d))) for x in ordered[d])]
    s["period"] = [days_with[0].isoformat(), days_with[-1].isoformat()] if days_with else None
    return s


def edge_against(picks: Mapping[date, list[str]], other: Mapping[date, list[str]], outcomes: Mapping) -> dict:
    """Day edge of `picks` over another selection on the days both have finished ideas."""
    from swing_trade_ml.brain.walk_forward import daily_edge

    edges = daily_edge(_in_order(picks), dict(other), dict(outcomes))
    low, high = confidence_range(edges)
    return {"days": len(edges), "edge_per_day": _mean(edges), "edge_low": low, "edge_high": high}


def _quantile(xs: Sequence[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[int(q * (len(s) - 1))]


def _draw_summary(values: list[float], candidate_avg: float | None) -> dict:
    beaten = None
    if candidate_avg is not None and values:
        beaten = sum(v < candidate_avg for v in values) / len(values)
    return {
        "draws": len(values),
        "avg_net_mean": _mean(values),
        "p5": _quantile(values, 0.05),
        "p95": _quantile(values, 0.95),
        "share_beaten": beaten,
    }


def random5_trade(
    days: Sequence[date],
    everyone: Mapping[date, list[str]],
    outcomes: Mapping,
    *,
    candidate_avg: float | None,
    draws: int = RANDOM_DRAWS,
    seed: int = RANDOM_SEED,
) -> dict:
    """3a random 5: per draw, 5 random finished stocks on each candidate day; average per trade."""
    import random

    rng = random.Random(seed)
    pools = {d: sorted(s for s in everyone.get(d, []) if _done(outcomes.get((s, d)))) for d in sorted(days)}
    values = []
    for _ in range(draws):
        rs = [
            outcomes[(s, d)].net_return
            for d, pool in pools.items()
            for s in rng.sample(pool, min(TOP_K, len(pool)))
        ]
        if rs:
            values.append(sum(rs) / len(rs))
    return _draw_summary(values, candidate_avg)


def vol20_by_day(bars: Mapping[str, pd.DataFrame], days: Sequence[date]) -> dict[str, dict[date, float]]:
    """20-day volatility (standard deviation of daily close-to-close returns over the last 20),
    known at each day's close."""
    wanted = set(days)
    out: dict[str, dict[date, float]] = {}
    for sym, df in bars.items():
        rets = df["close"].astype(float).pct_change()
        vol = rets.rolling(20, min_periods=20).std()
        out[sym] = {
            d: float(v) for d, v in zip(df["day"], vol, strict=True) if d in wanted and not pd.isna(v)
        }
    return out


def vol_thirds(vol: Mapping[str, Mapping[date, float]], day: date, symbols: Iterable[str]) -> dict[str, int]:
    """0 = calmest third of the day's stocks by 20-day volatility, 2 = wildest. Ties by name."""
    have = sorted((vol[s][day], s) for s in symbols if day in vol.get(s, {}))
    n = len(have)
    return {s: i * 3 // n for i, (_, s) in enumerate(have)}


def risk_matched_random(
    picks: Mapping[date, list[str]],
    everyone: Mapping[date, list[str]],
    outcomes: Mapping,
    buckets: Mapping[str, str | None],
    vol: Mapping[str, Mapping[date, float]],
    *,
    draws: int = RANDOM_DRAWS,
    seed: int = RANDOM_SEED,
) -> dict:
    """A2: for each finished idea, a random stock from the same sector and the same volatility
    third on that day (the idea's own stock included, so a match always exists when the idea has
    a volatility). Ideas without a volatility are counted as unmatched and left out."""
    import random

    def sector(s: str) -> str:
        return buckets.get(s) or "unmapped"

    keyed: list[tuple[date, list[str]]] = []
    unmatched = 0
    cand: list[float] = []
    for d, syms in _in_order(picks).items():
        done = [s for s in everyone.get(d, []) if _done(outcomes.get((s, d)))]
        thirds = vol_thirds(vol, d, done)
        for s in syms:
            if not _done(outcomes.get((s, d))):
                continue
            if s not in thirds:
                unmatched += 1
                continue
            pool = sorted(x for x in thirds if thirds[x] == thirds[s] and sector(x) == sector(s))
            keyed.append((d, pool))
            cand.append(outcomes[(s, d)].net_return)
    rng = random.Random(seed)
    values = []
    for _ in range(draws):
        rs = [outcomes[(rng.choice(pool), d)].net_return for d, pool in keyed]
        if rs:
            values.append(sum(rs) / len(rs))
    out = _draw_summary(values, _mean(cand))
    out.update(ideas=len(cand), unmatched=unmatched, draw_values=values)
    return out


def _round_trip(ix: pd.DataFrame, entry: date, exit_: date) -> float:
    """One stock-sized trade in an index: buy at `entry`'s open, sell at `exit_`'s close, with the
    same slippage and charges as a stock trade (`services/costs.py`)."""
    from swing_trade_ml.brain.replay_scoring import POSITION_INR, _sell
    from swing_trade_ml.services.costs import apply_slippage, compute_charges

    fill = apply_slippage(float(ix.loc[entry, "open"]), "BUY")
    qty = POSITION_INR / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    cash_in = fill * qty + brokerage + taxes
    return _sell(float(ix.loc[exit_, "close"]), qty) / cash_in - 1.0


def nifty_matched(picks: Mapping[date, list[str]], outcomes: Mapping, nifty: pd.DataFrame) -> dict:
    """3a NIFTY matched holding period: for each finished idea, NIFTY 50 from the same entry open to
    that idea's exit day close, with one stock trade's costs. A trade-level comparison only."""
    import bisect

    ix = nifty.set_index("day")
    nd = list(nifty["day"])
    rs, cand = [], []
    for d, syms in _in_order(picks).items():
        for s in syms:
            o = outcomes.get((s, d))
            if not _done(o) or o.exit_day is None:
                continue
            k = bisect.bisect_right(nd, d)
            j = bisect.bisect_right(nd, o.exit_day) - 1
            if k >= len(nd) or j < k:
                continue
            rs.append(_round_trip(ix, nd[k], nd[j]))
            cand.append(o.net_return)
    avg = _mean(rs)
    return {
        "ideas": len(rs),
        "avg_net": avg,
        "candidate_avg_same_ideas": _mean(cand),
        "candidate_minus_nifty": None if avg is None else _mean(cand) - avg,
        "note": "comparison only: its exits follow the candidate's trades, so no one could run it",
    }


def b3_skipped_days(
    scores: Mapping[str, Mapping[date, float]],
    days: Sequence[date],
    breadth: Mapping[date, float | None],
    outcomes: Mapping,
) -> dict:
    """B3's extra report: what the model's best 5 did on the days B3 stayed out."""
    weak = set(select_b3(scores, days, breadth))
    other = select_top_k(scores, [d for d in days if d not in weak])
    rs = [
        outcomes[(s, d)].net_return for d, syms in other.items() for s in syms if _done(outcomes.get((s, d)))
    ]
    losses = [r for r in rs if r < 0]
    gains = [r for r in rs if r > 0]
    return {
        "days": len(other),
        "ideas": len(rs),
        "losses_avoided": {"count": len(losses), "avg_net": _mean(losses)},
        "profits_missed": {"count": len(gains), "avg_net": _mean(gains)},
        "avg_net_of_skipped": _mean(rs),
    }


# ---------------------------------------------------------------- portfolio level (3a)

PORTFOLIO_CAPITAL = 1_000_000.0
CASH = {"final_net_return": 0.0, "max_drawdown": 0.0, "halt_triggered": False, "days_halted": 0}


def _risk(r) -> dict:
    return {
        "final_net_return": r.total_return,
        "max_drawdown": r.max_drawdown,
        "halt_triggered": r.triggers > 0,
        "days_halted": r.halted_days,
        "trades": r.trades,
        "still_open": r.still_open,
        "skipped": dict(r.skipped),
    }


def _as_picks(picks_by_day: Mapping[date, list[str]], buckets: Mapping[str, str | None]):
    from swing_trade_ml.brain.portfolio_sim import Pick

    return [
        Pick(d, s, float(len(syms) - i), buckets.get(s))
        for d, syms in sorted(picks_by_day.items())
        for i, s in enumerate(syms)
    ]


def portfolio_strategy(
    picks_by_day: Mapping[date, list[str]],
    bars: Mapping[str, pd.DataFrame],
    days: Sequence[date],
    *,
    buckets: Mapping[str, str | None],
    capital: float = PORTFOLIO_CAPITAL,
) -> dict:
    """One account through `portfolio_sim.simulate` (ladder limits, sector cap, 15% halt, costs).
    Each day's list is bought in order, best first."""
    from swing_trade_ml.brain.portfolio_sim import simulate

    return _risk(simulate(_as_picks(picks_by_day, buckets), dict(bars), list(days), capital=capital))


def portfolio_random5(
    pool_by_day: Mapping[date, list[str]],
    bars: Mapping[str, pd.DataFrame],
    days: Sequence[date],
    *,
    buckets: Mapping[str, str | None],
    draws: int = PORTFOLIO_DRAWS,
    seed: int = RANDOM_SEED,
    capital: float = PORTFOLIO_CAPITAL,
) -> dict:
    """3a portfolio random 5: 5 random stocks every trading day; `draws` seeded accounts
    (seeds `seed`, `seed` + 1, ...)."""
    import statistics

    from swing_trade_ml.brain.portfolio_sim import random_picks, simulate

    per_day = dict.fromkeys(pool_by_day, TOP_K)
    runs = [
        _risk(
            simulate(
                random_picks(dict(pool_by_day), per_day, seed + n, dict(buckets)),
                dict(bars),
                list(days),
                capital=capital,
            )
        )
        for n in range(draws)
    ]
    rets = [r["final_net_return"] for r in runs]
    return {
        "runs": draws,
        "final_net_return_median": statistics.median(rets),
        "p5": _quantile(rets, 0.05),
        "p95": _quantile(rets, 0.95),
        "max_drawdown_median": statistics.median(r["max_drawdown"] for r in runs),
        "halt_triggered_runs": sum(r["halt_triggered"] for r in runs),
        "days_halted_median": statistics.median(r["days_halted"] for r in runs),
    }


def nifty_buy_and_hold(nifty: pd.DataFrame, days: Sequence[date]) -> dict:
    """3a NIFTY buy and hold: all the capital at the first day's open, held to the last day's
    close, one round trip of costs. `services/costs.py` has no separate ETF rates, so the stock
    cost model is used (stated in the report). It has no halt rule: halt_triggered is None."""
    w = nifty[(nifty["day"] >= days[0]) & (nifty["day"] <= days[-1])].reset_index(drop=True)
    if w.empty:
        return {"final_net_return": None, "max_drawdown": None, "halt_triggered": None, "days_halted": None}
    ix = w.set_index("day")
    first, last = w["day"].iloc[0], w["day"].iloc[-1]
    entry = float(ix.loc[first, "open"])
    peak, worst = 1.0, 0.0
    for c in w["close"]:
        v = float(c) / entry
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    return {
        "final_net_return": _round_trip(ix, first, last),
        "max_drawdown": worst,
        "halt_triggered": None,
        "days_halted": None,
    }


# ---------------------------------------------------------------- checks (plan sections 3 and 4, A1, A9a)

MAX_DRAWDOWN = 0.15
MIN_IDEAS = 100
MARKET_TYPE_LIMIT = -0.01
MARKET_TYPE_MIN_WINDOWS = 3
BEST_SHARE_DROPPED = 0.05
MAX_STOCK_PROFIT_SHARE = 0.20


def reject_label(*, cand_avg: float | None, every_avg: float | None, days: int) -> str:
    """Robustness check on the reject set. It can only reject: FAIL when the candidate's rule does
    worse per trade than every reject-set stock on the same days; otherwise no warning."""
    if days < MIN_DAYS or cand_avg is None or every_avg is None:
        return INCONCLUSIVE
    return FAIL if cand_avg < every_avg else NO_WARNING


def coverage_label(*, ideas: int, weeks: float) -> str:
    if ideas < MIN_IDEAS:
        return INCONCLUSIVE
    return label(ideas / weeks >= 1.0)


def consistency(trades: Sequence[tuple[str, float]]) -> dict:
    """Still profitable without the best 5% of trades; no single stock more than 20% of the profit.
    Every trade is the same size, so summed returns stand in for rupees."""
    import math

    rs = sorted((r for _, r in trades), reverse=True)
    drop = math.ceil(BEST_SHARE_DROPPED * len(rs))
    without_best = sum(rs[drop:]) > 0 if rs else None
    total = sum(rs)
    by_stock: dict[str, float] = {}
    for s, r in trades:
        by_stock[s] = by_stock.get(s, 0.0) + r
    share = max(by_stock.values()) / total if total > 0 and by_stock else None
    if not rs:
        lab = INCONCLUSIVE
    else:
        lab = label(bool(without_best) and share is not None and share <= MAX_STOCK_PROFIT_SHARE)
    return {
        "trades": len(rs),
        "dropped_best": drop,
        "profitable_without_best_5pct": without_best,
        "largest_stock_share": share,
        "label": lab,
    }


def market_label(types: Mapping[str, Mapping]) -> str:
    seen = {k: v for k, v in types.items() if v.get("windows", 0) >= MARKET_TYPE_MIN_WINDOWS}
    if not seen:
        return INCONCLUSIVE
    bad = [k for k, v in seen.items() if v.get("avg_net") is not None and v["avg_net"] < MARKET_TYPE_LIMIT]
    return label(not bad)


def survives(*, beats_label: str, reject: str) -> bool:
    """Plan section 3: beats every-stock and momentum per trade after costs on development data,
    and is not worse than every-stock on the reject set. An INCONCLUSIVE part does not survive."""
    return beats_label == NO_WARNING and reject == NO_WARNING


# ---------------------------------------------------------------- one candidate, end to end


@dataclass(slots=True)
class Inputs:
    """Everything one candidate run needs; built from the database by `load_real`, or by hand in tests."""

    bars: dict[str, pd.DataFrame]  # the 49, history before the window and time to finish after it
    reject_bars: dict[str, pd.DataFrame]  # the 129
    scores: dict[str, dict[date, float]]  # the 49, test days only, each from its own fold's model
    reject_scores: dict[str, dict[date, float]]  # the 129, scored by the same fold models
    nifty: pd.DataFrame
    buckets: dict[str, str | None]  # sector bucket per stock (None = unmapped)
    folds: list  # walk_forward.Fold
    models: list[dict]  # per fold: name, cutoff, trained_on, leakage
    rules_only: dict[date, list[str]] | None  # A2 rules-only ideas per day; None = not run
    data_quality: dict | None
    window: tuple[date, date] = (DEV_START, DEV_END)


def _trading_days(bars: Mapping[str, pd.DataFrame], start: date, end: date | None = None) -> list[date]:
    return sorted({d for df in bars.values() for d in df["day"] if d >= start and (end is None or d <= end)})


def _select(cid: str, scores, days, breadth) -> dict[date, list[str]]:
    if cid == "B1":
        return select_b1(scores, days)
    if cid == "B3":
        return select_b3(scores, days, breadth)
    return select_top_k(scores, days)


def _on(picks: Mapping[date, list[str]], days: Iterable[date]) -> dict[date, list[str]]:
    return {d: list(picks[d]) for d in days if picks.get(d)}


def _not_testable(why: str) -> dict:
    return {"label": NOT_TESTABLE, "why": why}


RULES_ONLY_MISSING = (
    "no rules-only replay was supplied (whole-brain replay with M06 removed and no model fallback)"
)
MID_SMALL_WHY = (
    "NIFTY Midcap 150 and Smallcap 250 are not stored; owner decision 2026-10-21: added after the "
    "current trial"
)


def evaluate(
    candidate_id: str,
    inp: Inputs,
    *,
    manifest: dict,
    random_draws: int = RANDOM_DRAWS,
    portfolio_draws: int = PORTFOLIO_DRAWS,
) -> dict:
    """Score one candidate on development data with every comparison and check. Pure: no database."""
    from swing_trade_ml.brain import splits
    from swing_trade_ml.brain.replay_scoring import STOP, TARGET
    from swing_trade_ml.brain.walk_forward import classify_regime, momentum_scores, outcomes_for

    cand = _candidate(candidate_id)
    start, end = inp.window
    days = _trading_days(inp.bars, start, end)
    outcomes = outcomes_for(inp.bars, days, HORIZON, TARGET, STOP)
    everyone = {d: sorted(s for (s, dd) in outcomes if dd == d) for d in days}
    breadth = breadth_by_day(inp.bars, days)
    picks = _select(candidate_id, inp.scores, days, breadth)
    cdays = sorted(picks)
    mom_all = select_top_k(momentum_scores(inp.bars, days), days)
    model_all = select_top_k(inp.scores, days)

    # trade level, matched to the candidate's days (3a, A2)
    c_sum = trade_summary(picks, outcomes, everyone)
    every = _on(everyone, cdays)
    trade = {
        "candidate": c_sum,
        "every_stock": trade_summary(every, outcomes, everyone),
        "random_5": random5_trade(
            cdays, everyone, outcomes, candidate_avg=c_sum["avg_net"], draws=random_draws
        ),
        "momentum": trade_summary(_on(mom_all, cdays), outcomes, everyone),
        "nifty_matched": nifty_matched(picks, outcomes, inp.nifty),
        "cash": {"avg_net": 0.0},
        "model_only": trade_summary(_on(model_all, cdays), outcomes, everyone),
        "rules_only": (
            trade_summary(_on(inp.rules_only, cdays), outcomes, everyone)
            if inp.rules_only is not None
            else _not_testable(RULES_ONLY_MISSING)
        ),
        "risk_matched_random": risk_matched_random(
            picks, everyone, outcomes, inp.buckets, vol20_by_day(inp.bars, cdays), draws=random_draws
        ),
        "mid_small_cap_index": _not_testable(MID_SMALL_WHY),
    }
    trade["risk_matched_random"].pop("draw_values", None)
    edge_mom = edge_against(picks, _on(mom_all, cdays), outcomes)

    # portfolio level, equal capital, each strategy on its own rules (3a)
    pdays = _trading_days(inp.bars, start)
    pool = {d: everyone[d] for d in days if everyone[d]}
    port = {
        "candidate": portfolio_strategy(picks, inp.bars, pdays, buckets=inp.buckets),
        "random_5": portfolio_random5(pool, inp.bars, pdays, buckets=inp.buckets, draws=portfolio_draws),
        "momentum_5": portfolio_strategy(mom_all, inp.bars, pdays, buckets=inp.buckets),
        "model_only_5": portfolio_strategy(model_all, inp.bars, pdays, buckets=inp.buckets),
        "rules_only": (
            portfolio_strategy(_on(inp.rules_only, days), inp.bars, pdays, buckets=inp.buckets)
            if inp.rules_only is not None
            else _not_testable(RULES_ONLY_MISSING)
        ),
        "nifty_buy_and_hold": nifty_buy_and_hold(inp.nifty, pdays),
        "cash": dict(CASH),
    }

    # market types, labelled after the fact per 28-day fold (3a)
    labels, rows = [], []
    for f in inp.folds:
        lab = classify_regime(inp.bars, f.start, f.end)["label"]
        labels.append(lab)
        rows += [
            (lab, s, outcomes.get((s, d))) for d, syms in picks.items() if f.start <= d <= f.end for s in syms
        ]
    market = splits.by_market_type(rows, labels)

    # reject-set robustness check (reject only); breadth always from the 49
    r_out = outcomes_for(inp.reject_bars, days, HORIZON, TARGET, STOP)
    r_every = {d: sorted(s for (s, dd) in r_out if dd == d) for d in days}
    r_picks = _select(candidate_id, inp.reject_scores, days, breadth)
    r_cand = trade_summary(r_picks, r_out, r_every)
    r_base = trade_summary(_on(r_every, sorted(r_picks)), r_out, r_every)
    reject = {
        "candidate": r_cand,
        "every_stock": r_base,
        "label": reject_label(cand_avg=r_cand["avg_net"], every_avg=r_base["avg_net"], days=r_cand["days"]),
        "note": "the reject set can only reject a candidate; it never confirms one",
    }

    # checks
    weeks = ((end - start).days + 1) / 7
    enough = c_sum["days"] >= MIN_DAYS
    finished = [
        (s, outcomes[(s, d)].net_return)
        for d, syms in picks.items()
        for s in syms
        if _done(outcomes.get((s, d)))
    ]

    def gated(lab: str) -> str:
        return lab if enough else INCONCLUSIVE

    def beats(a: float | None, *bs: float | None) -> bool | None:
        if a is None or any(b is None for b in bs):
            return None
        return all(a > b for b in bs)

    ca, ea, ma = c_sum["avg_net"], trade["every_stock"]["avg_net"], trade["momentum"]["avg_net"]
    nm = trade["nifty_matched"]["candidate_minus_nifty"]
    pc, pr = port["candidate"]["final_net_return"], port["random_5"]["final_net_return_median"]
    pm, pn = port["momentum_5"]["final_net_return"], port["nifty_buy_and_hold"]["final_net_return"]
    beats_lab = gated(label(beats(ca, ea, ma)))
    cons = consistency(finished)
    checks = [
        {
            "id": "phase_b_beats_every_stock_and_momentum",
            "rule": "average per trade after costs above every-stock and momentum (plan section 3)",
            "value": {"candidate": ca, "every_stock": ea, "momentum": ma},
            "label": beats_lab,
        },
        {
            "id": "reject_set",
            "rule": "not worse than every-stock on the reject set (reject only)",
            "value": {
                "candidate": r_cand["avg_net"],
                "every_stock": r_base["avg_net"],
                "days": r_cand["days"],
            },
            "label": reject["label"],
        },
        {
            "id": "net_return",
            "rule": "average result after costs above zero (whole confidence range of the day result)",
            "value": {"avg_net": ca, "low": c_sum["day_result_low"], "high": c_sum["day_result_high"]},
            "label": gated(label_from_range(c_sum["day_result_low"], c_sum["day_result_high"])),
        },
        {
            "id": "baselines_trade_level",
            "rule": "beats every-stock and momentum per trade, and NIFTY over the matched holding periods",
            "value": {"candidate": ca, "every_stock": ea, "momentum": ma, "minus_nifty": nm},
            "label": gated(
                label(None if beats(ca, ea, ma) is None or nm is None else beats(ca, ea, ma) and nm > 0)
            ),
        },
        {
            "id": "baselines_portfolio_level",
            "rule": "final net return above Random 5 median, Momentum 5, NIFTY buy and hold and cash",
            "value": {"candidate": pc, "random_5_median": pr, "momentum_5": pm, "nifty": pn, "cash": 0.0},
            "label": gated(label(beats(pc, pr, pm, pn, 0.0))),
        },
        {
            "id": "statistical_confidence",
            "rule": "lower bound of the mean day edge over every-stock above zero (15-day blocks, 2,000 draws, seed 7)",
            "value": {"edge": c_sum["edge_per_day"], "low": c_sum["edge_low"], "high": c_sum["edge_high"]},
            "label": gated(label_from_range(c_sum["edge_low"], c_sum["edge_high"])),
        },
        {
            "id": "drawdown",
            "rule": "candidate's maximum drawdown in the portfolio replay under 15%",
            "value": port["candidate"]["max_drawdown"],
            "label": gated(label(port["candidate"]["max_drawdown"] < MAX_DRAWDOWN)),
        },
        {
            "id": "market_conditions",
            "rule": "no market type seen in at least 3 windows averages worse than -1% per trade",
            "value": {k: v.get("avg_net") for k, v in market.items()},
            "label": gated(market_label(market)),
        },
        {
            "id": "coverage",
            "rule": "at least 100 finished ideas and at least 1 idea per week",
            "value": {"ideas": c_sum["ideas"], "per_week": c_sum["ideas"] / weeks},
            "label": gated(coverage_label(ideas=c_sum["ideas"], weeks=weeks)),
        },
        {
            "id": "consistency",
            "rule": "profitable without the best 5% of trades; no stock above 20% of total profit",
            "value": {k: v for k, v in cons.items() if k != "label"},
            "label": gated(cons["label"]),
        },
        {
            "id": "mid_small_cap_index",
            "rule": "matched NIFTY Midcap 150 / Smallcap 250 comparison (A2)",
            "value": None,
            "label": NOT_TESTABLE,
        },
    ]

    extra: dict = {}
    if candidate_id == "B1":
        extra = {"ideas_per_week": c_sum["ideas"] / weeks, "days_with_ideas": c_sum["days"], "weeks": weeks}
    elif candidate_id == "B2":
        clean = all(m.get("leakage", "clean") == "clean" for m in inp.models)
        extra = {
            "leakage_check": (
                "clean: no reject-set stock in any training fold" if clean else "LEAKAGE FOUND: see models"
            ),
            "data_quality": inp.data_quality,
            "survivorship": SURVIVORSHIP,
        }
    else:
        years = ((end - start).days + 1) / 365.25
        skipped = b3_skipped_days(inp.scores, days, breadth, outcomes)
        extra = {
            "weak_days": sum(1 for d in days if breadth.get(d) is not None and breadth[d] < WEAK_BREADTH),
            "days_with_breadth": sum(1 for d in days if breadth.get(d) is not None),
            "trading_days_per_year": c_sum["days"] / years,
            **skipped,
        }

    return {
        "manifest": manifest,
        "candidate": {"id": cand.id, "name": cand.name, "setting": cand.setting, "extra": cand.extra},
        "window": [start.isoformat(), end.isoformat()],
        "trading_days": len(days),
        "folds": len(inp.folds),
        "trade_level": trade,
        "edge_vs_momentum": edge_mom,
        "portfolio_level": port,
        "market_types": market,
        "reject_check": reject,
        "checks": checks,
        "survives": survives(beats_label=beats_lab, reject=reject["label"]),
        "extra": extra,
        "models": inp.models,
    }


SURVIVORSHIP = (
    "All stock lists are today's: the 49 are today's watchlist and the 257 never-used stocks are "
    "today's active shares with candles. Stocks that were delisted, merged or dropped before today "
    "are missing, which flatters every strategy and baseline alike. NOT TESTABLE with our data."
)


# ---------------------------------------------------------------- manifest (A6) and ledger


def build_manifest(
    candidate_id: str,
    *,
    commit: str,
    dirty: bool,
    split: Mapping,
    window: tuple[date, date],
    models: Sequence[Mapping],
    ledger_row: str,
) -> dict:
    cand = _candidate(candidate_id)
    trained_on = len(training_symbols(candidate_id, split)) if "used_49" in split else None
    return {
        "candidate": {"id": cand.id, "name": cand.name, "setting": cand.setting},
        "protocol": f"{PROTOCOL_ID} v{PROTOCOL_VERSION}",
        "defs_version": f"{DEFS_VERSION} (adds to evidence-defs-v1)",
        "code_commit": commit + (" (with uncommitted changes)" if dirty else ""),
        "data_window": f"{window[0].isoformat()} to {window[1].isoformat()} (development data)",
        "stocks": {
            "scored": f"the 49 watchlisted stocks ({len(split['used_49'])} in the split file)",
            "trained_on": trained_on,
            "reject_set": len(split["reject_set"]),
            "split_file": f"docs/brain/evidence/stock_split/{SPLIT_FILE}",
            "split_sha256": split.get("sha256"),
            "survivorship": SURVIVORSHIP,
        },
        "model": {
            "kind": "train_model (LightGBM), retrained once per 28-day fold, never activated",
            "training_window": "all history up to each fold's cutoff (the day before the fold)",
            "folds": list(models),
        },
        "horizon": "15 trading days (+8% / -4%, half out at +5%, next-day open entry, costs)",
        "exposure_ledger_row": ledger_row,
    }


LEDGER_MARKER = "Phase B candidate {cid}"


def ledger_row(candidate_id: str, *, run_day: date, report_name: str, window: tuple[date, date]) -> str:
    cand = _candidate(candidate_id)
    return (
        f"| {window[0].isoformat()} to {window[1].isoformat()} (49 stocks; reject set of 129 for the "
        f"robustness check) | {LEDGER_MARKER.format(cid=cand.id)} ({cand.name}): trade and portfolio "
        f"results, baselines, reject-set check; run once | Owner's decision: to be written after "
        f"reading | {run_day.isoformat()} | `phase_b/{report_name}` |"
    )


def add_ledger_row(path: Path, row: str, *, candidate_id: str) -> None:
    """Add the run's row at the end of the ledger's local-data table, before any result exists.
    A candidate that already has a row has had its one run: refuse."""
    text = path.read_text(encoding="utf-8")
    if LEDGER_MARKER.format(cid=candidate_id) in text:
        raise RealRunRefusedError(
            f"Phase B refused: {candidate_id} already has a row in the exposure ledger, so it has "
            "already had its one run. A second run would be retuning."
        )
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Local data"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    last = max(i for i in range(start, end) if lines[i].startswith("|"))
    lines.insert(last + 1, row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- the report


def _pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def _share(x: float | None, digits: int = 0) -> str:
    """A share or a fall: no sign."""
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _range(lo: float | None, hi: float | None) -> str:
    return "too few days for a range" if lo is None else f"{_pct(lo)} to {_pct(hi)}"


def manifest_lines(m: dict, *, row_heading: str) -> list[str]:
    st = m["stocks"]
    return [
        "## Evidence manifest",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| Candidate | {m['candidate']['id']}: {m['candidate']['name']} ({m['candidate']['setting']}) |",
        f"| Protocol | {m['protocol']} |",
        f"| Definitions | {m['defs_version']} |",
        f"| Code commit | {m['code_commit']} |",
        f"| Data window | {m['data_window']} |",
        f"| Stocks | {st['scored']}; models trained on {st['trained_on']}; reject set {st['reject_set']} "
        f"(`{st['split_file']}`, SHA-256 `{st['split_sha256']}`) |",
        f"| Survivorship | {st['survivorship']} |",
        f"| Model | {m['model']['kind']}; {m['model']['training_window']}; {len(m['model']['folds'])} folds |",
        f"| Horizon | {m['horizon']} |",
        "",
        row_heading,
        "",
        m["exposure_ledger_row"],
    ]


def plain_report(result: dict) -> str:
    m, c = result["manifest"], result["candidate"]
    lines = [
        f"# Phase B, candidate {c['id']}: {c['name']}",
        "",
        *manifest_lines(m, row_heading="Exposure-ledger row (added before any result was produced):"),
        "",
        "## What this is",
        "",
        f"Setting (fixed before the run): {c['setting']}.",
        "This is development data: the best possible label here is NO WARNING (diagnostic). A FAIL here is a "
        "real warning. Confirmation can only come from data after the rules are locked (Phase C).",
        "",
        f"Survives Phase B (plan section 3): **{'yes' if result['survives'] else 'no'}**.",
        "",
        "## Checks",
        "",
        "| Check | Rule | Label |",
        "|---|---|---|",
    ]
    return _report_body(result, lines)


def _report_body(result: dict, lines: list[str]) -> str:
    c = result["candidate"]
    lines += [f"| {k['id']} | {k['rule']} | {k['label']} |" for k in result["checks"]]
    lines += [
        "",
        "## Trade level (same days, next-open entry, same exit rule and costs)",
        "",
        "| Strategy | Ideas | Days | Period | Hit target | Average per trade | Edge over every stock, per day "
        "| Confidence range (5th to 95th) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, row in result["trade_level"].items():
        if "label" in row:
            lines.append(f"| {name} | {row['label']}: {row['why']} | | | | | | |")
        elif "ideas" in row and "days" in row:
            period = " to ".join(row["period"]) if row.get("period") else "n/a"
            lines.append(
                f"| {name} | {row['ideas']} | {row['days']} | {period} | {_share(row.get('hit_rate'))} "
                f"| {_pct(row.get('avg_net'))} | {_pct(row.get('edge_per_day'))} "
                f"| {_range(row.get('edge_low'), row.get('edge_high'))} |"
            )
    r5, rm, nm = (result["trade_level"][k] for k in ("random_5", "risk_matched_random", "nifty_matched"))
    em = result["edge_vs_momentum"]
    lines += [
        "",
        f"- Random 5 ({r5['draws']} seeded draws): average {_pct(r5['avg_net_mean'])} "
        f"(5th to 95th {_pct(r5['p5'])} to {_pct(r5['p95'])}); the candidate beats "
        f"{_share(r5['share_beaten'])} of draws.",
        f"- Risk-matched random ({rm['draws']} draws, same sector and volatility third, {rm['ideas']} ideas, "
        f"{rm['unmatched']} unmatched): average {_pct(rm['avg_net_mean'])} "
        f"({_pct(rm['p5'])} to {_pct(rm['p95'])}); candidate beats {_share(rm['share_beaten'])} of draws.",
        f"- NIFTY matched ({nm['ideas']} ideas): {_pct(nm['avg_net'])} per trade; candidate minus NIFTY "
        f"{_pct(nm['candidate_minus_nifty'])}. {nm['note']}.",
        f"- Candidate minus momentum, per day ({em['days']} days): {_pct(em['edge_per_day'])} "
        f"({_range(em['edge_low'], em['edge_high'])}).",
        "- Cash: 0%.",
        "",
        "## Portfolio level (equal capital, each on its own rules; ladder limits, 25% sector cap, 15% halt)",
        "",
        f"Starting capital Rs {PORTFOLIO_CAPITAL:,.0f} each.",
        "",
        "| Strategy | Final net return | Maximum drawdown | Halt triggered | Days halted |",
        "|---|---|---|---|---|",
    ]
    for name, row in result["portfolio_level"].items():
        if "label" in row:
            lines.append(f"| {name} | {row['label']}: {row['why']} | | | |")
        elif "runs" in row:
            lines.append(
                f"| {name} ({row['runs']} runs, median) | {_pct(row['final_net_return_median'])} "
                f"({_pct(row['p5'])} to {_pct(row['p95'])}) | {_share(row['max_drawdown_median'], 1)} "
                f"| {row['halt_triggered_runs']} of {row['runs']} runs | {row['days_halted_median']} |"
            )
        else:
            halt = (
                "not applicable"
                if row["halt_triggered"] is None
                else ("yes" if row["halt_triggered"] else "no")
            )
            lines.append(
                f"| {name} | {_pct(row['final_net_return'])} | {_share(row['max_drawdown'], 1)} | {halt} "
                f"| {row['days_halted'] if row['days_halted'] is not None else 'n/a'} |"
            )
    rj = result["reject_check"]
    lines += [
        "",
        "NIFTY buy and hold uses the stock cost model (no separate ETF rates in `services/costs.py`). "
        "Every day is treated as NORMAL market mode in these accounts.",
        "",
        f"## Reject set ({rj['label']}; {rj['note']})",
        "",
        f"Candidate's rule on the reject set: {rj['candidate']['ideas']} ideas on {rj['candidate']['days']} days, "
        f"{_pct(rj['candidate']['avg_net'])} per trade; every reject-set stock on those days: "
        f"{_pct(rj['every_stock']['avg_net'])}. Edge per day {_pct(rj['candidate']['edge_per_day'])} "
        f"({_range(rj['candidate']['edge_low'], rj['candidate']['edge_high'])}).",
        "",
        "## Market types (labelled after the fact, per 28-day fold)",
        "",
        "| Market | Windows | Ideas | Finished | Average |",
        "|---|---|---|---|---|",
    ]
    for lab, row in result["market_types"].items():
        lines.append(
            f"| {lab} | {row.get('windows', 0)} | {row['ideas']} | {row.get('finished', 0)} "
            f"| {_pct(row.get('avg_net'))} |"
        )
    lines += ["", f"## Extra for {c['id']} ({c['extra']})", ""]
    lines += [f"- {k}: {_plain(v)}" for k, v in result["extra"].items()]
    return "\n".join(lines) + "\n"


def _plain(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, dict):
        return ", ".join(f"{k} {_plain(x)}" for k, x in v.items())
    return str(v)


# ---------------------------------------------------------------- real data (only after the guard)

MIN_SCORE_BARS = 220  # `ml/asof.MIN_BARS`: a stock needs this much history before it can be scored
FINISH_DAYS = 60  # calendar days of prices loaded after the window so its last ideas can finish


def _quality(names: Sequence[str], bars: Mapping[str, pd.DataFrame]) -> dict:
    enough = [s for s in names if s in bars and int((bars[s]["day"] < DEV_START).sum()) >= MIN_SCORE_BARS]
    return {
        "requested": len(names),
        "with_bars": sum(1 for s in names if s in bars),
        "enough_history_before_window": len(enough),
        "missing": sorted(s for s in names if s not in bars),
    }


def load_real(db, split: Mapping) -> dict:
    """Prices of the 49, the reject set and NIFTY 50 from the database, up to the window's end
    plus time to finish. Read-only."""
    from datetime import timedelta

    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    upto = DEV_END + timedelta(days=FINISH_DAYS)
    used, reject = list(split["used_49"]), list(split["reject_set"])
    bars = {s: df for s, df in load_bars(db, used, upto).items() if len(df)}
    rbars = {s: df for s, df in load_bars(db, reject, upto).items() if len(df)}
    bench = settings.BENCHMARK_INDEX_SYMBOL
    nifty = load_bars(db, [bench], upto).get(bench)
    if nifty is None:
        nifty = pd.DataFrame(columns=["day", "open", "high", "low", "close"])
    insts = {
        i.tradingsymbol: i
        for i in db.execute(
            select(Instrument).where(
                Instrument.tradingsymbol.in_(used + reject), Instrument.is_active.is_(True)
            )
        ).scalars()
    }
    return {
        "bars": bars,
        "reject_bars": rbars,
        "nifty": nifty,
        "buckets": {s: get_sector_bucket(s) for s in used + reject},
        "instruments": insts,
        "data_quality": {"scored_49": _quality(used, bars), "reject_set": _quality(reject, rbars)},
    }


def train_real(db, cutoff: date, symbols: Sequence[str], candidate_id: str):
    """One fold's model, trained only on `symbols` and only on outcomes known by `cutoff`. Registered
    TRAINED as `phaseb_<candidate>_<cutoff>`, never activated."""
    from swing_trade_ml.brain.replay_scoring import STOP, TARGET
    from swing_trade_ml.ml.train import train_model

    return train_model(
        db,
        name=f"phaseb_{candidate_id.lower()}_{cutoff:%Y%m%d}",
        symbols=list(symbols),
        cutoff=cutoff,
        horizon_days=HORIZON,
        target_return=TARGET,
        stop_return=STOP,
        auto_activate=False,
    )


def rules_only_real(db, days: Sequence[date]) -> dict[date, list[str]]:
    """A2 rules-only: replay the whole brain on each day with M06 left out and no as-of model, so no
    model score reaches it (the replay skips the model fallback without an as-of model). The ideas
    the brain liked are the rules-only ideas, as in ps1 (`module_ablation`). Slow: one brain run a day."""
    from swing_trade_ml.brain.module_ablation import run_variant

    out: dict[date, list[str]] = {}
    for j in run_variant(db, days, "M06", asof_model=None):
        if j.liked:
            out.setdefault(j.day, []).append(j.symbol)
    return out


def git_commit() -> tuple[str, bool]:
    """(short commit, has uncommitted changes)."""
    import subprocess

    from swing_trade_ml.core.config import REPO_ROOT

    def git(*a: str) -> str:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), *a], capture_output=True, text=True, check=False
        ).stdout

    return git("rev-parse", "--short", "HEAD").strip() or "unknown", bool(
        git("status", "--porcelain").strip()
    )


def default_out_dir() -> Path:
    from swing_trade_ml.core.config import REPO_ROOT

    return REPO_ROOT / "docs" / "brain" / "evidence" / "phase_b"


def default_ledger() -> Path:
    from swing_trade_ml.core.config import REPO_ROOT

    return REPO_ROOT / "docs" / "brain" / "EXPOSURE-LEDGER.md"


def output_paths(candidate_id: str, out_dir: Path) -> tuple[Path, Path]:
    stem = f"phase_b_{candidate_id}_{DEV_START.isoformat()}_{DEV_END.isoformat()}"
    return out_dir / f"{stem}.md", out_dir / f"{stem}.json"


def run_real(
    candidate_id: str,
    *,
    db,
    out_dir: Path | None = None,
    ledger_path: Path | None = None,
    split_dir: Path | None = None,
    today: date | None = None,
    tags: Iterable[str] | None = None,
    load_fn=load_real,
    train_fn=train_real,
    score_fn=None,
    rules_only_fn=rules_only_real,
    commit_fn=git_commit,
    random_draws: int = RANDOM_DRAWS,
    portfolio_draws: int = PORTFOLIO_DRAWS,
) -> tuple[Path, Path]:
    """The one real run of a candidate. Order: guard, one-run check, data, a model per fold with the
    leakage check, then the exposure-ledger row, and only then the results."""
    import json

    from swing_trade_ml.brain.walk_forward import make_folds

    split_dir = split_dir or default_split_dir()
    check_real_run_allowed(today=today, tags=tags, split_dir=split_dir)
    cand = _candidate(candidate_id)
    today = today or ist_today()
    out_dir = out_dir or default_out_dir()
    ledger_path = ledger_path or default_ledger()
    md, js = output_paths(candidate_id, out_dir)
    if md.exists() or js.exists():
        raise RealRunRefusedError(f"Phase B refused: {candidate_id} has already run ({md.name} exists).")
    if LEDGER_MARKER.format(cid=candidate_id) in ledger_path.read_text(encoding="utf-8"):
        raise RealRunRefusedError(
            f"Phase B refused: {candidate_id} already has a row in the exposure ledger, so it has already run."
        )
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn

    split = load_split(split_dir)
    reject = list(split["reject_set"])
    train_on = training_symbols(candidate_id, split)
    folds = make_folds(DEV_START, DEV_END)
    data = load_fn(db, split)
    insts = data["instruments"]

    scores: dict[str, dict[date, float]] = {s: {} for s in data["bars"] if s in insts}
    reject_scores: dict[str, dict[date, float]] = {s: {} for s in data["reject_bars"] if s in insts}
    models: list[dict] = []
    extra_in_training: list[int] = []
    for fold in folds:
        model = train_fn(db, fold.cutoff, train_on, candidate_id)
        trained = list(getattr(model, "training_symbols", None) or [])
        if not trained:
            raise LeakageError(
                f"Fold {fold.start}: the model does not list its training stocks, so leakage cannot be checked."
            )
        assert_no_leakage(trained, reject=reject, where=f"{cand.id} fold starting {fold.start}")
        extra_in_training.append(len(set(trained) & set(split["extra_training_set"])))
        models.append(
            {
                "name": getattr(model, "name", None),
                "cutoff": fold.cutoff.isoformat(),
                "test_days": f"{fold.start.isoformat()} to {fold.end.isoformat()}",
                "trained_on": len(trained),
                "leakage": "clean",
            }
        )
        for target in (scores, reject_scores):
            for sym in target:
                got = score_fn(db, insts[sym], model, fold.cutoff)
                target[sym].update({d: p for d, p in got.items() if fold.start <= d <= fold.end})

    window_days = _trading_days(data["bars"], DEV_START, DEV_END)
    rules_only = rules_only_fn(db, window_days) if rules_only_fn is not None else None
    quality = dict(data.get("data_quality") or {})
    if candidate_id == "B2":
        quality["extra_training_set"] = {
            "requested": len(split["extra_training_set"]),
            "in_training_per_fold": extra_in_training,
        }

    row = ledger_row(candidate_id, run_day=today, report_name=md.name, window=(DEV_START, DEV_END))
    commit, dirty = commit_fn()
    manifest = build_manifest(
        candidate_id,
        commit=commit,
        dirty=dirty,
        split=split,
        window=(DEV_START, DEV_END),
        models=models,
        ledger_row=row,
    )
    add_ledger_row(ledger_path, row, candidate_id=candidate_id)  # before any result exists

    result = evaluate(
        candidate_id,
        Inputs(
            bars=data["bars"],
            reject_bars=data["reject_bars"],
            scores=scores,
            reject_scores=reject_scores,
            nifty=data["nifty"],
            buckets=data["buckets"],
            folds=folds,
            models=models,
            rules_only=rules_only,
            data_quality=quality,
            window=(DEV_START, DEV_END),
        ),
        manifest=manifest,
        random_draws=random_draws,
        portfolio_draws=portfolio_draws,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    md.write_text(plain_report(result), encoding="utf-8", newline="\n")
    js.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return md, js


# ---------------------------------------------------------------- dry run and command line


def dry_run_plan(
    candidate_id: str,
    *,
    split_dir: Path | None = None,
    today: date | None = None,
    tags: Iterable[str] | None = None,
    commit: tuple[str, bool] | None = None,
) -> str:
    """The plan of a real run: dates, stocks, manifest. Reads no market data and scores nothing."""
    from swing_trade_ml.brain.walk_forward import make_folds
    from swing_trade_ml.core.config import REPO_ROOT

    cand = _candidate(candidate_id)
    split_dir = split_dir or default_split_dir()
    split = load_split(split_dir)
    today = today or ist_today()
    tags = git_tags(REPO_ROOT) if tags is None else set(tags)
    commit_id, dirty = commit or git_commit()
    folds = make_folds(DEV_START, DEV_END)
    train_on = training_symbols(candidate_id, split)
    reasons = refusal_reasons(today=today, tags=tags, split_dir=split_dir)
    planned = [
        {
            "name": f"phaseb_{candidate_id.lower()}_{f.cutoff:%Y%m%d} (planned)",
            "cutoff": f.cutoff.isoformat(),
            "test_days": f"{f.start.isoformat()} to {f.end.isoformat()}",
            "trained_on": len(train_on),
        }
        for f in folds
    ]
    row = ledger_row(
        candidate_id,
        run_day=PHASE_B_START if today < PHASE_B_START else today,
        report_name=output_paths(candidate_id, Path("."))[0].name,
        window=(DEV_START, DEV_END),
    )
    manifest = build_manifest(
        candidate_id,
        commit=commit_id,
        dirty=dirty,
        split=split,
        window=(DEV_START, DEV_END),
        models=planned,
        ledger_row=row,
    )
    extra = sorted(set(train_on) - set(split["used_49"]))
    lines = [
        f"DRY RUN: Phase B candidate {cand.id} ({cand.name}). Nothing was scored and no market data was read.",
        "",
        f"Setting, fixed before the run: {cand.setting}.",
        f"Extra report: {cand.extra}.",
        "",
        f"Development window: {DEV_START.isoformat()} to {DEV_END.isoformat()}; {len(folds)} test windows of "
        "28 days, each with its own model trained on all history up to the day before it:",
        *[
            f"  window {i}: model cutoff {f.cutoff}, test days {f.start} to {f.end}"
            for i, f in enumerate(folds, 1)
        ],
        "",
        f"Stocks scored ({len(split['used_49'])}): {', '.join(split['used_49'])}",
        f"Stocks the models learn from ({len(train_on)}): "
        + ("the 49 above" if not extra else f"the 49 above + {len(extra)} extra: {', '.join(extra)}"),
        f"Reject set ({len(split['reject_set'])}, robustness check only, never in any training data): "
        f"{', '.join(split['reject_set'])}",
        f"Split file SHA-256: {split['sha256']}",
        "",
        "A real run today: "
        + ("allowed." if not reasons else "Phase B refused:\n" + "\n".join(f"- {r}" for r in reasons)),
        "",
        *manifest_lines(manifest, row_heading="Exposure-ledger row a real run will add before any result:"),
        "",
        "## What a real run will produce",
        "",
        "- Trade level on the candidate's days: every stock, random 5 (1,000 draws), momentum, NIFTY matched, "
        "cash, model-only, rules-only (whole-brain replay with M06 removed), risk-matched random (1,000 draws); "
        "mid/small-cap index NOT TESTABLE.",
        "- Portfolio level, equal capital: candidate, random 5 (200 runs), momentum 5, model-only 5, rules-only, "
        "NIFTY buy and hold, cash; each with maximum drawdown, halt triggered, days halted, final net return.",
        "- Reject-set check (it can only reject), market types, the plan's checks with labels, and whether the "
        "candidate survives Phase B.",
    ]
    return "\n".join(lines) + "\n"


def cli(args) -> int:
    """`swingtrade brain phase-b --candidate B1 [--dry-run] [--out DIR]`."""
    import sys

    if args.dry_run:
        print(dry_run_plan(args.candidate))
        return 0
    try:
        check_real_run_allowed()
    except RealRunRefusedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    from swing_trade_ml.db.session import SessionLocal

    with SessionLocal() as db:
        try:
            md, js = run_real(args.candidate, db=db, out_dir=Path(args.out) if args.out else None)
        except (RealRunRefusedError, LeakageError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(
        f"Written: {md} and {js}. The exposure-ledger row was added before the results; write the owner's "
        "decision into it after reading."
    )
    return 0
