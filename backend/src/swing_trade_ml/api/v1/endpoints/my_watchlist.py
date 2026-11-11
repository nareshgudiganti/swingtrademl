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
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select

from swing_trade_ml.api.deps import SELF_SERVICE_NEEDS_PERSON, DbSession, Principal, get_principal
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import StockScore
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import score_history
from swing_trade_ml.services import watchlist_tracker as tracker

router = APIRouter(prefix="/me/watchlist", tags=["my-watchlist"])

#: At most this many stocks on one person's list at a time (removed ones do not count).
MAX_ITEMS = 50
#: The buy date can be moved back at most this far (the plan's horizon is 15 trading days).
MAX_BACKDATE_DAYS = 120
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
    buy_price: float | None = None
    quantity: float | None = None


class WatchlistOut(BaseModel):
    items: list[WatchlistItemOut]
    limit: int


class WatchlistAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=200)


class WatchlistPatch(BaseModel):
    buy_price: float | None = Field(default=None, gt=0)
    quantity: float | None = Field(default=None, gt=0, le=1e9)
    #: IST calendar date the person bought it. Null or omitted leaves the date as it is.
    bought_on: date | None = None
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
        symbol=item.symbol, name=name, added_at=item.added_at,
        removed_at=item.removed_at,
        note=item.note,
        buy_price=item.buy_price,
        quantity=item.quantity,
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


@router.patch("/{symbol}", response_model=WatchlistItemOut)
def update_stock(symbol: str, body: WatchlistPatch, db: DbSession, me: Me) -> WatchlistItemOut:
    """Set or clear your own Groww buy price and/or note. Only fields you send change."""
    sym = _clean(symbol)
    item = _mine(db, me, sym)
    if item is None or item.removed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{sym} is not on your list.")
    if "buy_price" in body.model_fields_set:
        item.buy_price = body.buy_price
    if "quantity" in body.model_fields_set:
        item.quantity = body.quantity
    if "bought_on" in body.model_fields_set and body.bought_on is not None:
        today = datetime.now(tracker.IST).date()
        if body.bought_on > today:
            raise HTTPException(422, "The buy date cannot be in the future.")
        if body.bought_on < today - timedelta(days=MAX_BACKDATE_DAYS):
            raise HTTPException(422, f"The buy date cannot be more than {MAX_BACKDATE_DAYS} days ago.")
        item.added_at = datetime.combine(body.bought_on, datetime.min.time(), tzinfo=tracker.IST)
    if "note" in body.model_fields_set:
        item.note = body.note.strip() if body.note and body.note.strip() else None
    db.commit()
    db.refresh(item)
    return _out(item, _names(db, [sym]).get(sym))


@router.get("/tracker")
def my_tracker(db: DbSession, me: Me) -> dict:
    """Read-only tracker over the caller's ACTIVE stocks (newest first). Display only."""
    rows = list(
        db.execute(
            select(UserWatchlistItem)
            .where(UserWatchlistItem.user_id == me.id, UserWatchlistItem.removed_at.is_(None))
            .order_by(UserWatchlistItem.added_at.desc())
        ).scalars()
    )
    if not rows:
        return {"as_of": None, "horizon_days": tracker.HORIZON_DAYS, "items": []}
    inst = {
        t: (i, n)
        for i, t, n in db.execute(
            select(Instrument.id, Instrument.tradingsymbol, Instrument.name).where(
                Instrument.exchange == EXCHANGE, Instrument.tradingsymbol.in_([r.symbol for r in rows])
            )
        ).all()
    }
    ids = [i for i, _ in inst.values()]
    since = tracker.ist_date(min(r.added_at for r in rows)) - timedelta(days=10)
    since_ts = datetime.combine(since, datetime.min.time(), tzinfo=tracker.IST)
    candles: dict[int, list[tuple[date, float]]] = {}
    for iid, ts, close in db.execute(
        select(Candle.instrument_id, Candle.ts, Candle.close)
        .where(Candle.instrument_id.in_(ids), Candle.interval == "day", Candle.ts >= since_ts)
        .order_by(Candle.instrument_id, Candle.ts)
    ).all():
        candles.setdefault(iid, []).append((tracker.ist_date(ts), close))
    by_stock: dict[int, list[StockScore]] = {}
    for row in db.execute(
        select(StockScore)
        .where(StockScore.instrument_id.in_(ids), StockScore.as_of >= since)
        .order_by(StockScore.instrument_id, StockScore.as_of)
    ).scalars():
        by_stock.setdefault(row.instrument_id, []).append(row)
    # One model per stock, so another model's score never reads as this stock's own change.
    scores: dict[int, list[tuple[date, float]]] = {
        iid: [(r.as_of, r.score) for r in score_history.one_model_rows(rows)]
        for iid, rows in by_stock.items()
    }
    items = []
    for r in rows:
        iid, name = inst.get(r.symbol, (None, None))
        items.append(
            tracker.build_item(
                symbol=r.symbol,
                name=name,
                added_at=r.added_at,
                note=r.note,
                buy_price=r.buy_price,
                quantity=r.quantity,
                candles=candles.get(iid, []),
                scores=scores.get(iid, []),
                today=tracker.today_ist(),
            )
        )
    last_dates = [c[-1][0] for c in candles.values() if c]
    return {
        "as_of": max(last_dates).isoformat() if last_dates else None,
        "horizon_days": tracker.HORIZON_DAYS,
        "items": items,
    }
