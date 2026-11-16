"""One entry at a time per trading mode (Codex audit finding 3).

`risk.check_entry` only reads: it looks at free cash, open positions and sector room, and the signal,
order and position are committed afterwards. Two entry paths running together (a manual scan during the
scheduled one, two processes) could therefore both see room and both buy. This lock makes the whole buy
section — cash read, risk check, order, committed position — one critical section per mode, across every
process that shares the database. The second entry waits, then sees the first one's position.

It is a Postgres session-level advisory lock held on its OWN connection. The caller's session commits
several times inside an entry, which would release a transaction-level lock early, and may switch pooled
connections between statements, which would strand a session lock taken on it.

Waiting is bounded. If the lock stays busy past the timeout the caller gets `EntryLockBusy` and must
REJECT the entry rather than place it: decisions only move toward caution (CLAUDE.md principle 5).
Sells and exits never use this lock.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.db.session import engine

log = get_logger(__name__)

# Long enough for a slow Telegram send inside an entry; short enough that a stuck holder cannot freeze a
# scan. Read at call time so tests can shorten it.
ENTRY_LOCK_TIMEOUT_SECONDS = 30.0
_POLL_SECONDS = 0.05


class EntryLockBusy(RuntimeError):  # noqa: N818 - reads better than ...BusyError at the call site
    """Another entry held the lock for the whole timeout. The entry must be rejected, not placed."""


def _key(mode: str) -> int:
    """A stable signed 63-bit key per mode, so paper and live entries never wait on each other."""
    digest = hashlib.sha256(f"swing-trade-ml:entry:{mode}".encode()).digest()
    return int.from_bytes(digest[:8], "big") >> 1


@contextmanager
def entry_lock(mode: str, timeout: float | None = None) -> Iterator[None]:
    wait = ENTRY_LOCK_TIMEOUT_SECONDS if timeout is None else timeout
    key = _key(str(mode))
    # AUTOCOMMIT: no transaction is left open (and idle) on this connection while the entry runs.
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    acquired = False
    try:
        deadline = time.monotonic() + wait
        while True:
            if conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
                acquired = True
                break
            if time.monotonic() >= deadline:
                log.warning("entry_lock.busy", mode=str(mode), waited_seconds=wait)
                raise EntryLockBusy(f"another {mode} entry held the lock for {wait:g}s")
            time.sleep(_POLL_SECONDS)
        yield
    finally:
        try:
            if acquired:
                released = conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key}).scalar()
                if released is not True:
                    raise RuntimeError("pg_advisory_unlock did not confirm the release")
        except Exception:
            # If the unlock cannot be confirmed, drop the connection: Postgres then releases every
            # session lock it held, so a failed unlock can never strand the lock.
            log.exception("entry_lock.unlock_failed", mode=str(mode))
            conn.invalidate()
        finally:
            conn.close()
