"""#321 the app's entry rules in the ledger: market mode, the stop-loss cooldown, liquidity, cap tier,
the avoid list (applied when their input is given, listed as not applied when not), the stale-exit rule, and
the owner decision that zero-trade accounts are kept with every blocked pick and its reason. Pure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from swing_trade_ml.simulation.cohorts import PortfolioSpec
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import (
    Bar,
    Candidate,
    LedgerInputError,
    compare_by_policy,
    run_cohort,
    run_portfolio,
)
from swing_trade_ml.simulation.rules import ALWAYS_NOT_APPLIED, OPTIONAL_INPUTS, RuleLoosened, TradingRules

RULES = TradingRules.plan_15d()
SHORT = TradingRules.plan_5d()
SESSIONS = tuple(f"2026-12-{day:02d}" for day in range(1, 31))


def spec(balance=1_000_000, key="syn-001", policy=Policy.MODEL_ONLY) -> PortfolioSpec:
    return PortfolioSpec(key, policy, "setup-01", balance, 0, True)


def flat(price: float, n: int) -> list[Bar]:
    return [Bar(price, price, price, price) for _ in range(n)]


def series(**by_symbol: list[Bar]) -> dict[str, dict[str, Bar]]:
    return {sym: dict(zip(SESSIONS, rows, strict=False)) for sym, rows in by_symbol.items()}


def pick(symbol: str, score: float = 0.9, block: str | None = None) -> Candidate:
    return Candidate(symbol, score, f"sector-{symbol}", block)


def on(index: int, *cands: Candidate) -> dict[str, list[Candidate]]:
    return {SESSIONS[index]: list(cands)}


def names(n: int) -> list[str]:
    return [f"S{i}" for i in range(n)]


# ------------------------------------------------------------------ market mode


def test_no_new_trades_buys_nothing_and_records_every_pick_with_its_reason():
    bars = series(**{n: flat(100.0, 4) for n in names(3)})
    modes = {SESSIONS[0]: "NO_NEW_TRADES"}
    cands = [pick("S0"), pick("S1"), pick("S2", block="risk check")]
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, on(0, *cands), RULES, market_modes=modes)
    day = ledger.records[1]
    assert day.fills == () and day.market_mode == "NO_NEW_TRADES"
    assert {b.symbol: b.reason for b in day.blocks} == {
        "S0": "no_new_trades",
        "S1": "no_new_trades",
        "S2": "held_back: risk check",
    }
    assert ledger.fill_count == 0 and all(r.cash == 1_000_000 for r in ledger.records)


def test_defensive_halves_the_size_and_allows_two_buys_a_day():
    bars = series(**{n: flat(100.0, 4) for n in names(4)})
    cands = [pick(n, 0.9 - i * 0.01) for i, n in enumerate(names(4))]
    normal = run_portfolio(
        spec(), SESSIONS[:4], bars, on(0, *cands), RULES, market_modes={SESSIONS[0]: "NORMAL"}
    )
    defensive = run_portfolio(
        spec(), SESSIONS[:4], bars, on(0, *cands), RULES, market_modes={SESSIONS[0]: "DEFENSIVE"}
    )
    n_fill, d_fill = normal.records[1].fills[0], defensive.records[1].fills[0]
    assert d_fill.qty == int(0.5 * 100_000 / d_fill.price)  # half of the 100,000 the 1M rung would take
    assert n_fill.qty == int(100_000 / n_fill.price)
    assert len(normal.records[1].fills) == 4 and len(defensive.records[1].fills) == 2
    assert {b.reason for b in defensive.records[1].blocks} == {"market_mode_limit"}


def test_an_unknown_mode_or_a_session_missing_from_the_modes_counts_as_no_new_trades():
    bars = series(AAA=flat(100.0, 4))
    for modes in ({SESSIONS[0]: "SOMETHING_NEW"}, {SESSIONS[2]: "NORMAL"}):
        ledger = run_portfolio(spec(), SESSIONS[:4], bars, on(0, pick("AAA")), RULES, market_modes=modes)
        assert ledger.fill_count == 0 and ledger.records[1].blocks[0].reason == "no_new_trades"


def test_without_market_modes_every_session_is_normal_and_that_is_listed_as_not_applied():
    bars = series(AAA=flat(100.0, 4))
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, on(0, pick("AAA")), RULES)
    assert ledger.fill_count == 1 and ledger.records[1].market_mode == ""
    assert OPTIONAL_INPUTS["market_modes"] in ledger.not_applied


# ------------------------------------------------------------------ the stop-loss cooldown


def _stopped_then_again() -> dict[str, dict[str, Bar]]:
    drop = Bar(100, 100, 94, 95)  # pierces the 4% stop on session index 2 (3 Dec)
    return series(AAA=[*flat(100.0, 2), drop, *flat(100.0, 12)])


def test_a_stopped_stock_picked_again_the_next_day_is_refused_during_the_cooldown():
    ledger = run_portfolio(
        spec(), SESSIONS[:6], _stopped_then_again(), {**on(0, pick("AAA")), **on(2, pick("AAA"))}, RULES
    )
    assert [e.reason for e in ledger.records[2].exits] == ["stop"]
    assert ledger.records[3].fills == () and ledger.records[3].blocks[0].reason == "stop_cooldown"


def test_the_cooldown_ends_after_the_apps_five_calendar_days():
    bars = _stopped_then_again()
    inside = run_portfolio(spec(), SESSIONS[:10], bars, {**on(0, pick("AAA")), **on(6, pick("AAA"))}, RULES)
    assert inside.records[7].blocks[0].reason == "stop_cooldown"  # 8 Dec is 5 days after the 3 Dec stop
    outside = run_portfolio(spec(), SESSIONS[:10], bars, {**on(0, pick("AAA")), **on(7, pick("AAA"))}, RULES)
    assert [f.symbol for f in outside.records[8].fills] == ["AAA"]  # 9 Dec is 6 days after


def test_only_a_stop_starts_the_cooldown_and_a_shorter_cooldown_is_refused():
    win = [*flat(100.0, 2), Bar(100, 110, 100, 109), *flat(109.0, 6)]
    ledger = run_portfolio(
        spec(), SESSIONS[:7], series(AAA=win), {**on(0, pick("AAA")), **on(2, pick("AAA"))}, RULES
    )
    assert ledger.records[2].exits[-1].reason == "target"
    assert [f.symbol for f in ledger.records[3].fills] == ["AAA"]  # a target is not a stop
    with pytest.raises(RuleLoosened):
        replace(RULES, stop_cooldown_days=4)
    assert TradingRules.from_app().stop_cooldown_days >= 5


def test_sessions_that_are_not_iso_dates_are_refused():
    with pytest.raises(LedgerInputError):
        run_portfolio(spec(), ("day-1", "day-2"), {}, {}, RULES)


# ------------------------------------------------------------------ liquidity, cap tier, avoid list


def test_liquidity_caps_the_position_and_blocks_a_thin_stock_and_an_unknown_one():
    bars = series(THIN=flat(100.0, 3), MID=flat(100.0, 3), DEEP=flat(100.0, 3), BLANK=flat(100.0, 3))
    adv = {
        "THIN": {SESSIONS[0]: 1_000_000.0},  # 2% of 1M = 20,000, below the minimum position
        "MID": {SESSIONS[0]: 3_000_000.0},  # 2% = 60,000: the position is cut to that
        "DEEP": {SESSIONS[0]: 50_000_000.0},  # plenty: the normal 100,000
    }
    picks = [pick("THIN", 0.9), pick("MID", 0.8), pick("DEEP", 0.7), pick("BLANK", 0.6)]
    ledger = run_portfolio(spec(balance=1_200_000), SESSIONS[:3], bars, on(0, *picks), RULES, liquidity=adv)
    day = ledger.records[1]
    bought = {f.symbol: f for f in day.fills}
    assert bought["MID"].price * bought["MID"].qty <= 60_000
    assert bought["DEEP"].price * bought["DEEP"].qty > 90_000
    assert {b.symbol: b.reason for b in day.blocks} == {"THIN": "liquidity", "BLANK": "liquidity_unknown"}
    assert OPTIONAL_INPUTS["liquidity"] not in ledger.not_applied


def test_cap_tier_blocks_a_tier_the_rung_does_not_allow_and_an_unknown_tier():
    bars = series(BIG=flat(100.0, 3), MIDCO=flat(100.0, 3), TINY=flat(100.0, 3), NOIDEA=flat(100.0, 3))
    tiers = {"BIG": "large", "MIDCO": "midcap", "TINY": "smallcap"}
    picks = [pick("BIG", 0.9), pick("MIDCO", 0.8), pick("TINY", 0.7), pick("NOIDEA", 0.6)]
    ledger = run_portfolio(spec(balance=120_000), SESSIONS[:3], bars, on(0, *picks), RULES, cap_tiers=tiers)
    day = ledger.records[1]
    assert {f.symbol for f in day.fills} == {"BIG", "MIDCO"}  # about Rs 1.2L: large and mid
    assert {b.symbol: b.reason for b in day.blocks} == {"TINY": "cap_tier", "NOIDEA": "cap_tier_unknown"}


def test_the_small_company_budget_stops_the_third_small_position_on_the_ten_lakh_rung():
    bars = series(**{n: flat(100.0, 3) for n in names(3)})
    tiers = dict.fromkeys(names(3), "smallcap")
    picks = [pick(n, 0.9 - i * 0.1) for i, n in enumerate(names(3))]
    ledger = run_portfolio(spec(balance=1_200_000), SESSIONS[:3], bars, on(0, *picks), RULES, cap_tiers=tiers)
    assert len(ledger.records[1].fills) == 2  # 20% of the account in small companies = two 10% positions
    assert [b.reason for b in ledger.records[1].blocks] == ["cap_tier"]


def test_the_avoid_list_blocks_a_stock_with_its_plain_reason():
    bars = series(AAA=flat(100.0, 3), BBB=flat(100.0, 3))
    avoid = {SESSIONS[0]: {"AAA": "results due in 2 days"}}
    ledger = run_portfolio(
        spec(), SESSIONS[:3], bars, on(0, pick("AAA"), pick("BBB", 0.5)), RULES, avoid=avoid
    )
    assert [f.symbol for f in ledger.records[1].fills] == ["BBB"]
    assert ledger.records[1].blocks[0].reason == "avoid: results due in 2 days"


def test_every_ledger_lists_what_it_did_not_apply_and_a_full_set_of_inputs_leaves_only_the_permanent_ones():
    bare = run_portfolio(spec(), SESSIONS[:3], series(AAA=flat(100.0, 3)), {}, RULES)
    assert set(ALWAYS_NOT_APPLIED) <= set(bare.not_applied)
    assert all(text in bare.not_applied for text in OPTIONAL_INPUTS.values())
    full = run_portfolio(
        spec(),
        SESSIONS[:3],
        series(AAA=flat(100.0, 3)),
        {},
        RULES,
        market_modes={},
        liquidity={},
        cap_tiers={},
        avoid={},
    )
    assert full.not_applied == ALWAYS_NOT_APPLIED


# ------------------------------------------------------------------ a stock with no bar for its whole window


def test_a_held_stock_with_no_bar_for_its_whole_window_is_sold_at_the_last_close_flagged_stale():
    bars = series(AAA=[*flat(100.0, 3)])  # bars for 1, 2 and 3 Dec only
    ledger = run_portfolio(spec(), SESSIONS[:10], bars, on(0, pick("AAA")), SHORT)  # a 5-session window
    held = [(i, r) for i, r in enumerate(ledger.records) if r.positions]
    assert held and all(
        any(m.stale for m in r.positions) for i, r in held if i >= 3
    )  # marked stale, not evaluated
    exits = [(i, e) for i, r in enumerate(ledger.records) for e in r.exits]
    assert len(exits) == 1
    index, exit_ = exits[0]
    assert (
        exit_.stale and exit_.reason == "horizon" and exit_.price == 100.0
    )  # the last known close, no invented price
    assert (
        index == 5 and ledger.records[-1].positions == ()
    )  # entry day 1 + 5 sessions: gone, not open forever


def test_a_stock_with_bars_is_never_flagged_stale():
    bars = series(AAA=flat(100.0, 8))
    ledger = run_portfolio(spec(), SESSIONS[:8], bars, on(0, pick("AAA")), SHORT)
    assert not any(e.stale for r in ledger.records for e in r.exits)


# ------------------------------------------------------------------ OWNER DECISION: zero-trade accounts kept


def test_a_10k_account_shows_zero_trades_every_pick_blocked_with_its_reason_and_equity_equal_to_cash():
    bars = series(AAA=flat(100.0, 8), BBB=flat(100.0, 8))
    decisions = {SESSIONS[d]: [pick("AAA", 0.9), pick("BBB", 0.8)] for d in range(7)}
    ledger = run_portfolio(spec(balance=10_000), SESSIONS[:8], bars, decisions, RULES)
    assert len(ledger.records) == 8  # a record for every session, even though nothing happened
    assert ledger.fill_count == 0 and ledger.exit_count == 0
    for record in ledger.records:
        assert record.positions == () and record.cash == 10_000 and record.equity == record.cash
    reasons = {(b.symbol, b.reason) for r in ledger.records for b in r.blocks}
    assert reasons == {("AAA", "below_minimum_position"), ("BBB", "below_minimum_position")}
    assert ledger.block_count == 7 * 2  # all 14 picks, none dropped, none substituted
    assert ledger.final_equity == 10_000


def test_zero_trade_accounts_are_counted_in_every_comparison_at_their_own_zero_return():
    bars = series(AAA=flat(100.0, 8))
    decisions = {p: {SESSIONS[d]: [pick("AAA")] for d in range(7)} for p in Policy}
    small = [
        PortfolioSpec(f"syn-0{i}", p, "setup-01", 10_000, 0, True) for i, p in enumerate(Policy, start=1)
    ]
    large = [
        PortfolioSpec(f"syn-1{i}", p, "setup-02", 1_000_000, 0, True) for i, p in enumerate(Policy, start=1)
    ]
    ledgers = run_cohort(small + large, SESSIONS[:8], bars, decisions, RULES)
    table = compare_by_policy(ledgers)
    for row in table.values():
        assert row["portfolios"] == 2 and row["zero_trade_portfolios"] == 1  # the Rs 10K one, still counted
        assert row["blocked"] > 0


def test_a_rejected_pick_is_never_replaced_by_another():
    bars = series(AAA=flat(100.0, 4), BBB=flat(100.0, 4))
    ledger = run_portfolio(spec(), SESSIONS[:4], bars, on(0, pick("AAA", 0.9, block="risk check")), RULES)
    assert ledger.fill_count == 0 and ledger.records[1].blocks[0].reason == "held_back: risk check"
