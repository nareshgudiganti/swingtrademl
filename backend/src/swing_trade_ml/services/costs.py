"""The paper cost model — one place, so every consumer stays honest together.

Previously duplicated (with a "must stay in sync" comment) between
`brokers/paper.py` and `services/backtest.py`. Both now import from here, so
a fill computed by PaperBroker and a fill computed by the backtest replay —
or a manually-recorded trade that falls back to these defaults — can never
silently drift apart.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import TransactionType

BPS = 10_000.0


def apply_slippage(price: float, side: TransactionType | str) -> float:
    """Move the fill against us — buys pay up, sells receive less."""
    delta = price * (settings.PAPER_SLIPPAGE_BPS / BPS)
    return price + delta if side == TransactionType.BUY else price - delta


def compute_charges(turnover: float, side: TransactionType | str | None = None) -> tuple[float, float]:
    """(brokerage, taxes) for one executed order.

    Approximates Zerodha's equity-delivery cost stack — STT, exchange
    transaction charges, SEBI fees, stamp duty and GST — with a single
    basis-point figure on turnover, folding in the flat per-scrip DP charge
    on sells too (see PAPER_DP_CHARGE_PER_SELL — a real, previously-missing
    cost). Exact to the rupee it is not; the point is that reported P&L is
    never gross, and never quietly cheaper than a real fill would be.

    `side` is optional only for backward compatibility with call sites that
    don't yet know which leg they're pricing — omitting it means the DP
    charge is skipped, which understates cost, so pass it whenever it's
    available.
    """
    brokerage = settings.PAPER_BROKERAGE_PER_ORDER
    taxes = turnover * (settings.PAPER_TAX_BPS / BPS)
    if side == TransactionType.SELL or side == "SELL":
        taxes += settings.PAPER_DP_CHARGE_PER_SELL
    return brokerage, taxes
