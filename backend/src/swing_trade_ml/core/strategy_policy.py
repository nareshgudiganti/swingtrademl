"""Strategy execution capabilities shared by validation and order paths."""

# The app never places orders for these: the owner records their trades by hand.
MANUAL_ONLY_TYPES = frozenset({"long_term_value"})
# Ordered ONLY through the owner's go-live stages (brain M18,
# services/brain_golive/approvals.py) — never by the scan itself.
STAGED_TYPES = frozenset({"brain"})
# Never scanned by the daily engine — manual paper validation only.
NON_SCAN_STRATEGY_TYPES = frozenset({"tester_paper"})
# Books of stocks a person chose (evidence plan amendment 1, A3: "human-selected ideas never count as the
# brain's"): My Holdings / Real Trading (`real_trading`, services/portfolio.py) and manual paper testing
# (`tester_paper`, services/tester_paper.py). Never part of any brain result, baseline or gate.
HAND_BOOK_STRATEGY_NAMES = ("real_trading", "tester_paper")


def outside_tester_book(strategy_id_col):
    """A WHERE clause dropping the manual paper-testing book's rows.

    That book has its own starting capital (services/tester_paper.py), so its
    positions, trades and orders are never the bot's money: counting them used
    to fill the bot's position slots and spend its paper cash. Rows with no
    strategy at all are the bot's.
    """
    from sqlalchemy import or_, select

    from swing_trade_ml.db.models.trading import Strategy

    tester_ids = select(Strategy.id).where(Strategy.strategy_type.in_(sorted(NON_SCAN_STRATEGY_TYPES)))
    return or_(strategy_id_col.is_(None), strategy_id_col.not_in(tester_ids))


def creates_owner_private_strategy(name: str, strategy_type: str, execution_mode: str, mode: str) -> bool:
    """The `owner_private` flag a newly created strategy starts with.

    Private: a hand-book name, the manual-testing or manual-only type, or an advisory strategy
    stored as `live` (that is how real shares are recorded). The brain's staged
    type is always member-facing. Everything else made through the API is a
    registered model/rule strategy, which members may see.
    """
    # long_term_value is the owner's hand-recorded book (MANUAL_ONLY_TYPES): private until reviewed.
    if name in HAND_BOOK_STRATEGY_NAMES or strategy_type in NON_SCAN_STRATEGY_TYPES | MANUAL_ONLY_TYPES:
        return True
    if strategy_type in STAGED_TYPES:
        return False
    return execution_mode == "advisory" and mode == "live"


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
