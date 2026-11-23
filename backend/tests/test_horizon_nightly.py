# ruff: noqa: E501 (long lines in test code)
"""5-session records from real predictions, the nightly job and its off switch (#387, #389). Integration, dev4."""

from __future__ import annotations

import ast
import importlib
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.ml import MLModel, Prediction
from swing_trade_ml.db.models.trading import Signal
from swing_trade_ml.services import horizon_nightly as hn
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import writer

sched_mod = importlib.import_module("swing_trade_ml.workers.scheduler")  # the package also exports a `scheduler` object

SESSION = date(2026, 11, 20)  # a Friday
STAMP = datetime(2026, 11, 20, tzinfo=IST)  # daily candles are stamped IST midnight
_tokens = iter(range(387_300, 387_900))


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, *a, **k):
        self.jobs.append((a, k))


def stock(db, symbol: str, *, known: bool = True, name: str | None = None) -> Instrument:
    inst = Instrument(
        instrument_token=next(_tokens),
        tradingsymbol=symbol,
        name=name,
        exchange="NSE",
        instrument_type="EQ",
        is_active=True,
    )
    db.add(inst)
    db.flush()
    if known:
        writer.ensure_for_instrument(db, inst)
    return inst


def model(db, name: str, horizon: int, role: str | None = "final", version: str = "v1") -> MLModel:
    row = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status="TRAINED",
        prediction_horizon_days=horizon,
        label_kind="endpoint",
        model_role=role,
        feature_names=["a"],
        training_symbols=["X"],
    )
    db.add(row)
    db.flush()
    return row


def predict(db, mdl: MLModel, inst: Instrument, p: float = 0.9, close: float = 100.0, ts: datetime = STAMP) -> Prediction:
    row = Prediction(
        model_id=mdl.id,
        instrument_id=inst.id,
        ts=ts,
        predicted_class=1 if p >= 0.5 else 0,
        probability=p,
        price_at_prediction=close,
        label_kind="endpoint",
    )
    db.add(row)
    db.flush()
    return row


def rows(db) -> list[HorizonRecordRow]:
    db.expire_all()
    return list(db.scalars(select(HorizonRecordRow).order_by(HorizonRecordRow.id)))


def sid(db, inst: Instrument) -> int:
    from swing_trade_ml.services.identity import resolve

    return resolve(db, token=inst.instrument_token, symbol=inst.tradingsymbol)


# ------------------------------------------------------------------------- the writer: exact provenance


def test_one_five_day_prediction_becomes_one_versioned_record_with_exact_provenance(db_session):
    inst = stock(db_session, "HN387A")
    m5 = model(db_session, "fd5_final_a", 5)
    pred = predict(db_session, m5, inst, p=0.91, close=250.5)
    out = hn.record_prediction(db_session, pred, m5, inst, SESSION)
    assert out is not None and out.created and out.revision == 1
    (row,) = rows(db_session)
    assert row.security_id == sid(db_session, inst)
    assert (row.horizon_days, row.session_date, row.decision) == (5, SESSION, "TRADE")
    assert (row.model_id, row.model_name, row.model_version) == (m5.id, "fd5_final_a", "v1")
    assert row.run_ref == f"prediction:{pred.id}" and row.scan_key == "h5:2026-11-20"
    assert row.input_cutoff == STAMP and row.score == 0.91 and row.input_close == 250.5
    # five sessions on, over the exchange calendar (24 Nov 2026 is an exchange holiday, so it is Monday 30 Nov)
    assert row.evaluation_due_session == hn.sessions_from(SESSION)[5] == date(2026, 11, 30)
    assert row.research_only is False and row.research_config_version == "hz-rules-v1"


def test_a_retry_adds_nothing(db_session):
    inst = stock(db_session, "HN387B")
    m5 = model(db_session, "fd5_final_b", 5)
    pred = predict(db_session, m5, inst)
    first = hn.record_prediction(db_session, pred, m5, inst, SESSION)
    again = hn.record_prediction(db_session, pred, m5, inst, SESSION)
    assert (again.created, again.row_id) == (False, first.row_id)
    assert len(rows(db_session)) == 1


def test_a_rescored_prediction_appends_revision_two_and_keeps_the_first(db_session):
    inst = stock(db_session, "HN387C")
    m5 = model(db_session, "fd5_final_c", 5)
    pred = predict(db_session, m5, inst, p=0.91)
    hn.record_prediction(db_session, pred, m5, inst, SESSION)
    pred.probability = 0.65  # the predictions table can be overwritten by a re-run (#355): the record keeps both
    db_session.flush()
    second = hn.record_prediction(db_session, pred, m5, inst, SESSION)
    assert (second.created, second.revision) == (True, 2)
    assert [(r.revision, r.score, r.decision) for r in rows(db_session)] == [(1, 0.91, "TRADE"), (2, 0.65, "WATCH")]


@pytest.mark.parametrize("horizon", [10, 15])
def test_a_prediction_of_another_horizon_is_never_turned_into_a_five_day_record(db_session, horizon):
    inst = stock(db_session, f"HN387D{horizon}")
    other = model(db_session, f"x_final_{horizon}", horizon)
    pred = predict(db_session, other, inst)
    assert hn.record_prediction(db_session, pred, other, inst, SESSION) is None
    assert rows(db_session) == []


def test_a_stock_the_identity_service_does_not_know_is_skipped_not_created(db_session):
    inst = stock(db_session, "HN387E", known=False)
    m5 = model(db_session, "fd5_final_e", 5)
    pred = predict(db_session, m5, inst)
    assert hn.record_prediction(db_session, pred, m5, inst, SESSION) is None
    assert rows(db_session) == []


def test_a_production_marked_model_is_recorded_as_no_decision_until_the_owner_decides_d1(db_session):
    inst = stock(db_session, "HN387F")
    prod = model(db_session, "swing_prod_f", 5, role="prod")
    hn.record_prediction(db_session, predict(db_session, prod, inst), prod, inst, SESSION)
    (row,) = rows(db_session)
    assert row.decision == "NO_DECISION" and "not approved for decisions" in row.reason
    assert row.score is None and (row.model_name, row.model_version) == ("swing_prod_f", "v1")


# ------------------------------------------------------------------------- the day, the job, product reads


def test_the_day_records_every_five_day_prediction_and_only_those(db_session):
    a, b, c = (stock(db_session, s) for s in ("HN387G1", "HN387G2", "HN387G3"))
    m5, m5b, m15 = model(db_session, "fd5_g", 5), model(db_session, "fd5_g2", 5), model(db_session, "sl_g", 15)
    for inst in (a, b):
        predict(db_session, m5, inst)
    predict(db_session, m5b, a)  # a second 5-session model on the same stock is its own line
    predict(db_session, m15, c)  # a 15-session model's prediction is not a 5D record
    predict(db_session, m5, c, ts=datetime(2026, 11, 19, tzinfo=IST))  # another session: not today's
    out = hn.record_day(db_session, SESSION)
    assert (out.predictions, out.recorded, out.unchanged, out.refused) == (3, 3, 0, 0)
    assert sorted((r.model_id, r.security_id) for r in rows(db_session)) == sorted(
        [(m5.id, sid(db_session, a)), (m5.id, sid(db_session, b)), (m5b.id, sid(db_session, a))]
    )
    again = hn.record_day(db_session, SESSION)
    assert (again.recorded, again.unchanged) == (0, 3) and len(rows(db_session)) == 3


def test_the_newest_prediction_of_the_session_is_the_one_recorded(db_session):
    inst = stock(db_session, "HN387H")
    m5 = model(db_session, "fd5_h", 5)
    predict(db_session, m5, inst, p=0.30, ts=datetime(2026, 11, 20, 9, 0, tzinfo=IST))
    predict(db_session, m5, inst, p=0.92, ts=datetime(2026, 11, 20, 15, 0, tzinfo=IST))
    hn.record_day(db_session, SESSION)
    (row,) = rows(db_session)
    assert row.score == 0.92


def test_end_to_end_product_records_return_the_five_day_line_with_provenance_and_nothing_else(db_session):
    inst = stock(db_session, "HN387I")
    m5, m10, m15 = model(db_session, "fd5_i", 5), model(db_session, "td_i", 10), model(db_session, "sl_i", 15)
    p5 = predict(db_session, m5, inst)
    predict(db_session, m10, inst)
    predict(db_session, m15, inst)
    hn.record_day(db_session, SESSION)
    hn.record_day(db_session, SESSION)  # a retry
    product = hr.product_records(db_session, sid(db_session, inst))
    assert [(r.horizon_days, r.model_id, r.run_ref, r.revision) for r in product] == [(5, m5.id, f"prediction:{p5.id}", 1)]
    assert all(r.horizon_days == 5 for r in rows(db_session))  # 10D and 15D were never written
    assert hr.product_records(db_session, sid(db_session, inst), horizon_days=15) == []


def test_the_job_writes_nothing_outside_horizon_records(db_session):
    inst = stock(db_session, "HN387J")
    m5 = model(db_session, "fd5_j", 5)
    predict(db_session, m5, inst)
    before = {
        "signals": db_session.scalar(select(func.count()).select_from(Signal)),
        "predictions": db_session.scalar(select(func.count()).select_from(Prediction)),
        "models": db_session.scalar(select(func.count()).select_from(MLModel)),
    }
    hn.record_day(db_session, SESSION)
    after = {
        "signals": db_session.scalar(select(func.count()).select_from(Signal)),
        "predictions": db_session.scalar(select(func.count()).select_from(Prediction)),
        "models": db_session.scalar(select(func.count()).select_from(MLModel)),
    }
    assert before == after


def test_the_module_is_independent_of_the_h05_lane_the_brain_and_the_lane_tables():
    path = Path(hn.__file__)
    imported = {n.module for n in ast.walk(ast.parse(path.read_text(encoding="utf8"))) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = ("swing_trade_ml.brain.lanes", "swing_trade_ml.shadow_lanes", "swing_trade_ml.db.models.lanes", "swing_trade_ml.db.models.lane_shadow", "swing_trade_ml.brain.service", "swing_trade_ml.brain.contracts")
    assert not [m for m in imported if m.startswith(forbidden)]
    h05_files = list((path.parents[1] / "brain" / "lanes").glob("*.py"))
    assert h05_files and not any("horizon_nightly" in f.read_text(encoding="utf8") for f in h05_files)


# ------------------------------------------------------------------------- stocks with no security_id yet


def test_an_unbackfilled_database_still_records_the_day_and_a_second_run_adds_nothing(db_session):
    a, b = stock(db_session, "HN387K1", known=False), stock(db_session, "HN387K2", known=False)
    m5 = model(db_session, "fd5_k", 5)
    predict(db_session, m5, a)
    predict(db_session, m5, b)
    first = hn.record_day(db_session, SESSION)
    assert (first.recorded, first.linked, first.resolved, first.refused) == (2, 2, 0, 0)
    assert sorted(r.security_id for r in rows(db_session)) == sorted([sid(db_session, a), sid(db_session, b)])
    second = hn.record_day(db_session, SESSION)
    assert (second.recorded, second.unchanged, second.linked, second.resolved) == (0, 2, 0, 2)
    assert len(rows(db_session)) == 2


def test_a_stock_with_two_models_is_linked_once(db_session):
    a = stock(db_session, "HN387L", known=False)
    for name in ("fd5_l1", "fd5_l2"):
        predict(db_session, model(db_session, name, 5), a)
    out = hn.record_day(db_session, SESSION)
    assert (out.recorded, out.linked, out.resolved) == (2, 1, 0)
    assert len({r.security_id for r in rows(db_session)}) == 1


def test_a_reissued_token_of_the_same_company_joins_its_existing_security(db_session):
    inst = stock(db_session, "HN387M", name="Mango Industries Limited")
    before = sid(db_session, inst)
    inst.instrument_token = next(_tokens)  # the broker re-issued the token; the row is the same stock
    inst.name = "MANGO INDUSTRIES LTD"
    db_session.flush()
    m5 = model(db_session, "fd5_m", 5)
    predict(db_session, m5, inst)
    out = hn.record_day(db_session, SESSION)
    assert (out.recorded, out.linked, out.refused) == (1, 1, 0)
    assert rows(db_session)[0].security_id == before == sid(db_session, inst)


def test_a_conflicting_instrument_is_skipped_and_counted_and_the_others_are_still_recorded(db_session):
    clash = stock(db_session, "HN387N", name="Nectar Foods Limited")
    holder_id = sid(db_session, clash)
    clash.instrument_token = next(_tokens)  # the symbol now belongs to a different company with a new token
    clash.name = "Totally Different Mining Corp"
    fine = stock(db_session, "HN387O", known=False, name="Olive Ltd")
    db_session.flush()
    m5 = model(db_session, "fd5_n", 5)
    for inst in (clash, fine):
        predict(db_session, m5, inst)
    out = hn.record_day(db_session, SESSION)
    assert (out.recorded, out.refused, out.linked) == (1, 1, 1)
    (row,) = rows(db_session)
    assert row.security_id == sid(db_session, fine) and row.security_id != holder_id
    again = hn.record_day(db_session, SESSION)  # the conflict stays refused; nothing else changes
    assert (again.recorded, again.refused, again.unchanged) == (0, 1, 1) and len(rows(db_session)) == 1


# ------------------------------------------------------------------------- the off switch


def test_it_is_not_scheduled_by_default(monkeypatch):
    monkeypatch.delenv("HORIZON_NIGHTLY_ENABLED", raising=False)
    assert hn.HorizonNightlySettings().ENABLED is False
    s = FakeScheduler()
    assert hn.register(s) is False and sched_mod.add_horizon_nightly_job(s) is False
    assert s.jobs == []


def test_the_real_scheduler_does_not_list_the_job_by_default(monkeypatch):
    monkeypatch.delenv("HORIZON_NIGHTLY_ENABLED", raising=False)
    source = Path(sched_mod.__file__).read_text(encoding="utf8")
    assert "add_horizon_nightly_job(scheduler)" in source  # wired, but only through the guarded function
    assert hn.JOB_ID not in source  # no unconditional registration by id


def test_it_registers_one_evening_job_only_when_switched_on(monkeypatch):
    monkeypatch.setenv("HORIZON_NIGHTLY_ENABLED", "true")
    s = FakeScheduler()
    assert sched_mod.add_horizon_nightly_job(s) is True
    assert len(s.jobs) == 1 and s.jobs[0][1]["id"] == hn.JOB_ID and s.jobs[0][1]["max_instances"] == 1


def test_registration_never_raises_even_if_it_breaks(monkeypatch):
    def boom(_):
        raise RuntimeError("scheduler refused")

    monkeypatch.setattr(hn, "register", boom)
    assert sched_mod.add_horizon_nightly_job(FakeScheduler()) is False
