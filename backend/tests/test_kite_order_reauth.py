"""An order must survive the token dying mid-session.

Zerodha invalidates this app's access token whenever the same account signs
in to kite.zerodha.com — so opening the Kite app on a phone to glance at a
price kills the bot's session in the middle of a trading day. Quotes,
holdings, LTP and historical data already re-authenticate and retry when that
happens. Placing an order did not, which meant the one call that actually
moves money was the only one that gave up.

Retrying is safe here precisely because it is narrow: reauth_and_retry
re-raises anything that is not a rejected token, and a rejected token is
refused before Zerodha processes the request, so the order cannot already be
resting at the exchange.
"""

from __future__ import annotations

import pytest
from kiteconnect.exceptions import TokenException

from swing_trade_ml.brokers.base import OrderRequest
from swing_trade_ml.brokers.kite import KiteBroker
from swing_trade_ml.core import config
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType

# The exact wording KiteBroker._is_token_rejected matches on.
TOKEN_REJECTED = "Incorrect `api_key` or `access_token`."


class _FakeKite:
    """Rejects the token once, then behaves."""

    VARIETY_REGULAR = "regular"

    def __init__(self, fail_times: int = 1) -> None:
        self.calls = 0
        self._fail_times = fail_times

    def place_order(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise TokenException(TOKEN_REJECTED)
        return 251001


@pytest.fixture
def live_broker(monkeypatch):
    """A KiteBroker with the live latches open and a session already loaded,
    so the test exercises the token path rather than the guards in front of
    it."""
    monkeypatch.setattr(config.settings, "TRADING_MODE", "live", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", True, raising=False)
    monkeypatch.setattr(config.settings, "KITE_USER_ID", "ZZ0000", raising=False)
    monkeypatch.setattr(config.settings, "KITE_PASSWORD", "pw", raising=False)
    monkeypatch.setattr(config.settings, "KITE_TOTP_SECRET", "seed", raising=False)

    broker = KiteBroker()
    broker._token_loaded = True

    logins: list[int] = []
    monkeypatch.setattr(broker, "auto_login", lambda db: logins.append(1))
    return broker, logins


def _request() -> OrderRequest:
    return OrderRequest(
        tradingsymbol="TITAN",
        exchange="NSE",
        transaction_type=TransactionType.SELL,
        quantity=10,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
    )


def test_a_rejected_token_reauthenticates_instead_of_failing_the_order(live_broker):
    broker, logins = live_broker
    broker._kite = _FakeKite(fail_times=1)

    result = broker.place_order(_request(), db=None)

    assert logins == [1], "should have re-authenticated exactly once"
    assert result.status == OrderStatus.PENDING
    assert result.broker_order_id == "251001"
    assert broker._kite.calls == 2


def test_a_token_rejected_twice_still_gives_up(live_broker):
    """One retry only. A second failure is a real problem and must surface as
    a rejection rather than loop against the exchange."""
    broker, logins = live_broker
    broker._kite = _FakeKite(fail_times=2)

    result = broker.place_order(_request(), db=None)

    assert logins == [1]
    assert result.status == OrderStatus.REJECTED
    assert broker._kite.calls == 2


def test_a_rejection_that_is_not_the_token_is_never_retried(live_broker):
    """Margin shortfalls, freeze limits and bad symbols must fail on the first
    attempt — retrying those is how one intended order becomes two."""
    broker, logins = live_broker

    class _Broke:
        VARIETY_REGULAR = "regular"

        def __init__(self) -> None:
            self.calls = 0

        def place_order(self, **kwargs):
            self.calls += 1
            raise TokenException("Insufficient funds")

    broker._kite = _Broke()

    result = broker.place_order(_request(), db=None)

    assert logins == []
    assert result.status == OrderStatus.REJECTED
    assert broker._kite.calls == 1
