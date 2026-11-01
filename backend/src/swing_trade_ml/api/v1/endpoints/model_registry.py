# ruff: noqa: E501 (long explanatory lines)
"""Model registry, phase 1: owner-only.

Reads models and shows the nine slots; the single write changes a slot's research priority, status or note.
Nothing here trains, activates, scores or trades, and it never calls the model-activation endpoint."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from swing_trade_ml.api.deps import DbSession, Principal, require_owner
from swing_trade_ml.services import model_registry as svc

router = APIRouter(prefix="/model-registry", tags=["model-registry"], dependencies=[Depends(require_owner)])

Owner = Annotated[Principal, Depends(require_owner)]


class SlotChange(BaseModel):
    """Only these fields can be sent; anything else is rejected."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1, description="The slot's version as the caller last read it")
    priority: int | None = None
    research_status: str | None = None
    note: str | None = None


@router.get("/slots")
def slots(db: DbSession) -> dict[str, Any]:
    return svc.list_slots(db)


@router.get("/models/{model_id}")
def model(model_id: int, db: DbSession) -> dict[str, Any]:
    out = svc.get_model(db, model_id)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such model.")
    return out


@router.patch("/slots/{slot_key}")
def change_slot(
    slot_key: str, body: SlotChange, db: DbSession, principal: Owner, request: Request
) -> dict[str, Any]:
    change = svc.Change(
        priority_set="priority" in body.model_fields_set,
        priority=body.priority,
        status=body.research_status,
        note_set="note" in body.model_fields_set,
        note=body.note,
    )
    try:
        out = svc.update_slot(db, slot_key, body.expected_version, change, principal.user)
        db.commit()
    except LookupError:
        # Nothing was written on any of these paths; the request's session is closed (and rolled back) by get_db.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such slot.") from None
    except svc.InvalidChange as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except svc.VersionConflict as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "This slot was changed by someone else. Reload and try again.",
                "current": exc.current,
            },
        ) from None
    return out
