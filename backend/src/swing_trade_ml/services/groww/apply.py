"""Apply a complete Groww sync to the Groww Tracker (`user_watchlist_items`).

Display/tracking only: nothing here places or changes an order, and nothing in trading,
sizing, exits or the brain reads these rows. Rules (spec §6 "Applying to the tracker"):

- Only a `complete` sync is applied, and only its `confirmed` rows change anything.
- Every overwritten field writes one `UserWatchlistItemChange` (changed_by="groww_sync") first.
- Buy date (`added_at`) and note never change, except a re-buy after "not held" (and a new
  row), which gets the sync day as its buy date.
- A stock linked to Groww that the sync no longer holds stays on the list, marked not held.
  Rows never linked to Groww are never marked not held.
- Values are written only when they differ, so repeating the same sync writes no history.

None of these functions commit; the caller does (run_sync commits after applying).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy import and_, func, or_, select
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


def apply_sync(db: Session, sync: GrowwSync, *, user_id: int) -> dict:
    """Apply one complete sync's confirmed rows to this user's tracker rows. Does not commit."""
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
    day = sync_day(sync)
    seen_isins: set[str] = set()

    for h in confirmed:
        if h.isin in seen_isins:
            continue
        seen_isins.add(h.isin)
        symbol = symbols.get(h.instrument_id)
        if symbol is None:
            continue
        item = db.scalar(
            select(UserWatchlistItem).where(
                UserWatchlistItem.user_id == user_id, UserWatchlistItem.symbol == symbol
            )
        )
        qty = h.quantity

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
        if item.removed_at is not None:
            changed |= _set_dt(db, item, "removed_at", None, sid)
        if item.held_state == NOT_HELD:
            # Re-buy after a confirmed zero: a new holding, so the Day count restarts.
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

    # Linked rows whose ISIN this sync does not contain at all: confirmed zero.
    linked = db.scalars(
        select(UserWatchlistItem).where(
            UserWatchlistItem.user_id == user_id,
            UserWatchlistItem.groww_isin.is_not(None),
            UserWatchlistItem.held_state != NOT_HELD,
        )
    )
    for item in list(linked):
        if item.groww_isin in present_isins:
            continue
        if _mark_not_held(db, item, sid):
            counts["not_held"] += 1
            if pending_sale_qty(db, item) is not None:
                counts["pending_sale"] += 1
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


def _reapply_latest(db: Session, user_id: int) -> None:
    db.flush()
    latest = _latest_complete_sync(db)
    if latest is not None:
        apply_sync(db, latest, user_id=user_id)


def confirm_match(db: Session, *, user_id: int, isin: str, instrument_id: int) -> None:
    """Owner confirms ISIN -> stock: save it for every future sync, then re-apply. Does not commit."""
    if db.get(Instrument, instrument_id) is None:
        raise ValueError("unknown instrument")
    symbol = _confirm_rows(db, _target_syncs(db), isin, instrument_id)
    _save_alias(db, user_id=user_id, isin=isin, instrument_id=instrument_id, external_symbol=symbol)
    _reapply_latest(db, user_id)


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
        _reapply_latest(db, user_id)
    return len(pending)


def confirm_empty(db: Session, *, user_id: int, sync_id: int) -> None:
    """Owner confirms "I hold nothing": the empty sync becomes complete and is applied."""
    sync = db.get(GrowwSync, sync_id)
    if sync is None or sync.status != SYNC_EMPTY:
        raise ValueError("not an unconfirmed empty sync")
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


def pending_sale_qty(db: Session, item: UserWatchlistItem) -> float | None:
    """Shares Groww shows as gone since the last confirmed sale; None when there are none."""
    last_sale = db.scalar(
        select(func.max(UserWatchlistSale.created_at)).where(
            UserWatchlistSale.user_id == item.user_id, UserWatchlistSale.symbol == item.symbol
        )
    )
    q = select(UserWatchlistItemChange.old_value, UserWatchlistItemChange.new_value).where(
        UserWatchlistItemChange.item_id == item.id,
        UserWatchlistItemChange.field == "quantity",
        UserWatchlistItemChange.changed_by == CHANGED_BY,
    )
    if last_sale is not None:
        q = q.where(UserWatchlistItemChange.changed_at > last_sale)
    total = 0.0
    for old_s, new_s in db.execute(q).all():
        old, new = _parse(old_s), _parse(new_s)
        if old is not None and new is not None and new < old:
            total += old - new
    return total if total > _EPS else None


def groww_held_symbols(db: Session) -> list[str]:
    """Symbols Groww currently shows as held (any user), for the daily price collection."""
    return list(
        db.scalars(
            select(UserWatchlistItem.symbol)
            .where(UserWatchlistItem.held_state == HELD)
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
