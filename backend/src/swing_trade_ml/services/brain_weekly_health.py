"""The Saturday health check: the owner's weekly checklist, done by the machine.

Reads and reports only. It reuses what the brain endpoints already compute
(`brain.service.health`, `module_overview`, `stage_overview`, the learning-run
store) and writes nothing but its own result row.

Every check is {name, ok, detail, level}. `level` is "ok", "info" (shown for
information, never a failure) or "warn"/"fail" (ok is False). A check that
itself blows up becomes a failed check, so one bad read never hides the rest.
"""

from __future__ import annotations

import html
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import (
    is_trading_day,
    last_closed_trading_day,
    trading_days_between,
)
from swing_trade_ml.db.models.brain import BrainRun, BrainWeeklyHealth
from swing_trade_ml.ml.backup import RUN_RECORD, read_run_record

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Modules that must be on for the brain to be doing its job (M07 is the risk gate).
REQUIRED_MODULES = ("M01", "M02", "M07", "M08")
# A side feed whose newest day is more than this many trading days old is stale.
FEED_MAX_AGE_TRADING_DAYS = 3
# The learning loop runs Saturdays; a result older than this is "not this week".
LEARNING_MAX_AGE_DAYS = 8
HISTORY_KEPT = 52
# Models are backed up daily (16:30 job); a newest copy older than this means the job stopped.
BACKUP_MAX_AGE_DAYS = 7
# The job runs every weekday; a run record older than this (a long weekend is 3-4 days) means it stopped.
BACKUP_RUN_MAX_AGE_DAYS = 4

FEED_LABELS = {
    "delivery": "delivery",
    "bulk_deals": "bulk and block deals",
    "fii_dii": "FII/DII flows",
}


def _check(name: str, ok: bool, detail: str, level: str | None = None) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "level": level or ("ok" if ok else "fail")}


def _ist_date(value: datetime) -> date:
    return value.astimezone(IST).date()


def _day(d: date) -> str:
    return d.strftime("%a %d %b")


def check_last_nightly(health: dict, expected: date) -> dict:
    last = health.get("last_nightly_ok")
    if last is None:
        return _check("Nightly run", False, "No finished nightly brain run found.")
    ran = _ist_date(last)
    if ran >= expected:
        return _check("Nightly run", True, f"Last nightly finished {_day(ran)}, the latest trading day.")
    return _check("Nightly run", False, f"Last nightly finished {_day(ran)}; expected {_day(expected)}.")


def check_failed_runs(health: dict) -> dict:
    n = int(health.get("failed_runs_7d") or 0)
    if n == 0:
        return _check("Failed runs", True, "No failed brain runs in the last 7 days.")
    return _check("Failed runs", False, f"{n} brain run(s) failed in the last 7 days.")


def check_data_fresh(health: dict) -> dict:
    fresh = (health.get("data") or {}).get("fresh")
    if fresh is None:
        return _check("Data freshness", False, "No data check has run yet.")
    if fresh:
        return _check("Data freshness", True, "Price data is fresh.")
    return _check(
        "Data freshness", False, f"Price data is stale ({health.get('stale_count') or 0} stock(s) behind)."
    )


def check_feeds(health: dict, today: date) -> list[dict]:
    out = []
    for feed in health.get("feeds") or []:
        name = f"Feed: {FEED_LABELS.get(feed.get('name'), feed.get('name'))}"
        latest = feed.get("latest")
        if not latest:
            out.append(_check(name, False, "No data at all."))
            continue
        d = date.fromisoformat(str(latest))
        age = trading_days_between(d, today)
        if age > FEED_MAX_AGE_TRADING_DAYS:
            out.append(_check(name, False, f"Latest day is {_day(d)}, {age} trading days ago."))
        else:
            out.append(_check(name, True, f"Latest day is {_day(d)}."))
    return out


def check_modules(modules: list[dict]) -> dict:
    modes = {m["id"]: m["mode"] for m in modules}
    off = [m for m in REQUIRED_MODULES if modes.get(m) != "on"]
    if not off:
        return _check("Key modules", True, "M01, M02, M07 and M08 are on.")
    return _check(
        "Key modules", False, "Not on: " + ", ".join(f"{m} ({modes.get(m, 'missing')})" for m in off) + "."
    )


def check_modules_ran(db: Session) -> dict:
    """Did every module actually run in the last live nightly run? A run can finish with modules
    dropped (too slow, an error) and a simpler fallback answering for them; until 2026-10-13 this check
    did not exist and three modules were dropped every night unnoticed. A dropped module that is on
    fails the check; a dropped trial (shadow) module is a warning."""
    from swing_trade_ml.brain import service

    run = service.latest_run(db, "nightly")
    if run is None:
        return _check("Modules ran", True, "No finished nightly run yet.", "info")
    day = _day(_ist_date(run.as_of))
    dropped = service.modules_dropped(run)
    if not dropped:
        return _check("Modules ran", True, f"Every module ran in the {day} nightly run.")
    listed = "; ".join(f"{d['module']} ({d['mode']}): {d['reason']}" for d in dropped)
    if any(d["mode"] == "on" for d in dropped):
        detail = f"Dropped in the {day} nightly run, so a simpler fallback answered: {listed}."
        return _check("Modules ran", False, detail)
    return _check("Modules ran", False, f"Trial modules dropped in the {day} nightly run: {listed}.", "warn")


def check_stage(stage: dict) -> dict:
    current = stage.get("stage")
    if current == "shadow":
        return _check("Trading stage", True, "Still practice (shadow); no brain orders.")
    return _check("Trading stage", False, f"Stage is '{current}', not practice (shadow). Was that you?")


def check_progress(stage: dict) -> dict:
    return _check(
        "Finished ideas",
        True,
        f"{stage.get('finished', 0)} of {stage.get('needed', 30)} finished brain ideas.",
        "info",
    )


def check_banner(db: Session) -> dict:
    run = db.execute(
        select(BrainRun)
        .where(BrainRun.kind == "nightly", BrainRun.status == "done", BrainRun.live.is_(True))
        .order_by(BrainRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if run is None or not run.banner_mode:
        return _check("Banner", True, "No banner yet (no finished nightly run).", "info")
    return _check("Banner", True, f"Banner is {run.banner_mode.replace('_', ' ')}.", "info")


def _counted_ideas(db: Session, today: date) -> dict:
    from swing_trade_ml.services.brain_golive import idea_watch

    return idea_watch.check(db, today)


def check_banner_history(db: Session, today: date, days: int = 20) -> dict:
    """How many of the last trading days have a recorded market mode. Replays need this history;
    without it they have to assume every day was NORMAL."""
    from swing_trade_ml.brain.market_mode_history import coverage, mode_history
    from swing_trade_ml.core.market_session import previous_trading_day

    day = today if is_trading_day(today) else previous_trading_day(today)
    window = []
    for _ in range(days):
        window.append(day)
        day = previous_trading_day(day)
    have, total = coverage(mode_history(db), window)
    return _check(
        "Banner history",
        True,
        f"A market mode is recorded for {have} of the last {total} trading days.",
        "info",
    )


def check_learning(db: Session, now: datetime) -> dict:
    from swing_trade_ml.brain.modules.m09_learn import store

    row = store.latest_learning_run(db)
    if row is None:
        return _check("Learning and drift", True, "Not checked yet.", "info")
    when = _day(_ist_date(row.created_at))
    if now - row.created_at > timedelta(days=LEARNING_MAX_AGE_DAYS):
        return _check("Learning and drift", True, f"Last checked {when}, not this week.", "info")
    lines = list(row.drift_lines or [])
    if lines:
        return _check("Learning and drift", True, f"Checked {when}. Drift noted: {lines[0]}", "info")
    return _check("Learning and drift", True, f"Checked {when}. No drift noted.", "info")


def check_backup(backup_dir: str | None = None, now: datetime | None = None) -> dict:
    """The newest file's change time in the backup folder. No backup run is
    recorded anywhere, so this is the closest honest answer: on the server the
    change time is when the copy was made. Nothing there is a warning, never a
    made-up time; a newest copy older than BACKUP_MAX_AGE_DAYS is a warning too
    (the daily backup job has stopped)."""
    folder = backup_dir if backup_dir is not None else settings.MODEL_BACKUP_DIR
    if not folder:
        return _check(
            "Model backup", False, "No backup folder is set up, so there is no record of a backup.", "warn"
        )
    path = Path(folder)
    record = read_run_record(path)
    if record is not None:
        ran = record["at"]
        age = ((now or datetime.now(UTC)) - ran).days
        if age > BACKUP_RUN_MAX_AGE_DAYS:
            return _check(
                "Model backup",
                False,
                f"The backup job last ran {_day(_ist_date(ran))}, {age} days ago; it may have stopped.",
                "warn",
            )
        if record["missing"]:
            return _check(
                "Model backup",
                False,
                f"Backup ran {_day(_ist_date(ran))} but these model files are missing: "
                + ", ".join(record["missing"]),
                "warn",
            )
        kept = record["already_present"] + record["copied"]
        return _check(
            "Model backup", True, f"Backup ran {_day(_ist_date(ran))}; all {kept} model files are copied."
        )
    try:
        files = [f for f in path.iterdir() if f.is_file() and f.name != RUN_RECORD] if path.is_dir() else []
        newest = max((f.stat().st_ctime for f in files), default=None)
    except OSError as exc:
        return _check(
            "Model backup", False, f"Could not read the backup folder ({exc.__class__.__name__}).", "warn"
        )
    if newest is None:
        return _check(
            "Model backup", False, "The backup folder is empty or missing; no record of a backup.", "warn"
        )
    made = datetime.fromtimestamp(newest, UTC)
    age = ((now or datetime.now(UTC)) - made).days
    if age > BACKUP_MAX_AGE_DAYS:
        return _check(
            "Model backup",
            False,
            f"Newest backup file is from {_day(_ist_date(made))}, {age} days ago; "
            "the daily backup may have stopped.",
            "warn",
        )
    return _check("Model backup", True, f"Newest backup file is from {_day(_ist_date(made))}.")


def compute_checks(db: Session, now: datetime | None = None, backup_dir: str | None = None) -> dict:
    """Run every check. Never raises: a check that fails to run is reported as failed."""
    from swing_trade_ml.brain import service
    from swing_trade_ml.services.brain_golive import stage as stage_service

    now = now or datetime.now(UTC)
    today = _ist_date(now)
    expected = last_closed_trading_day(now)
    checks: list[dict] = []

    def run(name: str, fn, *args) -> None:
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 - one bad read must not hide the others
            log.warning("brain.weekly_health.check_failed", check=name, error=str(exc))
            checks.append(_check(name, False, f"Could not check ({exc.__class__.__name__})."))
            return
        checks.extend(result if isinstance(result, list) else [result])

    run("Brain health", _health_checks, service, db, expected, today)
    run("Key modules", lambda: check_modules(service.module_overview(db)))
    run("Modules ran", check_modules_ran, db)
    run("Trading stage", _stage_checks, stage_service, db)
    run("Banner", check_banner, db)
    run("Banner history", check_banner_history, db, today)
    run("Counted ideas", _counted_ideas, db, today)
    run("Learning and drift", check_learning, db, now)
    run("Model backup", check_backup, backup_dir, now)
    run("Risk rules", _risk_rules, db)

    return {
        "status": "ok" if all(c["ok"] for c in checks) else "check",
        "generated_at": now.isoformat(),
        "checks": checks,
    }


def _risk_rules(db: Session) -> dict:
    from swing_trade_ml.services import rules_watch

    return rules_watch.check(db)


def _health_checks(service, db: Session, expected: date, today: date) -> list[dict]:
    health = service.health(db)
    return [
        check_last_nightly(health, expected),
        check_failed_runs(health),
        check_data_fresh(health),
        *check_feeds(health, today),
    ]


def _stage_checks(stage_service, db: Session) -> list[dict]:
    stage = stage_service.stage_overview(db, history_limit=1)
    return [check_stage(stage), check_progress(stage)]


def format_message(result: dict) -> str:
    """One plain-English Telegram message: OK / CHECK lines."""
    bad = sum(1 for c in result["checks"] if not c["ok"])
    head = "Weekly brain check: all good." if not bad else f"Weekly brain check: {bad} thing(s) to look at."
    lines = [head, ""]
    for c in result["checks"]:
        word = "OK" if c["ok"] else "CHECK"
        lines.append(html.escape(f"{word} {c['name']}: {c['detail']}", quote=False))
    return "\n".join(lines)


def store_result(db: Session, result: dict) -> BrainWeeklyHealth:
    row = BrainWeeklyHealth(status=result["status"], checks=result["checks"])
    db.add(row)
    db.flush()
    old = (
        db.execute(select(BrainWeeklyHealth.id).order_by(BrainWeeklyHealth.id.desc()).offset(HISTORY_KEPT))
        .scalars()
        .all()
    )
    if old:
        db.execute(delete(BrainWeeklyHealth).where(BrainWeeklyHealth.id.in_(old)))
    db.commit()
    return row


def latest_result(db: Session) -> dict:
    """The last stored result, or a clear 'not run yet'."""
    row = db.execute(
        select(BrainWeeklyHealth).order_by(BrainWeeklyHealth.id.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return {"run": False, "status": None, "checks": [], "detail": "The weekly check has not run yet."}
    return {"run": True, "status": row.status, "checked_at": row.created_at.isoformat(), "checks": row.checks}
