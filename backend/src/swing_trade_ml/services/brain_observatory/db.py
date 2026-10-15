"""The Observatory's own database session: READ ONLY in Postgres, time-limited, never committed (R8).

It is a separate session from the request's `get_db` one (used by auth), so the read-only setting is the
first statement of its own transaction, as Postgres requires.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import text
from sqlalchemy.orm import Session

from swing_trade_ml.db.session import SessionLocal

STATEMENT_TIMEOUT = "5s"


def get_readonly_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        yield db
    finally:
        db.rollback()
        db.close()
