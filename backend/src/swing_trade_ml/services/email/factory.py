"""Pick the sender from settings. Fails closed: 'resend' without key/from sends nothing."""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.email.senders import EmailSender, LogEmailSender, ResendEmailSender

_log_sender = LogEmailSender()
_override: EmailSender | None = None


def get_sender() -> EmailSender:
    if _override is not None:
        return _override
    if settings.EMAIL_PROVIDER.strip().lower() == "resend":
        # ResendEmailSender itself returns False (and warns) when key or from-address is missing.
        return ResendEmailSender(settings.RESEND_API_KEY, settings.EMAIL_FROM)
    return _log_sender


def log_sender() -> LogEmailSender:
    return _log_sender


def set_sender_for_tests(sender: EmailSender | None) -> None:
    global _override
    _override = sender
