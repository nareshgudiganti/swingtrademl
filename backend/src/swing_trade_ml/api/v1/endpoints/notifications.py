"""Telegram configuration checks and manual sends."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from swing_trade_ml.api.deps import DbSession, Principal, actor_name, require_owner
from swing_trade_ml.core.config import settings
from swing_trade_ml.notifications import notifier
from swing_trade_ml.schemas import MessageResponse, TelegramTestResponse
from swing_trade_ml.services import alert_settings, audit
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
    # Asked for by the owner just now, so it goes out at once whatever the alert settings say.
    sent = await notifier.notify_daily_summary(stats, stats["mode"], kind=None)
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Send failed — check GET /notifications/telegram/status",
        )
    return MessageResponse(message="Daily summary sent")


# ------------------------------------------------------------- alert settings (ux3) --
# Which Telegram messages the owner gets, quiet hours and the daily digest. Owner only
# (testers and members are refused). These settings decide only whether and when an
# informational message is sent; sells, real orders, safety stops, login and system
# problems are always sent at once whatever is stored here.

OwnerDep = Annotated[Principal, Depends(require_owner)]


class AlertSettingsUpdate(BaseModel):
    disabled: list[str] = Field(default_factory=list)
    quiet_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    digest_enabled: bool = False
    digest_time: str = "18:00"


@router.get("/alert-settings", response_model=dict)
def get_alert_settings(db: DbSession, _owner: OwnerDep) -> dict[str, Any]:
    return alert_settings.as_dict(alert_settings.load(db), alert_settings.held_count(db))


@router.put("/alert-settings", response_model=dict)
def put_alert_settings(body: AlertSettingsUpdate, db: DbSession, principal: OwnerDep) -> dict[str, Any]:
    try:
        prefs = alert_settings.from_payload(body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    saved = alert_settings.save(db, prefs, by=actor_name(principal))
    result = alert_settings.as_dict(saved, alert_settings.held_count(db))
    audit.record(
        db,
        "alerts.settings",
        actor=principal.user,
        actor_label=actor_name(principal),
        after={k: result[k] for k in AlertSettingsUpdate.model_fields},
    )
    db.commit()
    return result
