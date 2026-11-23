"""Apply a complete Groww sync to the Groww Tracker (`user_watchlist_items`).

Display/tracking only: nothing here places or changes an order, and nothing in trading,
sizing, exits or the brain reads these rows. Rules (spec §6 "Applying to the tracker"):

- Only a `complete` sync is applied, and only its `confirmed` rows change anything.
- Every overwritten field writes one `UserWatchlistItemChange` (changed_by="groww_sync") first.
- Buy date (`added_at`) and note never change, except a re-buy after "not held" or of a row the
  owner removed or sold by hand (and a new row), which gets the sync day as its buy date.
- A stock linked to Groww that the sync no longer holds stays on the list, marked not held.
  Rows never linked to Groww are never marked not held.
- Values are written only when they differ, so repeating the same sync writes no history.

None of these functions commit; the caller does (run_sync commits after applying).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from typing import Any

from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.orm import Session

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.groww import (
    HELD,
    HELD_UNKNOWN,
    MATCH_CONFIRMED,
    MATCH_SUGGESTED,
    NOT_HELD,
    SOURCE_GROWW,
    SOURCE_MANUAL,
    SYNC_COMPLETE,
    SYNC_EMPTY,
    SYNC_PARTIAL,
    GrowwHolding,
    GrowwSync,
    StockAlias,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.user_watchlist import (
    UserWatchlistItem,
    UserWatchlistItemChange,
    UserWatchlistSale,
)

PROVIDER = "groww"
CHANGED_BY = "groww_sync"
_EPS = 1e-9


def _num_str(value: float | None) -> str | None:
    return None if value is None else str(float(value))


def _dt_str(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) < _EPS


def sync_day(sync: GrowwSync) -> datetime:
    """IST midnight of the day the sync started (tz-aware)."""
    started = sync.started_at or utcnow()
    return datetime.combine(started.astimezone(IST).date(), time.min, tzinfo=IST)


def _record(db: Session, item: UserWatchlistItem, field: str, old: str | None, new: str | None, sync_id):
    db.add(
        UserWatchlistItemChange(
            item_id=item.id,
            field=field,
            old_value=old,
            new_value=new,
            changed_by=CHANGED_BY,
            sync_id=sync_id,
        )
    )


def _set_num(db, item, field: str, new: float | None, sync_id) -> bool:
    old = getattr(item, field)
    if _same(old, new):
        return False
    _record(db, item, field, _num_str(old), _num_str(new), sync_id)
    setattr(item, field, new)
    return True


def _set_text(db, item, field: str, new: str | None, sync_id) -> bool:
    old = getattr(item, field)
    if old == new:
        return False
    _record(db, item, field, old, new, sync_id)
    setattr(item, field, new)
    return True


def _set_dt(db, item, field: str, new: datetime | None, sync_id) -> bool:
    old = getattr(item, field)
    if old == new:
        return False
    _record(db, item, field, _dt_str(old), _dt_str(new), sync_id)
    setattr(item, field, new)
    return True


def _mark_not_held(db: Session, item: UserWatchlistItem, sync_id: int) -> bool:
    """Confirmed zero: quantity 0 (so the drop shows as an unconfirmed sale), held_state not_held.

    The row stays on the list; buy price, buy date and note are kept.
    """
    if item.held_state == NOT_HELD:
        return False
    if item.quantity is not None:
        _set_num(db, item, "quantity", 0.0, sync_id)
    _set_text(db, item, "held_state", NOT_HELD, sync_id)
    return True


def _empty_counts() -> dict[str, int]:
    return {"updated": 0, "added": 0, "not_held": 0, "pending_sale": 0, "needs_matching": 0}


def _changed_after(item: UserWatchlistItem, sync: GrowwSync) -> bool:
    """True when the owner removed (or sold by hand) this row after the sync finished: that sync says nothing
    about it any more, so applying it again must not bring the row back or rewrite it."""
    return (
        item.removed_at is not None
        and sync.finished_at is not None
        and item.removed_at > sync.finished_at
    )


def apply_sync(db: Session, sync: GrowwSync, *, user_id: int, only_isins: set[str] | None = None) -> dict:
    """Apply one complete sync's confirmed rows to this user's tracker rows. Does not commit.

    `only_isins` is for a confirmation: only those ISINs are applied, and no other row is marked not held.
    A row the owner removed after this sync finished is never touched, whichever way it is applied."""
    counts = _empty_counts()
    if sync.status != SYNC_COMPLETE:
        return counts
    sid = sync.id
    holdings = list(
        db.scalars(select(GrowwHolding).where(GrowwHolding.sync_id == sid).order_by(GrowwHolding.id))
    )
    present_isins = {h.isin for h in holdings}
    confirmed = [h for h in holdings if h.match_state == MATCH_CONFIRMED and h.instrument_id is not None]
    counts["needs_matching"] = len(holdings) - len(confirmed)

    inst_ids = {h.instrument_id for h in confirmed}
    symbols = (
        dict(
            db.execute(
                select(Instrument.id, Instrument.tradingsymbol).where(Instrument.id.in_(inst_ids))
            ).all()
        )
        if inst_ids
        else {}
    )
    # Group by target tracker row. More than one Groww row for one stock (same ISIN twice, or two
    # ISINs matched to the same stock) is ambiguous: apply none of them, touch nothing for that stock.
    by_symbol: dict[str, list[GrowwHolding]] = {}
    for h in confirmed:
        symbol = symbols.get(h.instrument_id)
        if symbol is None:
            counts["needs_matching"] += 1
            continue
        by_symbol.setdefault(symbol, []).append(h)
    conflicted_symbols = {sym for sym, rows in by_symbol.items() if len(rows) > 1}
    conflicted_isins = {h.isin for sym in conflicted_symbols for h in by_symbol[sym]}
    counts["needs_matching"] += sum(len(by_symbol[sym]) for sym in conflicted_symbols)
    isin_symbol = {rows[0].isin: sym for sym, rows in by_symbol.items() if sym not in conflicted_symbols}
    day = sync_day(sync)

    for symbol, rows in by_symbol.items():
        if symbol in conflicted_symbols:
            continue
        h = rows[0]
        if only_isins is not None and h.isin not in only_isins:
            continue
        item = db.scalar(
            select(UserWatchlistItem).where(
                UserWatchlistItem.user_id == user_id, UserWatchlistItem.symbol == symbol
            )
        )
        qty = h.quantity
        if item is not None and _changed_after(item, sync):
            continue

        if qty is None or qty <= 0:
            # Present with quantity 0: confirmed zero, only for a row linked to this ISIN.
            if item is not None and item.groww_isin == h.isin and _mark_not_held(db, item, sid):
                counts["not_held"] += 1
                if pending_sale_qty(db, item) is not None:
                    counts["pending_sale"] += 1
            continue

        if item is None:
            item = UserWatchlistItem(
                user_id=user_id,
                symbol=symbol,
                source=SOURCE_GROWW,
                groww_isin=h.isin,
                quantity=qty,
                buy_price=h.average_price,
                added_at=day,
                held_state=HELD,
                note=None,
                groww_synced_at=sync.finished_at,
            )
            db.add(item)
            db.flush()
            _record(db, item, "created", None, SOURCE_GROWW, sid)
            counts["added"] += 1
            continue

        changed = False
        was_removed = item.removed_at is not None
        if was_removed:
            changed |= _set_dt(db, item, "removed_at", None, sid)
        if item.held_state == NOT_HELD or was_removed:
            # Re-buy after a confirmed zero, or a row the owner removed or sold by hand: a new holding,
            # so the buy date and Day count restart (the old date stays in the change history).
            changed |= _set_dt(db, item, "added_at", day, sid)
        changed |= _set_text(db, item, "groww_isin", h.isin, sid)
        old_qty = item.quantity
        changed |= _set_num(db, item, "quantity", qty, sid)
        changed |= _set_num(db, item, "buy_price", h.average_price, sid)
        changed |= _set_text(db, item, "held_state", HELD, sid)
        item.groww_synced_at = sync.finished_at
        if changed:
            counts["updated"] += 1
        if old_qty is not None and qty < old_qty - _EPS:
            counts["pending_sale"] += 1

    # Linked rows this sync no longer backs: their ISIN is absent, or it now belongs to another stock
    # (match moved). Both are confirmed zero; a moved ISIN is also unlinked from the old row.
    # A confirmation (`only_isins`) looks only at the rows linked to the ISINs just confirmed: an ISIN
    # that moved to another stock frees its old row, and nothing else is marked not held.
    linked = db.scalars(
        select(UserWatchlistItem).where(
            UserWatchlistItem.user_id == user_id, UserWatchlistItem.groww_isin.is_not(None)
        )
    )
    for item in list(linked):
        if item.symbol in conflicted_symbols or item.groww_isin in conflicted_isins:
            continue
        if only_isins is not None and item.groww_isin not in only_isins:
            continue
        if _changed_after(item, sync):
            continue
        moved = item.groww_isin in isin_symbol and isin_symbol[item.groww_isin] != item.symbol
        if not moved and item.groww_isin in present_isins:
            continue
        if _mark_not_held(db, item, sid):
            counts["not_held"] += 1
            if pending_sale_qty(db, item) is not None:
                counts["pending_sale"] += 1
        if moved:
            _set_text(db, item, "groww_isin", None, sid)
    db.flush()
    return counts


def _latest_stored_sync(db: Session) -> GrowwSync | None:
    """Latest sync that stored holdings (complete or partial)."""
    return db.scalar(
        select(GrowwSync)
        .where(GrowwSync.status.in_((SYNC_COMPLETE, SYNC_PARTIAL)))
        .order_by(GrowwSync.id.desc())
        .limit(1)
    )


def _latest_complete_sync(db: Session) -> GrowwSync | None:
    return db.scalar(
        select(GrowwSync).where(GrowwSync.status == SYNC_COMPLETE).order_by(GrowwSync.id.desc()).limit(1)
    )


def _save_alias(db: Session, *, user_id: int, isin: str, instrument_id: int, external_symbol: str | None):
    alias = db.scalar(
        select(StockAlias).where(StockAlias.provider == PROVIDER, StockAlias.external_id == isin)
    )
    if alias is None:
        alias = StockAlias(provider=PROVIDER, external_id=isin)
        db.add(alias)
    alias.instrument_id = instrument_id
    alias.external_symbol = external_symbol or alias.external_symbol
    alias.confirmed_by_user_id = user_id
    alias.confirmed_at = utcnow()


def _confirm_rows(db: Session, syncs: list[GrowwSync], isin: str, instrument_id: int) -> str | None:
    """Mark that ISIN's rows confirmed in the given syncs; returns a Groww symbol seen."""
    symbol = None
    for sync in syncs:
        for row in db.scalars(
            select(GrowwHolding).where(GrowwHolding.sync_id == sync.id, GrowwHolding.isin == isin)
        ):
            row.instrument_id = instrument_id
            row.match_state = MATCH_CONFIRMED
            symbol = symbol or row.trading_symbol
    return symbol


def _target_syncs(db: Session) -> list[GrowwSync]:
    out: list[GrowwSync] = []
    for sync in (_latest_stored_sync(db), _latest_complete_sync(db)):
        if sync is not None and all(s.id != sync.id for s in out):
            out.append(sync)
    return out


def _reapply_latest(db: Session, user_id: int, isins: set[str]) -> None:
    """Apply the latest complete sync for just these ISINs, the ones the owner has now confirmed."""
    db.flush()
    latest = _latest_complete_sync(db)
    if latest is not None:
        apply_sync(db, latest, user_id=user_id, only_isins=isins)


def confirm_match(db: Session, *, user_id: int, isin: str, instrument_id: int) -> None:
    """Owner confirms ISIN -> stock: save it for every future sync, then re-apply. Does not commit."""
    if db.get(Instrument, instrument_id) is None:
        raise ValueError("unknown instrument")
    symbol = _confirm_rows(db, _target_syncs(db), isin, instrument_id)
    _save_alias(db, user_id=user_id, isin=isin, instrument_id=instrument_id, external_symbol=symbol)
    _reapply_latest(db, user_id, {isin})


def confirm_all_suggested(db: Session, *, user_id: int) -> int:
    """Confirm every suggested match in the latest sync; returns how many ISINs were confirmed."""
    syncs = _target_syncs(db)
    pending: dict[str, int] = {}
    for sync in syncs:
        for row in db.scalars(
            select(GrowwHolding).where(
                GrowwHolding.sync_id == sync.id, GrowwHolding.match_state == MATCH_SUGGESTED
            )
        ):
            if row.instrument_id is not None:
                pending.setdefault(row.isin, row.instrument_id)
    for isin, instrument_id in pending.items():
        symbol = _confirm_rows(db, syncs, isin, instrument_id)
        _save_alias(db, user_id=user_id, isin=isin, instrument_id=instrument_id, external_symbol=symbol)
    if pending:
        _reapply_latest(db, user_id, set(pending))
    return len(pending)


def confirm_empty(db: Session, *, user_id: int, sync_id: int) -> None:
    """Owner confirms "I hold nothing": the empty sync becomes complete and is applied."""
    sync = db.get(GrowwSync, sync_id)
    if sync is None or sync.status != SYNC_EMPTY:
        raise ValueError("not an unconfirmed empty sync")
    newer = db.scalar(select(GrowwSync.id).where(GrowwSync.id > sync.id).limit(1))
    if newer is not None:
        # A newer sync exists: confirming this old one could wipe holdings Groww has shown since.
        raise ValueError("a newer Groww sync exists; only the latest empty sync can be confirmed")
    sync.status = SYNC_COMPLETE
    db.flush()
    apply_sync(db, sync, user_id=user_id)


def _parse(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def pending_sale_qty_for(db: Session, items: Sequence[UserWatchlistItem]) -> dict[int, float | None]:
    """`pending_sale_qty` for many rows at once: ONE query for their quantity history and ONE for their sales,
    however many rows there are. The answer for each row is the same as asking row by row.

    Shares Groww shows as gone that no confirmed sale has covered yet; None when there are none.
    Read in time order: each drop Groww showed adds to the pending shares, and each confirmed sale takes
    its shares off (a sale with no quantity clears everything before it). Confirming only part of a drop
    therefore leaves the rest to confirm, and a sale never takes the count below zero. A drop and a sale
    at the same moment count the drop first, as before."""
    if not items:
        return {}
    # (when, 0 = drop / 1 = sale, shares; inf = all), per row
    events: dict[int, list[tuple[datetime, int, float]]] = {item.id: [] for item in items}
    for item_id, old_s, new_s, at in db.execute(
        select(
            UserWatchlistItemChange.item_id,
            UserWatchlistItemChange.old_value,
            UserWatchlistItemChange.new_value,
            UserWatchlistItemChange.changed_at,
        ).where(
            UserWatchlistItemChange.item_id.in_(list(events)),
            UserWatchlistItemChange.field == "quantity",
            UserWatchlistItemChange.changed_by == CHANGED_BY,
        )
    ).all():
        old, new = _parse(old_s), _parse(new_s)
        if old is not None and new is not None and new < old:
            events[item_id].append((at, 0, old - new))
    owners: dict[tuple[int, str], list[int]] = {}
    for item in items:
        owners.setdefault((item.user_id, item.symbol), []).append(item.id)
    for user_id, symbol, qty, at in db.execute(
        select(
            UserWatchlistSale.user_id,
            UserWatchlistSale.symbol,
            UserWatchlistSale.quantity,
            UserWatchlistSale.created_at,
        ).where(tuple_(UserWatchlistSale.user_id, UserWatchlistSale.symbol).in_(list(owners)))
    ).all():
        for item_id in owners.get((user_id, symbol), ()):
            events[item_id].append((at, 1, float("inf") if qty is None else float(qty)))
    out: dict[int, float | None] = {}
    for item_id, found in events.items():
        pending = 0.0
        for _, kind, shares in sorted(found, key=lambda e: (e[0], e[1])):
            pending = pending + shares if kind == 0 else max(0.0, pending - shares)
        out[item_id] = pending if pending > _EPS else None
    return out


def pending_sale_qty(db: Session, item: UserWatchlistItem) -> float | None:
    """Shares Groww shows as gone that no confirmed sale has covered yet (see `pending_sale_qty_for`)."""
    return pending_sale_qty_for(db, [item])[item.id]


def groww_held_symbols(db: Session) -> list[str]:
    """Symbols Groww currently shows as held (any user), for the daily price collection. A stock the owner
    removed from the tracker is left out, so it stops getting daily candles (a later sync that shows it held
    brings the row, and its prices, back)."""
    return list(
        db.scalars(
            select(UserWatchlistItem.symbol)
            .where(UserWatchlistItem.held_state == HELD, UserWatchlistItem.removed_at.is_(None))
            .distinct()
            .order_by(UserWatchlistItem.symbol)
        )
    )


def is_currently_held_clause() -> Any:
    """The one definition of "currently held" that reports and the tracker share."""
    return or_(
        UserWatchlistItem.held_state == HELD,
        and_(
            UserWatchlistItem.source == SOURCE_MANUAL,
            UserWatchlistItem.held_state == HELD_UNKNOWN,
            UserWatchlistItem.buy_price.is_not(None),
        ),
    )
