"""The owner_private backfill (alembic ownerprivate01) classifies representative rows deterministically.

Runs the migration's own `backfill()` against the scratch test database inside the test's
rolled-back transaction (the table already has the column there, created by create_all).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from brain_m18_fixtures import instrument
from swing_trade_ml.db.models.trading import Position, Strategy

MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261110_1000_owner_private.py"


def _mig():
    spec = importlib.util.spec_from_file_location("owner_private_mig", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(db, name, stype, *, mode="paper", execution_mode="auto") -> Strategy:
    s = Strategy(
        name=name, strategy_type=stype, params={}, is_active=True, mode=mode, execution_mode=execution_mode
    )
    db.add(s)
    db.flush()
    return s


def test_migration_chain_and_downgrade_shape():
    m = _mig()
    assert m.revision == "ownerprivate01" and m.down_revision == "wlquantity01"
    assert "DROP" not in "".join(m.PRIVATE_MARKERS).upper()


def test_backfill_classifies_representative_rows(db_session):
    rows = {
        "real": _row(db_session, "real_trading", "ml_swing", mode="live", execution_mode="advisory"),
        "renamed_real": _row(
            db_session, "om_renamed_real", "ml_swing", mode="live", execution_mode="advisory"
        ),
        "tester": _row(db_session, "tester_paper", "tester_paper"),
        "brain": _row(db_session, "om_brain", "brain", execution_mode="advisory"),
        "rule": _row(db_session, "om_rule", "sma_crossover"),
        "model": _row(db_session, "om_model", "ml_swing"),
        "unknown": _row(db_session, "om_unknown", "om_mystery"),
        "owns_live": _row(db_session, "om_owns_live", "ml_swing", execution_mode="advisory"),
        "live_auto": _row(db_session, "om_live_auto", "ml_swing", mode="live"),
        "long_term": _row(db_session, "om_long_term", "long_term_value", execution_mode="advisory"),
    }
    inst = instrument(db_session, "OMLIVE", 929101)
    db_session.add(
        Position(
            strategy_id=rows["owns_live"].id,
            instrument_id=inst.id,
            mode="live",
            status="OPEN",
            quantity=1,
            entry_price=100.0,
            entry_at=datetime(2026, 11, 2, tzinfo=UTC),
        )
    )
    # Pretend the column was just added: every row starts at the server default (TRUE).
    db_session.execute(update(Strategy).values(owner_private=True))
    m = _mig()
    m.backfill(db_session.connection())
    m.backfill(db_session.connection())  # idempotent
    db_session.expire_all()
    got = {
        k: db_session.scalar(select(Strategy.owner_private).where(Strategy.id == v.id))
        for k, v in rows.items()
    }
    assert got == {
        "real": True,
        "renamed_real": True,
        "tester": True,
        "brain": False,
        "rule": False,
        "model": False,
        "unknown": True,
        "owns_live": True,
        "live_auto": True,
        "long_term": True,
    }
