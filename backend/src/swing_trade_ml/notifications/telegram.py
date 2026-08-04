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
from datetime import datetime
from typing import Any

import httpx

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import NotificationEvent
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

API_BASE = "https://api.telegram.org"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
# Telegram rejects messages over 4096 characters outright
MAX_MESSAGE_LENGTH = 4000


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


class TelegramNotifier:
    def __init__(self) -> None:
        self._token = settings.TELEGRAM_BOT_TOKEN
        self._chat_id = settings.TELEGRAM_CHAT_ID

    @property
    def enabled(self) -> bool:
        return bool(settings.TELEGRAM_ENABLED and self._token and self._chat_id)

    def _should_send(self, event: NotificationEvent | str) -> bool:
        event = str(event).lower()
        return self.enabled and event in settings.telegram_events

    async def send(
        self, text: str, event: NotificationEvent | str = NotificationEvent.SYSTEM
    ) -> bool:
        if not self._should_send(event):
            # The key must be `event_type`, never `event`: structlog reserves
            # `event` for the log message itself, so passing it as a keyword
            # raises TypeError — which would abort every signal that tries to
            # notify while notifications are disabled.
            log.debug("telegram.skipped", event_type=str(event), enabled=self.enabled)
            return False

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
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — never let notification failure propagate
            log.error("telegram.send_error", error=str(exc))
            return False

    def send_sync(
        self, text: str, event: NotificationEvent | str = NotificationEvent.SYSTEM
    ) -> bool:
        """Blocking wrapper for APScheduler jobs, which run in worker threads.

        `asyncio.run` is safe here precisely because those threads have no
        running event loop. Calling this from async code would raise, which is
        the desired failure — use `send` there instead.
        """
        try:
            return asyncio.run(self.send(text, event))
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

    async def notify_daily_summary(self, stats: dict[str, Any], mode: str = "paper") -> bool:
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

        return await self.send("\n".join(lines), NotificationEvent.DAILY_SUMMARY)

    async def notify_error(self, context: str, error: str) -> bool:
        text = (
            f"⚠️ <b>Error — {_esc(context)}</b>\n\n"
            f"<code>{_esc(error[:800])}</code>"
        )
        return await self.send(text, NotificationEvent.ERROR)

    async def notify_system(self, message: str) -> bool:
        return await self.send(f"ℹ️ {_esc(message)}", NotificationEvent.SYSTEM)  # noqa: RUF001


notifier = TelegramNotifier()
