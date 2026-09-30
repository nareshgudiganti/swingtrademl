"""The constitution pass: the last thing every run does, and it cannot be
switched off. It only ever lowers decisions (via `contracts.downgrade`).

C1  no TRADE without an allowed verdict from the mandatory risk gate
C2  no risk gate, or an owner halt → banner NO NEW TRADES, every TRADE → WATCH
C5  data not checked, or stale → TRADE capped at WATCH
C11 every stock in the run gets a decision with a reason
"""

from __future__ import annotations

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext

NO_RISK_GATE = "The risk gate is not installed or did not run, so the brain will not suggest new trades."
NOT_APPROVED = "The risk gate did not approve this trade."
DATA_NOT_CHECKED = "Data quality was not checked (the data gateway is not installed)."


def _no_new_trades_reasons(ctx: BrainContext) -> list[str]:
    reasons = []
    system = ctx.system
    if system is not None and system.entries_halted:
        why = f": {system.halt_reason}" if system.halt_reason else ""
        reasons.append(f"Owner paused new buys{why}.")
    if not ctx.risk_gate_ran:
        reasons.append(NO_RISK_GATE)
    return reasons


def _cap_trade(ctx: BrainContext, d: c.Decision, stop_reasons: list[str]) -> c.Decision:
    if d.word is not c.IdeaWord.TRADE:
        return d
    if stop_reasons:
        return c.downgrade(d, c.IdeaWord.WATCH, stop_reasons[0])
    verdict = ctx.verdicts.get(d.symbol)
    if verdict is None or not verdict.allowed:
        return c.downgrade(d, c.IdeaWord.WATCH, NOT_APPROVED)
    quality = ctx.quality.get(d.symbol)
    if quality is None:
        return c.downgrade(d, c.IdeaWord.WATCH, DATA_NOT_CHECKED)
    if not quality.fresh:
        detail = "; ".join(quality.issues) or f"quality score {quality.score:.2f}"
        return c.downgrade(d, c.IdeaWord.WATCH, f"Data is not reliable today ({detail}).")
    return d


def enforce(ctx: BrainContext) -> None:
    stop_reasons = _no_new_trades_reasons(ctx)
    if stop_reasons:
        ctx.banner = c.Banner(
            mode=c.MarketMode.NO_NEW_TRADES, headline=stop_reasons[0], reasons=tuple(stop_reasons)
        )
    elif ctx.banner is None:
        ctx.banner = c.Banner(mode=c.MarketMode.DEFENSIVE, headline="Market state is unknown.")

    for symbol in ctx.idea_symbols:
        if symbol not in ctx.decisions:
            ctx.decisions[symbol] = c.Decision(
                symbol=symbol,
                kind="idea",
                word=c.IdeaWord.WAIT,
                reasons=("No decision was produced for this stock.",),
            )
    for symbol in ctx.held_symbols:
        if symbol not in ctx.decisions:
            ctx.decisions[symbol] = c.Decision(
                symbol=symbol,
                kind="holding",
                word=c.HoldingWord.MONITOR,
                reasons=("No review was produced for this holding.",),
            )

    for symbol, decision in list(ctx.decisions.items()):
        ctx.decisions[symbol] = _cap_trade(ctx, decision, stop_reasons)
