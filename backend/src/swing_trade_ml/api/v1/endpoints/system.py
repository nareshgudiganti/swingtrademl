"""Health, readiness and system status."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select

from swing_trade_ml import __version__
from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker, kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.holidays import is_trading_holiday
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.db.session import check_connection
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.schemas import HealthResponse, ReadinessResponse, SystemStatus
from swing_trade_ml.workers import heartbeat
from swing_trade_ml.workers.scheduler import list_jobs

router = APIRouter(tags=["system"])

IST = ZoneInfo("Asia/Kolkata")


def _expected_latest_trading_day(now_ist: datetime) -> date:
    """The most recent trading day whose candle should already be in by now.

    Zerodha doesn't publish a day's own historical candle same-day — even
    checked well after both the 15:30 close and the 15:40 ingest job, it's
    consistently still missing, and only shows up some time before the next
    trading day. So "today" is never the right expectation; the bar is
    always the previous trading day, all day today, regardless of the hour.
    """
    d = now_ist.date() - timedelta(days=1)
    while d.weekday() >= 5 or is_trading_holiday(d):
        d -= timedelta(days=1)
    return d


def _plain_status(
    *,
    broker_authenticated: bool,
    scheduler_running: bool,
    latest_candle_date: date | None,
    last_scan_at: datetime | None,
) -> tuple[str, str]:
    """One plain-English sentence a non-technical user can act on, instead of
    three separate technical flags they'd have to interpret themselves."""
    now_ist = datetime.now(IST)

    if not broker_authenticated:
        return "warning", "Not logged into Zerodha today — log in below to keep prices and trading current."

    if not scheduler_running:
        return (
            "warning",
            "Background scheduler isn't running — automatic scans won't fire until it's restarted.",
        )

    expected_day = _expected_latest_trading_day(now_ist)
    if latest_candle_date is None or latest_candle_date < expected_day:
        seen = latest_candle_date.strftime("%d %b") if latest_candle_date else "never"
        return "warning", f"Market data hasn't updated since {seen} — may need a manual refresh."

    scan_desc = last_scan_at.astimezone(IST).strftime("%d %b, %I:%M %p") if last_scan_at else "not yet today"
    return (
        "ok",
        f"All good — logged in, data current as of {latest_candle_date.strftime('%d %b')}, "
        f"last scan {scan_desc} IST.",
    )


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
def ready(db: DbSession) -> ReadinessResponse:
    """Readiness — the database must be reachable to serve traffic.

    A missing Kite session is not a readiness failure: the dashboard, history
    and paper portfolio all work without one.
    """
    db_ok = check_connection()
    if db_ok:
        # This process never runs the worker's periodic session-check job,
        # so its cached is_authenticated flag can sit on a stale "true" for
        # hours after the token actually expired — refresh it every call
        # instead of trusting whatever it last happened to see.
        kite_broker.load_session(db)
    return ReadinessResponse(
        ready=db_ok,
        database=db_ok,
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=heartbeat.is_alive(),
        trading_mode=get_broker().mode,
        live_trading_enabled=settings.is_live_trading,
    )


def _build_status(db: DbSession) -> SystemStatus:
    # Same staleness fix as ready() above — this process's kite_broker is
    # never touched by the worker's periodic check, so verify against the
    # database on every call rather than trusting an old in-memory flag.
    kite_broker.load_session(db)
    active_model = get_active_model(db)

    latest_candle_ts = db.execute(
        select(func.max(Candle.ts)).where(Candle.interval == "day")
    ).scalar_one_or_none()
    latest_candle_date = latest_candle_ts.date() if latest_candle_ts else None
    last_scan_at = db.execute(select(func.max(Signal.generated_at))).scalar_one_or_none()

    status_level, status_message = _plain_status(
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=heartbeat.is_alive(),
        latest_candle_date=latest_candle_date,
        last_scan_at=last_scan_at,
    )

    return SystemStatus(
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        trading_mode=get_broker().mode,
        live_trading_enabled=settings.is_live_trading,
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=heartbeat.is_alive(),
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
        latest_candle_date=latest_candle_date,
        last_scan_at=last_scan_at,
        last_scan_result=heartbeat.read_last_scan(),
        status_level=status_level,
        status_message=status_message,
    )


@router.get("/status", response_model=SystemStatus)
def status(db: DbSession) -> SystemStatus:
    return _build_status(db)


@router.post("/refresh-data", response_model=SystemStatus)
def refresh_data(db: DbSession) -> SystemStatus:
    """The self-service fix for a "market data hasn't updated" warning —
    fires the same ingest + predict jobs the 15:40 IST cron runs, on demand,
    instead of making the user wait for that time or ask someone to check.
    """
    kite_broker.load_session(db)  # this process's flag can be stale — see _build_status
    if not kite_broker.is_authenticated:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            "Log into Zerodha first — refreshing data needs a live session to fetch candles.",
        )

    from swing_trade_ml.workers.jobs import job_daily_ingest, job_predict_watchlist

    job_daily_ingest()
    job_predict_watchlist()

    db.expire_all()  # this request's session cached the pre-refresh rows
    return _build_status(db)
