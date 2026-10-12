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
    "Days before the first stored watchlist snapshot use today's watchlist, "
    "which favours stocks that survived.",
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


def apply_market_gate(
    ideas: Sequence[ScoredIdea],
    banners: dict[date, str],
    defensive_max_new: int = 2,
    normal_max_new: int = 5,
) -> list[ScoredIdea]:
    """The ideas the real brain would let through each day, given that day's market mode.

    NO_NEW_TRADES lets none through, DEFENSIVE only the strongest `defensive_max_new`
    (the same cap as the risk check, M07), NORMAL the strongest `normal_max_new` (the
    owner's "top 5 a day"). A day with no known mode is treated as DEFENSIVE, as the brain does.
    """
    by_day: dict[date, list[ScoredIdea]] = {}
    for i in ideas:
        by_day.setdefault(i.day, []).append(i)
    kept: list[ScoredIdea] = []
    for day, day_ideas in by_day.items():
        mode = banners.get(day, "DEFENSIVE")
        cap = 0 if mode == "NO_NEW_TRADES" else defensive_max_new if mode == "DEFENSIVE" else normal_max_new
        ranked = sorted(day_ideas, key=lambda i: (-(i.score if i.score is not None else -1), i.symbol))
        kept.extend(ranked[:cap])
    return kept


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
        return [
            f"{name}: {s['ideas']} ideas, {s['open']} still open. Not enough finished ideas to judge yet."
        ]
    return [
        f"{name}: {s['ideas']} ideas, {s['resolved']} finished ({s['open']} still open"
        + (f", {s['no_price_data']} with no price data" if s["no_price_data"] else "")
        + ").",
        f"  Reached the target first: {s['target']}, hit the stop first: {s['stop']},"
        f" ran out of time: {s['timeout']} ({_rate(s['hit_rate'])} reached the target;"
        f" about {_rate(BREAK_EVEN)} is needed to break even before costs).",
        f"  Average result per idea after costs: {_pct(s['avg_net_return'])}"
        f" (the simpler rule, no costs: {_pct(s['avg_locked_return'])}).",
    ]


def plain_summary(report: dict) -> str:
    w = report["window"]
    lines = [
        f"Replay of {w['from']} to {w['to']}: {w['days_replayed']} trading day(s) replayed.",
    ]
    m = report.get("model")
    if m:
        if m["in_sample"]:
            lines.insert(
                0,
                "IN-SAMPLE: the model had already seen some of these days, so the numbers are flattering"
                " and not evidence.",
            )
        gap = m["days_without_score"]
        lines.append(
            f"Scored by {m['name']} {m['version']}, trained on data up to {m['cutoff'] or 'an unknown date'}."
            + (f" {gap} day{'s' if gap != 1 else ''} had no score." if gap else "")
        )
    if w.get("failed_days"):
        lines.append("Days that failed and are missing from the numbers: " + ", ".join(w["failed_days"]))
    lines += _track_lines("Every idea (before the risk check)", report["track_a"])
    lines += _track_lines("Only ideas the risk check allowed", report["track_b"])
    if report.get("track_gated"):
        lines += _track_lines(
            "Ideas after the market-mode limit (what the brain would really have bought)",
            report["track_gated"],
        )
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
        lines.append(
            f"Version 1's buys on the same days: {_rate(v['hit_rate'])} reached the target,"
            f" average {_pct(v['avg_net_return'])}."
        )
    lines.append("")
    lines.append("What this test cannot tell you (limits):")
    lines += [f"  - {text}" for text in report["limitations"]]
    return "\n".join(lines)
