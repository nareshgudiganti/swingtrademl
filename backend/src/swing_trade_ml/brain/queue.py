"""Queued brain runs (one-app technical design, step 1).

A web request never runs the brain: it only queues a run and answers at once.
A worker job (workers/jobs.py `job_brain_run_queue`, every few seconds in the
process that already owns the scheduler) runs the oldest queued run.

One run at a time per (kind, book): a Postgres advisory lock, held on its own
connection for the whole run, so the 15:50 scheduled run, a queued "Run the
brain now" and the CLI can never overlap. A row left `running` while nobody
holds its lock was cut short by a restart and is marked failed.
"""

from __future__ import annotations

import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import STEPS_FOR
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.models.brain import BrainRun
from swing_trade_ml.db.session import engine

log = get_logger(__name__)

QUEUED = "queued"
RUNNING = "running"
WAITING = (QUEUED, RUNNING)
INTERRUPTED = "Stopped before it finished — the server restarted. Run it again."


class RunBusyError(Exception):
    """Another run of the same kind and book holds the lock."""


def _lock_key(kind: str, book: str) -> int:
    return zlib.crc32(f"brain-run:{kind}:{book}".encode())


@contextmanager
def run_lock(kind: str, book: str, wait_seconds: float = 0) -> Iterator[None]:
    """Hold the single-flight lock for (kind, book), or raise RunBusyError.

    On its own connection, not the caller's session: a run commits several
    times, and a session-level lock must stay on the connection that took it."""
    key = _lock_key(kind, book)
    deadline = time.monotonic() + wait_seconds
    with engine.connect() as conn:
        while True:
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
                break
            if time.monotonic() >= deadline:
                raise RunBusyError(f"A {kind} brain run is already in progress.")
            time.sleep(min(2.0, max(0.05, deadline - time.monotonic())))
        try:
            yield
        finally:
            # Never let a failed unlock hide the run's own error: a broken
            # connection frees the lock anyway when Postgres drops it.
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                log.warning("brain.queue.unlock_failed", kind=kind, book=book, error=str(exc))


def request_run(
    db: Session,
    *,
    kind: str = "nightly",
    book: str = "paper",
    symbols: list[str] | None = None,
    as_of: datetime | None = None,
    requested_by: str = "owner",
) -> tuple[BrainRun, bool]:
    """Queue a run, or return the one already waiting or running for the same
    kind and book (True = it was already there; nothing new is queued)."""
    existing = db.execute(
        select(BrainRun)
        .where(
            BrainRun.kind == kind,
            BrainRun.book == book,
            BrainRun.live.is_(as_of is None),  # a waiting replay is not "the brain thinking now"
            BrainRun.status.in_(WAITING),
        )
        .order_by(BrainRun.started_at)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, True
    now = datetime.now(UTC)
    run = BrainRun(
        id=service.new_run_id(kind, now),
        kind=kind,
        as_of=as_of or now,
        book=book,
        live=as_of is None,
        status=QUEUED,
        started_at=now,
        requested_by=requested_by,
        requested_at=now,
        request={"symbols": symbols, "as_of": as_of.isoformat() if as_of else None},
    )
    db.add(run)
    db.commit()
    return run, False


def _fail_orphans(db: Session, kind: str, book: str) -> None:
    """Called while holding the (kind, book) lock: any row still `running`
    was not finished by a live process."""
    db.execute(
        update(BrainRun)
        .where(BrainRun.kind == kind, BrainRun.book == book, BrainRun.status == RUNNING)
        .values(status="failed", error=INTERRUPTED, finished_at=datetime.now(UTC))
        .execution_options(synchronize_session="fetch")
    )
    db.commit()


def _progress_writer(run_id: str):
    """Write "step n of total" on its own short transaction so a page polling
    the run sees it while the run is still thinking. SKIP LOCKED: never wait
    on the row (in tests the run's own transaction holds it)."""

    def on_step(done: int, total: int, step: str) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE brain_runs SET progress = CAST(:p AS JSONB) "
                        "WHERE id = (SELECT id FROM brain_runs WHERE id = :id FOR UPDATE SKIP LOCKED)"
                    ),
                    {"id": run_id, "p": f'{{"done": {done}, "total": {total}, "step": "{step}"}}'},
                )
        except Exception as exc:  # noqa: BLE001 — progress is a courtesy, never the run
            log.warning("brain.queue.progress_failed", run_id=run_id, error=str(exc))

    return on_step


def process_next(db: Session) -> str | None:
    """Run the oldest queued run whose (kind, book) lock is free; return its id,
    or None when nothing could run. Orphaned `running` rows are failed first."""
    queued = list(
        db.execute(
            select(BrainRun).where(BrainRun.status.in_(WAITING)).order_by(BrainRun.requested_at)
        ).scalars()
    )
    seen: set[tuple[str, str]] = set()
    for run in queued:
        key = (run.kind, run.book)
        if key in seen:
            continue
        seen.add(key)
        try:
            with run_lock(run.kind, run.book):
                _fail_orphans(db, run.kind, run.book)
                db.refresh(run)
                if run.status != QUEUED:
                    target = db.execute(
                        select(BrainRun)
                        .where(
                            BrainRun.kind == run.kind, BrainRun.book == run.book, BrainRun.status == QUEUED
                        )
                        .order_by(BrainRun.requested_at)
                        .limit(1)
                    ).scalar_one_or_none()
                    if target is None:
                        continue
                    run = target
                return _execute(db, run)
        except RunBusyError:
            continue
    return None


def _execute(db: Session, run: BrainRun) -> str:
    run.status = RUNNING
    run.started_at = datetime.now(UTC)
    run.progress = {"done": 0, "total": None, "step": None}
    db.commit()
    request = run.request or {}
    as_of = None if run.live else run.as_of
    progress = _progress_writer(run.id)
    started = time.perf_counter()
    try:
        _, run_id = service.run_brain(
            db,
            kind=run.kind,
            as_of=as_of,
            symbols=request.get("symbols"),
            book=run.book,
            run_id=run.id,
            on_step=progress,
        )
    except Exception as exc:  # noqa: BLE001 — recorded on the row by run_brain
        log.error("brain.queue.run_failed", run_id=run.id, error=str(exc))
        return run.id
    db.refresh(run)
    total = len(STEPS_FOR[run.kind])
    run.progress = {"done": total, "total": total, "step": None}
    db.commit()
    log.info("brain.queue.run_done", run_id=run_id, ms=int((time.perf_counter() - started) * 1000))
    return run_id
