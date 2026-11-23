# ruff: noqa: E501  (long plain-English test text)
"""P0 end to end: synthetic securities (identity writer) -> 5D horizon records (Developer-4's writer) -> the 99+1
simulated portfolios under rule hz-rules-v1:5D -> checks on traceability, repeatability, zero-trade accounts, the
horizon gate and look-ahead.

What is real here: the identity tables and writer, the horizon-record table and its writer, the research config, the
cohort matrix, the ledger and the app's limits, costs and sizing. What is SYNTHETIC: the securities (invented symbols, no
ISIN), their prices, their model scores, and the momentum picks (no verified ranking source exists yet). Nothing is
persisted by the simulation itself (no table yet), nothing is sent, and no real stock or user is involved.
"""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brain.horizons import HorizonStore, ModelOutput, run_all_horizons
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import writer
from swing_trade_ml.simulation import source
from swing_trade_ml.simulation.cohorts import build_matrix, comparison_specs
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import (
    Bar,
    Candidate,
    compare_by_policy,
    ledgers_rule_version,
    run_cohort,
    run_portfolio,
)
from swing_trade_ml.simulation.rules import MixedRuleVersions, TradingRules

ALL_DAYS = tuple(d for i in range(60) if (d := date(2026, 12, 1) + timedelta(days=i)).weekday() < 5)
SESSIONS = tuple(d.isoformat() for d in ALL_DAYS[:16])
RECORDED = ALL_DAYS[:12]  # sessions that have records; the last four only trade out
SCORES = {0: 0.90, 1: 0.88, 2: 0.86, 3: 0.84, 4: 0.70, 5: 0.30}  # TRADE, TRADE, TRADE, TRADE, WATCH, WAIT
_tokens = iter(range(420_000, 420_900))


def _bars(index: int) -> list[Bar]:
    rng = random.Random(1000 + index)
    out, last = [], 100.0 + 10 * index
    for _ in SESSIONS:
        o = last * (1 + rng.uniform(-0.01, 0.01))
        c = o * (1 + rng.uniform(-0.03, 0.03))
        out.append(Bar(o, max(o, c) * 1.012, min(o, c) * 0.988, c))
        last = c
    return out


def _output(symbol: str, horizon: int, session: date, score: float) -> ModelOutput:
    return ModelOutput(
        model_name=f"synthetic_h{horizon}",
        model_version=f"v{horizon}.1",
        forecast_horizon_sessions=horizon,
        role="final",
        symbol=symbol,
        input_session=session,
        input_close=100.0,
        score=score,
    )


def _make_security(db, symbol: str) -> int:
    instrument = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        exchange="NSE",
        instrument_type="EQ",
        is_active=True,
    )
    db.add(instrument)
    db.flush()
    return writer.ensure_for_instrument(db, instrument)


@pytest.fixture()
def world(db_session):
    """Six synthetic securities with 5D, 10D and 15D records for 12 sessions, plus one that only has 10D/15D records."""
    secs: dict[int, str] = {}
    for i in range(6):
        symbol = f"P0E{i}"
        secs[_make_security(db_session, symbol)] = symbol
    only_long = _make_security(db_session, "P0ONLY")
    ids = list(secs)
    for day in RECORDED:
        for k, sid in enumerate(ids):
            results = run_all_horizons(
                day,
                [_output(secs[sid], h, day, SCORES[k]) for h in (5, 10, 15)],
                ALL_DAYS,
                HorizonStore(),
                symbol=secs[sid],
                research_caller=True,  # 10D and 15D give a decision word only to research callers
            )
            for horizon, record in results.items():
                hr.save_for_symbol(
                    db_session, record, scan_key=f"p0e2e:{day}", run_ref=f"run-{day}-{horizon}"
                )
        long_only = {
            h: run_all_horizons(
                day,
                [_output("P0ONLY", h, day, 0.95) for h in (10, 15)],
                ALL_DAYS,
                HorizonStore(),
                symbol="P0ONLY",
                research_caller=True,
            )[h]
            for h in (10, 15)
        }
        for record in long_only.values():
            hr.save_for_symbol(db_session, record, scan_key=f"p0e2e:{day}", run_ref=f"run-{day}-long")
    db_session.flush()
    bars = {symbol: dict(zip(SESSIONS, _bars(i), strict=True)) for i, symbol in enumerate(secs.values())}
    bars["P0ONLY"] = dict(zip(SESSIONS, _bars(9), strict=True))
    return {"secs": secs, "only_long": only_long, "bars": bars, "db": db_session}


def _momentum(bars) -> dict[str, list[Candidate]]:
    """Synthetic: the two best 3-session returns among the six, using only bars up to the decision session."""
    symbols = [s for s in bars if s != "P0ONLY"]
    picks: dict[str, list[Candidate]] = {}
    for i in range(3, len(SESSIONS) - 1):
        ranked = sorted(
            symbols, key=lambda s: -(bars[s][SESSIONS[i]].close / bars[s][SESSIONS[i - 3]].close - 1)
        )
        picks[SESSIONS[i]] = [Candidate(s, 0.5, f"sec-{s}") for s in ranked[:2]]
    return picks


@pytest.fixture()
def run(world):
    rules = TradingRules.plan_5d()
    db = world["db"]
    decisions = source.decisions_by_policy(db, rules, momentum=_momentum(world["bars"]), sessions=SESSIONS)
    specs = build_matrix()
    ledgers = run_cohort(specs, SESSIONS, world["bars"], decisions, rules)
    return {**world, "rules": rules, "decisions": decisions, "specs": specs, "ledgers": ledgers}


def test_there_are_99_compared_portfolios_plus_1_validation_and_each_has_a_record_for_every_session(run):
    specs, ledgers = run["specs"], run["ledgers"]
    assert len(specs) == 100 and len(comparison_specs(specs)) == 99
    for spec in specs:
        ledger = ledgers[spec.persona_key]
        assert [r.session for r in ledger.records] == list(SESSIONS[spec.start_offset :])
        assert ledger.rule_version == "hz-rules-v1:5D" and ledger.research_only is False
    assert ledgers_rule_version(ledgers) == "hz-rules-v1:5D"
    table = compare_by_policy(ledgers)
    assert {p: row["portfolios"] for p, row in table.items()} == {
        Policy.MOMENTUM: 33,
        Policy.MODEL_ONLY: 33,
        Policy.BRAIN_FILTERED: 33,
    }


def test_every_pick_traces_to_a_security_and_a_horizon_record(run):
    db, ledgers, specs = run["db"], run["ledgers"], run["specs"]
    secs = run["secs"]
    checked = 0
    for spec in specs:
        if spec.policy is Policy.MOMENTUM:
            continue  # momentum has no record source yet: its picks carry a security but no record (still synthetic)
        for record in ledgers[spec.persona_key].records:
            for item in (*record.fills, *record.blocks):
                if item.record_id is None:
                    raise AssertionError(f"{spec.persona_key} {record.session}: {item} has no record id")
                row = db.get(HorizonRecordRow, item.record_id)
                assert row is not None and row.horizon_days == 5 and row.research_only is False
                assert row.security_id == item.security_id and secs[row.security_id] == item.symbol
                assert row.session_date < date.fromisoformat(record.session)  # decided at an earlier close
                checked += 1
    assert checked > 100
    momentum_fills = [
        f
        for s in specs
        if s.policy is Policy.MOMENTUM
        for r in ledgers[s.persona_key].records
        for f in r.fills
    ]
    assert momentum_fills and all(f.record_id is None for f in momentum_fills)


def test_identical_setups_give_identical_ledgers(run):
    ledgers, specs = run["ledgers"], run["specs"]
    spec = next(
        s
        for s in specs
        if s.policy is Policy.MODEL_ONLY and s.balance_inr == 1_000_000 and s.start_offset == 0
    )
    replica = run_portfolio(
        replace(spec, persona_key="syn-replica"),
        SESSIONS,
        run["bars"],
        run["decisions"][Policy.MODEL_ONLY],
        run["rules"],
    )
    assert replica.records == ledgers[spec.persona_key].records
    by_setup: dict[str, dict[Policy, object]] = {}
    for s in comparison_specs(specs):
        by_setup.setdefault(s.setup_key, {})[s.policy] = ledgers[s.persona_key]
    for policies in by_setup.values():
        model, brain = policies[Policy.MODEL_ONLY], policies[Policy.BRAIN_FILTERED]
        assert [r.fills for r in model.records] == [
            r.fills for r in brain.records
        ]  # the Brain only holds picks back
        assert brain.block_count >= model.block_count


def test_zero_trade_accounts_are_present_with_every_session_and_a_reason_for_every_blocked_pick(run):
    ledgers, specs = run["ledgers"], run["specs"]
    small = [
        s for s in specs if s.balance_inr in (10_000, 25_000)
    ]  # includes the validation portfolio (setup-01)
    zero = [s for s in specs if ledgers[s.persona_key].fill_count == 0]
    assert small and {s.persona_key for s in small} <= {
        s.persona_key for s in zero
    }  # the two smallest balances never trade
    for spec in small:
        ledger = ledgers[spec.persona_key]
        assert len(ledger.records) == len(SESSIONS) - spec.start_offset
        assert all(r.equity == r.cash == spec.balance_inr and r.positions == () for r in ledger.records)
        if spec.policy is not Policy.MOMENTUM:
            reasons = {b.reason for r in ledger.records for b in r.blocks}
            assert reasons and reasons <= {
                "below_minimum_position",
                "held_back: brain check: WATCH",
                "held_back: brain check: WAIT",
            }
    table = compare_by_policy(ledgers)
    assert all(row["zero_trade_portfolios"] >= 6 for row in table.values())  # counted in every comparison


def test_no_10d_or_15d_record_reaches_a_5d_portfolio(run):
    db, ledgers, specs = run["db"], run["ledgers"], run["specs"]
    only_long = run["only_long"]
    assert db.scalar(
        select(HorizonRecordRow.id)
        .where(HorizonRecordRow.security_id == only_long, HorizonRecordRow.horizon_days == 10)
        .limit(1)
    )
    for spec in specs:
        for record in ledgers[spec.persona_key].records:
            for item in (*record.fills, *record.blocks):
                assert item.symbol != "P0ONLY" and item.security_id != only_long
                if item.record_id is not None:
                    assert db.get(HorizonRecordRow, item.record_id).horizon_days == 5
    seen = source.read_records(db, run["rules"])
    assert seen and {r.horizon_days for r in seen} == {5} and not any(r.research_only for r in seen)


def test_a_research_rule_reads_its_own_horizon_and_the_ledger_says_research_only(run):
    db, secs = run["db"], run["secs"]
    rules15 = TradingRules.plan_15d()
    assert rules15.research_only is True
    decisions = source.decisions_by_policy(db, rules15, sessions=SESSIONS)
    symbols = {c.symbol for picks in decisions[Policy.MODEL_ONLY].values() for c in picks}
    assert "P0ONLY" in symbols  # the 15D rule sees the stock that has only long-horizon records
    assert {r.horizon_days for r in source.read_records(db, rules15)} == {15}
    spec = next(s for s in build_matrix() if s.balance_inr == 1_000_000 and s.policy is Policy.MODEL_ONLY)
    ledger = run_portfolio(spec, SESSIONS, run["bars"], decisions[Policy.MODEL_ONLY], rules15)
    assert ledger.research_only and all(r.research_only for r in ledger.records)
    assert ledger.rule_version == "hz-rules-v1:15D" and secs
    with pytest.raises(MixedRuleVersions):  # a 5D and a 15D result never share a comparison
        ledgers_rule_version({"a": ledger, "b": run["ledgers"][spec.persona_key]})


def test_the_adapter_refuses_a_row_that_does_not_belong_to_the_rule_even_if_the_service_returned_it(
    monkeypatch,
):
    """Defence in depth: whatever the service hands back, a 10D row, a research row for a product rule, or a row made
    under another research config stops the run."""
    from types import SimpleNamespace

    good = {
        "id": 1,
        "session_date": date(2026, 12, 1),
        "horizon_days": 5,
        "research_only": False,
        "research_config_version": "hz-rules-v1",
    }
    rules = TradingRules.plan_5d()
    monkeypatch.setattr(source, "_security_ids", lambda db: [1])
    monkeypatch.setattr(hr, "records_for", lambda db, sid, **kw: [SimpleNamespace(**good)])
    assert source.read_records(None, rules)
    for bad in ({"horizon_days": 10}, {"research_only": True}, {"research_config_version": "hz-rules-v2"}):
        monkeypatch.setattr(
            hr, "records_for", lambda db, sid, bad=bad, **kw: [SimpleNamespace(**{**good, **bad})]
        )
        with pytest.raises(source.HorizonSourceError):
            source.read_records(None, rules)


def test_nothing_looks_ahead(run):
    ledgers, specs, bars = run["ledgers"], run["specs"], run["bars"]
    k = 7
    poisoned = {
        s: {d: (b if SESSIONS.index(d) <= k else Bar(1.0, 9_999.0, 0.01, 5_000.0)) for d, b in m.items()}
        for s, m in bars.items()
    }
    for spec in [s for s in specs if s.policy is Policy.MODEL_ONLY][:6]:
        later = run_portfolio(spec, SESSIONS, poisoned, run["decisions"][Policy.MODEL_ONLY], run["rules"])
        full = ledgers[spec.persona_key]
        upto = len([r for r in full.records if SESSIONS.index(r.session) <= k])
        assert later.records[:upto] == full.records[:upto]
    for spec in specs:
        for record in ledgers[spec.persona_key].records:
            for fill in record.fills:
                if fill.record_id is not None:
                    row = run["db"].get(HorizonRecordRow, fill.record_id)
                    assert row.session_date < date.fromisoformat(
                        record.session
                    )  # bought after the record's own session


def test_a_later_revision_of_a_record_never_changes_what_a_past_session_picked(run):
    db, rules = run["db"], run["rules"]
    sid = next(iter(run["secs"]))
    day = RECORDED[2]
    before = source.decisions_from_horizon_records(db, rules, Policy.MODEL_ONLY)[day.isoformat()]
    first = db.scalar(
        select(HorizonRecordRow).where(
            HorizonRecordRow.security_id == sid,
            HorizonRecordRow.session_date == day,
            HorizonRecordRow.horizon_days == 5,
        )
    )
    results = run_all_horizons(
        day, [_output(run["secs"][sid], 5, day, 0.10)], ALL_DAYS, HorizonStore(), symbol=run["secs"][sid]
    )
    saved = hr.save_for_symbol(db, results[5], scan_key="rerun")
    assert saved.created and saved.revision == 2  # the re-run is kept as revision 2 ...
    after = source.decisions_from_horizon_records(db, rules, Policy.MODEL_ONLY)[day.isoformat()]
    assert [c.record_id for c in after] == [c.record_id for c in before] and first.id in {
        c.record_id for c in after
    }  # ... and ignored
