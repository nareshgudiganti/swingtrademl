"""Merge the two migration heads that PRs #191 and #194 each created on top of wlquantity01

Revision ID: mergeheads01
Revises: ownerprivate01, f11m0d3l5c0r3
Create Date: 2026-11-11 10:00:00.000000+00:00

No schema change. Both parents were merged to main without ever being applied to production
(the deploy gate was red), so main had two heads and `alembic upgrade head` would have refused to run.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "mergeheads01"
down_revision: str | Sequence[str] | None = ("ownerprivate01", "f11m0d3l5c0r3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
