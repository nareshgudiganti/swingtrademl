"""The daily operations digest: one read-only summary of how production is doing today.

Built only from rows and snapshots the app already keeps (brain runs and decisions, v1 signals,
orders, positions, the worker's job records, candles). It decides nothing and writes nothing.

What it never contains, on purpose:
- any profit, loss, return, win rate or outcome (so nothing the blind trial seal protects can leak;
  see services/trial_seal.py). Only counts, words, prices the idea was made at, and states;
- the real Zerodha account (`real_trading` strategy) or any owner-private strategy;
- credentials, tokens, account numbers or settings values.
Every section is built on its own: if one fails, that section says so and the rest still answer.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.core import market_session
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Order, Position, Signal, Strategy
from swing_trade_ml.services import trial_seal

log = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
TOP_IDEAS = 5
WORDS = ("TRADE", "WATCH", "WAIT", "AVOID")
#: A job whose last run ended in anything but these needs a look.
OK_JOB_STATUSES = frozenset({"ok", "success", "done", "completed", None})


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=IST)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso_ist(dt: datetime | None) -> str | None:
    return None if dt is None else _aware(dt).astimezone(IST).isoformat(timespec="minutes")


def _private_strategy_ids(db: Session) -> set[int]:
    """Strategies the digest must never describe: the real Zerodha book and owner-private ones."""
    from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME

    rows = db.execute(
        select(Strategy.id).where(
            (Strategy.name == REAL_TRADING_STRATEGY_NAME) | (Strategy.owner_private.is_(True))
        )
    ).scalars()
    return set(rows)


def _brain_section(db: Session, day: date) -> dict[str, Any]:
    from swing_trade_ml.brain.service import decisions_for, latest_run
    from swing_trade_ml.services.brain_golive import stage

    lo, hi = _day_bounds(day)
    todays = list(
        db.execute(
            select(BrainRun)
            .where(BrainRun.live.is_(True), BrainRun.started_at >= lo, BrainRun.started_at < hi)
            .order_by(BrainRun.started_at)
        ).scalars()
    )
    run = latest_run(db)
    out: dict[str, Any] = {
        "enabled": settings.BRAIN_ENABLED,
        "stage": stage.current_stage(db),
        "runs_today": [
            {
                "kind": r.kind,
                "status": r.status,
                "started_at": _iso_ist(r.started_at),
                "finished_at": _iso_ist(r.finished_at),
                "error": (r.error or "")[:200] or None,
            }
            for r in todays
        ],
        "failed_runs_today": sum(1 for r in todays if r.status not in ("done", "running", "queued")),
        "latest_run": None,
    }
    if run is None:
        out["note"] = "The brain has no finished run yet."
        return out
    decisions = decisions_for(db, run.id)
    ideas = [d for d in decisions if d.kind == "idea"]
    holdings = [d for d in decisions if d.kind == "holding"]
    by_word = Counter(d.word for d in ideas)
    ranked = sorted(
        ideas, key=lambda d: (WORDS.index(d.word) if d.word in WORDS else 9, -(d.confidence or 0.0))
    )
    out["latest_run"] = {
        "id": run.id,
        "kind": run.kind,
        "as_of": _iso_ist(run.as_of),
        "finished_at": _iso_ist(run.finished_at or run.started_at),
        "is_today": lo <= _aware(run.started_at) < hi,
        "market_banner": {"mode": run.banner_mode, "headline": run.banner_headline},
        "stocks_scanned": len(ideas),
        "ideas_by_word": {w: by_word.get(w, 0) for w in WORDS},
        "holdings_by_word": dict(Counter(d.word for d in holdings)),
        # Deliberately no outcome / return fields: the idea as made, never how it turned out.
        "top_ideas": [
            {
                "symbol": d.symbol,
                "word": d.word,
                "confidence": d.confidence,
                "entry_low": d.entry_low,
                "entry_high": d.entry_high,
                "target": d.target,
                "stop": d.stop,
                "why": (d.reasons[0] if d.reasons else None),
            }
            for d in ranked[:TOP_IDEAS]
        ],
    }
    return out


def _v1_scan_section(db: Session, day: date) -> dict[str, Any]:
    from swing_trade_ml.workers import heartbeat

    lo, hi = _day_bounds(day)
    hidden = _private_strategy_ids(db)
    rows = [
        r
        for r in db.execute(
            select(Signal, Strategy.name, Instrument.tradingsymbol)
            .join(Strategy, Strategy.id == Signal.strategy_id)
            .join(Instrument, Instrument.id == Signal.instrument_id)
            .where(Signal.generated_at >= lo, Signal.generated_at < hi)
        ).all()
        if r[0].strategy_id not in hidden
    ]
    by_strategy: dict[str, Counter] = {}
    for sig, name, _sym in rows:
        by_strategy.setdefault(name, Counter())[sig.signal_type] += 1
    buys = sorted((r for r in rows if r[0].signal_type == "BUY"), key=lambda r: -(r[0].confidence or 0.0))
    return {
        "signals_today": len(rows),
        "by_strategy": {k: dict(v) for k, v in sorted(by_strategy.items())},
        "executed_today": sum(1 for r in rows if r[0].was_executed),
        "top_buy_signals": [
            {
                "symbol": sym,
                "strategy": name,
                "confidence": sig.confidence,
                "price": sig.price,
                "executed": sig.was_executed,
                "blocked_because": (sig.rejection_reason or "")[:160] or None,
            }
            for sig, name, sym in buys[:TOP_IDEAS]
        ],
        "last_scan_result": heartbeat.read_last_scan(),
    }


def _trading_section(db: Session, day: date) -> dict[str, Any]:
    """Paper orders and positions opened or closed today. Counts and names only, never profit."""
    from swing_trade_ml.api.v1.endpoints.system import open_positions_by_book
    from swing_trade_ml.brokers import get_broker

    lo, hi = _day_bounds(day)
    hidden = _private_strategy_ids(db)
    orders = [
        (o, sym)
        for o, sym in db.execute(
            select(Order, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == Order.instrument_id)
            .where(Order.placed_at >= lo, Order.placed_at < hi)
        ).all()
        if o.strategy_id not in hidden
    ]
    opened = [
        sym
        for p, sym in db.execute(
            select(Position, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(Position.entry_at >= lo, Position.entry_at < hi)
        ).all()
        if p.strategy_id not in hidden
    ]
    closed = [
        (sym, p.exit_reason)
        for p, sym in db.execute(
            select(Position, Instrument.tradingsymbol)
            .join(Instrument, Instrument.id == Position.instrument_id)
            .where(Position.exit_at >= lo, Position.exit_at < hi, Position.status == PositionStatus.CLOSED)
        ).all()
        if p.strategy_id not in hidden
    ]
    books = open_positions_by_book(db)
    return {
        "trading_mode": get_broker().mode,
        "orders_today": len(orders),
        "orders_by_status": dict(Counter(o.status for o, _ in orders)),
        "orders_by_side": dict(Counter(o.transaction_type for o, _ in orders)),
        "orders_failed": [
            {
                "symbol": s,
                "side": o.transaction_type,
                "status": o.status,
                "message": (o.status_message or "")[:160],
            }
            for o, s in orders
            if o.status in ("REJECTED", "CANCELLED")
        ],
        "positions_opened_today": sorted(opened),
        "positions_closed_today": [{"symbol": s, "exit_reason": r} for s, r in sorted(closed)],
        # The real book is never shown, not even as a count.
        "open_positions": {"bot": books["bot"], "testing": books["testing"]},
    }


def _jobs_section() -> dict[str, Any]:
    from swing_trade_ml.workers import heartbeat, job_runs
    from swing_trade_ml.workers.scheduler import list_jobs

    registered = {j["id"] for j in list_jobs() if j.get("id")}
    runs, available = job_runs.read_runs()
    problems, rows = [], []
    for jid in sorted(registered | set(runs), key=job_runs.order_key):
        run = runs.get(jid, {})
        row = {
            "id": jid,
            "last_finished_at": run.get("last_finished_at"),
            "last_status": run.get("last_status"),
            "last_error_kind": run.get("last_error_kind"),
            "last_missed_at": run.get("last_missed_at"),
            "running_since": run.get("running_since"),
        }
        rows.append(row)
        if row["last_status"] not in OK_JOB_STATUSES or row["last_error_kind"]:
            problems.append(row)
    return {
        "worker_alive": heartbeat.is_alive(),
        "run_records_available": available,
        "job_count": len(rows),
        "jobs_needing_a_look": problems,
        "jobs": rows,
    }


def _freshness_section(db: Session, now_ist: datetime) -> dict[str, Any]:
    latest_ts = db.execute(select(func.max(Candle.ts)).where(Candle.interval == "day")).scalar_one_or_none()
    latest = latest_ts.astimezone(IST).date() if latest_ts else None
    expected = market_session.previous_trading_day(now_ist.date())
    behind = None
    if latest is not None:
        behind = sum(
            1
            for i in range(1, max((expected - latest).days, 0) + 1)
            if market_session.is_trading_day(latest + timedelta(days=i))
        )
    return {
        "latest_daily_candle": latest.isoformat() if latest else None,
        "expected_latest_candle": expected.isoformat(),
        "stale": latest is None or latest < expected,
        "trading_days_behind": behind,
        "calendar_warning": market_session.calendar_warning(now_ist.date()),
    }


def _risk_section(db: Session) -> dict[str, Any]:
    from swing_trade_ml.brokers import get_broker
    from swing_trade_ml.services import risk
    from swing_trade_ml.services.limits import limits_for
    from swing_trade_ml.services.portfolio import portfolio_value_and_cash

    mode = get_broker().mode
    value, cash = portfolio_value_and_cash(db, mode)
    dd = risk.current_drawdown(db, mode, value)
    limit = limits_for(value).max_drawdown_pct
    return {
        "mode": mode,
        "portfolio_value": round(value, 2),
        "cash": round(cash, 2),
        "drawdown_pct": round(dd * 100, 2),
        "drawdown_limit_pct": round(limit * 100, 2),
        "new_entries_halted": dd >= limit,
    }


def _safe(name: str, fn, *args) -> dict[str, Any]:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - one broken section must not hide the rest
        log.warning("ops_digest.section_failed", section=name, error_kind=type(exc).__name__)
        return {"error": f"{name} could not be read ({type(exc).__name__})"}


def build_digest(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    now_ist = now.astimezone(IST)
    day = now_ist.date()
    session = market_session.session(now_ist)
    brain = _safe("brain", _brain_section, db, day)
    jobs = _safe("scheduler", _jobs_section)
    fresh = _safe("data_freshness", _freshness_section, db, now_ist)
    risk_ = _safe("risk", _risk_section, db)

    attention: list[str] = []
    for section in (brain, jobs, fresh, risk_):
        if "error" in section:
            attention.append(section["error"])
    if brain.get("failed_runs_today"):
        attention.append(f"{brain['failed_runs_today']} brain run(s) failed today.")
    latest = brain.get("latest_run")
    if latest and not latest["is_today"] and market_session.is_trading_day(day):
        attention.append("The brain's latest finished run is not from today.")
    if "error" not in jobs:
        if not jobs["worker_alive"]:
            attention.append("The background worker is not running.")
        for j in jobs["jobs_needing_a_look"]:
            attention.append(f"Scheduled job {j['id']} last ended as {j['last_status']}.")
    if fresh.get("stale"):
        attention.append("Market data is behind where it should be.")
    if risk_.get("new_entries_halted"):
        attention.append("The drawdown limit is reached: new entries are halted.")

    return {
        "generated_at": _iso_ist(now),
        "date_ist": day.isoformat(),
        "all_clear": not attention,
        "needs_attention": attention,
        "market": {"state": session.state.value, "plain": session.plain},
        "trial_seal": {
            "active": trial_seal.active(),
            "note": "This digest never contains profit, loss, returns or outcomes of any idea or position.",
        },
        "brain": brain,
        "v1_scan": _safe("v1_scan", _v1_scan_section, db, day),
        "trading_paper": _safe("trading_paper", _trading_section, db, day),
        "scheduler": jobs,
        "data_freshness": fresh,
        "risk": risk_,
    }
