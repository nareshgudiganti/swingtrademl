# backend/tests/test_brain_portfolio_sim.py
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from swing_trade_ml.brain.portfolio_sim import Pick, random_baseline, simulate

START = date(2026, 1, 5)
DAYS = [START + timedelta(days=i) for i in range(30)]  # day numbers only; weekends do not matter here


def flat(price=100.0, n=30, overrides=None):
    rows = []
    for i in range(n):
        o = h = lo = c = price
        if overrides and i in overrides:
            o, h, lo, c = overrides[i]
        rows.append({"day": DAYS[i], "open": o, "high": h, "low": lo, "close": c})
    return pd.DataFrame(rows)


def run(picks, bars, capital=500_000, modes=None):
    return simulate(picks, bars, DAYS, capital=capital, modes=modes)


def test_a_flat_stock_only_costs_money():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()})
    assert r.trades == 1 and r.still_open == 0
    assert -0.01 < r.total_return < 0  # costs and slippage only, on one position
    assert r.avg_trade_return < 0


def test_a_target_hit_makes_money_and_a_stop_loses():
    up = flat(overrides={3: (100, 109, 100, 108)})
    down = flat(overrides={3: (100, 100, 94, 95)})
    assert run([Pick(DAYS[0], "A", 0.9)], {"A": up}).total_return > 0.005
    lost = run([Pick(DAYS[0], "A", 0.9)], {"A": down})
    assert lost.total_return < -0.003 and lost.max_drawdown > 0.003


def test_no_new_trades_buys_nothing_and_defensive_buys_two():
    bars = {s: flat() for s in "ABCD"}
    picks = [Pick(DAYS[0], s, 1 - i / 10) for i, s in enumerate("ABCD")]
    none = run(picks, bars, modes={DAYS[0]: "NO_NEW_TRADES"})
    assert none.trades == 0 and none.total_return == 0
    two = run(picks, bars, modes={DAYS[0]: "DEFENSIVE"})
    assert two.trades == 2 and two.skipped["market_mode_limit"] == 2


def test_the_strongest_picks_get_the_free_slots():
    bars = {s: flat() for s in "ABCDE"}
    picks = [Pick(DAYS[0], s, sc) for s, sc in zip("ABCDE", (0.1, 0.9, 0.5, 0.8, 0.7), strict=True)]
    r = run(picks, bars, capital=100_000)  # the Rs 1 lakh rung: four positions
    assert r.trades == 4 and r.skipped.get("no_free_slot") == 1


def test_a_tiny_account_cannot_size_a_position_above_the_minimum():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()}, capital=10_000)
    assert r.trades == 0 and r.skipped["too_small_or_no_cash"] == 1


def test_a_stock_already_held_is_not_bought_twice():
    r = run([Pick(DAYS[0], "A", 0.9), Pick(DAYS[1], "A", 0.9)], {"A": flat()})
    assert r.trades == 1 and r.skipped["already_held"] == 1


def test_a_position_times_out_after_fifteen_bars():
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": flat()})
    assert r.trades == 1
    short = simulate([Pick(DAYS[0], "A", 0.9)], {"A": flat()}, DAYS[:8], capital=500_000)
    assert short.trades == 0 and short.still_open == 1


def test_a_deep_loss_halts_new_buys():
    gap = dict.fromkeys(range(2, 30), (70, 70, 70, 70))  # gaps down 30% and stays there
    bars = {s: flat(overrides=gap) for s in "ABCD"}
    bars["F"] = flat()
    picks = [Pick(DAYS[0], s, 1.0) for s in "ABCD"] + [Pick(DAYS[5], "F", 1.0)]
    r = run(picks, bars, capital=100_000)
    assert r.max_drawdown > 0.15 and r.halted_days > 0
    assert r.skipped["drawdown_halt"] == 1


def test_random_baseline_is_repeatable():
    bars = {s: flat() for s in "ABC"}
    pool = {DAYS[0]: list("ABC"), DAYS[1]: list("ABC")}
    a = random_baseline(pool, {DAYS[0]: 1, DAYS[1]: 1}, bars, DAYS, {}, capital=500_000, draws=5)
    b = random_baseline(pool, {DAYS[0]: 1, DAYS[1]: 1}, bars, DAYS, {}, capital=500_000, draws=5)
    assert a == b and a["return_p5"] <= a["return_p95"]


def _slide():
    """Two stocks gap down 35% on day 2 (stopped out at the open); two stay flat and stay held."""
    gap = dict.fromkeys(range(2, 30), (65, 65, 65, 65))
    return {"A": flat(overrides=gap), "B": flat(overrides=gap), "C": flat(), "D": flat()}


def test_half_out_proceeds_count_as_cash_straight_away():
    up = flat(overrides={2: (100, 106, 100, 105)})  # touches +5% (half out) but not +8%
    r = run([Pick(DAYS[0], "A", 0.9)], {"A": up})
    day2 = dict(r.curve)[DAYS[2]]
    assert day2 > 500_000 * 0.995  # equity must not drop when half is sold


def test_selling_all_at_a_fall_ends_with_no_positions_and_records_the_cost():
    picks = [Pick(DAYS[0], s, 1.0) for s in "ABCD"]
    r = simulate(picks, _slide(), DAYS, capital=100_000, drawdown_policy="liquidate")
    assert r.forced_exits >= 1 and r.forced_shortfall > 0 and r.triggers >= 1


def test_selling_half_keeps_some_exposure_and_the_default_keeps_all():
    picks = [Pick(DAYS[0], s, 1.0) for s in "ABCD"]
    halve = simulate(picks, _slide(), DAYS, capital=100_000, drawdown_policy="reduce")
    keep = simulate(picks, _slide(), DAYS, capital=100_000, drawdown_policy="halt")
    assert halve.forced_exits >= 1 and keep.forced_exits == 0
    assert halve.forced_exits == 2  # the two flat stocks are the ones still open


# --- tv6: the rules-only arm (layer 2 protocol section 3): same account rules, random eligible picks ----

import pytest  # noqa: E402

from swing_trade_ml.brain import portfolio_sim as ps  # noqa: E402


def _eligible(days, syms):
    return {d: list(syms) for d in days}


def test_rules_only_picks_come_only_from_the_eligible_stocks_and_match_the_count():
    eligible = {DAYS[0]: ["A", "B", "C", "D"], DAYS[1]: ["B"], DAYS[2]: []}
    per_day = {DAYS[0]: 2, DAYS[1]: 3, DAYS[2]: 1}
    picks = ps.rules_only_picks(eligible, seed=5, buckets={}, per_day=per_day)
    by_day: dict = {}
    for p in picks:
        by_day.setdefault(p.day, []).append(p.symbol)
    assert len(by_day[DAYS[0]]) == 2 and set(by_day[DAYS[0]]) <= {"A", "B", "C", "D"}
    assert by_day[DAYS[1]] == ["B"]  # never more than are eligible
    assert DAYS[2] not in by_day
    assert picks == ps.rules_only_picks(eligible, seed=5, buckets={}, per_day=per_day)  # seeded
    draws = {
        tuple(p.symbol for p in ps.rules_only_picks(eligible, seed=s, buckets={}, per_day=per_day))
        for s in range(20)
    }
    assert len(draws) > 1


def test_rules_only_without_a_count_offers_every_eligible_stock_in_random_order():
    picks = ps.rules_only_picks({DAYS[0]: ["A", "B", "C"]}, seed=1, buckets={"A": "bank"})
    assert sorted(p.symbol for p in picks) == ["A", "B", "C"]
    scores = [p.score for p in picks]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 3  # the book keeps this order
    assert next(p.bucket for p in picks if p.symbol == "A") == "bank"


def test_rules_only_baseline_runs_the_same_account_rules():
    bars = {s: flat() for s in "ABCD"}
    eligible = _eligible(DAYS[:1], "ABCD")
    halted = ps.rules_only_baseline(
        eligible, bars, DAYS, {}, capital=500_000, draws=5, modes={DAYS[0]: "NO_NEW_TRADES"}
    )
    assert halted["draws"] == 5 and halted["trades"]["median"] == 0  # the market-mode limit applies
    normal = ps.rules_only_baseline(eligible, bars, DAYS, {}, capital=500_000, draws=5, per_day={DAYS[0]: 2})
    assert normal["trades"]["median"] == 2 and normal["matched_count"] is True
    assert normal["avg_trade_return"]["draws_with_trades"] == 5
    assert normal["avg_trade_return"]["median"] < 0  # flat stocks: costs only
    assert set(normal["total_return"]) >= {"median", "p5", "p95", "mean"}
    assert normal["seeds"] == "11..15"


def test_a_brain_that_picks_the_one_winner_beats_rules_only_only_with_enough_evidence():
    up = flat(overrides={3: (100, 109, 100, 108)})
    bars = {"A": up, **{s: flat() for s in "BCDE"}}
    eligible = _eligible(DAYS[:1], "ABCDE")
    out = ps.compare_with_rules_only(
        [Pick(DAYS[0], "A", 0.9)], eligible, bars, DAYS, {}, capital=500_000, draws=40
    )
    assert out["brain"]["trades"] == 1
    assert out["rules_only"]["matched_count"] is True
    v = out["verdict"]
    assert v["word"] == "insufficient"  # 1 trade over 1 decision day is far below 60 trades / 40 days
    assert v["brain_avg_trade_return"] > v["rules_median"]
    assert 0.5 < v["brain_beats_share"] <= 1.0
    assert any("rules only" in t.lower() for t in out["limits"])


def test_the_beats_rules_only_rule_of_section_5():
    rules = {
        "avg_trade_return": {
            "median": 0.001,
            "p5": -0.01,
            "p95": 0.012,
            "draws_with_trades": 3,
            "values": [-0.01, 0.001, 0.012],
        }
    }
    enough = {"trading_days": 40}
    win = ps.beats_rules_only({"avg_trade_return": 0.005, "trades": 60}, rules, **enough)
    assert win["word"] == "pass" and win["brain_beats_share"] == pytest.approx(2 / 3)
    lose = ps.beats_rules_only({"avg_trade_return": 0.0005, "trades": 60}, rules, **enough)
    assert lose["word"] == "fail"
    few_trades = ps.beats_rules_only({"avg_trade_return": 0.005, "trades": 59}, rules, **enough)
    assert few_trades["word"] == "insufficient" and "60" in few_trades["why"]
    few_days = ps.beats_rules_only({"avg_trade_return": 0.005, "trades": 60}, rules, trading_days=39)
    assert few_days["word"] == "insufficient" and "40" in few_days["why"]
    no_draws = {
        "avg_trade_return": {"median": None, "p5": None, "p95": None, "draws_with_trades": 0, "values": []}
    }
    assert (
        ps.beats_rules_only({"avg_trade_return": 0.005, "trades": 60}, no_draws, **enough)["word"]
        == "insufficient"
    )


# --- the database side: stored brain runs -> brain picks and the eligible pool ----------------------


def test_rules_only_inputs_refuse_a_window_inside_the_sealed_trial(db_session):
    from swing_trade_ml.services import trial_seal

    with pytest.raises(ValueError, match="sealed"):
        ps.rules_only_inputs(db_session, trial_seal.SEALED_FROM - timedelta(days=5), trial_seal.SEALED_FROM)


def test_rules_only_inputs_read_trade_picks_and_every_non_avoid_idea(db_session):
    from brain_m18_fixtures import decision, run

    day = date(2020, 3, 2)  # far before any real stored run, and before the trial seal
    run(db_session, "tv6-ro-1", day)
    decision(db_session, "tv6-ro-1", "TV6A", "TRADE")
    decision(db_session, "tv6-ro-1", "TV6B", "WATCH")
    decision(db_session, "tv6-ro-1", "TV6C", "WAIT")
    decision(db_session, "tv6-ro-1", "TV6D", "AVOID")
    decision(db_session, "tv6-ro-1", "TV6E", "TRADE", overruled_word="AVOID", overrule_reason="owner")
    inp = ps.rules_only_inputs(db_session, day, day)
    assert [p.symbol for p in inp["picks"]] == ["TV6A"]
    assert sorted(inp["eligible"][day]) == ["TV6A", "TV6B", "TV6C"]
    assert inp["per_day"] == {day: 1}
    assert inp["banners"] == {day: None}


def test_rules_only_comparison_runs_from_stored_runs_and_says_where_modes_came_from(db_session, monkeypatch):
    from brain_m18_fixtures import candle, decision, instrument, run
    from swing_trade_ml.brain import market_mode_history as mmh

    monkeypatch.setattr(mmh, "derived_mode", lambda db, day: "DEFENSIVE")
    day = date(2020, 3, 2)
    a, b = instrument(db_session, "TV6RA", 918801), instrument(db_session, "TV6RB", 918802)
    for n in range(20):
        candle(db_session, a, day + timedelta(days=n), 100.0 + n)  # rising: the brain's pick
        candle(db_session, b, day + timedelta(days=n), 100.0)
    r = run(db_session, "tv6-ro-run", day)
    r.banner_mode = "NORMAL"
    run(db_session, "tv6-ro-run2", day + timedelta(days=1))  # no banner: derived
    decision(db_session, "tv6-ro-run", "TV6RA", "TRADE")
    decision(db_session, "tv6-ro-run", "TV6RB", "WATCH")
    decision(db_session, "tv6-ro-run2", "TV6RB", "WAIT")
    db_session.flush()
    out = ps.run_rules_only_comparison(
        db_session, start=day, end=day + timedelta(days=1), capitals=[500_000], draws=4
    )
    assert out["decision_days"] == 2 and out["brain_picks"] == 1
    assert out["mode_days"] == {"recorded": 1, "derived": 1, "missing": 0}
    (acc,) = out["accounts"]
    assert acc["brain"]["trades"] == 1 and acc["verdict"]["word"] == "insufficient"
    assert acc["rules_only"]["draws"] == 4
    assert any("M04" in t for t in out["limits"])  # a derived day brings its limits
    text = ps.rules_only_report(out)
    assert "1 recorded, 1 derived, 0 missing" in text and "insufficient" in text


def test_the_rules_only_command_needs_an_explicit_end_date():
    with pytest.raises(SystemExit):
        ps.main(["--rules-only", "--from", "2020-03-02"])
