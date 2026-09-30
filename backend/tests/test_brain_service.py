"""Brain against the real database: the dated reader, module switches,
storing runs, and the brain package's isolation from order placement."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain import service
from swing_trade_ml.brain.module import Mode, Step
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Position
from swing_trade_ml.services import system_state

AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _instrument(db, symbol: str, token: int, *, watch: bool = True) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=True
    )
    db.add(inst)
    db.flush()
    return inst


def _candle(db, inst: Instrument, ts: datetime, close: float) -> None:
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=ts,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1000,
        )
    )


@pytest.fixture()
def market(db_session):
    """Two watchlisted stocks with one bar before AS_OF and one after it."""
    abc = _instrument(db_session, "BRAINABC", 991001)
    xyz = _instrument(db_session, "BRAINXYZ", 991002)
    _instrument(db_session, "BRAINOFF", 991003, watch=False)
    for inst, before, after in ((abc, 100.0, 150.0), (xyz, 50.0, 80.0)):
        _candle(db_session, inst, AS_OF - timedelta(days=1), before)
        _candle(db_session, inst, AS_OF + timedelta(days=1), after)
    db_session.commit()
    return abc, xyz


# --- dated reader ----------------------------------------------------------


def test_reader_never_returns_a_price_from_after_as_of(db_session, market):
    reader = DatedReader(db_session, as_of=AS_OF, live=False)
    bar_date, close = reader.last_close("BRAINABC")
    assert close == 100.0
    assert bar_date == (AS_OF - timedelta(days=1)).date().isoformat()


def test_reader_universe_is_the_active_watchlist(db_session, market):
    universe = DatedReader(db_session, as_of=AS_OF, live=False).universe()
    assert {"BRAINABC", "BRAINXYZ"} <= set(universe)
    assert "BRAINOFF" not in universe


def test_reader_reports_an_owner_halt(db_session, market):
    system_state.halt(db_session, "testing", "pytest")
    state = DatedReader(db_session, as_of=AS_OF, live=True).system_state()
    assert state.entries_halted and state.halt_reason == "testing"


def test_reader_lists_open_positions_of_the_book(db_session, market):
    abc, _ = market
    db_session.add(
        Position(
            instrument_id=abc.id,
            mode="paper",
            status=PositionStatus.OPEN,
            quantity=7,
            entry_price=95.0,
            entry_at=AS_OF - timedelta(days=3),
        )
    )
    db_session.commit()
    held = DatedReader(db_session, as_of=AS_OF, live=True).holdings("paper")
    assert c.Holding(symbol="BRAINABC", qty=7, avg_price=95.0) in held


def test_reader_without_an_active_model_gives_no_score(db_session, market):
    assert DatedReader(db_session, as_of=AS_OF, live=True).model_probability("BRAINABC") is None


# --- module switches -------------------------------------------------------


def test_set_mode_is_stored_and_read_back(db_session):
    service.set_mode(db_session, "M02", Mode.OFF, by="pytest", known_ids={"M02"})
    assert service.load_modes(db_session)["M02"] == Mode.OFF


def test_set_mode_refuses_to_switch_off_a_mandatory_module(db_session):
    with pytest.raises(service.ModeRefusedError):
        service.set_mode(db_session, "M07", Mode.OFF, by="pytest", known_ids={"M07"}, mandatory_ids={"M07"})


def test_set_mode_refuses_an_unknown_module(db_session):
    with pytest.raises(service.UnknownModuleError):
        service.set_mode(db_session, "M42", Mode.ON, by="pytest", known_ids={"M02"})


# --- running and storing ------------------------------------------------------


def test_run_brain_stores_the_run_and_one_decision_per_stock(db_session, market):
    _ctx, run_id = service.run_brain(
        db_session, kind="nightly", as_of=AS_OF, symbols=["BRAINABC", "BRAINXYZ"]
    )
    run = db_session.get(BrainRun, run_id)
    assert (
        run.status == "done" and run.banner_mode == c.MarketMode.DEFENSIVE.value
    )  # risk gate ran; no NIFTY data
    rows = db_session.query(BrainDecision).filter_by(run_id=run_id).all()
    assert {r.symbol for r in rows} == {"BRAINABC", "BRAINXYZ"}
    assert all(r.reasons for r in rows)
    assert any(e["module_id"] == "fallback" for e in run.trace)


def test_latest_run_returns_the_newest_of_a_kind(db_session, market):
    service.run_brain(db_session, kind="nightly", as_of=AS_OF, symbols=["BRAINABC"])
    _, second = service.run_brain(db_session, kind="nightly", as_of=AS_OF, symbols=["BRAINXYZ"])
    assert service.latest_run(db_session, "nightly").id == second


def test_step_overview_lists_all_eight_steps():
    overview = service.step_overview()
    assert [s["step"] for s in overview] == [s.value for s in Step]


# --- isolation ------------------------------------------------------------


def test_brain_package_never_imports_order_placement():
    """C10: no brain module places orders. Only M18 will, via the strategy
    interface, and it lives outside this package."""
    brain_dir = Path(__file__).parents[1] / "src" / "swing_trade_ml" / "brain"
    forbidden = ("swing_trade_ml.brokers", "swing_trade_ml.services.execution")
    offenders = []
    for path in brain_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.startswith(forbidden)]
    assert offenders == []


def test_a_missing_model_file_is_tried_once_not_per_stock(db_session, market, monkeypatch):
    """The model files live in the Docker volume; a run outside it must give up
    after the first missing file instead of failing and logging 50 times."""
    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.ml import predict

    db_session.add(
        MLModel(
            name="swing_classifier",
            version="v9",
            algorithm="lightgbm",
            status=ModelStatus.ACTIVE,
            artifact_path="/nowhere/model.joblib",
            activated_at=AS_OF,
        )
    )
    db_session.commit()
    calls = []

    def missing(*args, **kwargs):
        calls.append(1)
        raise FileNotFoundError("/nowhere/model.joblib")

    monkeypatch.setattr(predict, "predict_instrument", missing)
    reader = DatedReader(db_session, as_of=AS_OF, live=True)
    assert reader.model_probability("BRAINABC") is None
    assert reader.model_probability("BRAINXYZ") is None
    assert len(calls) == 1


def test_a_daily_bar_stamped_at_ist_midnight_is_that_ist_day(db_session):
    """Kite stamps daily bars at IST midnight, stored as 18:30 UTC the day before."""
    inst = _instrument(db_session, "BRAINIST", 991009)
    _candle(db_session, inst, datetime(2026, 9, 24, 18, 30, tzinfo=UTC), 100.0)
    db_session.commit()
    bar_date, _close = DatedReader(db_session, as_of=AS_OF, live=False).last_close("BRAINIST")
    assert bar_date == "2026-09-25"
