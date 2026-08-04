"""Health, readiness and system status."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from swing_trade_ml import __version__
from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker, kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.db.session import check_connection
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.schemas import HealthResponse, ReadinessResponse, SystemStatus
from swing_trade_ml.workers.scheduler import list_jobs, scheduler

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness only — deliberately touches no dependency.

    A container orchestrator restarts on a failing liveness probe; making this
    depend on the database would turn a brief DB blip into a restart loop.
    """
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        version=__version__,
    )


@router.get("/ready", response_model=ReadinessResponse)
def ready() -> ReadinessResponse:
    """Readiness — the database must be reachable to serve traffic.

    A missing Kite session is not a readiness failure: the dashboard, history
    and paper portfolio all work without one.
    """
    db_ok = check_connection()
    return ReadinessResponse(
        ready=db_ok,
        database=db_ok,
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=scheduler.running,
        trading_mode=get_broker().mode,
        live_trading_enabled=settings.is_live_trading,
    )


@router.get("/status", response_model=SystemStatus)
def status(db: DbSession) -> SystemStatus:
    active_model = get_active_model(db)
    return SystemStatus(
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        trading_mode=get_broker().mode,
        live_trading_enabled=settings.is_live_trading,
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=scheduler.running,
        scheduled_jobs=list_jobs(),
        telegram_enabled=settings.TELEGRAM_ENABLED,
        active_model=f"{active_model.name}:{active_model.version}" if active_model else None,
        watchlist_size=int(
            db.execute(
                select(func.count(Instrument.id)).where(Instrument.is_watchlisted.is_(True))
            ).scalar_one()
        ),
        active_strategies=int(
            db.execute(
                select(func.count(Strategy.id)).where(Strategy.is_active.is_(True))
            ).scalar_one()
        ),
        open_positions=int(
            db.execute(
                select(func.count(Position.id)).where(Position.status == PositionStatus.OPEN)
            ).scalar_one()
        ),
    )
