"""Plain-English SELL states for the Bot and Testing tabs, and the book name in sell alerts. Display only.

Four states, each meaning one thing:
  * "PAPER SELL executed"     a paper position was sold in full (stop, target, time limit, model, manual).
  * "Partial SELL completed"  part of a paper position was sold at the first target; the rest is held.
  * "SELL review required"    an OPEN position is past its stop, target or time limit; a sell is due now.
  * "Exit check unavailable"  an OPEN position that the stop/target check cannot currently judge: exits are
                              switched off, the check job is not healthy, or the position has no price.

Nothing here sells, changes a stop or touches a stored trade.
"""

from __future__ import annotations

from swing_trade_ml.core.enums import ExitReason, TradingMode

PAPER_SELL = "PAPER SELL executed"
LIVE_SELL = "SELL executed"
PARTIAL_SELL = "Partial SELL completed"
REVIEW_REQUIRED = "SELL review required"
CHECK_UNAVAILABLE = "Exit check unavailable"

TESTING_STRATEGY_NAME = "tester_paper"


def book_label(strategy_name: str | None) -> str:
    """'Testing' for the manual Testing book, otherwise 'Bot': a sell alert must say which one."""
    return "Testing" if strategy_name == TESTING_STRATEGY_NAME else "Bot"


def trade_label(exit_reason: str | None, mode: str | None) -> str:
    if str(exit_reason) == ExitReason.SCALE_OUT:
        return PARTIAL_SELL
    return PAPER_SELL if str(mode) == TradingMode.PAPER else LIVE_SELL


def open_label(
    *,
    price: float | None,
    stop_loss: float | None,
    take_profit: float | None,
    holding_days: int | None,
    limit_days: int | None,
    exits_enabled: bool,
    check_job_ok: bool,
) -> str | None:
    """The state of an open position, or None when nothing needs saying.

    The check being unavailable is reported before a breach: if the check cannot be trusted, "no breach" and
    "breach" are both guesses, and the owner must hear that first."""
    if not exits_enabled or not check_job_ok or not price:
        return CHECK_UNAVAILABLE
    if stop_loss and price <= stop_loss:
        return REVIEW_REQUIRED
    if take_profit and price >= take_profit:
        return REVIEW_REQUIRED
    if limit_days and holding_days is not None and holding_days >= limit_days:
        return REVIEW_REQUIRED
    return None


def exit_check_health(db) -> tuple[bool, bool]:
    """(exits_enabled, check_job_ok). If the worker's run history cannot be read, the job is not called
    broken: nothing is claimed that is not known."""
    from swing_trade_ml.services import system_state
    from swing_trade_ml.workers import job_runs

    exits_enabled = bool(system_state.get_state(db).exits_enabled)
    try:
        runs, available = job_runs.read_runs()
    except Exception:  # noqa: BLE001 - a display helper must never break the page
        return exits_enabled, True
    last = runs.get("check_exits", {}).get("last_status") if available else None
    return exits_enabled, last in (None, "ok")
