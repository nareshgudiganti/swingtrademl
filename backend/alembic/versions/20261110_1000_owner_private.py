"""strategies.owner_private: an explicit "the owner's own book" flag, with a deterministic backfill

A plan member must never see the owner's real holdings or manual testing book. Until now that was
guessed from data markers (names, mode, positions). This adds the flag itself. Safe default: TRUE,
so a strategy nobody has classified stays private until reviewed.

Backfill rule table (runs ONLY when the column is first added, so a later re-run never overwrites
a review; every later row is set by the code that creates it):

  Step 1  owner_private = TRUE  (private markers; same as services/plans.is_owner_private_strategy)
          - name is real_trading or tester_paper
          - type is tester_paper (never scanned) or long_term_value (owner's hand-recorded book)
          - execution_mode = 'advisory' AND type is not 'brain' AND (mode = 'live'
            OR the strategy owns a live-mode position or trade)   -> import-holdings style books
  Step 2  owner_private = FALSE (positively recognised member-facing kinds)
          - type 'brain' (the staged strategy), unless a hand-book name
          - type 'ml_swing' or 'sma_crossover', mode <> 'live', and NOT step 1
  Step 3  everything else (unknown type, live auto strategy, ...) keeps the default TRUE

Revision ID: ownerprivate01
Revises: wlquantity01
Create Date: 2026-11-10 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ownerprivate01"
down_revision: str | None = "wlquantity01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the policy constants: a migration must not change when the code later does.
HAND_BOOK_NAMES = ("real_trading", "tester_paper")
HAND_BOOK_TYPES = ("tester_paper", "long_term_value")
MEMBER_RULE_TYPES = ("ml_swing", "sma_crossover")

_NAMES = ", ".join(f"'{n}'" for n in HAND_BOOK_NAMES)
_TYPES = ", ".join(f"'{t}'" for t in HAND_BOOK_TYPES)
_MEMBER = ", ".join(f"'{t}'" for t in MEMBER_RULE_TYPES)

# One definition of "private by markers", used by step 1 and negated in step 2.
PRIVATE_MARKERS = f"""(
    name IN ({_NAMES})
    OR strategy_type IN ({_TYPES})
    OR (
        execution_mode = 'advisory'
        AND strategy_type <> 'brain'
        AND (
            mode = 'live'
            OR EXISTS (SELECT 1 FROM positions p WHERE p.strategy_id = strategies.id AND p.mode = 'live')
            OR EXISTS (SELECT 1 FROM trades t WHERE t.strategy_id = strategies.id AND t.mode = 'live')
        )
    )
)"""


def _has_column(bind) -> bool:
    return "owner_private" in {c["name"] for c in sa.inspect(bind).get_columns("strategies")}


def backfill(bind) -> None:
    """The deterministic classification (see the module docstring). Safe to run twice."""
    bind.execute(sa.text(f"UPDATE strategies SET owner_private = TRUE WHERE {PRIVATE_MARKERS}"))
    bind.execute(
        sa.text(
            "UPDATE strategies SET owner_private = FALSE "
            f"WHERE strategy_type = 'brain' AND name NOT IN ({_NAMES})"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE strategies SET owner_private = FALSE "
            f"WHERE strategy_type IN ({_MEMBER}) AND mode <> 'live' AND NOT {PRIVATE_MARKERS}"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        return  # already applied (or already reviewed): never overwrite
    op.add_column(
        "strategies",
        sa.Column("owner_private", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    backfill(bind)


def downgrade() -> None:
    if _has_column(op.get_bind()):
        op.drop_column("strategies", "owner_private")
