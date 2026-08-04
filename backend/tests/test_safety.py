"""Trading-mode safety tests.

These guard the single most consequential behaviour in the system: that real
orders cannot be placed unless both latches are deliberately opened.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.brokers import get_broker
from swing_trade_ml.brokers.paper import PaperBroker
from swing_trade_ml.core.config import Settings


def _settings(**overrides) -> Settings:
    base = {
        "TRADING_MODE": "paper",
        "ALLOW_LIVE_TRADING": False,
        "API_KEY": "test",
        "JWT_SECRET_KEY": "test",
    }
    return Settings(**{**base, **overrides})


def test_paper_mode_is_not_live():
    assert _settings().is_live_trading is False


def test_trading_mode_live_alone_is_not_enough():
    """The whole point of the second latch: one flag flipped is not live."""
    assert _settings(TRADING_MODE="live", ALLOW_LIVE_TRADING=False).is_live_trading is False


def test_allow_live_alone_is_not_enough():
    assert _settings(TRADING_MODE="paper", ALLOW_LIVE_TRADING=True).is_live_trading is False


def test_both_latches_open_enables_live():
    assert _settings(TRADING_MODE="live", ALLOW_LIVE_TRADING=True).is_live_trading is True


def test_default_broker_is_paper():
    """With a default configuration, nothing can reach the exchange."""
    broker = get_broker()
    assert isinstance(broker, PaperBroker)
    assert broker.mode == "paper"


def test_kite_broker_refuses_to_place_orders_in_paper_mode(monkeypatch):
    """Even if a live broker is obtained directly, it must refuse to transmit."""
    from swing_trade_ml.brokers.base import OrderRequest
    from swing_trade_ml.brokers.kite import kite_broker
    from swing_trade_ml.core.enums import TransactionType

    request = OrderRequest(
        tradingsymbol="INFY",
        exchange="NSE",
        transaction_type=TransactionType.BUY,
        quantity=1,
    )

    with pytest.raises(RuntimeError, match="Refusing to place a live order"):
        kite_broker.place_order(request, db=None)
