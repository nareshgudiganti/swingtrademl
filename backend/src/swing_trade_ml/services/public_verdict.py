"""The stock-level verdict public (non-owner) screens show, kept apart from the test portfolio's decision.

The brain writes ONE decision per stock. For a stock it likes, the risk gate (M07) then asks the *test
portfolio* whether there is room to buy it, and M08 lowers TRADE to WATCH when there is not. That second
answer is about the private account, not the stock, so a customer who has no portfolio must not see it.

Nothing here changes what the brain stored, what M07/M08 decide, or any order path. It only decides what a
non-owner is shown:

* `stock_verdict` gives the word back as TRADE only when the stored record PROVES that the one thing which
  held the idea back was the account's room or the minimum position size. The brain stores no rule id, only
  the text each rule wrote, so the proof is the text: it is matched by the same templates the "what would
  change" feature pins in tests (tests/test_what_would_change.py runs the real rules), and anything not
  recognised is NOT restored. A sector limit, the small-company budget, the trading-volume limit, a drawdown
  halt, a cool-down, an exchange watch list, results, a weak signal, a market-mode rule or a second
  recognised reason all keep WATCH / WAIT / AVOID.
* The WATCH rule "in a careful market only stocks in an up-trend" runs AFTER the risk check and is silently
  skipped once the risk check has already said WATCH, so the record cannot show it. In a careful market a
  stock is therefore restored only when its own price trend is shown not to be falling.
* `scrub` removes the account's own numbers (rupee room, positions, limits) from what a non-owner gets.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from swing_trade_ml.brain.constitution import NOT_APPROVED
from swing_trade_ml.services.what_would_change import (
    RISK_PREFIX,
    _line,
    _risk_line,
    what_would_change,
)

#: Risk-gate refusals that are only about the account's room or the minimum position size.
#: Keys are those of what_would_change._risk_line.
CAPACITY_KEYS = frozenset(
    {
        "slots_full",
        "slots_taken_by_stronger",
        "deployable_room",
        "cash_reserve",
        "cash",
        "defensive_half_size",
        "room_after_stronger",
        "min_position",
    }
)

#: For "...limited by the X..." refusals, the X values that are the account's own size or room. Anything
#: else (sector limit, small-company budget, trading-volume limit, an unknown label) is not capacity.
CAPACITY_LIMITS = frozenset(
    {
        "market-conditions limit",
        "cash reserve",
        "available cash",
        "concentration cap",
        "fixed amount",
        "risk-per-trade",
        "half size in a defensive market",
        "limits",
    }
)

_LIMITED_BY = re.compile(r"^The position would only be .+? \(limited by the (.+?)\) — below the")
_AFTER_STRONGER = re.compile(r"^After stronger ideas in this run, the (.+?) leaves room for only")

#: Same words as the brain's market modes.
NORMAL = "NORMAL"


def is_capacity_reason(reason: str) -> bool:
    """True when `reason` is a risk-gate refusal that is ONLY about the account's room / minimum position."""
    r = (reason or "").strip()
    if not r.startswith(RISK_PREFIX):
        return False
    why = r[len(RISK_PREFIX) :]
    key, _ = _risk_line(why)
    if key not in CAPACITY_KEYS:
        return False
    for pattern in (_LIMITED_BY, _AFTER_STRONGER):
        m = pattern.match(why.strip())
        if m:
            return m.group(1) in CAPACITY_LIMITS
    return True


def _holds_back(reason: str) -> bool:
    """A stored reason that holds the idea back (recognised by the explain-why catalogue)."""
    return _line(reason, None, None, None) is not None


@dataclass(frozen=True, slots=True)
class StockVerdict:
    word: str  # what a public screen shows
    restored: bool  # True when TRADE was recovered from a capacity-only downgrade


def stock_verdict(
    *,
    kind: str,
    word: str,
    downgraded_from: str | None,
    downgrade_reason: str | None,
    reasons: Iterable[str],
    overruled_word: str | None = None,
    banner_mode: str | None = None,
    trend: Callable[[], str | None] | None = None,
) -> StockVerdict:
    """The stock-level word: the stored word unless the capacity-only proof holds (see module doc)."""
    same = StockVerdict(word, False)
    if kind != "idea" or word != "WATCH" or downgraded_from != "TRADE" or overruled_word:
        return same
    if not is_capacity_reason(downgrade_reason or ""):
        return same
    for r in reasons:
        if isinstance(r, str) and r != downgrade_reason and _holds_back(r) and not is_capacity_reason(r):
            return same  # mixed: a second, non-capacity reason is on record
    if banner_mode != NORMAL:
        # Careful market: M08's "falling stock" rule could have been skipped silently, so prove the trend.
        found = trend() if trend is not None else None
        if found is None or found == "down":
            return same
    return StockVerdict("TRADE", True)


def trend_lookup(db: Any, run: Any, symbol: str) -> Callable[[], str | None] | None:
    """The stock's own price trend as the brain's M03 computes it, read only when a public verdict in a
    careful market needs it (see services/public_verdict.py). None when it cannot be worked out."""
    if run is None or run.as_of is None:
        return None

    def trend() -> str | None:
        try:
            import pandas as pd

            from swing_trade_ml.brain.modules.m03_state.state import stock_state
            from swing_trade_ml.brain.reader import DatedReader

            closes = DatedReader(db, run.as_of, bool(run.live)).ohlcv(symbol, 260)["close"]
            found = stock_state(symbol, closes, pd.Series(dtype=float)).trend
            return None if found == "unknown" else found
        except Exception:  # noqa: BLE001 - a trend that cannot be shown simply means "not restored"
            return None

    return trend


# --------------------------------------------------------------- what a non-owner is shown --


#: What a non-owner reads in place of any risk-gate refusal that is NOT capacity-only (a sector limit, a
#: halt, a cool-down, ...). Those texts quote the account's own holdings, limits or trade history, so they
#: stay private; the word is still WATCH / WAIT / AVOID and this number-free line says a safety check held it.
PUBLIC_RISK_LINE = NOT_APPROVED


def _is_risk_line(reason: Any) -> bool:
    return isinstance(reason, str) and reason.strip().startswith(RISK_PREFIX)


def scrub_reasons(reasons: Iterable[str]) -> list[str]:
    """The stored reasons without any account figure: capacity lines are dropped, other risk-gate lines become
    PUBLIC_RISK_LINE (once)."""
    out: list[str] = []
    for r in reasons:
        if _is_risk_line(r):
            if not is_capacity_reason(r) and PUBLIC_RISK_LINE not in out:
                out.append(PUBLIC_RISK_LINE)
        else:
            out.append(r)
    return out


def public_fields(
    *,
    kind: str,
    word: str,
    downgraded_from: str | None,
    downgrade_reason: str | None,
    reasons: Iterable[str],
    overruled_word: str | None = None,
    banner_mode: str | None = None,
    trend: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    """The decision fields a non-owner may see: the stock verdict, reasons and downgrade without the account's
    numbers. `downgraded_from` / `downgrade_reason` are dropped when the downgrade was capacity-only."""
    reasons = list(reasons or [])
    verdict = stock_verdict(
        kind=kind,
        word=word,
        downgraded_from=downgraded_from,
        downgrade_reason=downgrade_reason,
        reasons=reasons,
        overruled_word=overruled_word,
        banner_mode=banner_mode,
        trend=trend,
    )
    capacity_only = is_capacity_reason(downgrade_reason or "")
    if capacity_only:
        shown_from, shown_reason = None, None
    elif _is_risk_line(downgrade_reason):
        shown_from, shown_reason = downgraded_from, PUBLIC_RISK_LINE
    else:
        shown_from, shown_reason = downgraded_from, downgrade_reason
    return {
        "word": verdict.word,
        "reasons": scrub_reasons(reasons),
        "downgraded_from": shown_from,
        "downgrade_reason": shown_reason,
    }


def public_what_would_change(
    fields: Mapping[str, Any],
    *,
    kind: str,
    banner_mode: str | None,
    banner_headline: str | None,
    rank: Any = None,
) -> list[dict[str, str]]:
    """'What would change this?' read from the scrubbed record, so no account number leaks through it."""
    shim = SimpleNamespace(
        kind=kind,
        word=fields["word"],
        reasons=fields["reasons"],
        downgrade_reason=fields["downgrade_reason"],
    )
    return what_would_change(shim, rank=rank, banner_mode=banner_mode, banner_headline=banner_headline)


__all__ = [
    "CAPACITY_KEYS",
    "CAPACITY_LIMITS",
    "PUBLIC_RISK_LINE",
    "StockVerdict",
    "is_capacity_reason",
    "public_fields",
    "public_what_would_change",
    "scrub_reasons",
    "stock_verdict",
    "trend_lookup",
]
