# ruff: noqa: E501 (long explanatory lines)
"""model role: ml_models.model_role (fold / final / prod)

One new nullable column. Nothing is rewritten or removed. The only data step ADDS the value "prod" to the
currently ACTIVE rows of the three verified production names (swing_classifier, swing_classifier_midcap,
swing_classifier_smallcap) that have no role yet. Every other row stays null, which shadow lanes treat as "not
eligible". The upgrade is safe to run twice. The downgrade deliberately drops nothing: a recorded role is evidence.

Revision ID: mdlrole1a2b3
Revises: h05ao7p2k9d1
Create Date: 2026-11-03 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mdlrole1a2b3"
down_revision: str | None = "h05ao7p2k9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "model_role" not in {c["name"] for c in insp.get_columns("ml_models")}:
        op.add_column("ml_models", sa.Column("model_role", sa.String(8), nullable=True))
    op.execute(
        "UPDATE ml_models SET model_role = 'prod' "
        "WHERE model_role IS NULL AND status = 'ACTIVE' "
        "AND name IN ('swing_classifier', 'swing_classifier_midcap', 'swing_classifier_smallcap')"
    )


def downgrade() -> None:
    # Recorded roles are evidence; a schema step never removes them.
    pass
