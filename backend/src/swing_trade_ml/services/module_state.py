"""The durable store behind the module registry (#291): the `module_switches` table.

One row per optional module that has been switched. No row = the declared default. The registry
(core/modules.py) reads this through a short cache in every process (the API and the worker), so a switch made
in one process is seen by the others within a few seconds; the worker also re-reads it before every job run.
Only the registry writes here.

Reads and writes use their own short sessions (`module_audit._new_session`, the same hook the audit sink
uses, so a test can point both at one session).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import select, text

from swing_trade_ml.db.models.module_switch import ModuleSwitch
from swing_trade_ml.services import module_audit

LOCK_KEY = 291_001  # the database-wide lock id for module switches (one switch decides and writes at a time)


class DbStore:
    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Hold a database lock while one switch checks its dependencies and writes, so two owners at
        the same moment cannot both pass a check the other invalidates. Released at the end of the block."""
        with module_audit._new_session() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
            yield

    def read(self) -> dict[str, bool]:
        """module id -> enabled, for every module that has a row."""
        with module_audit._new_session() as db:
            return {row.module_id: row.enabled for row in db.scalars(select(ModuleSwitch))}

    def write(self, module_id: str, enabled: bool, by: str, reason: str) -> None:
        """Set one module's row (created on first use) and commit it."""
        with module_audit._new_session() as db:
            row = db.get(ModuleSwitch, module_id)
            if row is None:
                db.add(ModuleSwitch(module_id=module_id, enabled=enabled, updated_by=by[:128], reason=reason))
            else:
                row.enabled, row.updated_by, row.reason = enabled, by[:128], reason
            db.flush()
