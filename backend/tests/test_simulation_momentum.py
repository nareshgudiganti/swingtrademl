# ruff: noqa: E501  (long plain-English test text)
"""#321 the Momentum policy's picks: the app's existing momentum rule reused read-only, point in time, carrying a rule
reference in place of a horizon record, traced through the store.

The first half needs no database (a fixed synthetic price series). The second half runs the runner on the test database:
stored records and candles -> momentum portfolios that now trade -> persisted rows that trace to the rule reference."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models import (
    Instrument,
    SimBlock,
    SimExit,
    SimFill,
    SimNotRanked,
    SimPortfolio,
    SimRun,
)
from swing_trade_ml.db.models.market import Candle
from swing_trade_ml.simulation import momentum, runner, store
from swing_trade_ml.simulation.cohorts import build_matrix
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Bar, Candidate, run_cohort, run_portfolio
from swing_trade_ml.simulation.rules import TradingRules
from test_p0_end_to_end import MODEL_5D, SESSIONS, _make_security, world  # noqa: F401 - `world` is a fixture
from test_simulation_runner import stored  # noqa: F401 - fixture: the world's December candles

RULE = "momentum-20d-top5:v1"


def _weekdays(start: date, count: int) -> list[date]:
    out, day = [], start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


HISTORY = _weekdays(date(2026, 9, 1), 80)  # 80 weekdays: plenty of history before the last sessions
DECISION_DAYS = HISTORY[-12:]  # the sessions the policy decides on
SESS = [d.isoformat() for d in DECISION_DAYS]


def _closes(n_stocks: int = 9, seed: int = 7, days=HISTORY) -> dict[int, dict[date, float]]:
    rng = random.Random(seed)
    out = {}
    for i in range(n_stocks):
        price, drift = 100.0 + 15 * i, rng.uniform(-0.004, 0.006)
        series = {}
        for d in days:
            price *= 1 + drift + rng.uniform(-0.02, 0.02)
            series[d] = round(price, 2)
        out[500 + i] = series
    return out


def _ids(decisions):
    return {s: [c.security_id for c in picks] for s, picks in decisions.items()}


# ----------------------------------------------------------------------------------------------- the rule, pure


def test_the_rule_reference_is_built_from_the_rule_it_reuses():
    from swing_trade_ml.brain.walk_forward import MOMENTUM_BARS
    from swing_trade_ml.services.brain_observatory.defs import TOP_N

    assert (MOMENTUM_BARS, TOP_N) == (20, 5) and momentum.rule_ref() == RULE


def test_the_picks_are_the_existing_rule_top_five_by_trailing_20_bar_gain_at_each_close():
    closes = _closes()
    decisions = momentum.momentum_decisions(closes, SESS)
    assert set(decisions) == set(SESS)
    for day in DECISION_DAYS:
        gain = {}
        for sid, series in closes.items():
            ordered = sorted(series)
            i = ordered.index(day)
            gain[sid] = series[day] / series[ordered[i - 20]] - 1.0
        expected = sorted(gain, key=lambda sid: (-gain[sid], str(sid)))[:5]
        picks = decisions[day.isoformat()]
        assert [c.security_id for c in picks] == expected
        assert [c.score for c in picks] == pytest.approx([gain[s] for s in expected])
        assert all(c.rule_ref == RULE and c.record_id is None and c.block_reason is None for c in picks)


def test_picks_never_use_a_candle_after_the_decision_day():
    closes = _closes()
    base = momentum.momentum_decisions(closes, SESS)
    k = DECISION_DAYS[6]
    poisoned = {
        sid: {d: (c if d <= k else (c * 50 if sid % 2 else c / 50)) for d, c in series.items()}
        for sid, series in closes.items()
    }
    after = momentum.momentum_decisions(poisoned, SESS)
    for day in DECISION_DAYS:
        if day <= k:
            assert _ids(after)[day.isoformat()] == _ids(base)[day.isoformat()], day
            assert [c.score for c in after[day.isoformat()]] == [c.score for c in base[day.isoformat()]]
    assert any(_ids(after)[d.isoformat()] != _ids(base)[d.isoformat()] for d in DECISION_DAYS if d > k)
    extra = {
        sid: {**series, date(2027, 1, 4): 1e9} for sid, series in closes.items()
    }  # a close past the last session
    assert momentum.momentum_decisions(extra, SESS) == base


def test_too_little_history_gives_no_pick_and_the_universe_is_the_callers():
    short = _closes(days=HISTORY[-15:])
    assert momentum.momentum_decisions(short, SESS) == {}  # 15 bars: no 20-bar window yet
    closes = _closes()
    limited = momentum.momentum_decisions(closes, SESS, universe=[500, 501, 502])
    assert {c.security_id for picks in limited.values() for c in picks} <= {500, 501, 502}
    assert all(len(picks) == 3 for picks in limited.values())
    assert momentum.momentum_decisions(closes, SESS, universe=[]) == {}
    assert momentum.momentum_decisions(closes, []) == {}


def _tied(ids: dict[int, str]) -> dict[int, dict[date, float]]:
    """Stocks with one identical price series: every stock ties on the momentum score on every day."""
    series = {d: 100.0 + 0.3 * i for i, d in enumerate(HISTORY)}
    return {sid: dict(series) for sid in ids}


def test_ties_break_by_symbol_exactly_as_the_brain_baseline_does_and_not_by_id_text():
    from swing_trade_ml.services.brain_observatory.baselines import momentum_picks

    symbols = {1: "ZZZ", 2: "AAA", 3: "MMM", 9: "BBB", 10: "CCC", 11: "DDD", 12: "EEE"}
    closes = _tied(symbols)
    result = momentum.momentum_decisions(closes, SESS, symbols=symbols)
    for day in SESS:  # the five alphabetically first symbols win the tie, whatever their ids are
        assert [c.symbol for c in result[day]] == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    import pandas as pd

    bars = {
        sym: pd.DataFrame(
            {"day": sorted(closes[sid]), "close": [closes[sid][d] for d in sorted(closes[sid])]}
        )
        for sid, sym in symbols.items()
    }
    days = [date.fromisoformat(s) for s in SESS]
    expected = momentum_picks(bars, {d: sorted(bars) for d in days}, days)  # the brain baseline itself
    assert [[c.symbol for c in result[d.isoformat()]] for d in days] == [expected[d] for d in days]
    # with no symbols the id breaks the tie as a NUMBER: 9 before 10 (as text, "10" would come first)
    plain = momentum.momentum_decisions(_tied({9: "", 10: "", 11: "", 12: "", 13: "", 14: ""}), SESS)
    assert [c.security_id for c in plain[SESS[-1]]] == [9, 10, 11, 12, 13]


def test_a_declared_stock_with_no_stored_prices_is_reported_not_silently_dropped():
    closes = _closes()
    declared = [*closes, 7001, 7002]
    closes[7002] = {}  # a stock that is known but has no candle at all
    result = momentum.momentum_result(closes, SESS, universe=declared)
    assert result.not_ranked == {7001: momentum.NO_PRICES, 7002: momentum.NO_PRICES}
    assert set(result.ranked) == set(closes) - {7002} and set(result.ranked) | set(result.not_ranked) == set(
        declared
    )
    assert not {7001, 7002} & {c.security_id for picks in result.decisions.values() for c in picks}
    assert momentum.NO_PRICES == "no stored prices in window"
    assert result.decisions == momentum.momentum_decisions(closes, SESS, universe=declared)
    only_future = {sid: {d: c for d, c in s.items() if d > DECISION_DAYS[-1]} for sid, s in _closes().items()}
    assert set(momentum.momentum_result(only_future, SESS).not_ranked) == set(
        only_future
    )  # nothing up to the last session


def _bars(closes):
    return {
        sid: {
            d.isoformat(): Bar(c, c * 1.01, c * 0.99, c) for d, c in series.items() if d >= DECISION_DAYS[0]
        }
        for sid, series in closes.items()
    }


def test_momentum_portfolios_trade_on_a_fixed_series_with_identical_ledgers_for_identical_setups():
    closes = _closes()
    decisions = momentum.momentum_decisions(closes, SESS, symbols={sid: f"S{sid}" for sid in closes})
    bars = _bars(closes)
    rules = TradingRules.plan_5d()
    spec = next(
        s
        for s in build_matrix()
        if s.policy is Policy.MOMENTUM and s.balance_inr == 1_000_000 and s.start_offset == 0
    )
    first = run_portfolio(spec, SESS, bars, decisions, rules)
    again = run_portfolio(replace(spec, persona_key="syn-replica"), SESS, bars, decisions, rules)
    assert first.fill_count > 0 and first.records == again.records
    fills = [f for r in first.records for f in r.fills]
    assert all(f.rule_ref == RULE and f.record_id is None and f.symbol.startswith("S") for f in fills)
    assert all(x.rule_ref == RULE for r in first.records for x in r.exits)
    assert all(b.rule_ref == RULE for r in first.records for b in r.blocks)
    # same rules, sizing and blocks as the other policies: it is the same ledger, a small account still blocks
    small = run_portfolio(replace(spec, balance_inr=10_000), SESS, bars, decisions, rules)
    assert small.fill_count == 0 and small.block_count > 0
    assert all(b.reason for r in small.records for b in r.blocks)


def test_the_cohort_runs_all_33_momentum_portfolios_and_some_trade():
    closes = _closes()
    decisions = momentum.momentum_decisions(closes, SESS)
    specs = [s for s in build_matrix() if s.policy is Policy.MOMENTUM]
    ledgers = run_cohort(specs, SESS, _bars(closes), {Policy.MOMENTUM: decisions}, TradingRules.plan_5d())
    assert len(ledgers) == 33 and sum(1 for led in ledgers.values() if led.fill_count) >= 20
    assert all(len(led.records) == len(SESS) - led.spec.start_offset for led in ledgers.values())


# ----------------------------------------------------------------------------------------------- the store, pure


def test_the_store_accepts_momentum_rows_with_a_rule_reference_and_refuses_the_rest():
    closes = _closes()
    decisions = momentum.momentum_decisions(closes, SESS)
    rules = TradingRules.plan_5d()
    spec = next(s for s in build_matrix() if s.policy is Policy.MOMENTUM and s.balance_inr == 1_000_000)
    ledger = run_portfolio(spec, SESS, _bars(closes), decisions, rules)
    ledgers = {spec.persona_key: ledger}
    store._validate("run", ledgers, rules)  # accepted: every row names the rule
    i = next(i for i, r in enumerate(ledger.records) if r.fills)
    record = ledger.records[i]
    bare = replace(record, fills=(replace(record.fills[0], rule_ref=None), *record.fills[1:]))
    broken = replace(ledger, records=(*ledger.records[:i], bare, *ledger.records[i + 1 :]))
    with pytest.raises(store.StoreError, match="no rule reference"):
        store._validate("run", {spec.persona_key: broken}, rules)
    # the other policies still need a horizon record, and may not carry a rule reference
    model_spec = replace(spec, policy=Policy.MODEL_ONLY)
    as_model = replace(ledger, spec=model_spec)
    with pytest.raises(store.StoreError, match="no horizon record"):
        store._validate("run", {model_spec.persona_key: as_model}, rules)
    with_both = replace(record, fills=(replace(record.fills[0], record_id=1), *record.fills[1:]))
    both = replace(as_model, records=(*ledger.records[:i], with_both, *ledger.records[i + 1 :]))
    with pytest.raises(store.StoreError, match="only momentum"):
        store._validate("run", {model_spec.persona_key: both}, rules)


# ----------------------------------------------------------------------------- the runner on stored data (database)


@pytest.fixture()
def with_history(stored):  # noqa: F811
    """The world's December candles plus 30 earlier weekdays, so a 20-bar window exists before the first decision."""
    db = stored["db"]
    instruments = {
        i.tradingsymbol: i.id
        for i in db.scalars(select(Instrument).where(Instrument.tradingsymbol.like("P0%")))
    }
    first = datetime.fromisoformat(SESSIONS[0]).date()
    earlier = [d for d in _weekdays(first - timedelta(days=60), 60) if d < first][-30:]
    rng = random.Random(3)
    for symbol in stored["by_symbol"]:
        price = 90.0 + rng.uniform(0, 20)
        for d in earlier:
            price *= 1 + rng.uniform(-0.02, 0.02)
            db.add(
                Candle(
                    instrument_id=instruments[symbol],
                    interval="day",
                    ts=datetime.combine(d, datetime.min.time(), tzinfo=IST),
                    open=price,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                    volume=1000,
                )
            )
    db.flush()
    return stored


def _momentum_count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.policy == "momentum"))


def test_momentum_portfolios_now_trade_from_stored_candles_and_trace_to_the_rule_reference(with_history):
    db = with_history["db"]
    report = runner.run_and_persist(
        db,
        run_key="mom-run",
        sessions=SESSIONS,
        models=[MODEL_5D],
        momentum_universe=with_history["universe"],
    )
    assert report.picks["momentum"] > 0 and any("momentum-20d-top5:v1" in n for n in report.notes)
    assert _momentum_count(db, SimFill) > 0
    rows = [r for r in store.trace_fills(db, "mom-run") if r.policy == "momentum"]
    assert rows and all(r.rule_ref == RULE and r.horizon_record_id is None for r in rows)
    for model in (SimFill, SimExit, SimBlock):
        refs = set(db.scalars(select(model.rule_ref).where(model.policy == "momentum")))
        assert refs <= {RULE} and None not in refs
        assert not db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.policy != "momentum", model.rule_ref.is_not(None))
        )
    others = [r for r in store.trace_fills(db, "mom-run") if r.policy != "momentum"]
    assert others and all(r.horizon_record_id is not None and r.rule_ref is None for r in others)
    # the universe is the one the run declared: the stock with 10D/15D records only is not in it, so it is never ranked
    only_long = with_history["only_long"]
    assert not db.scalar(select(func.count()).select_from(SimFill).where(SimFill.security_id == only_long))
    # the 10K and 25K momentum accounts still hold cash (no forced trades), each with its block reasons
    small = list(
        db.scalars(
            select(SimPortfolio).where(
                SimPortfolio.policy == "momentum", SimPortfolio.balance_inr.in_((10_000, 25_000))
            )
        )
    )
    assert len(small) == 6
    for p in small:
        assert not db.scalar(select(func.count()).select_from(SimFill).where(SimFill.portfolio_id == p.id))


def test_momentums_universe_is_its_own_and_not_the_models(with_history):
    db, only_long = with_history["db"], with_history["only_long"]  # a stock the model never scored for 5D
    runner.run_and_persist(
        db, run_key="mom-own", sessions=SESSIONS, models=[MODEL_5D], momentum_universe=[only_long]
    )
    momentum_ids = set(db.scalars(select(SimFill.security_id).where(SimFill.policy == "momentum")))
    assert momentum_ids == {only_long}
    assert only_long not in set(db.scalars(select(SimFill.security_id).where(SimFill.policy != "momentum")))
    assert db.scalar(select(SimRun.momentum_universe).where(SimRun.run_key == "mom-own")) == f"[{only_long}]"


def test_a_declared_stock_without_candles_is_recorded_as_not_ranked_and_reported(with_history):
    db = with_history["db"]
    ghost = _make_security(db, "P0GHOST")  # a known security with an instrument, but no stored candle at all
    db.flush()
    universe = [*with_history["universe"], ghost]
    run = {"run_key": "mom-gap", "sessions": SESSIONS, "models": [MODEL_5D], "momentum_universe": universe}
    report = runner.run_and_persist(db, **run)
    assert (report.momentum_declared, report.momentum_ranked) == (7, 6)
    assert report.momentum_not_ranked == {ghost: "no stored prices in window"}
    assert any("6 of 7" in n and "no stored prices in window" in n for n in report.notes)
    assert "6 of 7" in report.summary()
    rows = list(db.execute(select(SimNotRanked.security_id, SimNotRanked.reason)))
    assert rows == [(ghost, "no stored prices in window")]
    assert report.created["sim_not_ranked"] == 1
    assert not db.scalar(select(func.count()).select_from(SimFill).where(SimFill.security_id == ghost))
    assert runner.run_and_persist(db, **run).rows_created == 0  # a replay adds nothing, the row exists once
    assert db.scalar(select(func.count()).select_from(SimNotRanked)) == 1
    # a replay that records another set of not-ranked stocks is refused, and writes nothing
    ledgers_before = db.scalar(select(func.count()).select_from(SimFill))
    from swing_trade_ml.simulation import store as sim_store

    with pytest.raises(sim_store.ReplayMismatchError):
        runner.run_and_persist(db, **{**run, "momentum_universe": [*universe, with_history["only_long"]]})
    assert db.scalar(select(func.count()).select_from(SimNotRanked)) == 1
    assert db.scalar(select(func.count()).select_from(SimFill)) == ledgers_before
    # the store itself refuses a different not-ranked set or a reason-less row
    stored_run = db.scalar(select(SimRun).where(SimRun.run_key == "mom-gap"))
    with pytest.raises(sim_store.ReplayMismatchError):
        sim_store._store_not_ranked(db, stored_run, {ghost: "another reason"}, sim_store.StoreResult(0))
    with pytest.raises(sim_store.ReplayMismatchError):
        sim_store._store_not_ranked(db, stored_run, {}, sim_store.StoreResult(0))
    with pytest.raises(sim_store.StoreError):
        sim_store._store_not_ranked(db, stored_run, {ghost: ""}, sim_store.StoreResult(0))


def test_picks_passed_in_cannot_claim_the_momentum_rules_reference(with_history):
    db, sid = with_history["db"], with_history["universe"][0]
    base = {
        "run_key": "mom-claim",
        "sessions": SESSIONS,
        "models": [MODEL_5D],
        "momentum_universe": with_history["universe"],
    }
    for ref in (RULE, None, "", " "):
        with pytest.raises(runner.RunnerError, match="rule reference"):
            runner.run_and_persist(
                db, **base, momentum={SESSIONS[3]: [Candidate(sid, "P0E0", 0.5, rule_ref=ref)]}
            )
    assert not db.scalar(select(func.count()).select_from(SimRun).where(SimRun.run_key == "mom-claim"))
    own = {SESSIONS[3]: [Candidate(sid, "P0E0", 0.5, rule_ref="my-own-list:v1")]}
    assert runner.run_and_persist(db, **base, momentum=own).picks["momentum"] == 1
    # the rule's own picks do carry its reference
    made = runner.run_and_persist(db, **{**base, "run_key": "mom-own-rule"})
    assert made.picks["momentum"] > 0 and RULE in made.summary()


def test_a_second_momentum_run_adds_nothing_and_a_longer_one_adds_only_new_days(with_history):
    db = with_history["db"]
    first = runner.run_and_persist(
        db,
        run_key="mom-run",
        sessions=SESSIONS[:12],
        models=[MODEL_5D],
        momentum_universe=with_history["universe"],
    )
    again = runner.run_and_persist(
        db,
        run_key="mom-run",
        sessions=SESSIONS[:12],
        models=[MODEL_5D],
        momentum_universe=with_history["universe"],
    )
    assert again.rows_created == 0 and again.run_id == first.run_id
    longer = runner.run_and_persist(
        db,
        run_key="mom-run",
        sessions=SESSIONS,
        models=[MODEL_5D],
        momentum_universe=with_history["universe"],
    )
    assert longer.created.get("sim_portfolios", 0) == 0 and longer.created["sim_days"] > 0
    assert (
        runner.run_and_persist(
            db,
            run_key="mom-run",
            sessions=SESSIONS,
            models=[MODEL_5D],
            momentum_universe=with_history["universe"],
        ).rows_created
        == 0
    )
