"""Reading and saving Free / Pro plan settings.

A plan the owner has never edited has no row and uses its defaults from
core/plans.py, so a fresh database works without seeding.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.plans import BASE_MODEL, DEFAULT_PLANS, PLAN_KEYS, clean_plan, default_plan
from swing_trade_ml.core.strategy_policy import (
    HAND_BOOK_STRATEGY_NAMES,
    NON_SCAN_STRATEGY_TYPES,
    STAGED_TYPES,
)
from swing_trade_ml.db.models.session import PlanSettings, SubscriptionPlan
from swing_trade_ml.db.models.trading import Position, Strategy, Trade
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


def is_owner_private_strategy(strategy: Strategy | None, owns_live_book: bool = False) -> bool:
    """Is this strategy the owner's own hand-recorded book, never a member's to see?

    Decided from data markers, not the name alone, so renaming a strategy does
    not unhide it. Private when ANY of these holds:
    - its name is a hand-book name (`real_trading`, `tester_paper`);
    - its type is the manual paper-testing type (`tester_paper`);
    - it is advisory (never auto-ordered) AND either stored as mode `live`
      or owns live-mode positions/trades (`owns_live_book`): that is how
      import-holdings records real Zerodha shares. The brain's own staged
      strategy is exempt: it is advisory by design and member-facing.
    """
    if strategy is None:
        return False
    if strategy.name in HAND_BOOK_STRATEGY_NAMES or strategy.strategy_type in NON_SCAN_STRATEGY_TYPES:
        return True
    if strategy.strategy_type in STAGED_TYPES:
        return False
    return strategy.execution_mode == "advisory" and (strategy.mode == "live" or owns_live_book)


def owner_private_strategy_ids(db: Session) -> set[int]:
    """Ids of every owner-private strategy (see `is_owner_private_strategy`)."""
    live_owners = set(
        db.execute(select(Position.strategy_id).where(Position.mode == "live")).scalars()
    ) | set(db.execute(select(Trade.strategy_id).where(Trade.mode == "live")).scalars())
    return {
        s.id
        for s in db.execute(select(Strategy)).scalars()
        if is_owner_private_strategy(s, s.id in live_owners)
    }


def history_cutoff(access: PlanAccess) -> datetime | None:
    days = access.history_days
    return datetime.now(UTC) - timedelta(days=days) if days else None
