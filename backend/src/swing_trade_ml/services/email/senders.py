"""Email senders. Never log bodies, tokens or the API key: only recipient and subject."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 8.0


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str, html: str | None = None) -> bool: ...


@dataclass
class SentMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class LogEmailSender:
    """Dev/test: keeps messages in memory (`outbox`); logs only recipient and subject."""

    def __init__(self) -> None:
        self.outbox: list[SentMessage] = []

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> bool:
        self.outbox.append(SentMessage(to, subject, text, html))
        log.info("email.logged", to=to, subject=subject)
        return True


class ResendEmailSender:
    """POST https://api.resend.com/emails. Returns False on any failure; never raises."""

    def __init__(self, api_key: str, from_address: str, transport: httpx.BaseTransport | None = None) -> None:
        self._api_key = api_key
        self._from = from_address
        self._transport = transport

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> bool:
        if not self._api_key or not self._from:
            log.warning("email.resend_not_configured", to=to, subject=subject)
            return False
        payload: dict[str, object] = {"from": self._from, "to": [to], "subject": subject, "text": text}
        if html:
            payload["html"] = html
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
                resp = client.post(
                    RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            if resp.status_code >= 300:
                log.warning("email.resend_failed", to=to, subject=subject, status=resp.status_code)
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - must never raise into a request
            log.warning("email.resend_error", to=to, subject=subject, error=type(exc).__name__)
            return False
