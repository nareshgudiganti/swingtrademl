"""Scheduled job bodies.

Each job owns its own session via `session_scope` and swallows its own
exceptions. A job that raises into APScheduler would be logged and dropped
silently; catching here means the failure reaches Telegram instead.

Times are IST — the exchange's timezone, and the only one in which "after
close" means anything.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.notifications import notifier
from swing_trade_ml.services import engine, ingestion, portfolio

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")


def _report_error(context: str, exc: Exception) -> None:
    log.error("job.failed", job=context, error=str(exc))
    notifier.send_sync(
        f"⚠️ <b>Job failed — {context}</b>\n\n<code>{str(exc)[:800]}</code>", "error"
    )


# Set the first time a trading day's refresh_quotes tick finds no valid Kite
# session, and cleared once a session is loaded again — so the warning below
# fires exactly once per missed day instead of once per poll interval.
_no_session_alert_date: date | None = None


def _alert_missing_session(db) -> None:
    global _no_session_alert_date
    today = datetime.now(IST).date()
    if _no_session_alert_date == today:
        return

    open_count = db.execute(
        select(func.count(Position.id)).where(Position.status == PositionStatus.OPEN)
    ).scalar_one()
    if open_count == 0:
        return

    _no_session_alert_date = today
    log.warning("kite.session.missing_during_market_hours", open_positions=open_count)
    notifier.send_sync(
        "🛑 <b>No active Kite session</b> — prices are not being refreshed, which means "
        f"stop-loss/target checks are NOT running on your {open_count} open position(s) "
        "today. New orders will also fail. Log in at /api/v1/auth/kite/login as soon as "
        "possible.",
        "error",
    )


def job_refresh_quotes() -> None:
    """Poll live prices during market hours and mark positions to market.

    Also re-checks the Kite session on every tick (cheap — see
    KiteBroker.load_session) so a login completed on the api container
    reaches this worker process within a minute, instead of needing a
    manual restart to notice it — the daily pain point this used to be.
    """
    if not ingestion.is_market_open():
        return
    try:
        from swing_trade_ml.brokers.kite import kite_broker

        with session_scope() as db:
            prev_session_id = kite_broker.loaded_session_id
            session_ok = kite_broker.load_session(db)
            if session_ok and kite_broker.loaded_session_id != prev_session_id:
                global _no_session_alert_date
                _no_session_alert_date = None
                notifier.send_sync(
                    "🔑 Kite session picked up automatically — quotes and trading are live.",
                    "system",
                )
            elif not session_ok:
                _alert_missing_session(db)

            count = ingestion.refresh_quotes(db)
            if count:
                portfolio.mark_to_market(db)
    except Exception as exc:  # noqa: BLE001
        _report_error("refresh_quotes", exc)


def job_check_exits() -> None:
    """Enforce stops and targets intraday, not just at the daily scan."""
    if not ingestion.is_market_open():
        return
    try:
        from swing_trade_ml.services.execution import check_exits

        with session_scope() as db:
            closed = check_exits(db)
            if closed:
                log.info("job.exits.closed", count=len(closed))
    except Exception as exc:  # noqa: BLE001
        _report_error("check_exits", exc)


def job_reconcile_orders() -> None:
    """Catch up any order still PENDING against its real broker status.

    Every live order starts PENDING — Kite's placement API confirms
    acceptance, not a fill — and nothing else finishes creating the
    Position/Trade it's blocking on until this checks back (see
    execution.reconcile_pending_orders for the full story). A no-op in paper
    mode. Runs on the same market-hours cadence as refresh_quotes/check_exits
    so a live fill is reflected within about a minute, not left pending
    indefinitely.
    """
    if not ingestion.is_market_open():
        return
    try:
        from swing_trade_ml.services.execution import reconcile_pending_orders

        with session_scope() as db:
            counts = reconcile_pending_orders(db)
            if counts["filled"] or counts["failed"]:
                log.info("job.reconcile.done", **counts)
    except Exception as exc:  # noqa: BLE001
        _report_error("reconcile_orders", exc)


def job_daily_ingest() -> None:
    """Top up daily candles after the close, before the scan runs.

    Also tops up the benchmark index used for relative-strength/regime ML
    features — it needs to be current before predict_watchlist/signal_scan
    fire right after this job — and any strategy running its own,
    deliberately unwatchlisted symbol list (e.g. ml_swing_midcap,
    ml_swing_smallcap), which backfill_watchlist() above never touches.
    """
    try:
        with session_scope() as db:
            results = ingestion.backfill_watchlist(db, interval="day", incremental=True)
            log.info("job.ingest.done", symbols=len(results), bars=sum(results.values()))
            index_bars = ingestion.backfill_index(db, interval="day")
            log.info("job.ingest.index_done", bars=index_bars)

            # load_index_candles() caches the index's full history in memory
            # for the life of the process (see market_context.py) — cheap for
            # the many per-symbol lookups a scan does, but it means the fresh
            # bar just ingested above stays invisible to predict_watchlist/
            # signal_scan/the regime endpoint until something clears it. That
            # "something" never existed before this line — clear_cache() was
            # defined but never called anywhere in the codebase.
            from swing_trade_ml.ml.market_context import clear_cache as clear_index_cache

            clear_index_cache()

            # Every strategy's own symbol list, minus whatever the watchlist
            # backfill above already covered — pooled and de-duplicated so two
            # strategies sharing a symbol don't cost a second Kite call for
            # the same bar. Generic over how many such strategies exist,
            # rather than naming each one here.
            watchlisted = {
                symbol
                for (symbol,) in db.execute(
                    select(Instrument.tradingsymbol).where(Instrument.is_watchlisted.is_(True))
                )
            }
            extra_symbols: set[str] = set()
            for (symbols,) in db.execute(select(Strategy.symbols)):
                extra_symbols.update(s.upper() for s in (symbols or []))
            extra_symbols -= watchlisted

            if extra_symbols:
                extra_results = ingestion.backfill_symbols(db, sorted(extra_symbols), interval="day")
                log.info(
                    "job.ingest.extra_done",
                    symbols=len(extra_results),
                    bars=sum(extra_results.values()),
                )
    except Exception as exc:  # noqa: BLE001
        _report_error("daily_ingest", exc)


def job_signal_scan() -> None:
    """The main daily scan.

    Runs after the close so every strategy sees a completed daily bar. Scanning
    intraday would evaluate a half-formed candle and produce signals that
    disappear by 15:30.
    """
    try:
        with session_scope() as db:
            result = engine.run_all_active(db, interval="day")
            log.info(
                "job.scan.done",
                strategies=result.strategies_run,
                signals=result.signals_generated,
                executed=result.executed,
            )
            if result.errors:
                notifier.send_sync(
                    f"⚠️ Scan finished with {len(result.errors)} error(s):\n"
                    + "\n".join(f"• {e}" for e in result.errors[:10]),
                    "error",
                )
    except Exception as exc:  # noqa: BLE001
        _report_error("signal_scan", exc)


def job_predict_watchlist() -> None:
    """Persist a prediction for every watchlisted symbol against today's close.

    This is what turns "prediction accuracy" from a number you get only by
    remembering to click Refresh on the Recommendations page into an actual
    history: every scored symbol lands in `predictions`, and
    evaluate_pending_predictions() later backfills whether each one panned
    out. Runs after daily_ingest so it sees the same completed bar the signal
    scan does.

    Pinned to "swing_classifier" explicitly — the watchlist is the large-cap
    universe, so it must always be scored by the large-cap model, not
    whichever model name was activated most recently across every strategy
    (mid-cap, small-cap, ...). Passing None here silently shadowed the
    large-cap model with mid-cap's from Aug 12 until this was caught.
    """
    try:
        from swing_trade_ml.ml.predict import predict_watchlist

        with session_scope() as db:
            results = predict_watchlist(db, model_name="swing_classifier", interval="day", persist=True)
            log.info("job.predict.done", scored=len(results))
    except Exception as exc:  # noqa: BLE001
        _report_error("predict_watchlist", exc)


def job_daily_summary() -> None:
    """Snapshot the equity curve and push the end-of-day Telegram digest."""
    try:
        with session_scope() as db:
            portfolio.mark_to_market(db)
            portfolio.take_snapshot(db)
            stats = portfolio.performance_stats(db)

        import asyncio

        asyncio.run(notifier.notify_daily_summary(stats, stats["mode"]))
    except Exception as exc:  # noqa: BLE001
        _report_error("daily_summary", exc)


def job_evaluate_predictions() -> None:
    """Backfill outcomes on predictions whose horizon has elapsed."""
    try:
        from swing_trade_ml.ml.predict import evaluate_pending_predictions

        with session_scope() as db:
            evaluate_pending_predictions(db)
    except Exception as exc:  # noqa: BLE001
        _report_error("evaluate_predictions", exc)


def job_sync_instruments() -> None:
    """Weekly refresh of the instrument master.

    Kite reassigns instrument tokens on corporate actions; a stale token makes
    historical requests fail for that symbol until this runs.
    """
    try:
        with session_scope() as db:
            count = ingestion.sync_instruments(db)
            ingestion.set_watchlist(db, settings.watchlist)
            log.info("job.instruments.synced", count=count)
    except Exception as exc:  # noqa: BLE001
        _report_error("sync_instruments", exc)
