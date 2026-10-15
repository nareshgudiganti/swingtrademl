"""Committed rows for Brain Observatory tests.

The Observatory reads through its own READ ONLY transaction (services/brain_observatory/db.py), so it
cannot see rows a test added inside the rolled-back `db_session`. These helpers commit marked rows and
delete them again. Every name is unique to this test session (RUN_PREFIX, SYM_PREFIX, TOKEN_BASE), and
nothing is committed unless the connected database is the dedicated test database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import is_trading_day
from swing_trade_ml.db.models.brain import BrainAlert, BrainDecision, BrainRun, BrainTrack, FeatureSnapshot
from swing_trade_ml.db.models.brain_golive import BrainStageChange
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.session import engine

IST = ZoneInfo("Asia/Kolkata")
TEST_DATABASE = "swing_trade_ml_test"
_RUN_TAG = uuid.uuid4().hex[:8]
RUN_PREFIX = f"obs-{_RUN_TAG}-"  # unique per test session; cleanup touches only this prefix
SYM_PREFIX = f"OX{_RUN_TAG[:6].upper()}"  # distinct symbols per session
TOKEN_BASE = 9_000_000_000 + int(_RUN_TAG[:6], 16) * 1000  # distinct instrument tokens per session
N_SYMBOLS, N_HOLDINGS, N_INTRADAY = 49, 3, 28


def assert_dedicated_test_database(url=None) -> None:
    """Refuse to commit anything unless this is the dedicated local or CI test database."""
    url = url or engine.url
    if url.database != TEST_DATABASE or url.host not in ("localhost", "127.0.0.1"):
        pytest.fail(f"refusing to commit fixture rows to database '{url.database}' on '{url.host}'")
    with engine.connect() as c:
        if c.execute(text("SELECT current_database()")).scalar() != TEST_DATABASE:
            pytest.fail(f"connected database is not {TEST_DATABASE}")


def make_run(
    suffix: str,
    *,
    as_of: datetime,
    kind: str = "nightly",
    status: str = "done",
    live: bool = True,
    book: str = "paper",
    modules: dict | None = None,
    trace: list | None = None,
    error: str | None = None,
    alerts_checked_at: datetime | None = None,
    context: dict | None = None,
    quality: dict | None = None,
    started_at: datetime | None = None,
) -> BrainRun:
    return BrainRun(
        id=f"{RUN_PREFIX}{suffix}",
        kind=kind,
        as_of=as_of,
        book=book,
        live=live,
        started_at=started_at or as_of,
        finished_at=as_of,
        ms=41000,
        status=status,
        error=error,
        modules=modules if modules is not None else {},
        trace=trace if trace is not None else [],
        quality=quality if quality is not None else {},
        alerts_checked_at=alerts_checked_at,
        context=context,
    )


def make_decision(
    run_suffix: str, symbol: str, *, kind: str = "idea", word: str = "WAIT", **kw
) -> BrainDecision:
    return BrainDecision(run_id=f"{RUN_PREFIX}{run_suffix}", symbol=symbol, kind=kind, word=word, **kw)


def cleanup() -> None:
    with Session(engine) as s:
        s.execute(delete(FeatureSnapshot).where(FeatureSnapshot.symbol.like(f"{SYM_PREFIX}%")))
        s.execute(delete(BrainTrack).where(BrainTrack.symbol.like(f"{SYM_PREFIX}%")))
        s.execute(delete(BrainAlert).where(BrainAlert.run_id.like(f"{RUN_PREFIX}%")))
        s.execute(delete(BrainDecision).where(BrainDecision.run_id.like(f"{RUN_PREFIX}%")))
        s.execute(delete(BrainRun).where(BrainRun.id.like(f"{RUN_PREFIX}%")))
        s.execute(
            delete(Instrument).where(
                Instrument.instrument_token >= TOKEN_BASE, Instrument.instrument_token < TOKEN_BASE + 1000
            )
        )
        s.commit()


@contextmanager
def committed(*rows) -> Iterator[None]:
    """Commit `rows` in order (parents first); always clean up afterwards."""
    assert_dedicated_test_database()
    cleanup()
    try:
        with Session(engine) as s:
            for row in rows:  # one flush per row: these models have no relationships to order the inserts
                s.add(row)
                s.flush()
            s.commit()
        yield
    finally:
        cleanup()


@pytest.fixture()
def obs_ns():
    assert_dedicated_test_database()
    cleanup()
    yield
    cleanup()


# --- realistic sizes (C7) ---------------------------------------------------------------------------


def trading_days(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def nightly_as_of(day: date) -> datetime:
    return datetime.combine(day, time(15, 50), tzinfo=IST).astimezone(UTC)


@dataclass
class Cohort:
    start: date
    today: date
    days: list[date]
    symbols: list[str] = field(default_factory=list)

    def add_live_book_run(self, db) -> None:
        db.add(make_run("livebook", as_of=nightly_as_of(self.days[3]), book="live"))
        db.flush()

    def add_stage_change(self, db, stage: str, day: date) -> None:
        db.add(
            BrainStageChange(
                stage=stage,
                previous_stage="shadow",
                changed_by="owner",
                reason="test",
                changed_at=datetime.combine(day, time(9, 0), tzinfo=IST),
            )
        )
        db.flush()


_CONTROL = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


def count_statements(session):
    """Counts SQL statements run on the session's connection. Savepoint control statements are counted
    apart (`.control`): they read nothing, and the journal runs inside one so a database error cannot
    poison the request."""

    class Counter:
        n = 0
        control = 0

    def bump(_conn, _cursor, statement, *_a):
        if statement.lstrip().upper().startswith(_CONTROL):
            Counter.control += 1
        else:
            Counter.n += 1

    event.listen(session.connection(), "before_cursor_execute", bump)
    return Counter


@pytest.fixture()
def realistic_cohort(db_session) -> Cohort:
    """Prod-sized or larger, in the rolled-back db_session: 92 IST days from TRIAL_START, one nightly
    run per trading day with 49 ideas and 3 holdings, 49 symbols plus NIFTY 50 with daily candles from
    130 days before the start to 60 days after the end."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START
    from swing_trade_ml.core.config import settings

    start, today = TRIAL_START, TRIAL_START + timedelta(days=91)
    days = trading_days(start, today)
    symbols = [f"{SYM_PREFIX}{i:02d}" for i in range(N_SYMBOLS)]
    bar_days = trading_days(start - timedelta(days=130), today + timedelta(days=60))
    for n, sym in enumerate([*symbols, settings.BENCHMARK_INDEX_SYMBOL]):
        inst = Instrument(instrument_token=TOKEN_BASE + n, tradingsymbol=sym, exchange="NSE")
        db_session.add(inst)
        db_session.flush()
        price = 100.0 + n
        candles = []
        for i, d in enumerate(bar_days):
            price *= 1 + ((n % 7) - 3) / 1000 + (0.01 if (i + n) % 11 == 0 else 0)
            candles.append(
                Candle(
                    instrument_id=inst.id,
                    interval="day",
                    ts=datetime.combine(d, time(0, 0), tzinfo=IST).astimezone(UTC),
                    open=price,
                    high=price * 1.02,
                    low=price * 0.98,
                    close=price,
                    volume=100_000,
                )
            )
        db_session.add_all(candles)
    db_session.flush()
    for k, d in enumerate(days):
        db_session.add(make_run(f"rc{k}", as_of=nightly_as_of(d)))
        db_session.flush()
        decisions = [
            make_decision(
                f"rc{k}",
                sym,
                word="TRADE" if j == k % N_SYMBOLS else "WAIT",
                confidence=0.5 + j / 200,
                score_source="model",
            )
            for j, sym in enumerate(symbols)
        ]
        decisions += [
            make_decision(f"rc{k}", sym, kind="holding", word="HOLD") for sym in symbols[:N_HOLDINGS]
        ]
        db_session.add_all(decisions)
    db_session.flush()
    return Cohort(start=start, today=today, days=days, symbols=symbols)


@dataclass
class CommittedRuns:
    start: date
    end: date
    intraday_total: int
    ideas_total: int


@pytest.fixture()
def committed_realistic_runs(obs_ns):
    """Runs and decisions only (no candles), committed in this session's namespace, for /days: 92 days,
    one nightly with 49 ideas and 28 intraday runs per trading day."""
    from swing_trade_ml.brain.trial_journal import TRIAL_START

    start, end = TRIAL_START, TRIAL_START + timedelta(days=91)
    rows, ideas, intraday = [], 0, 0
    for k, d in enumerate(trading_days(start, end)):
        rows.append(make_run(f"cn{k}", as_of=nightly_as_of(d)))
        rows += [make_decision(f"cn{k}", f"{SYM_PREFIX}{j:02d}", word="WAIT") for j in range(N_SYMBOLS)]
        ideas += N_SYMBOLS
        for s in range(N_INTRADAY):
            at = datetime.combine(d, time(9, 0), tzinfo=IST) + timedelta(minutes=15 * s)
            rows.append(make_run(f"ci{k}-{s}", as_of=at.astimezone(UTC), kind="intraday"))
            intraday += 1
    with committed(*rows):
        yield CommittedRuns(start=start, end=end, intraday_total=intraday, ideas_total=ideas)
