"""Which opinion speaks for a stock, and whether it likes the stock.

Shared by the risk gate (M07) and the decision engine (M08) so both always
read the same opinion the same way. A reasoning module's combined view (M06)
comes first, then the active model, then the strongest other view.

Modifier opinions (a sector's rotation, later a stock setup or an event) are
context, not a view: they never speak for a stock, so a stock the models
have not scored can never be bought on a sector tilt alone. They nudge the
order in which liked ideas are judged (`rank_strength`) and add a line to
the card (`modifier_notes`). A new modifier is one more name in
MODIFIER_SOURCES.
"""

from __future__ import annotations

from collections.abc import Iterable

from swing_trade_ml.brain.contracts import Opinion

SOURCE_PREFERENCE = ("combined", "model")
MODIFIER_SOURCES = frozenset({"sector"})
# How much the modifiers' stances move the order: a leading sector (+0.1)
# adds 2.5 points to a 0..1 strength — enough to break a near tie, never
# enough to lift a weak idea over a clearly stronger one.
TILT_WEIGHT = 0.25


def is_modifier(o: Opinion) -> bool:
    return o.source in MODIFIER_SOURCES


def pick_opinion(opinions: Iterable[Opinion]) -> Opinion | None:
    opinions = [o for o in opinions if not is_modifier(o)]
    if not opinions:
        return None
    for source in SOURCE_PREFERENCE:
        for o in opinions:
            if o.source == source:
                return o
    return max(opinions, key=lambda o: (o.stance, o.source))


def liked(o: Opinion) -> bool:
    """A probability at or above its buy level; otherwise a positive stance."""
    if o.probability is not None and o.threshold is not None:
        return o.probability >= o.threshold
    return o.stance > 0


def strength(o: Opinion) -> float:
    """0..1, for ranking: the probability when there is one, else the stance rescaled."""
    return o.probability if o.probability is not None else (o.stance + 1) / 2


def rank_strength(opinions: Iterable[Opinion]) -> float:
    """The order key for liked ideas: the speaking opinion's strength plus a
    small modifier tilt. 0 when nothing speaks for the stock."""
    opinions = list(opinions)
    primary = pick_opinion(opinions)
    if primary is None:
        return 0.0
    return strength(primary) + TILT_WEIGHT * sum(o.stance for o in opinions if is_modifier(o))


def modifier_notes(opinions: Iterable[Opinion]) -> tuple[str, ...]:
    return tuple(r for o in opinions if is_modifier(o) for r in o.reasons)
