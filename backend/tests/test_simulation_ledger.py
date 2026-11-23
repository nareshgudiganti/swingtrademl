"""#321 daily ledger engine on a small fixed price series: identical setups give identical results, the
app's rules are applied and never loosened, nothing looks ahead, and cash never goes negative. Pure."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from swing_trade_ml.services.costs import apply_slippage
from swing_trade_ml.simulation.cohorts import PortfolioSpec
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import (
    Bar,
    Candidate,
    _sell,
    run_cohort,
    run_portfolio,
)
from swing_trade_ml.simulation.rules import RuleLoosened, TradingRules

RULES = TradingRules.plan_15d()  # the 15-day research configuration: it has every exit this file exercises
SESSIONS = tuple(f"2026-12-{day:02d}" for day in range(1, 31))


def spec(balance=1_000_000, offset=0, key="syn-001", policy=Policy.MODEL_ONLY) -> PortfolioSpec:
    return PortfolioSpec(key, policy, "setup-01", balance, offset, True)


def flat(price: float, n: int) -> list[Bar]:
    return [Bar(price, price, price, price) for _ in range(n)]


def series(**by_symbol: list[Bar]) -> dict[str, dict[str, Bar]]:
    return {sym: dict(zip(SESSIONS, rows, strict=False)) for sym, rows in by_symbol.items()}


def buy_on_day(index: int, *cands: Candidate) -> dict[str, list[Candidate]]:
    """Picks decided at the close of session `index` (bought at the open of the next one)."""
    return {SESSIONS[index]: list(cands)}


def pick(symbol: str, score: float = 0.9, sector: str | None = None, block: str | None = None) -> Candidate:
    return Candidate(symbol, score, sector or f"sector-{symbol}", block)


# ------------------------------------------------------------------ the rules come from the app, never looser


def test_the_rules_come_from_the_research_config_and_match_the_replay_constants():
    from swing_trade_ml.brain.replay_scoring import HALF_OUT, HORIZON_BARS, STOP, TARGET

    rules = TradingRules.plan_15d()
    assert (rules.target, rules.stop, rules.half_out, rules.horizon_sessions) == (
        TARGET,
        STOP,
        HALF_OUT,
        HORIZON_BARS,
    )
    assert rules.drawdown_halt <= 0.15 and rules.max_new_per_day == 5 and rules == RULES
    assert TradingRules.from_app() == TradingRules.plan_5d()  # the default is the approved 5D paper rule


@pytest.mark.parametrize(
    "loose",
    [
        {"stop": 0.05},
        {"horizon_sessions": 20},
        {"drawdown_halt": 0.20},
        {"max_new_per_day": 6},
        {"risk_per_trade_pct": 0.02},
        {"half_out": 0.09},
    ],
)
def test_a_looser_rule_is_refused(loose):
    with pytest.raises(RuleLoosened):
        TradingRules(**loose)


def test_selling_costs_the_same_as_the_brain_replay_does():
    from swing_trade_ml.brain.replay_scoring import _sell as replay_sell

    for price, qty in ((100.0, 10), (2_500.5, 3), (12.34, 4_000)):
        assert _sell(price, qty) == pytest.approx(replay_sell(price, qty))


# ------------------------------------------------------------------ identical setups, identical results


def test_the_same_inputs_give_the_same_ledger_and_a_replica_matches_it():
    bars = series(AAA=[Bar(100, 101, 99, 100)] * 4 + [Bar(100, 109, 99, 108)] * 3)
    decisions = buy_on_day(0, pick("AAA"))
    first = run_portfolio(spec(), SESSIONS[:7], bars, decisions, RULES)
    again = run_portfolio(spec(), SESSIONS[:7], bars, decisions, RULES)
    replica = run_portfolio(spec(key="syn-002"), SESSIONS[:7], bars, decisions, RULES)
    assert first.records == again.records
    assert first.records == replica.records  # a replica with identical inputs and policy matches


def test_identical_setups_on_different_policies_differ_only_by_their_picks():
    bars = series(AAA=flat(100.0, 5), BBB=flat(50.0, 5))
    by_policy = {
        Policy.MOMENTUM: buy_on_day(0, pick("AAA")),
        Policy.MODEL_ONLY: buy_on_day(0, pick("AAA")),
        Policy.BRAIN_FILTERED: buy_on_day(0, pick("AAA", block="risk check")),
    }
    specs = [spec(key=f"syn-00{i}", policy=p) for i, p in enumerate(Policy, start=1)]
    ledgers = run_cohort(specs, SESSIONS[:5], bars, by_policy, RULES)
    momentum, model_only, brain = (ledgers[s.persona_key] for s in specs)
    assert momentum.records == model_only.records  # same capital, offset, picks: identical
    assert brain.fill_count == 0 and brain.records[1].blocks[0].reason == "held_back: risk check"


# ------------------------------------------------------------------ the app's rules are applied


def test_a_pick_is_bought_at_the_next_open_with_slippage_and_charges_and_cash_drops_by_its_cost():
    bars = series(AAA=[Bar(100, 100, 100, 100), Bar(102, 103, 101, 102), *flat(102.0, 3)])
    ledger = run_portfolio(spec(), SESSIONS[:5], bars, buy_on_day(0, pick("AAA")), RULES)
    assert ledger.records[0].fills == ()  # decided at the close of day 0: nothing bought on day 0
    (fill,) = ledger.records[1].fills
    assert fill.price == pytest.approx(apply_slippage(102.0, "BUY"))
    assert ledger.records[1].cash == pytest.approx(1_000_000 - fill.cost)
    assert fill.qty == int(100_000 / fill.price)  # 1% risk at the 4% stop = 25%, capped by the ladder's 10%


def test_the_stop_exits_at_the_stop_level_and_at_the_open_on_a_gap_down():
    fill = apply_slippage(100.0, "BUY")
    stop = fill * 0.96
    bars = series(AAA=[Bar(100, 100, 100, 100), Bar(100, 100, 100, 100), Bar(99, 99.5, stop - 0.5, 97)])
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, buy_on_day(0, pick("AAA")), RULES)
    (exit_,) = ledger.records[2].exits
    assert (exit_.reason, exit_.price) == ("stop", pytest.approx(stop))
    assert ledger.records[2].positions == ()
    gap = series(AAA=[Bar(100, 100, 100, 100), Bar(100, 100, 100, 100), Bar(90, 91, 89, 90)])
    (gap_exit,) = run_portfolio(spec(), SESSIONS[:4], gap, buy_on_day(0, pick("AAA")), RULES).records[2].exits
    assert (gap_exit.reason, gap_exit.price) == ("stop", 90)


def test_half_out_at_5_percent_then_target_at_8_percent():
    fill = apply_slippage(100.0, "BUY")
    bars = series(
        AAA=[
            Bar(100, 100, 100, 100),
            Bar(100, 100, 100, 100),
            Bar(101, fill * 1.06, 100, 104),  # touches +5% only
            Bar(104, fill * 1.09, 103, 108),  # touches +8%
        ]
    )
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, buy_on_day(0, pick("AAA")), RULES)
    qty = ledger.records[1].fills[0].qty
    (half,) = ledger.records[2].exits
    assert (half.reason, half.qty, half.price) == ("half_out", qty // 2, pytest.approx(fill * 1.05))
    assert ledger.records[2].positions[0].qty == qty - qty // 2 and ledger.records[2].positions[0].half_done
    (target,) = ledger.records[3].exits
    assert (target.reason, target.qty) == ("target", qty - qty // 2)
    assert target.price == pytest.approx(fill * 1.08)
    assert ledger.records[3].positions == ()


def test_a_position_that_goes_nowhere_is_sold_at_the_close_of_the_15th_session():
    bars = series(AAA=flat(100.0, 20))
    ledger = run_portfolio(spec(), SESSIONS[:20], bars, buy_on_day(0, pick("AAA")), RULES)
    bought = next(i for i, r in enumerate(ledger.records) if r.fills)
    exits = [(i, e) for i, r in enumerate(ledger.records) for e in r.exits]
    assert len(exits) == 1
    index, exit_ = exits[0]
    assert exit_.reason == "horizon" and index - bought + 1 == 15


def test_the_sector_cap_holds_at_25_percent_of_the_account():
    bars = series(AAA=flat(100.0, 4), BBB=flat(100.0, 4), CCC=flat(100.0, 4), DDD=flat(100.0, 4))
    same = [
        pick(s, score, sector="IT") for s, score in (("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7), ("DDD", 0.6))
    ]
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, buy_on_day(0, *same), RULES)
    last = ledger.records[-1]
    assert sum(m.value for m in last.positions) <= 0.25 * last.equity + 1.0
    assert ledger.records[1].blocks or len(ledger.records[1].fills) < 4  # the cap stopped at least one buy


def test_a_small_account_holds_one_stock_per_sector():
    bars = series(AAA=flat(100.0, 4), BBB=flat(100.0, 4))
    ledger = run_portfolio(
        spec(balance=50_000),
        SESSIONS[:4],
        bars,
        buy_on_day(0, pick("AAA", 0.9, "IT"), pick("BBB", 0.8, "IT")),
        RULES,
    )
    assert [f.symbol for f in ledger.records[1].fills] == ["AAA"]
    assert [(b.symbol, b.reason) for b in ledger.records[1].blocks] == [("BBB", "sector_cap")]


def test_the_ladders_share_price_ceiling_applies_to_the_small_rungs():
    bars = series(DEAR=flat(3_000.0, 3))
    ledger = run_portfolio(spec(balance=50_000), SESSIONS[:3], bars, buy_on_day(0, pick("DEAR")), RULES)
    assert ledger.fill_count == 0 and ledger.records[1].blocks[0].reason == "price_above_ladder_limit"


@pytest.mark.parametrize("balance", [10_000, 25_000])
def test_the_two_smallest_balances_cannot_reach_their_minimum_position_under_the_settled_sizing(balance):
    """FINDING, pinned as it behaves: 1% risk at the 4% stop sizes a trade at 25% of the account, below the
    ladder's own minimum position at Rs 10K (2,500 < 4,000) and Rs 25K (6,250 < about 8,377). These portfolios
    never trade under this sizing: 2 of the 11 balances, so 18 of the 99 portfolios would show zero trades."""
    bars = series(AAA=flat(100.0, 3))
    ledger = run_portfolio(spec(balance=balance), SESSIONS[:3], bars, buy_on_day(0, pick("AAA")), RULES)
    assert ledger.fill_count == 0 and ledger.records[1].blocks[0].reason == "below_minimum_position"


def test_the_daily_buy_cap_and_a_held_back_pick_are_recorded_as_blocks():
    names = [f"S{i}" for i in range(7)]
    bars = series(**{n: flat(100.0, 3) for n in names})
    cands = [pick(n, 0.9 - i * 0.01) for i, n in enumerate(names[:6])] + [pick("S6", 0.5, block="stale data")]
    ledger = run_portfolio(spec(), SESSIONS[:3], bars, buy_on_day(0, *cands), RULES)
    day = ledger.records[1]
    assert len(day.fills) == 5
    reasons = {b.symbol: b.reason for b in day.blocks}
    assert reasons == {"S5": "over_daily_limit", "S6": "held_back: stale data"}


def test_a_pick_with_no_price_that_day_is_blocked_and_a_held_stock_without_a_bar_is_marked_stale():
    bars = series(AAA=[Bar(100, 100, 100, 100)] * 4)
    bars["AAA"].pop(SESSIONS[2])  # no bar on day 2
    ledger = run_portfolio(
        spec(), SESSIONS[:4], bars, {**buy_on_day(0, pick("AAA")), **buy_on_day(1, pick("ZZZ"))}, RULES
    )
    assert ledger.records[2].blocks[0].reason == "no_price"
    assert ledger.records[2].positions[0].stale and ledger.records[2].positions[0].mark == 100


def test_the_drawdown_halt_stops_new_buys_after_a_15_percent_fall_and_never_sells():
    names = [f"G{i}" for i in range(5)]
    crash = [Bar(100, 100, 100, 100), Bar(100, 100, 100, 100), Bar(65, 66, 64, 65), *flat(65.0, 3)]
    bars = series(**dict.fromkeys(names, crash), NEW=flat(100.0, 6))
    ledger = run_portfolio(
        spec(), SESSIONS[:6], bars, {**buy_on_day(0, *map(pick, names)), **buy_on_day(2, pick("NEW"))}, RULES
    )
    assert len(ledger.records[1].fills) == 5
    assert ledger.records[2].equity < 0.85 * 1_000_000  # five 10% positions each fell by more than a third
    day3 = ledger.records[3]
    assert day3.halted and day3.fills == () and [b.reason for b in day3.blocks] == ["drawdown_halt"]


# ------------------------------------------------------------------ zero trades and overlapping stocks


def test_zero_trades_are_fine_and_cash_stays_whole():
    ledger = run_portfolio(spec(), SESSIONS[:6], series(AAA=flat(100.0, 6)), {}, RULES)
    assert ledger.fill_count == ledger.exit_count == ledger.block_count == 0
    assert all(r.cash == 1_000_000 and r.equity == 1_000_000 and r.positions == () for r in ledger.records)


def test_two_portfolios_may_hold_the_same_stock_each_in_its_own_account():
    bars = series(AAA=flat(100.0, 4))
    specs = [
        spec(key="syn-001", policy=Policy.MOMENTUM),
        spec(key="syn-002", policy=Policy.MODEL_ONLY, balance=500_000),
    ]
    decisions = {Policy.MOMENTUM: buy_on_day(0, pick("AAA")), Policy.MODEL_ONLY: buy_on_day(0, pick("AAA"))}
    ledgers = run_cohort(specs, SESSIONS[:4], bars, decisions, RULES)
    assert all(ledgers[s.persona_key].records[1].fills[0].symbol == "AAA" for s in specs)
    assert ledgers["syn-001"].records[1].fills[0].qty != ledgers["syn-002"].records[1].fills[0].qty


def test_a_start_offset_delays_the_first_session():
    bars = series(AAA=flat(100.0, 8))
    decisions = {SESSIONS[i]: [pick("AAA")] for i in range(8)}
    on_time = run_portfolio(spec(offset=0), SESSIONS[:8], bars, decisions, RULES)
    late = run_portfolio(spec(offset=4), SESSIONS[:8], bars, decisions, RULES)
    assert on_time.records[0].session == SESSIONS[0] and late.records[0].session == SESSIONS[4]
    assert (
        len(late.records) == 4 and late.records[0].fills == ()
    )  # no pick was decided before its first session


# ------------------------------------------------------------------ no look-ahead


def _wiggle(seed: int, n: int, base: float) -> list[Bar]:
    rng = random.Random(seed)
    out, last = [], base
    for _ in range(n):
        o = last * (1 + rng.uniform(-0.03, 0.03))
        c = o * (1 + rng.uniform(-0.04, 0.04))
        out.append(Bar(o, max(o, c) * 1.01, min(o, c) * 0.99, c))
        last = c
    return out


def _random_world(seed: int, n=25):
    names = [f"R{i}" for i in range(8)]
    bars = series(**{name: _wiggle(seed * 31 + i, n, 50 + 40 * i) for i, name in enumerate(names)})
    rng = random.Random(seed)
    decisions = {
        SESSIONS[d]: [pick(s, rng.random(), sector=f"sec{rng.randrange(4)}") for s in rng.sample(names, 4)]
        for d in range(n - 1)
    }
    return bars, decisions


def test_a_pick_is_never_bought_before_the_open_of_the_session_after_it_was_decided():
    bars, decisions = _random_world(1)
    ledger = run_portfolio(spec(), SESSIONS[:25], bars, decisions, RULES)
    for i, record in enumerate(ledger.records):
        previous = decisions.get(SESSIONS[i - 1], []) if i else []
        decided = {c.symbol for c in previous}
        for fill in record.fills:
            assert fill.symbol in decided, (record.session, fill.symbol)
            assert fill.price == pytest.approx(apply_slippage(bars[fill.symbol][record.session].open, "BUY"))


def test_the_record_of_a_session_never_depends_on_later_prices_or_later_picks():
    bars, decisions = _random_world(2)
    full = run_portfolio(spec(), SESSIONS[:25], bars, decisions, RULES)
    k = 12
    poisoned = {
        s: {d: (b if SESSIONS.index(d) <= k else Bar(1.0, 9_999.0, 0.01, 5_000.0)) for d, b in m.items()}
        for s, m in bars.items()
    }
    later_picks = {d: ([pick("R0", 9.9)] if SESSIONS.index(d) > k else c) for d, c in decisions.items()}
    other = run_portfolio(spec(), SESSIONS[:25], poisoned, later_picks, RULES)
    assert other.records[: k + 1] == full.records[: k + 1]
    cut = run_portfolio(spec(), SESSIONS[: k + 1], bars, decisions, RULES)  # the world ends at session k
    assert cut.records == full.records[: k + 1]


# ------------------------------------------------------------------ cash never goes negative


@pytest.mark.parametrize("seed", range(30))
def test_cash_never_goes_negative_and_equity_is_cash_plus_marks(seed):
    bars, decisions = _random_world(seed)
    for balance in (10_000, 100_000, 1_000_000):
        ledger = run_portfolio(spec(balance=balance), SESSIONS[:25], bars, decisions, RULES)
        for record in ledger.records:
            assert record.cash >= -1e-6, (seed, balance, record.session)
            assert record.equity == pytest.approx(record.cash + sum(m.value for m in record.positions))
            assert all(m.qty > 0 for m in record.positions)


def test_two_buys_on_one_morning_cannot_spend_the_same_rupee():
    bars = series(AAA=flat(100.0, 3), BBB=flat(100.0, 3), CCC=flat(100.0, 3))
    tight = spec(balance=120_000)  # the 100k rung floor leaves little to spend
    ledger = run_portfolio(
        tight, SESSIONS[:3], bars, buy_on_day(0, pick("AAA"), pick("BBB"), pick("CCC")), RULES
    )
    spent = sum(f.cost for f in ledger.records[1].fills)
    assert (
        spent <= 120_000
        and ledger.records[1].cash == pytest.approx(120_000 - spent)
        and ledger.records[1].cash >= 0
    )


def test_a_pick_too_dear_for_the_account_is_blocked_not_bought():
    bars = series(AAA=flat(9_000.0, 3))
    ledger = run_portfolio(spec(balance=10_000), SESSIONS[:3], bars, buy_on_day(0, pick("AAA")), RULES)
    assert ledger.fill_count == 0 and ledger.records[1].blocks[0].reason == "price_above_ladder_limit"


def test_the_rules_object_is_what_the_engine_obeys():
    tighter = replace(RULES, stop=0.02)
    bars = series(AAA=[Bar(100, 100, 100, 100), Bar(100, 100, 100, 100), Bar(100, 100, 97.5, 98)])
    exits = run_portfolio(spec(), SESSIONS[:3], bars, buy_on_day(0, pick("AAA")), tighter).records[2].exits
    assert [e.reason for e in exits] == ["stop"]
    assert run_portfolio(spec(), SESSIONS[:3], bars, buy_on_day(0, pick("AAA")), RULES).records[2].exits == ()
