# ruff: noqa: E501  (long plain-English docstrings)
"""The Momentum policy's daily picks (#321, #379): the app's EXISTING momentum rule, reused read-only.

The rule is not new. It is the "momentum 5" baseline of the brain's own evaluation: each day, the `TOP_N` (5) stocks of
the day's pool with the highest trailing `MOMENTUM_BARS` (20) bar gain at the close, ties broken by SYMBOL
(`brain/walk_forward.momentum_scores` and `services/brain_observatory/baselines.momentum_picks`). This module only feeds
those two functions stored closes and wraps what they return as ledger candidates. It invents no number and no ranking.
The functions are given the stock's SYMBOL as the key, exactly as the baseline gets it, so a tie breaks by symbol and not
by the text of an id (where "10" would sort before "9"). A stock with no symbol is keyed by its zero-padded id.

Point in time: the picks decided at the close of session D use only closes up to and including D (the ledger buys them at
the open of the next session). A close dated after D never enters D's score, and the loader never reads one past the last
session. Nothing is looked up after the fact.

Each pick carries a RULE REFERENCE (rule name and version, e.g. "momentum-20d-top5:v1") instead of a horizon record, which
is how a stored momentum fill traces back: stock id -> rule reference -> simulated fill. The name is built from the
constants of the rule it reuses, so it cannot drift from them; the version changes only when this wrapper does. Only this
module makes picks that carry that reference (the runner refuses caller-passed picks that claim it).

Momentum's "eligible universe" is declared by the caller (the stocks passed in), never widened here. A declared stock with
no stored price in the window is NOT silently dropped: it comes back in `not_ranked` with its reason, so the caller can
record it and report ranked against declared. Pure: no database, no clock. pandas and the brain functions are imported when
called.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from swing_trade_ml.simulation.ledger import Candidate, Decisions

WRAPPER_VERSION = "v1"
NO_PRICES = "no stored prices in window"


def rule_ref() -> str:
    """The rule reference stamped on every momentum pick, such as "momentum-20d-top5:v1"."""
    from swing_trade_ml.brain.walk_forward import MOMENTUM_BARS
    from swing_trade_ml.services.brain_observatory.defs import TOP_N

    return f"momentum-{MOMENTUM_BARS}d-top{TOP_N}:{WRAPPER_VERSION}"


@dataclass(frozen=True, slots=True)
class MomentumResult:
    decisions: Decisions
    ranked: tuple[int, ...]  # declared stocks that had stored prices in the window
    not_ranked: dict[int, str] = field(default_factory=dict)  # declared stocks left out, with the reason


def _keys(ids: Sequence[int], symbols: Mapping[int, str] | None) -> dict[int, str]:
    """The key each stock is ranked under: its symbol (as the brain baseline does), else its zero-padded id. Two stocks
    with one symbol are told apart by their id so that no stock is lost."""
    out: dict[int, str] = {}
    used: set[str] = set()
    for security_id in ids:
        key = ((symbols or {}).get(security_id) or "").strip() or f"#{security_id:012d}"
        if key in used:
            key = f"{key}#{security_id:012d}"
        used.add(key)
        out[security_id] = key
    return out


def momentum_result(
    closes: Mapping[int, Mapping[date, float]],
    sessions: Sequence[str],
    *,
    symbols: Mapping[int, str] | None = None,
    universe: Sequence[int] | None = None,
) -> MomentumResult:
    """The momentum picks decided at each session's close, plus which declared stocks were ranked and which were not.

    `closes[security_id][day]` are stored daily closes, including enough history before the first session for the
    trailing window. `universe` is the declared set of stocks (default: every stock in `closes`)."""
    import pandas as pd

    from swing_trade_ml.brain.walk_forward import momentum_scores
    from swing_trade_ml.services.brain_observatory.baselines import momentum_picks

    days = [date.fromisoformat(s) for s in sessions]
    declared = sorted(set(closes) if universe is None else set(universe))
    if not days:
        return MomentumResult({}, (), {})
    last = max(days)
    histories = {
        security_id: sorted((d, c) for d, c in closes.get(security_id, {}).items() if d <= last)
        for security_id in declared
    }  # nothing after the last session
    ranked = tuple(sid for sid in declared if histories[sid])
    not_ranked = {sid: NO_PRICES for sid in declared if not histories[sid]}
    key_of = _keys(ranked, symbols)
    id_of = {key: sid for sid, key in key_of.items()}
    bars = {
        key_of[sid]: pd.DataFrame(
            {"day": [d for d, _ in histories[sid]], "close": [c for _, c in histories[sid]]}
        )
        for sid in ranked
    }
    pool = {d: sorted(bars) for d in days}
    picks = momentum_picks(bars, pool, days)
    scores = momentum_scores(bars, days)
    ref = rule_ref()
    out: Decisions = {}
    for d in days:
        chosen = [
            Candidate(
                security_id=id_of[key],
                symbol=(symbols or {}).get(id_of[key], ""),
                score=float(scores[key][d]),
                rule_ref=ref,
            )
            for key in picks.get(d, [])
        ]
        if chosen:
            out[d.isoformat()] = chosen
    return MomentumResult(out, ranked, not_ranked)


def momentum_decisions(
    closes: Mapping[int, Mapping[date, float]],
    sessions: Sequence[str],
    *,
    symbols: Mapping[int, str] | None = None,
    universe: Sequence[int] | None = None,
) -> Decisions:
    """session (ISO date) -> the momentum picks decided at that session's close (see `momentum_result`, which also says
    which declared stocks were not ranked). Sessions with no pick are left out."""
    return momentum_result(closes, sessions, symbols=symbols, universe=universe).decisions
