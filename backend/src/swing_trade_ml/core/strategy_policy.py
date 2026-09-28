"""Strategy execution capabilities shared by validation and order paths."""


def requires_advisory(strategy_type: str) -> bool:
    return strategy_type == "long_term_value"


def is_advisory(strategy) -> bool:
    return strategy is not None and (
        requires_advisory(strategy.strategy_type) or strategy.execution_mode == "advisory"
    )


def validate_execution_mode(strategy_type: str, execution_mode: str) -> None:
    if requires_advisory(strategy_type) and execution_mode != "advisory":
        raise ValueError("Long-term strategies support advisory execution only")


def require_broker_execution(strategy) -> None:
    if strategy is not None and requires_advisory(strategy.strategy_type):
        raise ValueError("Long-term strategies are advisory only; record the trade manually")

#: Risk and exit rules are the same for every strategy and are read from
#: settings, never from a strategy row. Listed here so the API can refuse
#: them by name instead of relying on the downstream code happening to ignore
#: them - ml_swing does ignore stop_loss_pct, but sma_crossover reads it, so
#: "inert" was only ever true for some strategies.
#:
#: Changing any of these is a change to the whole system's safety, which is a
#: settings change and a deliberate act, not a per-strategy preference.
LOCKED_RISK_FIELDS: frozenset[str] = frozenset({
    "stop_loss_pct",
    "take_profit_pct",
    "max_positions",
    "capital_allocation",
    "allow_pyramiding",
    "risk_per_trade_pct",
    "max_drawdown_pct",
    "sector_cap_pct",
    "cash_floor_pct",
    "max_position_pct",
    "time_stop_days",
    "scale_out_at_pct",
    "scale_out_fraction",
    "position_sizing_mode",
})


def locked_fields_in(payload: dict) -> list[str]:
    """Which locked fields a request is trying to set, top level or inside
    `params`.

    `params` is a free-form dict, so it is the obvious way around a top-level
    block. Both doors have to be shut or neither is. Class-level
    default_params are unaffected: this only inspects what a caller sent.
    """
    found = set(payload) & LOCKED_RISK_FIELDS
    nested = payload.get("params")
    if isinstance(nested, dict):
        found |= set(nested) & LOCKED_RISK_FIELDS
    return sorted(found)
