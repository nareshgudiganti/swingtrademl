"""The broker port.

Every piece of trading logic depends on this interface, never on `kiteconnect`
directly. That is what makes the six-month paper phase honest: the paper broker
and the live broker are called through the same methods with the same
arguments, so nothing about the strategy code changes on the day the switch is
flipped — only which implementation the factory returns.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import OrderStatus, OrderType, ProductType, TransactionType


@dataclass(slots=True)
class OrderRequest:
    """Broker-agnostic order instruction."""

    tradingsymbol: str
    exchange: str
    transaction_type: TransactionType
    quantity: int
    order_type: OrderType = OrderType.MARKET
    product: ProductType = ProductType.CNC
    price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None


@dataclass(slots=True)
class OrderResult:
    """Outcome of a placement, normalised across brokers."""

    broker_order_id: str
    status: OrderStatus
    filled_quantity: int = 0
    average_price: float | None = None
    brokerage: float = 0.0
    taxes: float = 0.0
    slippage: float = 0.0
    message: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(slots=True)
class BrokerPosition:
    tradingsymbol: str
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float


@dataclass(slots=True)
class BrokerMargins:
    available_cash: float
    used_margin: float
    total: float


class BrokerStopState:
    """Lifecycle of a stop the broker holds on our behalf.

    Deliberately plain strings rather than a core enum: this is the broker
    port's own vocabulary, and `Position.broker_stop_state` stores it verbatim
    so a state a future broker reports that we do not yet model is recorded
    rather than rejected.
    """

    NONE = "NONE"
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class StopRequest:
    """A stop the broker should hold and trigger itself.

    Distinct from an OrderRequest with a trigger price: that is an order we
    send when *we* decide, and it rests only for the session. This is a
    standing instruction (Zerodha's GTT) that survives us being offline —
    which is the entire reason for wanting one.
    """

    tradingsymbol: str
    exchange: str
    quantity: int
    trigger_price: float
    # None means "sell at market once triggered"
    limit_price: float | None = None
    product: ProductType = ProductType.CNC
    tag: str | None = None


@dataclass(slots=True)
class BrokerStop:
    """A stop currently held at the broker, normalised across brokers."""

    broker_stop_id: str
    tradingsymbol: str
    exchange: str
    quantity: int
    trigger_price: float
    state: str = BrokerStopState.ACTIVE
    raw: dict = field(default_factory=dict)


class Broker(ABC):
    """Common surface for the paper and live implementations."""

    #: "paper" or "live" — stamped onto every row this broker writes
    mode: str

    #: Whether this broker can hold a stop itself, so a position is protected
    #: while nothing of ours is running. Callers branch on this flag and never
    #: on the broker's type: a broker that gains stops later then needs no
    #: change at any call site, and one that loses them degrades to our own
    #: polled stop by flipping a single attribute.
    supports_broker_stops: bool = False

    @abstractmethod
    def place_order(self, request: OrderRequest, db: Session) -> OrderResult:
        """Submit an order. Paper fills it synchronously; live returns PENDING."""

    @abstractmethod
    def cancel_order(self, broker_order_id: str, db: Session) -> bool: ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str, db: Session) -> OrderResult | None: ...

    @abstractmethod
    def get_positions(self, db: Session) -> list[BrokerPosition]: ...

    @abstractmethod
    def get_margins(self, db: Session) -> BrokerMargins: ...

    @abstractmethod
    def get_ltp(self, symbols: list[str], db: Session) -> dict[str, float]:
        """Last traded price per `EXCHANGE:SYMBOL` key.

        Live prices are real in both modes — only order execution is simulated.
        """

    @abstractmethod
    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        db: Session,
    ) -> list[dict]: ...

    # -------------------------------------------------------- broker stops --
    # Concrete no-ops, not abstract methods: a broker that cannot hold stops
    # is the normal case, not an incomplete implementation, and making these
    # abstract would force every such broker to write the same four stubs.
    # They are safe to call unconditionally — a caller that has already
    # checked `supports_broker_stops` loses nothing, and one that forgets gets
    # "there is no stop" rather than an AttributeError mid-exit.

    def place_stop(self, request: StopRequest, db: Session) -> BrokerStop | None:
        """None means this broker holds no stops — ours stays the only one."""
        return None

    def modify_stop(
        self, broker_stop_id: str, trigger_price: float, quantity: int | None, db: Session
    ) -> BrokerStop | None:
        return None

    def cancel_stop(self, broker_stop_id: str, db: Session) -> bool | None:
        """None distinguishes "this broker has no stops" from a cancel that
        was genuinely attempted and refused (False)."""
        return None

    def list_stops(self, db: Session) -> list[BrokerStop]:
        return []
