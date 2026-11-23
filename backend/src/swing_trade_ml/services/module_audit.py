"""Write a module switch request to the app's durable audit log (#291).

One row per request, through the same service the admin console uses (`services/audit.record`), so a switch
shows in the same trail as every other owner action. No new table. The registry (core/modules.py) calls
`write_durable` BEFORE it applies a change: if this raises, the change is not made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from swing_trade_ml.services import audit

ACTION = "module.switch"


def write(db: Session, event: dict) -> None:
    """Add the audit row to `db` (the caller commits)."""
    audit.record(
        db,
        ACTION,
        actor_label=str(event["by"]),
        target_type="module",
        target_id=event["module"],
        before={"enabled": event["from"]},
        after={
            "enabled": event["to"],
            "outcome": event["outcome"],
            "reason": str(event["reason"])[:200],
            "scope": event.get("scope"),
        },
    )


def sink_for_session(db: Session) -> Callable[[dict], None]:
    """A sink that writes into a session the caller owns and commits."""
    return lambda event: write(db, event)


@contextmanager
def _new_session() -> Iterator[Session]:
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:  # commits on success, rolls back on error
        yield db


def write_durable(event: dict) -> None:
    """Write and commit one row in its own session, so the record exists before the change is applied."""
    with _new_session() as db:
        write(db, event)
