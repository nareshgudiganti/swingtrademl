"""portfolio_risk_layer

Revision ID: 7b3e9d51a2c4
Revises: c4a1f7b28d93
Create Date: 2026-09-15 16:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3e9d51a2c4"
down_revision: str | None = "b95286c2ad43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_state",
        sa.Column("id", sa.Integer(), nullable=False),
        # Both switches default ON at the database level too: a row inserted
        # by hand or by a future script must not silently halt trading or,
        # worse, silently disable stop-losses.
        sa.Column("new_entries_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exits_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("halt_reason", sa.Text(), nullable=True),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("halted_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_state")),
    )
    # The single row every read expects. Inserted here rather than lazily by
    # the app so the entry check never has to write.
    op.execute("INSERT INTO system_state (id, new_entries_enabled, exits_enabled) VALUES (1, true, true)")

    op.create_table(
        "risk_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=64), nullable=True),
        sa.Column("rule", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("amount_inr", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"],
            name=op.f("fk_risk_events_strategy_id_strategies"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"], ["instruments.id"],
            name=op.f("fk_risk_events_instrument_id_instruments"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_events")),
    )
    op.create_index(op.f("ix_risk_events_ts"), "risk_events", ["ts"], unique=False)
    op.create_index(op.f("ix_risk_events_mode"), "risk_events", ["mode"], unique=False)
    op.create_index(op.f("ix_risk_events_rule"), "risk_events", ["rule"], unique=False)
    op.create_index(op.f("ix_risk_events_strategy_id"), "risk_events", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_risk_events_instrument_id"), "risk_events", ["instrument_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_risk_events_instrument_id"), table_name="risk_events")
    op.drop_index(op.f("ix_risk_events_strategy_id"), table_name="risk_events")
    op.drop_index(op.f("ix_risk_events_rule"), table_name="risk_events")
    op.drop_index(op.f("ix_risk_events_mode"), table_name="risk_events")
    op.drop_index(op.f("ix_risk_events_ts"), table_name="risk_events")
    op.drop_table("risk_events")
    op.drop_table("system_state")
