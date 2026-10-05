"""Merge plans branch and main (Service 1 P0).

Revision ID: m3r6e5p1s1v1
Revises: 5a2f9d4e8c13, c7d8e9f0a1b2
Create Date: 2026-10-05 13:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "m3r6e5p1s1v1"
down_revision: str | Sequence[str] | None = ("5a2f9d4e8c13", "c7d8e9f0a1b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
