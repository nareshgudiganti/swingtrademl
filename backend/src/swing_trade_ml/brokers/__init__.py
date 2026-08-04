"""Broker selection.

`get_broker()` is the only way trading code obtains a broker. It reads the
safety latches on every call rather than caching a decision at import time, so
the mode cannot be stale relative to configuration.
"""

from __future__ import annotations

from swing_trade_ml.brokers.base import (
    Broker,
    BrokerMargins,
    BrokerPosition,
    OrderRequest,
    OrderResult,
)
from swing_trade_ml.brokers.kite import KiteAuthError, KiteBroker, kite_broker
from swing_trade_ml.brokers.paper import PaperBroker, paper_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)


def get_broker() -> Broker:
    """Return the live broker only when both safety latches are open.

    Any other configuration — including `TRADING_MODE=live` on its own —
    resolves to the paper broker. Defaulting to simulation means a
    misconfiguration costs nothing.
    """
    if settings.is_live_trading:
        return kite_broker
    return paper_broker


def current_mode() -> str:
    return get_broker().mode


__all__ = [
    "Broker",
    "BrokerMargins",
    "BrokerPosition",
    "KiteAuthError",
    "KiteBroker",
    "OrderRequest",
    "OrderResult",
    "PaperBroker",
    "current_mode",
    "get_broker",
    "kite_broker",
    "paper_broker",
]
