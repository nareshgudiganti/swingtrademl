"""Telegram configuration checks and manual sends."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.core.config import settings
from swing_trade_ml.notifications import notifier
from swing_trade_ml.schemas import MessageResponse, TelegramTestResponse
from swing_trade_ml.services import portfolio as portfolio_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/telegram/status", response_model=TelegramTestResponse)
async def telegram_status() -> TelegramTestResponse:
    """Verify the bot token and report which chat messages will go to."""
    result = await notifier.test_connection()
    return TelegramTestResponse(**result)


@router.post("/telegram/test", response_model=MessageResponse)
async def telegram_test() -> MessageResponse:
    """Send a test message — confirms the token, the chat id, and delivery."""
    if not settings.TELEGRAM_ENABLED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "TELEGRAM_ENABLED is false — set it to true in .env and restart",
        )

    sent = await notifier.send(
        "✅ <b>Swing Trade ML</b>\n\nTelegram notifications are wired up correctly.",
        "system",
    )
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Send failed — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID, and make "
            "sure you have messaged the bot at least once.",
        )
    return MessageResponse(message="Test message sent")


@router.post("/telegram/daily-summary", response_model=MessageResponse)
async def send_daily_summary(db: DbSession) -> MessageResponse:
    """Push the end-of-day digest now instead of waiting for 16:00 IST."""
    stats = portfolio_service.performance_stats(db)
    sent = await notifier.notify_daily_summary(stats, stats["mode"])
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Send failed — check GET /notifications/telegram/status",
        )
    return MessageResponse(message="Daily summary sent")
