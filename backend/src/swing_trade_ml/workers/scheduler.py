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

    # --- after the close ----------------------------------------------------
    # Ingest at 15:40 so the day's final candle is settled, then scan at the
    # configured time (15:45 by default) against complete data.
    scheduler.add_job(
        jobs.job_daily_ingest,
        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=40),
        id="daily_ingest",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_predict_watchlist,
        CronTrigger(day_of_week=WEEKDAYS, hour=15, minute=42),
        id="predict_watchlist",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_signal_scan,
        CronTrigger(
            day_of_week=WEEKDAYS,
            hour=settings.SIGNAL_SCAN_CRON_HOUR,
            minute=settings.SIGNAL_SCAN_CRON_MINUTE,
        ),
        id="signal_scan",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_daily_summary,
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=0),
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.job_evaluate_predictions,
        CronTrigger(day_of_week=WEEKDAYS, hour=16, minute=15),
        id="evaluate_predictions",
        replace_existing=True,
    )

    # --- weekly -------------------------------------------------------------
    # Sunday: the instrument dump is stable and nothing is trading.
    scheduler.add_job(
        jobs.job_sync_instruments,
        CronTrigger(day_of_week="sun", hour=8, minute=0),
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
    return [
        {
            "id": job.id,
            "name": job.name,
            "trigger": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in scheduler.get_jobs()
    ]
