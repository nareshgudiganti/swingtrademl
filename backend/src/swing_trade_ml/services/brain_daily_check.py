"""The daily brain check: one stored record per trading day, made after the nightly run.

Answers "was the brain healthy and wired properly that day, and where does the trial stand?" for any
day, without recomputing: the Saturday checks run daily (services/brain_weekly_health.py), the nightly
run's summary with any modules it dropped, modules dropped by that day's intraday runs, and a snapshot of
the forward trial journal. Reads and reports only; writes nothing but its own row.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.brain import BrainDailyCheck, BrainRun

IST = ZoneInfo("Asia/Kolkata")
TRIAL_SETS = ("brain_trade", "brain_blocked", "brain_top5", "brain_over_80", "v1_buys", "every_stock")
SET_FIELDS = ("picked", "ideas", "still_open", "hit_rate", "avg_net", "edge_vs_every_stock")


def _run_summary(db: Session, run: BrainRun | None) -> dict:
    from swing_trade_ml.brain import service

    if run is None:
        return {}
    words = Counter(d.overruled_word or d.word for d in service.decisions_for(db, run.id))
    return {
        "run_id": run.id,
        "as_of": run.as_of.isoformat(),
        "seconds": round((run.ms or 0) / 1000),
        "banner": run.banner_mode,
        "counts": dict(sorted(words.items())),
        "modules_dropped": service.modules_dropped(run),
    }


def _intraday(db: Session, day: date) -> dict:
    """Every intraday run of `day` and the modules they dropped, counted by module and reason."""
    from swing_trade_ml.brain import service

    lo = datetime.combine(day, time(0, 0), tzinfo=IST)
    runs = list(
        db.execute(
            select(BrainRun).where(
                BrainRun.kind == "intraday",
                BrainRun.live.is_(True),
                BrainRun.as_of >= lo,
                BrainRun.as_of < lo + timedelta(days=1),
            )
        ).scalars()
    )
    seen: Counter = Counter()
    for r in runs:
        for d in service.modules_dropped(r):
            seen[(d["module"], d["reason"])] += 1
    dropped = [{"module": m, "reason": why, "runs": n} for (m, why), n in sorted(seen.items())]
    return {"runs": len(runs), "failed": sum(1 for r in runs if r.status == "failed"), "dropped": dropped}


def _trial(db: Session, day: date) -> dict:
    from swing_trade_ml.brain.trial_journal import TRIAL_START, journal_for

    if day < TRIAL_START:
        return {"start": TRIAL_START.isoformat(), "sessions": 0, "gate": {"word": "not started"}}
    j = journal_for(db, TRIAL_START, day)
    sets = {
        name: {f: (j["summaries"].get(name) or {}).get(f) for f in SET_FIELDS} for name in TRIAL_SETS
    }
    return {
        "start": TRIAL_START.isoformat(),
        "sessions": j["sessions"],
        "gate": j["gate"],
        "sets": sets,
        "nifty": j["summaries"].get("nifty"),
    }


def compute(db: Session, now: datetime | None = None, backup_dir: str | None = None) -> dict:
    """Never raises for one bad part: a part that fails is recorded as a failed check."""
    from swing_trade_ml.brain import service
    from swing_trade_ml.services import brain_weekly_health as weekly

    now = now or datetime.now(UTC)
    day = now.astimezone(IST).date()
    result = weekly.compute_checks(db, now, backup_dir=backup_dir)
    checks = list(result["checks"])
    run = service.latest_run(db, "nightly")
    out = {"day": day.isoformat(), "run": _run_summary(db, run), "intraday": {}, "trial": {}}
    for key, fn in (("intraday", _intraday), ("trial", _trial)):
        try:
            out[key] = fn(db, day)
        except Exception as exc:  # noqa: BLE001 - one bad part must not hide the rest
            why = f"Could not check ({exc.__class__.__name__})."
            checks.append(weekly._check(key.capitalize(), False, why))
    dropped = out["intraday"].get("dropped")
    if dropped:
        listed = "; ".join(f"{d['module']}: {d['reason']} ({d['runs']} runs)" for d in dropped)
        checks.append(weekly._check("Intraday modules ran", False, f"Dropped during the day: {listed}."))
    elif out["intraday"]:
        runs = out["intraday"]["runs"]
        detail = f"{runs} intraday runs, none dropped a module."
        checks.append(weekly._check("Intraday modules ran", True, detail))
    out["checks"] = checks
    out["status"] = "ok" if all(c["ok"] or c.get("level") == "info" for c in checks) else "check"
    return out


def store(db: Session, result: dict) -> None:
    """One row per day: a rerun of the same day replaces it."""
    row = {
        "day": date.fromisoformat(result["day"]),
        "status": result["status"],
        "checks": result.get("checks") or [],
        "run": result.get("run") or {},
        "intraday": result.get("intraday") or {},
        "trial": result.get("trial") or {},
        "created_at": datetime.now(UTC),
    }
    stmt = pg_insert(BrainDailyCheck).values(row)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["day"], set_={k: stmt.excluded[k] for k in row if k != "day"}
        )
    )
    db.commit()


def message_if_problem(result: dict) -> str | None:
    """A short Telegram message when something needs a look; None on a good day (no daily noise)."""
    if result.get("status") == "ok":
        return None
    lines = [f"Brain daily check {result['day']}: something to look at."]
    for c in result.get("checks") or []:
        if not c.get("ok") and c.get("level") != "info":
            lines.append(html.escape(f"CHECK {c['name']}: {c['detail']}", quote=False))
    for d in (result.get("intraday") or {}).get("dropped") or []:
        line = f"Intraday: {d['module']} dropped ({d['reason']}), {d['runs']} runs"
        lines.append(html.escape(line, quote=False))
    return "\n".join(lines)


def _out(row: BrainDailyCheck) -> dict:
    return {
        "day": row.day.isoformat(),
        "status": row.status,
        "checked_at": row.created_at.isoformat() if row.created_at else None,
        "checks": row.checks,
        "run": row.run,
        "intraday": row.intraday,
        "trial": row.trial,
    }


def recent(db: Session, days: int = 30) -> list[dict]:
    rows = db.execute(select(BrainDailyCheck).order_by(BrainDailyCheck.day.desc()).limit(days)).scalars()
    return [_out(r) for r in rows]


def latest(db: Session) -> dict | None:
    rows = recent(db, 1)
    return rows[0] if rows else None
