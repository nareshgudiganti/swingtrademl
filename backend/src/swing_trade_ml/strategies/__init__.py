"""Importing this package populates STRATEGY_REGISTRY via the @register_strategy
decorator on each implementation. Any new strategy module must be imported here
or it will be invisible to the engine."""

from swing_trade_ml.strategies.base import (
    STRATEGY_REGISTRY,
    BaseStrategy,
    SignalDecision,
    get_strategy,
    register_strategy,
)
from swing_trade_ml.strategies.ml_swing import MLSwingStrategy
from swing_trade_ml.strategies.sma_crossover import SMACrossoverStrategy

__all__ = [
    "STRATEGY_REGISTRY",
    "BaseStrategy",
    "MLSwingStrategy",
    "SMACrossoverStrategy",
    "SignalDecision",
    "get_strategy",
    "register_strategy",
]
