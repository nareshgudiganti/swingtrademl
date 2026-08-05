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


def compute_charges(turnover: float) -> tuple[float, float]:
    """(brokerage, taxes) for one executed order.

    Approximates Zerodha's equity-delivery cost stack — STT, exchange
    transaction charges, SEBI fees, stamp duty and GST — with a single
    basis-point figure on turnover. Exact to the rupee it is not; the point
    is that reported P&L is never gross.
    """
    brokerage = settings.PAPER_BROKERAGE_PER_ORDER
    taxes = turnover * (settings.PAPER_TAX_BPS / BPS)
    return brokerage, taxes
