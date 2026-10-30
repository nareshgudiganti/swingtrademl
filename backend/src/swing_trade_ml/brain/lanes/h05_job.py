# backend/src/swing_trade_ml/brain/lanes/h05_job.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""The h05 daily job: record the latest closed session, report missed sessions, mature outcomes.

DISABLED by default and not wired into the scheduler: `register(scheduler)` adds nothing unless the lane is
enabled AND the owner has accepted the protocol hash, and nobody calls it until the owner approves the wiring.
It never starts a run (the owner does), never trades, and writes only the h05_* tables.

One pass (`run_daily`) does, in order:
  1. refuse quietly if the lane is disabled or the protocol is not accepted (no write at all);
  2. take a database lock so two passes can never run at once;
  3. mature the outcomes of every run (label after session 5, trade at its exit);
  4. for the active run, record the latest closed session once the data is in (NIFTY bar present and
     >= 90% of the universe has its candle); wait and retry until 09:00 IST on the next calendar day; after
     that the session is MISSED;
  5. report every session of the window that was not recorded, once, with its reason;
  6. close the run after its last session is recorded or missed.

Duplicate prevention has three layers: the lock, an existence check before scoring, and the unique keys of the
tables (an IntegrityError is treated as 'already recorded'). A recorded day is never rewritten.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes import h05_rules as R
from swing_trade_ml.brain.lanes import h05_service as S
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.lanes import H05Event, H05GroupDay, H05Run
from swing_trade_ml.db.models.market import Candle, Instrument

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
LOCK_KEY = 0x48303544  # "H05D": one daily pass at a time
JOB_ID = "h05_daily"
# 18:30 is after the 15:50 brain run and the ingest; later passes retry; the 07:30 and 08:30 passes are the last
# chances before the 09:00 IST cut-off of the previous session.
SCHEDULE = {"day_of_week": "mon-sat", "hour": "7,8,18,20,22", "minute": 30}


def cutoff(signal_day: date) -> datetime:
    """After this moment an unrecorded signal session is MISSED (09:00 IST on the next calendar day)."""
    nxt = signal_day + timedelta(days=1)
    return datetime(nxt.year, nxt.month, nxt.day, P.JOB_CUTOFF_HOUR_IST, tzinfo=IST)


def _event_once(db: Session, run: H05Run, day: date | None, kind: str, detail: str) -> bool:
    """Persist an event once per (run, day, kind). True if it was new."""
    exists = db.scalar(
        select(func.count())
        .select_from(H05Event)
        .where(H05Event.run_id == run.id, H05Event.signal_day == day, H05Event.kind == kind)
    )
    if exists:
        return False
    db.add(H05Event(run_id=run.id, signal_day=day, kind=kind, detail=detail))
    db.flush()
    return True


def _recorded_days(db: Session, run: H05Run) -> set[date]:
    return set(db.scalars(select(H05GroupDay.signal_day).where(H05GroupDay.run_id == run.id).distinct()))


def data_ready(db: Session, run: H05Run, signal_day: date, sessions: list[date]) -> tuple[bool, dict]:
    """NIFTY has the session and at least DATA_READY_SHARE of the frozen universe has a candle on it."""
    symbols = sorted(run.universe["groups"])
    stamp = datetime(signal_day.year, signal_day.month, signal_day.day, tzinfo=IST)
    have = (
        db.scalar(
            select(func.count(func.distinct(Candle.instrument_id)))
            .join(Instrument, Instrument.id == Candle.instrument_id)
            .where(
                Instrument.exchange == "NSE",
                Instrument.tradingsymbol.in_(symbols),
                Candle.interval == "day",
                Candle.ts == stamp,
            )
        )
        or 0
    )
    share = have / len(symbols) if symbols else 0.0
    nifty = R.session_index(sessions, signal_day) is not None
    info = {"nifty_bar": nifty, "universe": len(symbols), "with_candle": have, "share": round(share, 4)}
    return nifty and share >= P.DATA_READY_SHARE, info


def _pending(db: Session, run: H05Run) -> int:
    from swing_trade_ml.db.models.lanes import H05Signal

    return (
        db.scalar(
            select(func.count())
            .select_from(H05Signal)
            .where(
                H05Signal.run_id == run.id,
                H05Signal.status == "scored",
                (H05Signal.label_status == "pending") | (H05Signal.trade_status == "pending"),
            )
        )
        or 0
    )


def run_daily(db: Session, now: datetime | None = None) -> dict:
    """One pass. Returns a plain dict describing what happened; it does not commit (the caller's scope does)."""
    now = now or datetime.now(UTC)
    out: dict = {"at": now.astimezone(IST).isoformat(timespec="minutes"), "state": "ok", "actions": []}
    try:
        P.require_runnable()
    except P.ProtocolError as exc:
        return {**out, "state": "disabled", "reason": str(exc)}
    if not db.scalar(select(func.pg_try_advisory_xact_lock(LOCK_KEY))):
        return {**out, "state": "busy", "reason": "another daily pass holds the lock"}

    runs = db.scalars(select(H05Run).order_by(H05Run.run_no)).all()
    if not runs:
        return {**out, "state": "no_run", "reason": "no run exists; the owner starts run 1"}

    # 3. maturation: every run, active or closed, until nothing is pending
    out["maturation"] = {}
    for run in runs:
        before = _pending(db, run)
        done = S.evaluate(db, run) if before else {"label": 0, "trade": 0}
        out["maturation"][run.run_no] = {"pending_before": before, "pending_after": _pending(db, run), **done}

    sessions = S.market_sessions(db)
    last = last_closed_trading_day(now)
    out["latest_closed_session"] = str(last)
    active = [r for r in runs if r.status == "active"]
    if not active:
        nxt = max(r.run_no for r in runs) + 1
        out["state"] = "no_active_run"
        out["reason"] = (
            "all runs are closed" if nxt > 3 else f"run {nxt} is not started; the owner starts it"
        )
        return out

    for run in active:
        info: dict = {"run_no": run.run_no, "window": [str(run.start_day), str(run.end_day)]}
        out["actions"].append(info)
        recorded = _recorded_days(db, run)
        window = [d for d in sessions if run.start_day <= d <= min(run.end_day, last)]
        if not window:
            info["state"] = "window_not_reached"
            continue

        # 4. the latest closed session, if it belongs to this run and is still open for recording
        if last in window and last not in recorded and now <= cutoff(last):
            ready, why = data_ready(db, run, last, sessions)
            info["data"] = why
            if not ready:
                info["state"] = "waiting_for_data"
                _event_once(
                    db, run, last, "data_not_ready", f"first pass found the data incomplete: {why}"
                )
            else:
                try:
                    with db.begin_nested():
                        result = S.score_day(db, run, last, now)
                except IntegrityError:
                    info["state"] = "already_recorded"  # the unique keys caught a second writer
                except P.ProtocolError as exc:
                    info["state"] = "refused"
                    info["reason"] = str(exc)
                else:
                    if result.get("stopped"):
                        info["state"] = "lane_stopped"
                        info["reason"] = result["reason"]
                    else:
                        info["state"] = "recorded"
                        info["selected"] = {g: result[g]["selected"] for g in P.GROUPS}
                        recorded.add(last)
        elif last in recorded:
            info["state"] = "already_recorded"

        # 5. sessions of the window that are not recorded and can no longer be: MISSED, reported once
        newly_missed = []
        for d in window:
            if d in recorded or (d == last and now <= cutoff(d)):
                continue
            stopped = db.scalar(
                select(H05Event.detail)
                .where(H05Event.run_id == run.id, H05Event.signal_day == d)
                .where(H05Event.kind == "lane_stopped_model_check")
                .order_by(H05Event.id.desc())
            )
            waited = db.scalar(
                select(H05Event.detail)
                .where(H05Event.run_id == run.id, H05Event.signal_day == d)
                .where(H05Event.kind == "data_not_ready")
            )
            reason = (
                f"lane stopped by a frozen-model check: {stopped}"
                if stopped
                else f"data was not ready by the cut-off: {waited}"
                if waited
                else "no pass recorded the session before the cut-off (the job did not run)"
            )
            if _event_once(
                db,
                run,
                d,
                "missed_session",
                f"{reason}. Not scored late, not replaced, the run is not extended.",
            ):
                newly_missed.append(str(d))
        info["newly_missed_sessions"] = newly_missed

        # 6. close the run once its last session is recorded or missed
        if last >= run.end_day:
            end_open = run.end_day not in recorded and now <= cutoff(run.end_day)
            if not end_open:
                S.close_run(db, run)
                _event_once(
                    db,
                    run,
                    run.end_day,
                    "run_closed",
                    f"recorded {len(recorded)} of {len([d for d in sessions if run.start_day <= d <= run.end_day])} sessions",
                )
                info["closed"] = True
    return out


# ------------------------------------------------------------------ scheduler wiring (not called yet)


def should_register() -> bool:
    s = P.H05Settings()
    return bool(s.ENABLED) and P.accepted(s) and not P.missing_values()


def job_h05_daily() -> None:
    """The scheduled entry point: own session, never raises (an evaluation lane must not disturb the bot)."""
    from swing_trade_ml.db.session import session_scope

    try:
        with session_scope() as db:
            result = run_daily(db)
        log.info("h05.daily", state=result.get("state"), actions=result.get("actions"))
    except Exception as exc:  # noqa: BLE001
        log.error("h05.daily_failed", error_kind=type(exc).__name__)


def register(target) -> bool:
    """Add the daily job to a scheduler ONLY if the lane is enabled and accepted. Returns whether it did."""
    if not should_register():
        return False
    target.add_job(
        job_h05_daily,
        CronTrigger(timezone=IST, **SCHEDULE),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return True
