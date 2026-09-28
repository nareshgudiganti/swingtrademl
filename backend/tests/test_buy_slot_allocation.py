"""Why the bot bought nothing between 17 and 27 September 2026.

Two independent faults, one test each. Both had the same visible symptom —
a scan reporting dozens of BUY signals and `executed: 0` — and the second
hid the first, because only the top-ranked candidates ever reached sizing.

1. The daily buy slots were awarded by confidence *before* `risk.check_entry`
   ran, and a rejection did not give the slot back. The two highest-confidence
   names were ones check_entry would always refuse (cap tier, ASM list,
   stop-out cooldown, below-minimum size), so they burned both slots and every
   remaining candidate was discarded as "ranked out".

2. `fixed_amount` sizing targeted a flat rupee amount that could sit below the
   account ladder's own `min_position_inr`, so `check_entry` rejected the
   very quantity its own sizer had just produced. On the ~₹9.8L paper account
   that was ₹10,000 against a ₹39,778 floor: no buy could ever pass.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.services import deployable, engine, risk
from swing_trade_ml.services.limits import limits_for
from swing_trade_ml.services.risk import calculate_quantity
from swing_trade_ml.strategies.base import SignalDecision

# The real paper account the September 2026 outage happened on.
PAPER_ACCOUNT_INR = 979_791.66


def _scan_three_buys(monkeypatch, *, executes: set[int], slots: int) -> list[tuple[int, str | None]]:
    """Run one scan over three BUY candidates and report what was attempted.

    Candidate `i` is offered at confidence 0.9 - i/10, so instrument ids 0, 1
    and 2 are already in descending-confidence order. Only ids in `executes`
    come back from process_decision as filled; the rest stand for the entries
    check_entry refuses. Returns (instrument_id, ranked_out_reason) per call,
    in the order the scan made them.
    """
    strategy = Strategy(
        id=1, name="scan", mode="paper", strategy_type="ml_swing",
        execution_mode="auto", max_positions=slots, max_daily_buys=None,
    )
    items = [SimpleNamespace(id=i, tradingsymbol=str(i)) for i in range(3)]
    decisions = {i: SignalDecision(SignalType.BUY, 100.0, 0.9 - i / 10) for i in range(3)}

    impl = SimpleNamespace(min_bars_required=lambda: 1, evaluate=lambda df, i, db: decisions[i.id])
    monkeypatch.setattr(engine, "get_strategy", lambda *a: impl)
    monkeypatch.setattr(engine, "eligible_instruments", lambda *a: items)
    monkeypatch.setattr(engine, "load_candles", lambda *a, **kw: pd.DataFrame({"close": [100.0]}))
    monkeypatch.setattr(engine.risk, "open_position_count", lambda db, mode, strategy_id=None: 0)
    monkeypatch.setattr(engine.risk, "active_strategy_count", lambda db, mode: 1)
    monkeypatch.setattr(
        engine, "portfolio_value_and_cash", lambda db, mode: (PAPER_ACCOUNT_INR, PAPER_ACCOUNT_INR)
    )

    calls: list[tuple[int, str | None]] = []

    def process(db, strategy, instrument, decision, ranked_out_reason=None):
        calls.append((instrument.id, ranked_out_reason))
        filled = ranked_out_reason is None and instrument.id in executes
        return SimpleNamespace(was_executed=filled)

    monkeypatch.setattr(engine, "process_decision", process)

    assert not engine.run_strategy(Mock(), strategy).errors
    return calls


def test_a_rejected_buy_does_not_consume_a_daily_buy_slot(monkeypatch):
    """The September outage in miniature: one slot, and the highest-confidence
    candidate is one check_entry refuses. The slot must survive that rejection
    and be spent on the next candidate down, instead of the scan ending with
    nothing bought."""
    calls = _scan_three_buys(monkeypatch, executes={1}, slots=1)

    attempted = [inst_id for inst_id, reason in calls if reason is None]
    assert attempted == [0, 1], "the runner-up must still be tried after the favourite is refused"

    ranked_out = [inst_id for inst_id, reason in calls if reason is not None]
    assert ranked_out == [2], "only candidates beyond a *filled* slot are ranked out"


def test_filled_buys_still_stop_at_the_slot_budget(monkeypatch):
    """The other side of the same rule — slots are a real cap, not advice.
    Once the budget is spent on actual fills, the rest are ranked out without
    being attempted."""
    calls = _scan_three_buys(monkeypatch, executes={0, 1, 2}, slots=2)

    assert [inst_id for inst_id, reason in calls if reason is None] == [0, 1]
    assert [inst_id for inst_id, reason in calls if reason is not None] == [2]


def test_fixed_amount_sizing_never_lands_below_the_accounts_minimum(monkeypatch):
    """check_entry rejects any position worth less than `min_position_inr`, so
    a sizer that targets less than that floor can only ever produce entries
    check_entry will throw away. The flat target must be lifted to the floor
    rather than fed through as-is."""
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "fixed_amount")
    monkeypatch.setattr(settings, "FIXED_POSITION_AMOUNT_INR", 10_000.0)

    floor = limits_for(PAPER_ACCOUNT_INR, None).min_position_inr
    assert floor > 10_000.0, "fixture must reproduce a flat target below the ladder floor"

    quantity, _note = calculate_quantity(
        price=100.0,
        stop_loss=96.0,
        portfolio_value=PAPER_ACCOUNT_INR,
        available_cash=PAPER_ACCOUNT_INR,
    )

    assert quantity * 100.0 >= floor


def test_the_september_2026_paper_account_can_buy_again(db_session, monkeypatch):
    """The outage reproduced end to end against the real gate.

    Every number here is the live paper configuration on 27 Sept 2026: a
    ₹9,79,792 book with nothing open, `fixed_amount` sizing at ₹10,000, and a
    "stressed" market letting only 10% of the account be deployed. Under that
    exact setup `check_entry` refused every entry with MIN_POSITION, which is
    why the bot booked no trade for eleven days. It must now approve one.
    """
    monkeypatch.setattr(settings, "POSITION_SIZING_MODE", "fixed_amount")
    monkeypatch.setattr(settings, "FIXED_POSITION_AMOUNT_INR", 10_000.0)
    monkeypatch.setattr(
        deployable, "current_deployable",
        lambda db: deployable.DeployableCapital(
            regime="stressed", fraction=0.10, context_available=True
        ),
    )

    strategy = Strategy(name="sept_outage_strategy", strategy_type="ml_swing", mode="paper")
    instrument = Instrument(
        instrument_token=987_654, tradingsymbol="ZZZIRCON", exchange="NSE", is_watchlisted=True
    )
    db_session.add_all([strategy, instrument])
    db_session.commit()

    decision = risk.check_entry(
        db_session,
        mode="paper",
        instrument_id=instrument.id,
        price=105.85,
        stop_loss=101.62,
        portfolio_value=PAPER_ACCOUNT_INR,
        available_cash=PAPER_ACCOUNT_INR,
        strategy=strategy,
    )

    assert decision.allowed is True, f"still blocked by {decision.rule}: {decision.reason}"
    assert decision.quantity >= 1
    floor = limits_for(PAPER_ACCOUNT_INR, strategy).min_position_inr
    assert decision.quantity * 105.85 >= floor
