"""Saved screens (#310 slice A): each signed-in person's own named Discover filters, plus the Brain-idea
"what changed" note for a screen and for the watchlist.

The screen routes are self-service on purpose (api/deps.py SELF_SERVICE_ROUTES): any signed-in
person may keep THEIR OWN screens, whatever their role or plan (the plan only sets how many: Free 3, at most
10). Every handler
takes the user id from the credential (`Me`), never from the body or the path; another person's screen answers
404 exactly like a missing one. The API key has no person behind it and is refused.

The two digest routes are a Pro feature (core/plans.py ROUTE_RULES, feature `screen_digest`), read only.
Nothing here touches trading, sizing, exits, limits, orders or the brain's own tables (reads only).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.api.deps import DbSession, PlanAccessDep, Principal, get_principal
from swing_trade_ml.api.v1.endpoints.brain import _brain_switched_on
from swing_trade_ml.api.v1.endpoints.my_watchlist import Me
from swing_trade_ml.core.plans import FEATURES
from swing_trade_ml.db.models.saved_screen import SavedScreen
from swing_trade_ml.services import saved_screens as svc
from swing_trade_ml.services import screen_digest

router = APIRouter(prefix="/me", tags=["my-screens"])

NAME_TAKEN = "You already have a saved screen with that name."
NOT_FOUND = "That saved screen was not found."


class ScreenOut(BaseModel):
    id: int
    name: str
    spec: dict
    filters_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScreensOut(BaseModel):
    screens: list[ScreenOut]
    limit: int


class ScreenCreate(BaseModel):
    name: str = Field(max_length=200)
    spec: dict = Field(default_factory=dict)


class ScreenPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    spec: dict | None = None


def _out(row: SavedScreen) -> ScreenOut:
    try:
        spec = svc.normalise_spec(row.spec)
    except ValidationError:  # a screen saved under older rules: show what is stored, never guess
        spec = dict(row.spec or {})
    return ScreenOut(
        id=row.id,
        name=row.name,
        spec=spec,
        filters_version=row.filters_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _spec(raw: dict | None) -> dict:
    try:
        return svc.normalise_spec(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ())) or "filters"
        raise HTTPException(422, f"That filter value is not allowed ({field}).") from exc


def _name(raw: str) -> str:
    name = svc.clean_name(raw)
    if not name or len(name) > svc.MAX_NAME:
        raise HTTPException(422, f"Give the screen a name of 1 to {svc.MAX_NAME} characters.")
    return name


def _limit(access: PlanAccessDep) -> int:
    return svc.allowed_screens(access.limits, access.unrestricted)


def _mine_or_404(db: DbSession, me: Me, screen_id: int) -> SavedScreen:
    row = svc.get_mine(db, me.id, screen_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return row


@router.get("/screens", response_model=ScreensOut)
def list_screens(db: DbSession, me: Me, access: PlanAccessDep) -> ScreensOut:
    return ScreensOut(screens=[_out(r) for r in svc.mine(db, me.id)], limit=_limit(access))


@router.post("/screens", response_model=ScreenOut, status_code=status.HTTP_201_CREATED)
def create_screen(body: ScreenCreate, db: DbSession, me: Me, access: PlanAccessDep) -> ScreenOut:
    name, spec = _name(body.name), _spec(body.spec)
    limit = _limit(access)
    if svc.count_mine(db, me.id) >= limit:
        raise HTTPException(422, f"You can keep up to {limit} saved screens. Delete one to save another.")
    if svc.name_taken(db, me.id, name):
        raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN)
    row = SavedScreen(user_id=me.id, name=name, spec=spec, filters_version=svc.FILTERS_VERSION)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:  # two taps at once: the unique index decides
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN) from exc
    db.refresh(row)
    return _out(row)


@router.get("/screens/{screen_id}", response_model=ScreenOut)
def get_screen(screen_id: int, db: DbSession, me: Me) -> ScreenOut:
    return _out(_mine_or_404(db, me, screen_id))


@router.patch("/screens/{screen_id}", response_model=ScreenOut)
def change_screen(screen_id: int, body: ScreenPatch, db: DbSession, me: Me) -> ScreenOut:
    row = _mine_or_404(db, me, screen_id)
    if body.name is not None:
        name = _name(body.name)
        if svc.name_taken(db, me.id, name, except_id=row.id):
            raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN)
        row.name = name
    if body.spec is not None:
        row.spec = _spec(body.spec)
        row.filters_version = svc.FILTERS_VERSION
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, NAME_TAKEN) from exc
    db.refresh(row)
    return _out(row)


@router.delete("/screens/{screen_id}")
def delete_screen(screen_id: int, db: DbSession, me: Me) -> dict:
    """Hard delete: a screen holds only settings, so there is no history to keep. The watchlist and every
    trade are untouched."""
    row = _mine_or_404(db, me, screen_id)
    db.delete(row)
    db.commit()
    return {"deleted": True, "id": screen_id}


# ----------------------------------------------------------------------------- the digest (Pro)


def _digest_allowed(access: PlanAccessDep) -> None:
    """The digest reads TradeMind's brain ideas, so the plan must include TradeMind too."""
    if not access.has("trademind"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"“{FEATURES['trademind']['label']}” isn't included in the {access.plan} plan.",
        )


@router.get("/screens/{screen_id}/digest", dependencies=[Depends(_brain_switched_on)])
def screen_changes(
    screen_id: int,
    db: DbSession,
    me: Me,
    access: PlanAccessDep,
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict:
    row = _mine_or_404(db, me, screen_id)
    _digest_allowed(access)
    out = screen_digest.digest(db, _out(row).spec, user_id=me.id, owner=principal.is_owner)
    out["screen"] = {"id": row.id, "name": row.name}
    return out


@router.get("/watchlist/digest", dependencies=[Depends(_brain_switched_on)])
def watchlist_changes(
    db: DbSession,
    me: Me,
    access: PlanAccessDep,
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict:
    _digest_allowed(access)
    spec = svc.normalise_spec({"watch_only": True})
    out = screen_digest.digest(db, spec, user_id=me.id, owner=principal.is_owner)
    out["screen"] = {"id": None, "name": "My Watchlist"}
    return out
