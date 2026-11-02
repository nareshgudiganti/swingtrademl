# ruff: noqa: E501, N812 (long explanatory lines; S is the service alias)
"""The shared shadow-lane daily job: record the latest closed session's top 5, then score matured picks.

DISABLED by default and NOT wired into the scheduler: `register(scheduler)` adds nothing unless the setting
LANE_SHADOW_ENABLED is true, and nothing in `workers/scheduler.py` calls it. The owner approves wiring and
deploy separately. It never activates a model, never trades and writes only `lane_picks` / `lane_outcomes`.

The owner chooses each slot's model in LANE_SHADOW_MODELS (a JSON map of slot key to model id); nothing is auto-picked, and a
slot keeps the model it first used: a configured model that differs from the slot's existing picks stops that slot.
The stock lists come from the frozen universe file (the locked 49 and the 14 mid-cap stocks), re-verified on every run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger
from swing_trade_ml.core.market_session import last_closed_trading_day
from swing_trade_ml.db.models.lane_shadow import LanePick
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services.model_registry import slot_for
from swing_trade_ml.shadow_lanes import lane_service as S
from swing_trade_ml.shadow_lanes import lane_universe

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
JOB_ID = "lane_shadow_daily"
SCHEDULE = {"day_of_week": "mon-sat", "hour": "18,20,22", "minute": 45}
READY_SHARE = 0.8  # record only when at least this share of the group's stocks can be scored


def enabled() -> bool:
    return bool(settings.LANE_SHADOW_ENABLED)


def configured_model_ids() -> dict[str, int]:
    """The owner's choice per slot from LANE_SHADOW_MODELS ({} when unset or not valid JSON). Never auto-picked."""
    try:
        raw = json.loads(settings.LANE_SHADOW_MODELS or "{}")
        return {str(k): int(v) for k, v in raw.items()}
    except (ValueError, TypeError, AttributeError):
        return {}


def _used_model_id(db: Session, slot_key: str) -> int | None:
    return db.scalar(
        select(LanePick.model_id)
        .where(LanePick.slot_key == slot_key)
        .order_by(LanePick.signal_day.desc())
        .limit(1)
    )


def lane_model_for(db: Session, slot_key: str) -> MLModel | None:
    """The model this slot already uses, else the one the owner configured for it, else None. Nothing is picked
    automatically. A TRAINED, never-activated model is the normal case; it must be registered for this slot."""
    used = _used_model_id(db, slot_key)
    if used is not None:
        return db.get(MLModel, used)
    chosen = configured_model_ids().get(slot_key)
    model = db.get(MLModel, chosen) if chosen is not None else None
    if model is not None and slot_for(model.name, model.prediction_horizon_days) == slot_key:
        return model
    return None


def model_conflict(db: Session, slot_key: str) -> str | None:
    """Set when the owner configured a different model than the slot's existing picks use: the slot never switches."""
    used, chosen = _used_model_id(db, slot_key), configured_model_ids().get(slot_key)
    if used is not None and chosen is not None and used != chosen:
        return f"slot keeps model {used}; configured model is {chosen}"
    return None


def run_daily(db: Session, now: datetime | None = None) -> dict:
    moment = now or datetime.now(UTC)
    signal_day = last_closed_trading_day(moment)
    result: dict = {"signal_day": str(signal_day), "slots": {}}
    try:
        universe = lane_universe.load_universe()
    except lane_universe.UniverseError as exc:
        for slot_key in S.SLOTS:
            result["slots"][slot_key] = f"no_universe: {exc}"
        result["outcomes"] = S.evaluate_matured(db, signal_day)
        return result
    for slot_key, (_, group) in S.SLOTS.items():
        conflict = model_conflict(db, slot_key)
        if conflict:
            result["slots"][slot_key] = f"model_mismatch: {conflict}"
            continue
        model = lane_model_for(db, slot_key)
        if model is None:
            result["slots"][slot_key] = "no_model: choose one in LANE_SHADOW_MODELS"
            continue
        try:
            result["slots"][slot_key] = S.record_day(
                db,
                model,
                slot_key,
                {group: lane_universe.group_symbols(universe, group)},
                signal_day,
                moment,
                min_ready_share=READY_SHARE,
                extra_flags={"universe_sha256": universe["sha256"]},
            )
        except S.LaneError as exc:
            result["slots"][slot_key] = f"not_recorded: {exc}"
    result["outcomes"] = S.evaluate_matured(db, signal_day)
    return result


def job_lane_daily() -> None:
    """Scheduled entry point: own session, never raises (an evaluation lane must not disturb the bot)."""
    from swing_trade_ml.db.session import session_scope

    try:
        with session_scope() as db:
            result = run_daily(db)
        log.info("lane_shadow.daily", signal_day=result["signal_day"])
    except Exception as exc:  # noqa: BLE001
        log.error("lane_shadow.daily_failed", error_kind=type(exc).__name__)


def register(target) -> bool:
    """Add the daily job to a scheduler ONLY when LANE_SHADOW_ENABLED is true. Returns whether it did."""
    if not enabled():
        return False
    target.add_job(
        job_lane_daily,
        CronTrigger(timezone=IST, **SCHEDULE),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return True
