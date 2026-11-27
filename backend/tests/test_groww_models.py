"""Schema for the Groww holdings sync: defaults for old rows and alias uniqueness."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.db.models.groww import HELD_UNKNOWN, SOURCE_MANUAL, StockAlias
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem


def test_existing_rows_default_manual_unknown(db_session):
    user = User(username="groww_owner", hashed_password="x", is_active=True, role="owner", plan="pro")
    db_session.add(user)
    db_session.flush()
    item = UserWatchlistItem(user_id=user.id, symbol="RELIANCE")
    db_session.add(item)
    db_session.flush()
    db_session.refresh(item)
    assert item.source == SOURCE_MANUAL == "manual"
    assert item.held_state == HELD_UNKNOWN == "unknown"
    assert item.groww_isin is None
    assert item.groww_synced_at is None


def test_alias_unique_per_provider_isin(db_session):
    db_session.add(StockAlias(provider="groww", external_id="INE002A01018", external_symbol="RELIANCE"))
    db_session.flush()
    db_session.add(StockAlias(provider="groww", external_id="INE002A01018", external_symbol="RELIANCE2"))
    with pytest.raises(IntegrityError):
        db_session.flush()
