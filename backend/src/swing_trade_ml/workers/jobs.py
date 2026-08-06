"""Scheduled job bodies.

Each job owns its own session via `session_scope` and swallows its own
exceptions. A job that raises into APScheduler would be logged and dropped
silently; catching here means the failure reaches Telegram instead.

Times are IST — the exchange's timezone, and the only one in which "after
close" means anything.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.session import session_scope
from swing_trade_ml.notifications import notifier
from swing_trade_ml.services import engine, ingestion, portfolio

log = get_logger(__name__)


def _report_error(context: str, exc: Exception) -> None:
    log.error("job.failed", job=context, error=str(exc))
    notifier.send_sync(
        f"⚠️ <b>Job failed — {context}</b>\n\n<code>{str(exc)[:800]}</code>", "error"
    )


def job_refresh_quotes() -> None:
    """Poll live prices during market hours and mark positions to market."""
    if not ingestion.is_market_open():
        return
    try:
        with session_scope() as db:
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


def job_daily_ingest() -> None:
    """Top up daily candles after the close, before the scan runs.

    Also tops up the benchmark index used for relative-strength/regime ML
    features — it needs to be current before predict_watchlist/signal_scan
    fire right after this job.
    """
    try:
        with session_scope() as db:
            results = ingestion.backfill_watchlist(db, interval="day", incremental=True)
            log.info("job.ingest.done", symbols=len(results), bars=sum(results.values()))
            index_bars = ingestion.backfill_index(db, interval="day")
            log.info("job.ingest.index_done", bars=index_bars)
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
    """
    try:
        from swing_trade_ml.ml.predict import predict_watchlist

        with session_scope() as db:
            results = predict_watchlist(db, interval="day", persist=True)
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
