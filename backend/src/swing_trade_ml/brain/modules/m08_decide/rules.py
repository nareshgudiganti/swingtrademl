"""The decision rules. Each one looks at a draft decision and its facts and may
propose a MORE CAREFUL word with a plain reason — or nothing.

To add a rule: write a `check(decision, facts, policy)` returning
`(word, reason)` or `None`, and append a `Rule` to the right list. To remove
one without deleting it: put its id in `DecidePolicy.disabled`. The engine
applies proposals with `contracts.downgrade`, so a rule can never make a
decision bolder, whatever it returns. Order matters only for which reason is
shown first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.services.limits import format_inr

Proposal = tuple[Any, str] | None
CARE_MODES = {MarketMode.DEFENSIVE, MarketMode.NO_NEW_TRADES}
# "breakdown" is deliberately absent: on 5 years of watch-list stocks a
# breakdown reached +8% before -4% more often than an average day (20.4% vs
# 17.6%), so avoiding it has no evidence behind it (see M12 notes).
AVOID_SITUATIONS = {"results soon", "event blackout"}


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    name: str  # plain words, shown wherever rules are listed
    applies_to: str  # "idea" | "holding"
    check: Callable[[c.Decision, Any, Any], Proposal]


# --- new ideas -------------------------------------------------------------------


def _exchange_watch_list(d, f, p) -> Proposal:
    if f.stock is not None and f.stock.restrictions:
        names = ", ".join(f.stock.restrictions)
        return IdeaWord.AVOID, f"On the exchange's watch list ({names}), so the brain stays away."
    return None


def _event_window(d, f, p) -> Proposal:
    for sit in f.situations:
        if sit.label in AVOID_SITUATIONS:
            what = sit.evidence[0] if sit.evidence else sit.label.capitalize()
            if "avoids" in what:  # the situation already states the rule in full
                return IdeaWord.AVOID, what if what.endswith(".") else f"{what}."
            return IdeaWord.AVOID, f"{what} — the brain avoids new trades around this."
    return None


def _weak_signals(d, f, p) -> Proposal:
    o = f.opinion
    if o is not None and o.probability is None and o.confidence < p.uncertain_below:
        return IdeaWord.WAIT, f"The signals are weak or disagree (confidence {o.confidence:.2f})."
    return None


def _risk_check(d, f, p) -> Proposal:
    v = f.verdict
    if v is None:
        return IdeaWord.WATCH, "The risk check has not approved this trade."
    if not v.allowed:
        return IdeaWord.WATCH, f"Good idea, but the risk check said no: {v.reason}"
    return None


def _negative_expected_result(d, f, p) -> Proposal:
    r = f.recall
    if r is None or r.hit_rate is None or r.n_similar < p.min_similar_cases or f.snapshot is None:
        return None
    from swing_trade_ml.brain.modules.m08_decide.engine import recall_r

    ev = recall_r(r, f, p)
    if ev <= 0:
        return (
            IdeaWord.WAIT,
            f"Similar cases lost money on average (expected {ev:+.2f} R per trade after costs).",
        )
    return None


def _sector_gate(d, f, p) -> Proposal:
    from swing_trade_ml.core.config import settings

    top = settings.BRAIN_SECTOR_GATE_TOP_N
    if top <= 0 or f.sector_rank is None:
        return None
    if f.sector_rank > top:
        return (
            IdeaWord.WAIT,
            f"Its sector ranks {f.sector_rank} of 15 — outside the top {top} for new ideas.",
        )
    return None


def _playbook_gate(d, f, p) -> Proposal:
    from swing_trade_ml.core.config import settings

    if not settings.BRAIN_PLAYBOOK_GATE or f.playbook_match:
        return None
    return IdeaWord.WAIT, "No classic setup (pullback or breakout on volume) today."


def _defensive_needs_uptrend(d, f, p) -> Proposal:
    if f.market_mode in CARE_MODES and f.stock is not None and f.stock.trend == "down":
        return (
            IdeaWord.WATCH,
            "The market is careful and this stock is falling, so the brain waits for it to turn up.",
        )
    return None


IDEA_RULES: list[Rule] = [
    Rule(
        "exchange_watch_list",
        "Stay away from stocks on the exchange's watch list",
        "idea",
        _exchange_watch_list,
    ),
    Rule("event_window", "Stay away around results and similar events", "idea", _event_window),
    Rule("weak_signals", "Wait when the signals are weak or disagree", "idea", _weak_signals),
    Rule("risk_check", "Only trade what the risk check approved", "idea", _risk_check),
    Rule(
        "negative_expected_result",
        "Skip ideas whose similar cases lost money",
        "idea",
        _negative_expected_result,
    ),
    Rule(
        "defensive_needs_uptrend",
        "In a careful market, only stocks in an up-trend",
        "idea",
        _defensive_needs_uptrend,
    ),
    Rule("sector_gate", "Only ideas from the strongest sectors", "idea", _sector_gate),
    Rule("playbook_gate", "Only ideas with a named setup", "idea", _playbook_gate),
]


# --- holdings ----------------------------------------------------------------------


def _stop_hit(d, f, p) -> Proposal:
    h, snap = f.holding, f.snapshot
    if snap is not None and h.stop is not None and snap.close <= h.stop:
        return HoldingWord.EXIT, (
            f"Stop hit: the price {format_inr(snap.close)} is at or below the stop {format_inr(h.stop)}; "
            "the exit rules sell it."
        )
    return None


def _first_target(d, f, p) -> Proposal:
    h, snap = f.holding, f.snapshot
    if snap is None or h.scaled_out or h.avg_price <= 0:
        return None
    gain = snap.close / h.avg_price - 1
    if gain >= p.first_target_pct:
        evidence = (
            f" {f.track.first_target_note}" if f.track is not None and f.track.first_target_note else ""
        )
        return HoldingWord.REDUCE, (
            f"Up {gain:+.1%}: the first target (+{p.first_target_pct:.0%}) is reached — book half and "
            f"trail the rest (the exit rules do this).{evidence}"
        )
    return None


def _what_changed(f) -> str:
    changes = []
    if f.market_mode in CARE_MODES:
        changes.append(f"the market is careful ({f.market_mode.value.replace('_', ' ')})")
    if f.stock is not None and f.stock.trend == "down":
        changes.append("its own trend has turned down")
    if any(n.startswith("Sector:") and "lagging" in n for n in f.notes):
        changes.append("its sector is lagging NIFTY")
    if not changes:
        return "What has changed: nothing obvious in the market or its sector — watch it closely."
    return "What has changed: " + "; ".join(changes) + "."


def _off_track(d, f, p) -> Proposal:
    t = f.track
    if t is not None and t.status in ("drift", "breakdown"):
        return HoldingWord.MONITOR, f"{t.reason} {_what_changed(f)}"
    return None


def _careful_market_falling(d, f, p) -> Proposal:
    if f.market_mode in CARE_MODES and f.stock is not None and f.stock.trend == "down":
        return HoldingWord.MONITOR, "The market is careful and this stock is falling — watch it closely."
    return None


def _lagging_nifty(d, f, p) -> Proposal:
    rel = f.stock.rel_strength_vs_nifty if f.stock is not None else None
    if rel is not None and rel <= p.lagging_vs_nifty:
        return HoldingWord.MONITOR, f"Trailing NIFTY by {abs(rel):.0%} over 60 days."
    return None


HOLDING_RULES: list[Rule] = [
    Rule("stop_hit", "A stop that has been hit is an exit", "holding", _stop_hit),
    Rule("first_target", "Book half at the first target", "holding", _first_target),
    Rule("off_track", "Watch trades falling behind similar past trades", "holding", _off_track),
    Rule(
        "careful_market_falling",
        "Watch falling holdings closely in a careful market",
        "holding",
        _careful_market_falling,
    ),
    Rule("lagging_nifty", "Watch holdings that trail NIFTY badly", "holding", _lagging_nifty),
]
