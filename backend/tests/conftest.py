"""Test configuration.

Environment is pinned before any application module is imported, so the tests
never pick up a developer's real `.env` — in particular they can never inherit
a live trading configuration.
"""

from __future__ import annotations

import os

os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("ALLOW_LIVE_TRADING", "false")
# Pinned for the same reason as TRADING_MODE above — risk tests assume the
# default risk-based sizer, and a real .env switched to fixed_amount (for
# the live rollout) would otherwise silently change what these tests mean.
os.environ.setdefault("POSITION_SIZING_MODE", "risk_based")
os.environ.setdefault("ENABLE_SCHEDULER", "false")
os.environ.setdefault("TELEGRAM_ENABLED", "false")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("DB_AUTO_MIGRATE", "false")
# A separate database on the same local Postgres instance docker-compose
# already runs — never the real swing_trade_ml database, so a test can never
# read or write real positions/trades/models. Created once by hand (see
# README's test section); tables are (re)created per test session below.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://swingtrade:swingtrade_local_pw@localhost:5433/swing_trade_ml_test",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def db_engine():
    """One schema, created once per test run — every model table, via the
    same create_all() fallback the app itself uses when Alembic hasn't run
    yet (see db/session.py::create_all_tables). Cheaper and more portable
    across test runs than driving real Alembic migrations for every session.
    """
    from swing_trade_ml.db import models  # noqa: F401 — registers mappers on Base
    from swing_trade_ml.db.base import Base
    from swing_trade_ml.db.session import engine as app_engine

    Base.metadata.create_all(bind=app_engine)
    yield app_engine


@pytest.fixture()
def db_session(db_engine) -> Session:
    """One test, one transaction — committed-looking writes inside a test are
    rolled back at teardown, so tests never leak state into one another
    without needing to truncate every table between runs."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session) -> TestClient:
    """A FastAPI TestClient wired to the same rolled-back-after-the-test
    session db_session uses, so assertions against the DB and assertions
    against the API respond to the exact same in-flight transaction."""
    from swing_trade_ml.db.session import get_db
    from swing_trade_ml.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
