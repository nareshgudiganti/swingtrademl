"""Groww holdings sync: Refresh, status, and the owner's stock-matching screen.

Owner only (require_real_account) on every route: the Groww Tracker holds the owner's own real
shares, so it follows the same privacy rule as My Holdings. Display/tracking only: nothing here
places or changes an order, and nothing in trading, sizing, exits or the brain reads it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.api.deps import DbSession, Principal, require_real_account
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.groww import (
    MATCH_CONFIRMED,
    SYNC_COMPLETE,
    SYNC_PARTIAL,
    GrowwHolding,
    GrowwSync,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.groww import apply as groww_apply
from swing_trade_ml.services.groww import client as groww_client
from swing_trade_ml.services.groww import sync as groww_sync

router = APIRouter(prefix="/groww", tags=["groww"], dependencies=[Depends(require_real_account)])

Owner = Annotated[Principal, Depends(require_real_account)]

#: Refresh at most once a minute (spec §6 Connection).
REFRESH_EVERY = timedelta(seconds=60)
NOT_CONFIGURED = "Groww is not connected yet. Add the Groww keys on the server first."
NO_OWNER = "No owner account was found to update."
NOT_GROWW_OWNER = "Only the Groww account owner can do this."
TOO_SOON = "Groww was refreshed less than a minute ago. Try again soon."


def iso(value: datetime | None) -> str | None:
    """Timezone-aware ISO time (the screen converts to IST). A naive value is taken as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def status_payload(db: Session) -> dict:
    """The Groww connection status the tracker and the status route share."""
    latest = db.scalar(select(GrowwSync).order_by(GrowwSync.id.desc()).limit(1))
    success = db.scalar(
        select(GrowwSync).where(GrowwSync.status == SYNC_COMPLETE).order_by(GrowwSync.id.desc()).limit(1)
    )
    return {
        "configured": groww_client.is_configured(),
        "last_success_at": iso(success.finished_at) if success else None,
        "last_status": latest.status if latest else None,
        "last_attempt_at": iso(latest.started_at) if latest else None,
        "last_sync_id": latest.id if latest else None,
    }


def _user_id(db: Session, principal: Principal) -> int:
    """The one tracker Groww writes go to: the Groww account owner's (groww_sync.owner_user_id),
    the same one the 15:35 job updates. Another real-account owner may look, not write."""
    uid = groww_sync.owner_user_id(db)
    if uid is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_OWNER)
    if principal.user is not None and principal.user.id != uid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_GROWW_OWNER)
    return uid


class MatchBody(BaseModel):
    instrument_id: int


def _refuse_other_owner(db: Session, principal: Principal) -> None:
    """Who is calling is checked first: another real-account owner learns nothing about the connection."""
    uid = groww_sync.owner_user_id(db)
    if uid is not None and principal.user is not None and principal.user.id != uid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_GROWW_OWNER)


@router.post("/sync")
def refresh(db: DbSession, principal: Owner) -> dict:
    """Refresh now: fetch Groww holdings and, if the result is complete, update the tracker."""
    _refuse_other_owner(db, principal)
    if not groww_client.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NOT_CONFIGURED)
    last_started = db.scalar(select(GrowwSync.started_at).order_by(GrowwSync.id.desc()).limit(1))
    if last_started is not None:
        if last_started.tzinfo is None:
            last_started = last_started.replace(tzinfo=UTC)
        if utcnow() - last_started < REFRESH_EVERY:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_SOON)
    user_id = _user_id(db, principal)
    try:
        sync = groww_sync.run_sync(db, user_id=user_id, trigger="manual")
    except groww_sync.SyncAlreadyRunning:
        raise HTTPException(status.HTTP_409_CONFLICT, "already refreshing") from None
    return {
        "status": sync.status,
        "holdings_count": sync.holdings_count,
        "finished_at": iso(sync.finished_at),
    }


@router.get("/status")
def groww_status(db: DbSession) -> dict:
    return status_payload(db)


@router.get("/matching")
def matching(db: DbSession) -> dict:
    """Stocks from the latest stored Groww result that still need the owner's OK."""
    latest = db.scalar(
        select(GrowwSync)
        .where(GrowwSync.status.in_((SYNC_COMPLETE, SYNC_PARTIAL)))
        .order_by(GrowwSync.id.desc())
        .limit(1)
    )
    if latest is None:
        return {"items": []}
    rows = list(
        db.scalars(
            select(GrowwHolding)
            .where(GrowwHolding.sync_id == latest.id, GrowwHolding.match_state != MATCH_CONFIRMED)
            .order_by(GrowwHolding.trading_symbol, GrowwHolding.id)
        )
    )
    ids = {r.instrument_id for r in rows if r.instrument_id is not None}
    symbols = (
        dict(db.execute(select(Instrument.id, Instrument.tradingsymbol).where(Instrument.id.in_(ids))).all())
        if ids
        else {}
    )
    return {
        "items": [
            {
                "isin": r.isin,
                "trading_symbol": r.trading_symbol,
                "quantity": r.quantity,
                "average_price": r.average_price,
                "match_state": r.match_state,
                "suggested_symbol": symbols.get(r.instrument_id),
                "suggested_instrument_id": r.instrument_id if r.instrument_id in symbols else None,
            }
            for r in rows
        ]
    }


@router.post("/matching/confirm-all")
def confirm_all(db: DbSession, principal: Owner) -> dict:
    """Accept every suggested match at once."""
    count = groww_apply.confirm_all_suggested(db, user_id=_user_id(db, principal))
    db.commit()
    return {"confirmed": count}


@router.post("/matching/{isin}")
def confirm_one(isin: str, body: MatchBody, db: DbSession, principal: Owner) -> dict:
    """The owner says which stock this Groww holding is. Saved for every future sync."""
    try:
        groww_apply.confirm_match(
            db, user_id=_user_id(db, principal), isin=isin.strip().upper(), instrument_id=body.instrument_id
        )
    except ValueError:  # raised before anything is written
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That stock was not found.") from None
    db.commit()
    return {"isin": isin.strip().upper(), "instrument_id": body.instrument_id}


@router.post("/syncs/{sync_id}/confirm-empty")
def confirm_empty(sync_id: int, db: DbSession, principal: Owner) -> dict:
    """The owner confirms "I hold nothing in Groww": the empty result is applied."""
    try:
        groww_apply.confirm_empty(db, user_id=_user_id(db, principal), sync_id=sync_id)
    except ValueError as exc:  # raised before anything is written
        if "newer" in str(exc):
            msg = "A newer Groww refresh exists. Only the latest empty result can be confirmed."
        else:
            msg = "This Groww result is not an empty one waiting for your OK."
        raise HTTPException(status.HTTP_409_CONFLICT, msg) from None
    db.commit()
    return {"sync_id": sync_id, "status": SYNC_COMPLETE}
