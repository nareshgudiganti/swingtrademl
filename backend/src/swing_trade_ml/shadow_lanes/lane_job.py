# ruff: noqa: E501, N812 (long explanatory lines; S is the service alias)
"""The shared shadow-lane daily job: record the latest closed session's top 5, then score matured picks.

DISABLED by default and NOT wired into the scheduler: `register(scheduler)` adds nothing unless the setting
LANE_SHADOW_ENABLED is true, and nothing in `workers/scheduler.py` calls it. The owner approves wiring and
deploy separately. It never activates a model, never trades and writes only `lane_picks` / `lane_outcomes`.

A slot keeps the model it first used: the newest registered lane model is chosen only for a slot with no picks.
"""

from __future__ import annotations

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
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services.model_registry import LANE_PREFIXES, slot_for
from swing_trade_ml.shadow_lanes import lane_service as S

log = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
JOB_ID = "lane_shadow_daily"
SCHEDULE = {"day_of_week": "mon-sat", "hour": "18,20,22", "minute": 45}
READY_SHARE = 0.8  # record only when at least this share of the group's stocks can be scored

#: cap group -> the v1 model name whose active ml_swing strategies list that group's stocks
GROUP_STRATEGY_MODEL = {"large": "swing_classifier", "mid": "swing_classifier_midcap"}


def enabled() -> bool:
    return bool(settings.LANE_SHADOW_ENABLED)


def lane_model_for(db: Session, slot_key: str) -> MLModel | None:
    """The model already used by this slot, else the newest registered lane model for it. No status filter:
    a TRAINED, never-activated model is the normal case."""
    used = db.scalar(
        select(LanePick.model_id)
        .where(LanePick.slot_key == slot_key)
        .order_by(LanePick.signal_day.desc())
        .limit(1)
    )
    if used is not None:
        return db.get(MLModel, used)
    rows = db.execute(select(MLModel).order_by(MLModel.created_at.desc(), MLModel.id.desc())).scalars()
    for m in rows:
        if (
            m.name.startswith(tuple(p for p, _, _ in LANE_PREFIXES))
            and slot_for(m.name, m.prediction_horizon_days) == slot_key
        ):
            return m
    return None


def group_symbols(db: Session, cap_group: str) -> list[str]:
    wanted = GROUP_STRATEGY_MODEL[cap_group]
    out: set[str] = set()
    for s in db.execute(
        select(Strategy).where(Strategy.is_active.is_(True), Strategy.strategy_type == "ml_swing")
    ).scalars():
        if (s.params or {}).get("model_name") == wanted:
            out.update(x.upper() for x in (s.symbols or []))
    return sorted(out)


def run_daily(db: Session, now: datetime | None = None) -> dict:
    moment = now or datetime.now(UTC)
    signal_day = last_closed_trading_day(moment)
    result: dict = {"signal_day": str(signal_day), "slots": {}}
    for slot_key, (_, group) in S.SLOTS.items():
        model = lane_model_for(db, slot_key)
        if model is None:
            result["slots"][slot_key] = "no_model"
            continue
        try:
            result["slots"][slot_key] = S.record_day(
                db,
                model,
                slot_key,
                {group: group_symbols(db, group)},
                signal_day,
                moment,
                min_ready_share=READY_SHARE,
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
