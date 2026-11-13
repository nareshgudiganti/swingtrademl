"""Safe-by-construction environment for the test suite (used by conftest.py).

conftest used to call os.environ.setdefault for these values, so anything
already exported in the developer's shell won: TRADING_MODE=live,
ALLOW_LIVE_TRADING=true, a production DATABASE_URL. Now the safety-critical
values are *forced*, credentials are blanked (an empty environment variable
beats a value in .env), and the database must be a local test database or the
whole run refuses to start.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from swing_trade_ml.core.db_guard import assert_local_test_database, assert_no_connection_overrides

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test"
)

# Forced, whatever the shell says.
FORCED = {
    "TRADING_MODE": "paper",
    "ALLOW_LIVE_TRADING": "false",
    "ENABLE_SCHEDULER": "false",
    "TELEGRAM_ENABLED": "false",
    "TELEGRAM_SEND_OUTSIDE_PRODUCTION": "false",
    "ERROR_WATCH_ENABLED": "false",
    "DB_AUTO_MIGRATE": "false",
    # Risk tests assume the default risk-based sizer; a .env switched to
    # fixed_amount would silently change what they mean.
    "POSITION_SIZING_MODE": "risk_based",
    # Per-IP request limits off (one TestClient IP makes hundreds of calls);
    # test_rate_limit.py switches them on with an in-memory Redis stand-in.
    "RATE_LIMIT_ENABLED": "false",
}

# Blanked, so a value in the developer's .env can never reach a test.
BLANKED_CREDENTIALS = (
    "KITE_API_KEY",
    "KITE_API_SECRET",
    "KITE_USER_ID",
    "KITE_PASSWORD",
    "KITE_TOTP_SECRET",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)

# Placeholders a caller (CI) may override; never the real ones.
DEFAULTS = {"API_KEY": "test-api-key", "JWT_SECRET_KEY": "test-jwt-secret"}


# The check itself lives in the package so scripts/check_migrations.py shares it. It imports
# nothing from the app, so it is safe to use before the settings are read.
assert_test_database = assert_local_test_database


def pin_safe_environment(env: MutableMapping[str, str]) -> None:
    """Apply the safe settings to `env` (os.environ in conftest)."""
    assert_no_connection_overrides(env)  # an inherited PGHOSTADDR/PGPORT/... could reroute the URL
    env.update(FORCED)
    for name in BLANKED_CREDENTIALS:
        env[name] = ""
    for name, value in DEFAULTS.items():
        env.setdefault(name, value)
    env.setdefault("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    assert_test_database(env["DATABASE_URL"])
