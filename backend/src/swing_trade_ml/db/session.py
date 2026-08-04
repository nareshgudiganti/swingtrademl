"""Engine, session factory, and the automatic schema bootstrap.

`init_database()` is called once during app startup so the server comes up with
a ready schema — no manual DDL, no `alembic upgrade` step to remember.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    # Cloud databases drop idle connections through load balancers; pre-ping
    # turns the resulting stale-connection error into a transparent reconnect.
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for background jobs, which have no request scope.

    Commits on success, rolls back on any exception, always closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _backend_dir() -> Path:
    # db/session.py -> swing_trade_ml -> src -> backend
    return Path(__file__).resolve().parents[3]


def run_migrations() -> None:
    """Apply all pending Alembic migrations up to `head`.

    Invoked programmatically rather than via the CLI so a plain `uvicorn` start
    (or a container with no shell step) still lands on the current schema.
    """
    from alembic import command
    from alembic.config import Config

    backend = _backend_dir()
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

    log.info("db.migrate.start")
    command.upgrade(cfg, "head")
    log.info("db.migrate.done")


def create_all_tables() -> None:
    """Fallback schema creation straight from the SQLAlchemy models.

    Only used if Alembic cannot run (for example the versions directory is
    empty on a fresh clone). It creates missing tables but cannot alter
    existing ones, which is exactly why migrations are the primary path.
    """
    from swing_trade_ml.db import models  # noqa: F401 — registers mappers on Base
    from swing_trade_ml.db.base import Base

    log.warning("db.create_all.fallback")
    Base.metadata.create_all(bind=engine)


def init_database() -> None:
    """Bring the schema to a usable state at startup.

    Tries migrations first; falls back to `create_all` so a first run never
    fails just because migrations are not set up yet.
    """
    if not settings.DB_AUTO_MIGRATE:
        log.info("db.auto_migrate.disabled")
        return

    try:
        run_migrations()
    except Exception as exc:  # noqa: BLE001 — degrade to create_all, don't block boot
        log.warning("db.migrate.failed", error=str(exc))
        create_all_tables()


def check_connection() -> bool:
    """Used by the readiness probe."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("db.healthcheck.failed", error=str(exc))
        return False
