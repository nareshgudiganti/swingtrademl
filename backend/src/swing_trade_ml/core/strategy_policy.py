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
