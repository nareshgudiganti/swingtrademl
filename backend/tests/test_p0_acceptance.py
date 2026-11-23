# ruff: noqa: E501  (long plain-English test text)
"""P0 acceptance: ONE run from real-shaped 5-session predictions to stored simulation results.

    prediction rows (as the scan writes them) -> canonical security_id (identity) -> 5D horizon records with
    model / version / prediction provenance (the nightly writer, called directly) -> the 100 simulated portfolios fed
    from the STORED records -> results persisted -> a replay adds nothing.

What is real here: the identity tables and writer, `predictions` and `ml_models` rows in the shape the scan writes, the
nightly writer and the horizon-record table, the research config, the cohort matrix, the ledger (the app's limits, costs
and sizing) and the simulation store.

What is SYNTHETIC: the stocks' prices and model scores are invented (the symbols look like NSE names but no market data
is used), there is no ISIN, the momentum policy has no pick source (so its 33 portfolios hold cash), and the persisted
simulation rows are flagged synthetic. Nothing is sent, nothing trades, no job is enabled, and every write rolls back
with the test.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.brain.horizons import run_horizon
from swing_trade_ml.core.market_session import IST, is_trading_day
from swing_trade_ml.db.models import SimBlock, SimExit, SimFill, SimNotApplied, SimPortfolio, SimRun
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.services import horizon_nightly as hn
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import resolve, writer
from swing_trade_ml.simulation import runner, source, store
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Bar
from swing_trade_ml.simulation.rules import TradingRules
from swing_trade_ml.simulation.source import AmbiguousRecordsError, ModelNotNamedError, ModelRef

DAYS = tuple(d for i in range(40) if (d := date(2026, 12, 1) + timedelta(days=i)).weekday() < 5)[:16]
SESSIONS = tuple(d.isoformat() for d in DAYS)
RENAME_AT = 6  # OLDCO becomes NEWCO from the 7th session
V2_FROM = 8  # the 5-session model is replaced by version v2 from the 9th session
STALE_AFTER = 2  # STALECO has candles only for the first three sessions
RUN_KEY = "p0-accept-1"
_tokens = iter(range(430_000, 430_900))

# symbol -> the model's (synthetic) score for it, every session. >= 0.80 is TRADE, >= 0.60 WATCH, else WAIT.
SCORES = {
    "RELIANCE": 0.90,
    "TCS": 0.88,
    "HDFCBANK": 0.86,
    "INFY": 0.84,
    "ICICIBANK": 0.70,  # WATCH
    "SBIN": 0.30,  # WAIT
    "ITC": 0.83,  # not linked to an identity before the first nightly pass
    "OLDCO": 0.87,  # renamed NEWCO from session 7
    "STALECO": 0.95,  # no candles after the third session
}
UNLINKED = {"ITC"}
LONG_ONLY = "LONGONLY"  # only 10-session and 15-session models score it


def _bars(seed: int, count: int) -> list[Bar]:
    rng = random.Random(seed)
    out, last = [], 100.0 + 7 * seed
    for _ in range(count):
        o = last * (1 + rng.uniform(-0.01, 0.01))
        c = o * (1 + rng.uniform(-0.03, 0.03))
        out.append(Bar(o, max(o, c) * 1.012, min(o, c) * 0.988, c))
        last = c
    return out


def _quiet_bars(count: int) -> list[Bar]:
    return [Bar(100.0, 100.4, 99.6, 100.0 + 0.1 * i) for i in range(count)]


def _model(db, name: str, version: str, horizon: int, role: str, status: str = "ACTIVE") -> MLModel:
    row = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        prediction_horizon_days=horizon,
        label_kind="endpoint" if horizon == 5 else "barrier",
        model_role=role,
        feature_names=["a", "b"],
        training_symbols=["X"],
    )
    db.add(row)
    db.flush()
    return row


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=IST)  # daily candles are stamped IST midnight


@pytest.fixture()
def world(db_session):
    """Stocks, models, bars and one prediction row per model, stock and session, written the way the scan writes them."""
    assert all(is_trading_day(d) for d in DAYS), "the fixture window must be exchange sessions"
    db = db_session
    instruments: dict[str, Instrument] = {}
    for symbol in (*SCORES, LONG_ONLY):
        inst = Instrument(
            instrument_token=next(_tokens),
            tradingsymbol=symbol,
            name=f"{symbol.title()} Limited",
            exchange="NSE",
            instrument_type="EQ",
            is_active=True,
            is_watchlisted=True,  # followed: a session it is not scored on becomes an explicit no-data record
        )
        db.add(inst)
        db.flush()
        if symbol not in UNLINKED:
            writer.ensure_for_instrument(db, inst)
        instruments[symbol] = inst

    m5a = _model(db, "swing_5d", "v1", 5, "final")  # ACTIVE until session 8, then replaced by v2
    m5b = _model(db, "swing_5d", "v2", 5, "final", status="TRAINED")
    m5prod = _model(db, "swing_prod_5d", "v1", 5, "prod")  # a production-marked model: D1 not decided, so no decision
    m10 = _model(db, "td_10d", "v1", 10, "final")
    m15 = _model(db, "sl_15d", "v1", 15, "final")

    bars_by_symbol: dict[str, list[Bar]] = {}
    for k, symbol in enumerate((*SCORES, LONG_ONLY)):
        count = STALE_AFTER + 1 if symbol == "STALECO" else len(DAYS)
        # the stale stock's few candles are quiet ones (no stop or target touched), so a holder is still in it when they stop
        bars_by_symbol[symbol] = _quiet_bars(count) if symbol == "STALECO" else _bars(100 + k, count)

    def predict(model: MLModel, symbol: str, i: int, score: float) -> Prediction:
        bar = bars_by_symbol[symbol][i]
        row = Prediction(
            model_id=model.id,
            instrument_id=instruments[symbol].id,
            ts=_stamp(DAYS[i]),
            predicted_class=1 if score >= 0.5 else 0,
            probability=score,
            price_at_prediction=bar.close,
            features={"scan": "p0-accept"},
            label_kind="endpoint" if model.prediction_horizon_days == 5 else "barrier",
        )
        db.add(row)
        return row

    for i in range(len(DAYS)):
        five = m5a if i < V2_FROM else m5b
        for symbol, score in SCORES.items():
            if symbol == "STALECO" and i > STALE_AFTER:
                continue  # the candle went stale: no bar and so no prediction
            predict(five, symbol, i, score if i < V2_FROM else min(0.99, score + 0.01))
        predict(m5prod, "RELIANCE", i, 0.91)
        for symbol in ("RELIANCE", LONG_ONLY):
            predict(m10, symbol, i, 0.95)
            predict(m15, symbol, i, 0.95)
    for symbol, bars in bars_by_symbol.items():  # stored daily candles: STALECO has only its first three
        for i, bar in enumerate(bars):
            db.add(
                Candle(
                    instrument_id=instruments[symbol].id,
                    interval="day",
                    ts=_stamp(DAYS[i]),
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=100_000,
                )
            )
    db.flush()
    return {
        "db": db,
        "instruments": instruments,
        "models": {"m5a": m5a, "m5b": m5b, "m5prod": m5prod, "m10": m10, "m15": m15},
        "bars_by_symbol": bars_by_symbol,
    }


def _nightly(world, indices=None) -> list[hn.DaySummary]:
    """The nightly writer, called directly, session by session. OLDCO is renamed between two sessions."""
    db, out, models = world["db"], [], world["models"]
    for i in indices if indices is not None else range(len(DAYS)):
        models["m5a"].status = "ACTIVE" if i < V2_FROM else "ARCHIVED"  # the model in force that night
        models["m5b"].status = "ACTIVE" if i >= V2_FROM else "TRAINED"
        db.flush()
        if i == RENAME_AT and "NEWCO" not in world.get("renamed", ""):
            inst = world["instruments"]["OLDCO"]
            inst.tradingsymbol = "NEWCO"  # the exchange renamed the stock; the token and the company are the same
            db.flush()
            writer.set_symbol(db, resolve(db, token=inst.instrument_token), "NEWCO", DAYS[RENAME_AT])
            world["renamed"] = "NEWCO"
        out.append(hn.record_day(db, DAYS[i], finalize=True))  # the day's final pass: gaps become explicit records
    return out


def _five_rows(db) -> list[HorizonRecordRow]:
    db.expire_all()
    return list(db.scalars(select(HorizonRecordRow).order_by(HorizonRecordRow.id)))


MODELS = [ModelRef("swing_5d")]  # the run names its model: both versions of it (v1, then v2) decide, one per session


# ------------------------------------------------------------------------------- 1. predictions -> identity -> records


def test_real_shaped_predictions_become_five_day_records_with_exact_provenance(world):
    db = world["db"]
    summaries = _nightly(world)
    rows = _five_rows(db)
    five_predictions = db.scalars(
        select(Prediction).join(MLModel, MLModel.id == Prediction.model_id).where(MLModel.prediction_horizon_days == 5)
    ).all()
    from_prediction = [r for r in rows if r.run_ref.startswith("prediction:")]
    no_data = [r for r in rows if r.run_ref == "no-data"]
    assert len(from_prediction) == len(five_predictions) > 100  # one record per stored 5-session prediction
    assert sum(s.recorded for s in summaries) == len(from_prediction) and sum(s.no_data for s in summaries) == len(no_data)
    assert sum(s.refused + s.unresolved for s in summaries) == 0 and not any(s.zero_records for s in summaries)
    assert sum(s.linked for s in summaries) == 1  # ITC was not in the identity tables: linked by the first pass, once
    assert {r.horizon_days for r in rows} == {5}  # no 10-session or 15-session prediction became a record
    assert all(r.research_only is False and r.research_config_version == "hz-rules-v1" for r in rows)
    for row in from_prediction:  # every record names the exact prediction row, model and version it came from
        kind, _, pid = row.run_ref.partition(":")
        pred = db.get(Prediction, int(pid))
        model = db.get(MLModel, row.model_id)
        assert kind == "prediction" and pred.model_id == model.id
        assert (row.model_name, row.model_version) == (model.name, model.version)
        assert row.session_date == pred.ts.astimezone(IST).date() and row.input_cutoff == pred.ts
        assert row.scan_key == f"h5:{row.session_date}"
        # a decided record carries the score and the close it was decided on; a "no decision" one keeps only the link
        assert row.input_close == (pred.price_at_prediction if row.decision != "NO_DECISION" else None)
        assert row.score == (pred.probability if row.decision != "NO_DECISION" else None)
        assert row.security_id == resolve(db, token=db.get(Instrument, pred.instrument_id).instrument_token)
        assert row.evaluation_due_session > row.session_date
    models = world["models"]
    by_model = {m: {r.model_version for r in rows if r.model_id == models[m].id} for m in ("m5a", "m5b", "m5prod")}
    assert by_model == {"m5a": {"v1"}, "m5b": {"v2"}, "m5prod": {"v1"}}  # the version change is a new line, not a revision
    assert all(r.revision == 1 for r in rows)
    prod = [r for r in rows if r.model_id == models["m5prod"].id]
    assert prod and all(r.decision == "NO_DECISION" and r.score is None for r in prod)  # D1 pending: never a pick
    assert all(r.decision == "NO_DECISION" and r.score is None and r.model_name for r in no_data)  # a gap names its model
    assert not any(r.model_id == models["m5b"].id for r in rows if r.session_date < DAYS[V2_FROM])  # v2 was not in force


def test_a_second_pass_over_the_same_predictions_adds_nothing(world):
    db = world["db"]
    _nightly(world)
    before = len(_five_rows(db))
    again = _nightly(world)
    assert sum(s.recorded for s in again) == 0 and sum(s.unchanged for s in again) == before
    assert len(_five_rows(db)) == before


def test_a_rename_keeps_one_security_and_records_on_both_sides_of_it(world):
    db = world["db"]
    _nightly(world)
    inst = world["instruments"]["OLDCO"]
    sid = resolve(db, token=inst.instrument_token)
    assert sid == resolve(db, symbol="OLDCO", on_date=DAYS[0]) == resolve(db, symbol="NEWCO", on_date=DAYS[-1])
    rows = [r for r in _five_rows(db) if r.security_id == sid]
    scored = [r for r in rows if r.run_ref.startswith("prediction:")]
    assert {r.session_date for r in scored} == set(DAYS) and len(scored) == len(DAYS)
    assert source.symbol_on(db, sid, DAYS[RENAME_AT - 1]) == "OLDCO"
    assert source.symbol_on(db, sid, DAYS[RENAME_AT]) == "NEWCO"
    assert len({r.security_id for r in rows}) == 1


def test_the_stale_stock_has_an_explicit_no_data_record_after_its_candles_stop(world):
    db = world["db"]
    _nightly(world)
    sid = resolve(db, token=world["instruments"]["STALECO"].instrument_token)
    rows = [r for r in _five_rows(db) if r.security_id == sid and r.model_id == world["models"]["m5a"].id]
    scored = {r.session_date for r in rows if r.run_ref.startswith("prediction:")}
    assert scored == set(DAYS[: STALE_AFTER + 1])  # no score is invented after the candles stop
    gaps = [r for r in rows if r.run_ref == "no-data"]
    assert gaps and all(r.decision == "NO_DECISION" and r.score is None for r in gaps)
    assert all(f"stale candle {DAYS[STALE_AFTER]}" in r.reason for r in gaps)  # the gap says why, and since when


# ------------------------------------------------------------------------------- 2. the 10D / 15D gates


def test_ten_and_fifteen_day_research_records_never_reach_a_product_reader_or_a_5d_portfolio(world):
    db, models = world["db"], world["models"]
    _nightly(world)
    long_id = resolve(db, token=world["instruments"][LONG_ONLY].instrument_token)
    assert long_id is not None
    for horizon, name in ((10, "m10"), (15, "m15")):  # a research caller stores them, as the research lanes do
        out = [
            hn.model_output(models[name], p, world["instruments"][LONG_ONLY], DAYS[3])
            for p in db.scalars(select(Prediction).where(Prediction.model_id == models[name].id)).all()
            if p.instrument_id == world["instruments"][LONG_ONLY].id and p.ts == _stamp(DAYS[3])
        ]
        record = run_horizon(horizon, out, DAYS[3], hn.sessions_from(DAYS[3], 20), symbol=LONG_ONLY, research_caller=True)
        hr.save_record(db, record, security_id=long_id, model_id=models[name].id)
    assert {r.horizon_days for r in hr.records_for(db, long_id) if r.horizon_days != 5} == {10, 15}  # stored, as research
    product = hr.product_records(db, long_id)  # a customer or Brain reader sees only the explicit 5D gaps
    assert product and {r.horizon_days for r in product} == {5} and {r.decision for r in product} == {"NO_DECISION"}
    rules5 = TradingRules.plan_5d()
    seen_long = [r for r in source.read_records(db, rules5, models=MODELS) if r.security_id == long_id]
    assert seen_long and {r.decision for r in seen_long} == {"NO_DECISION"}  # only explicit gaps, never a decision
    assert {r.horizon_days for r in seen_long} == {5}  # the 10D and 15D research rows are not read
    decisions = source.decisions_by_policy(db, rules5, models=MODELS, sessions=SESSIONS)
    picked = {c.security_id for pol in decisions.values() for picks in pol.values() for c in picks}
    assert long_id not in picked
    default_caller = run_horizon(
        10, [hn.model_output(models["m10"], db.scalars(select(Prediction).where(Prediction.model_id == models["m10"].id)).first(), world["instruments"]["RELIANCE"], DAYS[0])],
        DAYS[0], hn.sessions_from(DAYS[0], 20), symbol="RELIANCE",
    )
    assert default_caller.decision == "NO_DECISION"  # a non-research caller never gets a TRADE word for 10D


# ------------------------------------------------------------------------------- 3. stored records -> 100 portfolios
#
# Momentum is OUT OF SCOPE here: it has no verified ranking source yet (Developer-1 is making `momentum_universe`
# required on feat/321-momentum-picks). The runner is called without momentum picks, so its 33 portfolios make no trades;
# they are still stored, and this test only asserts that. Once that branch lands, give it its own acceptance case.


def _run(world, key: str = RUN_KEY, **kwargs):
    """The real caller: stored records and stored candles in, 100 stored portfolios out. Does not commit."""
    kwargs.setdefault("models", MODELS)
    return runner.run_and_persist(world["db"], run_key=key, sessions=SESSIONS, **kwargs)


def _sim_counts(db) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in (SimRun, SimPortfolio, SimFill, SimExit, SimBlock)}


@pytest.fixture()
def simulated(world):
    _nightly(world)
    report = _run(world)
    return {**world, "report": report, "rules": TradingRules.plan_5d()}


def test_the_hundred_portfolios_are_fed_from_stored_records_only(simulated):
    db, report, rules = simulated["db"], simulated["report"], simulated["rules"]
    assert (report.portfolios, report.compared, report.validation) == (100, 99, 1)
    assert report.rule_version == "hz-rules-v1:5D" and report.models == ("swing_5d",)
    decisions = source.decisions_by_policy(db, rules, models=MODELS, sessions=SESSIONS)
    prod_id = simulated["models"]["m5prod"].id
    for policy in (Policy.MODEL_ONLY, Policy.BRAIN_FILTERED):
        for picks in decisions[policy].values():
            for cand in picks:
                row = db.get(HorizonRecordRow, cand.record_id)  # every pick is a stored first-revision record
                assert row.horizon_days == 5 and row.research_only is False and row.revision == 1
                assert row.model_id != prod_id and row.model_name == "swing_5d"
                assert row.security_id == cand.security_id and cand.symbol == source.symbol_on(db, cand.security_id, row.session_date)
    assert report.picks["momentum"] == 0 and report.picks["model_only"] > 0 and report.picks["brain_filtered"] >= report.picks["model_only"]
    assert any("momentum" in note for note in report.notes)  # the runner says momentum has no source
    perf = store.performance_by_policy(db, RUN_KEY)
    assert {p: row["portfolios"] for p, row in perf.items()} == {"momentum": 33, "model_only": 33, "brain_filtered": 33}
    assert perf["momentum"]["zero_trade_portfolios"] == 33 and perf["model_only"]["zero_trade_portfolios"] < 33
    assert report.fills > 0 and report.blocks > 0


def test_missing_stale_and_blocked_stay_explicit_in_the_stored_run(simulated):
    db = simulated["db"]
    stale_sid = resolve(db, token=simulated["instruments"]["STALECO"].instrument_token)
    long_id = resolve(db, token=simulated["instruments"][LONG_ONLY].instrument_token)
    stale_exits = db.scalars(select(SimExit).where(SimExit.security_id == stale_sid, SimExit.stale.is_(True))).all()
    assert stale_exits  # sold at the last known close and flagged stale, never at an invented price
    reasons = set(db.scalars(select(SimBlock.reason)))
    assert "no_price" in reasons  # a pick on the stale stock with no stored candle to buy at is a recorded block
    assert {"held_back: brain check: WATCH", "held_back: brain check: WAIT"} <= reasons
    assert "below_minimum_position" in reasons  # the small accounts' zero-trade reason
    assert db.scalar(select(func.count()).select_from(SimNotApplied)) > 0  # inputs the run did not have are listed
    for table in (SimFill, SimBlock, SimExit):
        assert db.scalar(select(func.count()).select_from(table).where(table.security_id == long_id)) == 0


# ------------------------------------------------------------------------------- 4. persisted, traceable, repeatable


def test_results_are_persisted_traced_to_the_prediction_and_a_replay_adds_nothing(simulated):
    db, report = simulated["db"], simulated["report"]
    assert report.rows_created > 0
    run = db.scalar(select(SimRun).where(SimRun.run_key == RUN_KEY))
    assert (run.rule_version, run.horizon_days, run.synthetic, run.research_only) == ("hz-rules-v1:5D", 5, True, False)
    fills = db.scalar(select(func.count()).select_from(SimFill))
    assert fills == report.fills > 0
    rows = store.trace_fills(db, RUN_KEY)
    assert len(rows) == fills
    traced = 0
    for row in rows:
        if row.policy == "momentum":
            continue
        record = db.get(HorizonRecordRow, row.horizon_record_id)
        pred = db.get(Prediction, int(record.run_ref.split(":")[1]))  # fill -> record -> the prediction row of the scan
        model = db.get(MLModel, pred.model_id)
        assert row.record_decision == "TRADE" and row.record_horizon_days == 5 and row.rule_version == "hz-rules-v1:5D"
        assert record.security_id == row.security_id and (record.model_id, record.model_version) == (model.id, model.version)
        assert model.prediction_horizon_days == 5 and model.model_role == "final" and model.name == "swing_5d"
        assert row.record_session < row.session_date
        traced += 1
    assert traced > 50
    before = (_sim_counts(db), len(_five_rows(db)))
    again = _run(simulated)
    assert again.rows_created == 0 and again.run_id == report.run_id
    assert hn.record_day(db, DAYS[0]).recorded == 0  # re-running the nightly writer on a stored day adds no record either
    assert (_sim_counts(db), len(_five_rows(db))) == before


def test_a_changed_prediction_never_rewrites_what_a_stored_run_decided(simulated):
    db, rules = simulated["db"], simulated["rules"]
    pred = db.scalars(select(Prediction).where(Prediction.model_id == simulated["models"]["m5b"].id)).first()  # in force at the end
    pred.probability = 0.05  # the predictions table can be overwritten by a re-score (#355)
    db.flush()
    hn.record_day(db, pred.ts.astimezone(IST).date())
    revised = [r for r in _five_rows(db) if r.revision == 2]
    assert revised and revised[0].score == 0.05  # the re-score is kept as revision 2 ...
    decisions = source.decisions_by_policy(db, rules, models=MODELS, sessions=SESSIONS)  # ... and the run still reads revision 1
    assert all(db.get(HorizonRecordRow, c.record_id).revision == 1 for pol in decisions.values() for picks in pol.values() for c in picks)
    assert _run(simulated).rows_created == 0


def test_two_models_deciding_one_stock_and_session_refuse_the_run_and_write_nothing(world):
    db = world["db"]
    _nightly(world)
    alt = _model(db, "swing_5d_alt", "v1", 5, "final")  # a second 5-session model that also scores RELIANCE on one day
    inst = world["instruments"]["RELIANCE"]
    db.add(
        Prediction(model_id=alt.id, instrument_id=inst.id, ts=_stamp(DAYS[3]), predicted_class=1, probability=0.97,
                   price_at_prediction=100.0, features={}, label_kind="endpoint")
    )
    db.flush()
    assert hn.record_day(db, DAYS[3]).recorded == 1
    before = _sim_counts(db)
    with pytest.raises(AmbiguousRecordsError):  # two decisive records for one stock and session: never resolved by picking
        _run(world, models=[ModelRef("swing_5d"), ModelRef("swing_5d_alt")])
    assert _sim_counts(db) == before == {"sim_runs": 0, "sim_portfolios": 0, "sim_fills": 0, "sim_exits": 0, "sim_blocks": 0}
    report = _run(world, models=[ModelRef("swing_5d_alt")])  # naming ONE model works: only its own records decide
    assert report.models == ("swing_5d_alt",) and report.picks["model_only"] == 1
    assert _run(world, key="p0-accept-2", models=MODELS).picks["model_only"] > 1  # and so does the other one


def test_a_run_must_name_its_model_and_a_research_rule_needs_permission(world):
    db = world["db"]
    _nightly(world)
    with pytest.raises(ModelNotNamedError):
        _run(world, models=[])
    with pytest.raises(runner.RunnerError):
        _run(world, rule_version="hz-rules-v1/10D")  # a research-only rule is refused unless asked for on purpose
    assert _sim_counts(db)["sim_runs"] == 0


# ------------------------------------------------------------------------------- 5. the protections that stay on


def test_records_cannot_be_edited_once_the_database_guards_are_installed(world):
    import importlib.util
    from pathlib import Path

    path = next((Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("*_horizon_records.py"))
    spec = importlib.util.spec_from_file_location("horizon_records_migration_accept", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = world["db"]
    module.install_triggers(db.connection())
    _nightly(world, indices=range(2))
    row = _five_rows(db)[0]
    for statement in (f"UPDATE horizon_records SET score = 0.01 WHERE id = {row.id}", f"DELETE FROM horizon_records WHERE id = {row.id}"):
        nested = db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(text(statement))
        nested.rollback()


def test_no_job_is_enabled_and_the_h05_lane_is_untouched(world, monkeypatch):
    import importlib

    monkeypatch.delenv("HORIZON_NIGHTLY_ENABLED", raising=False)
    sched = importlib.import_module("swing_trade_ml.workers.scheduler")

    class Fake:
        def __init__(self):
            self.jobs: list = []

        def add_job(self, *a, **k):
            self.jobs.append((a, k))

    fake = Fake()
    assert sched.add_horizon_nightly_job(fake) is False and fake.jobs == []
    db = world["db"]
    from swing_trade_ml.db.models.lanes import H05Run, H05Signal

    _nightly(world)
    assert db.scalar(select(func.count()).select_from(H05Run)) == 0 and db.scalar(select(func.count()).select_from(H05Signal)) == 0
