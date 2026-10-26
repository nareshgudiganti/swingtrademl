"""FastAPI application entrypoint.

Startup order matters and is deliberate:
  1. logging      — so everything after this is captured
  2. database     — schema created/migrated before anything queries it
  3. Kite session — restored if today's token is still valid
  4. seed         — watchlist populated on an empty database
  5. scheduler    — started last, once its dependencies are ready
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from swing_trade_ml import __version__
from swing_trade_ml.api.rate_limit import public_limit
from swing_trade_ml.api.v1.router import api_router
from swing_trade_ml.brokers.kite import kite_broker
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import configure_logging, get_logger
from swing_trade_ml.core.security import assert_secrets_safe
from swing_trade_ml.db.session import SessionLocal, init_database
from swing_trade_ml.notifications import notifier
from swing_trade_ml.notifications.alert_policy import APP_STATUS
from swing_trade_ml.workers.scheduler import start_scheduler, stop_scheduler

configure_logging()
log = get_logger(__name__)


def _seed_watchlist() -> None:
    """Populate the watchlist on a fresh database so the app is usable at once.

    Only runs when no instruments exist; a configured watchlist is never
    overwritten on restart.
    """
    from sqlalchemy import func, select

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.services import ingestion

    db = SessionLocal()
    try:
        count = db.execute(select(func.count(Instrument.id))).scalar_one()
        if count:
            return
        if not kite_broker.is_authenticated:
            log.info("seed.skipped.no_kite_session")
            return

        log.info("seed.instruments.start")
        ingestion.sync_instruments(db)
        matched = ingestion.set_watchlist(db, settings.watchlist)
        log.info("seed.done", watchlist=len(matched))
    except Exception as exc:  # noqa: BLE001 — seeding is convenience, never fatal
        log.warning("seed.failed", error=str(exc))
    finally:
        db.close()


async def _watch_api_memory() -> None:
    """Housekeeping loop for the API process. Each round runs in a thread (it reads files and Redis) and
    a failure is only logged; the loop never stops on an error."""
    from swing_trade_ml.services import server_watch

    while True:
        await asyncio.sleep(server_watch.SAMPLE_EVERY_SECONDS)
        try:
            await asyncio.to_thread(server_watch.run_watch, "api")
        except Exception as exc:  # noqa: BLE001
            log.warning("server_watch.api_round_failed", error_kind=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_secrets_safe(settings)
    log.info(
        "app.starting",
        app=settings.APP_NAME,
        version=__version__,
        environment=settings.ENVIRONMENT,
        trading_mode="live" if settings.is_live_trading else "paper",
    )

    init_database()

    db = SessionLocal()
    try:
        kite_broker.load_session(db)
    except Exception as exc:  # noqa: BLE001 — the app is useful without a token
        log.warning("kite.session.restore_failed", error=str(exc))
    finally:
        db.close()

    _seed_watchlist()
    start_scheduler()

    mode_line = (
        "💰 <b>LIVE TRADING</b> — real orders will be placed"
        if settings.is_live_trading
        else "📝 PAPER mode — all orders are simulated"
    )
    # await, not send_sync: lifespan is an async function running on uvicorn's
    # event loop, and send_sync's internal asyncio.run() always raises "cannot
    # be called from a running event loop" from here. send_sync exists for
    # truly synchronous callers (APScheduler's worker threads), not this one.
    await notifier.send(f"🚀 <b>Swing Trade ML started</b>\n\n{mode_line}", "system", kind=APP_STATUS)

    if settings.is_live_trading:
        # Loud on purpose. This is the one state where a bug costs real money.
        log.warning("app.LIVE_TRADING_ENABLED")

    # The worker watches itself through the scheduler (job_server_watch); the API has no scheduler, so
    # it watches itself with this task: a memory sample every five minutes, and a safe restart if it
    # has grown too big (services/server_watch.py).
    watch_task = None if settings.ENABLE_SCHEDULER else asyncio.create_task(_watch_api_memory())

    yield

    log.info("app.stopping")
    if watch_task is not None:
        watch_task.cancel()
        with suppress(asyncio.CancelledError):
            await watch_task
    stop_scheduler()
    await notifier.send("🛑 <b>Swing Trade ML stopped</b>", "system", kind=APP_STATUS)


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "ML-driven swing trading bot for Indian equities.\n\n"
        "FastAPI · PostgreSQL/TimescaleDB · Zerodha Kite Connect · Telegram\n\n"
        "**Paper mode is the default.** Live orders require both "
        "`TRADING_MODE=live` and `ALLOW_LIVE_TRADING=true`."
    ),
    version=__version__,
    lifespan=lifespan,
    # Interactive docs are a full read/write control surface for the trading
    # system; they stay off outside local development.
    docs_url="/docs" if settings.ENVIRONMENT == "local" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "local" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT == "local" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the full error, return a generic one.

    Stack traces and driver messages can disclose schema and credentials, so
    they belong in the logs rather than in an HTTP response.
    """
    log.error("api.unhandled", path=request.url.path, error=str(exc), exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["system"], dependencies=[Depends(public_limit)])
def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": __version__,
        "trading_mode": "live" if settings.is_live_trading else "paper",
        "docs": "/docs" if settings.ENVIRONMENT == "local" else "disabled",
        "api": settings.API_V1_PREFIX,
    }
