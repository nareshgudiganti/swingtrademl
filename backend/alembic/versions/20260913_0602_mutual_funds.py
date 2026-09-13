"""mutual_funds

Revision ID: 06b7f1c1db82
Revises: 24df8a18dfa3
Create Date: 2026-09-13 06:02:27.721314+00:00
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '06b7f1c1db82'
down_revision: str | None = '24df8a18dfa3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mutual_funds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("amc_name", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mutual_funds_scheme_code", "mutual_funds", ["scheme_code"], unique=True)
    op.create_index("ix_mutual_funds_name", "mutual_funds", ["name"])
    op.create_index("ix_mutual_funds_is_tracked", "mutual_funds", ["is_tracked"])

    op.create_table(
        "mutual_fund_navs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.UniqueConstraint("scheme_id", "date", name="uq_mf_nav_scheme_date"),
    )
    op.create_index("ix_mutual_fund_navs_scheme_id", "mutual_fund_navs", ["scheme_id"])
    op.create_index("ix_mutual_fund_navs_date", "mutual_fund_navs", ["date"])

    op.create_table(
        "mutual_fund_holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_id", sa.Integer(), sa.ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("units", sa.Float(), nullable=False),
        sa.Column("purchase_nav", sa.Float(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mutual_fund_holdings_scheme_id", "mutual_fund_holdings", ["scheme_id"])


def downgrade() -> None:
    op.drop_table("mutual_fund_holdings")
    op.drop_index("ix_mutual_fund_navs_date", table_name="mutual_fund_navs")
    op.drop_index("ix_mutual_fund_navs_scheme_id", table_name="mutual_fund_navs")
    op.drop_table("mutual_fund_navs")
    op.drop_index("ix_mutual_funds_is_tracked", table_name="mutual_funds")
    op.drop_index("ix_mutual_funds_name", table_name="mutual_funds")
    op.drop_index("ix_mutual_funds_scheme_code", table_name="mutual_funds")
    op.drop_table("mutual_funds")
