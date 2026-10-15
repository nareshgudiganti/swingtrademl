"""R8: the Observatory's session is READ ONLY in Postgres itself; a write is refused by the database.
C8: committed fixture rows only ever go to the dedicated test database."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import observatory_fixtures as fx
from observatory_fixtures import obs_ns  # noqa: F401 — pytest fixture
from swing_trade_ml.db.models.brain import BrainModuleSetting
from swing_trade_ml.db.session import engine
from swing_trade_ml.services.brain_observatory.db import STATEMENT_TIMEOUT, get_readonly_db

pytestmark = pytest.mark.usefixtures("obs_ns")


def _open():
    gen = get_readonly_db()
    return gen, next(gen)


def test_the_transaction_is_read_only_and_time_limited():
    gen, s = _open()
    try:
        assert s.execute(text("SHOW transaction_read_only")).scalar() == "on"
        assert s.execute(text("SHOW statement_timeout")).scalar() == STATEMENT_TIMEOUT
    finally:
        gen.close()


def test_a_write_in_the_session_is_refused_by_postgres():
    gen, s = _open()
    try:
        with pytest.raises(DBAPIError) as exc:
            s.execute(text("INSERT INTO brain_modules (module_id, mode) VALUES ('OBSW', 'on')"))
        assert "read-only transaction" in str(exc.value).lower()
    finally:
        gen.close()
    with Session(engine) as check:
        assert check.get(BrainModuleSetting, "OBSW") is None


def test_the_session_is_rolled_back_and_closed_never_committed(monkeypatch):
    calls = []
    gen, s = _open()
    monkeypatch.setattr(s, "commit", lambda: calls.append("commit"))
    gen.close()
    assert calls == []


def test_fixture_refuses_a_non_test_database():
    with pytest.raises(pytest.fail.Exception):
        fx.assert_dedicated_test_database(make_url("postgresql+psycopg://u:p@db.example.com/swing_trade_ml"))
    with pytest.raises(pytest.fail.Exception):
        fx.assert_dedicated_test_database(make_url("postgresql+psycopg://u:p@localhost/swing_trade_ml"))


def test_namespace_is_unique_to_this_session():
    assert fx.RUN_PREFIX.startswith("obs-") and len(fx.RUN_PREFIX) == len("obs-12345678-")
    assert fx.SYM_PREFIX.startswith("OX") and fx.TOKEN_BASE >= 9_000_000_000
