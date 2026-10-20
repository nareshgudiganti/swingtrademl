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
    sets = {name: {f: (j["summaries"].get(name) or {}).get(f) for f in SET_FIELDS} for name in TRIAL_SETS}
    return {
        "start": TRIAL_START.isoformat(),
        "sessions": j["sessions"],
        "gate": j["gate"],
        "sets": sets,
        "nifty": j["summaries"].get("nifty"),
    }


def check_ideas_reached_counter(db: Session, day: date) -> dict | None:
    """Did today's brain ideas land in the practice record (the "N of 30" counter)? Uses the brain
    strategy's own to_signal, so "expected" is exactly what it turns into a recorded BUY. A day the brain
    named nothing is shown (info), never a failure on its own: idea_watch fails 3 such days in a row."""
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.core.enums import SignalType
    from swing_trade_ml.services import brain_weekly_health as weekly
    from swing_trade_ml.services.brain_golive import compare
    from swing_trade_ml.services.brain_golive.stage import current_stage
    from swing_trade_ml.strategies import brain as brain_strategy

    run, decisions = brain_strategy.todays_decisions(db, day, settings.TRADING_MODE)
    if run is None:
        return None  # no nightly run today: "Nightly run" already fails
    practice = current_stage(db) not in ("approval", "auto")
    said = sum(
        brain_strategy.to_signal(d, run, d.entry_high or 1.0, practice=practice).signal == SignalType.BUY
        for d in decisions.values()
    )
    rows, _ = compare.load(db, since=day)
    counted = [r for r in compare.one_per_day(rows) if r.is_brain and r.day == day]
    blocked = sum(r.blocked for r in counted)
    name = "Ideas reached the counter"
    if said == 0:
        return weekly._check(name, True, "Zero-idea day: today's run named no idea to record.", "info")
    if not counted:
        detail = (
            f'Today\'s run named {said} idea(s) but none reached the practice record (the "N of 30" '
            "counter). The link from the brain to the record is broken; this is how 4-9 Oct went unseen."
        )
        return weekly._check(name, False, detail)
    detail = f"{len(counted)} of {said} idea(s) from today's run were recorded ({blocked} blocked by limits)."
    if len(counted) < said:
        detail += " The rest are stocks outside the brain strategy's watchlist."
    return weekly._check(name, True, detail)


# The intraday job fires every 15 minutes from 09:00 to 15:45 IST: 28 runs on a full trading day. Fewer
# than half means the job was mostly not running (a busy lock skips one now and then, never half).
INTRADAY_RUNS_FULL_DAY = 28
INTRADAY_RUNS_MIN = INTRADAY_RUNS_FULL_DAY // 2


def check_intraday_runs(intraday: dict) -> dict:
    from swing_trade_ml.services import brain_weekly_health as weekly

    runs, failed = intraday.get("runs", 0), intraday.get("failed", 0)
    name = "Intraday runs"
    if runs == 0:
        return weekly._check(name, False, "No intraday brain run today; the 15-minute job did not run.")
    if failed:
        return weekly._check(name, False, f"{failed} of {runs} intraday brain runs failed today.")
    if runs < INTRADAY_RUNS_MIN:
        detail = f"Only {runs} of about {INTRADAY_RUNS_FULL_DAY} intraday brain runs today."
        return weekly._check(name, False, detail, "warn")
    return weekly._check(name, True, f"{runs} intraday brain runs today, none failed.")


def check_stale_stocks(run: BrainRun | None) -> dict | None:
    """Stocks behind on prices. The market can still count as fresh with up to a fifth of them stale
    (M01), so "Data freshness" stays green; this names them so a quiet gap is seen the same day."""
    from swing_trade_ml.services import brain_weekly_health as weekly

    if run is None:
        return None
    stale = list((run.quality or {}).get("stale") or [])
    if not stale:
        return weekly._check("Stale stocks", True, "Every stock's prices are up to date.")
    shown = ", ".join(stale[:5]) + (f" and {len(stale) - 5} more" if len(stale) > 5 else "")
    detail = f"{len(stale)} stock(s) behind on prices; the brain treats their data as unreliable: {shown}."
    return weekly._check("Stale stocks", False, detail, "warn")


# ps6 decision stability. A flip is a jump between opposite answers from one nightly run to the next
# while the price hardly moved: many of them mean the answers are noise, not a view.
OPPOSITES = ({"TRADE", "AVOID"}, {"HOLD", "EXIT"})
FLIP_MOVE = 0.02  # a price move under 2% between the two runs counts as "hardly moved"
# Owner sets this after two weeks of counts (plan ps6). Until then the check only reports the number.
NORMAL_MAX_FLIPS: int | None = None


def _previous_nightly(db: Session, run: BrainRun) -> BrainRun | None:
    return db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == "nightly",
            BrainRun.live.is_(True),
            BrainRun.status == "done",
            BrainRun.as_of < run.as_of,
        )
        .order_by(BrainRun.as_of.desc())
        .limit(1)
    ).scalar_one_or_none()


def _close_on_or_before(db: Session, symbol: str, day: date) -> float | None:
    from swing_trade_ml.db.models.market import Candle, Instrument

    # Daily candles are stamped at IST midnight, so "before the next IST midnight" is "on or before day".
    upto = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=IST)
    return db.execute(
        select(Candle.close)
        .join(Instrument, Instrument.id == Candle.instrument_id)
        .where(Instrument.tradingsymbol == symbol, Candle.interval == "day", Candle.ts < upto)
        .order_by(Candle.ts.desc())
        .limit(1)
    ).scalar_one_or_none()


def decision_flips(db: Session, run: BrainRun | None) -> dict | None:
    """Stocks whose answer jumped to its opposite since the previous nightly run with < 2% price move."""
    from swing_trade_ml.brain import service

    if run is None:
        return None
    prev = _previous_nightly(db, run)
    if prev is None:
        return None
    before = {(d.kind, d.symbol): d.word for d in service.decisions_for(db, prev.id)}
    day_now, day_before = run.as_of.astimezone(IST).date(), prev.as_of.astimezone(IST).date()
    compared, changed, flips = 0, 0, []
    for d in service.decisions_for(db, run.id):
        old = before.get((d.kind, d.symbol))
        if old is None:
            continue
        compared += 1
        if old == d.word:
            continue
        changed += 1
        if not any({old, d.word} == pair for pair in OPPOSITES):
            continue
        now_px, then_px = (
            _close_on_or_before(db, d.symbol, day_now),
            _close_on_or_before(db, d.symbol, day_before),
        )
        if now_px is None or not then_px:
            continue
        move = now_px / then_px - 1
        if abs(move) < FLIP_MOVE:
            flips.append({"symbol": d.symbol, "from": old, "to": d.word, "move": round(move, 4)})
    return {
        "since_run": prev.id,
        "compared": compared,
        "changed": changed,
        "flips": flips,
        "normal_max": NORMAL_MAX_FLIPS,
    }


def check_decision_stability(stability: dict | None) -> dict | None:
    from swing_trade_ml.services import brain_weekly_health as weekly

    if stability is None:
        return None
    flips = stability["flips"]
    shown = ", ".join(f"{f['symbol']} {f['from']}→{f['to']}" for f in flips[:5])
    shown += f" and {len(flips) - 5} more" if len(flips) > 5 else ""
    detail = (
        f"{len(flips)} of {stability['compared']} stocks jumped to the opposite answer since the last "
        f"nightly run while the price moved less than {FLIP_MOVE:.0%}"
        + (f": {shown}." if flips else ".")
        + f" {stability['changed']} answers changed in all."
    )
    limit = stability["normal_max"]
    if limit is None:
        return weekly._check("Decision flips", True, detail + " Normal range not set yet.", "info")
    if len(flips) > limit:
        return weekly._check("Decision flips", False, detail + f" More than the normal {limit}.", "warn")
    return weekly._check("Decision flips", True, detail + f" Within the normal {limit}.")


def _live_models(db: Session) -> list:
    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel

    return list(db.execute(select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)).scalars())


def _question(m) -> str:
    """A model's own question in plain words, from its stored label definition."""
    days, target = m.prediction_horizon_days, f"+{m.target_return_pct:.0%}"
    if m.label_kind == "barrier" and m.stop_return_pct:
        return f"{target} before -{m.stop_return_pct:.0%} within {days} days"
    if m.label_kind == "endpoint":
        return f"closes {target} or more after {days} days"
    return f"{target} in {days} days"


def check_model_question(models: list) -> dict:
    """Does each live model's question match the trade plan? A model scores "+2% in 5 days" yet the plan
    trades +8% before -4% in 15 days: the score is then not evidence for that trade. Shown, never a
    failure (level info): it is a known gap until the 15-day models are live (Atlas tv23/tv24), and a
    daily alarm would only be noise. Reads the stored label fields; changes no decision."""
    from swing_trade_ml.brain.modules.m08_decide.policy import DEFAULT_POLICY
    from swing_trade_ml.services import brain_weekly_health as weekly

    plan = DEFAULT_POLICY
    name = "Score matches the trade plan"
    want = f"+{plan.target_pct:.0%} before -{plan.stop_pct:.0%} within {plan.horizon_days} days"
    if not models:
        return weekly._check(name, False, f"No live model found. The plan trades {want}.", "info")

    def matches(m) -> bool:
        return (
            m.label_kind == "barrier"
            and m.prediction_horizon_days == plan.horizon_days
            and abs(m.target_return_pct - plan.target_pct) < 1e-9
            and m.stop_return_pct is not None
            and abs(m.stop_return_pct - plan.stop_pct) < 1e-9
        )

    off = [m for m in models if not matches(m)]
    if not off:
        return weekly._check(name, True, f"Every live model asks the plan's question: {want}.")
    listed = "; ".join(f"{m.name} asks '{_question(m)}'" for m in sorted(off, key=lambda m: m.name))
    detail = f"NOT matched. The plan trades {want}, but {listed}. Such a score does not prove that trade."
    return weekly._check(name, False, detail, "info")


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
    stability = None
    try:
        stability = decision_flips(db, run)
    except Exception as exc:  # noqa: BLE001 - one bad part must not hide the rest
        checks.append(weekly._check("Decision flips", False, f"Could not check ({exc.__class__.__name__})."))
    if out["run"] and stability is not None:
        out["run"]["stability"] = stability  # kept in the stored record, so the counts have a history
    for key, fn in (("intraday", _intraday), ("trial", _trial)):
        try:
            out[key] = fn(db, day)
        except Exception as exc:  # noqa: BLE001 - one bad part must not hide the rest
            why = f"Could not check ({exc.__class__.__name__})."
            checks.append(weekly._check(key.capitalize(), False, why))
    if out["intraday"]:
        checks.append(check_intraday_runs(out["intraday"]))
    for label, fn in (
        ("Ideas reached the counter", lambda: check_ideas_reached_counter(db, day)),
        ("Stale stocks", lambda: check_stale_stocks(run)),
        ("Score matches the trade plan", lambda: check_model_question(_live_models(db))),
        ("Decision flips", lambda: check_decision_stability(stability)),
    ):
        try:
            found = fn()
        except Exception as exc:  # noqa: BLE001 - one bad part must not hide the rest
            found = weekly._check(label, False, f"Could not check ({exc.__class__.__name__}).")
        if found is not None:
            checks.append(found)
    # Server checks (qa9 new kinds of error, qa11 disk / memory / database size): never raise.
    from swing_trade_ml.services import server_health

    checks.extend(server_health.checks(db, day))
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
