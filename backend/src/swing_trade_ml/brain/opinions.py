"""Which opinion speaks for a stock, and whether it likes the stock.

Shared by the risk gate (M07) and the decision engine (M08) so both always
read the same opinion the same way. A reasoning module's combined view (M06)
comes first, then the active model, then the strongest other view.
"""

from __future__ import annotations

from collections.abc import Iterable

from swing_trade_ml.brain.contracts import Opinion

SOURCE_PREFERENCE = ("combined", "model")


def pick_opinion(opinions: Iterable[Opinion]) -> Opinion | None:
    opinions = list(opinions)
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
