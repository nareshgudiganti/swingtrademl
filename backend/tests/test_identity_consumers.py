# ruff: noqa: E501 (long lines in test code)
"""#389 slice 2: one security_id across Discover, the watchlist and Groww Tracker rows, Portfolio and Reports (also
through a rename); score history for stocks outside the top ranks, with explicit missing and stale states and
provenance; and no duplicate record when a scan is retried.

The Groww SYNC (#388) is not on main, so its linked rows are not exercised; the Groww Tracker on main is the
watchlist (`user_watchlist_items`), which is.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from swing_trade_ml.core.enums import PositionStatus, TradingMode
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.identity import ScoreLedger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Signal, StockScore, Strategy
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import execution, score_history
from swing_trade_ml.services.identity import consumers, ledger, resolve, writer

_tokens = iter(range(390_100, 390_900))
FRIDAY, THURSDAY = date(2026, 11, 20), date(2026, 11, 19)


def _instrument(db, symbol: str, *, name: str | None = None, token: int | None = None) -> Instrument:
    row = Instrument(
        instrument_token=token or next(_tokens), tradingsymbol=symbol, exchange="NSE", name=name or f"{symbol} Ltd",
        instrument_type="EQ", segment="NSE", is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _candle(db, inst, day: date) -> None:
    db.add(
        Candle(
            instrument_id=inst.id, interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST).astimezone(UTC),
            open=1.0, high=1.0, low=1.0, close=1.0, volume=1,
        )
    )
    db.flush()


class _Clock(datetime):
    fixed: datetime

    @classmethod
    def now(cls, tz=None):
        return cls.fixed.astimezone(tz) if tz else cls.fixed


def _at(monkeypatch, when: datetime) -> None:
    _Clock.fixed = when
    monkeypatch.setattr(score_history, "datetime", _Clock)


def _rows(db, security_id: int) -> list[ScoreLedger]:
    db.expire_all()
    return list(db.scalars(select(ScoreLedger).where(ScoreLedger.security_id == security_id).order_by(ScoreLedger.id)))


# ---------------------------------------------------------------- 1. one security_id in every consumer


def _user(db) -> User:
    user = User(username="idc390", email="idc390@example.com", hashed_password="x", is_active=True)
    db.add(user)
    db.flush()
    return user


def test_every_consumer_resolves_one_stock_to_one_security(db_session):
    inst = _instrument(db_session, "CONS390")
    writer.ensure_for_instrument(db_session, inst)
    strategy = Strategy(name="cons390", strategy_type="ml_swing", params={}, is_active=True)
    db_session.add(strategy)
    db_session.flush()
    position = Position(
        strategy_id=strategy.id, instrument_id=inst.id, mode=TradingMode.PAPER, status=PositionStatus.OPEN,
        quantity=1, entry_price=10.0, current_price=10.0, entry_at=datetime(2026, 11, 2, 10, 0, tzinfo=UTC),
    )
    db_session.add(position)
    db_session.add(UserWatchlistItem(user_id=_user(db_session).id, symbol="CONS390", added_at=datetime(2026, 11, 1, tzinfo=UTC)))
    db_session.add(
        BrokerFill(trade_id="idc390-1", symbol="CONS390", side="BUY", quantity=1, price=10.0, executed_at=datetime(2026, 11, 3, 10, 0, tzinfo=IST))
    )
    db_session.flush()

    discover = resolve(db_session, token=inst.instrument_token)
    portfolio = consumers.security_for_instrument(db_session, position.instrument_id)
    watchlist = consumers.security_for_symbol(db_session, db_session.scalar(select(UserWatchlistItem.symbol)))
    report_fill = consumers.security_for_symbol(
        db_session, db_session.scalar(select(BrokerFill.symbol)), on=db_session.scalar(select(BrokerFill.executed_at))
    )
    assert discover is not None
    assert discover == portfolio == watchlist == report_fill


def test_the_same_security_survives_a_rename_in_every_consumer(db_session):
    inst = _instrument(db_session, "OLDNAME390", token=390_001)
    writer.ensure_for_instrument(db_session, inst)
    sid = resolve(db_session, symbol="OLDNAME390")
    old_fill = datetime(2025, 3, 3, 10, 0, tzinfo=IST)
    old_row_day = datetime(2025, 3, 1, tzinfo=UTC)
    db_session.add(BrokerFill(trade_id="idc390-r1", symbol="OLDNAME390", side="BUY", quantity=1, price=10.0, executed_at=old_fill))
    db_session.add(UserWatchlistItem(user_id=_user(db_session).id, symbol="OLDNAME390", added_at=old_row_day))
    strategy = Strategy(name="ren390", strategy_type="ml_swing", params={}, is_active=True)
    db_session.add(strategy)
    db_session.flush()
    position = Position(
        strategy_id=strategy.id, instrument_id=inst.id, mode=TradingMode.PAPER, status=PositionStatus.OPEN,
        quantity=1, entry_price=10.0, current_price=10.0, entry_at=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
    )
    db_session.add(position)
    db_session.flush()
    inst.tradingsymbol = "NEWNAME390"  # the sync renames the row by token
    db_session.flush()
    writer.ensure_for_instrument(db_session, inst)

    assert resolve(db_session, token=inst.instrument_token) == sid
    assert consumers.security_for_instrument(db_session, position.instrument_id) == sid  # Portfolio
    assert resolve(db_session, symbol="NEWNAME390") == sid  # Discover by its new symbol
    assert consumers.security_for_symbol(db_session, "OLDNAME390", on=old_row_day) == sid  # the watchlist row
    assert consumers.security_for_symbol(db_session, "OLDNAME390", on=old_fill) == sid  # a report fill
    assert consumers.security_for_symbol(db_session, "NEWNAME390", on=old_fill) is None, "it was not called that yet"


def test_the_adapters_never_write(db_session):
    from swing_trade_ml.db.models.identity import Security

    inst = _instrument(db_session, "NOWRITE390")
    before = len(list(db_session.scalars(select(Security))))
    assert consumers.security_for_instrument(db_session, inst.id) is None
    assert consumers.security_for_symbol(db_session, "NOWRITE390") is None
    assert consumers.security_for_instrument(db_session, 99_999_999) is None
    assert len(list(db_session.scalars(select(Security)))) == before


# ---------------------------------------------------------------- 2. history, gaps and provenance


MODEL = "swing_classifier:v2"


def test_stocks_outside_the_top_ranks_keep_a_full_history(db_session, monkeypatch):
    stocks = [_instrument(db_session, f"RANK390{i}") for i in range(6)]
    for inst in stocks:
        _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    scores = [(inst.id, 0.9 - i * 0.1, MODEL) for i, inst in enumerate(stocks)]  # the scan scores all six
    score_history.record_stock_scores(db_session, scores, 0.4)
    last = stocks[-1]  # the lowest-ranked one
    sid = resolve(db_session, symbol="RANK3905")
    got = ledger.history(db_session, sid)
    assert [(r.session_date, round(r.score, 2), r.status) for r in got] == [(FRIDAY, 0.4, "scored")] and last.id


def test_a_stale_stock_has_an_explicit_stale_row_in_the_scan_session(db_session, monkeypatch):
    fresh, stale = _instrument(db_session, "FRESH390"), _instrument(db_session, "STALE390")
    _candle(db_session, fresh, FRIDAY)
    _candle(db_session, stale, THURSDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(fresh.id, 0.8, MODEL), (stale.id, 0.7, MODEL)], 0.4)
    sid_stale = resolve(db_session, symbol="STALE390")
    state = ledger.session_state(db_session, [sid_stale], FRIDAY, horizon_days=None)[sid_stale]
    assert state is not None and state.status == "stale" and state.score is None
    assert "2026-11-19" in state.note
    assert ledger.session_state(db_session, [sid_stale], THURSDAY, horizon_days=None)[sid_stale].status == "scored"
    # run again: no second stale row
    score_history.record_stock_scores(db_session, [(fresh.id, 0.8, MODEL), (stale.id, 0.7, MODEL)], 0.4)
    assert len([r for r in _rows(db_session, sid_stale) if r.status == "stale"]) == 1


def test_session_state_tells_scored_missing_and_not_in_the_scan_apart(db_session, monkeypatch):
    a, b, c = (_instrument(db_session, f"STATE390{x}") for x in "ABC")
    for inst in (a, b):
        _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(a.id, 0.8, MODEL)], 0.4, universe=[a.id, b.id])
    ids = {x: writer.ensure_for_instrument(db_session, inst) for x, inst in zip("ABC", (a, b, c), strict=True)}
    state = ledger.session_state(db_session, ids.values(), FRIDAY, horizon_days=None)
    assert state[ids["A"]].status == "scored"
    assert state[ids["B"]].status == "missing" and state[ids["B"]].score is None
    assert state[ids["C"]] is None, "not in the scan at all: absent, not a score"


def test_a_scored_row_outranks_a_gap_for_the_same_stock_and_session(db_session):
    sid = writer.ensure_for_instrument(db_session, _instrument(db_session, "RANKUP390"))
    ledger.append_missing(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", reason="no candle")
    ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.6)
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=None)[sid].status == "scored"


def test_v1_rows_carry_the_model_id_version_and_horizon_when_known_and_null_when_not(db_session):
    known = MLModel(name="prov390", version="v3", algorithm="x", prediction_horizon_days=5)
    db_session.add(known)
    db_session.flush()
    a, b = _instrument(db_session, "PROV390A"), _instrument(db_session, "PROV390B")
    score_history.record_stock_scores(db_session, [(a.id, 0.6, "prov390:v3")], 0.4, today=FRIDAY)
    score_history.record_stock_scores(db_session, [(b.id, 0.6, "unregistered390:v9")], 0.4, today=FRIDAY)
    (ra,) = _rows(db_session, resolve(db_session, symbol="PROV390A"))
    (rb,) = _rows(db_session, resolve(db_session, symbol="PROV390B"))
    assert (ra.model_id, ra.model_name, ra.model_version, ra.horizon_days) == (known.id, "prov390", "v3", 5)
    assert (rb.model_id, rb.model_name, rb.model_version, rb.horizon_days) == (None, "unregistered390", "v9", None)


def _brain_run(db, run_id: str, decisions: list[tuple[str, float | None, str]], *, kind="nightly") -> BrainRun:
    run = BrainRun(id=run_id, kind=kind, as_of=datetime(2026, 11, 20, 15, 50, tzinfo=IST), book="paper", live=True, status="done")
    db.add(run)
    db.flush()
    for symbol, confidence, source in decisions:
        db.add(
            BrainDecision(run_id=run_id, symbol=symbol, kind="idea", word="WATCH", confidence=confidence, score_source=source, horizon_days=15)
        )
    db.flush()
    return run


def test_a_brain_run_is_recorded_with_its_run_id_and_no_guessed_model(db_session):
    a, b = _instrument(db_session, "BRN390A"), _instrument(db_session, "BRN390B")
    _brain_run(db_session, "iso390-run", [("BRN390A", 0.71, "combined"), ("BRN390B", None, "model")])
    assert ledger.append_from_brain_run(db_session, "iso390-run") == 2
    (ra,) = _rows(db_session, resolve(db_session, symbol="BRN390A"))
    (rb,) = _rows(db_session, resolve(db_session, symbol="BRN390B"))
    # horizon is None, not the decision's 15: the brain stamps a frozen default of 15 on a score that may come from a
    # 5-session model (#385), and the evidence ledger must not carry that label until it is fixed
    assert (ra.source, ra.run_ref, ra.horizon_days, ra.score, ra.session_date) == ("brain", "iso390-run", None, 0.71, FRIDAY)
    assert (ra.model_id, ra.model_name, ra.model_version) == (None, "", ""), "the brain stores no model identity: null, not guessed"
    assert "score_source=combined" in ra.note
    assert (rb.status, rb.score, rb.run_ref) == ("missing", None, "iso390-run")
    assert ledger.append_from_brain_run(db_session, "iso390-run") == 0, "a repeat writes nothing"
    assert a.id and b.id


def test_an_on_demand_why_run_is_not_a_scan(db_session):
    _instrument(db_session, "WHY390")
    _brain_run(db_session, "iso390-why", [("WHY390", 0.5, "model")], kind="why")
    assert ledger.append_from_brain_run(db_session, "iso390-why") == 0
    assert ledger.append_from_brain_run(db_session, "no-such-run") == 0


def test_old_score_history_is_copied_into_the_ledger_without_changing_it(db_session):
    inst = _instrument(db_session, "OLDHIST390")
    db_session.add(StockScore(instrument_id=inst.id, as_of=THURSDAY, score=0.55, band="easing", model_version="swing_classifier:v1", model_name="swing_classifier"))
    db_session.add(StockScore(instrument_id=inst.id, as_of=FRIDAY, score=0.65, band="strong", model_version=None, model_name=""))
    db_session.flush()
    assert ledger.backfill_from_stock_scores(db_session) >= 2
    rows = _rows(db_session, resolve(db_session, symbol="OLDHIST390"))
    assert [(r.session_date, r.source, r.model_name, r.model_version, r.score) for r in rows] == [
        (THURSDAY, "backfill", "swing_classifier", "v1", 0.55),
        (FRIDAY, "backfill", "", "", 0.65),
    ]
    assert ledger.backfill_from_stock_scores(db_session) == 0, "idempotent"
    assert db_session.scalar(select(StockScore.score).where(StockScore.instrument_id == inst.id, StockScore.as_of == FRIDAY)) == 0.65


# ---------------------------------------------------------------- 3. retries (#360)


def test_a_retried_scan_records_one_ledger_row_per_stock_horizon_and_session(db_session, monkeypatch):
    db_session.add(MLModel(name="retry390", version="v1", algorithm="x", prediction_horizon_days=15))
    db_session.flush()
    stocks = [_instrument(db_session, f"RETRY390{i}") for i in range(3)]
    for inst in stocks:
        _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    scores = [(inst.id, 0.6 + i * 0.01, "retry390:v1") for i, inst in enumerate(stocks)]
    for _ in range(3):  # the scan is retried twice
        score_history.record_stock_scores(db_session, scores, 0.4)
    for inst in stocks:
        rows = _rows(db_session, resolve(db_session, symbol=inst.tradingsymbol))
        assert len(rows) == 1 and rows[0].revision == 1 and rows[0].horizon_days == 15


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN (#360): services/execution.py record_signal (line 59) always inserts, so a retried scan records a "
        "second v1 `signals` row for the same strategy, stock, horizon and session. The fix is in the v1 trading "
        "path (S7: needs review-risk and the owner's approval), so it is NOT made here. execution.py is not in "
        "trial_freeze.json, but it is the signal-to-order path. The ledger above is not affected."
    ),
)
def test_a_retried_scan_records_one_v1_signal(db_session):
    inst = _instrument(db_session, "SIG390")
    strategy = Strategy(name="sig390", strategy_type="ml_swing", params={}, is_active=True, mode="paper")
    db_session.add(strategy)
    db_session.flush()
    decision = SimpleNamespace(
        signal="BUY", price=10.0, confidence=0.7, stop_loss=9.6, take_profit=10.8, horizon_days=15,
        reason="test", features={},
    )
    for _ in range(2):
        execution.record_signal(db_session, strategy, inst, decision, "paper")
    count = len(list(db_session.scalars(select(Signal).where(Signal.strategy_id == strategy.id, Signal.instrument_id == inst.id))))
    assert count == 1, f"{count} signals recorded for one scan retried once"


def test_a_fifteen_day_score_never_hides_a_five_day_gap_for_the_same_stock(db_session):
    sid = writer.ensure_for_instrument(db_session, _instrument(db_session, "HOR390"))
    ledger.append_missing(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", reason="5d model had no score", horizon_days=5)
    ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.7, horizon_days=15)
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=5)[sid].status == "missing"
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=15)[sid].status == "scored"
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=10)[sid] is None
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=None)[sid] is None, "None means rows with no known horizon"


def test_two_models_can_be_told_apart_by_name(db_session):
    sid = writer.ensure_for_instrument(db_session, _instrument(db_session, "MDL390"))
    ledger.append_score(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", score=0.6, horizon_days=5, model_name="a", model_version="v1")
    ledger.append_missing(db_session, security_id=sid, session_date=FRIDAY, source="v1_scan", reason="b had none", horizon_days=5, model_name="b", model_version="v1")
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=5, model_name="a")[sid].status == "scored"
    assert ledger.session_state(db_session, [sid], FRIDAY, horizon_days=5, model_name="b")[sid].status == "missing"


def test_a_token_and_a_symbol_that_name_different_stocks_give_none_not_the_token(db_session):
    a = _instrument(db_session, "CONFA390", token=390_501)
    writer.ensure_for_instrument(db_session, a)
    other = writer.create_security(db_session, name="Someone else")
    writer.set_symbol(db_session, other, "CONFB390", date(2000, 1, 1))
    a.tradingsymbol = "CONFB390"  # this instrument's token says stock A, its symbol now says someone else's
    db_session.flush()
    assert consumers.security_for_instrument(db_session, a.id) is None
