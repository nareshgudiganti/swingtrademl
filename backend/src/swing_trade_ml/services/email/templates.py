"""Plain-English email templates. No secrets other than the one-time link."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from swing_trade_ml.core.config import settings


def _link(path: str, token: str) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}/{path}?token={quote(token)}"


def verification_email(token: str) -> tuple[str, str, str]:
    link = _link("verify-email", token)
    text = (
        "Welcome to TradeMind.\n\n"
        "Please confirm this is your email address by opening this link (it works once, for 24 hours):\n"
        f"{link}\n\n"
        "If you did not create an account, you can ignore this message."
    )
    html = (
        "<p>Welcome to TradeMind.</p>"
        "<p>Please confirm this is your email address (the link works once, for 24 hours):</p>"
        f'<p><a href="{escape(link)}">Confirm my email</a></p>'
        "<p>If you did not create an account, you can ignore this message.</p>"
    )
    return "Confirm your email for TradeMind", text, html


def reset_email(token: str) -> tuple[str, str, str]:
    link = _link("reset-password", token)
    text = (
        "We received a request to reset your TradeMind password.\n\n"
        "Open this link to choose a new one (it works once, for 1 hour):\n"
        f"{link}\n\n"
        "If you did not ask for this, ignore this message; your password has not changed."
    )
    html = (
        "<p>We received a request to reset your TradeMind password.</p>"
        "<p>Choose a new one here (the link works once, for 1 hour):</p>"
        f'<p><a href="{escape(link)}">Choose a new password</a></p>'
        "<p>If you did not ask for this, ignore this message; your password has not changed.</p>"
    )
    return "Reset your TradeMind password", text, html
