"""Zerodha Kite Connect broker — the only module that imports `kiteconnect`.

Market data flows through here in both paper and live mode. Order *placement*
is gated behind `settings.is_live_trading`, so even if this broker is somehow
constructed while the safety latches are closed, it refuses to transmit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from swing_trade_ml.brokers.base import (
    Broker,
    BrokerMargins,
    BrokerPosition,
    OrderRequest,
    OrderResult,
)
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import OrderStatus, TradingMode
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.session import BrokerSession

log = get_logger(__name__)


class KiteAuthError(RuntimeError):
    """Raised when no valid access token is loaded.

    Distinct from a generic error because the fix is always the same and always
    manual: a human must complete the Kite login flow for today.
    """


class KiteBroker(Broker):
    mode = TradingMode.LIVE

    def __init__(self) -> None:
        self._kite = KiteConnect(api_key=settings.KITE_API_KEY)
        self._token_loaded = False
        self._loaded_session_id: int | None = None

    # ------------------------------------------------------------- session --

    @property
    def client(self) -> KiteConnect:
        return self._kite

    @property
    def is_authenticated(self) -> bool:
        return self._token_loaded

    @property
    def loaded_session_id(self) -> int | None:
        """Which BrokerSession row is currently live in this process — lets a
        caller (job_refresh_quotes) detect "just picked up a new login" vs.
        "still the same session as last tick" without reaching into internals.
        """
        return self._loaded_session_id

    def login_url(self) -> str:
        return self._kite.login_url()

    def complete_login(self, request_token: str, db: Session) -> BrokerSession:
        """Exchange a request_token for the day's access token and persist it."""
        data = self._kite.generate_session(request_token, api_secret=settings.KITE_API_SECRET)

        # Retire older sessions so "the current token" is never ambiguous.
        db.query(BrokerSession).filter(BrokerSession.is_active.is_(True)).update(
            {"is_active": False}
        )

        session = BrokerSession(
            broker="zerodha",
            kite_user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            access_token=data["access_token"],
            public_token=data.get("public_token"),
            refresh_token=data.get("refresh_token"),
            is_active=True,
            # Kite expires tokens at ~06:00 IST the next day.
            expires_at=(datetime.now(UTC) + timedelta(days=1)).replace(
                hour=0, minute=30, second=0, microsecond=0
            ),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        self._kite.set_access_token(data["access_token"])
        self._token_loaded = True
        log.info("kite.login.success", user_id=data.get("user_id"))
        return session

    def load_session(self, db: Session) -> bool:
        """Restore the newest active token — called at startup, and cheaply
        re-checked on every refresh_quotes tick (job_refresh_quotes) so a
        login completed on another process (the api container, which serves
        the OAuth callback) reaches this one within a minute instead of
        requiring a manual restart to notice it. Skips the redundant
        set_access_token call when the same session is already loaded.

        Returns False if there is none or it has expired — the caller reports
        that as a degraded-but-running state rather than failing the boot,
        since historical data and the dashboard still work without a token.
        """
        stmt = (
            select(BrokerSession)
            .where(BrokerSession.is_active.is_(True))
            .order_by(BrokerSession.created_at.desc())
            .limit(1)
        )
        session = db.execute(stmt).scalar_one_or_none()
        if not session:
            if self._token_loaded:
                log.warning("kite.session.none")
            self._token_loaded = False
            self._loaded_session_id = None
            return False

        if session.expires_at and session.expires_at < datetime.now(UTC):
            log.warning("kite.session.expired", expired_at=str(session.expires_at))
            session.is_active = False
            db.commit()
            self._token_loaded = False
            self._loaded_session_id = None
            return False

        if self._token_loaded and self._loaded_session_id == session.id:
            return True

        self._kite.set_access_token(session.access_token)
        self._token_loaded = True
        self._loaded_session_id = session.id
        log.info("kite.session.restored", user_id=session.kite_user_id, session_id=session.id)
        return True

    def _require_auth(self) -> None:
        if not self._token_loaded:
            raise KiteAuthError("No active Kite session — complete the login flow at /api/v1/auth/kite/login")

    # --------------------------------------------------------------- orders --

    def place_order(self, request: OrderRequest, db: Session) -> OrderResult:
        # Belt and braces: the factory should never hand out a live broker while
        # the latches are closed, but an order that reaches the exchange cannot
        # be un-sent, so the check is repeated at the point of no return.
        if not settings.is_live_trading:
            raise RuntimeError(
                "Refusing to place a live order: requires TRADING_MODE=live AND "
                "ALLOW_LIVE_TRADING=true"
            )
        self._require_auth()

        try:
            order_id = self._kite.place_order(
                variety=self._kite.VARIETY_REGULAR,
                exchange=request.exchange,
                tradingsymbol=request.tradingsymbol,
                transaction_type=request.transaction_type.value,
                quantity=request.quantity,
                order_type=request.order_type.value,
                product=request.product.value,
                price=request.price,
                trigger_price=request.trigger_price,
                tag=request.tag,
            )
        except KiteException as exc:
            log.error("kite.order.rejected", symbol=request.tradingsymbol, error=str(exc))
            return OrderResult(
                broker_order_id="",
                status=OrderStatus.REJECTED,
                message=str(exc),
            )

        log.info("kite.order.placed", order_id=order_id, symbol=request.tradingsymbol)
        # Kite is asynchronous: placement only means accepted. The reconciliation
        # job polls get_order_status until it reaches a terminal state.
        return OrderResult(broker_order_id=str(order_id), status=OrderStatus.PENDING)

    def cancel_order(self, broker_order_id: str, db: Session) -> bool:
        self._require_auth()
        try:
            self._kite.cancel_order(variety=self._kite.VARIETY_REGULAR, order_id=broker_order_id)
            return True
        except KiteException as exc:
            log.error("kite.order.cancel_failed", order_id=broker_order_id, error=str(exc))
            return False

    def get_order_status(self, broker_order_id: str, db: Session) -> OrderResult | None:
        self._require_auth()
        try:
            history = self._kite.order_history(order_id=broker_order_id)
        except KiteException as exc:
            log.error("kite.order.history_failed", order_id=broker_order_id, error=str(exc))
            return None
        if not history:
            return None

        latest = history[-1]
        return OrderResult(
            broker_order_id=broker_order_id,
            status=OrderStatus(latest.get("status", "PENDING")),
            filled_quantity=latest.get("filled_quantity", 0) or 0,
            average_price=latest.get("average_price"),
            message=latest.get("status_message"),
            raw=latest,
        )

    # ----------------------------------------------------------- portfolio --

    def get_positions(self, db: Session) -> list[BrokerPosition]:
        self._require_auth()
        data = self._kite.positions()
        return [
            BrokerPosition(
                tradingsymbol=p["tradingsymbol"],
                exchange=p["exchange"],
                quantity=p["quantity"],
                average_price=p["average_price"],
                last_price=p["last_price"],
                pnl=p["pnl"],
            )
            for p in data.get("net", [])
            if p["quantity"] != 0
        ]

    def get_holdings(self, db: Session) -> list[dict]:
        self._require_auth()
        return self._kite.holdings()

    def get_margins(self, db: Session) -> BrokerMargins:
        self._require_auth()
        m = self._kite.margins()
        equity = m.get("equity", {})
        available = equity.get("available", {}).get("live_balance", 0.0)
        used = equity.get("utilised", {}).get("debits", 0.0)
        return BrokerMargins(available_cash=available, used_margin=used, total=available + used)

    # ---------------------------------------------------------- marketdata --

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(KiteException),
        reraise=True,
    )
    def get_ltp(self, symbols: list[str], db: Session) -> dict[str, float]:
        self._require_auth()
        if not symbols:
            return {}
        data = self._kite.ltp(symbols)
        return {k: v["last_price"] for k, v in data.items()}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(KiteException),
        reraise=True,
    )
    def get_quote(self, symbols: list[str], db: Session) -> dict:
        self._require_auth()
        if not symbols:
            return {}
        return self._kite.quote(symbols)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(KiteException),
        reraise=True,
    )
    def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str,
        db: Session,
    ) -> list[dict]:
        self._require_auth()
        return self._kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=False,
            oi=False,
        )

    def get_instruments(self, exchange: str = "NSE") -> list[dict]:
        """The full tradable list. Public endpoint — needs no access token."""
        return self._kite.instruments(exchange)


#: Module-level singleton. KiteConnect holds the access token as instance
#: state, so every caller must share one object or only the instance that
#: performed the login would be authenticated.
kite_broker = KiteBroker()
