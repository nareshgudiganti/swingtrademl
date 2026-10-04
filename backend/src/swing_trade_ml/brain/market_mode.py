"""The market mode every step should act on.

The market brain (M10) decides NORMAL / DEFENSIVE / NO NEW TRADES in the
state step. Situation recognition (M04) runs one step later and may suggest
going careful (a crash, a bear phase, a market unlike any day before). This
turns that suggestion into DEFENSIVE — only ever more careful, never bolder —
so the risk gate (M07), the decision engine (M08), the decide fallback and the
constitution all read the same mode the same way.
"""

from __future__ import annotations

from collections.abc import Iterable

from swing_trade_ml.brain import contracts as c


def effective_mode(
    market: c.MarketState | None, situations: Iterable[c.Situation]
) -> tuple[c.MarketMode, str | None]:
    """(mode, reason) — reason is set only when a suggestion changed the mode."""
    mode = (market.mode if market is not None else None) or c.MarketMode.DEFENSIVE
    if mode is not c.MarketMode.NORMAL:
        return mode, None
    for s in situations:
        if s.scope == "market" and s.suggest_defensive:
            reason = s.evidence[0] if s.evidence else f"Market situation: {s.label}."
            return c.MarketMode.DEFENSIVE, reason
    return mode, None
