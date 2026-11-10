"""Outgoing email: an interface, a dev/test logger and the Resend sender. See factory.get_sender()."""

from swing_trade_ml.services.email.factory import get_sender, log_sender, set_sender_for_tests
from swing_trade_ml.services.email.senders import EmailSender, LogEmailSender, ResendEmailSender

__all__ = [
    "EmailSender",
    "LogEmailSender",
    "ResendEmailSender",
    "get_sender",
    "log_sender",
    "set_sender_for_tests",
]
