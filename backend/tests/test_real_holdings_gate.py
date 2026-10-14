"""Real orders from My Holdings open a narrow door, not the whole system.

The bot stays on paper for its trial. The owner's own hand-placed My Holdings
orders may reach Zerodha only when ALLOW_REAL_HOLDINGS_ORDERS is on AND the
request carries the reserved tag only services/execution.py builds
(place_real_holding_buy / place_real_holding_sell, called from services/real_orders.py). Anything
else still needs both full live latches, exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from swing_trade_ml.brokers import get_broker, paper_broker
from swing_trade_ml.brokers.base import REAL_HOLDINGS_TAG_PREFIX, OrderRequest
from swing_trade_ml.brokers.kite import KiteBroker
from swing_trade_ml.core import config
from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType


class _RecordingKite:
    VARIETY_REGULAR = "regular"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return 990001


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    b = KiteBroker()
    b._token_loaded = True
    b._kite = _RecordingKite()
    return b


def _request(tag: str | None) -> OrderRequest:
    return OrderRequest(
        tradingsymbol="ITC",
        exchange="NSE",
        transaction_type=TransactionType.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product=ProductType.CNC,
        tag=tag,
    )


def test_the_reserved_tag_is_alphanumeric_and_unique_to_my_holdings():
    """Kite documents a tag as alphanumeric, max 20 characters; no other tag
    the app sends (stml-<id>, stml-exit-<id>, manual) starts with it."""
    assert REAL_HOLDINGS_TAG_PREFIX == "stmlh" and REAL_HOLDINGS_TAG_PREFIX.isalnum()
    for other in ("stml-7", "stml-exit-7", "manual"):
        assert not other.startswith(REAL_HOLDINGS_TAG_PREFIX)


def test_the_latch_is_off_by_default():
    assert config.Settings.model_fields["ALLOW_REAL_HOLDINGS_ORDERS"].default is False
    assert config.Settings.model_fields["REAL_HOLDINGS_MAX_ORDER_INR"].default == 10000
    assert config.Settings.model_fields["REAL_HOLDINGS_MAX_DAY_INR"].default == 25000


def test_latch_off_refuses_even_a_my_holdings_order(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", False, raising=False)
    with pytest.raises(RuntimeError, match="Refusing to place a live order"):
        broker.place_order(_request(f"{REAL_HOLDINGS_TAG_PREFIX}b1"), db=None)
    assert broker._kite.calls == []


def test_latch_on_lets_only_a_my_holdings_order_through(broker, monkeypatch):
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)

    result = broker.place_order(_request(f"{REAL_HOLDINGS_TAG_PREFIX}b1"), db=None)
    assert result.status == OrderStatus.PENDING
    assert len(broker._kite.calls) == 1

    for tag in (None, "manual", "stml-exit-7", "brain-approval"):
        with pytest.raises(RuntimeError, match="Refusing to place a live order"):
            broker.place_order(_request(tag), db=None)
    assert len(broker._kite.calls) == 1, "a bot/manual/brain order must never reach Zerodha"


def test_latch_on_still_hands_the_bot_the_paper_broker(monkeypatch):
    monkeypatch.setattr(config.settings, "TRADING_MODE", "paper", raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_LIVE_TRADING", False, raising=False)
    monkeypatch.setattr(config.settings, "ALLOW_REAL_HOLDINGS_ORDERS", True, raising=False)
    assert get_broker() is paper_broker


def test_only_the_my_holdings_flow_uses_the_reserved_tag():
    """The gate trusts the tag, so only the My Holdings placement code in
    services/execution.py may build one."""
    src = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
    allowed = {"brokers/base.py", "brokers/kite.py", "services/execution.py"}
    users = {
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if "REAL_HOLDINGS_TAG_PREFIX" in p.read_text(encoding="utf-8")
        or '"stmlh' in p.read_text(encoding="utf-8")
    }
    assert users <= allowed, f"unexpected users of the real-order tag: {users - allowed}"
