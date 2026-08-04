"""Strategy interface and registry.

A strategy's only job is to answer "what would you do with this instrument
right now, and why". It never places orders, sizes positions, or checks risk
limits — the execution service owns all of that. Keeping strategies pure makes
them testable against historical frames without a database or a broker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy as StrategyModel


@dataclass(slots=True)
class SignalDecision:
    """A strategy's verdict on one instrument."""

    signal: SignalType
    price: float
    confidence: float | None = None
    reason: str = ""
    stop_loss: float | None = None
    take_profit: float | None = None
    features: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Subclasses set `strategy_type` and are picked up by the registry."""

    strategy_type: ClassVar[str]
    display_name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    #: Documented defaults, overridden per-instance by Strategy.params
    default_params: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: StrategyModel) -> None:
        self.config = config
        self.params = {**self.default_params, **(config.params or {})}

    @abstractmethod
    def evaluate(
        self, df: pd.DataFrame, instrument: Instrument, db: Session
    ) -> SignalDecision | None:
        """Assess one instrument. `df` is ascending OHLCV with a `ts` column.

        Return None when there is not enough history to judge — distinct from
        returning HOLD, which is an actual decision to stay flat.
        """

    def min_bars_required(self) -> int:
        """Bars needed before `evaluate` can produce anything meaningful."""
        return 250


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register_strategy(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    STRATEGY_REGISTRY[cls.strategy_type] = cls
    return cls


def get_strategy(config: StrategyModel) -> BaseStrategy:
    cls = STRATEGY_REGISTRY.get(config.strategy_type)
    if cls is None:
        raise ValueError(
            f"Unknown strategy_type '{config.strategy_type}'. "
            f"Available: {sorted(STRATEGY_REGISTRY)}"
        )
    return cls(config)
