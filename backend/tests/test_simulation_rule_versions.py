"""#321 the trade rule as a setting: the 15-day plan and the 5-day trade rule, each refused if looser,
carried on every ledger record, never mixed in one comparison. Sizing is unchanged: the two smallest
balances still never trade. Pure: no database, no clock."""

from __future__ import annotations

from dataclasses import replace

import pytest

from swing_trade_ml.services.costs import apply_slippage
from swing_trade_ml.simulation.cohorts import PortfolioSpec, build_matrix
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import (
    Bar,
    Candidate,
    compare_by_policy,
    ledgers_rule_version,
    run_cohort,
    run_portfolio,
)
from swing_trade_ml.simulation.rules import (
    RULE_5D,
    RULE_15D,
    MixedRuleVersions,
    RuleLoosened,
    TradingRules,
)

SESSIONS = tuple(f"2026-12-{day:02d}" for day in range(1, 31))
PLAN_15D = TradingRules.plan_15d()
PLAN_5D = TradingRules.plan_5d()


def spec(balance=1_000_000, key="syn-001", policy=Policy.MODEL_ONLY, counts=True) -> PortfolioSpec:
    return PortfolioSpec(key, policy, "setup-01", balance, 0, counts)


_IDS: dict[str, int] = {}


def sid(symbol: str) -> int:
    """A stable synthetic security_id per test symbol: the ledger is keyed by id, symbols are for display."""
    return _IDS.setdefault(symbol, 1000 + len(_IDS))


def series(**by_symbol: list[Bar]) -> dict[int, dict[str, Bar]]:
    return {sid(sym): dict(zip(SESSIONS, rows, strict=False)) for sym, rows in by_symbol.items()}


def flat(price: float, n: int) -> list[Bar]:
    return [Bar(price, price, price, price) for _ in range(n)]


def buy_first(symbol: str = "AAA") -> dict[str, list[Candidate]]:
    return {SESSIONS[0]: [Candidate(sid(symbol), symbol, 0.9, f"sector-{symbol}")]}


# ------------------------------------------------------------------ the two rules, and their refusals


def test_the_two_built_in_rules_are_the_ones_the_task_names():
    assert (PLAN_15D.version, PLAN_15D.horizon_label) == (RULE_15D, "15D")
    assert (PLAN_15D.target, PLAN_15D.stop, PLAN_15D.half_out, PLAN_15D.horizon_sessions) == (
        0.08,
        0.04,
        0.05,
        15,
    )
    assert (PLAN_5D.version, PLAN_5D.horizon_label) == (RULE_5D, "5D")
    assert (PLAN_5D.target, PLAN_5D.stop, PLAN_5D.half_out, PLAN_5D.horizon_sessions) == (0.02, 0.04, None, 5)
    assert TradingRules.from_app() == PLAN_5D  # the default is the approved 5D paper rule
    assert TradingRules() == PLAN_5D


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"stop": 0.05},  # a wider stop
        {"target": 0.09},  # a higher target than the definition
        {"horizon_sessions": 16},
        {"half_out": 0.06},  # a later half-out
        {"half_out": None},  # the 15-day plan always has one
        {"drawdown_halt": 0.2},
        {"max_new_per_day": 6},
        {"risk_per_trade_pct": 0.02},
    ],
)
def test_the_15_day_plan_is_refused_if_looser(kwargs):
    with pytest.raises(RuleLoosened):
        replace(PLAN_15D, **kwargs)


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"stop": 0.05},
        {"target": 0.03},
        {"horizon_sessions": 6},
        {"half_out": 0.01},  # the 5-day rule has no half-out at all
        {"drawdown_halt": 0.2},
    ],
)
def test_the_5_day_rule_is_refused_if_looser(kwargs):
    with pytest.raises(RuleLoosened):
        replace(PLAN_5D, **kwargs)


def test_a_tighter_setting_is_allowed_and_10d_and_unknown_versions_are_out():
    assert replace(PLAN_5D, stop=0.03).stop == 0.03
    assert replace(PLAN_15D, horizon_sessions=10).horizon_sessions == 10  # shorter is tighter
    with pytest.raises(RuleLoosened):
        TradingRules(version="trade-10d-v1", horizon_label="10D")
    with pytest.raises(RuleLoosened):  # a version cannot be relabelled as another horizon
        replace(PLAN_5D, horizon_label="15D")


# ------------------------------------------------------------------ the same prices under both rules


def _staircase() -> dict[str, dict[str, Bar]]:
    """Entry at the open of session index 1 (fill about 100). Days 2, 3, 4 touch +3%, +6% and +9%."""
    return series(
        AAA=[
            Bar(100, 100, 100, 100),
            Bar(100, 100.2, 99.9, 100),
            Bar(100, 103.1, 99.9, 102),
            Bar(102, 106.2, 101.5, 105),
            Bar(105, 109.5, 104.5, 109),
            *flat(109.0, 12),
        ]
    )


def test_the_same_prices_give_different_exits_under_the_two_rules():
    bars = _staircase()
    fill = apply_slippage(100.0, "BUY")
    long_ledger = run_portfolio(spec(), SESSIONS[:8], bars, buy_first(), PLAN_15D)
    short_ledger = run_portfolio(spec(), SESSIONS[:8], bars, buy_first(), PLAN_5D)
    # 5-day rule: the +2% target is touched on session index 2; everything is sold there.
    (target,) = short_ledger.records[2].exits
    assert (target.reason, target.price) == ("target", pytest.approx(fill * 1.02))
    assert short_ledger.records[2].positions == ()
    # 15-day plan: nothing happens at +3%; half out at +5% on index 3; target at +8% on index 4.
    assert long_ledger.records[2].exits == ()
    (half,) = long_ledger.records[3].exits
    assert half.reason == "half_out" and half.price == pytest.approx(fill * 1.05)
    (target15,) = long_ledger.records[4].exits
    assert target15.reason == "target" and target15.price == pytest.approx(fill * 1.08)
    assert short_ledger.rule_version == RULE_5D and long_ledger.rule_version == RULE_15D


def test_the_5_day_rule_sells_at_the_close_of_session_5_and_the_15_day_plan_does_not():
    bars = series(AAA=flat(100.0, 12))
    short_ledger = run_portfolio(spec(), SESSIONS[:12], bars, buy_first(), PLAN_5D)
    bought = next(i for i, r in enumerate(short_ledger.records) if r.fills)
    exits = [(i, e) for i, r in enumerate(short_ledger.records) for e in r.exits]
    assert len(exits) == 1
    index, exit_ = exits[0]
    assert exit_.reason == "horizon" and index - bought + 1 == 5  # the entry day is session 1
    assert exit_.price == 100.0 and not short_ledger.records[index - 1].exits
    long_ledger = run_portfolio(spec(), SESSIONS[:12], bars, buy_first(), PLAN_15D)
    assert long_ledger.exit_count == 0 and long_ledger.records[index].positions


def test_the_5_day_stop_is_checked_before_the_target_like_the_lane():
    fill = apply_slippage(100.0, "BUY")
    both = [Bar(100, 100, 100, 100), Bar(100, 100, 100, 100), Bar(100, fill * 1.03, fill * 0.95, 100)]
    ledger = run_portfolio(spec(), SESSIONS[:4], series(AAA=both), buy_first(), PLAN_5D)
    (exit_,) = ledger.records[2].exits
    assert exit_.reason == "stop" and exit_.price == pytest.approx(fill * 0.96)


def test_the_5_day_rule_never_makes_a_half_out_exit():
    import random

    rng = random.Random(7)
    rows, last = [], 100.0
    for _ in range(25):
        o = last * (1 + rng.uniform(-0.02, 0.02))
        c = o * (1 + rng.uniform(-0.03, 0.03))
        rows.append(Bar(o, max(o, c) * 1.015, min(o, c) * 0.99, c))
        last = c
    decisions = {SESSIONS[d]: [Candidate(sid("AAA"), "AAA", 0.9, "s")] for d in range(24)}
    ledger = run_portfolio(spec(), SESSIONS[:25], series(AAA=rows), decisions, PLAN_5D)
    reasons = {e.reason for r in ledger.records for e in r.exits}
    assert ledger.exit_count > 0 and "half_out" not in reasons
    assert all(m.half_done is False for r in ledger.records for m in r.positions)


# ------------------------------------------------------------------ the version travels with every record


def test_every_record_and_every_ledger_says_which_rule_it_ran():
    bars = series(AAA=flat(100.0, 6))
    for rules in (PLAN_15D, PLAN_5D):
        busy = run_portfolio(spec(), SESSIONS[:6], bars, buy_first(), rules)
        quiet = run_portfolio(spec(), SESSIONS[:6], bars, {}, rules)
        assert busy.rule_version == quiet.rule_version == rules.version
        assert (
            {r.rule_version for r in busy.records}
            == {r.rule_version for r in quiet.records}
            == {rules.version}
        )
    empty = run_portfolio(replace(spec(), start_offset=10), SESSIONS[:6], bars, {}, PLAN_5D)
    assert empty.records == () and empty.rule_version == RULE_5D  # a ledger with no sessions still says


# ------------------------------------------------------------------ mixing versions is an error


def _cohort(rules: TradingRules):
    specs = list(build_matrix())[:6]
    bars = series(AAA=flat(100.0, 8))
    decisions = {p: buy_first() for p in Policy}
    return run_cohort(specs, SESSIONS[:8], bars, decisions, rules)


def test_one_rule_compares_fine_and_leaves_the_validation_portfolio_out():
    ledgers = _cohort(PLAN_5D)
    assert ledgers_rule_version(ledgers) == RULE_5D
    table = compare_by_policy(ledgers)
    assert set(table) == set(Policy) and all(row["portfolios"] == 2 for row in table.values())


def test_mixing_rule_versions_in_one_comparison_raises():
    short_ledgers, long_ledgers = _cohort(PLAN_5D), _cohort(PLAN_15D)
    keys = list(short_ledgers)
    mixed = {**short_ledgers, keys[0]: long_ledgers[keys[0]]}
    with pytest.raises(MixedRuleVersions):
        ledgers_rule_version(mixed)
    with pytest.raises(MixedRuleVersions):
        compare_by_policy(mixed)


def test_a_ledger_whose_records_disagree_with_its_own_version_is_also_caught():
    ledgers = _cohort(PLAN_5D)
    key = next(iter(ledgers))
    tampered = replace(
        ledgers[key], records=tuple(replace(r, rule_version=RULE_15D) for r in ledgers[key].records)
    )
    with pytest.raises(MixedRuleVersions):
        compare_by_policy({**ledgers, key: tampered})


def test_an_empty_comparison_raises_rather_than_guessing_a_rule():
    with pytest.raises(MixedRuleVersions):
        ledgers_rule_version({})


# ------------------------------------------------------------------ sizing is unchanged


@pytest.mark.parametrize("rules", [PLAN_15D, PLAN_5D], ids=["15D", "5D"])
@pytest.mark.parametrize("balance", [10_000, 25_000])
def test_the_two_smallest_balances_still_never_trade_under_either_rule(balance, rules):
    bars = series(AAA=flat(100.0, 8))
    decisions = {SESSIONS[d]: [Candidate(sid("AAA"), "AAA", 0.9, "s")] for d in range(7)}
    ledger = run_portfolio(spec(balance=balance), SESSIONS[:8], bars, decisions, rules)
    assert ledger.fill_count == 0 and ledger.exit_count == 0
    assert {b.reason for r in ledger.records for b in r.blocks} == {"below_minimum_position"}
    assert ledger.final_cash == balance


@pytest.mark.parametrize("rules", [PLAN_15D, PLAN_5D], ids=["15D", "5D"])
def test_the_larger_balances_size_trades_the_same_way_under_both_rules(rules):
    bars = series(AAA=flat(100.0, 4))
    ledger = run_portfolio(spec(balance=1_000_000), SESSIONS[:4], bars, buy_first(), rules)
    (fill,) = ledger.records[1].fills
    assert fill.qty == int(100_000 / fill.price)  # 1% risk at the 4% stop, capped by the ladder: unchanged
