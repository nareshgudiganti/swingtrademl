"""Sending brain alerts.

Compare a finished live run with the previous finished live run of the same
kind, drop anything already told today (IST), send one message through v1's
Telegram notifier as a `signal` event, and record only what was really sent
— so turning Telegram on later still delivers what is new.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from swing_trade_ml.brain.alerts.compose import compose
from swing_trade_ml.brain.alerts.detectors import AlertItem, DecisionView, RunView, detect
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainAlert, BrainDecision, BrainRun

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
ALERTING_KINDS = {"nightly", "intraday"}

Sender = Callable[[str], bool]


def default_sender() -> Sender:
    from swing_trade_ml.core.enums import NotificationEvent
    from swing_trade_ml.notifications import notifier

    return lambda text: notifier.send_sync(text, NotificationEvent.SIGNAL)


def _view(db: Session, run: BrainRun) -> RunView:
    rows = db.execute(select(BrainDecision).where(BrainDecision.run_id == run.id)).scalars()
    decisions = {
        d.symbol: DecisionView(
            symbol=d.symbol,
            kind=d.kind,
            word=d.word,
            reason=(d.reasons or [""])[0],
            qty=d.qty or 0,
            entry_low=d.entry_low,
            entry_high=d.entry_high,
            target=d.target,
            stop=d.stop,
            overruled_word=d.overruled_word,
        )
        for d in rows
    }
    return RunView(run.id, run.started_at, run.banner_mode, run.banner_headline, decisions)


def _previous(db: Session, run: BrainRun) -> BrainRun | None:
    return db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == run.kind,
            BrainRun.book == run.book,
            BrainRun.live.is_(True),
            BrainRun.status.in_(("done", "superseded")),
            BrainRun.alerts_checked_at.is_not(None),
            BrainRun.started_at < run.started_at,
        )
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _alert_day(run: BrainRun):
    return run.started_at.astimezone(IST).date()


def pending(db: Session, run_id: str) -> list[AlertItem]:
    """What this run should tell the owner that has not been told today."""
    run = db.get(BrainRun, run_id)
    if run is None or not run.live or run.status != "done" or run.kind not in ALERTING_KINDS:
        return []
    previous = _previous(db, run)
    items = detect(_view(db, run), _view(db, previous) if previous else None)
    told = set(
        db.execute(select(BrainAlert.alert_key).where(BrainAlert.alert_date == _alert_day(run))).scalars()
    )
    return [i for i in items if i.key not in told]


def preview(db: Session, run_id: str) -> dict:
    run = db.get(BrainRun, run_id)
    items = pending(db, run_id)
    text = compose(items, _view(db, run)) if run is not None else None
    return {
        "items": [{"key": i.key, "kind": i.kind, "symbol": i.symbol, "text": i.text} for i in items],
        "text": text,
    }


def _mark_checked(db: Session, run: BrainRun | None) -> None:
    """Nothing to tell is still a check: this run becomes the next baseline.
    A failed send is NOT marked, so the next run compares against the older
    baseline and the news is found again."""
    if run is not None and run.live and run.kind in ALERTING_KINDS:
        run.alerts_checked_at = datetime.now(UTC)
        db.commit()


def send(db: Session, run_id: str, sender: Sender | None = None) -> dict:
    run = db.get(BrainRun, run_id)
    items = pending(db, run_id)
    text = compose(items, _view(db, run)) if items else None
    if text is None:
        _mark_checked(db, run)
        return {"sent": False, "count": 0, "text": None}
    sent = (sender or default_sender())(text)
    if sent:
        run.alerts_checked_at = datetime.now(UTC)
        day = _alert_day(run)
        for item in items:
            db.execute(
                insert(BrainAlert)
                .values(alert_key=item.key, alert_date=day, run_id=run.id, kind=item.kind, text=item.text)
                .on_conflict_do_nothing(index_elements=["alert_key", "alert_date"])
            )
        db.commit()
    log.info("brain.alerts", run_id=run_id, items=len(items), sent=sent)
    return {"sent": bool(sent), "count": len(items), "text": text}
