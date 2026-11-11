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


def already_registered_email() -> tuple[str, str, str]:
    base = settings.APP_BASE_URL.rstrip("/")
    signin, reset = f"{base}/login", f"{base}/reset-password"
    text = (
        "Someone tried to sign up for TradeMind with this email address.\n\n"
        "If it was you, you already have an account. Sign in here:\n"
        f"{signin}\n\n"
        "Forgotten your password? Ask for a reset here:\n"
        f"{reset}\n\n"
        "If it was not you, ignore this message; nothing has changed on your account."
    )
    html = (
        "<p>Someone tried to sign up for TradeMind with this email address.</p>"
        "<p>If it was you, you already have an account.</p>"
        f'<p><a href="{escape(signin)}">Sign in</a> or '
        f'<a href="{escape(reset)}">reset your password</a>.</p>'
        "<p>If it was not you, ignore this message; nothing has changed on your account.</p>"
    )
    return "Someone tried to sign up with your email on TradeMind", text, html


def deletion_confirm_email(token: str) -> tuple[str, str, str]:
    link = _link("confirm-deletion", token)
    text = (
        "We received a request to delete your TradeMind account.\n\n"
        "To go ahead, open this link (it works once, for 1 hour):\n"
        f"{link}\n\n"
        "Nothing is deleted yet. After you confirm, a waiting period lets you change your mind.\n"
        "If you did not ask for this, ignore this message; your account is unchanged."
    )
    html = (
        "<p>We received a request to delete your TradeMind account.</p>"
        f'<p><a href="{escape(link)}">Yes, delete my account</a> (the link works once, for 1 hour).</p>'
        "<p>Nothing is deleted yet. After you confirm, a waiting period lets you change your mind.</p>"
        "<p>If you did not ask for this, ignore this message; your account is unchanged.</p>"
    )
    return "Confirm deleting your TradeMind account", text, html


def deletion_scheduled_email(cancel_token: str, when: str, cancelled_pro: bool) -> tuple[str, str, str]:
    link = _link("cancel-deletion", cancel_token)
    pro = "\nYour Pro subscription has been cancelled and will not renew." if cancelled_pro else ""
    text = (
        f"Your TradeMind account will be deleted on {when}.{pro}\n\n"
        "You are signed out everywhere and cannot sign in until then.\n"
        "Changed your mind? Open this link before that date to keep your account:\n"
        f"{link}"
    )
    html = (
        f"<p>Your TradeMind account will be deleted on <b>{escape(when)}</b>.</p>"
        + ("<p>Your Pro subscription has been cancelled and will not renew.</p>" if cancelled_pro else "")
        + "<p>You are signed out everywhere and cannot sign in until then.</p>"
        + f'<p>Changed your mind? <a href="{escape(link)}">Keep my account</a> before that date.</p>'
    )
    return "Your TradeMind account will be deleted", text, html
