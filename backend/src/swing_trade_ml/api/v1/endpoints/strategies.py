"""Strategy CRUD, activation, and manual scan triggering."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Signal, Strategy
from swing_trade_ml.schemas import (
    MessageResponse,
    ScanResponse,
    SignalOut,
    StrategyCreate,
    StrategyOut,
    StrategyTypeInfo,
    StrategyUpdate,
)
from swing_trade_ml.services import engine
from swing_trade_ml.services import portfolio as portfolio_service
from swing_trade_ml.strategies import STRATEGY_REGISTRY
from swing_trade_ml.strategies.tier import cap_tier

router = APIRouter(prefix="/strategies", tags=["strategies"])

# A strategy needs this many all-time closed trades before it's eligible to
# be recommended — fewer than this and win rate is noise, not signal.
MIN_TRADES_FOR_RECOMMENDATION = 10
# The 90-day window is only trusted for ranking once it has this many trades
# of its own; below that, all-time win rate is the fairer comparison.
MIN_TRADES_FOR_90D_WINDOW = 3
# Only ml_swing strategies running in "auto" mode compete for the
# recommendation — advisory strategies like real_trading track personal
# holdings, not a switchable trading approach.
RECOMMENDABLE_STRATEGY_TYPE = "ml_swing"
RECOMMENDABLE_EXECUTION_MODE = "auto"


@router.get("/types", response_model=list[StrategyTypeInfo])
def list_strategy_types() -> list[StrategyTypeInfo]:
    """Available strategy implementations and their tunable parameters."""
    return [
        StrategyTypeInfo(
            strategy_type=cls.strategy_type,
            display_name=cls.display_name or cls.strategy_type,
            description=cls.description,
            default_params=cls.default_params,
        )
        for cls in STRATEGY_REGISTRY.values()
    ]


@router.get("/performance", response_model=dict)
def strategy_performance(db: DbSession) -> dict[str, Any]:
    """Per-strategy win rate over three windows, plus a deterministic
    recommendation — the data behind the Strategies tab's cards. See
    docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b.
    """
    strategies = list(db.execute(select(Strategy).order_by(Strategy.name)).scalars().all())
    now = datetime.now(UTC)
    since_30d = now - timedelta(days=30)
    since_90d = now - timedelta(days=90)

    rows: list[dict[str, Any]] = []
    for strategy in strategies:
        model_name = strategy.params.get("model_name") if strategy.params else None
        open_positions = db.execute(
            select(func.count(Position.id)).where(
                Position.strategy_id == strategy.id, Position.status == PositionStatus.OPEN
            )
        ).scalar_one()
        rows.append(
            {
                "id": strategy.id,
                "name": strategy.name,
                "strategy_type": strategy.strategy_type,
                "execution_mode": strategy.execution_mode,
                "cap_tier": cap_tier(model_name),
                "is_active": strategy.is_active,
                "universe_size": len(engine.eligible_instruments(db, strategy)),
                "open_positions": open_positions,
                "windows": {
                    "last_30d": portfolio_service.strategy_performance_stats(db, strategy.id, since=since_30d),
                    "last_90d": portfolio_service.strategy_performance_stats(db, strategy.id, since=since_90d),
                    "all_time": portfolio_service.strategy_performance_stats(db, strategy.id),
                },
            }
        )

    def _rank_key(row: dict[str, Any]) -> tuple[float, float, float]:
        w90 = row["windows"]["last_90d"]
        primary = w90 if w90["trades"] >= MIN_TRADES_FOR_90D_WINDOW else row["windows"]["all_time"]
        return (primary["win_rate"], primary["profit_factor"], primary["net_pnl"])

    eligible = [
        row
        for row in rows
        if row["is_active"]
        and row["strategy_type"] == RECOMMENDABLE_STRATEGY_TYPE
        and row["execution_mode"] == RECOMMENDABLE_EXECUTION_MODE
        and row["windows"]["all_time"]["trades"] >= MIN_TRADES_FOR_RECOMMENDATION
    ]

    recommended_id: int | None = None
    if eligible:
        best = max(eligible, key=_rank_key)
        recommended_id = best["id"]
        w90 = best["windows"]["last_90d"]
        used_90d = w90["trades"] >= MIN_TRADES_FOR_90D_WINDOW
        primary = w90 if used_90d else best["windows"]["all_time"]
        window_label = "the last 90 days" if used_90d else "all time"
        reason = (
            f"{best['name']}: best win rate ({primary['win_rate']:.0%}) over {window_label} "
            f"among strategies with at least {MIN_TRADES_FOR_RECOMMENDATION} closed trades."
        )
    else:
        candidates = [
            row
            for row in rows
            if row["is_active"]
            and row["strategy_type"] == RECOMMENDABLE_STRATEGY_TYPE
            and row["execution_mode"] == RECOMMENDABLE_EXECUTION_MODE
        ]
        closest = max(candidates, key=lambda r: r["windows"]["all_time"]["trades"], default=None)
        if closest is not None and closest["windows"]["all_time"]["trades"] > 0:
            have = closest["windows"]["all_time"]["trades"]
            need = MIN_TRADES_FOR_RECOMMENDATION - have
            reason = (
                f"{closest['name']} is closest with {have} closed trade{'s' if have != 1 else ''} — "
                f"{need} more needed before a recommendation."
            )
        else:
            reason = "Not enough closed trades yet to recommend a strategy."

    return {"strategies": rows, "recommended_strategy_id": recommended_id, "recommendation_reason": reason}


@router.get("", response_model=list[StrategyOut])
def list_strategies(db: DbSession, active_only: bool = False) -> list[Strategy]:
    stmt = select(Strategy).order_by(Strategy.created_at.desc())
    if active_only:
        stmt = stmt.where(Strategy.is_active.is_(True))
    return list(db.execute(stmt).scalars().all())


@router.post("", response_model=StrategyOut, status_code=status.HTTP_201_CREATED)
def create_strategy(payload: StrategyCreate, db: DbSession) -> Strategy:
    if payload.strategy_type not in STRATEGY_REGISTRY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown strategy_type '{payload.strategy_type}'. "
            f"Available: {sorted(STRATEGY_REGISTRY)}",
        )
    if db.execute(select(Strategy).where(Strategy.name == payload.name)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Strategy '{payload.name}' already exists")

    fields = payload.model_dump(exclude={"mode"})
    # An advisory strategy never places a broker order, so letting it declare
    # its own mode (e.g. "live" to track real trades made manually) carries
    # none of the risk that motivates pinning "auto" strategies to the
    # broker's current mode below.
    resolved_mode = payload.mode if (payload.mode and payload.execution_mode == "advisory") else get_broker().mode

    strategy = Strategy(
        **fields,
        # Bound to the current mode at creation, so a strategy made during the
        # paper phase does not start trading the moment live mode is enabled.
        mode=resolved_mode,
        is_active=False,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.get("/{strategy_id}", response_model=StrategyOut)
def get_strategy_by_id(strategy_id: int, db: DbSession) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    return strategy


@router.patch("/{strategy_id}", response_model=StrategyOut)
def update_strategy(strategy_id: int, payload: StrategyUpdate, db: DbSession) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(strategy, field, value)
    db.commit()
    db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", response_model=MessageResponse)
def delete_strategy(strategy_id: int, db: DbSession) -> MessageResponse:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    if strategy.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Deactivate the strategy before deleting it"
        )
    db.delete(strategy)
    db.commit()
    return MessageResponse(message=f"Deleted strategy '{strategy.name}'")


@router.post("/{strategy_id}/activate", response_model=StrategyOut)
def activate(strategy_id: int, db: DbSession) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    strategy.is_active = True
    db.commit()
    db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/deactivate", response_model=StrategyOut)
def deactivate(strategy_id: int, db: DbSession) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    strategy.is_active = False
    db.commit()
    db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/scan", response_model=ScanResponse)
def scan_one(strategy_id: int, db: DbSession, interval: str = "day") -> ScanResponse:
    """Run one strategy immediately.

    Synchronous on purpose: a manual scan is how a strategy gets tested, and
    the caller wants the result rather than a job id.
    """
    strategy = db.get(Strategy, strategy_id)
    if strategy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Strategy not found")
    result = engine.run_strategy(db, strategy, interval)
    return ScanResponse(**asdict(result))


@router.post("/scan-all", response_model=ScanResponse)
def scan_all(db: DbSession, interval: str = "day") -> ScanResponse:
    """Run every active strategy now, without waiting for the scheduled time."""
    result = engine.run_all_active(db, interval)
    return ScanResponse(**asdict(result))


@router.get("/{strategy_id}/signals", response_model=list[SignalOut])
def strategy_signals(
    strategy_id: int, db: DbSession, limit: int = Query(100, le=500)
) -> list[dict]:
    """Symbol-resolved so a caller (e.g. the Suggestions page, which groups
    by cap-tier strategy) never needs a second round-trip to name a row."""
    rows = db.execute(
        select(Signal, Instrument.tradingsymbol, Instrument.name)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.strategy_id == strategy_id)
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": signal.id,
            "strategy_id": signal.strategy_id,
            "instrument_id": signal.instrument_id,
            "tradingsymbol": tradingsymbol,
            "name": name,
            "signal_type": signal.signal_type,
            "mode": signal.mode,
            "price": signal.price,
            "confidence": signal.confidence,
            "suggested_quantity": signal.suggested_quantity,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "reason": signal.reason,
            "features": signal.features,
            "was_executed": signal.was_executed,
            "rejection_reason": signal.rejection_reason,
            "advisory_only": signal.advisory_only,
            "generated_at": signal.generated_at,
        }
        for signal, tradingsymbol, name in rows
    ]
