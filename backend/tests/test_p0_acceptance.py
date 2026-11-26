# ruff: noqa: E501  (long plain-English test text)
"""P0 acceptance: ONE run from real-shaped 5-session predictions to stored simulation results.

    prediction rows (as the scan writes them) -> canonical security_id (identity) -> 5D horizon records with
    model / version / prediction provenance (the nightly writer, called directly) -> the 100 simulated portfolios fed
    from the STORED records -> results persisted -> a replay adds nothing.

What is real here: the identity tables and writer, `predictions` and `ml_models` rows in the shape the scan writes, the
nightly writer and the horizon-record table, the research config, the cohort matrix, the ledger (the app's limits, costs
and sizing) and the simulation store.

What is SYNTHETIC: the stocks' prices and model scores are invented (the symbols look like NSE names but no market data
is used), there is no ISIN, the momentum policy ranks a declared universe of these invented stocks with the app's 20-day top-5 rule, and the persisted
simulation rows are flagged synthetic. Nothing is sent, nothing trades, no job is enabled, and every write rolls back
with the test.
"""

from __future__ import annotations

import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from swing_trade_ml.brain.horizons import run_horizon
from swing_trade_ml.core.market_session import IST, is_trading_day
from swing_trade_ml.db.models import (
    SimBlock,
    SimDay,
    SimExit,
    SimFill,
    SimMark,
    SimNotApplied,
    SimPortfolio,
    SimRun,
)
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.services import horizon_nightly as hn
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import resolve, writer
from swing_trade_ml.simulation import momentum as momentum_rule
from swing_trade_ml.simulation import runner, source, store
from swing_trade_ml.simulation.identity import Policy
from swing_trade_ml.simulation.ledger import Bar, Candidate
from swing_trade_ml.simulation.rules import TradingRules
from swing_trade_ml.simulation.runner import RunnerError
from swing_trade_ml.simulation.source import AmbiguousRecordsError, ModelNotNamedError, ModelRef
from swing_trade_ml.simulation.store import ReplayMismatchError

DAYS = tuple(d for i in range(40) if (d := date(2026, 12, 1) + timedelta(days=i)).weekday() < 5)[:16]
SESSIONS = tuple(d.isoformat() for d in DAYS)
RENAME_AT = 6  # OLDCO becomes NEWCO from the 7th session
V2_FROM = 8  # the 5-session model is replaced by version v2 from the 9th session
STALE_AFTER = 2  # STALECO has candles only for the first three sessions
RUN_KEY = "p0-accept-1"
PRE_DAYS = tuple(d for i in range(60) if (d := date(2026, 12, 1) - timedelta(days=i + 1)).weekday() < 5)[:26][::-1]  # 26 sessions of history before the window (the 20-day Momentum rule needs more than 20 closes)
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
    for k, symbol in enumerate((*SCORES, LONG_ONLY)):  # stored history BEFORE the first session, for the trailing 20-day Momentum rule
        for bar, day in zip(_bars(300 + k, len(PRE_DAYS)), PRE_DAYS, strict=True):
            db.add(Candle(instrument_id=instruments[symbol].id, interval="day", ts=_stamp(day), open=bar.open, high=bar.high, low=bar.low, close=bar.close, volume=100_000))
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


def _universe(world) -> list[int]:
    """Momentum's DECLARED universe: every stock of the fixture, as permanent security ids (never 'whatever the models scored')."""
    ids = (resolve(world["db"], token=i.instrument_token) for i in world["instruments"].values())
    return sorted({sid for sid in ids if sid is not None})


def _run(world, key: str = RUN_KEY, **kwargs):
    """The real caller: stored records and stored candles in, 100 stored portfolios out. Does not commit."""
    kwargs.setdefault("models", MODELS)
    kwargs.setdefault("momentum_universe", _universe(world))
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
    assert report.picks["momentum"] > 0 and report.picks["model_only"] > 0 and report.picks["brain_filtered"] >= report.picks["model_only"]
    assert any("momentum-20d-top5" in note for note in report.notes)  # the runner names the rule Momentum used
    perf = store.performance_by_policy(db, RUN_KEY)
    assert {p: row["portfolios"] for p, row in perf.items()} == {"momentum": 33, "model_only": 33, "brain_filtered": 33}
    assert perf["model_only"]["zero_trade_portfolios"] < 33
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
    for table in (SimFill, SimBlock, SimExit):  # no model decided it: only Momentum (a declared universe, no model) may touch it
        assert db.scalar(select(func.count()).select_from(table).where(table.security_id == long_id, table.policy != "momentum")) == 0


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


# ------------------------------------------------------------------------------- 6. the reports reconcile with the ledger
#
# Only the reports that already exist are used (the runner report, `store.performance_by_policy`, `store.trace_fills`)
# and the stored rows they are built from. Every mismatch is collected with its portfolio key, so a failure names it.

MONEY = 0.01  # one paisa


def _per_portfolio(db):
    """portfolio -> its stored days, fills, exits and marks, from the tables (the ledger as persisted)."""
    portfolios = {p.id: p for p in db.scalars(select(SimPortfolio))}
    days: dict[int, list] = {pid: [] for pid in portfolios}
    for d in db.scalars(select(SimDay).order_by(SimDay.session_date)):
        days[d.portfolio_id].append(d)
    fills, exits, marks = ({pid: [] for pid in portfolios} for _ in range(3))
    for row in db.scalars(select(SimFill)):
        fills[row.portfolio_id].append(row)
    for row in db.scalars(select(SimExit)):
        exits[row.portfolio_id].append(row)
    for row in db.scalars(select(SimMark)):
        marks[row.portfolio_id].append(row)
    return portfolios, days, fills, exits, marks


def _reconciliation_problems(db) -> list[str]:
    """Every way the stored days, fills, exits and marks fail to add up, each naming its portfolio key."""
    portfolios, days, fills, exits, marks = _per_portfolio(db)
    problems: list[str] = []

    def bad(portfolio, what: str) -> None:
        problems.append(f"{portfolio.persona_key} ({portfolio.policy}, {portfolio.balance_inr}): {what}")

    for pid, p in portfolios.items():
        start = float(p.balance_inr)
        stored_days = days[pid]
        if not stored_days:
            bad(p, "has no stored days")
            continue
        value_by_day: dict = {}
        for m in marks[pid]:
            value_by_day[m.session_date] = value_by_day.get(m.session_date, 0.0) + m.value
        for d in stored_days:  # cash + market value of the open positions = the stored equity, every day
            if abs(d.cash + value_by_day.get(d.session_date, 0.0) - d.equity) > MONEY:
                bad(p, f"{d.session_date}: cash {d.cash} + positions {value_by_day.get(d.session_date, 0.0)} != equity {d.equity}")
        for d in stored_days:  # cash = starting cash - buys (with costs) + sales (after costs), to date
            spent = sum(f.cost for f in fills[pid] if f.session_date <= d.session_date)
            got = sum(e.proceeds for e in exits[pid] if e.session_date <= d.session_date)
            if abs(start - spent + got - d.cash) > MONEY:
                bad(p, f"{d.session_date}: start {start} - buys {spent} + sales {got} != cash {d.cash}")
        if not fills[pid]:  # a zero-trade account is present, every day, with equity = cash
            if exits[pid] or marks[pid]:
                bad(p, "no fills but it has exits or open positions")
            if any(abs(d.equity - d.cash) > MONEY or abs(d.cash - start) > MONEY for d in stored_days):
                bad(p, "a zero-trade account moved or its equity differs from its cash")
        last = stored_days[-1]
        if marks[pid] and {m.session_date for m in marks[pid]} - {d.session_date for d in stored_days}:
            bad(p, "a position is marked on a session with no stored day")
        if last.session_date != DAYS[-1]:
            bad(p, f"stops on {last.session_date}, not the last session")
    return problems


def test_the_reports_reconcile_with_the_ledger_for_every_portfolio_and_policy(simulated):
    db, report = simulated["db"], simulated["report"]
    portfolios, days, fills, _exits, _marks = _per_portfolio(db)
    assert len(portfolios) == 100
    problems = _reconciliation_problems(db)
    assert not problems, f"{len(problems)} reconciliation mismatches:\n" + "\n".join(problems[:25])

    # the runner's report agrees with the rows
    assert report.fills == db.scalar(select(func.count()).select_from(SimFill)) == sum(len(v) for v in fills.values())
    assert report.blocks == db.scalar(select(func.count()).select_from(SimBlock))
    no_trade = sum(1 for pid in portfolios if not fills[pid])
    assert report.zero_trade_portfolios == no_trade
    assert (report.portfolios, report.compared, report.validation) == (len(portfolios), 99, 1)
    # trace_fills is the same fills, one row each
    traced = store.trace_fills(db, RUN_KEY)
    assert len(traced) == report.fills
    by_policy_fills: dict[str, int] = {}
    for f in db.scalars(select(SimFill)):
        by_policy_fills[f.policy] = by_policy_fills.get(f.policy, 0) + 1
        assert f.policy == portfolios[f.portfolio_id].policy, f"fill {f.id} carries another policy than its portfolio"
    assert {t.policy for t in traced} == set(by_policy_fills)
    assert {p: sum(1 for t in traced if t.policy == p) for p in by_policy_fills} == by_policy_fills

    # per policy: the validation portfolio is in no total, and the totals are the portfolios' own numbers
    perf = store.performance_by_policy(db, RUN_KEY)
    compared = [(pid, p) for pid, p in portfolios.items() if p.counts_in_comparison]
    validation = [p for p in portfolios.values() if not p.counts_in_comparison]
    assert len(validation) == 1 and len(compared) == 99
    assert sum(int(row["portfolios"]) for row in perf.values()) == 99
    for policy in ("momentum", "model_only", "brain_filtered"):
        mine = [(pid, p) for pid, p in compared if p.policy == policy]
        assert int(perf[policy]["portfolios"]) == len(mine) == 33, policy
        assert int(perf[policy]["zero_trade_portfolios"]) == sum(1 for pid, _ in mine if not fills[pid]), policy
        returns = [days[pid][-1].equity / p.balance_inr - 1 for pid, p in mine]
        assert abs(perf[policy]["mean_return"] - sum(returns) / len(returns)) < 1e-9, policy
    only = validation[0]
    assert only.persona_key not in {p.persona_key for _, p in compared}  # in no policy denominator


def test_a_ledger_that_does_not_add_up_fails_and_names_its_portfolio(simulated):
    db = simulated["db"]
    assert _reconciliation_problems(db) == []
    portfolios = {p.id: p.persona_key for p in db.scalars(select(SimPortfolio))}
    day = db.scalars(select(SimDay).order_by(SimDay.id)).first()
    day.equity += 5.0  # an equity that is not its cash plus its positions
    fill = db.scalars(select(SimFill).order_by(SimFill.id)).first()
    fill.cost += 7.0  # a buy that cost more than the cash that left
    db.flush()
    problems = _reconciliation_problems(db)
    assert any(portfolios[day.portfolio_id] in p and "equity" in p for p in problems)
    assert any(portfolios[fill.portfolio_id] in p and "cash" in p for p in problems)


# ------------------------------------------------------------------------------- 7. the demonstration evidence file
#
# Written only when P0_DEMO_OUT names a file (never in the repo, never in CI): the input, the output, three traces from a
# fill back to its prediction, the blocked reasons, and the row counts before and after a rerun, as JSON.


@pytest.mark.skipif(not os.environ.get("P0_DEMO_OUT"), reason="set P0_DEMO_OUT to write the demonstration evidence file")
def test_write_the_demonstration_evidence_file(world):
    db = world["db"]
    summaries = _nightly(world)
    first = _run(world)
    models = world["models"]
    model_rows = {m.id: m for m in models.values()}
    symbol_of = {i.id: s for s, i in world["instruments"].items()}

    def prediction_view(p: Prediction) -> dict:
        m = model_rows[p.model_id]
        return {
            "prediction_id": p.id, "symbol": symbol_of[p.instrument_id], "session": p.ts.astimezone(IST).date().isoformat(),
            "model": m.name, "version": m.version, "horizon_sessions": m.prediction_horizon_days,
            "probability": p.probability, "price_at_prediction": p.price_at_prediction,
        }

    predictions = [prediction_view(p) for p in db.scalars(select(Prediction).order_by(Prediction.id))]
    records = _five_rows(db)

    def record_view(r: HorizonRecordRow) -> dict:
        return {
            "record_id": r.id, "security_id": r.security_id, "symbol_on_session": source.symbol_on(db, r.security_id, r.session_date),
            "session": r.session_date.isoformat(), "horizon_sessions": r.horizon_days, "model": r.model_name, "version": r.model_version,
            "revision": r.revision, "decision": r.decision, "score": r.score, "due_session": r.evaluation_due_session,
            "run_ref": r.run_ref, "scan_key": r.scan_key, "research_only": r.research_only, "rule": r.research_config_version,
        }

    perf = store.performance_by_policy(db, RUN_KEY)
    fills_by_policy = dict(db.execute(select(SimFill.policy, func.count()).group_by(SimFill.policy)).all())
    exits_by_policy = dict(db.execute(select(SimExit.policy, func.count()).group_by(SimExit.policy)).all())
    block_counts = dict(db.execute(select(SimBlock.reason, func.count()).group_by(SimBlock.reason).order_by(func.count().desc())).all())
    traces, seen = [], set()
    for t in store.trace_fills(db, RUN_KEY):
        if t.policy == "momentum" or t.security_id in seen:
            continue
        seen.add(t.security_id)
        record = db.get(HorizonRecordRow, t.horizon_record_id)
        pred = db.get(Prediction, int(record.run_ref.split(":")[1]))
        traces.append({"fill": {"portfolio": t.persona_key, "policy": t.policy, "session": t.session_date, "symbol": t.symbol, "qty": t.qty, "price": t.price},
                       "record": record_view(record), "prediction": prediction_view(pred)})
        if len(traces) == 3:
            break
    before = {"simulation": _sim_counts(db), "horizon_records": len(_five_rows(db))}
    again = _run(world)
    nightly_again = _nightly(world)
    after = {"simulation": _sim_counts(db), "horizon_records": len(_five_rows(db))}
    out = {
        "summary": {
            "what_this_is": "One synthetic run: invented stocks, prices and scores; real code from prediction rows to stored simulation results",
            "stocks": len(world["instruments"]), "sessions": len(DAYS), "models": len(models),
            "predictions_5d": sum(1 for p in predictions if p["horizon_sessions"] == 5), "predictions_10d_15d": sum(1 for p in predictions if p["horizon_sessions"] != 5),
            "records_written": len(records), "from_predictions": sum(1 for r in records if r.run_ref.startswith("prediction:")),
            "explicit_no_data_records": sum(1 for r in records if r.run_ref == "no-data"), "research_records_in_product_run": sum(1 for r in records if r.research_only),
            "portfolios": first.portfolios, "compared": first.compared, "validation": first.validation,
            "fills": first.fills, "blocked_picks": first.blocks, "zero_trade_portfolios": first.zero_trade_portfolios,
            "rerun_adds_rows": again.rows_created, "momentum": f"the app's 20-day top-5 rule over a declared universe of {first.momentum_declared} stocks",
        },
        "input": {
            "stocks": [{"symbol": s, "token": i.instrument_token, "model_score": SCORES.get(s), "candles": len(world["bars_by_symbol"][s]),
                        "note": {"OLDCO": f"renamed NEWCO from {DAYS[RENAME_AT]}", "STALECO": f"no candles after {DAYS[STALE_AFTER]}",
                                 "ITC": "not in the identity tables at the start", LONG_ONLY: "only 10- and 15-session models score it"}.get(s, "")}
                       for s, i in world["instruments"].items()],
            "models": [{"name": m.name, "version": m.version, "horizon_sessions": m.prediction_horizon_days, "role": m.model_role} for m in models.values()],
            "sessions": [d.isoformat() for d in DAYS],
            "prediction_rows": predictions,
        },
        "output": {
            "nightly_summaries": [s.as_dict() for s in summaries],
            "records": [record_view(r) for r in records],
            "per_policy": {p: {**row, "fills": fills_by_policy.get(p, 0), "exits": exits_by_policy.get(p, 0)} for p, row in perf.items()},
            "example_traces": traces,
            "blocked_reasons": block_counts,
            "rerun": {"before": before, "after": after, "nightly_rows_added": sum(s.recorded + s.no_data for s in nightly_again), "unchanged": before == after},
        },
    }
    assert before == after and again.rows_created == 0 and len(traces) == 3
    path = Path(os.environ["P0_DEMO_OUT"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf8")


# ======================================================================================= three-policy acceptance
# ONE world, the real callers (nightly 5D writer, then runner.run_and_persist with a declared momentum_universe), the three
# compared policies of #321: Momentum (the app's 20-day top-5 rule), Model-only (the 5-session model's TRADE records) and
# Brain-filtered (the same model picks, held back unless the Brain's own check said TRADE).


POLICIES = ("momentum", "model_only", "brain_filtered")


def _oracle_momentum(db, universe: list[int]) -> dict[str, list[int]]:
    """Independent recomputation of the Momentum picks of each session, straight from the stored candles: the 5 stocks
    with the highest gain over the last 20 bars up to and including that session's close, a tie broken by the symbol."""
    closes: dict[int, dict[date, float]] = {}
    instruments = list(db.scalars(select(Instrument)))
    for sid in universe:
        inst_ids = [i.id for i in instruments if resolve(db, token=i.instrument_token) == sid]
        for c in db.scalars(select(Candle).where(Candle.instrument_id.in_(inst_ids), Candle.interval == "day")):
            closes.setdefault(sid, {})[c.ts.astimezone(IST).date()] = float(c.close)
    last_day = date.fromisoformat(SESSIONS[-1])
    out: dict[str, list[int]] = {}
    for session in SESSIONS:
        day = date.fromisoformat(session)
        scored = []
        for sid, by_day in closes.items():
            seen = sorted((d, v) for d, v in by_day.items() if d <= day)
            if day in by_day and len(seen) > 20 and seen[-21][1] > 0:
                scored.append((-(seen[-1][1] / seen[-21][1] - 1.0), source.symbol_on(db, sid, last_day) or "", sid))
        out[session] = [sid for _, _, sid in sorted(scored)[:5]]
    return out


@pytest.fixture()
def three(world):
    _nightly(world)
    universe = _universe(world)
    report = _run(world)
    return {**world, "report": report, "universe": universe}


def test_all_hundred_portfolios_run_all_three_policies_from_their_own_sources(three):
    db, report, universe = three["db"], three["report"], three["universe"]
    assert (report.portfolios, report.compared, report.validation) == (100, 99, 1)
    assert db.scalar(select(func.count()).select_from(SimPortfolio)) == 100
    perf = store.performance_by_policy(db, RUN_KEY)
    assert set(perf) == set(POLICIES) and {p: int(perf[p]["portfolios"]) for p in POLICIES} == dict.fromkeys(POLICIES, 33)
    assert all(report.picks[p] > 0 for p in POLICIES)  # each policy had picks in the window
    fills_by_policy = dict(db.execute(select(SimFill.policy, func.count()).group_by(SimFill.policy)).all())
    assert set(fills_by_policy) == set(POLICIES) and all(n > 0 for n in fills_by_policy.values())
    # every portfolio is stored through the last session, so none silently dropped out
    last = date.fromisoformat(SESSIONS[-1])
    assert db.scalar(select(func.count(func.distinct(SimDay.portfolio_id))).where(SimDay.session_date == last)) == 100
    run = db.scalar(select(SimRun).where(SimRun.run_key == RUN_KEY))
    assert json.loads(run.momentum_universe) == universe and run.momentum_universe_sha256  # the declared universe is on the row
    assert (report.momentum_declared, report.momentum_ranked, report.momentum_not_ranked) == (len(universe), len(universe), {})
    # each policy traces to its own source: Momentum to the rule, the other two to a stored 5-session record
    ref = momentum_rule.rule_ref()
    assert ref == "momentum-20d-top5:v1"
    for table in (SimFill, SimBlock):
        for row in db.scalars(select(table)):
            if row.policy == "momentum":
                assert row.rule_ref == ref and row.horizon_record_id is None
            else:
                rec = db.get(HorizonRecordRow, row.horizon_record_id)
                assert row.rule_ref is None and rec.horizon_days == 5 and rec.research_only is False and rec.revision == 1
    # the third policy, Brain-filtered: only records whose Brain check said TRADE are ever bought; the rest are named
    for t in store.trace_fills(db, RUN_KEY):
        if t.policy == "brain_filtered":
            assert t.record_decision == "TRADE"
    held_back = {p: set(db.scalars(select(SimBlock.reason).where(SimBlock.policy == p, SimBlock.reason.like("held_back%")))) for p in POLICIES}
    assert {"held_back: brain check: WATCH", "held_back: brain check: WAIT"} <= held_back["brain_filtered"]
    assert not held_back["momentum"] and not held_back["model_only"]  # only the Brain-filtered policy holds picks back


def test_momentum_trades_from_the_twenty_day_top_five_rule_with_no_look_ahead(three):
    db, universe = three["db"], three["universe"]
    oracle = _oracle_momentum(db, universe)
    assert all(len(picks) == 5 for picks in oracle.values())  # 26 sessions of history before the window: ranked on every session
    # 1. the runner's own picks equal the independent recomputation, session by session
    closes = source.closes_from_candles(db, universe, SESSIONS[0], SESSIONS[-1])
    symbols = {sid: source.symbol_on(db, sid, date.fromisoformat(SESSIONS[-1])) or "" for sid in closes}
    decided = momentum_rule.momentum_decisions(closes, SESSIONS, symbols=symbols, universe=universe)
    assert {s: [c.security_id for c in picks] for s, picks in decided.items()} == oracle
    # 2. every stored Momentum fill or block is the NEXT session's open on a stock the rule picked at the close before
    index = {s: i for i, s in enumerate(SESSIONS)}
    touched = 0
    for table in (SimFill, SimBlock):
        for row in db.scalars(select(table).where(table.policy == "momentum")):
            i = index[row.session_date.isoformat()]
            assert i >= 1, "a Momentum buy on the first session would have used a decision made before the window"
            assert row.security_id in oracle[SESSIONS[i - 1]]
            touched += 1
    assert touched > 0
    # 3. nothing after a session reaches that session's picks: wreck every close after session 8 and the earlier picks stay put
    cut = date.fromisoformat(SESSIONS[8])
    poisoned = {sid: {d: (v if d <= cut else v * (50 if sid % 2 else 0.02)) for d, v in by.items()} for sid, by in closes.items()}
    again = momentum_rule.momentum_decisions(poisoned, SESSIONS, symbols=symbols, universe=universe)
    got = {s: [c.security_id for c in picks] for s, picks in again.items()}
    assert {s: got.get(s) for s in SESSIONS[:9]} == {s: oracle[s] for s in SESSIONS[:9]}
    assert {s: got.get(s) for s in SESSIONS[9:]} != {s: oracle[s] for s in SESSIONS[9:]}  # the poison does bite the later sessions


def test_a_shorter_run_makes_the_same_momentum_buys_so_no_future_data_is_used(three):
    db = three["db"]
    k = 9
    short = runner.run_and_persist(db, run_key="p0-accept-short", sessions=SESSIONS[:k], models=MODELS, momentum_universe=three["universe"])
    assert short.portfolios == 100
    last = date.fromisoformat(SESSIONS[k - 1])

    def momentum_fills(run_key: str) -> set:
        return {(t.persona_key, t.session_date, t.security_id, t.qty, t.price) for t in store.trace_fills(db, run_key) if t.policy == "momentum" and t.session_date <= last}

    assert momentum_fills("p0-accept-short") == momentum_fills(RUN_KEY) and momentum_fills(RUN_KEY)


def test_zero_trade_portfolios_are_stored_with_their_cash_and_the_reason_never_forced(three):
    db, report = three["db"], three["report"]
    portfolios, days, fills, exits, marks = _per_portfolio(db)
    blocks: dict[int, list[SimBlock]] = {pid: [] for pid in portfolios}
    for b in db.scalars(select(SimBlock)):
        blocks[b.portfolio_id].append(b)
    empty = [pid for pid in portfolios if not fills[pid]]
    assert empty and len(empty) == report.zero_trade_portfolios  # accounts that cannot afford a position are recorded, not hidden
    for pid in empty:
        p = portfolios[pid]
        assert days[pid] and days[pid][-1].session_date == DAYS[-1]
        assert all(abs(d.cash - p.balance_inr) < MONEY and abs(d.equity - p.balance_inr) < MONEY for d in days[pid]), p.persona_key  # cash untouched
        assert not marks[pid] and not exits[pid]
        assert blocks[pid], f"{p.persona_key} bought nothing and no pick was refused with a reason"  # picks were made and refused, never forced
        assert all(b.reason and b.reason.strip() for b in blocks[pid])
    assert "below_minimum_position" in {b.reason for pid in empty for b in blocks[pid]}
    assert "momentum" in {portfolios[pid].policy for pid in empty}  # Momentum has zero-trade portfolios too, recorded the same way
    perf = store.performance_by_policy(db, RUN_KEY)
    compared_empty = [pid for pid in empty if portfolios[pid].counts_in_comparison]
    assert sum(int(perf[p]["zero_trade_portfolios"]) for p in POLICIES) == len(compared_empty)


def test_a_rerun_adds_nothing_and_a_different_universe_is_refused(three):
    db, universe = three["db"], three["universe"]
    before = (_sim_counts(db), len(_five_rows(db)))
    again = _run(three)
    assert again.rows_created == 0 and again.run_id == three["report"].run_id
    assert (_sim_counts(db), len(_five_rows(db))) == before
    with pytest.raises(ReplayMismatchError):
        _run(three, momentum_universe=universe[:-1])  # a replay under another universe is refused ...
    assert (_sim_counts(db), len(_five_rows(db))) == before  # ... and writes nothing


def test_each_policys_results_reconcile_with_its_stored_fills(three):
    db = three["db"]
    portfolios, days, fills, exits, marks = _per_portfolio(db)
    assert not _reconciliation_problems(db)  # cash and equity add up for every portfolio, day by day
    perf = store.performance_by_policy(db, RUN_KEY)
    traced = store.trace_fills(db, RUN_KEY)
    for policy in POLICIES:
        mine = [pid for pid, p in portfolios.items() if p.policy == policy]
        assert sum(len(fills[pid]) for pid in mine) == sum(1 for t in traced if t.policy == policy) > 0, policy
        start = sum(portfolios[pid].balance_inr for pid in mine)
        spent = sum(f.cost for pid in mine for f in fills[pid])
        got = sum(e.proceeds for pid in mine for e in exits[pid])
        last_value = sum(m.value for pid in mine for m in marks[pid] if m.session_date == DAYS[-1])
        end_equity = sum(days[pid][-1].equity for pid in mine)
        end_cash = sum(days[pid][-1].cash for pid in mine)
        assert abs(start - spent + got - end_cash) < MONEY * len(mine), policy  # cash = start - buys + sales
        assert abs(end_cash + last_value - end_equity) < MONEY * len(mine), policy  # equity = cash + open positions
        compared = [pid for pid in mine if portfolios[pid].counts_in_comparison]
        returns = [days[pid][-1].equity / portfolios[pid].balance_inr - 1 for pid in compared]
        assert abs(perf[policy]["mean_return"] - sum(returns) / len(returns)) < 1e-9, policy


def test_missing_stale_and_rejected_momentum_inputs_are_explicit(three):
    db, universe = three["db"], three["universe"]
    # missing: a declared stock with no stored price is reported as not ranked, never dropped silently
    ghost = Instrument(instrument_token=next(_tokens), tradingsymbol="NOPRICE", name="No Price Limited", exchange="NSE", instrument_type="EQ", is_active=True, is_watchlisted=True)
    db.add(ghost)
    db.flush()
    writer.ensure_for_instrument(db, ghost)
    ghost_id = resolve(db, token=ghost.instrument_token)
    wider = runner.run_and_persist(db, run_key="p0-accept-ghost", sessions=SESSIONS, models=MODELS, momentum_universe=[*universe, ghost_id])
    assert wider.momentum_declared == len(universe) + 1 and wider.momentum_ranked == len(universe)
    assert wider.momentum_not_ranked == {ghost_id: momentum_rule.NO_PRICES}
    assert any("not ranked" in n and momentum_rule.NO_PRICES in n for n in wider.notes)
    assert db.scalar(select(func.count()).select_from(SimFill).where(SimFill.security_id == ghost_id)) == 0
    # stale: a stock whose candles stop is no longer ranked after its last bar and is bought on no later session
    stale_id = resolve(db, token=three["instruments"]["STALECO"].instrument_token)
    oracle = _oracle_momentum(db, universe)
    assert all(stale_id not in picks for s, picks in oracle.items() if s > SESSIONS[STALE_AFTER])
    assert db.scalar(select(func.count()).select_from(SimFill).where(SimFill.policy == "momentum", SimFill.security_id == stale_id, SimFill.session_date > DAYS[STALE_AFTER + 1])) == 0
    # rejected: no universe, an empty or repeated one, and picks that borrow the app rule's name are all refused, and write nothing
    before = _sim_counts(db)
    for bad in (None, [], [universe[0], universe[0]], [0], ["x"]):
        with pytest.raises(RunnerError):
            runner.run_and_persist(db, run_key="p0-accept-bad", sessions=SESSIONS, models=MODELS, momentum_universe=bad)
    forged = {SESSIONS[0]: [Candidate(security_id=universe[0], symbol="X", score=1.0, rule_ref=momentum_rule.rule_ref())]}
    with pytest.raises(RunnerError):
        runner.run_and_persist(db, run_key="p0-accept-bad", sessions=SESSIONS, models=MODELS, momentum_universe=universe, momentum=forged)
    assert _sim_counts(db) == before
