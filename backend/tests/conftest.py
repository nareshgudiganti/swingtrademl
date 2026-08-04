"""Test configuration.

Environment is pinned before any application module is imported, so the tests
never pick up a developer's real `.env` — in particular they can never inherit
a live trading configuration.
"""

from __future__ import annotations

import os

os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("ALLOW_LIVE_TRADING", "false")
os.environ.setdefault("ENABLE_SCHEDULER", "false")
os.environ.setdefault("TELEGRAM_ENABLED", "false")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("DB_AUTO_MIGRATE", "false")
