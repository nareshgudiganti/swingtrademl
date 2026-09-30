"""M07's batch allocator: approvals that fit the account together.

v1's check_entry judges one stock against the account as it is now; v1 gets
away with that because it places each order before checking the next. The
brain places no orders, so the allocator keeps the running tally itself.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.modules.m07_risk.allocator import (
    Account,
    Candidate,
    CheckResult,
    Policy,
    allocate,
)


def _account(**overrides) -> Account:
    base = {
        "portfolio_value": 1_000_000.0,
        "cash": 1_000_000.0,
        "free_slots": 10,
        "min_position_inr": 10_000.0,
        "sector_rule": "pct_cap",
        "sector_cap_pct": 0.25,
        "sector_exposure": {},
        "deploy_room": 1_000_000.0,
    }
    return Account(**{**base, **overrides})


def _cost(price: float, qty: int) -> float:
    return price * qty


def _fixed_check(qty: int = 100):
    """Approves `qty` shares of every stock and records the cash it was given."""
    seen: list[tuple[str, float]] = []

    def check(cand: Candidate, cash_left: float) -> CheckResult:
        seen.append((cand.symbol, cash_left))
        return CheckResult(allowed=True, qty=qty, reason="Sized by risk-per-trade")

    return check, seen


def _run(cands, account=None, check=None, mode=MarketMode.NORMAL):
    check = check or _fixed_check()[0]
    verdicts = allocate(cands, account or _account(), check, Policy(mode=mode), _cost)
    return {v.symbol: v for v in verdicts}


def test_strongest_candidate_is_judged_first_and_ties_break_by_symbol():
    check, seen = _fixed_check()
    cands = [
        Candidate("BBB", 100.0, 0.7, None),
        Candidate("CCC", 100.0, 0.9, None),
        Candidate("AAA", 100.0, 0.7, None),
    ]
    _run(cands, check=check)
    assert [s for s, _ in seen] == ["CCC", "AAA", "BBB"]


def test_no_new_trades_refuses_everything():
    out = _run([Candidate("AAA", 100.0, 0.9, None)], mode=MarketMode.NO_NEW_TRADES)
    assert out["AAA"].allowed is False and out["AAA"].rule == "MARKET"


def test_weakest_ideas_lose_when_slots_run_out():
    cands = [Candidate(s, 100.0, p, None) for s, p in (("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7))]
    out = _run(cands, account=_account(free_slots=2))
    assert out["AAA"].allowed and out["BBB"].allowed
    assert out["CCC"].rule == "POSITION_LIMIT" and "stronger" in out["CCC"].reason


def test_each_check_sees_cash_left_after_stronger_approvals():
    check, seen = _fixed_check(qty=100)
    cands = [Candidate("AAA", 1_000.0, 0.9, None), Candidate("BBB", 1_000.0, 0.8, None)]
    _run(cands, account=_account(cash=500_000.0), check=check)
    assert seen == [("AAA", 500_000.0), ("BBB", 400_000.0)]


def test_second_stock_in_a_sector_is_shrunk_to_the_room_left():
    # 25% of 10 lakh = 2.5 lakh sector room; first takes 2 lakh, 50k left.
    cands = [Candidate("BANK1", 1_000.0, 0.9, "bank"), Candidate("BANK2", 1_000.0, 0.8, "bank")]
    out = _run(cands, check=_fixed_check(qty=200)[0])
    assert out["BANK1"].max_qty == 200
    assert out["BANK2"].max_qty == 50


def test_sector_refuses_when_room_left_is_below_the_minimum_position():
    cands = [Candidate("BANK1", 1_000.0, 0.9, "bank"), Candidate("BANK2", 1_000.0, 0.8, "bank")]
    out = _run(cands, account=_account(sector_exposure={"bank": 45_000.0}), check=_fixed_check(qty=200)[0])
    assert out["BANK1"].max_qty == 200
    assert out["BANK2"].allowed is False and out["BANK2"].rule == "SECTOR_CAP"


def test_one_per_sector_refuses_a_second_approval_in_the_same_sector():
    cands = [Candidate("BANK1", 100.0, 0.9, "bank"), Candidate("BANK2", 100.0, 0.8, "bank")]
    out = _run(cands, account=_account(sector_rule="one_per_sector", sector_cap_pct=None))
    assert out["BANK1"].allowed and out["BANK2"].rule == "SECTOR_CAP"


def test_market_conditions_room_is_shared_across_the_batch():
    cands = [Candidate("AAA", 1_000.0, 0.9, None), Candidate("BBB", 1_000.0, 0.8, None)]
    out = _run(cands, account=_account(deploy_room=150_000.0), check=_fixed_check(qty=100)[0])
    assert out["AAA"].max_qty == 100
    assert out["BBB"].max_qty == 50


def test_defensive_mode_halves_size_and_allows_only_two_new_ideas():
    cands = [Candidate(s, 100.0, p, None) for s, p in (("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7))]
    out = _run(cands, check=_fixed_check(qty=300)[0], mode=MarketMode.DEFENSIVE)
    assert out["AAA"].max_qty == 150 and out["BBB"].max_qty == 150
    assert out["CCC"].rule == "DEFENSIVE_LIMIT"


def test_defensive_half_size_below_minimum_is_refused():
    out = _run(
        [Candidate("AAA", 100.0, 0.9, None)], check=_fixed_check(qty=150)[0], mode=MarketMode.DEFENSIVE
    )
    assert out["AAA"].allowed is False and out["AAA"].rule == "DEFENSIVE_SIZE"


def test_a_v1_refusal_is_passed_through_unchanged():
    def refuse(cand, cash_left):
        return CheckResult(allowed=False, rule="COOLDOWN", reason="Stopped out within the last 5 days")

    out = _run([Candidate("AAA", 100.0, 0.9, None)], check=refuse)
    assert out["AAA"].rule == "COOLDOWN" and out["AAA"].reason.startswith("Stopped out")


def test_a_refused_stock_does_not_use_up_a_slot():
    def refuse_aaa(cand, cash_left):
        if cand.symbol == "AAA":
            return CheckResult(allowed=False, rule="AVOID", reason="Results on Friday")
        return CheckResult(allowed=True, qty=100, reason="ok")

    cands = [Candidate("AAA", 100.0, 0.9, None), Candidate("BBB", 100.0, 0.8, None)]
    out = _run(cands, account=_account(free_slots=1), check=refuse_aaa)
    assert out["BBB"].allowed


def test_a_check_that_raises_refuses_only_that_stock():
    def flaky(cand, cash_left):
        if cand.symbol == "AAA":
            raise RuntimeError("instrument missing")
        return CheckResult(allowed=True, qty=100, reason="ok")

    out = _run([Candidate("AAA", 100.0, 0.9, None), Candidate("BBB", 100.0, 0.8, None)], check=flaky)
    assert out["AAA"].rule == "ERROR" and out["BBB"].allowed


@pytest.mark.parametrize("mode", [MarketMode.NORMAL, MarketMode.DEFENSIVE, MarketMode.NO_NEW_TRADES])
def test_every_refusal_explains_itself(mode):
    cands = [Candidate(s, 100.0, 0.9 - i / 10, "bank") for i, s in enumerate(("A1", "A2", "A3", "A4"))]
    out = _run(cands, account=_account(free_slots=1), mode=mode)
    assert all(v.reason for v in out.values() if not v.allowed)
