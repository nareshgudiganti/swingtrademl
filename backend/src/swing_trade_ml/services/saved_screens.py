"""Saved screens (#310 slice A): a person's named Discover filters. Settings only.

`ScreenSpec` is the one place that says which filter values exist. It refuses anything else (and any extra
field), so no result, score, price or trade instruction can ever be stored. Limits: at most MAX_SCREENS per
person (hard cap, owner decision D3); the plan may allow fewer (`saved_screens` limit, Free = 3).
Every function takes the person's user id from the credential; nothing here reads another person's rows.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.saved_screen import SavedScreen

#: Hard cap per person (owner decision D3, 2026-11-27) and the longest name.
MAX_SCREENS = 10
MAX_NAME = 60
FILTERS_VERSION = 1

HORIZONS = ("1d", "5d", "15d", "30d", "90d")  # frontend/src/trademind/horizons.ts
CAP_TIERS = ("large", "midcap", "smallcap")
#: The labels find_setups (brain/modules/m12_stock/setups.py) can return.
PATTERNS = ("pullback in up-trend", "breakout", "base", "breakdown")
WORDS = ("ALL", "TRADE", "WATCH", "WAIT", "AVOID")


class ScreenSpec(BaseModel):
    """The filters of one saved screen. Defaults = "no filter"."""

    model_config = ConfigDict(extra="forbid", strict=True)

    horizon: Literal["1d", "5d", "15d", "30d", "90d"] = "15d"
    cap_tiers: list[Literal["large", "midcap", "smallcap"]] = Field(default_factory=list, max_length=3)
    patterns: list[Literal["pullback in up-trend", "breakout", "base", "breakdown"]] = Field(
        default_factory=list, max_length=4
    )
    word: Literal["ALL", "TRADE", "WATCH", "WAIT", "AVOID"] = "ALL"
    sector: str | None = Field(default=None, max_length=60)
    query: str = Field(default="", max_length=32)
    layout: Literal["table", "slides"] = "table"
    watch_only: bool = False


def normalise_spec(raw: dict | None) -> dict:
    """A stored or incoming spec as a full, validated dict (missing fields take their defaults; the order
    of tiers and patterns is the catalogue's, duplicates dropped)."""
    spec = ScreenSpec.model_validate(raw or {})
    data = spec.model_dump()
    data["cap_tiers"] = [t for t in CAP_TIERS if t in spec.cap_tiers]
    data["patterns"] = [p for p in PATTERNS if p in spec.patterns]
    data["sector"] = (spec.sector or "").strip() or None
    data["query"] = spec.query.strip()
    return data


def clean_name(name: str) -> str:
    return " ".join(name.split())


def allowed_screens(limits: dict | None, unrestricted: bool) -> int:
    """How many screens this person may keep: the plan's `saved_screens` limit, never above MAX_SCREENS.
    A plan with no number set (0) gets the hard cap; the owner always gets the hard cap."""
    if unrestricted:
        return MAX_SCREENS
    planned = int((limits or {}).get("saved_screens") or 0)
    return min(planned, MAX_SCREENS) if planned > 0 else MAX_SCREENS


def mine(db: Session, user_id: int) -> list[SavedScreen]:
    return list(
        db.execute(
            select(SavedScreen).where(SavedScreen.user_id == user_id).order_by(SavedScreen.id)
        ).scalars()
    )


def count_mine(db: Session, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(SavedScreen).where(SavedScreen.user_id == user_id)) or 0


def get_mine(db: Session, user_id: int, screen_id: int) -> SavedScreen | None:
    """None for a missing screen AND for another person's: callers answer 404 either way."""
    return db.execute(
        select(SavedScreen).where(SavedScreen.id == screen_id, SavedScreen.user_id == user_id)
    ).scalar_one_or_none()


def name_taken(db: Session, user_id: int, name: str, *, except_id: int | None = None) -> bool:
    q = select(SavedScreen.id).where(
        SavedScreen.user_id == user_id, func.lower(SavedScreen.name) == name.lower()
    )
    if except_id is not None:
        q = q.where(SavedScreen.id != except_id)
    return db.execute(q).first() is not None
