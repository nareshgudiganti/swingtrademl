"""Reading and saving Free / Plus / Pro plan settings.

A plan the owner has never edited has no row and uses its defaults from
core/plans.py, so a fresh database works without seeding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from swing_trade_ml.core.plans import BASE_MODEL, DEFAULT_PLANS, PLAN_KEYS, clean_plan, default_plan
from swing_trade_ml.db.models.session import PlanSettings, SubscriptionPlan
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME
from swing_trade_ml.strategies.tier import cap_tier

if TYPE_CHECKING:
    from swing_trade_ml.api.deps import PlanAccess

PLAN_SETTINGS_ID = 1


def plans_enabled(db: Session) -> bool:
    """The owner's master switch. Off (the default, and with no row at all)
    means every signed-in account sees the whole app, exactly as before
    plans existed."""
    row = db.get(PlanSettings, PLAN_SETTINGS_ID)
    return bool(row and row.enabled)


def set_plans_enabled(db: Session, enabled: bool) -> bool:
    row = db.get(PlanSettings, PLAN_SETTINGS_ID)
    if row is None:
        row = PlanSettings(id=PLAN_SETTINGS_ID)
        db.add(row)
    row.enabled = enabled
    db.commit()
    return row.enabled


def get_plan(db: Session, key: str) -> dict[str, Any]:
    defaults = default_plan(key)
    row = db.get(SubscriptionPlan, key)
    if row is None:
        return defaults
    # Re-cleaning drops any key since removed from the catalogue; a feature
    # added after the row was saved starts off, a new limit at its default.
    saved_features = {k: v for k, v in (row.features or {}).items() if k in defaults["features"]}
    saved_limits = {k: v for k, v in (row.limits or {}).items() if k in defaults["limits"]}
    features, limits = clean_plan(saved_features, {**defaults["limits"], **saved_limits})
    return {"key": key, "name": DEFAULT_PLANS[key]["name"], "features": features, "limits": limits}


def list_plans(db: Session) -> list[dict[str, Any]]:
    return [get_plan(db, key) for key in PLAN_KEYS]


def save_plan(db: Session, key: str, features: dict[str, Any], limits: dict[str, Any]) -> dict[str, Any]:
    if key not in PLAN_KEYS:
        raise KeyError(key)
    clean_features, clean_limits = clean_plan(features, limits)
    row = db.get(SubscriptionPlan, key)
    if row is None:
        row = SubscriptionPlan(key=key)
        db.add(row)
    row.features = clean_features
    row.limits = clean_limits
    db.commit()
    return get_plan(db, key)


def strategy_visible(strategy: Strategy | None, access: PlanAccess) -> bool:
    """May this caller see signals and trades from `strategy`?

    Plan users only ever see model-driven strategies, never the owner's
    hand-bought `real_trading` book or rule strategies. Without
    `all_models` that narrows to the base model alone, and the plan's
    company sizes apply on top.
    """
    if access.unrestricted:
        return True
    if strategy is None or strategy.strategy_type != "ml_swing":
        return False
    if strategy.name == REAL_TRADING_STRATEGY_NAME:
        return False
    model_name = (strategy.params or {}).get("model_name") or BASE_MODEL
    if not access.has("all_models") and model_name != BASE_MODEL:
        return False
    tiers = access.cap_tiers
    return tiers is None or cap_tier(model_name) in tiers


def history_cutoff(access: PlanAccess) -> datetime | None:
    days = access.history_days
    return datetime.now(UTC) - timedelta(days=days) if days else None
