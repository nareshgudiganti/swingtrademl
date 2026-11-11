"""Company filings: announcements and shareholding, for the Company and news tab

Two new tables, nothing else touched. Display only. Named company_filing_* so they cannot clash with any older
table of a similar name.

Revision ID: f9c3o7m1p5n2
Revises: c8d2p9s1t4k6
Create Date: 2026-10-26 15:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9c3o7m1p5n2"
down_revision: str | None = "c8d2p9s1t4k6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "company_filing_announcements",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("seq_id", sa.String(40), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("attachment_url", sa.String(400), nullable=True),
        *_stamps(),
        sa.UniqueConstraint("source", "seq_id", name="uq_company_filing_announcement"),
    )
    op.create_index("ix_company_filing_announcements_symbol", "company_filing_announcements", ["symbol"])
    op.create_index(
        "ix_company_filing_announcements_announced_at", "company_filing_announcements", ["announced_at"]
    )

    op.create_table(
        "company_filing_shareholdings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("filed_on", sa.Date(), nullable=False),
        sa.Column("promoter_pct", sa.Float(), nullable=False),
        sa.Column("public_pct", sa.Float(), nullable=False),
        *_stamps(),
        sa.UniqueConstraint("symbol", "source", "as_of", name="uq_company_filing_shareholding"),
    )
    op.create_index("ix_company_filing_shareholdings_symbol", "company_filing_shareholdings", ["symbol"])
    op.create_index("ix_company_filing_shareholdings_as_of", "company_filing_shareholdings", ["as_of"])


def downgrade() -> None:
    op.drop_table("company_filing_shareholdings")
    op.drop_table("company_filing_announcements")
