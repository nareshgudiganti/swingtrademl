"""Paper broker — simulated execution against real, live market prices.

This is what runs for the first six months. Design rules it follows:

* Prices are real. Only the fill is simulated. A backtest that invents prices
  proves nothing; this consumes the same live quotes the live broker would.
* Costs are charged. Slippage, brokerage and statutory charges are deducted on
  every fill. A cost-free simulation reliably overstates returns, and swing
  strategies with modest edges are exactly where that illusion bites.
* Fills are adverse. Buys fill above the quote, sells below, by the configured
  slippage. Simulated fills should be pessimistic, never optimistic.
* Cash is finite. Orders are rejected when virtual cash runs out, so position
  sizing gets tested rather than assumed.

Virtual cash is not stored in its own table: it is derived from the starting
capital and the realised cash flows of every paper order. That keeps a single
source of truth and makes the balance reproducible from the order log alone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.brokers.base import (
    Broker,
    BrokerMargins,
    BrokerPosition,
    OrderRequest,
    OrderResult,
)
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import (
    OrderStatus,
    OrderType,
    PositionStatus,
    TradingMode,
    TransactionType,
)
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Candle, Instrument, Quote
from swing_trade_ml.db.models.trading import Order, Position

log = get_logger(__name__)

BPS = 10_000.0


class PaperBroker(Broker):
    mode = TradingMode.PAPER

    # ------------------------------------------------------------ pricing --

    def _reference_price(self, tradingsymbol: str, exchange: str, db: Session) -> float | None:
        """Best available current price, most to least fresh.

        Falls back through live quote -> cached quote row -> last candle close
        so a paper fill still happens outside market hours or when the Kite
        session has lapsed, instead of silently dropping signals.
        """
        symbol_key = f"{exchange}:{tradingsymbol}"

        if kite_broker.is_authenticated:
            try:
                ltp = kite_broker.get_ltp([symbol_key], db)
                if symbol_key in ltp:
                    return float(ltp[symbol_key])
            except Exception as exc:  # noqa: BLE001 — fall through to cached data
                log.warning("paper.ltp.failed", symbol=symbol_key, error=str(exc))

        instrument = db.execute(
            select(Instrument).where(
                Instrument.tradingsymbol == tradingsymbol,
                Instrument.exchange == exchange,
            )
        ).scalar_one_or_none()
        if instrument is None:
            return None

        quote = db.execute(
            select(Quote).where(Quote.instrument_id == instrument.id)
        ).scalar_one_or_none()
        if quote:
            return float(quote.last_price)

        candle = db.execute(
            select(Candle)
            .where(Candle.instrument_id == instrument.id)
            .order_by(Candle.ts.desc())
            .limit(1)
        ).scalar_one_or_none()
        return float(candle.close) if candle else None

    def _apply_slippage(self, price: float, side: TransactionType) -> float:
        """Move the fill against us — buys pay up, sells receive less."""
        delta = price * (settings.PAPER_SLIPPAGE_BPS / BPS)
        return price + delta if side == TransactionType.BUY else price - delta

    def _charges(self, turnover: float) -> tuple[float, float]:
        """(brokerage, taxes) for one executed order.

        Approximates Zerodha's equity-delivery cost stack — STT, exchange
        transaction charges, SEBI fees, stamp duty and GST — with a single
        basis-point figure on turnover. Exact to the rupee it is not; the point
        is that paper P&L is never reported gross.
        """
        brokerage = settings.PAPER_BROKERAGE_PER_ORDER
        taxes = turnover * (settings.PAPER_TAX_BPS / BPS)
        return brokerage, taxes

    # ------------------------------------------------------------ balance --

    def get_available_cash(self, db: Session) -> float:
        """Starting capital, less net cash consumed by every filled paper order.

        Buys consume cash and charges; sells return it. Derived on read so the
        balance can never drift out of sync with the order log.
        """
        rows = db.execute(
            select(
                Order.transaction_type,
                func.sum(Order.average_price * Order.filled_quantity),
                func.sum(Order.brokerage + Order.taxes),
            )
            .where(
                Order.mode == TradingMode.PAPER,
                Order.status == OrderStatus.COMPLETE,
            )
            .group_by(Order.transaction_type)
        ).all()

        cash = settings.PAPER_STARTING_CAPITAL
        for side, gross, charges in rows:
            gross = float(gross or 0.0)
            charges = float(charges or 0.0)
            cash += -gross - charges if side == TransactionType.BUY else gross - charges
        return cash

    # ------------------------------------------------------------- orders --

    def place_order(self, request: OrderRequest, db: Session) -> OrderResult:
        """Simulate an immediate fill, subject to price availability and cash."""
        ref_price = self._reference_price(request.tradingsymbol, request.exchange, db)
        if ref_price is None:
            msg = f"No price available for {request.exchange}:{request.tradingsymbol}"
            log.warning("paper.order.no_price", symbol=request.tradingsymbol)
            return OrderResult(
                broker_order_id=f"PAPER-{uuid.uuid4().hex[:12].upper()}",
                status=OrderStatus.REJECTED,
                message=msg,
            )

        # A limit order that the market has not reached does not fill. Modelling
        # this matters: treating limits as instant fills is the single most
        # common way a paper system flatters itself.
        if request.order_type == OrderType.LIMIT and request.price is not None:
            unreachable = (
                request.transaction_type == TransactionType.BUY and ref_price > request.price
            ) or (request.transaction_type == TransactionType.SELL and ref_price < request.price)
            if unreachable:
                return OrderResult(
                    broker_order_id=f"PAPER-{uuid.uuid4().hex[:12].upper()}",
                    status=OrderStatus.OPEN,
                    message=f"Limit {request.price} not reached (market {ref_price})",
                )
            fill_price = request.price
        else:
            fill_price = self._apply_slippage(ref_price, request.transaction_type)

        turnover = fill_price * request.quantity
        brokerage, taxes = self._charges(turnover)

        if request.transaction_type == TransactionType.BUY:
            required = turnover + brokerage + taxes
            available = self.get_available_cash(db)
            if required > available:
                msg = f"Insufficient paper cash: need {required:,.2f}, have {available:,.2f}"
                log.warning(
                    "paper.order.insufficient_funds",
                    symbol=request.tradingsymbol,
                    required=round(required, 2),
                    available=round(available, 2),
                )
                return OrderResult(
                    broker_order_id=f"PAPER-{uuid.uuid4().hex[:12].upper()}",
                    status=OrderStatus.REJECTED,
                    message=msg,
                )

        order_id = f"PAPER-{uuid.uuid4().hex[:12].upper()}"
        log.info(
            "paper.order.filled",
            order_id=order_id,
            symbol=request.tradingsymbol,
            side=request.transaction_type.value,
            qty=request.quantity,
            price=round(fill_price, 2),
        )
        return OrderResult(
            broker_order_id=order_id,
            status=OrderStatus.COMPLETE,
            filled_quantity=request.quantity,
            average_price=round(fill_price, 2),
            brokerage=round(brokerage, 2),
            taxes=round(taxes, 2),
            slippage=round(abs(fill_price - ref_price) * request.quantity, 2),
            message="Simulated fill (paper mode)",
        )

    def cancel_order(self, broker_order_id: str, db: Session) -> bool:
        order = db.execute(
            select(Order).where(
                Order.broker_order_id == broker_order_id,
                Order.mode == TradingMode.PAPER,
            )
        ).scalar_one_or_none()
        # Only resting orders can be cancelled; a simulated fill is already final.
        if order is None or order.status not in (OrderStatus.PENDING, OrderStatus.OPEN):
            return False
        order.status = OrderStatus.CANCELLED
        db.commit()
        return True

    def get_order_status(self, broker_order_id: str, db: Session) -> OrderResult | None:
        order = db.execute(
            select(Order).where(
                Order.broker_order_id == broker_order_id,
                Order.mode == TradingMode.PAPER,
            )
        ).scalar_one_or_none()
        if order is None:
            return None
        return OrderResult(
            broker_order_id=broker_order_id,
            status=OrderStatus(order.status),
            filled_quantity=order.filled_quantity,
            average_price=order.average_price,
            brokerage=order.brokerage,
            taxes=order.taxes,
        )

    # ---------------------------------------------------------- portfolio --

    def get_positions(self, db: Session) -> list[BrokerPosition]:
        positions = (
            db.execute(
                select(Position).where(
                    Position.mode == TradingMode.PAPER,
                    Position.status == PositionStatus.OPEN,
                )
            )
            .scalars()
            .all()
        )

        result: list[BrokerPosition] = []
        for pos in positions:
            instrument = db.get(Instrument, pos.instrument_id)
            if instrument is None:
                continue
            last = pos.current_price or pos.entry_price
            result.append(
                BrokerPosition(
                    tradingsymbol=instrument.tradingsymbol,
                    exchange=instrument.exchange,
                    quantity=pos.quantity,
                    average_price=pos.entry_price,
                    last_price=last,
                    pnl=(last - pos.entry_price) * pos.quantity,
                )
            )
        return result

    def get_margins(self, db: Session) -> BrokerMargins:
        cash = self.get_available_cash(db)
        used = sum(p.entry_price * p.quantity for p in self._open_positions(db))
        return BrokerMargins(available_cash=cash, used_margin=used, total=cash + used)

    def _open_positions(self, db: Session) -> list[Position]:
        return list(
            db.execute(
                select(Position).where(
                    Position.mode == TradingMode.PAPER,
                    Position.status == PositionStatus.OPEN,
                )
            )
            .scalars()
            .all()
        )

    # --------------------------------------------------------- marketdata --
    # Market data is never simulated — it is delegated to the real Kite client.

    def get_ltp(self, symbols: list[str], db: Session) -> dict[str, float]:
        if kite_broker.is_authenticated:
            try:
                return kite_broker.get_ltp(symbols, db)
            except Exception as exc:  # noqa: BLE001
                log.warning("paper.ltp.delegate_failed", error=str(exc))

        # Cached fallback so the dashboard still renders without a Kite session
        out: dict[str, float] = {}
        for key in symbols:
            exchange, _, tradingsymbol = key.partition(":")
            price = self._reference_price(tradingsymbol, exchange, db)
            if price is not None:
                out[key] = price
        return out

    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        db: Session,
    ) -> list[dict]:
        return kite_broker.get_historical_data(instrument_token, from_date, to_date, interval, db)

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)


paper_broker = PaperBroker()
