"""Test configuration.

Environment is pinned before any application module is imported, so the tests
never pick up a developer's real `.env` — in particular they can never inherit
a live trading configuration.
"""

from __future__ import annotations

import os

import _env_safety

# Forced, not setdefault: a value already exported in the shell (TRADING_MODE=live,
# a production DATABASE_URL, ...) must never win. See tests/_env_safety.py. The
# database is a separate "_test" database on the same local Postgres instance
# docker-compose already runs — created once by hand (see README's test
# section); tables are (re)created per test session below. Anything else aborts.
_env_safety.pin_safe_environment(os.environ)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402


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


@pytest.fixture(autouse=True)
def _brain_on_for_brain_tests(request, monkeypatch):
    """The brain's API answers only while BRAIN_ENABLED is true (production
    keeps it off until the owner switches it on). Brain tests run with it on;
    a test that needs it off patches it back (see test_brain_visibility.py)."""
    if request.module.__name__.startswith("test_brain"):
        from swing_trade_ml.core.config import settings

        monkeypatch.setattr(settings, "BRAIN_ENABLED", True)


@pytest.fixture(autouse=True)
def _trial_seal_on_for_tests(monkeypatch):
    """Production has the blind-trial seal switched OFF (owner's decision, 2026-11-11). The seal logic is
    still guarded: tests run with it ON so the leak tests keep proving that, when it is on, nothing leaks.
    A test of the unsealed behaviour patches trial_seal.SEALED back to False."""
    from swing_trade_ml.services import trial_seal

    monkeypatch.setattr(trial_seal, "SEALED", True)


@pytest.fixture(autouse=True)
def _billing_on_for_route_audits(request, monkeypatch):
    """Billing routes answer 404 while BILLING_ENABLED is false (the default). The route-by-route
    permission audits must see them, so they run with billing on; they never reach a provider."""
    audits = ("test_permissions_review", "test_p0_role_matrix", "test_p0_tester_private")
    if request.module.__name__ in audits:
        from swing_trade_ml.core.config import settings

        monkeypatch.setattr(settings, "BILLING_ENABLED", True)
        monkeypatch.setattr(settings, "ACCOUNT_DELETION_ENABLED", True)
        monkeypatch.setattr(settings, "BILLING_ACCEPT_NEW_CHECKOUTS", True)  # checkout is audited too
