"""Models and scores that are safe to use for a past day (brain replays).

A model trained with a cutoff only learned from rows whose outcome was known by that day,
and may only score days strictly after it.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.ml.train import train_model


def asof_cutoff(model: Any) -> date | None:
    """The cutoff a model was trained with, or None for an ordinary (live) model."""
    raw = (getattr(model, "metrics", None) or {}).get("asof_cutoff")
    return date.fromisoformat(raw) if raw else None


def train_asof_model(db: Session, cutoff: date, symbols: list[str] | None = None, **kwargs) -> MLModel:
    """Train `swing_classifier_asof_<YYYYMMDD>` on data known by `cutoff`. Never activated."""
    kwargs.pop("auto_activate", None)
    return train_model(
        db,
        name=f"swing_classifier_asof_{cutoff:%Y%m%d}",
        symbols=symbols,
        cutoff=cutoff,
        auto_activate=False,
        **kwargs,
    )
