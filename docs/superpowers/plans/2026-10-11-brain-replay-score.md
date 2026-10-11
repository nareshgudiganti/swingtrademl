# Brain Replay-and-Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command, `swingtrade brain replay-score`, that replays the brain over past trading days, scores every idea against what the stock really did, compares it with baselines, and writes a plain-English report.

**Architecture:** Two pure modules (strict scorer, report maths) and one orchestrator that reuses `run_replay_week` for the replay and `m09_learn.outcomes.score` for the locked rule. It is read-only with respect to live evidence: it never writes `brain_decisions.outcome*` and never touches the 30-idea gate. A thin CLI wrapper prints the summary and writes JSON.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy (Postgres test DB), pytest. Run tests with `backend/.venv/Scripts/python.exe` and `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE` (Docker Postgres must be up or DB tests hang silently).

**Spec:** `docs/superpowers/specs/2026-10-11-brain-replay-score-design.md`

## Global Constraints

- Horizon 15 trading bars, target +8%, stop −4%, half out at +5% (CLAUDE.md principle 7).
- Same-bar touch of stop and target counts as the stop.
- Daily candles are stamped IST midnight (18:30 UTC previous day): always convert with `.astimezone(IST).date()`.
- Never write to `brain_decisions.outcome`, `outcome_return`, `outcome_days`, `max_up`, `max_down`, `resolved_on`.
- Never change `COUNT_BLOCKED_TOWARD_GATE`, order placement, sizing, stops or limits.
- Do not `ruff format` the whole package: format only files you touched.
- Plain English in anything the owner reads (summary text, report).
- The cost model (`services/costs.py`) is used as it is; do not edit it.

## Review Focus

- A window where no idea was produced: report says "no ideas", exits cleanly, no division by zero.
- Ideas whose stock has no candles after the decision day: counted as "still open", never as win or loss.
- A symbol with no candles at all (delisted/renamed): skipped and counted in a "no price data" line.
- The newest ideas (fewer than 15 bars after them) must be listed as open, not scored on partial data.
- Two ideas for the same stock on consecutive days both appear (no silent de-duplication).
- A replay run that fails on one day must not hide the other days: the report lists the failed days.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/swing_trade_ml/brain/replay_scoring.py` (new, pure) | Strict scorer and bar helpers. No DB. |
| `backend/src/swing_trade_ml/brain/replay_report.py` (new, pure) | Stats per track, baselines, plain-English summary, JSON. No DB. |
| `backend/src/swing_trade_ml/brain/replay_score.py` (new) | Replay, collect ideas, load bars, score, assemble the report. |
| `backend/src/swing_trade_ml/cli.py` (modify) | `brain replay-score` subcommand. |
| `backend/tests/test_brain_replay_scoring.py` (new) | Strict scorer tests. |
| `backend/tests/test_brain_replay_report.py` (new) | Stats, baselines, summary tests. |
| `backend/tests/test_brain_replay_score.py` (new) | DB-backed orchestrator tests. |
| `docs/brain/TESTING.md` (modify) | How to run and read it. |

---

### Task 1: Strict scorer (pure)

**Files:**
- Create: `backend/src/swing_trade_ml/brain/replay_scoring.py`
- Test: `backend/tests/test_brain_replay_scoring.py`

**Interfaces:**
- Produces:
  - `StrictOutcome(status: str, net_return: float | None, days: int | None, half_out: bool, gap: bool, exit_day: date | None)` (frozen dataclass; `status` is `target|stop|timeout|open`)
  - `strict_score(bars: pd.DataFrame) -> StrictOutcome` (bars: columns `day, open, high, low, close`; first row is the entry day)
  - `after_day(df: pd.DataFrame, day: date) -> pd.DataFrame` (rows with `day` strictly after the decision day, reset index)
  - `locked_score(df: pd.DataFrame, day: date) -> Outcome | None` (the existing M09 rule, entry at the decision day's close)
  - `strict_for(df: pd.DataFrame, day: date) -> StrictOutcome`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_brain_replay_scoring.py
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.replay_scoring import after_day, locked_score, strict_for, strict_score

START = date(2026, 9, 28)


def bars(rows):
    return pd.DataFrame(
        [
            {"day": START + timedelta(days=i), "open": o, "high": h, "low": lo, "close": c}
            for i, (o, h, lo, c) in enumerate(rows)
        ]
    )


FLAT = (100.0, 100.5, 99.5, 100.0)


def test_empty_bars_are_open():
    assert strict_score(bars([])).status == "open"


def test_fewer_than_fifteen_quiet_bars_are_open_not_scored():
    out = strict_score(bars([FLAT] * 5))
    assert out.status == "open" and out.net_return is None


def test_fifteen_quiet_bars_time_out_slightly_negative_after_costs():
    out = strict_score(bars([FLAT] * 15))
    assert out.status == "timeout" and out.days == 15
    assert -0.02 < out.net_return < 0.0  # flat price minus costs and slippage


def test_target_after_half_out_is_between_five_and_eight_percent():
    out = strict_score(bars([(100, 101, 99, 100)] * 2 + [(100, 109, 100, 108)]))
    assert out.status == "target" and out.half_out and not out.gap
    assert 0.05 < out.net_return < 0.08


def test_stop_is_about_minus_four_percent_after_costs():
    out = strict_score(bars([(100, 101, 99, 100), (100, 100, 95, 96)]))
    assert out.status == "stop" and not out.gap
    assert -0.05 < out.net_return < -0.04


def test_gap_through_the_stop_fills_at_the_open_and_loses_more():
    out = strict_score(bars([(100, 101, 99, 100), (90, 91, 89, 90)]))
    assert out.status == "stop" and out.gap
    assert out.net_return < -0.09


def test_a_bar_touching_both_target_and_stop_is_the_stop():
    out = strict_score(bars([(100, 109, 95, 100)]))
    assert out.status == "stop"


def test_half_sold_then_stopped_is_about_break_even():
    out = strict_score(bars([(100, 101, 99, 100), (100, 106, 99, 105), (105, 105, 90, 92)]))
    assert out.status == "stop" and out.half_out
    assert -0.01 < out.net_return < 0.01


def test_gap_up_through_the_target_fills_at_the_open_and_gains_more():
    out = strict_score(bars([(100, 101, 99, 100), (110, 112, 109, 111)]))
    assert out.status == "target" and out.gap
    assert out.net_return > 0.08


def test_after_day_keeps_only_later_bars():
    df = bars([FLAT] * 5)
    later = after_day(df, START + timedelta(days=1))
    assert list(later["day"]) == [START + timedelta(days=i) for i in (2, 3, 4)]


def test_locked_score_enters_at_the_decision_days_close():
    # decision day = START (close 100); the next bar's high is 108.5 -> +8% target
    rows = [(100, 100, 100, 100), (100, 108.5, 99.5, 108)]
    out = locked_score(bars(rows), START)
    assert out is not None and out.outcome == "target" and out.ret == 0.08


def test_locked_score_is_none_without_a_bar_on_or_before_the_decision_day():
    assert locked_score(bars([FLAT] * 3), START - timedelta(days=5)) is None


def test_strict_for_uses_the_bar_after_the_decision_day_as_entry():
    df = bars([FLAT] * 17)
    assert strict_for(df, START).status == "timeout"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -m pytest tests/test_brain_replay_scoring.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: swing_trade_ml.brain.replay_scoring`.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/swing_trade_ml/brain/replay_scoring.py
"""Strict, pure scoring of one idea against what the stock really did (replay-score).

The locked rule in `m09_learn.outcomes` enters at the decision day's close and
assumes exactly +8% / -4%. This stricter rule is closer to what a real order would
get: it enters at the next day's open, fills a gap at the open (not at the level),
pays slippage and charges (`services/costs.py`) and sells half at +5%. After the
half-out the stop is NOT moved up: that is the cautious reading of a plain stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from swing_trade_ml.brain.modules.m09_learn.outcomes import Outcome, score
from swing_trade_ml.services.costs import apply_slippage, compute_charges

HORIZON_BARS = 15
TARGET = 0.08
STOP = 0.04
HALF_OUT = 0.05
POSITION_INR = 40_000.0  # about the smallest position the risk rules allow


@dataclass(frozen=True, slots=True)
class StrictOutcome:
    status: str  # target | stop | timeout | open
    net_return: float | None  # fraction of the money put in, after costs; None while open
    days: int | None  # bars held, counting the entry day as 1
    half_out: bool  # half was sold at +5%
    gap: bool  # an exit filled at the open, past the level
    exit_day: date | None


def _sell(price: float, qty: float) -> float:
    """Cash received for selling `qty` shares at `price`, after slippage and charges."""
    gross = apply_slippage(price, "SELL") * qty
    brokerage, taxes = compute_charges(gross, "SELL")
    return gross - brokerage - taxes


def _done(status, cash_in, cash_out, days, half_done, gap, day) -> StrictOutcome:
    return StrictOutcome(status, cash_out / cash_in - 1.0, days, half_done, gap, day)


def strict_score(bars: pd.DataFrame) -> StrictOutcome:
    """`bars`: columns day, open, high, low, close; the first row is the entry day
    (the day after the decision), ascending."""
    if bars.empty:
        return StrictOutcome("open", None, None, False, False, None)
    fill = apply_slippage(float(bars.iloc[0]["open"]), "BUY")
    qty = POSITION_INR / fill
    brokerage, taxes = compute_charges(fill * qty, "BUY")
    cash_in = fill * qty + brokerage + taxes
    stop, half, target = fill * (1 - STOP), fill * (1 + HALF_OUT), fill * (1 + TARGET)

    held, cash_out, half_done, gap = qty, 0.0, False, False
    n = min(len(bars), HORIZON_BARS)
    for i in range(n):
        row = bars.iloc[i]
        o, h, lo, day = float(row["open"]), float(row["high"]), float(row["low"]), row["day"]
        if lo <= stop:  # checked first: a bar touching the stop and anything else is the stop
            gap = gap or o <= stop
            cash_out += _sell(o if o <= stop else stop, held)
            return _done("stop", cash_in, cash_out, i + 1, half_done, gap, day)
        if not half_done and h >= half:
            cash_out += _sell(o if o >= half else half, qty / 2)
            held, half_done = qty / 2, True
        if h >= target:
            gap = gap or o >= target
            cash_out += _sell(o if o >= target else target, held)
            return _done("target", cash_in, cash_out, i + 1, half_done, gap, day)
    if n < HORIZON_BARS:
        return StrictOutcome("open", None, None, half_done, gap, None)
    last = bars.iloc[HORIZON_BARS - 1]
    cash_out += _sell(float(last["close"]), held)
    return _done("timeout", cash_in, cash_out, HORIZON_BARS, half_done, gap, last["day"])


def after_day(df: pd.DataFrame, day: date) -> pd.DataFrame:
    """Bars strictly after the decision day."""
    return df[df["day"] > day].reset_index(drop=True)


def locked_score(df: pd.DataFrame, day: date) -> Outcome | None:
    """The existing M09 rule: entry at the decision day's close. None if there is no such bar."""
    before = df[df["day"] <= day]
    if before.empty:
        return None
    entry = float(before.iloc[-1]["close"])
    return score(entry, after_day(df, day)[["day", "high", "low", "close"]])


def strict_for(df: pd.DataFrame, day: date) -> StrictOutcome:
    return strict_score(after_day(df, day))
```

- [ ] **Step 4: Run to verify they pass**

Run: same command as Step 2. Expected: `13 passed`.

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/brain/replay_scoring.py tests/test_brain_replay_scoring.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/brain/replay_scoring.py tests/test_brain_replay_scoring.py
git add backend/src/swing_trade_ml/brain/replay_scoring.py backend/tests/test_brain_replay_scoring.py
git commit -m "Add a strict, pure scorer for replayed brain ideas (next-open entry, gaps, costs, half-out)."
```

---

### Task 2: Report maths and baselines (pure)

**Files:**
- Create: `backend/src/swing_trade_ml/brain/replay_report.py`
- Test: `backend/tests/test_brain_replay_report.py`

**Interfaces:**
- Consumes: `StrictOutcome` from Task 1; `Outcome` from `m09_learn.outcomes`.
- Produces:
  - `ScoredIdea(day: date, symbol: str, word: str, track_b: bool, blocked: bool, score: int | None, reasons: tuple[str, ...], locked: Outcome | None, strict: StrictOutcome | None)` (frozen dataclass; `strict is None` means no price data)
  - `track_stats(ideas: Sequence[ScoredIdea]) -> dict`
  - `random_baseline(pool: dict[date, list[str]], picks_per_day: dict[date, int], outcomes: dict[tuple[str, date], StrictOutcome | None], draws: int = 200, seed: int = 7) -> dict`
  - `all_eligible_stats(pool, outcomes) -> dict`
  - `plain_summary(report: dict) -> str`
  - `LIMITATIONS: tuple[str, ...]`
  - `BREAK_EVEN = 0.04 / (0.04 + 0.08)`

`track_stats` returns exactly these keys: `ideas`, `no_price_data`, `open`, `resolved`, `target`, `stop`, `timeout`, `hit_rate`, `avg_net_return`, `avg_locked_return`, `half_out`, `gaps`, `by_score` (dict bucket label to `{"resolved": int, "hit_rate": float | None}`), where `hit_rate` and the averages are `None` when `resolved` is 0.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_brain_replay_report.py
from __future__ import annotations

from datetime import date

from swing_trade_ml.brain.modules.m09_learn.outcomes import Outcome
from swing_trade_ml.brain.replay_report import (
    BREAK_EVEN,
    LIMITATIONS,
    ScoredIdea,
    all_eligible_stats,
    plain_summary,
    random_baseline,
    track_stats,
)
from swing_trade_ml.brain.replay_scoring import StrictOutcome

D = date(2026, 9, 1)


def strict(status, ret=None, half=False, gap=False):
    return StrictOutcome(status, ret, 5 if ret is not None else None, half, gap, D)


def idea(symbol, status, ret=None, score=70, track_b=True, locked=None, no_data=False):
    return ScoredIdea(
        day=D,
        symbol=symbol,
        word="TRADE" if track_b else "WATCH",
        track_b=track_b,
        blocked=not track_b,
        score=score,
        reasons=("because",),
        locked=locked,
        strict=None if no_data else strict(status, ret),
    )


def test_break_even_is_one_third_before_costs():
    assert round(BREAK_EVEN, 3) == 0.333


def test_stats_on_no_ideas_do_not_divide_by_zero():
    s = track_stats([])
    assert s["ideas"] == 0 and s["resolved"] == 0 and s["hit_rate"] is None and s["avg_net_return"] is None


def test_open_and_no_price_data_are_never_counted_as_wins_or_losses():
    s = track_stats([idea("A", "open"), idea("B", "open", no_data=True), idea("C", "target", 0.07)])
    assert (s["ideas"], s["open"], s["no_price_data"], s["resolved"]) == (3, 1, 1, 1)
    assert s["target"] == 1 and s["hit_rate"] == 1.0


def test_hit_rate_and_average_net_return():
    s = track_stats([idea("A", "target", 0.07), idea("B", "stop", -0.045), idea("C", "timeout", 0.01)])
    assert s["resolved"] == 3 and round(s["hit_rate"], 3) == 0.333
    assert round(s["avg_net_return"], 4) == round((0.07 - 0.045 + 0.01) / 3, 4)


def test_locked_return_averages_only_where_it_exists():
    lk = Outcome("target", 0.08, 3, 0.09, -0.01, D)
    s = track_stats([idea("A", "target", 0.07, locked=lk), idea("B", "stop", -0.04)])
    assert s["avg_locked_return"] == 0.08


def test_score_buckets_split_hit_rates():
    s = track_stats(
        [idea("A", "target", 0.07, score=85), idea("B", "stop", -0.04, score=85), idea("C", "stop", -0.04, score=62)]
    )
    assert s["by_score"]["80+"] == {"resolved": 2, "hit_rate": 0.5}
    assert s["by_score"]["60-69"] == {"resolved": 1, "hit_rate": 0.0}


def test_random_baseline_is_repeatable_and_ordered():
    pool = {D: ["A", "B", "C", "D"]}
    outcomes = {
        ("A", D): strict("target", 0.07),
        ("B", D): strict("stop", -0.045),
        ("C", D): strict("stop", -0.045),
        ("D", D): strict("open"),
    }
    one = random_baseline(pool, {D: 2}, outcomes, draws=50, seed=1)
    two = random_baseline(pool, {D: 2}, outcomes, draws=50, seed=1)
    assert one == two
    assert one["p5"] <= one["mean"] <= one["p95"]


def test_random_baseline_with_no_picks_is_empty_not_an_error():
    out = random_baseline({D: ["A"]}, {}, {}, draws=10, seed=1)
    assert out["mean"] is None


def test_all_eligible_counts_every_stock_that_day():
    pool = {D: ["A", "B"]}
    outcomes = {("A", D): strict("target", 0.07), ("B", D): strict("stop", -0.045)}
    s = all_eligible_stats(pool, outcomes)
    assert s["ideas"] == 2 and s["resolved"] == 2 and s["hit_rate"] == 0.5


def test_summary_says_plainly_when_nothing_is_resolved():
    report = {
        "window": {"from": "2026-09-01", "to": "2026-09-05", "days_replayed": 5, "failed_days": []},
        "track_a": track_stats([idea("A", "open")]),
        "track_b": track_stats([]),
        "baselines": {},
        "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "not enough finished ideas" in text.lower()
    assert "5" in text


def test_summary_lists_failed_days_and_limitations():
    report = {
        "window": {"from": "2026-09-01", "to": "2026-09-05", "days_replayed": 4, "failed_days": ["2026-09-03"]},
        "track_a": track_stats([idea("A", "target", 0.07)]),
        "track_b": track_stats([idea("A", "target", 0.07)]),
        "baselines": {"random": {"mean": 0.0, "p5": -0.01, "p95": 0.01, "draws": 50}, "all_eligible": track_stats([])},
        "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "2026-09-03" in text and "limits" in text.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest tests/test_brain_replay_report.py -q -p no:cacheprovider` (same prefix as Task 1).
Expected: FAIL, `ModuleNotFoundError: swing_trade_ml.brain.replay_report`.

- [ ] **Step 3: Write the implementation**

```python
# backend/src/swing_trade_ml/brain/replay_report.py
"""Pure maths and plain-English text for the replay-score report. No database."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from swing_trade_ml.brain.modules.m09_learn.outcomes import Outcome
from swing_trade_ml.brain.replay_scoring import StrictOutcome

BREAK_EVEN = 0.04 / (0.04 + 0.08)  # hit rate needed before costs, if every trade ends at a level

LIMITATIONS: tuple[str, ...] = (
    "Days before the first stored watchlist snapshot use today's watchlist, which favours stocks that survived.",
    "A model trained on later data has seen these days; check the model's training window against this one.",
    "Daily candles cannot show which of target or stop came first inside one day; the stop is assumed.",
    "Ideas with fewer than 15 trading days after them are still open and are not counted.",
    "This replay is a test on past data. It does not count toward the live 30-idea gate.",
)

_BUCKETS = (("80+", 80, 1000), ("70-79", 70, 80), ("60-69", 60, 70), ("below 60", 0, 60))


@dataclass(frozen=True, slots=True)
class ScoredIdea:
    day: date
    symbol: str
    word: str
    track_b: bool  # stayed TRADE after the risk check
    blocked: bool  # a TRADE the risk check lowered to WATCH
    score: int | None
    reasons: tuple[str, ...]
    locked: Outcome | None
    strict: StrictOutcome | None  # None = no price data at all


def _hit_rate(resolved: Sequence[ScoredIdea]) -> float | None:
    if not resolved:
        return None
    return sum(1 for i in resolved if i.strict.status == "target") / len(resolved)


def track_stats(ideas: Sequence[ScoredIdea]) -> dict:
    no_data = [i for i in ideas if i.strict is None]
    priced = [i for i in ideas if i.strict is not None]
    open_ = [i for i in priced if i.strict.status == "open"]
    resolved = [i for i in priced if i.strict.status != "open"]
    locked = [i.locked.ret for i in resolved if i.locked is not None]
    by_score = {}
    for label, lo, hi in _BUCKETS:
        bucket = [i for i in resolved if i.score is not None and lo <= i.score < hi]
        by_score[label] = {"resolved": len(bucket), "hit_rate": _hit_rate(bucket)}
    return {
        "ideas": len(ideas),
        "no_price_data": len(no_data),
        "open": len(open_),
        "resolved": len(resolved),
        "target": sum(1 for i in resolved if i.strict.status == "target"),
        "stop": sum(1 for i in resolved if i.strict.status == "stop"),
        "timeout": sum(1 for i in resolved if i.strict.status == "timeout"),
        "hit_rate": _hit_rate(resolved),
        "avg_net_return": sum(i.strict.net_return for i in resolved) / len(resolved) if resolved else None,
        "avg_locked_return": sum(locked) / len(locked) if locked else None,
        "half_out": sum(1 for i in resolved if i.strict.half_out),
        "gaps": sum(1 for i in resolved if i.strict.gap),
        "by_score": by_score,
    }


def _as_ideas(pool: dict[date, list[str]], outcomes: dict) -> list[ScoredIdea]:
    return [
        ScoredIdea(day, sym, "ANY", False, False, None, (), None, outcomes.get((sym, day)))
        for day, symbols in pool.items()
        for sym in symbols
    ]


def all_eligible_stats(pool: dict[date, list[str]], outcomes: dict) -> dict:
    """Every stock the brain looked at, each day, scored the same way."""
    return track_stats(_as_ideas(pool, outcomes))


def random_baseline(
    pool: dict[date, list[str]],
    picks_per_day: dict[date, int],
    outcomes: dict,
    draws: int = 200,
    seed: int = 7,
) -> dict:
    """Average net return of picking as many random stocks as the brain did, each day,
    repeated `draws` times with a fixed seed. Open and no-data picks are skipped."""
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(draws):
        rets: list[float] = []
        for day, k in picks_per_day.items():
            symbols = pool.get(day, [])
            if not symbols or k <= 0:
                continue
            for sym in rng.sample(symbols, min(k, len(symbols))):
                out = outcomes.get((sym, day))
                if out is not None and out.status != "open":
                    rets.append(out.net_return)
        if rets:
            means.append(sum(rets) / len(rets))
    if not means:
        return {"mean": None, "p5": None, "p95": None, "draws": draws}
    means.sort()
    return {
        "mean": sum(means) / len(means),
        "p5": means[int(0.05 * (len(means) - 1))],
        "p95": means[int(0.95 * (len(means) - 1))],
        "draws": draws,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def _rate(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _track_lines(name: str, s: dict) -> list[str]:
    if s["resolved"] == 0:
        return [f"{name}: {s['ideas']} ideas, {s['open']} still open. Not enough finished ideas to judge yet."]
    return [
        f"{name}: {s['ideas']} ideas, {s['resolved']} finished ({s['open']} still open"
        + (f", {s['no_price_data']} with no price data" if s["no_price_data"] else "")
        + ").",
        f"  Reached the target first: {s['target']}, hit the stop first: {s['stop']}, ran out of time: {s['timeout']}"
        f" ({_rate(s['hit_rate'])} reached the target; about {_rate(BREAK_EVEN)} is needed to break even before costs).",
        f"  Average result per idea after costs: {_pct(s['avg_net_return'])}"
        f" (the simpler rule, no costs: {_pct(s['avg_locked_return'])}).",
    ]


def plain_summary(report: dict) -> str:
    w = report["window"]
    lines = [
        f"Replay of {w['from']} to {w['to']}: {w['days_replayed']} trading day(s) replayed.",
    ]
    if w.get("failed_days"):
        lines.append("Days that failed and are missing from the numbers: " + ", ".join(w["failed_days"]))
    lines += _track_lines("Every idea (before the risk check)", report["track_a"])
    lines += _track_lines("Only ideas the risk check allowed", report["track_b"])
    base = report.get("baselines") or {}
    if base.get("random") and base["random"]["mean"] is not None:
        r = base["random"]
        lines.append(
            f"Random picks, same number each day ({r['draws']} tries): average {_pct(r['mean'])}"
            f" (the middle 90% of tries: {_pct(r['p5'])} to {_pct(r['p95'])})."
        )
    if base.get("all_eligible") and base["all_eligible"]["resolved"]:
        a = base["all_eligible"]
        lines.append(
            f"Every stock the brain looked at: {_rate(a['hit_rate'])} reached the target,"
            f" average {_pct(a['avg_net_return'])}."
        )
    if base.get("v1") and base["v1"]["resolved"]:
        v = base["v1"]
        lines.append(f"Version 1's buys on the same days: {_rate(v['hit_rate'])} reached the target, average {_pct(v['avg_net_return'])}.")
    lines.append("")
    lines.append("What this test cannot tell you (limits):")
    lines += [f"  - {text}" for text in report["limitations"]]
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2. Expected: `11 passed`.

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/brain/replay_report.py tests/test_brain_replay_report.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/brain/replay_report.py tests/test_brain_replay_report.py
git add backend/src/swing_trade_ml/brain/replay_report.py backend/tests/test_brain_replay_report.py
git commit -m "Add the replay-score report maths, baselines and plain-English summary."
```

---

### Task 3: Orchestrator (DB)

**Files:**
- Create: `backend/src/swing_trade_ml/brain/replay_score.py`
- Test: `backend/tests/test_brain_replay_score.py`

**Interfaces:**
- Consumes: `run_replay_week`, `ReplayDayResult` (`brain/replay_week.py`); `service.decisions_for(db, run_id) -> list[BrainDecision]`; `blocked_by_risk(d) -> bool` from `swing_trade_ml.strategies.brain`; Task 1 and Task 2 names.
- Produces:
  - `Idea` is not a new type: ideas become `ScoredIdea` directly.
  - `collect_ideas(db, run_id: str, day: date) -> tuple[list[dict], list[str]]` returns `(idea_rows, all_idea_symbols)`; each row has keys `symbol, word, track_b, blocked, score, reasons`.
  - `load_bars(db, symbols: Sequence[str], upto: date) -> dict[str, pd.DataFrame]` (columns `day, open, high, low, close`, ascending, IST days, bounded by `upto`).
  - `v1_buys(db, start: date, end: date) -> dict[date, list[str]]` (v1 `ml_swing` BUY signals per IST day, paper mode).
  - `run_replay_score(db, *, start: date, end: date, book: str = "paper", symbols: list[str] | None = None, upto: date | None = None, replay=run_replay_week, draws: int = 200, seed: int = 7) -> dict` returning the report dict used by `plain_summary` plus keys `ideas` (list of per-idea rows) and `generated_at`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_brain_replay_score.py
"""Replay-score orchestrator against the test database. The replay itself is stubbed:
the runs and decisions are written by hand so the test controls exactly what the
brain 'said', and the candles decide what happened next."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from swing_trade_ml.brain.replay_score import collect_ideas, load_bars, run_replay_score, v1_buys
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

IST = ZoneInfo("Asia/Kolkata")
DAY1, DAY2 = date(2026, 8, 3), date(2026, 8, 4)  # Mon, Tue
UPTO = date(2026, 9, 30)


def _inst(db, symbol, token):
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=True, is_active=True)
    db.add(inst)
    db.flush()
    return inst


def _bars(db, inst, start: date, closes_ohlc):
    d = start
    for o, h, lo, c in closes_ohlc:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        ts = datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC)
        db.add(Candle(instrument_id=inst.id, interval="day", ts=ts, open=o, high=h, low=lo, close=c, volume=1000))
        d += timedelta(days=1)


def _run(db, run_id, day):
    as_of = datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)
    db.add(BrainRun(id=run_id, kind="nightly", as_of=as_of, book="paper", live=False, status="done"))
    db.flush()


def _decision(db, run_id, symbol, word, *, downgraded_from=None, reason=None, confidence=0.7, stop=96.0, target=108.0):
    db.add(
        BrainDecision(
            run_id=run_id, symbol=symbol, kind="idea", word=word, reasons=[reason or "because"],
            entry_low=100.0, entry_high=100.0, target=target, stop=stop, confidence=confidence,
            downgraded_from=downgraded_from, downgrade_reason=reason,
        )
    )


RISK_NO = "Good idea, but the risk check said no: slots are full."


@pytest.fixture()
def world(db_session):
    win = _inst(db_session, "RSWIN", 995001)  # rises 9% on the day after DAY1
    lose = _inst(db_session, "RSLOSE", 995002)  # falls 5% on the day after DAY1
    quiet = _inst(db_session, "RSQUIET", 995003)
    gone = _inst(db_session, "RSGONE", 995004)  # no candles at all
    flat = (100.0, 100.5, 99.5, 100.0)
    _bars(db_session, win, DAY1, [flat, (100, 109, 100, 108), *[(108, 109, 107, 108)] * 20])
    _bars(db_session, lose, DAY1, [flat, (100, 100, 94, 95), *[(95, 96, 94, 95)] * 20])
    _bars(db_session, quiet, DAY1, [flat] * 22)
    _run(db_session, "rs-run-1", DAY1)
    _decision(db_session, "rs-run-1", "RSWIN", "TRADE")
    _decision(db_session, "rs-run-1", "RSLOSE", "WATCH", downgraded_from="TRADE", reason=RISK_NO)
    _decision(db_session, "rs-run-1", "RSQUIET", "WAIT", confidence=0.4)
    _decision(db_session, "rs-run-1", "RSGONE", "TRADE")
    db_session.commit()
    return SimpleNamespace(day=DAY1, run_id="rs-run-1")


def test_collect_ideas_splits_the_two_tracks(db_session, world):
    rows, symbols = collect_ideas(db_session, world.run_id, world.day)
    by = {r["symbol"]: r for r in rows}
    assert set(symbols) == {"RSWIN", "RSLOSE", "RSQUIET", "RSGONE"}
    assert set(by) == {"RSWIN", "RSLOSE", "RSGONE"}  # the WAIT is not an idea
    assert by["RSWIN"]["track_b"] and not by["RSWIN"]["blocked"]
    assert by["RSLOSE"]["blocked"] and not by["RSLOSE"]["track_b"]


def test_load_bars_is_in_ist_days_and_bounded(db_session, world):
    bars = load_bars(db_session, ["RSWIN", "RSGONE"], UPTO)
    assert "RSGONE" not in bars or bars["RSGONE"].empty
    first = bars["RSWIN"].iloc[0]
    assert first["day"] == DAY1  # not the 18:30 UTC date before it
    capped = load_bars(db_session, ["RSWIN"], DAY1)
    assert len(capped["RSWIN"]) == 1


def test_full_run_scores_each_idea_and_never_touches_live_outcomes(db_session, world):
    stub = lambda db, **kw: [SimpleNamespace(day=DAY1, run_id=world.run_id, banner="DEFENSIVE", counts={}, universe_size=4)]  # noqa: E731
    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=20)

    by = {i["symbol"]: i for i in report["ideas"]}
    assert by["RSWIN"]["strict_status"] == "target"
    assert by["RSLOSE"]["strict_status"] == "stop"
    assert by["RSGONE"]["strict_status"] == "no_price_data"
    assert report["track_a"]["ideas"] == 3 and report["track_b"]["ideas"] == 2
    assert report["track_a"]["no_price_data"] == 1
    assert report["baselines"]["all_eligible"]["ideas"] == 4
    assert report["window"]["days_replayed"] == 1 and report["window"]["failed_days"] == []

    # the live learning columns are untouched
    outcomes = db_session.execute(select(BrainDecision.outcome)).scalars().all()
    assert all(o is None for o in outcomes)


def test_a_failed_replay_day_is_listed_not_hidden(db_session, world):
    def stub(db, **kw):
        raise RuntimeError("boom")

    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=5)
    assert report["window"]["failed_days"] and report["track_a"]["ideas"] == 0


def test_a_window_with_no_ideas_reports_cleanly(db_session):
    stub = lambda db, **kw: []  # noqa: E731
    report = run_replay_score(db_session, start=DAY1, end=DAY1, upto=UPTO, replay=stub, draws=5)
    assert report["track_a"]["ideas"] == 0 and report["track_a"]["hit_rate"] is None


def test_v1_buys_reads_ml_swing_buy_signals_per_ist_day(db_session, world):
    strat = Strategy(name="rs-v1", strategy_type="ml_swing", params={}, is_active=True, mode="paper")
    db_session.add(strat)
    db_session.flush()
    inst = db_session.execute(select(Instrument).where(Instrument.tradingsymbol == "RSWIN")).scalar_one()
    when = datetime.combine(DAY2, time(10, 0), tzinfo=IST).astimezone(UTC)
    db_session.add(Signal(strategy_id=strat.id, instrument_id=inst.id, signal_type="BUY", mode="paper", price=100.0, generated_at=when))
    db_session.add(Signal(strategy_id=strat.id, instrument_id=inst.id, signal_type="HOLD", mode="paper", price=100.0, generated_at=when))
    db_session.commit()
    assert v1_buys(db_session, DAY1, DAY2) == {DAY2: ["RSWIN"]}
```

- [ ] **Step 2: Run to verify they fail**

Run: `... pytest tests/test_brain_replay_score.py -q -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: swing_trade_ml.brain.replay_score`. (Docker Postgres must be up.)

- [ ] **Step 3: Write the implementation**

```python
# backend/src/swing_trade_ml/brain/replay_score.py
"""Replay the brain over past days and score every idea against what happened next.

Read-only for live evidence: it never writes `brain_decisions.outcome*` and nothing it
produces counts toward the M18 30-idea gate. Replays are non-live runs; this module
only reads their decisions and the candles.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain import service
from swing_trade_ml.brain.replay_report import (
    LIMITATIONS,
    ScoredIdea,
    all_eligible_stats,
    random_baseline,
    track_stats,
)
from swing_trade_ml.brain.replay_scoring import locked_score, strict_for
from swing_trade_ml.brain.replay_week import run_replay_week
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.strategies.brain import blocked_by_risk

IST = ZoneInfo("Asia/Kolkata")
_BAR_COLUMNS = ["day", "open", "high", "low", "close"]


def collect_ideas(db: Session, run_id: str, day: date) -> tuple[list[dict], list[str]]:
    """(ideas, every symbol the brain judged that day). An idea is a TRADE that stayed
    TRADE (track B) or a TRADE the risk check lowered to WATCH (blocked). The owner's
    overrule, if any, wins over the brain's own word."""
    rows: list[dict] = []
    symbols: list[str] = []
    for d in service.decisions_for(db, run_id):
        if d.kind != "idea":
            continue
        symbols.append(d.symbol)
        final = d.overruled_word or d.word
        track_b = final == "TRADE"
        blocked = (not track_b) and blocked_by_risk(d) and d.stop is not None and d.target is not None
        if not (track_b or blocked):
            continue
        rows.append(
            {
                "symbol": d.symbol,
                "word": final,
                "track_b": track_b,
                "blocked": blocked,
                "score": round(d.confidence * 100) if d.confidence is not None else None,
                "reasons": tuple(d.reasons or ()),
            }
        )
    return rows, symbols


def load_bars(db: Session, symbols: Sequence[str], upto: date) -> dict[str, pd.DataFrame]:
    """Daily bars per symbol, ascending, with IST trading days, up to and including `upto`."""
    if not symbols:
        return {}
    ceiling = datetime.combine(upto + timedelta(days=1), time(0, 0), tzinfo=IST)
    rows = db.execute(
        select(Instrument.tradingsymbol, Candle.ts, Candle.open, Candle.high, Candle.low, Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol.in_(list(symbols)), Candle.interval == "day", Candle.ts < ceiling)
        .order_by(Instrument.tradingsymbol, Candle.ts.asc())
    ).all()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for symbol, ts, o, h, lo, c in rows:
        grouped[symbol].append(
            {"day": ts.astimezone(IST).date(), "open": float(o), "high": float(h), "low": float(lo), "close": float(c)}
        )
    return {s: pd.DataFrame(r, columns=_BAR_COLUMNS) for s, r in grouped.items()}


def v1_buys(db: Session, start: date, end: date) -> dict[date, list[str]]:
    """Version 1's `ml_swing` BUY signals per IST day (paper), for the same-days comparison."""
    lo = datetime.combine(start, time(0, 0), tzinfo=IST)
    hi = datetime.combine(end + timedelta(days=1), time(0, 0), tzinfo=IST)
    rows = db.execute(
        select(Signal.generated_at, Instrument.tradingsymbol)
        .join(Strategy, Strategy.id == Signal.strategy_id)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(
            Strategy.strategy_type == "ml_swing",
            Signal.signal_type == "BUY",
            Signal.mode == "paper",
            Signal.generated_at >= lo,
            Signal.generated_at < hi,
        )
        .order_by(Signal.generated_at)
    ).all()
    out: dict[date, list[str]] = defaultdict(list)
    for when, symbol in rows:
        day = when.astimezone(IST).date()
        if symbol not in out[day]:
            out[day].append(symbol)
    return dict(out)


def _idea_row(i: ScoredIdea) -> dict:
    s = i.strict
    return {
        "day": i.day.isoformat(),
        "symbol": i.symbol,
        "word": i.word,
        "track": "B" if i.track_b else "A only (blocked by the risk check)",
        "score": i.score,
        "why": list(i.reasons[:3]),
        "strict_status": "no_price_data" if s is None else s.status,
        "strict_net_return": None if s is None else s.net_return,
        "strict_days": None if s is None else s.days,
        "locked_status": None if i.locked is None else i.locked.outcome,
        "locked_return": None if i.locked is None else i.locked.ret,
    }


def run_replay_score(
    db: Session,
    *,
    start: date,
    end: date,
    book: str = "paper",
    symbols: list[str] | None = None,
    upto: date | None = None,
    replay: Callable = run_replay_week,
    draws: int = 200,
    seed: int = 7,
) -> dict:
    failed: list[str] = []
    try:
        results = list(replay(db, start=start, end=end, book=book, symbols=symbols))
    except Exception as exc:  # noqa: BLE001 - a failed replay is reported, never hidden
        results = []
        failed.append(f"{start.isoformat()}..{end.isoformat()} ({type(exc).__name__}: {exc})")

    upto = upto or last_closed_trading_day(datetime.now(UTC))
    per_day: dict[date, list[dict]] = {}
    pool: dict[date, list[str]] = {}
    for r in results:
        rows, judged = collect_ideas(db, r.run_id, r.day)
        per_day[r.day] = rows
        pool[r.day] = judged

    wanted = sorted({s for syms in pool.values() for s in syms})
    bars = load_bars(db, wanted, upto)

    outcomes: dict[tuple[str, date], object] = {}
    for day, judged in pool.items():
        for sym in judged:
            df = bars.get(sym)
            outcomes[(sym, day)] = None if df is None or df.empty else strict_for(df, day)

    scored: list[ScoredIdea] = []
    for day, rows in per_day.items():
        for row in rows:
            df = bars.get(row["symbol"])
            locked = None if df is None or df.empty else locked_score(df, day)
            scored.append(
                ScoredIdea(
                    day=day,
                    symbol=row["symbol"],
                    word=row["word"],
                    track_b=row["track_b"],
                    blocked=row["blocked"],
                    score=row["score"],
                    reasons=row["reasons"],
                    locked=locked,
                    strict=outcomes[(row["symbol"], day)],
                )
            )

    picks_per_day = {d: len(rows) for d, rows in per_day.items() if rows}
    v1 = v1_buys(db, start, end)
    v1_bars = load_bars(db, sorted({s for syms in v1.values() for s in syms}), upto)
    v1_outcomes = {
        (s, d): (None if v1_bars.get(s) is None or v1_bars[s].empty else strict_for(v1_bars[s], d))
        for d, syms in v1.items()
        for s in syms
    }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "days_replayed": len(results),
            "failed_days": failed,
            "scored_up_to": upto.isoformat(),
        },
        "track_a": track_stats(scored),
        "track_b": track_stats([i for i in scored if i.track_b]),
        "baselines": {
            "all_eligible": all_eligible_stats(pool, outcomes),
            "random": random_baseline(pool, picks_per_day, outcomes, draws=draws, seed=seed),
            "v1": all_eligible_stats(v1, v1_outcomes),
        },
        "ideas": [_idea_row(i) for i in scored],
        "limitations": list(LIMITATIONS),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2. Expected: `6 passed`. If `v1_buys` fails because `Signal.generated_at` is set by a default, pass the value as in the test (the column accepts it).

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format src/swing_trade_ml/brain/replay_score.py tests/test_brain_replay_score.py && .venv/Scripts/python.exe -m ruff check src/swing_trade_ml/brain/replay_score.py tests/test_brain_replay_score.py
git add backend/src/swing_trade_ml/brain/replay_score.py backend/tests/test_brain_replay_score.py
git commit -m "Add the replay-score orchestrator: replay, collect ideas, score, compare with baselines."
```

---

### Task 4: CLI command and docs

**Files:**
- Modify: `backend/src/swing_trade_ml/cli.py` (the `brain` subparsers near line 806 and `cmd_brain` near line 584)
- Modify: `docs/brain/TESTING.md`
- Test: `backend/tests/test_brain_replay_score_cli.py`

**Interfaces:**
- Consumes: `run_replay_score`, `plain_summary`, `resolve_replay_range`, `REPO_ROOT`.
- Produces: `swingtrade brain replay-score [--from D --to D | --days N] [--symbols A,B] [--book paper|live] [--draws N] [--out PATH]`; writes JSON (default `docs/brain/evidence/replay_score_<from>_<to>.json`) and prints the plain summary. Exit code 0.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_brain_replay_score_cli.py
from __future__ import annotations

import json
from datetime import date

from swing_trade_ml import cli


def test_parser_knows_replay_score():
    parser = cli.build_parser()
    args = parser.parse_args(["brain", "replay-score", "--from", "2026-09-01", "--to", "2026-09-05", "--draws", "10"])
    assert args.brain_command == "replay-score" and args.draws == 10


def test_replay_score_writes_json_and_prints_summary(tmp_path, monkeypatch, capsys, db_session):
    report = {
        "generated_at": "x",
        "window": {"from": "2026-09-01", "to": "2026-09-05", "days_replayed": 0, "failed_days": [], "scored_up_to": "2026-09-05"},
        "track_a": {"ideas": 0, "no_price_data": 0, "open": 0, "resolved": 0, "target": 0, "stop": 0, "timeout": 0,
                    "hit_rate": None, "avg_net_return": None, "avg_locked_return": None, "half_out": 0, "gaps": 0, "by_score": {}},
        "track_b": {"ideas": 0, "no_price_data": 0, "open": 0, "resolved": 0, "target": 0, "stop": 0, "timeout": 0,
                    "hit_rate": None, "avg_net_return": None, "avg_locked_return": None, "half_out": 0, "gaps": 0, "by_score": {}},
        "baselines": {},
        "ideas": [],
        "limitations": ["a limit"],
    }
    monkeypatch.setattr("swing_trade_ml.brain.replay_score.run_replay_score", lambda *a, **k: report)
    out = tmp_path / "r.json"
    code = cli.main(["brain", "replay-score", "--from", "2026-09-01", "--to", "2026-09-05", "--out", str(out)])
    assert code == 0
    assert json.loads(out.read_text())["window"]["from"] == "2026-09-01"
    assert "Replay of 2026-09-01 to 2026-09-05" in capsys.readouterr().out
```

(Before writing, check `cli.build_parser` and `cli.main` names with `grep -n "def build_parser\|def main" backend/src/swing_trade_ml/cli.py`; if they differ, use the real names. The test must run `main` against the test DB session the way `tests/test_brain_cli_and_jobs.py` does, so open that file and copy its pattern for invoking a brain subcommand.)

- [ ] **Step 2: Run to verify it fails**

Run: `... pytest tests/test_brain_replay_score_cli.py -q -p no:cacheprovider`
Expected: FAIL (`replay-score` is not a known command).

- [ ] **Step 3: Implement**

Add the subparser after `validate-week` (about line 840):

```python
    b = brain_sub.add_parser(
        "replay-score",
        help="Replay past days, score every idea against what happened, compare with baselines (read-only)",
    )
    b.add_argument("--from", dest="from_date", default=None, help="YYYY-MM-DD (inclusive)")
    b.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD (inclusive)")
    b.add_argument("--days", type=int, default=None, help="Trading days ending at the last closed day")
    b.add_argument("--symbols", default=None, help="Comma-separated (default: full universe)")
    b.add_argument("--book", default="paper", choices=["paper", "live"])
    b.add_argument("--draws", type=int, default=200, help="Random-baseline repeats")
    b.add_argument("--out", default=None, help="Report path (default: docs/brain/evidence/replay_score_*.json)")
```

Add the handler in `cmd_brain` next to the `replay-week` branch:

```python
        if args.brain_command == "replay-score":
            import json
            from pathlib import Path

            from swing_trade_ml.brain import queue as brain_queue
            from swing_trade_ml.brain import replay_score
            from swing_trade_ml.brain.replay_report import plain_summary
            from swing_trade_ml.brain.replay_week import resolve_replay_range
            from swing_trade_ml.core.config import REPO_ROOT

            from_day = date.fromisoformat(args.from_date) if args.from_date else None
            to_day = date.fromisoformat(args.to_date) if args.to_date else None
            try:
                start, end = resolve_replay_range(from_day=from_day, to_day=to_day, days=args.days)
            except ValueError as exc:
                print(f"❌ {exc}", file=sys.stderr)
                return 1
            symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
            try:
                report = replay_score.run_replay_score(
                    db, start=start, end=end, book=args.book, symbols=symbols, draws=args.draws
                )
            except brain_queue.RunBusyError as exc:
                print(f"⏳ {exc} Try again when it has finished.")
                return 1
            path = (
                Path(args.out)
                if args.out
                else REPO_ROOT / "docs" / "brain" / "evidence" / f"replay_score_{start.isoformat()}_{end.isoformat()}.json"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
            print(plain_summary(report))
            print(f"Report written to {path}")
            return 0
```

Add to the module docstring command list at the top of `cli.py`: `replay-score [--days 20]`.

Append to `docs/brain/TESTING.md`:

```markdown
## Replay and score (does the brain pick well?)

`swingtrade brain replay-score --days 20` replays the last 20 trading days, scores every
idea against what the stock really did, and compares with random picks, every stock the
brain looked at, and version 1's buys. Read-only: it never writes the live outcome columns
and never counts toward the 30-idea gate. Ideas younger than 15 trading days are "still
open" and are not counted. Read the "limits" lines at the bottom of the summary every time.
Run it against a database that has the candles for the window (a local copy, not prod).
```

- [ ] **Step 4: Run to verify it passes, then the whole new set and the full suite**

Run: `... pytest tests/test_brain_replay_scoring.py tests/test_brain_replay_report.py tests/test_brain_replay_score.py tests/test_brain_replay_score_cli.py -q -p no:cacheprovider`
Expected: all pass. Then the full backend suite: only `test_brain_is_off_by_default` may fail (local `.env`), same as before.

- [ ] **Step 5: Lint, format touched files only, commit**

```bash
cd backend && .venv/Scripts/python.exe -m ruff format tests/test_brain_replay_score_cli.py && .venv/Scripts/python.exe -m ruff check tests/test_brain_replay_score_cli.py src/swing_trade_ml/cli.py
git add backend/src/swing_trade_ml/cli.py backend/tests/test_brain_replay_score_cli.py docs/brain/TESTING.md
git commit -m "Add brain replay-score: replay past days, score every idea, compare with baselines."
```

(Do not `ruff format` all of `cli.py`: it is an existing file. Check the diff touches only the added lines.)

---

### Task 5: First real run and reading it

**Files:**
- Create (output, not code): `docs/brain/evidence/replay_score_<from>_<to>.json` and a short `docs/brain/evidence/replay_score_<from>_<to>.md` with the summary pasted and the owner's reading.

- [ ] **Step 1: Find the honest window.** Against the database you will run on, find the earliest date that has both candles and `watchlist_snapshots` rows, and the number of nightly-eligible trading days since:

```bash
cd backend && env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE .venv/Scripts/python.exe -c "
from swing_trade_ml.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(db.execute(text('select min(ts), max(ts), count(distinct instrument_id) from candles where interval=\'day\'')).one())
print(db.execute(text('select min(snapshot_date), max(snapshot_date) from watchlist_snapshots')).one())
"
```

If the second query errors, open `backend/src/swing_trade_ml/db/models/` for the real watchlist-snapshot column name. Expected: candle range ending near the last close and a snapshot range. Pick a window of about 20 trading days that ends at least 15 trading days before the last candle, so most ideas have finished.

- [ ] **Step 2: Run it** on that window: `swingtrade brain replay-score --from <D1> --to <D2>` (local database only). Expected: a plain-English summary and a JSON file.

- [ ] **Step 3: Read it with the owner.** Check: do Track A and Track B counts look plausible? Is "no price data" small? Does the random baseline sit near the all-eligible number (a sanity check on the scorer)? Write the reading into the `.md` file.

- [ ] **Step 4: Commit the evidence** with a message that states the window and the result in one line.

---

## Self-Review

1. **Spec coverage:** replay (Task 3), both tracks (collect_ideas, track_a/track_b), locked and strict scoring side by side (Tasks 1 and 3), baselines: all eligible, random, v1 (Tasks 2 and 3), report with per-idea rows, totals, open ideas separate, break-even, score buckets, limitations (Tasks 2 and 3), CLI and docs (Task 4), first real run (Task 5). Sector-matched random is explicitly deferred in the spec.
2. **Placeholders:** none; Task 4 Step 1 names the two things to look up (real parser function names and the existing CLI test pattern) with the exact commands.
3. **Type consistency:** `StrictOutcome`, `ScoredIdea`, `strict_for`, `locked_score`, `track_stats`, `all_eligible_stats`, `random_baseline`, `run_replay_score` have the same names and fields in every task; the report keys `track_a`, `track_b`, `baselines.{all_eligible,random,v1}`, `ideas`, `limitations`, `window` are the same in Tasks 2, 3 and 4.
4. **Review Focus:** no ideas (Task 2 `test_stats_on_no_ideas...`, Task 3 `test_a_window_with_no_ideas...`); open ideas not counted (Task 2); no price data (Task 3 RSGONE); newest ideas open (Task 1 and Task 2); consecutive-day duplicates (not de-duplicated by design, `collect_ideas` has no dedup); failed replay days (Task 3 `test_a_failed_replay_day...`).
