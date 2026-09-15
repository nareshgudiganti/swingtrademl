"""barrier_label_definition

Revision ID: c4a1f7b28d93
Revises: 8f3d2a9c6b41
Create Date: 2026-09-15 10:40:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a1f7b28d93"
down_revision: str | None = "8f3d2a9c6b41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default is "endpoint", NOT the model's "barrier" default, and the
    # difference is the whole point of this migration: every row that already
    # exists was trained on — or scored against — the old close-only question
    # ("was it higher at the horizon"). Backfilling those as "barrier" would
    # tell the calibration report that losing trades had been counted
    # correctly, which is precisely the silent error this column exists to
    # prevent. New rows written by the ORM supply "barrier" explicitly.
    op.add_column(
        "ml_models",
        sa.Column("label_kind", sa.String(length=16), nullable=False, server_default="endpoint"),
    )
    op.create_index(op.f("ix_ml_models_label_kind"), "ml_models", ["label_kind"], unique=False)

    # Nullable: endpoint models have no lower barrier, and inventing one for
    # them would misdescribe what they were trained on.
    op.add_column("ml_models", sa.Column("stop_return_pct", sa.Float(), nullable=True))

    op.add_column(
        "predictions",
        sa.Column("label_kind", sa.String(length=16), nullable=False, server_default="endpoint"),
    )
    op.create_index(op.f("ix_predictions_label_kind"), "predictions", ["label_kind"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_predictions_label_kind"), table_name="predictions")
    op.drop_column("predictions", "label_kind")
    op.drop_column("ml_models", "stop_return_pct")
    op.drop_index(op.f("ix_ml_models_label_kind"), table_name="ml_models")
    op.drop_column("ml_models", "label_kind")
