# ruff: noqa: E501 (long plain-English test text)
"""#252: capital limits, position sizing and allocation, verified at five account sizes (tests only; nothing here
changes the app). Findings note: docs/verification/252-capital-limits-sizing.md.

Account sizes: Rs 10,000, 25,000, 1,00,000, 10,00,000 and 1,00,00,000 (Rs 1 crore). Rs 10K, 1L, 10L and 1Cr are ladder
rungs; Rs 25K sits between two rungs, where the limits are blended on a log scale (services/limits.py).

Settled rules checked (CLAUDE.md, never loosened): +8% target / -4% stop / half out at +5% / 15 trading days for the
brain plan (5D lane +2% / -4% / 5); 15% drawdown halt; 25% of the account in one sector (smallest tier: one stock per
sector); limits scale with account size; 1% risk per trade; a minimum position; a daily buy cap; DEFENSIVE half size.
"""

from __future__ import annotations

import itertools
import math

import pytest

from swing_trade_ml.brain import pause_check
from swing_trade_ml.brain.contracts import MarketMode
from swing_trade_ml.brain.modules.m07_risk.allocator import Account, CheckResult, Policy, allocate
from swing_trade_ml.brain.modules.m07_risk.allocator import Candidate as AllocCandidate
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.core.config import settings
from swing_trade_ml.services import costs, risk
from swing_trade_ml.services.limits import RUNGS, limits_for
from swing_trade_ml.simulation import rules as sim_rules
from test_portfolio_risk_layer import _flat_deployable, _instrument, _open_position, _strategy

ACCOUNTS = [10_000, 25_000, 100_000, 1_000_000, 10_000_000]
LADDER = {  # the published ladder: positions, max share of the account in one stock, minimum position, sector rule, sector cap, cash floor
    10_000: (2, 0.50, 4_000, "one_per_sector", None, 0.0),
    100_000: (4, 0.25, 15_000, "pct_cap", 0.25, 0.05),
    1_000_000: (8, 0.10, 40_000, "pct_cap", 0.25, 0.10),
    10_000_000: (22, 0.045, 150_000, "pct_cap", 0.25, 0.10),
}
PRICES = [37.5, 99.99, 250.0, 500.0, 1_234.56, 2_400.0, 4_999.0]


def _stop(price: float) -> float:
    return price * 0.96  # the settled -4% stop


# ------------------------------------------------------------------------------- the ladder


@pytest.mark.parametrize("value", sorted(LADDER))
def test_each_published_rung_gives_exactly_its_published_limits(value):
    lim = limits_for(value)
    positions, pct, minimum, rule, cap, floor = LADDER[value]
    assert (lim.max_positions, lim.max_position_pct, lim.min_position_inr) == (positions, pct, minimum)
    assert (lim.sector_rule, lim.sector_cap_pct, lim.cash_floor_pct) == (rule, cap, floor)
    assert lim.rung_value == value


def test_the_ladder_has_the_six_published_rungs_and_the_top_one_is_one_crore_ten_million():
    assert [r.value for r in RUNGS] == [10_000, 100_000, 1_000_000, 2_500_000, 5_000_000, 10_000_000]


def test_twenty_five_thousand_sits_strictly_between_its_neighbouring_rungs():
    low, mid, high = limits_for(10_000), limits_for(25_000), limits_for(100_000)
    assert low.max_positions < mid.max_positions < high.max_positions
    assert high.max_position_pct < mid.max_position_pct < low.max_position_pct
    assert low.min_position_inr < mid.min_position_inr < high.min_position_inr
    assert mid.sector_rule == "one_per_sector"  # one stock per sector until the account reaches the Rs 1L rung


def test_limits_scale_with_the_account_across_the_whole_range():
    grid = [5_000 * 1.25**i for i in range(40)]  # Rs 5K to far above Rs 1Cr
    rows = [limits_for(v) for v in grid]
    for a, b in itertools.pairwise(rows):
        assert b.max_positions >= a.max_positions
        assert b.min_position_inr >= a.min_position_inr
        assert b.max_position_pct <= a.max_position_pct + 1e-12
        assert b.cash_floor_pct >= a.cash_floor_pct - 1e-12
    for lim in rows:
        assert lim.sector_cap_pct in (None, 0.25)  # never looser than the settled 25%
        assert lim.max_position_pct <= 0.5 and lim.max_positions >= 2


@pytest.mark.parametrize("bad", [0, -5, None])
def test_a_missing_or_non_positive_account_value_gets_the_smallest_rung(bad):
    assert limits_for(bad).rung_value == 10_000 and limits_for(bad).max_positions == 2  # type: ignore[arg-type]


def test_the_settled_risk_values_are_what_the_code_reads():
    lim = limits_for(1_000_000)
    assert (lim.risk_per_trade_pct, lim.max_drawdown_pct) == (0.01, 0.15)
    assert settings.MAX_PORTFOLIO_DRAWDOWN_PCT == 0.15 and pause_check.HALT == 0.15 == sim_rules.SETTLED_DRAWDOWN_HALT
    assert sim_rules.SETTLED_RISK_PER_TRADE == settings.RISK_PER_TRADE_PCT == 0.01


def test_the_trade_plan_constants_are_the_settled_ones():
    plan = DecidePolicy()
    assert (plan.target_pct, plan.stop_pct, plan.first_target_pct, plan.horizon_days) == (0.08, 0.04, 0.05, 15)
    assert (settings.ML_TARGET_RETURN_PCT, settings.ML_STOP_RETURN_PCT, settings.ML_FIRST_TARGET_PCT) == (0.08, 0.04, 0.05)
    five = sim_rules.TradingRules.plan_5d()
    assert (five.target, five.stop, five.half_out, five.horizon_sessions) == (0.02, 0.04, None, 5)
    fifteen = sim_rules.TradingRules.plan_15d()
    assert (fifteen.target, fifteen.stop, fifteen.half_out, fifteen.horizon_sessions) == (0.08, 0.04, 0.05, 15)
    assert (sim_rules.SETTLED_MAX_NEW_PER_DAY, sim_rules.SETTLED_DEFENSIVE_MAX_NEW) == (5, 2)


# ------------------------------------------------------------------------------- a strategy's own overrides


def _strategy_row(**fields):
    """A real `Strategy` row (not saved): `limits_for` reads its max_positions and capital_allocation."""
    from swing_trade_ml.db.models.trading import Strategy

    return Strategy(name="s252-override", strategy_type="ml_swing", mode="paper", **fields)


@pytest.mark.parametrize("value", ACCOUNTS)
def test_a_strategy_may_make_its_own_limits_tighter_than_the_ladder(value):
    ladder = limits_for(value)
    tight = limits_for(value, _strategy_row(max_positions=1, capital_allocation=0.02))
    assert tight.max_positions == 1 and tight.max_position_pct == 0.02
    assert tight.max_positions <= ladder.max_positions and tight.max_position_pct <= ladder.max_position_pct


@pytest.mark.parametrize("value", [10_000, 100_000, 10_000_000])
def test_a_strategy_override_must_never_loosen_the_ladder(value):
    ladder = limits_for(value)
    loose = limits_for(value, _strategy_row(max_positions=50, capital_allocation=0.9))
    assert loose.max_positions <= ladder.max_positions
    assert loose.max_position_pct <= ladder.max_position_pct


@pytest.mark.parametrize("value", [10_000, 100_000, 1_000_000, 10_000_000])
def test_a_looser_strategy_is_capped_at_exactly_the_ladder_values(value):
    ladder = limits_for(value)
    loose = limits_for(value, _strategy_row(max_positions=50, capital_allocation=0.9))
    assert loose.max_positions == ladder.max_positions
    assert loose.max_position_pct == ladder.max_position_pct


@pytest.mark.parametrize("value", [10_000, 100_000, 1_000_000, 10_000_000])
def test_each_field_is_capped_on_its_own_and_unset_means_the_ladder(value):
    ladder = limits_for(value)
    only_count = limits_for(value, _strategy_row(max_positions=50, capital_allocation=0.01))
    assert only_count.max_positions == ladder.max_positions and only_count.max_position_pct == 0.01
    only_pct = limits_for(value, _strategy_row(max_positions=1, capital_allocation=0.9))
    assert only_pct.max_positions == 1 and only_pct.max_position_pct == ladder.max_position_pct
    unset = limits_for(value, _strategy_row())
    assert (unset.max_positions, unset.max_position_pct) == (ladder.max_positions, ladder.max_position_pct)


@pytest.mark.parametrize("value", [10_000, 100_000, 1_000_000, 10_000_000])
def test_a_strategy_equal_to_the_ladder_is_unchanged(value):
    ladder = limits_for(value)
    same = limits_for(value, _strategy_row(max_positions=ladder.max_positions, capital_allocation=ladder.max_position_pct))
    assert same == ladder


def test_what_a_loosened_override_does_not_loosen_the_other_limits_still_hold():
    """Context for the gap: the override changes the position count and the single-stock cap only. The risk-per-trade
    size, minimum position, sector rule and cash floor come from elsewhere in `limits_for` and are unchanged."""
    ladder, loose = limits_for(1_000_000), limits_for(1_000_000, _strategy_row(max_positions=50, capital_allocation=0.9))
    for field in ("min_position_inr", "sector_rule", "sector_cap_pct", "cash_floor_pct", "risk_per_trade_pct", "max_drawdown_pct"):
        assert getattr(loose, field) == getattr(ladder, field), field
    qty, _ = risk.calculate_quantity(500.0, 480.0, 1_000_000, 1_000_000, limits=loose)
    assert qty * 20.0 <= 1_000_000 * 0.01 + 1e-9  # a stop-out still costs at most 1% of the account


# ------------------------------------------------------------------------------- sizing: size per trade, rounding, cash


@pytest.mark.parametrize("value", ACCOUNTS)
@pytest.mark.parametrize("price", PRICES)
def test_a_size_never_exceeds_the_concentration_cap_the_risk_budget_or_the_cash(value, price):
    lim = limits_for(value)
    qty, note = risk.calculate_quantity(price, _stop(price), value, value, limits=lim)
    assert isinstance(qty, int) and qty >= 0, note
    assert qty * price <= value * lim.max_position_pct + 1e-9  # whole shares round DOWN: the cap is never exceeded
    assert qty * (price - _stop(price)) <= value * 0.01 + 1e-9  # a stop-out costs at most 1% of the account
    assert risk.buy_cost(price, qty) <= value  # cash never goes negative, charges included


@pytest.mark.parametrize("value", ACCOUNTS)
def test_a_tight_cash_balance_still_never_goes_negative(value):
    lim = limits_for(value)
    for fraction in (0.02, 0.1, 0.33, 0.77):
        cash = value * fraction
        for price in PRICES:
            qty, _ = risk.calculate_quantity(price, _stop(price), value, cash, limits=lim)
            assert risk.buy_cost(price, qty) <= cash + 1e-9, (value, cash, price, qty)


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_a_sector_room_ceiling_is_a_hard_rupee_limit_on_the_size(value):
    lim = limits_for(value)
    room = value * 0.05
    for price in PRICES:
        qty, _ = risk.calculate_quantity(price, _stop(price), value, value, limits=lim, ceilings={"sector limit": room})
        assert qty * price <= room + 1e-9


def test_the_concentration_cap_counts_what_is_already_held_in_the_stock():
    lim = limits_for(1_000_000)
    qty, _ = risk.calculate_quantity(500.0, 480.0, 1_000_000, 1_000_000, existing_exposure=90_000.0, limits=lim)
    assert qty * 500.0 + 90_000.0 <= 1_000_000 * lim.max_position_pct
    qty, _ = risk.calculate_quantity(500.0, 480.0, 1_000_000, 1_000_000, existing_exposure=100_000.0, limits=lim)
    assert qty == 0


def test_no_stop_supplied_sizes_off_the_wider_default_stop_so_the_size_is_smaller_never_larger():
    with_stop, _ = risk.calculate_quantity(500.0, 480.0, 100_000, 100_000)  # a 4% stop
    without, _ = risk.calculate_quantity(500.0, None, 100_000, 100_000)  # DEFAULT_STOP_LOSS_PCT is 5%
    assert settings.DEFAULT_STOP_LOSS_PCT == 0.05 and 0 < without <= with_stop


def test_measured_at_the_fill_price_a_position_can_pass_the_cap_by_the_slippage_only():
    """OBSERVED, not a defect: the caps are measured at the signal price. The paper fill is 5 basis points higher, so a
    position that fills the cap exactly (no whole-share slack) ends up to 0.05% over it. Pinned so a change is noticed."""
    value = 1_000_000
    lim = limits_for(value)
    qty, _ = risk.calculate_quantity(500.0, 480.0, value, value, limits=lim)
    assert qty * 500.0 == value * lim.max_position_pct  # exactly at the cap at the signal price
    fill = costs.apply_slippage(500.0, "BUY")
    over = qty * fill / (value * lim.max_position_pct) - 1
    assert 0 < over <= settings.PAPER_SLIPPAGE_BPS / 10_000 + 1e-12


# ------------------------------------------------------------------------------- the entry gate at each size


def _enter(db, value: float, symbol: str, price: float = 500.0, cash: float | None = None, strategy=None):
    inst = _instrument(db, symbol)
    return risk.check_entry(
        db, mode="paper", instrument_id=inst.id, price=price, stop_loss=_stop(price),
        portfolio_value=value, available_cash=value if cash is None else cash, strategy=strategy,
    )


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_a_normal_entry_is_allowed_at_and_above_the_one_lakh_rung_and_inside_every_limit(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    decision = _enter(db_session, value, f"ZQ{value}")
    lim = limits_for(value)
    assert decision.allowed and decision.quantity >= 1
    assert lim.min_position_inr <= decision.quantity * 500.0 <= value * lim.max_position_pct
    assert risk.buy_cost(500.0, decision.quantity) <= value - lim.cash_floor_inr + 1e-6


@pytest.mark.parametrize("value", [10_000, 25_000])
def test_the_two_smallest_accounts_never_trade_and_the_reason_is_the_minimum_position(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    for price in (50.0, 500.0, 2_400.0):
        decision = _enter(db_session, value, f"ZS{value}{int(price)}", price=price)
        assert decision.allowed is False and decision.rule == "MIN_POSITION", (value, price, decision.rule)
        assert "minimum" in decision.reason and "fixed charges" in decision.reason


def test_why_the_small_accounts_never_trade_and_where_that_stops_being_true():
    """In plain words: risking 1% of the account on a trade with a 4% stop makes the trade 25% of the account. Below
    about Rs 43,000 that is smaller than the minimum position (the size below which fixed charges eat the trade), so the
    risk-sized trade is always refused. The rule is the owner's (accepted); this pins the numbers behind it."""
    lim10, lim25 = limits_for(10_000), limits_for(25_000)
    assert 10_000 * 0.25 == 2_500 < lim10.min_position_inr == 4_000
    assert 25_000 * 0.25 == 6_250 < lim25.min_position_inr < 8_400
    crossover = next(v for v in range(10_000, 100_001, 100) if v * 0.25 >= limits_for(v).min_position_inr)
    assert 40_000 <= crossover <= 45_000  # the smallest account (in Rs 100 steps) whose 25% trade clears the minimum
    assert limits_for(100_000).min_position_inr <= 100_000 * 0.25  # and at the Rs 1L rung it does, with room to spare


@pytest.mark.parametrize("value", [1_000_000, 10_000_000])
def test_above_the_hundred_thousand_rung_the_concentration_cap_makes_the_stop_out_cost_less_than_one_percent(value):
    """At Rs 10L and Rs 1Cr the single-stock cap (10%, 4.5%) is tighter than the 25% the 1%-risk rule would give, so
    the cap binds and the real loss at the stop is 0.4% or 0.18% of the account: caution, not a gap."""
    lim = limits_for(value)
    qty, note = risk.calculate_quantity(500.0, 480.0, value, value, limits=lim)
    assert note == "Sized by concentration cap" and qty * 20.0 < value * 0.01


@pytest.mark.parametrize("value", [10_000, 25_000, 100_000, 1_000_000, 10_000_000])
def test_the_open_position_limit_refuses_the_next_buy_and_one_below_it_passes(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    lim = limits_for(value)
    strat = _strategy(db_session, name=f"s252_slots_{value}")
    for i in range(lim.max_positions - 1):
        _open_position(db_session, strat, _instrument(db_session, f"ZP{value}X{i}"), quantity=1, entry_price=10.0)
    db_session.commit()
    one_below = _enter(db_session, value, f"ZP{value}LAST")  # one slot is still free: not refused for the slot count
    assert one_below.rule != "POSITION_LIMIT"
    if value >= 100_000:
        assert one_below.allowed
    _open_position(db_session, strat, _instrument(db_session, f"ZP{value}FILL"), quantity=1, entry_price=10.0)
    db_session.commit()
    full = _enter(db_session, value, f"ZP{value}NEXT")
    assert full.allowed is False and full.rule == "POSITION_LIMIT"


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_the_sector_cap_never_lets_a_sector_pass_twenty_five_percent(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    lim = limits_for(value)
    strat = _strategy(db_session, name=f"s252_sector_{value}")
    held = value * 0.20  # banks already take 20% of the account
    _open_position(db_session, strat, _instrument(db_session, "ICICIBANK"), quantity=int(held / 1000), entry_price=1000.0)
    db_session.commit()
    room = lim.sector_cap_pct * value - held
    decision = _enter(db_session, value, "HDFCBANK", price=1000.0)
    if room < lim.min_position_inr:
        assert decision.allowed is False and decision.rule == "SECTOR_CAP"  # not even a minimum position fits
    else:
        assert decision.allowed and decision.quantity * 1000.0 <= room + 1e-9  # shrunk to the room that is left
        assert held + decision.quantity * 1000.0 <= lim.sector_cap_pct * value + 1e-9
    assert decision.allowed is False or held + decision.quantity * 1000.0 <= 0.25 * value + 1e-9


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_a_sector_already_at_its_cap_refuses_another_stock_in_it(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    strat = _strategy(db_session, name=f"s252_sector_full_{value}")
    _open_position(db_session, strat, _instrument(db_session, "ICICIBANK"), quantity=int(value * 0.25 / 1000), entry_price=1000.0)
    db_session.commit()
    decision = _enter(db_session, value, "HDFCBANK", price=1000.0)
    assert decision.allowed is False and decision.rule == "SECTOR_CAP"


@pytest.mark.parametrize("value", [10_000, 25_000])
def test_at_the_two_smallest_sizes_a_second_stock_in_one_sector_is_refused_outright(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    strat = _strategy(db_session, name=f"s252_one_per_sector_{value}")
    _open_position(db_session, strat, _instrument(db_session, "ICICIBANK"), quantity=1, entry_price=100.0)
    db_session.commit()
    decision = _enter(db_session, value, "HDFCBANK", price=1000.0)
    assert decision.allowed is False and decision.rule == "SECTOR_CAP" and "one stock per sector" in decision.reason


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_the_cash_floor_keeps_the_reserve_at_each_rung_that_has_one(db_session, monkeypatch, value):
    _flat_deployable(monkeypatch)
    lim = limits_for(value)
    floor = lim.cash_floor_inr
    assert floor == value * lim.cash_floor_pct > 0
    short = _enter(db_session, value, f"ZCASHFLOOR{value}", cash=floor + lim.min_position_inr * 0.5)
    assert short.allowed is False and short.rule == "CASH_FLOOR"
    spare = lim.min_position_inr * 1.5
    roomy = _enter(db_session, value, f"ZCASHROOM{value}", cash=floor + spare)
    assert roomy.allowed and risk.buy_cost(500.0, roomy.quantity) <= spare + 1e-6  # spends only what is above the reserve


def test_the_smallest_rung_has_no_cash_floor():
    assert limits_for(10_000).cash_floor_inr == 0.0


# ------------------------------------------------------------------------------- the Brain's batch allocator


def _account(value: float, cash: float | None = None) -> Account:
    lim = limits_for(value)
    return Account(
        portfolio_value=value, cash=value if cash is None else cash, free_slots=lim.max_positions,
        min_position_inr=lim.min_position_inr, sector_rule=lim.sector_rule, sector_cap_pct=lim.sector_cap_pct,
        deploy_room=value,
    )


def _check_for(value: float):
    lim = limits_for(value)

    def check(cand: AllocCandidate, cash_left: float) -> CheckResult:
        qty, note = risk.calculate_quantity(cand.price, _stop(cand.price), value, cash_left, limits=lim)
        if qty < 1 or qty * cand.price < lim.min_position_inr:
            return CheckResult(False, rule="MIN_POSITION", reason="below the minimum position")
        return CheckResult(True, qty=qty, reason=note)

    return check


def _ideas(n: int = 8) -> list[AllocCandidate]:
    return [AllocCandidate(f"S{i}", 400.0 + 25 * i, 0.9 - 0.05 * i, f"bucket{i % 4}") for i in range(n)]


@pytest.mark.parametrize("value", [100_000, 1_000_000, 10_000_000])
def test_the_allocator_never_overspends_cash_slots_or_a_sector(value):
    account, lim = _account(value), limits_for(value)
    out = allocate(_ideas(), account, _check_for(value), Policy(MarketMode.NORMAL), risk.buy_cost)
    approved = [(v, next(c for c in _ideas() if c.symbol == v.symbol)) for v in out if v.allowed]
    assert approved and len(approved) <= lim.max_positions
    assert sum(risk.buy_cost(c.price, v.max_qty) for v, c in approved) <= account.cash
    by_bucket: dict[str, float] = {}
    for v, c in approved:
        by_bucket[c.bucket] = by_bucket.get(c.bucket, 0.0) + v.max_qty * c.price
        assert v.max_qty * c.price >= lim.min_position_inr
        assert v.max_qty * c.price <= value * lim.max_position_pct + 1e-9
    assert all(total <= 0.25 * value + 1e-9 for total in by_bucket.values())


@pytest.mark.parametrize("value", [1_000_000, 10_000_000])
def test_defensive_means_at_most_two_new_ideas_each_at_most_half_the_normal_size(value):
    normal = {v.symbol: v for v in allocate(_ideas(), _account(value), _check_for(value), Policy(MarketMode.NORMAL), risk.buy_cost)}
    defensive = [v for v in allocate(_ideas(), _account(value), _check_for(value), Policy(MarketMode.DEFENSIVE), risk.buy_cost) if v.allowed]
    assert len(defensive) == 2  # not vacuous: exactly the two strongest are approved
    for v in defensive:
        assert 0 < v.max_qty <= math.floor(normal[v.symbol].max_qty * 0.5)  # half size, rounded down


def test_at_one_lakh_a_defensive_market_approves_nothing_because_half_a_trade_is_below_the_minimum():
    """OBSERVED, by design (the minimum position): at Rs 1L a normal trade is Rs 25,000 and the minimum is Rs 15,000, so
    half a trade (about Rs 12,500) is below it. Defensive days therefore buy nothing until the account is roughly twice
    the minimum position's size per trade (found by `crossover` below)."""
    value = 100_000
    out = allocate(_ideas(), _account(value), _check_for(value), Policy(MarketMode.DEFENSIVE), risk.buy_cost)
    assert out and not any(v.allowed for v in out) and {v.rule for v in out} == {"DEFENSIVE_SIZE"}
    crossover = next(v for v in range(100_000, 1_000_001, 5_000) if any(x.allowed for x in allocate(_ideas(), _account(v), _check_for(v), Policy(MarketMode.DEFENSIVE), risk.buy_cost)))
    assert 100_000 < crossover <= 350_000  # about Rs 3 lakh


@pytest.mark.parametrize("value", ACCOUNTS)
def test_no_new_trades_approves_nothing_at_any_size(value):
    out = allocate(_ideas(), _account(value), _check_for(value), Policy(MarketMode.NO_NEW_TRADES), risk.buy_cost)
    assert out and not any(v.allowed for v in out) and {v.rule for v in out} == {"MARKET"}


@pytest.mark.parametrize("value", [10_000, 25_000])
def test_the_allocator_agrees_that_the_smallest_accounts_do_not_trade(value):
    out = allocate(_ideas(), _account(value), _check_for(value), Policy(MarketMode.NORMAL), risk.buy_cost)
    assert not any(v.allowed for v in out)
