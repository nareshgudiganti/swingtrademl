"""Telegram notifications.

Every send is best-effort: a notification failure must never abort a trade or
crash a scheduled job. Failures are logged and swallowed at the call boundary.

Messages use HTML rather than Markdown parse mode — Telegram's Markdown chokes
on stock symbols containing underscores (`M_M`, `BAJAJ_AUTO`), silently
rejecting the whole message.
"""

from __future__ import annotations

import asyncio
import html
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import NotificationEvent
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.notifications import failure_log
from swing_trade_ml.notifications.alert_policy import DAILY_SUMMARY

log = get_logger(__name__)

API_BASE = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# Telegram rejects messages over 4096 characters outright
MAX_MESSAGE_LENGTH = 4000


# Urgent alerts (no `kind`) that fail for a temporary reason are retried twice, at about 30 s and
# about 2 min after the first attempt (owner criteria, #217 / #358).
RETRY_AT_SECONDS = (30.0, 120.0)


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status: int | None = None
    permanent: bool = False
    reason: str = ""


# The outcome of the latest `_post` in this task, so `send` can tell a temporary failure from a
# permanent one without changing `_post`'s plain True/False answer.
_last_result: ContextVar[SendResult | None] = ContextVar("telegram_last_result", default=None)


def _sleep(seconds: float):
    """Indirection so tests can run the retry timings without really waiting."""
    return asyncio.sleep(seconds)


def _spawn(make_coro) -> None:
    """Run the pending retries off to the side so a trade or scheduler job never waits minutes on
    Telegram. A daemon thread because send_sync callers run in short-lived event loops."""
    threading.Thread(target=lambda: asyncio.run(make_coro()), name="telegram-retry", daemon=True).start()


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


class TelegramNotifier:
    def __init__(self) -> None:
        self._token = settings.TELEGRAM_BOT_TOKEN
        self._chat_id = settings.TELEGRAM_CHAT_ID

    @property
    def enabled(self) -> bool:
        if settings.ENVIRONMENT != "production" and not settings.TELEGRAM_SEND_OUTSIDE_PRODUCTION:
            return False
        return bool(settings.TELEGRAM_ENABLED and self._token and self._chat_id)

    def can_deliver(
        self, event: NotificationEvent | str = NotificationEvent.SIGNAL, kind: str | None = None
    ) -> bool:
        """False when nothing of this kind can reach the chat at all. A caller that retries a failed send
        uses it to tell "try again" from "never". A safety alert (no `kind`) ignores the owner's event list and only
        needs Telegram to be on and configured; a switchable kind also honours the list."""
        if kind is None:
            return self.enabled
        return self._should_send(event, kind)

    def _should_send(self, event: NotificationEvent | str, kind: str | None = None) -> bool:
        """Telegram must be on. Then a message tagged with a switchable `kind` (informational) follows the
        TELEGRAM_NOTIFY_ON list; a message with NO kind is a safety alert (sell, stop-loss, real-money order,
        risk stop, login or system problem) or untagged, and is sent whatever that list says (#482): a safety
        alert must never depend on a server setting that leaves a category out."""
        if not self.enabled:
            return False
        if kind is None:
            return True
        return str(event).lower() in settings.telegram_events

    async def send(
        self,
        text: str,
        event: NotificationEvent | str = NotificationEvent.SYSTEM,
        kind: str | None = None,
    ) -> bool:
        """Send one message. `kind` tags an informational message with one of the
        owner's switchable alert types (notifications/alert_policy.py); such a
        message may be dropped (type switched off) or held for quiet hours or the
        digest. A message with no kind is safety-critical or untagged and is
        always sent at once. Held counts as True: it will be delivered."""
        if not self._should_send(event, kind):
            # The key must be `event_type`, never `event`: structlog reserves
            # `event` for the log message itself, so passing it as a keyword
            # raises TypeError — which would abort every signal that tries to
            # notify while notifications are disabled.
            log.debug("telegram.skipped", event_type=str(event), enabled=self.enabled)
            return False

        if kind is not None:
            from swing_trade_ml.services import alert_settings

            # The settings read is a short blocking database call; keep it off the event loop.
            decision = await asyncio.to_thread(alert_settings.gate, kind, text)
            if decision == "drop":
                log.info("telegram.switched_off", kind=kind)
                return False
            if decision == "held":
                log.info("telegram.held", kind=kind)
                return True
            return await self._post(text)

        # Urgent (no kind): a failure is recorded and, if temporary, retried in the background.
        _last_result.set(None)
        if await self._post(text):
            return True
        self._after_first_failure(text, event)
        return False

    async def _attempt(self, text: str) -> SendResult:
        payload = {
            "chat_id": self._chat_id,
            "text": text[:MAX_MESSAGE_LENGTH],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(
                    f"{API_BASE}/bot{self._token}/sendMessage", json=payload
                )
            if response.status_code != 200:
                log.error(
                    "telegram.send_failed",
                    status=response.status_code,
                    body=response.text[:300],
                )
                code = response.status_code
                # 429 and 5xx pass with time; anything else (bad token, blocked chat, bad request)
                # fails the same way every time.
                transient = code == 429 or code >= 500
                return SendResult(False, code, permanent=not transient, reason=f"HTTP {code}")
            return SendResult(True, 200)
        except Exception as exc:  # noqa: BLE001 — never let notification failure propagate
            # Class name only: an httpx error message can carry the request URL, which holds the token.
            log.error("telegram.send_error", error_kind=type(exc).__name__)
            return SendResult(False, None, reason=f"network error ({type(exc).__name__})")

    async def _post(self, text: str) -> bool:
        result = await self._attempt(text)
        _last_result.set(result)
        return result.ok

    def _after_first_failure(self, text: str, event: NotificationEvent | str) -> None:
        """An urgent alert's first attempt failed: record it, then retry or stop."""
        result = _last_result.get()
        if result is None or result.ok:
            return
        event_name = str(event).lower()
        if result.permanent:
            failure_log.record(
                failure_log.PERMANENT,
                event=event_name,
                status=result.status,
                reason=result.reason,
                attempts=1,
            )
            log.warning("telegram.alert_failed_permanently", event_type=event_name, status=result.status)
            return
        entry_id = failure_log.record(
            failure_log.RETRYING, event=event_name, status=result.status, reason=result.reason, attempts=1
        )
        _spawn(lambda: self.retry_urgent(text, event_name, entry_id))

    async def retry_urgent(self, text: str, event_name: str, entry_id: str, sleep=None) -> bool:
        """Two more tries, at about 30 s and 2 min after the first. Quiet on success; one warning
        when the retries are used up; stops at once on a permanent refusal."""
        sleep = sleep or _sleep
        waited = 0.0
        attempts = 1
        result = SendResult(False)
        for at in RETRY_AT_SECONDS:
            await sleep(at - waited)
            waited = at
            attempts += 1
            result = await self._attempt(text)
            if result.ok:
                failure_log.clear(entry_id)
                log.info("telegram.retry_succeeded", event_type=event_name, attempts=attempts)
                return True
            state = failure_log.PERMANENT if result.permanent else failure_log.RETRYING
            failure_log.record(
                state,
                event=event_name,
                status=result.status,
                reason=result.reason,
                attempts=attempts,
                entry_id=entry_id,
            )
            if result.permanent:
                log.warning("telegram.alert_failed_permanently", event_type=event_name, status=result.status)
                return False
        failure_log.record(
            failure_log.GAVE_UP,
            event=event_name,
            status=result.status,
            reason=result.reason,
            attempts=attempts,
            entry_id=entry_id,
        )
        log.warning("telegram.alert_not_delivered", event_type=event_name, attempts=attempts)
        return False

    def deliver_sync(self, text: str) -> bool:
        """Send already-held messages (the digest), past the alert settings. Blocking, for
        scheduler threads. False while Telegram is switched off, so nothing is marked sent."""
        if not self.enabled:
            return False
        try:
            return asyncio.run(self._post(text))
        except RuntimeError as exc:
            log.error("telegram.sync_in_async_context", error=str(exc))
            return False

    def send_sync(
        self,
        text: str,
        event: NotificationEvent | str = NotificationEvent.SYSTEM,
        kind: str | None = None,
    ) -> bool:
        """Blocking wrapper for APScheduler jobs, which run in worker threads.

        `asyncio.run` is safe here precisely because those threads have no
        running event loop. Calling this from async code would raise, which is
        the desired failure — use `send` there instead.
        """
        try:
            return asyncio.run(self.send(text, event, kind=kind))
        except RuntimeError as exc:
            log.error("telegram.sync_in_async_context", error=str(exc))
            return False

    async def test_connection(self) -> dict[str, Any]:
        """Verify the token and report the bot identity — used by the setup endpoint."""
        if not self._token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set"}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(f"{API_BASE}/bot{self._token}/getMe")
            data = response.json()
            if not data.get("ok"):
                return {"ok": False, "error": data.get("description", "Unknown error")}
            return {"ok": True, "bot": data["result"].get("username"), "chat_id": self._chat_id}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ---------------------------------------------------------- templates --

    async def notify_signal(
        self,
        symbol: str,
        signal: str,
        price: float,
        confidence: float | None,
        reason: str,
        strategy: str,
        quantity: int | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        mode: str = "paper",
    ) -> bool:
        icon = {"BUY": "🟢", "SELL": "🔴", "EXIT": "🟠"}.get(signal.upper(), "⚪")
        # The mode banner is on every trade message on purpose: the one thing
        # that must never be ambiguous is whether real money moved.
        badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"

        lines = [
            f"{icon} <b>{_esc(signal.upper())} · {_esc(symbol)}</b>  ({badge})",
            "",
            f"Price: <b>₹{price:,.2f}</b>",
        ]
        if quantity:
            lines.append(f"Quantity: <b>{quantity:,}</b>  (₹{price * quantity:,.0f})")
        if confidence is not None:
            lines.append(f"Confidence: <b>{confidence:.1%}</b>")
        if stop_loss:
            lines.append(f"Stop loss: ₹{stop_loss:,.2f}  ({(stop_loss / price - 1):+.1%})")
        if take_profit:
            lines.append(f"Target: ₹{take_profit:,.2f}  ({(take_profit / price - 1):+.1%})")
        lines += ["", f"Strategy: <i>{_esc(strategy)}</i>", f"Reason: {_esc(reason)}"]

        return await self.send("\n".join(lines), NotificationEvent.SIGNAL)

    async def notify_fill(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_id: str,
        charges: float = 0.0,
        mode: str = "paper",
    ) -> bool:
        badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
        text = (
            f"✅ <b>FILLED · {_esc(symbol)}</b>  ({badge})\n\n"
            f"{_esc(side)} <b>{quantity:,}</b> @ <b>₹{price:,.2f}</b>\n"
            f"Value: ₹{price * quantity:,.2f}\n"
            f"Charges: ₹{charges:,.2f}\n"
            f"Order: <code>{_esc(order_id)}</code>"
        )
        return await self.send(text, NotificationEvent.FILL)

    async def notify_exit(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        net_pnl: float,
        return_pct: float,
        holding_days: int,
        reason: str,
        mode: str = "paper",
    ) -> bool:
        icon = "🎯" if net_pnl >= 0 else "🛑"
        badge = "📝 PAPER" if mode == "paper" else "💰 <b>LIVE</b>"
        text = (
            f"{icon} <b>CLOSED · {_esc(symbol)}</b>  ({badge})\n\n"
            f"Entry: ₹{entry_price:,.2f} → Exit: ₹{exit_price:,.2f}\n"
            f"Quantity: {quantity:,}\n"
            f"P&amp;L: <b>₹{net_pnl:,.2f}</b>  (<b>{return_pct:+.2%}</b>)\n"
            f"Held: {holding_days} days\n"
            f"Reason: {_esc(reason)}"
        )
        return await self.send(text, NotificationEvent.FILL)

    async def notify_daily_summary(
        self,
        stats: dict[str, Any],
        mode: str = "paper",
        post_exit_watch: list[dict[str, Any]] | None = None,
        kind: str | None = DAILY_SUMMARY,
    ) -> bool:
        badge = "📝 PAPER" if mode == "paper" else "💰 LIVE"
        day_pnl = stats.get("day_pnl", 0.0)
        icon = "📈" if day_pnl >= 0 else "📉"

        lines = [
            f"{icon} <b>Daily Summary — {datetime.now().strftime('%d %b %Y')}</b>  ({badge})",
            "",
            f"Portfolio: <b>₹{stats.get('total_value', 0):,.2f}</b>",
            f"Day P&amp;L: <b>₹{day_pnl:,.2f}</b>  ({stats.get('day_pnl_pct', 0):+.2%})",
            f"Total P&amp;L: ₹{stats.get('total_pnl', 0):,.2f}  ({stats.get('total_return_pct', 0):+.2%})",
            "",
            f"Cash: ₹{stats.get('cash', 0):,.2f}",
            f"Open positions: {stats.get('open_positions', 0)}",
            f"Drawdown: {stats.get('drawdown_pct', 0):.2%}",
        ]

        if stats.get("total_trades"):
            lines += [
                "",
                f"Trades: {stats['total_trades']}  ·  Win rate: {stats.get('win_rate', 0):.1%}",
            ]
        else:
            lines += ["", "Trades: no finished trades yet"]
        if stats.get("signals_today"):
            lines.append(f"Signals today: {stats['signals_today']}")

        top = stats.get("top_movers") or []
        if top:
            lines += ["", "<b>Open positions</b>"]
            for pos in top[:5]:
                arrow = "▲" if pos["pnl_pct"] >= 0 else "▼"
                lines.append(
                    f"  {arrow} {_esc(pos['symbol'])}: {pos['pnl_pct']:+.2%} "
                    f"(₹{pos['pnl']:,.0f})"
                )

        if post_exit_watch:
            lines += ["", "<b>Since we sold</b>"]
            for row in post_exit_watch[:8]:
                arrow = "▲" if row["change_pct"] >= 0 else "▼"
                # From our perspective, not the stock's: a rise since we sold
                # is money left on the table, so it's flagged not celebrated.
                flag = "⚠️" if row["change_pct"] >= 0.03 else ""
                lines.append(
                    f"  {arrow} {_esc(row['symbol'])}: {row['change_pct']:+.2%} since exit "
                    f"({row['days_since_exit']}d ago) {flag}"
                )

        return await self.send("\n".join(lines), NotificationEvent.DAILY_SUMMARY, kind=kind)

    async def notify_error(self, context: str, error: str) -> bool:
        text = (
            f"⚠️ <b>Error — {_esc(context)}</b>\n\n"
            f"<code>{_esc(error[:800])}</code>"
        )
        return await self.send(text, NotificationEvent.ERROR)

    async def notify_system(self, message: str) -> bool:
        return await self.send(f"ℹ️ {_esc(message)}", NotificationEvent.SYSTEM)  # noqa: RUF001


notifier = TelegramNotifier()
