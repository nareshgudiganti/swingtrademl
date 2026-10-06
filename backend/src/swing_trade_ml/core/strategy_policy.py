"""Strategy execution capabilities shared by validation and order paths."""

# The app never places orders for these: the owner records their trades by hand.
MANUAL_ONLY_TYPES = frozenset({"long_term_value"})
# Ordered ONLY through the owner's go-live stages (brain M18,
# services/brain_golive/approvals.py) — never by the scan itself.
STAGED_TYPES = frozenset({"brain"})
# Never scanned by the daily engine — manual paper validation only.
NON_SCAN_STRATEGY_TYPES = frozenset({"tester_paper"})


def requires_advisory(strategy_type: str) -> bool:
    return strategy_type in MANUAL_ONLY_TYPES or strategy_type in STAGED_TYPES


def is_staged(strategy) -> bool:
    return strategy is not None and strategy.strategy_type in STAGED_TYPES


def is_advisory(strategy) -> bool:
    return strategy is not None and (
        requires_advisory(strategy.strategy_type) or strategy.execution_mode == "advisory"
    )


def exits_are_advisory(strategy) -> bool:
    """Whether exits only alert (the owner sells by hand). A staged strategy's
    positions exist only because the owner approved an order, so version 1's
    own stops, targets and time stop must protect them."""
    return is_advisory(strategy) and not is_staged(strategy)


def validate_execution_mode(strategy_type: str, execution_mode: str) -> None:
    if strategy_type in STAGED_TYPES and execution_mode != "advisory":
        raise ValueError(
            "The brain strategy only records ideas here. Its trading stage is changed "
            "by the owner on the Brain page."
        )
    if requires_advisory(strategy_type) and execution_mode != "advisory":
        raise ValueError("Long-term strategies support advisory execution only")


def require_broker_execution(strategy) -> None:
    if strategy is not None and strategy.strategy_type in MANUAL_ONLY_TYPES:
        raise ValueError("Long-term strategies are advisory only; record the trade manually")
