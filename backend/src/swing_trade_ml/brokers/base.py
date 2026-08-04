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


class Broker(ABC):
    """Common surface for the paper and live implementations."""

    #: "paper" or "live" — stamped onto every row this broker writes
    mode: str

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
