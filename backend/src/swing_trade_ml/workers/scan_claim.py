"""One daily scan at a time, across threads and processes (#316).

The 15:45 job, the 5-minute retries and the start-up recovery are separate scheduler jobs, so
APScheduler's max_instances does not keep them apart. A Postgres session-level advisory lock does.

The lock lives on its own connection, held open for the whole scan: the scan's ORM session commits
many times and may use a different pooled connection after each commit, which would strand a lock taken
on it. If the process dies, Postgres drops the connection and the lock with it.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

LOCK_KEY = int.from_bytes(hashlib.sha256(b"daily_signal_scan").digest()[:8], "big") >> 1


@contextmanager
def claim(db: Session, *, wait_seconds: float = 0.0, poll_seconds: float = 1.0) -> Iterator[bool]:
    """Yield True while this caller holds the scan claim, False if another run holds it.

    With `wait_seconds`, keep trying until then (the jobs that follow the scan wait for one in progress)."""
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)
    if engine.dialect.name != "postgresql":  # no other database is used; nothing to coordinate
        yield True
        return
    conn = engine.connect()
    try:
        give_up_at = time.monotonic() + wait_seconds
        while True:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
            conn.commit()
            if got or time.monotonic() >= give_up_at:
                break
            time.sleep(poll_seconds)
        try:
            yield got
        finally:
            if got:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    # Never hand a connection that may still hold the lock back to the pool.
                    log.warning("scan_claim.unlock_failed", error=type(exc).__name__)
                    conn.invalidate()
    finally:
        conn.close()
