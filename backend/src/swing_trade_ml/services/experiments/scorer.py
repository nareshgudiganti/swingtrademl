"""Score every active pick at each protocol horizon from daily candles.

Safe to run any number of times: each (selection, horizon, protocol) row is rewritten from the same inputs,
so a re-run gives the same result. A Postgres advisory lock stops two scorers running at once; the second
one records
that it stepped aside and returns. The caller owns the transaction (the job commits; tests roll back).

States: pending (entry session not traded yet), open (entered, exit not reached: marked to the latest close),
closed, data_issue (missing bar, big one-day gap, split/bonus in the window, no holiday list), void (cannot be
simulated, e.g. one share costs more than the notional). A data_issue is never scored silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from statistics import fmean
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.experiments import ExperimentJobRun, ExperimentOutcome, ExperimentSelection
from swing_trade_ml.db.models.feeds import UpcomingEvent
from swing_trade_ml.db.models.market import Candle, Instrument

from . import rules
from .ledger import active_selections
from .protocol import PROTOCOL_V1, Protocol, ensure_owner_cohort, protocol_from_row

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
LOCK_KEY = 7_302_017_1  # arbitrary, fixed: "horizon experiments scorer"
SCORER_VERSION = "horizon-scorer-1"
_CORPORATE = re.compile(r"split|bonus|consolidat|sub-?division", re.IGNORECASE)


@dataclass(frozen=True)
class RunResult:
    status: str
    scored: int = 0
    flagged: int = 0


def _ist_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=IST)


def _bars(db: Session, instrument_id: int, start: date, end: date) -> dict[date, tuple[float, float]]:
    rows = db.execute(
        select(Candle.ts, Candle.open, Candle.close).where(
            Candle.instrument_id == instrument_id,
            Candle.interval == "day",
            Candle.ts >= _ist_midnight(start),
            Candle.ts < _ist_midnight(end + timedelta(days=1)),
        )
    ).all()
    return {ts.astimezone(IST).date(): (o, c) for ts, o, c in rows}


def _index_id(db: Session) -> int | None:
    return db.scalar(
        select(Instrument.id)
        .where(Instrument.tradingsymbol == settings.BENCHMARK_INDEX_SYMBOL)
        .order_by(Instrument.id)
    )


def _latest_market_day(db: Session, index_id: int | None, today: date) -> date | None:
    """The last session the market has prices for (the index's, else any instrument's), not after today."""
    q = select(func.max(Candle.ts)).where(
        Candle.interval == "day", Candle.ts < _ist_midnight(today + timedelta(days=1))
    )
    if index_id is not None:
        found = db.scalar(q.where(Candle.instrument_id == index_id))
        if found is not None:
            return found.astimezone(IST).date()
    found = db.scalar(q)
    return found.astimezone(IST).date() if found is not None else None


def _sessions(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if rules.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


class _Benchmarks:
    """NIFTY and equal-weight-universe returns from one entry open to one end close, cached per window.

    The universe gets the same data checks as a pick: a stock is left out (and counted in `dropped`) when it
    misses a session in the window, jumps more than `big_gap` in a day, or has a split/bonus in the window.
    Otherwise an unadjusted split would read as a -50% "return" and flatter every pick."""

    def __init__(self, db: Session, index_id: int | None, protocol: Protocol):
        self.db, self.index_id, self.protocol, self.cache = db, index_id, protocol, {}
        self.equities = dict(
            db.execute(
                select(Instrument.id, Instrument.tradingsymbol).where(
                    func.coalesce(Instrument.segment, "") != "INDICES",
                    Instrument.tradingsymbol != settings.BENCHMARK_INDEX_SYMBOL,
                    or_(Instrument.instrument_type.is_(None), Instrument.instrument_type == "EQ"),
                )
            ).all()
        )

    def get(self, entry: date, end: date) -> tuple[float | None, float | None, int, int]:
        key = (entry, end)
        if key in self.cache:
            return self.cache[key]
        rows = self.db.execute(
            select(Candle.instrument_id, Candle.ts, Candle.open, Candle.close).where(
                Candle.interval == "day",
                Candle.ts >= _ist_midnight(entry),
                Candle.ts < _ist_midnight(end + timedelta(days=1)),
            )
        ).all()
        by_inst: dict[int, dict[date, tuple[float, float]]] = {}
        for iid, ts, o, c in rows:
            by_inst.setdefault(iid, {})[ts.astimezone(IST).date()] = (o, c)
        nifty = None
        idx = by_inst.get(self.index_id) if self.index_id is not None else None
        if idx and entry in idx and end in idx:
            nifty = idx[end][1] / idx[entry][0] - 1
        sessions = _sessions(entry, end)
        events = {
            e.symbol.upper()
            for e in self.db.scalars(
                select(UpcomingEvent).where(
                    UpcomingEvent.kind == "corporate_action",
                    UpcomingEvent.event_date >= entry,
                    UpcomingEvent.event_date <= end,
                )
            )
            if _CORPORATE.search(e.detail or "")
        }
        rets, dropped = [], 0
        for iid, symbol in self.equities.items():
            bars = by_inst.get(iid)
            if not bars:
                continue  # not traded in this window: not part of the universe
            clean = (
                all(d in bars for d in sessions)
                and bars[entry][0] > 0
                and symbol.upper() not in events
                and not _big_gap(bars, self.protocol.big_gap)
            )
            if clean:
                rets.append(bars[end][1] / bars[entry][0] - 1)
            else:
                dropped += 1
        self.cache[key] = (nifty, fmean(rets) if rets else None, len(rets), dropped)
        return self.cache[key]


def _big_gap(bars: dict[date, tuple[float, float]], limit: float) -> dict | None:
    ordered = sorted(bars.items())
    for (_, (_, c0)), (d1, (o1, c1)) in pairwise(ordered):
        for move in (c1 / c0 - 1, o1 / c0 - 1):
            if abs(move) > limit:
                return {"day": d1.isoformat(), "move": round(move, 4)}
    return None


def _flags(db: Session, sel: ExperimentSelection, bars, entry: date, end: date, protocol: Protocol) -> dict:
    flags: dict[str, object] = {}
    missing = [d.isoformat() for d in _sessions(entry, end) if d not in bars]
    if missing:
        flags["missing_bar"] = missing
    gap = _big_gap(bars, protocol.big_gap)
    if gap:
        flags["big_gap"] = gap
    events = db.scalars(
        select(UpcomingEvent).where(
            func.upper(UpcomingEvent.symbol) == sel.symbol_at_entry.upper(),
            UpcomingEvent.kind == "corporate_action",
            UpcomingEvent.event_date >= entry,
            UpcomingEvent.event_date <= end,
        )
    )
    hits = [f"{e.event_date.isoformat()}: {e.detail}" for e in events if _CORPORATE.search(e.detail or "")]
    if hits:
        flags["corporate_action"] = hits
    return flags


def _score_one(db, sel, horizon, protocol, latest, bench) -> dict:
    blank = {
        "entry_price": None,
        "exit_session": None,
        "exit_price": None,
        "mark_session": None,
        "gross_return": None,
        "costs_inr": None,
        "slippage_inr": None,
        "net_return": None,
        "nifty_return": None,
        "universe_return": None,
        "universe_count": None,
        "buy_hold_return": None,
        "excess_vs_nifty": None,
        "excess_vs_universe": None,
        "data_flags": {},
    }
    entry = sel.entry_session
    try:
        exit_day = rules.session_n(entry, horizon)
    except rules.CalendarMissingError as exc:
        # No holiday list yet for the exit's year: wait. It is scored once the list is added, never guessed.
        return {**blank, "state": "pending", "data_flags": {"holiday_calendar_missing": str(exc)}}
    if latest is None or latest < entry:
        return {**blank, "state": "pending"}
    end = min(exit_day, latest)
    bars = _bars(db, sel.instrument_id, entry, end)
    flags = _flags(db, sel, bars, entry, end, protocol)
    entry_bar = bars.get(entry)
    if entry_bar is None:
        flags.setdefault("missing_bar", [entry.isoformat()])
    if flags:
        return {
            **blank,
            "state": "data_issue",
            "data_flags": flags,
            "entry_price": entry_bar[0] if entry_bar else None,
        }
    last_day = max(bars)
    closing = latest >= exit_day
    fill = rules.simulate(entry_bar[0], bars[last_day][1], protocol)
    if fill is None:
        return {
            **blank,
            "state": "void",
            "entry_price": entry_bar[0],
            "data_flags": {"price_above_notional": entry_bar[0]},
        }
    nifty, universe, n_universe, n_dropped = bench.get(entry, last_day)
    return {
        **blank,
        "state": "closed" if closing else "open",
        "entry_price": entry_bar[0],
        "exit_session": exit_day if closing else None,
        "exit_price": bars[exit_day][1] if closing else None,
        "mark_session": None if closing else last_day,
        "gross_return": fill.gross_return,
        "costs_inr": fill.costs_inr,
        "slippage_inr": fill.slippage_inr,
        "net_return": fill.net_return,
        "nifty_return": nifty,
        "universe_return": universe,
        "universe_count": n_universe,
        "buy_hold_return": fill.gross_return,
        "excess_vs_nifty": None if nifty is None else fill.net_return - nifty,
        "excess_vs_universe": None if universe is None else fill.net_return - universe,
        "data_flags": {"universe_dropped": n_dropped} if n_dropped else {},
    }


def run(db: Session, *, now: datetime, protocol: Protocol = PROTOCOL_V1) -> RunResult:
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}):
        db.add(ExperimentJobRun(status="skipped_locked", finished_at=utcnow()))
        db.flush()
        log.info("experiments.scorer.skipped_locked")
        return RunResult("skipped_locked")
    job = ExperimentJobRun(status="running")
    db.add(job)
    db.flush()
    protocol_row, _ = ensure_owner_cohort(db, protocol)
    protocol = protocol_from_row(
        protocol_row
    )  # score with the rules stored on first use, never today's settings
    index_id = _index_id(db)
    latest = _latest_market_day(db, index_id, now.astimezone(IST).date())
    bench = _Benchmarks(db, index_id, protocol)
    scored = flagged = 0
    for sel in active_selections(db):
        for horizon in protocol.horizons:
            values = _score_one(db, sel, horizon, protocol, latest, bench)
            row = db.scalar(
                select(ExperimentOutcome).where(
                    ExperimentOutcome.selection_id == sel.id,
                    ExperimentOutcome.horizon == horizon,
                    ExperimentOutcome.protocol_id == protocol_row.id,
                )
            )
            if row is None:
                row = ExperimentOutcome(selection_id=sel.id, horizon=horizon, protocol_id=protocol_row.id)
                db.add(row)
            for k, v in values.items():
                setattr(row, k, v)
            row.scored_at = utcnow()
            row.scorer_version = SCORER_VERSION
            scored += 1
            flagged += values["state"] == "data_issue"
    job.status, job.finished_at, job.rows_scored, job.rows_flagged = "done", utcnow(), scored, flagged
    db.flush()
    log.info("experiments.scorer.done", scored=scored, flagged=flagged, latest=str(latest))
    return RunResult("done", scored, flagged)
