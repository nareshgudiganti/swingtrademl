"""APScheduler wiring.

Job times are IST because they are defined relative to the NSE session.
`max_instances=1` and `coalesce=True` on every job: if a scan overruns its next
trigger, the run must be skipped, never overlapped — two concurrent scans would
both see no open position and both enter the same trade.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.workers import jobs

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

scheduler = BackgroundScheduler(
    timezone=IST,
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
)

# Monday-Friday only; the exchange is shut at weekends.
WEEKDAYS = "mon-fri"


def start_scheduler() -> None:
    if not settings.ENABLE_SCHEDULER:
        log.info("scheduler.disabled")
        return
    if scheduler.running:
        return

    # --- always on, every day, any hour — this is a liveness signal, not a
    # trading job, so it must not go quiet just because the market is closed
    # or it's a weekend. See workers/heartbeat.py for who reads it.
    scheduler.add_job(
        jobs.job_heartbeat,
        IntervalTrigger(seconds=60),
        id="heartbeat",
        replace_existing=True,
    )
    # Also always-on: confirming a completed Kite login shouldn't depend on
    # logging in during market hours — see job_check_kite_login's docstring.
    scheduler.add_job(
        jobs.job_check_kite_login,
        IntervalTrigger(seconds=60),
        id="check_kite_login",
        replace_existing=True,
    )

    # Unattended login, timed just after Zerodha expires the previous day's
    # token (~06:00 IST) and well before market open — see
    # job_kite_auto_login's docstring. No-ops if credentials aren't set.
    scheduler.add_job(
        jobs.job_kite_auto_login,
        CronTrigger(day_of_week=WEEKDAYS, hour=6, minute=10, timezone=IST),
        id="kite_auto_login",
        replace_existing=True,
    )

    # Chase the login until it actually happens. Runs from 06:15 — five
    # minutes after kite_auto_login has had its go, so this only speaks up
    # once automation has already failed — through to the close, half-hourly.
    # The job itself no-ops while a session is loaded, and _alert_missing_
    # session's own cooldown stops a repeat firing turning into spam.
    scheduler.add_job(
        jobs.job_nag_missing_session,
        CronTrigger(day_of_week=WEEKDAYS, hour="6-15", minute="15,45", timezone=IST),
        id="nag_missing_session",
        replace_existing=True,
    )

    # --- intraday, market hours only (the jobs self-check the session) -------
    scheduler.add_job(
        jobs.job_refresh_quotes,
        IntervalTrigger(seconds=settings.LIVE_POLL_SECONDS),
        id="refresh_quotes",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_check_exits,
        IntervalTrigger(seconds=max(60, settings.LIVE_POLL_SECONDS)),
        id="check_exits",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_reconcile_orders,
        IntervalTrigger(seconds=max(60, settings.LIVE_POLL_SECONDS)),
        id="reconcile_orders",
        replace_existing=True,
    )

    # --- after the close ----------------------------------------------------
    # Ingest at 15:40 so the day's final candle is settled, then scan at the
    # configured time (15:45 by default) against complete data.
    scheduler.add_job(
        jobs.job_daily_ingest,
        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=40, timezone=IST),
        id="daily_ingest",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_predict_watchlist,
        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=42, timezone=IST),
        id="predict_watchlist",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_signal_scan,
        CronTrigger(
            day_of_week=WEEKDAYS,
            hour=settings.SIGNAL_SCAN_CRON_HOUR,
            minute=settings.SIGNAL_SCAN_CRON_MINUTE,
            timezone=IST,
        ),
        id="signal_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_daily_summary,
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=0, timezone=IST),
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_evaluate_predictions,
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=15, timezone=IST),
        id="evaluate_predictions",
        replace_existing=True,
    )

    # --- weekly -------------------------------------------------------------
    # Sunday: the instrument dump is stable and nothing is trading.
    scheduler.add_job(
        jobs.job_sync_instruments,
        CronTrigger(day_of_week="sun", hour=8, minute=0, timezone=IST),
        id="sync_instruments",
        replace_existing=True,
    )

    scheduler.start()
    log.info(
        "scheduler.started",
        jobs=[j.id for j in scheduler.get_jobs()],
        timezone="Asia/Kolkata",
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")


def list_jobs() -> list[dict]:
    local = [
        {
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in scheduler.get_jobs()
    ]
    if local:
        return local
    # This process's own scheduler has nothing registered — true for the API
    # container, which deliberately never runs one (see heartbeat.py's
    # docstring). Fall back to the worker's last snapshot instead of
    # reporting zero jobs, which the Settings page would otherwise render as
    # "0 jobs registered" even while everything is running fine.
    from swing_trade_ml.workers import heartbeat

    return heartbeat.read_jobs()
