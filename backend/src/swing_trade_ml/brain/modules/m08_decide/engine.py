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
from swing_trade_ml.brain.modules.m08_decide.money import cost_pct, cost_qty, expected_r, expected_r_from_mean
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m08_decide.rules import HOLDING_RULES, IDEA_RULES, Rule
from swing_trade_ml.brain.opinions import liked, strength
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
    notes: tuple[str, ...] = ()  # context lines from modifier opinions; never change the word
    sector_rank: int | None = None  # M11 rank (1 = strongest); for optional sector gate
    playbook_match: bool = True  # False when playbook gate is on and no setup found


@dataclass(frozen=True, slots=True)
class HoldingFacts:
    holding: c.Holding
    snapshot: c.Snapshot | None
    stock: c.StockState | None
    market_mode: MarketMode
    notes: tuple[str, ...] = ()
    track: c.TrackPoint | None = None  # M15: where the trade stands against similar trades


# --- ideas -----------------------------------------------------------------------


def recall_r(r: c.Recall, f, policy: DecidePolicy) -> float:
    """Expected result after costs in R: from the honest average exit when M05
    gives one, otherwise from the hit rate (every miss a full loss)."""
    cost = cost_pct(f.snapshot.close, cost_qty(f.verdict, f.snapshot.close, policy))
    if r.honest_mean_return is not None:
        return expected_r_from_mean(r.honest_mean_return, cost, policy)
    return expected_r(r.hit_rate, cost, policy)


def _evidence(f: IdeaFacts, qty: int, policy: DecidePolicy) -> str:
    r = f.recall
    if (
        r is not None
        and r.honest_hit_rate is not None
        and r.n_similar >= policy.min_similar_cases
        and f.snapshot
    ):
        days = f" · median {r.median_days:.0f} trading days" if r.median_days is not None else ""
        band = (
            f" · middle half ended between {r.p25:+.1%} and {r.p75:+.1%}"
            if r.p25 is not None and r.p75 is not None
            else ""
        )
        return (
            f"Similar cases: {r.n_similar} · reached +{policy.target_pct:.0%} first in "
            f"{r.hit_rate:.0%}{band}{days}. "
            f"On months it had not seen, cases like these came true about {r.honest_hit_rate:.0%}; "
            f"expected result after costs {recall_r(r, f, policy):+.2f} R per trade "
            f"(1 R = the {policy.stop_pct:.0%} risked)."
        )
    if r is not None and r.hit_rate is not None and r.n_similar >= policy.min_similar_cases and f.snapshot:
        ev = expected_r(
            r.hit_rate, cost_pct(f.snapshot.close, cost_qty(f.verdict, f.snapshot.close, policy)), policy
        )
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
    if o is not None and o.calibrated and o.probability is not None and f.snapshot:
        ev = expected_r(
            o.probability, cost_pct(f.snapshot.close, cost_qty(f.verdict, f.snapshot.close, policy)), policy
        )
        return (
            f"Calibrated chance of +{policy.target_pct:.0%} before -{policy.stop_pct:.0%}: "
            f"{o.probability:.0%}. "
            f"Expected result after costs: {ev:+.2f} R per trade (1 R = the {policy.stop_pct:.0%} risked). "
            f"{o.evidence}"
        ).strip()
    if o is not None and o.probability is not None:
        return (
            "No similar-case record yet, so the chance of reaching the target first is not known. "
            f"The model scores this stock {o.probability:.0%} against a buy level of {o.threshold or 0:.0%}; "
            "that score ranks stocks, it is not a probability."
        )
    return "No similar-case record yet."


def _draft_idea(f: IdeaFacts, policy: DecidePolicy) -> c.Decision:
    def wait(
        reason: str, confidence: float | None = None, confidence_source: str | None = None
    ) -> c.Decision:
        return c.Decision(
            symbol=f.symbol,
            kind="idea",
            word=IdeaWord.WAIT,
            reasons=(reason,),
            confidence=confidence,
            confidence_source=confidence_source,
            evidence_text=_evidence(f, 0, policy),
        )

    if f.snapshot is None or f.snapshot.close <= 0:
        return wait("No price data for this stock yet.")
    o = f.opinion
    if o is None:
        return wait("No opinion about this stock today (no model score or reasoning module answer).")
    if not liked(o):
        if o.calibrated and o.probability is not None:
            return wait(
                f"Calibrated chance {o.probability:.0%} is below the {o.threshold or 0:.0%} "
                "needed to pay after costs.",
                o.probability,
                o.source,
            )
        if o.probability is not None:
            return wait(
                f"Model score {o.probability:.0%} is below the buy level {o.threshold or 0:.0%}.",
                o.probability,
                o.source,
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
        reasons=(*o.reasons, plan, *((f.verdict.note,) if f.verdict is not None and f.verdict.note else ())),
        entry_low=round(close - half_zone, 2),
        entry_high=round(close + half_zone, 2),
        target=target,
        stop=stop,
        qty=qty,
        horizon_days=policy.horizon_days,
        confidence=o.probability if o.probability is not None else o.confidence,
        confidence_source=o.source if o.probability is not None else None,
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
    # Context lines go last, except ones a reason already says ("Results on
    # 08 Oct." when the AVOID reason names that date).
    notes = tuple(n for n in facts.notes if not any(n.rstrip(".") in r for r in d.reasons))
    if notes:
        d = replace(d, reasons=(*d.reasons, *notes))
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
        if f.track is not None and f.track.status in ("on track", "past horizon", "no data"):
            draft = replace(draft, reasons=(*draft.reasons, f.track.reason))
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
        and liked(f.opinion)
        and ideas.get(s) is not None
        and ideas[s].word is IdeaWord.WATCH
    ]
    worried = [s for s, d in holdings.items() if d.word is HoldingWord.MONITOR]
    if not waiting or not worried:
        return ideas, holdings

    def strength_of(f: IdeaFacts) -> float:
        return strength(f.opinion)

    best = max(waiting, key=lambda f: (strength_of(f), f.symbol))

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
            f"A stronger idea is waiting ({best.symbol}, scored {strength_of(best):.0%}) "
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
