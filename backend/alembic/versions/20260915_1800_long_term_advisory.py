"""Enforce advisory execution on existing long-term strategies."""

from alembic import op

revision = "d5b2c8a39e04"
down_revision = "c4a1f7b28d93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE strategies SET execution_mode = 'advisory' "
               "WHERE strategy_type = 'long_term_value'")


def downgrade() -> None:
    # A code rollback must never re-arm automated execution.
    pass
