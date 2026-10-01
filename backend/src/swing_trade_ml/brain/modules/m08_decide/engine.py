"""The decision engine: draft, then rules, then notes.

Each stock starts as a draft — liked and priced → TRADE with an entry zone,
target, stop and the risk gate's size; otherwise WAIT with the reason — and
then passes through the rule list (rules.py). Rules only propose more careful
words; `contracts.downgrade` applies them, so the order of rules decides
which reason is shown first, never whether a decision can grow bolder.

Pure: the module (module.py) gathers the facts from the context.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.brain.modules.m08_decide.money import cost_pct, expected_r
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m08_decide.rules import HOLDING_RULES, IDEA_RULES, Rule
from swing_trade_ml.services.limits import format_inr


@dataclass(frozen=True, slots=True)
class IdeaFacts:
    symbol: str
    snapshot: c.Snapshot | None
    opinion: c.Opinion | None
    verdict: c.RiskVerdict | None
    quality: c.DataQuality | None
    stock: c.StockState | None
    situations: tuple[c.Situation, ...]
    recall: c.Recall | None
    market_mode: MarketMode


@dataclass(frozen=True, slots=True)
class HoldingFacts:
    holding: c.Holding
    snapshot: c.Snapshot | None
    stock: c.StockState | None
    market_mode: MarketMode


# --- ideas -----------------------------------------------------------------------


def _liked(o: c.Opinion) -> bool:
    if o.probability is not None and o.threshold is not None:
        return o.probability >= o.threshold
    return o.stance > 0


def _evidence(f: IdeaFacts, qty: int, policy: DecidePolicy) -> str:
    r = f.recall
    if r is not None and r.hit_rate is not None and r.n_similar >= policy.min_similar_cases and f.snapshot:
        ev = expected_r(r.hit_rate, cost_pct(f.snapshot.close, max(1, qty)), policy)
        band = (
            f" · the middle half ended between {r.p25:+.1%} and {r.p75:+.1%}"
            if r.p25 is not None and r.p75 is not None
            else ""
        )
        return (
            f"Similar cases: {r.n_similar} · reached +{policy.target_pct:.0%} before "
            f"-{policy.stop_pct:.0%} in {r.hit_rate:.0%}{band}. Expected result after costs: "
            f"{ev:+.2f} R per trade (1 R = the {policy.stop_pct:.0%} risked)."
        )
    o = f.opinion
    if o is not None and o.probability is not None:
        return (
            "No similar-case record yet, so the chance of reaching the target first is not known. "
            f"The model scores this stock {o.probability:.0%} against a buy level of {o.threshold or 0:.0%}; "
            "that score ranks stocks, it is not a probability."
        )
    return "No similar-case record yet."


def _draft_idea(f: IdeaFacts, policy: DecidePolicy) -> c.Decision:
    def wait(reason: str, confidence: float | None = None) -> c.Decision:
        return c.Decision(
            symbol=f.symbol,
            kind="idea",
            word=IdeaWord.WAIT,
            reasons=(reason,),
            confidence=confidence,
            evidence_text=_evidence(f, 0, policy),
        )

    if f.snapshot is None or f.snapshot.close <= 0:
        return wait("No price data for this stock yet.")
    o = f.opinion
    if o is None:
        return wait("No opinion about this stock today (no model score or reasoning module answer).")
    if not _liked(o):
        if o.probability is not None:
            return wait(
                f"Model score {o.probability:.0%} is below the buy level {o.threshold or 0:.0%}.",
                o.probability,
            )
        return wait("The signals do not favour buying this stock today.", o.confidence)

    close = f.snapshot.close
    half_zone = min((f.snapshot.atr_14 or 0.0) * policy.entry_atr_fraction, close * policy.entry_cap_pct)
    qty = f.verdict.max_qty if f.verdict is not None and f.verdict.allowed else 0
    target = round(close * (1 + policy.target_pct), 2)
    stop = round(close * (1 - policy.stop_pct), 2)
    plan = (
        f"Plan: buy around {format_inr(close - half_zone)} to {format_inr(close + half_zone)}, target "
        f"{format_inr(target)} (+{policy.target_pct:.0%}), stop {format_inr(stop)} (-{policy.stop_pct:.0%}), "
        f"up to {policy.horizon_days} trading days."
    )
    return c.Decision(
        symbol=f.symbol,
        kind="idea",
        word=IdeaWord.TRADE,
        reasons=(*o.reasons, plan),
        entry_low=round(close - half_zone, 2),
        entry_high=round(close + half_zone, 2),
        target=target,
        stop=stop,
        qty=qty,
        horizon_days=policy.horizon_days,
        confidence=o.probability if o.probability is not None else o.confidence,
        evidence_text=_evidence(f, qty, policy),
    )


def _apply(d: c.Decision, facts, policy: DecidePolicy, rules: list[Rule], kind: str) -> c.Decision:
    for rule in rules:
        if rule.applies_to != kind or rule.id in policy.disabled:
            continue
        proposal = rule.check(d, facts, policy)
        if proposal is not None:
            word, reason = proposal
            d = c.downgrade(d, word, reason)  # never bolder, whatever the rule asked
    return d


def decide_idea(f: IdeaFacts, policy: DecidePolicy, rules: list[Rule] = IDEA_RULES) -> c.Decision:
    return _apply(_draft_idea(f, policy), f, policy, rules, "idea")


# --- holdings ----------------------------------------------------------------------


def decide_holding(f: HoldingFacts, policy: DecidePolicy, rules: list[Rule] = HOLDING_RULES) -> c.Decision:
    h = f.holding
    if f.snapshot is None:
        draft = c.Decision(
            symbol=h.symbol,
            kind="holding",
            word=HoldingWord.MONITOR,
            reasons=("No price today to review this holding.",),
        )
    else:
        gain = f.snapshot.close / h.avg_price - 1 if h.avg_price > 0 else 0.0
        draft = c.Decision(
            symbol=h.symbol,
            kind="holding",
            word=HoldingWord.HOLD,
            reasons=(f"On track: {format_inr(f.snapshot.close)}, {gain:+.1%} since buying.",),
            stop=h.stop,
            target=h.target,
            qty=h.qty,
        )
    return _apply(draft, f, policy, rules, "holding")


# --- opportunity cost ---------------------------------------------------------------


def opportunity_notes(
    ideas: dict[str, c.Decision],
    idea_facts: dict[str, IdeaFacts],
    holdings: dict[str, c.Decision],
    holding_facts: dict[str, HoldingFacts],
) -> tuple[dict[str, c.Decision], dict[str, c.Decision]]:
    """When every slot is full and a liked idea waits for one, point at the
    weakest holding the brain is already worried about. Words only: nothing
    changes a decision's word and nothing is ever sold automatically."""
    waiting = [
        f
        for s, f in idea_facts.items()
        if f.verdict is not None
        and f.verdict.rule == "POSITION_LIMIT"
        and f.opinion is not None
        and _liked(f.opinion)
        and ideas.get(s) is not None
        and ideas[s].word is IdeaWord.WATCH
    ]
    worried = [s for s, d in holdings.items() if d.word is HoldingWord.MONITOR]
    if not waiting or not worried:
        return ideas, holdings

    def strength(f: IdeaFacts) -> float:
        return f.opinion.probability if f.opinion.probability is not None else (f.opinion.stance + 1) / 2

    best = max(waiting, key=lambda f: (strength(f), f.symbol))

    def rel(symbol: str) -> float:
        stock = holding_facts[symbol].stock if symbol in holding_facts else None
        return stock.rel_strength_vs_nifty if stock and stock.rel_strength_vs_nifty is not None else 0.0

    weakest = min(worried, key=lambda s: (rel(s), s))
    ideas = dict(ideas)
    holdings = dict(holdings)
    holdings[weakest] = replace(
        holdings[weakest],
        reasons=(
            *holdings[weakest].reasons,
            f"A stronger idea is waiting ({best.symbol}, scored {strength(best):.0%}) "
            "while every slot is full; "
            "consider replacing this one.",
        ),
    )
    ideas[best.symbol] = replace(
        ideas[best.symbol],
        reasons=(
            *ideas[best.symbol].reasons,
            f"Slots are full; your weakest holding is {weakest}.",
        ),
    )
    return ideas, holdings


__all__ = [
    "HoldingFacts",
    "IdeaFacts",
    "cost_pct",
    "decide_holding",
    "decide_idea",
    "expected_r",
    "opportunity_notes",
]
