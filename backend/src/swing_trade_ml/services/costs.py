"""The paper cost model — one place, so every consumer stays honest together.

Previously duplicated (with a "must stay in sync" comment) between
`brokers/paper.py` and `services/backtest.py`. Both now import from here, so
a fill computed by PaperBroker and a fill computed by the backtest replay —
or a manually-recorded trade that falls back to these defaults — can never
silently drift apart.

Two properties of the real cost stack drive the shape of this module:

1. **Brokerage on equity delivery is zero at Zerodha.** What remains is
   statutory, and it is *not* symmetric — stamp duty falls on the buy leg
   only, so each side gets its own rate.
2. **The depository fee is flat.** It costs the same on a 2,000 sale as on a
   200,000 one, which makes it the dominant cost at small position sizes and
   negligible at large ones. `flat_charge()` exposes it separately so sizing
   logic can reason about that, rather than having to re-derive it from a
   blended number.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import TransactionType

BPS = 10_000.0


def _is_sell(side: TransactionType | str) -> bool:
    """Normalise the leg once, and fail loudly on anything unrecognised.

    `TransactionType` is a `StrEnum`, so a bare `side == TransactionType.BUY`
    comparison happens to work for the raw string "BUY" as well — but that is
    accidental, and the failure mode of getting it wrong is silent: an
    unrecognised value would fall through to the `else` branch and be priced
    as the opposite leg. Raising is cheap; a mispriced fill discovered months
    later in a backtest is not.
    """
    normalised = str(side).upper()
    if normalised not in ("BUY", "SELL"):
        raise ValueError(f"Unknown transaction side: {side!r}")
    return normalised == "SELL"


def apply_slippage(price: float, side: TransactionType | str) -> float:
    """Move the fill against us — buys pay up, sells receive less."""
    delta = price * (settings.PAPER_SLIPPAGE_BPS / BPS)
    return price - delta if _is_sell(side) else price + delta


def flat_charge(side: TransactionType | str) -> float:
    """The part of the cost stack that does not scale with turnover.

    Zerodha's DP (Depository Participant) fee: a flat per-scrip charge on
    every DELIVERY SELL, levied by the depository regardless of quantity or
    value. Never on buys, never on intraday — only CNC sells, which is every
    exit this app makes.

    Exposed on its own because position sizing needs to know the cost is flat:
    it is what makes a 2,000 position uneconomic and what makes selling half
    of a small position cost a second full fee.
    """
    return settings.PAPER_DP_CHARGE_PER_SELL if _is_sell(side) else 0.0


def compute_charges(turnover: float, side: TransactionType | str) -> tuple[float, float]:
    """(brokerage, taxes) for one executed order.

    `taxes` bundles the proportional statutory stack — STT, exchange
    transaction charges, SEBI fees, stamp duty and GST — with the flat
    depository fee on sells, because `orders` and `positions` carry exactly
    two cost columns. Callers that need the flat component on its own should
    ask `flat_charge()` rather than trying to unpick this number.

    `side` is required. It was optional once, defaulting to skipping the
    depository fee, which meant a caller that forgot it silently understated
    cost — and now that the two legs carry different rates there is no
    defensible default at all.
    """
    rate = settings.PAPER_TAX_BPS_SELL if _is_sell(side) else settings.PAPER_TAX_BPS_BUY
    taxes = turnover * (rate / BPS) + flat_charge(side)
    return settings.PAPER_BROKERAGE_PER_ORDER, taxes
