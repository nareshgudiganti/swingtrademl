"""My Watchlist: each signed-in person's own list of stocks (new look, wave 2).

Self-service on purpose (api/deps.py SELF_SERVICE_ROUTES): any signed-in person
may read and change THEIR OWN list, whatever their role or plan. Every handler
takes the user id from the credential (`_me`), never from the body or the path,
so nobody can see or change somebody else's list. The API key has no person
behind it and is refused.

This list is display only. It is not the bot's global watchlist
(`/instruments/watchlist`, `instruments.is_watchlisted`), and nothing in
trading, sizing, exits, limits or the brain reads it.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from swing_trade_ml.api.deps import SELF_SERVICE_NEEDS_PERSON, DbSession, Principal, get_principal
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem

router = APIRouter(prefix="/me/watchlist", tags=["my-watchlist"])

#: At most this many stocks on one person's list at a time (removed ones do not count).
MAX_ITEMS = 50
EXCHANGE = "NSE"
_SYMBOL = re.compile(r"^[A-Z0-9&_.\-]{1,32}$")


def _me(principal: Annotated[Principal, Depends(get_principal)]) -> User:
    """The signed-in person. The API key is refused: a shared machine key has no list of its own."""
    if principal.user is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, SELF_SERVICE_NEEDS_PERSON)
    return principal.user


Me = Annotated[User, Depends(_me)]


class WatchlistItemOut(BaseModel):
    symbol: str
    name: str | None
    added_at: datetime
    removed_at: datetime | None
    note: str | None


class WatchlistOut(BaseModel):
    items: list[WatchlistItemOut]
    limit: int


class WatchlistAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=200)


class InstrumentHit(BaseModel):
    symbol: str
    name: str | None


def _clean(symbol: str) -> str:
    s = symbol.strip().upper()
    if not _SYMBOL.match(s):
        raise HTTPException(422, "That is not a stock symbol.")
    return s


def _instrument(db: DbSession, symbol: str) -> Instrument | None:
    return db.execute(
        select(Instrument).where(
            Instrument.exchange == EXCHANGE,
            Instrument.tradingsymbol == symbol,
            Instrument.is_active.is_(True),
        )
    ).scalar_one_or_none()


def _names(db: DbSession, symbols: list[str]) -> dict[str, str | None]:
    if not symbols:
        return {}
    rows = db.execute(
        select(Instrument.tradingsymbol, Instrument.name).where(
            Instrument.exchange == EXCHANGE, Instrument.tradingsymbol.in_(symbols)
        )
    ).all()
    return dict(rows)


def _out(item: UserWatchlistItem, name: str | None) -> WatchlistItemOut:
    return WatchlistItemOut(
        symbol=item.symbol, name=name, added_at=item.added_at, removed_at=item.removed_at, note=item.note
    )


def _mine(db: DbSession, me: User, symbol: str) -> UserWatchlistItem | None:
    return db.execute(
        select(UserWatchlistItem).where(
            UserWatchlistItem.user_id == me.id, UserWatchlistItem.symbol == symbol
        )
    ).scalar_one_or_none()


@router.get("", response_model=WatchlistOut)
def my_watchlist(db: DbSession, me: Me) -> WatchlistOut:
    """The caller's own list: stocks on it (newest first), then removed ones."""
    rows = list(
        db.execute(
            select(UserWatchlistItem)
            .where(UserWatchlistItem.user_id == me.id)
            .order_by(UserWatchlistItem.removed_at.is_not(None), UserWatchlistItem.added_at.desc())
        ).scalars()
    )
    names = _names(db, [r.symbol for r in rows])
    return WatchlistOut(items=[_out(r, names.get(r.symbol)) for r in rows], limit=MAX_ITEMS)


@router.get("/search", response_model=list[InstrumentHit])
def search_stocks(db: DbSession, me: Me, q: str = Query(min_length=1, max_length=32)) -> list[InstrumentHit]:
    """Stocks to add, by symbol or company name (NSE, active only). Names and symbols only."""
    upper = q.strip().upper()
    if not upper:
        return []
    like = upper.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    starts = Instrument.tradingsymbol.ilike(f"{like}%", escape="\\")
    watched = Instrument.is_watchlisted.is_(True)
    priority = case(
        (Instrument.tradingsymbol == upper, 0), (starts & watched, 1), (starts, 2), (watched, 3), else_=4
    )
    rows = db.execute(
        select(Instrument.tradingsymbol, Instrument.name)
        .where(
            Instrument.exchange == EXCHANGE,
            Instrument.is_active.is_(True),
            starts | Instrument.name.ilike(f"%{like}%", escape="\\"),
        )
        .order_by(priority, Instrument.tradingsymbol)
        .limit(8)
    ).all()
    return [InstrumentHit(symbol=s, name=n) for s, n in rows]


@router.post("", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED)
def add_stock(body: WatchlistAdd, db: DbSession, me: Me) -> WatchlistItemOut:
    """Put a stock on the caller's own list (or back on it, if it was removed)."""
    symbol = _clean(body.symbol)
    inst = _instrument(db, symbol)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{symbol} is not a stock we know on the NSE.")
    item = _mine(db, me, symbol)
    if item is not None and item.removed_at is None:
        return _out(item, inst.name)  # already on the list: nothing to do
    count = db.execute(
        select(func.count())
        .select_from(UserWatchlistItem)
        .where(UserWatchlistItem.user_id == me.id, UserWatchlistItem.removed_at.is_(None))
    ).scalar_one()
    if count >= MAX_ITEMS:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Your list is full ({MAX_ITEMS} stocks). Remove one to add another."
        )
    note = body.note.strip() if body.note and body.note.strip() else None
    if item is None:
        item = UserWatchlistItem(user_id=me.id, symbol=symbol, added_at=utcnow(), note=note)
        db.add(item)
    else:
        item.removed_at = None
        item.added_at = utcnow()
        item.note = note
    db.commit()
    db.refresh(item)
    return _out(item, inst.name)


@router.delete("/{symbol}", response_model=WatchlistItemOut)
def remove_stock(symbol: str, db: DbSession, me: Me) -> WatchlistItemOut:
    """Take a stock off the caller's own list. Kept under "Removed"; adding it again brings it back."""
    sym = _clean(symbol)
    item = _mine(db, me, sym)
    if item is None or item.removed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{sym} is not on your list.")
    item.removed_at = utcnow()
    db.commit()
    db.refresh(item)
    return _out(item, _names(db, [sym]).get(sym))
