"""Strategy CRUD, activation, and manual scan triggering."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from swing_trade_ml.api.deps import DbSession
from swing_trade_ml.brokers import get_broker
from swing_trade_ml.db.models.trading import Signal, Strategy
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
from swing_trade_ml.strategies import STRATEGY_REGISTRY

router = APIRouter(prefix="/strategies", tags=["strategies"])


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

    strategy = Strategy(
        **payload.model_dump(),
        # Bound to the current mode at creation, so a strategy made during the
        # paper phase does not start trading the moment live mode is enabled.
        mode=get_broker().mode,
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
    return ScanResponse(**result.__dict__)


@router.post("/scan-all", response_model=ScanResponse)
def scan_all(db: DbSession, interval: str = "day") -> ScanResponse:
    """Run every active strategy now, without waiting for the scheduled time."""
    result = engine.run_all_active(db, interval)
    return ScanResponse(**result.__dict__)


@router.get("/{strategy_id}/signals", response_model=list[SignalOut])
def strategy_signals(
    strategy_id: int, db: DbSession, limit: int = Query(100, le=500)
) -> list[Signal]:
    return list(
        db.execute(
            select(Signal)
            .where(Signal.strategy_id == strategy_id)
            .order_by(Signal.generated_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
