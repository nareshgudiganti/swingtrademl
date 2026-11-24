# ruff: noqa: E501  (long plain-English test text)
"""#321 the runner: stored horizon records and stored candles -> the 99+1 cohort -> persisted rows, idempotently.

Uses the synthetic world of the end-to-end test (identity writer -> horizon records), plus synthetic daily candles in the
candles table, so the runner reads everything from the database. Every write rolls back with the test."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models import (
    Instrument,
    SimBlock,
    SimDay,
    SimExit,
    SimFill,
    SimMark,
    SimNotApplied,
    SimPortfolio,
    SimRun,
)
from swing_trade_ml.db.models.market import Candle
from swing_trade_ml.simulation import runner, source, store
from test_p0_end_to_end import MODEL_5D, MODEL_15D, SESSIONS, world  # noqa: F401 - `world` is a fixture

SIM_MODELS = (SimRun, SimPortfolio, SimNotApplied, SimDay, SimFill, SimExit, SimBlock, SimMark)
RUN = "runner-test"
FIRST_12 = SESSIONS[:12]


def _count(db) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in SIM_MODELS}


@pytest.fixture()
def stored(world):  # noqa: F811
    """The world's prices written as daily candles (IST midnight), so the runner has to read them back."""
    db = world["db"]
    instruments = {
        i.tradingsymbol: i.id
        for i in db.scalars(select(Instrument).where(Instrument.tradingsymbol.like("P0%")))
    }
    for symbol, by_session in world["by_symbol"].items():
        for session, bar in by_session.items():
            db.add(
                Candle(
                    instrument_id=instruments[symbol],
                    interval="day",
                    ts=datetime.fromisoformat(session).replace(tzinfo=IST),
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=1000,
                )
            )
    db.flush()
    # Momentum's declared universe: the six stocks, as security ids (never "whatever the models scored")
    return {**world, "universe": [sid for symbol, sid in world["ids"].items() if symbol != "P0ONLY"]}


def test_stored_records_and_candles_become_persisted_rows_that_trace_to_the_records(stored):
    db = stored["db"]
    report = runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    assert (report.portfolios, report.compared, report.validation) == (100, 99, 1)
    assert report.rule_version == "hz-rules-v1:5D" and report.fills > 0 and report.picks["model_only"] > 0
    counts = _count(db)
    assert counts["sim_portfolios"] == 100
    assert counts["sim_fills"] == report.fills and counts["sim_blocks"] == report.blocks
    rows = store.trace_fills(db, RUN)
    assert len(rows) == report.fills
    traced = [r for r in rows if r.policy != "momentum"]
    assert traced and all(
        r.record_security_id == r.security_id and r.record_horizon_days == 5 and r.record_decision == "TRADE"
        for r in traced
    )
    assert all(r.price > 0 for r in rows)  # prices were read back from the candle table, matched by security


def test_a_second_call_adds_nothing_and_a_longer_call_adds_only_the_new_days(stored):
    db = stored["db"]
    first = runner.run_and_persist(
        db, run_key=RUN, sessions=FIRST_12, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    before = _count(db)
    again = runner.run_and_persist(
        db, run_key=RUN, sessions=FIRST_12, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    assert again.rows_created == 0 and _count(db) == before and again.run_id == first.run_id
    longer = runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    assert longer.created.get("sim_portfolios", 0) == 0 and longer.created["sim_days"] > 0
    assert longer.existing["sim_days"] == before["sim_days"]
    assert _count(db)["sim_days"] == before["sim_days"] + longer.created["sim_days"]
    assert (
        runner.run_and_persist(
            db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
        ).rows_created
        == 0
    )


def test_10d_and_15d_records_are_ignored_by_a_5d_run(stored):
    db = stored["db"]
    runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    only_long = stored["only_long"]  # a stock with 10D and 15D records only, scored 0.95 every day
    for model in (SimFill, SimBlock, SimExit, SimMark):
        assert not db.scalar(select(func.count()).select_from(model).where(model.security_id == only_long))
    assert {r.record_horizon_days for r in store.trace_fills(db, RUN) if r.horizon_record_id} == {5}
    with pytest.raises(runner.RunnerError, match="research-only"):
        runner.run_and_persist(
            db,
            run_key="runner-15d",
            sessions=SESSIONS,
            models=[MODEL_15D],
            momentum_universe=stored["universe"],
            rule_version="hz-rules-v1/15D",
        )
    research = runner.run_and_persist(
        db,
        run_key="runner-15d",
        sessions=SESSIONS,
        models=[MODEL_15D],
        momentum_universe=stored["universe"],
        rule_version="hz-rules-v1:15D",
        allow_research=True,
    )
    assert research.rule_version == "hz-rules-v1:15D" and research.picks["model_only"] > 0
    assert db.scalar(select(SimRun.research_only).where(SimRun.run_key == "runner-15d")) is True


def test_zero_trade_accounts_are_present_with_a_row_every_day_and_reasons(stored):
    db = stored["db"]
    report = runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    assert (
        report.zero_trade_portfolios >= 12
    )  # at least the 10K and 25K setups under the two record-driven policies
    small = list(
        db.scalars(
            select(SimPortfolio).where(
                SimPortfolio.balance_inr.in_((10_000, 25_000)), SimPortfolio.policy == "model_only"
            )
        )
    )
    assert len(small) == 6
    for portfolio in small:
        assert (
            db.scalar(select(func.count()).select_from(SimFill).where(SimFill.portfolio_id == portfolio.id))
            == 0
        )
        assert (
            db.scalar(select(func.count()).select_from(SimDay).where(SimDay.portfolio_id == portfolio.id)) > 0
        )
        assert (
            db.scalar(select(func.count()).select_from(SimBlock).where(SimBlock.portfolio_id == portfolio.id))
            > 0
        )
    assert any("momentum" in note for note in report.notes)  # stated plainly: no ranking source yet


def test_unknown_rule_and_bad_sessions_are_refused_before_anything_is_written(stored):
    db = stored["db"]
    before = _count(db)
    with pytest.raises(runner.RunnerError, match="unknown rule"):
        runner.run_and_persist(
            db,
            run_key=RUN,
            sessions=SESSIONS,
            models=[MODEL_5D],
            momentum_universe=stored["universe"],
            rule_version="hz-rules-v9/5D",
        )
    for bad in (
        [],
        ["2026-12-05"],
        ["2026-12-02", "2026-12-01"],
        ["not-a-date"],
    ):  # empty, a Saturday, unsorted, junk
        with pytest.raises(runner.RunnerError):
            runner.run_and_persist(
                db, run_key=RUN, sessions=bad, models=[MODEL_5D], momentum_universe=stored["universe"]
            )
    assert _count(db) == before


# ------------------------------------------------------------------------------------------ the admin command


def test_the_command_refuses_a_database_that_is_not_a_test_database():
    runner.check_database("postgresql+psycopg://u@localhost:5433/swing_trade_ml_e2e_test")
    for url in (
        "postgresql+psycopg://u@localhost:5433/swing_trade_ml",
        "postgresql+psycopg://u@db.example.com/prod",
        "postgresql+psycopg://u@db.example.com/swing_trade_ml_test",  # a *_test name on a remote host
        "postgresql+psycopg://u@localhost/swing_trade_ml_test?host=db.example.com",  # a rerouting query
        "",
        None,
    ):
        with pytest.raises(runner.RunnerError):
            runner.check_database(url)
    runner.check_database(
        "postgresql+psycopg://u@localhost/swing_trade_ml", allow=True
    )  # the owner's explicit flag
    argv = [*CLI, "--run-key", "x", "--from", "2026-12-01", "--to", "2026-12-05"]
    assert runner.main(argv, database_url="postgresql+psycopg://u@localhost/swing_trade_ml") == 2


CLI = ["--model", MODEL_5D, "--momentum-universe", "P0E0,P0E1"]


def test_the_command_dry_run_reports_and_keeps_nothing(capsys, db_session, monkeypatch):
    seen = {}

    def fake_resolve(db, spec, on):
        from swing_trade_ml.services.identity.writer import create_security

        seen.update(spec=spec, on=on)
        # two securities made inside the command's own session: the dry run rolls them back with everything else
        ids = (create_security(db, name="CLI TEST A"), create_security(db, name="CLI TEST B"))
        db.flush()
        return tuple(sorted(ids))

    monkeypatch.setattr(runner, "resolve_universe", fake_resolve)
    code = runner.main(
        [*CLI, "--run-key", "cli-dry", "--from", "2026-12-01", "--to", "2026-12-04", "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0 and "dry run: nothing was kept" in out and "(99 compared, 1 validation)" in out
    assert seen == {"spec": "P0E0,P0E1", "on": date(2026, 12, 1)}  # resolved on the run's first session
    assert db_session.scalar(select(func.count()).select_from(SimRun).where(SimRun.run_key == "cli-dry")) == 0
    assert runner.main([*CLI, "--run-key", "x", "--from", "2026-12-05", "--to", "2026-12-01"]) == 2


# ------------------------------------------------------------------------------------------ the run names its model


def _challenger(db, symbol, score):
    from swing_trade_ml.brain.horizons import HorizonStore, ModelOutput, run_all_horizons
    from swing_trade_ml.services import horizon_records as hr
    from test_p0_end_to_end import ALL_DAYS, RECORDED

    for day in RECORDED:
        output = ModelOutput(
            model_name="challenger_h5",
            model_version="v9.1",
            forecast_horizon_sessions=5,
            role="final",
            symbol=symbol,
            input_session=day,
            input_close=100.0,
            score=score,
        )
        record = run_all_horizons(
            day, [output], ALL_DAYS, HorizonStore(), symbol=symbol, research_caller=True
        )[5]
        hr.save_for_symbol(db, record, scan_key=f"chal:{day}", run_ref=f"chal-{day}")
    db.flush()


def test_a_run_must_name_its_model_and_two_models_on_one_stock_refuse_the_run(stored):
    db = stored["db"]
    with pytest.raises(TypeError):
        runner.run_and_persist(db, run_key=RUN, sessions=SESSIONS)
    with pytest.raises(source.ModelNotNamedError):
        runner.run_and_persist(
            db, run_key=RUN, sessions=SESSIONS, models=[], momentum_universe=stored["universe"]
        )
    _challenger(db, "P0E0", 0.97)  # the main model also scores P0E0 on the same sessions
    before = _count(db)
    with pytest.raises(source.AmbiguousRecordsError, match="name one model"):
        runner.run_and_persist(
            db,
            run_key=RUN,
            sessions=SESSIONS,
            models=[MODEL_5D, "challenger_h5"],
            momentum_universe=stored["universe"],
        )
    assert _count(db) == before  # nothing was written
    report = runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
    )
    assert report.models == (MODEL_5D,) and f"models named: {MODEL_5D}" in report.summary()
    assert {
        r.horizon_record_id for r in store.trace_fills(db, RUN) if r.horizon_record_id
    }  # the main model's records only


def test_the_command_needs_a_model_and_reads_name_at_version():
    with pytest.raises(SystemExit):
        runner.main(
            ["--run-key", "x", "--from", "2026-12-01", "--to", "2026-12-04", "--momentum-universe", "A"]
        )
    with pytest.raises(SystemExit):  # and the universe is required too
        runner.main(["--run-key", "x", "--from", "2026-12-01", "--to", "2026-12-04", "--model", MODEL_5D])
    assert runner.parse_model("a_model") == source.ModelRef("a_model", None)
    assert runner.parse_model("a_model@v2.1") == source.ModelRef("a_model", "v2.1")
    with pytest.raises(runner.RunnerError):
        runner.parse_model("@v1")


# ------------------------------------------------------------------------------ Momentum's declared universe


def test_the_run_must_declare_momentums_universe_and_it_is_never_defaulted(stored):
    db = stored["db"]
    with pytest.raises(TypeError):  # no default: the argument is required
        runner.run_and_persist(db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D])
    before = _count(db)
    for bad in ([], None, [1, 1], [0], [-3], ["P0E0"], [True]):
        with pytest.raises(runner.RunnerError):
            runner.run_and_persist(
                db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=bad
            )
    assert _count(db) == before


def test_the_declared_universe_is_stored_on_the_run_and_limits_what_momentum_ranks(stored):
    db = stored["db"]
    first_three = stored["universe"][:3]
    runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=first_three
    )
    run = db.scalar(select(SimRun).where(SimRun.run_key == RUN))
    text, sha = store.universe_fingerprint(first_three)
    assert (
        run.momentum_universe == text == str(sorted(first_three)).replace(" ", "")
        and run.momentum_universe_sha256 == sha
    )
    assert len(sha) == 64
    # momentum buys and blocks only stocks inside the universe it declared
    for model in (SimFill, SimBlock):
        ids = set(db.scalars(select(model.security_id).where(model.policy == "momentum")))
        assert ids <= set(first_three)
    # the order of the ids does not change the run; the same call again adds nothing
    again = runner.run_and_persist(
        db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=list(reversed(first_three))
    )
    assert again.rows_created == 0
    # another universe under the same run key is a different run: refused, nothing written
    before = _count(db)
    with pytest.raises(store.ReplayMismatchError):
        runner.run_and_persist(
            db, run_key=RUN, sessions=SESSIONS, models=[MODEL_5D], momentum_universe=stored["universe"]
        )
    assert _count(db) == before


def test_a_universe_of_symbols_is_resolved_on_the_first_session_and_unknown_symbols_refuse(stored, tmp_path):
    db, ids = stored["db"], stored["ids"]
    first = date.fromisoformat(SESSIONS[0])
    assert runner.resolve_universe(db, "P0E0, P0E1", first) == tuple(sorted((ids["P0E0"], ids["P0E1"])))
    listing = tmp_path / "universe.txt"
    listing.write_text("# my momentum list\nP0E2\nP0E3 , P0E4  # one more\n\n", encoding="utf-8")
    assert runner.resolve_universe(db, str(listing), first) == tuple(
        sorted(ids[s] for s in ("P0E2", "P0E3", "P0E4"))
    )
    for bad in ("P0E0,NOSUCHSTOCK", "", "  ,  ", "P0E0,P0E0", "p0e1,P0E1"):
        with pytest.raises(runner.RunnerError):
            runner.resolve_universe(db, bad, first)
    with pytest.raises(runner.RunnerError, match="NOSUCHSTOCK"):
        runner.resolve_universe(db, "NOSUCHSTOCK", first)
