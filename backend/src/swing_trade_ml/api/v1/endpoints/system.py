"""Health, readiness and system status."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select

from swing_trade_ml import __version__
from swing_trade_ml.api.deps import DbSession, Principal, PrincipalDep, require_auth
from swing_trade_ml.brokers import get_broker, kite_broker
from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import ModelStatus
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.trading import Signal, Strategy
from swing_trade_ml.db.session import check_connection
from swing_trade_ml.ml.registry import get_active_model
from swing_trade_ml.schemas import HealthResponse, ReadinessResponse, SystemStatus
from swing_trade_ml.services.portfolio import open_positions_by_book
from swing_trade_ml.workers import heartbeat
from swing_trade_ml.workers.scheduler import list_jobs

router = APIRouter(tags=["system"])

IST = ZoneInfo("Asia/Kolkata")


# Lives in core.market_session now (the services layer must not import this api module); same behaviour.
_expected_latest_trading_day = market_session.expected_latest_trading_day


# Auto-login fires at 06:10 IST; the missing-session nag starts at 06:15.
AUTO_LOGIN_GRACE = time(6, 15)


def _is_market_closed_day(d: date) -> bool:
    return not market_session.is_trading_day(d)


_next_trading_day = market_session.next_trading_day


def _plain_status(
    *,
    broker_authenticated: bool,
    scheduler_running: bool,
    latest_candle_date: date | None,
    last_scan_at: datetime | None,
    now_ist: datetime | None = None,
    calendar_warning: str | None = None,
) -> tuple[str, str]:
    """One plain-English sentence a non-technical user can act on, instead of
    three separate technical flags they'd have to interpret themselves."""
    now_ist = now_ist or datetime.now(IST)

    # Zerodha expires the token every morning, weekends included, but the
    # auto-login job only runs on trading days at 06:10. So on a weekend or
    # holiday (or a trading day before that job) "not logged in" is expected,
    # not something to act on — logging in then buys nothing.
    login_not_due = _is_market_closed_day(now_ist.date()) or now_ist.time() < AUTO_LOGIN_GRACE
    if not broker_authenticated and not login_not_due:
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

    if calendar_warning:
        return "warning", calendar_warning

    scan_desc = last_scan_at.astimezone(IST).strftime("%d %b, %I:%M %p") if last_scan_at else "not yet today"
    if not broker_authenticated:
        if _is_market_closed_day(now_ist.date()):
            reopen = _next_trading_day(now_ist.date()).strftime("%a %d %b")
            when = f"Market is closed today. The bot will log into Zerodha by itself on {reopen} at 6:10 AM"
        else:
            when = "The bot logs into Zerodha by itself at 6:10 AM"
        return (
            "ok",
            f"{when} — nothing to do. Data current as of {latest_candle_date.strftime('%d %b')}, "
            f"last scan {scan_desc} IST.",
        )
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


# open_positions_by_book lives in services.portfolio now (imported above); same behaviour.


def visible_books(principal: Principal, books: dict[str, int]) -> dict[str, int]:
    """The per-book counts this caller may see, by the same rule as `deps.book_for`.
    The real (My Holdings) count only for the real-account owner and the legacy API key;
    a tester only the shared testing book (the bot book is the owner's, issue #374)."""
    if principal.can_see_real_account:
        return dict(books)
    if principal.is_tester:
        return {"testing": books["testing"]}
    return {k: v for k, v in books.items() if k != "real"}


def visible_scan(principal: Principal, scan: dict | None) -> dict | None:
    """The last scan summary this caller may see. The scan is the bot's, and each `blocked` entry quotes the
    risk layer's own sentence, which can carry the bot's position count, account value and cash. A caller who
    may not see the bot book (a tester) keeps which limit fired and how often, without the sentence."""
    if scan is None or "bot" in visible_books(principal, {"bot": 0, "testing": 0, "real": 0}):
        return scan
    redacted = dict(scan)
    if scan.get("blocked"):
        redacted["blocked"] = [{**item, "reason": None} for item in scan["blocked"]]
    return redacted


def _build_status(db: DbSession, principal: Principal) -> SystemStatus:
    # Same staleness fix as ready() above — this process's kite_broker is
    # never touched by the worker's periodic check, so verify against the
    # database on every call rather than trusting an old in-memory flag.
    kite_broker.load_session(db)
    active_model = get_active_model(db)

    latest_candle_ts = db.execute(
        select(func.max(Candle.ts)).where(Candle.interval == "day")
    ).scalar_one_or_none()
    # Daily bars are stamped 00:00 IST, which comes back as 18:30 UTC the day
    # before — reading .date() in UTC would report every bar one day early.
    latest_candle_date = latest_candle_ts.astimezone(IST).date() if latest_candle_ts else None
    last_scan_at = db.execute(select(func.max(Signal.generated_at))).scalar_one_or_none()

    status_level, status_message = _plain_status(
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=heartbeat.is_alive(),
        latest_candle_date=latest_candle_date,
        last_scan_at=last_scan_at,
        calendar_warning=market_session.calendar_warning(),
    )

    books = visible_books(principal, open_positions_by_book(db))
    return SystemStatus(
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        trading_mode=get_broker().mode,
        live_trading_enabled=settings.is_live_trading,
        brain_enabled=settings.BRAIN_ENABLED,
        paper_tester_enabled=settings.PAPER_TESTER_ENABLED,
        broker_authenticated=kite_broker.is_authenticated,
        scheduler_running=heartbeat.is_alive(),
        scheduled_jobs=list_jobs(),
        telegram_enabled=settings.TELEGRAM_ENABLED,
        active_model=f"{active_model.name}:{active_model.version}" if active_model else None,
        active_models=sorted(
            f"{m.name}:{m.version}"
            for m in db.execute(select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)).scalars()
        ),
        watchlist_size=int(
            db.execute(
                select(func.count(Instrument.id)).where(Instrument.is_watchlisted.is_(True))
            ).scalar_one()
        ),
        active_strategies=int(
            db.execute(select(func.count(Strategy.id)).where(Strategy.is_active.is_(True))).scalar_one()
        ),
        open_positions=books.get("bot"),  # absent (null) when the caller may not see the bot book
        open_positions_by_book=books,
        latest_candle_date=latest_candle_date,
        last_scan_at=last_scan_at,
        last_scan_result=visible_scan(principal, heartbeat.read_last_scan()),
        status_level=status_level,
        status_message=status_message,
    )


@router.get("/status", response_model=SystemStatus, dependencies=[Depends(require_auth)])
def status(db: DbSession, principal: PrincipalDep) -> SystemStatus:
    """Authenticated, unlike /health and /ready above: this reports the
    portfolio's size, the job schedule and whether the broker is connected —
    an inventory of the account, not a liveness signal. The dashboard only
    ever asks for it once logged in (App.tsx gates the query on a token).
    Built per request for this caller and never cached: the book counts depend on who asks.
    """
    return _build_status(db, principal)


@router.get("/config/trading-rules")
def trading_rules_now(principal: PrincipalDep) -> dict:
    """The trading-rule numbers, the trial's session count and the holiday list the screens show (#416).
    Read-only: it reads the versioned research config, the brain plan settings and the NSE calendar. Any
    signed-in caller may read it (every plan): the numbers are the app's public rules, no account data."""
    from swing_trade_ml.services import trading_rules

    # The research-only horizons (10 and 15 sessions) are served to the owner and the shared key only.
    return trading_rules.trading_rules(include_research=principal.is_owner)


@router.get("/market/session", dependencies=[Depends(require_auth)])
def market_session_now(db: DbSession) -> dict:
    """Is the market open right now, when it next opens and closes, and a
    plain line for the top bar (the app's one market clock)."""
    s = market_session.session()
    latest_candle_ts = db.execute(
        select(func.max(Candle.ts)).where(Candle.interval == "day")
    ).scalar_one_or_none()
    return {
        "state": s.state.value,
        "plain": s.plain,
        "trading_day": s.trading_day,
        "opens_at": s.opens_at,
        "closes_at": s.closes_at,
        "next_open": s.next_open,
        "next_close": s.next_close,
        "last_closed_trading_day": s.last_closed_trading_day,
        # For the "prices are N days old" badge: today's IST date and the recent finished trading days.
        "today": s.now.date(),
        "recent_closed_trading_days": market_session.recent_closed_trading_days(s.now),
        # Daily bars are stamped 00:00 IST (18:30 UTC the day before): convert before taking the date.
        "latest_candle_date": latest_candle_ts.astimezone(IST).date() if latest_candle_ts else None,
        "calendar_warning": market_session.calendar_warning(s.now.date()),
    }


@router.post("/refresh-data", response_model=SystemStatus, dependencies=[Depends(require_auth)])
def refresh_data(db: DbSession, principal: PrincipalDep) -> SystemStatus:
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
    return _build_status(db, principal)
