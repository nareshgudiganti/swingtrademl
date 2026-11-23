# ruff: noqa: E501  (long plain-English test text)
"""#321 persistence of the simulation: idempotent, never rewritten, cash never negative, the validation portfolio in no
denominator, blocked decisions and not-applied rules stored, every fill traceable stock -> horizon record -> policy and
rule version -> fill, and synthetic rows unreachable by real users.

Uses the synthetic world of the end-to-end test (identity writer -> 5D horizon records -> ledgers). Needs the test
database; every write rolls back with the test."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

import swing_trade_ml
from swing_trade_ml.db.base import Base
from swing_trade_ml.db.models import (
    SimBlock,
    SimDay,
    SimExit,
    SimFill,
    SimMark,
    SimNotApplied,
    SimPortfolio,
    SimRun,
    User,
)
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.simulation import source, store
from swing_trade_ml.simulation.cohorts import build_matrix
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import BlockRecord, ExitRecord, compare_by_policy, run_cohort
from swing_trade_ml.simulation.rules import MixedRuleVersions, TradingRules
from test_p0_end_to_end import ALL_DAYS, SESSIONS, _momentum, world  # noqa: F401 - `world` is a fixture

SRC = Path(swing_trade_ml.__file__).parent
SIM_MODELS = (SimRun, SimPortfolio, SimNotApplied, SimDay, SimFill, SimExit, SimBlock, SimMark)
RUN = "run-test-1"


def _count(db) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in SIM_MODELS}


@pytest.fixture()
def sim(world):  # noqa: F811
    """A small cohort: the 10K and 10L setups at offset 0 under all three policies, plus the validation portfolio."""
    rules = TradingRules.plan_5d()
    db = world["db"]
    decisions = source.decisions_by_policy(
        db, rules, momentum=_momentum(world["by_symbol"], world["ids"]), sessions=SESSIONS
    )
    specs = [
        s
        for s in build_matrix()
        if (s.balance_inr in (10_000, 1_000_000) and s.start_offset == 0 and s.counts_in_comparison)
        or not s.counts_in_comparison
    ]
    ledgers = run_cohort(specs, SESSIONS, world["bars"], decisions, rules)
    return {**world, "rules": rules, "specs": specs, "ledgers": ledgers}


def test_a_run_is_stored_with_every_ledger_row(sim):
    db, ledgers = sim["db"], sim["ledgers"]
    result = store.persist_run(db, RUN, ledgers, sim["rules"])
    counts = _count(db)
    assert result.run_id and counts["sim_runs"] == 1 and counts["sim_portfolios"] == len(ledgers) == 7
    assert counts["sim_days"] == sum(len(led.records) for led in ledgers.values())
    assert counts["sim_fills"] == sum(led.fill_count for led in ledgers.values()) > 0
    assert counts["sim_exits"] == sum(led.exit_count for led in ledgers.values())
    assert counts["sim_blocks"] == sum(led.block_count for led in ledgers.values()) > 0
    assert counts["sim_marks"] == sum(len(r.positions) for led in ledgers.values() for r in led.records)
    run = db.scalar(select(SimRun))
    assert (
        run.rule_version,
        run.research_config_version,
        run.horizon_days,
        run.synthetic,
        run.schema_version,
    ) == (
        "hz-rules-v1:5D",
        "hz-rules-v1",
        5,
        True,
        1,
    )
    assert run.research_only is False


def test_writing_the_same_run_again_changes_nothing(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    first = store.persist_run(db, RUN, ledgers, rules)
    before = _count(db)
    cash_before = db.scalar(select(func.sum(SimDay.cash)))
    again = store.persist_run(db, RUN, ledgers, rules)
    third = store.persist_run(db, RUN, dict(reversed(list(ledgers.items()))), rules)
    assert again.run_id == first.run_id == third.run_id
    assert again.total_created == 0 and third.total_created == 0 and again.existing["sim_fills"] > 0
    assert _count(db) == before and db.scalar(select(func.sum(SimDay.cash))) == cash_before


def test_a_replay_with_other_values_is_refused_and_writes_nothing(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    store.persist_run(db, RUN, ledgers, rules)
    before = _count(db)
    key = next(k for k, led in ledgers.items() if led.fill_count)
    ledger = ledgers[key]
    first = ledger.records[0]
    changed = {
        **ledgers,
        key: replace(ledger, records=(replace(first, equity=first.equity + 1.0), *ledger.records[1:])),
    }
    with pytest.raises(store.ReplayMismatchError):
        store.persist_run(db, RUN, changed, rules)
    # another rule version under the same key is refused too
    with pytest.raises(MixedRuleVersions):
        store.persist_run(db, RUN, ledgers, TradingRules.plan_15d())
    assert _count(db) == before


def test_a_refused_replay_leaves_even_its_new_rows_unwritten(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    keys = list(ledgers)
    store.persist_run(db, RUN, {k: ledgers[k] for k in keys[:3]}, rules)
    before = _count(db)
    bad = ledgers[keys[0]]
    broken = replace(bad, records=(replace(bad.records[0], cash=bad.records[0].cash + 5.0), *bad.records[1:]))
    with pytest.raises(store.ReplayMismatchError):
        store.persist_run(
            db, RUN, {**ledgers, keys[0]: broken}, rules
        )  # 4 new portfolios + 1 changed old one
    assert _count(db) == before


def test_a_later_replay_that_carries_on_only_adds_the_new_days(sim):
    db, specs, rules = sim["db"], sim["specs"], sim["rules"]
    decisions = source.decisions_by_policy(
        db, rules, momentum=_momentum(sim["by_symbol"], sim["ids"]), sessions=SESSIONS
    )
    short = run_cohort(specs, SESSIONS[:10], sim["bars"], decisions, rules)
    store.persist_run(db, RUN, short, rules)
    days_before = _count(db)["sim_days"]
    longer = store.persist_run(db, RUN, sim["ledgers"], rules)  # the same run, six sessions further on
    assert longer.created["sim_days"] == _count(db)["sim_days"] - days_before > 0
    assert longer.existing["sim_days"] == days_before and longer.created.get("sim_portfolios", 0) == 0
    run = db.scalar(select(SimRun))
    assert run.last_session.isoformat() == SESSIONS[-1] and run.first_session.isoformat() == SESSIONS[0]
    assert store.persist_run(db, RUN, sim["ledgers"], rules).total_created == 0


def test_cash_is_never_negative_in_the_writer_or_in_the_database(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    key = next(iter(ledgers))
    ledger = ledgers[key]
    broke = replace(ledger, records=(replace(ledger.records[0], cash=-1.0), *ledger.records[1:]))
    with pytest.raises(store.StoreError):
        store.persist_run(db, RUN, {**ledgers, key: broke}, rules)
    noise = replace(ledger, records=(replace(ledger.records[0], cash=-1e-9), *ledger.records[1:]))
    store.persist_run(db, RUN, {key: noise}, rules)
    assert db.scalar(select(func.min(SimDay.cash))) == 0.0  # float noise is stored as zero
    portfolio = db.scalar(select(SimPortfolio))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            SimDay(
                portfolio_id=portfolio.id,
                session_date=ALL_DAYS[30],
                cash=-5.0,
                equity=1.0,
                halted=False,
                rule_version="x",
                research_only=False,
            )
        )
        db.flush()


def test_the_validation_portfolio_is_stored_but_is_in_no_denominator(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    store.persist_run(db, RUN, ledgers, rules)
    validation = [p for p in db.scalars(select(SimPortfolio)) if not p.counts_in_comparison]
    assert len(validation) == 1 and validation[0].persona_key in ledgers
    performance = store.performance_by_policy(db, RUN)
    assert sum(row["portfolios"] for row in performance.values()) == 6  # 3 policies x 2 setups, not 7
    expected = compare_by_policy(ledgers)
    for policy in Policy:
        assert performance[policy.value]["portfolios"] == expected[policy]["portfolios"] == 2
        assert performance[policy.value]["mean_return"] == pytest.approx(expected[policy]["mean_return"])
        assert performance[policy.value]["zero_trade_portfolios"] == expected[policy]["zero_trade_portfolios"]
    # a validation portfolio that did brilliantly or terribly moves no figure
    key = validation[0].persona_key
    ledger = ledgers[key]
    boosted = replace(
        ledger, records=(*ledger.records[:-1], replace(ledger.records[-1], equity=ledger.final_equity * 50))
    )
    assert compare_by_policy({**ledgers, key: boosted}) == expected
    # and the database refuses a second validation portfolio in one run
    run = db.scalar(select(SimRun))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            SimPortfolio(
                run_id=run.id,
                persona_key="syn-999",
                setup_key="setup-01",
                policy="momentum",
                balance_inr=10_000,
                start_offset=0,
                counts_in_comparison=False,
                rule_version="x",
                research_only=False,
            )
        )
        db.flush()
    two = {
        **ledgers,
        "syn-extra": replace(ledgers[key], spec=replace(ledgers[key].spec, persona_key="syn-extra")),
    }
    with pytest.raises(store.StoreError):
        store.persist_run(db, "run-two-validation", two, rules)


def test_blocked_decisions_and_the_rules_not_applied_are_stored_with_their_reasons(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    store.persist_run(db, RUN, ledgers, rules)
    by_key = {p.persona_key: p for p in db.scalars(select(SimPortfolio))}
    for key, ledger in ledgers.items():
        pid = by_key[key].id
        stored = [
            (b.session_date.isoformat(), b.seq, b.security_id, b.reason)
            for b in db.scalars(
                select(SimBlock)
                .where(SimBlock.portfolio_id == pid)
                .order_by(SimBlock.session_date, SimBlock.seq)
            )
        ]
        want = [
            (r.session, i, b.security_id, b.reason) for r in ledger.records for i, b in enumerate(r.blocks)
        ]
        assert stored == want
        assert (
            set(db.scalars(select(SimNotApplied.rule_text).where(SimNotApplied.portfolio_id == pid)))
            == set(ledger.not_applied)
            != set()
        )
    small = next(
        k
        for k, led in ledgers.items()
        if led.spec.balance_inr == 10_000 and led.spec.policy is Policy.MODEL_ONLY
    )
    assert ledgers[small].fill_count == 0  # the 10K account never trades under the settled sizing
    reasons = set(db.scalars(select(SimBlock.reason).where(SimBlock.portfolio_id == by_key[small].id)))
    assert reasons and reasons <= {
        "below_minimum_position",
        "insufficient_cash",
        "no_free_slot",
        "price_above_ladder_limit",
    }
    assert db.scalar(
        select(func.count()).select_from(SimDay).where(SimDay.portfolio_id == by_key[small].id)
    ) == len(ledgers[small].records)  # kept, every day


def test_every_fill_traces_stock_to_horizon_record_to_policy_and_rule_version(sim):
    db, ledgers, rules = sim["db"], sim["ledgers"], sim["rules"]
    store.persist_run(db, RUN, ledgers, rules)
    rows = store.trace_fills(db, RUN)
    assert len(rows) == sum(led.fill_count for led in ledgers.values()) > 0
    policy_of = {k: led.spec.policy.value for k, led in ledgers.items()}
    seen = set()
    for row in rows:
        seen.add(row.policy)
        assert row.policy == policy_of[row.persona_key] and row.rule_version == "hz-rules-v1:5D"
        if row.policy == "momentum":
            assert row.horizon_record_id is None  # momentum has no record source yet (synthetic)
            continue
        assert row.record_security_id == row.security_id and row.record_horizon_days == 5
        assert row.record_decision == "TRADE" and row.record_config_version == "hz-rules-v1"
        assert row.record_session < row.session_date  # decided at an earlier close
        assert sim["secs"][row.security_id] == row.symbol
    assert seen == {"momentum", "model_only", "brain_filtered"}
    # exits and blocks carry the same chain
    exits = db_exit_rows = list(db.scalars(select(SimExit)))
    assert exits and all(
        e.security_id and e.rule_version == "hz-rules-v1:5D" and e.policy for e in db_exit_rows
    )
    assert all(e.horizon_record_id is not None for e in exits if e.policy != "momentum")


def test_a_research_run_is_stamped_research_only_and_never_mixes_with_5d(sim):
    db, specs = sim["db"], sim["specs"]
    rules15 = TradingRules.plan_15d()
    decisions = source.decisions_by_policy(db, rules15, sessions=SESSIONS)
    ledgers15 = run_cohort(specs, SESSIONS, sim["bars"], decisions, rules15)
    store.persist_run(db, "run-15d", ledgers15, rules15)
    run = db.scalar(select(SimRun).where(SimRun.run_key == "run-15d"))
    assert (run.research_only, run.horizon_days, run.rule_version) == (True, 15, "hz-rules-v1:15D")
    assert all(p.research_only for p in db.scalars(select(SimPortfolio).where(SimPortfolio.run_id == run.id)))
    with pytest.raises(MixedRuleVersions):
        store.persist_run(
            db, "run-mixed", {**sim["ledgers"], **dict(list(ledgers15.items())[:1])}, sim["rules"]
        )


# ------------------------------------------------------------------------------------------ tenant isolation


def test_the_simulation_tables_have_no_user_or_account_link():
    allowed = {m.__tablename__ for m in SIM_MODELS} | {"securities", "horizon_records"}
    for model in SIM_MODELS:
        table = Base.metadata.tables[model.__tablename__]
        assert not {"user_id", "account_id", "owner_id", "email"} & {c.name for c in table.columns}
        assert {fk.column.table.name for fk in table.foreign_keys} <= allowed, model.__tablename__


def test_only_the_store_reads_or_writes_the_simulation_tables():
    importers = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(
                n.startswith("swing_trade_ml.db.models.simulation")
                or n.rsplit(".", 1)[-1] in {m.__name__ for m in SIM_MODELS}
                for n in names
            ):
                importers.add(path.relative_to(SRC).as_posix())
    assert importers - {"db/models/__init__.py", "simulation/store.py", "db/models/simulation.py"} == set(), (
        sorted(importers)
    )
    assert not [
        p
        for p in SRC.glob("api/**/*.py")
        if "simulation" in p.read_text(encoding="utf8")
        and "swing_trade_ml.simulation" in p.read_text(encoding="utf8")
    ]


def test_storing_a_run_creates_no_user_and_the_database_refuses_a_non_synthetic_row(sim):
    db = sim["db"]
    users = db.scalar(select(func.count()).select_from(User))
    store.persist_run(db, RUN, sim["ledgers"], sim["rules"])
    assert db.scalar(select(func.count()).select_from(User)) == users  # personas are keys, never accounts
    assert not [
        c for c in inspect(db.get_bind()).get_columns("sim_portfolios") if c["name"] in {"user_id", "email"}
    ]
    for bad in (
        "INSERT INTO sim_runs (run_key, rule_version, research_config_version, research_only, horizon_days, synthetic) VALUES ('x','v','c',false,5,false)",
    ):
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text(bad))
    run = db.scalar(select(SimRun))
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(
            SimPortfolio(
                run_id=run.id,
                persona_key="syn-888",
                setup_key="setup-01",
                policy="momentum",
                balance_inr=1,
                start_offset=0,
                counts_in_comparison=True,
                rule_version="x",
                research_only=False,
                synthetic=False,
            )
        )
        db.flush()


# ------------------------------------------------------------------------------ untraceable evidence is refused


def _model_ledger(sim):
    key = next(
        k for k, led in sim["ledgers"].items() if led.spec.policy is Policy.MODEL_ONLY and led.fill_count
    )
    return key, sim["ledgers"][key]


def _first_with(ledger, attr):
    return next(i for i, r in enumerate(ledger.records) if getattr(r, attr))


def _with_item(ledger, kind: str, record_id, security_id=None):
    """The ledger with the first fill / an added exit / an added block pointing at `record_id` (and `security_id`)."""
    i = _first_with(ledger, "fills")
    record = ledger.records[i]
    fill = record.fills[0]
    sid = fill.security_id if security_id is None else security_id
    if kind == "fill":
        record = replace(
            record, fills=(replace(fill, record_id=record_id, security_id=sid), *record.fills[1:])
        )
    elif kind == "exit":
        extra = ExitRecord(sid, fill.symbol, 1, fill.price, "stop", fill.price, False, record_id)
        record = replace(record, exits=(*record.exits, extra))
    else:
        record = replace(record, blocks=(*record.blocks, BlockRecord(sid, fill.symbol, "extra", record_id)))
    return replace(ledger, records=(*ledger.records[:i], record, *ledger.records[i + 1 :]))


@pytest.mark.parametrize("kind", ["fill", "exit", "block"])
def test_a_non_momentum_row_without_a_horizon_record_is_refused_and_nothing_is_written(sim, kind):
    db, rules = sim["db"], sim["rules"]
    key, ledger = _model_ledger(sim)
    before = _count(db)
    with pytest.raises(store.StoreError, match="horizon record"):
        store.persist_run(db, RUN, {**sim["ledgers"], key: _with_item(ledger, kind, None)}, rules)
    assert _count(db) == before


@pytest.mark.parametrize("kind", ["fill", "exit", "block"])
def test_a_record_of_another_stock_or_another_horizon_or_none_at_all_is_refused(sim, kind):
    db, rules = sim["db"], sim["rules"]
    key, ledger = _model_ledger(sim)
    fill = ledger.records[_first_with(ledger, "fills")].fills[0]
    other_stock = next(sid for sid in sim["secs"] if sid != fill.security_id)
    other_stock_record = hr.records_for(db, other_stock, view="first", horizon_days=5)[0].id
    long_record = hr.records_for(db, fill.security_id, view="first", horizon_days=10)[0].id
    before = _count(db)
    for bad in (other_stock_record, long_record, 10**9):
        with pytest.raises(store.StoreError, match="horizon record"):
            store.persist_run(db, RUN, {**sim["ledgers"], key: _with_item(ledger, kind, bad)}, rules)
        assert _count(db) == before
    # the right record is accepted
    good = _with_item(ledger, kind, fill.record_id)
    store.persist_run(db, RUN, {key: good}, rules)


def test_momentum_may_have_no_record_but_a_wrong_one_is_still_refused(sim):
    db, rules = sim["db"], sim["rules"]
    key = next(
        k for k, led in sim["ledgers"].items() if led.spec.policy is Policy.MOMENTUM and led.fill_count
    )
    ledger = sim["ledgers"][key]
    store.persist_run(
        db, RUN, {key: ledger}, rules
    )  # no record at all: fine, momentum has no record source yet
    fill = ledger.records[_first_with(ledger, "fills")].fills[0]
    other = next(sid for sid in sim["secs"] if sid != fill.security_id)
    wrong = hr.records_for(db, other, view="first", horizon_days=5)[0].id
    with pytest.raises(store.StoreError, match="horizon record"):
        store.persist_run(db, "run-momentum-wrong", {key: _with_item(ledger, "fill", wrong)}, rules)


# --------------------------------------------------------------------- a replay may not leave stored rows out


def test_a_replay_that_omits_stored_blocks_marks_exits_or_whole_days_is_refused(sim):
    db, rules = sim["db"], sim["rules"]
    key, ledger = _model_ledger(sim)
    with_exit = _with_item(ledger, "exit", ledger.records[_first_with(ledger, "fills")].fills[0].record_id)
    store.persist_run(db, RUN, {**sim["ledgers"], key: with_exit}, rules)
    before = _count(db)
    blocks_i = _first_with(ledger, "blocks")
    marks_i = _first_with(ledger, "positions")
    exits_i = _first_with(with_exit, "exits")

    def drop(led, i, **fields):
        return replace(
            led, records=(*led.records[:i], replace(led.records[i], **fields), *led.records[i + 1 :])
        )

    omissions = {
        "blocks": drop(with_exit, blocks_i, blocks=()),
        "marks": drop(with_exit, marks_i, positions=()),
        "exits": drop(with_exit, exits_i, exits=()),
        "fills": drop(with_exit, _first_with(with_exit, "fills"), fills=()),
        "a day": replace(with_exit, records=with_exit.records[:-1]),
    }
    for what, short in omissions.items():
        with pytest.raises(store.ReplayMismatchError, match=r"leaves out"):
            store.persist_run(db, RUN, {key: short}, rules)
        assert _count(db) == before, what
    assert store.persist_run(db, RUN, {key: with_exit}, rules).total_created == 0
