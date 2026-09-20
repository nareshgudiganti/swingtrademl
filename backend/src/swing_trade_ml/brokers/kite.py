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

    def auto_login(self, db: Session) -> BrokerSession:
        """Unattended login using Zerodha credentials + TOTP, for the daily
        06:10 IST scheduled job — the manual `/kite/login` flow this mirrors
        exists because access tokens expire every day, and this exists so a
        human doesn't have to remember to repeat it every trading morning.

        Zerodha's Connect (OAuth-style) flow has no official
        password-in/token-out API — it's designed to run in a browser. This
        drives the same web endpoints their login page itself calls
        (undocumented, but this is the standard pattern used for Kite
        automation): POST credentials, POST the TOTP code, then walk the
        Connect authorize redirect by hand to pull `request_token` out of the
        Location header — never letting `requests` actually follow the final
        hop, since that URL is our own public callback and would attempt a
        second, redundant `generate_session` call against an already-used
        request_token (Zerodha request_tokens are single-use).
        """
        if not (settings.KITE_USER_ID and settings.KITE_PASSWORD and settings.KITE_TOTP_SECRET):
            raise RuntimeError(
                "Kite auto-login is not configured — set KITE_USER_ID, KITE_PASSWORD, "
                "and KITE_TOTP_SECRET to enable it."
            )

        import pyotp
        import requests

        http = requests.Session()

        login_resp = http.post(
            "https://kite.zerodha.com/api/login",
            data={"user_id": settings.KITE_USER_ID, "password": settings.KITE_PASSWORD},
            timeout=15,
        )
        login_resp.raise_for_status()
        login_data = login_resp.json()["data"]
        request_id = login_data["request_id"]

        # Zerodha reports which 2FA types this login attempt will actually
        # accept — "External TOTP enabled" in profile settings does not
        # guarantee "totp" is one of them (observed: an account with it
        # enabled still offered only ["app_code", "sms"]). Failing here with
        # a clear message beats a bare 400 from the next call.
        available_types = login_data.get("twofa_types", [])
        if "totp" not in available_types:
            raise KiteAuthError(
                "Kite auto-login: this account's login step does not currently accept "
                f"a TOTP code (available: {available_types}). 'External TOTP' showing "
                "enabled in your Kite profile settings is not the same as it being the "
                "account's active login method — check Zerodha's security settings for "
                "an option to make External TOTP the primary 2FA method, or auto-login "
                "cannot proceed and the manual login flow must be used instead."
            )

        totp_code = pyotp.TOTP(settings.KITE_TOTP_SECRET).now()
        twofa_resp = http.post(
            "https://kite.zerodha.com/api/twofa",
            data={
                "user_id": settings.KITE_USER_ID,
                "request_id": request_id,
                "twofa_value": totp_code,
                "twofa_type": "totp",
            },
            timeout=15,
        )
        twofa_resp.raise_for_status()

        request_token = self._walk_authorize_redirect(http)
        return self.complete_login(request_token, db)

    def login_diagnostics(self) -> dict[str, object]:
        """Probe auto-login's first step and report why it would fail, without
        completing a login or submitting a TOTP code.

        This exists because the only other way to find out whether auto-login
        works was to wait for the 06:10 cron and read the Telegram error — a
        24-hour feedback loop for a config typo. `twofa_types` in particular is
        only knowable by asking Zerodha, and it is the single most common
        reason auto-login fails on an otherwise correct setup.

        It does POST the user id and password (one real authentication attempt)
        but stops before `/api/twofa`, so a wrong TOTP secret cannot contribute
        to a lockout here. Never returns or logs the secret itself.
        """
        result: dict[str, object] = {
            "user_id_set": bool(settings.KITE_USER_ID),
            "password_set": bool(settings.KITE_PASSWORD),
            "totp_secret_set": bool(settings.KITE_TOTP_SECRET),
            "api_key_set": bool(settings.KITE_API_KEY),
            "api_secret_set": bool(settings.KITE_API_SECRET),
        }

        if not (settings.KITE_USER_ID and settings.KITE_PASSWORD and settings.KITE_TOTP_SECRET):
            result["ok"] = False
            result["reason"] = (
                "Auto-login is not configured. Set KITE_USER_ID, KITE_PASSWORD and "
                "KITE_TOTP_SECRET. Note job_kite_auto_login returns silently when these "
                "are unset, so an unconfigured environment produces no error at all."
            )
            return result

        # Validate the secret locally first — a malformed secret is worth
        # catching before spending an authentication attempt on it.
        try:
            import pyotp

            code = pyotp.TOTP(settings.KITE_TOTP_SECRET).now()
            result["totp_generates"] = True
            result["totp_code_length"] = len(code)
        except ImportError:
            result["ok"] = False
            result["reason"] = "pyotp is not installed in this environment."
            return result
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["totp_generates"] = False
            result["reason"] = f"KITE_TOTP_SECRET is not a valid base32 TOTP secret: {exc}"
            return result

        import requests

        try:
            resp = requests.post(
                "https://kite.zerodha.com/api/login",
                data={
                    "user_id": settings.KITE_USER_ID,
                    "password": settings.KITE_PASSWORD,
                },
                timeout=15,
            )
        except Exception as exc:  # noqa: BLE001
            result["ok"] = False
            result["reason"] = f"Could not reach kite.zerodha.com: {exc}"
            return result

        result["login_http_status"] = resp.status_code
        if resp.status_code != 200:
            result["ok"] = False
            result["reason"] = (
                f"Zerodha rejected the user id / password step (HTTP {resp.status_code}). "
                "Check KITE_USER_ID and KITE_PASSWORD."
            )
            return result

        data = resp.json().get("data", {})
        twofa_types = data.get("twofa_types", [])
        result["twofa_types"] = twofa_types
        result["totp_available"] = "totp" in twofa_types
        result["request_id_received"] = bool(data.get("request_id"))

        if "totp" not in twofa_types:
            result["ok"] = False
            result["reason"] = (
                f"Credentials accepted, but this account's login step offers {twofa_types} "
                "and not 'totp'. 'External TOTP' enabled in Kite profile settings is not "
                "the same as it being the account's active login method — auto-login "
                "cannot proceed until TOTP is the primary 2FA method."
            )
            return result

        result["ok"] = True
        result["reason"] = (
            "Credentials accepted and TOTP is an available 2FA method. Auto-login should "
            "work — run without --check to complete a real login."
        )
        return result

    def _walk_authorize_redirect(self, http, max_hops: int = 5) -> str:
        from urllib.parse import parse_qs, urlparse

        response = http.get(self.login_url(), allow_redirects=False, timeout=15)
        for _ in range(max_hops):
            location = response.headers.get("Location")
            if not location:
                break
            token = parse_qs(urlparse(location).query).get("request_token")
            if token:
                return token[0]
            response = http.get(location, allow_redirects=False, timeout=15)
        raise KiteAuthError(
            "Kite auto-login: no request_token found in the authorize redirect chain "
            "— Zerodha may be asking for a fresh app authorization or CAPTCHA."
        )

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

    @staticmethod
    def _is_token_rejected(exc: Exception) -> bool:
        """True when Zerodha rejected the token itself, rather than the request.

        Matched on the message because kiteconnect raises TokenException for
        several unrelated conditions and a plain KiteException in others; the
        wording of this one is stable and unambiguous.
        """
        return "incorrect `api_key` or `access_token`" in str(exc).lower()

    def reauth_and_retry(self, db: Session, call, *args, **kwargs):
        """Run a Kite call; on a rejected token, log in again and retry once.

        Zerodha invalidates an existing Kite Connect access_token when the same
        account signs in to kite.zerodha.com — so simply opening the Kite app
        to check a price kills this app's token mid-session. Observed twice:
        tokens minted by the 06:10 job were dead by early afternoon while a
        freshly minted one worked immediately.

        Waiting for the next 06:10 would leave the rest of the trading day
        blind: no quote refresh, no stop-loss checks, no ingestion. Since
        auto-login is unattended, the honest fix is to just get a new token and
        carry on. Retried exactly once — a second failure is a real problem and
        must surface rather than loop.
        """
        try:
            return call(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not self._is_token_rejected(exc):
                raise
            if not (
                settings.KITE_USER_ID and settings.KITE_PASSWORD and settings.KITE_TOTP_SECRET
            ):
                log.warning("kite.token_rejected.no_autologin")
                raise
            log.warning("kite.token_rejected.reauthenticating")
            self.auto_login(db)
            return call(*args, **kwargs)

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
            # Through reauth_and_retry for the same reason quotes and holdings
            # are: Zerodha kills this token whenever the account opens the Kite
            # app, mid-session and unannounced. Narrow by construction — it
            # re-raises anything that is not a rejected token, and a rejected
            # token is refused before the request is processed, so a retry
            # cannot duplicate an order already resting at the exchange.
            order_id = self.reauth_and_retry(
                db,
                self._kite.place_order,
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
        return self.reauth_and_retry(db, self._kite.holdings)

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
        data = self.reauth_and_retry(db, self._kite.ltp, symbols)
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
        return self.reauth_and_retry(db, self._kite.quote, symbols)

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
        return self.reauth_and_retry(
            db,
            self._kite.historical_data,
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
