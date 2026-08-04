"""Structured logging setup.

Console-rendered and colourised locally; JSON in staging/production so a log
aggregator (CloudWatch, Loki, Datadog) can index the fields.
"""

from __future__ import annotations

import logging
import sys

import structlog

from swing_trade_ml.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    )

    # Third-party loggers are noisy at INFO; keep them at WARNING.
    for noisy in ("apscheduler", "httpx", "httpcore", "urllib3", "kiteconnect"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.LOG_FORMAT == "json"
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
