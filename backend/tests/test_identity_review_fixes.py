# ruff: noqa: E501 (long lines in test code)
"""#389 independent review of 30f2459: four P2 findings and one P3, each shown by a test (written first).

1. A symbol's history that does not cover the date must not fall back to whoever holds the symbol today.
2. A re-issued token or a symbol link needs the same company (ISIN, else the same normalised name).
3. Each stock's score is filed under ITS OWN latest session, capped at today, not the newest session of the call.
4. A stock the scan was meant to score and did not gets a `missing` ledger row, written in the same savepoint.
P3. An ISIN that two lookups answer differently is not resolved.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select

from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.identity import ScoreLedger
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import StockScore, Strategy
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import identity, ingestion, score_history
from swing_trade_ml.services.identity import ledger, resolve, writer
from swing_trade_ml.services.identity.memory import InMemoryStore

_tokens = iter(range(389_700, 389_999))
FRIDAY, THURSDAY = date(2026, 11, 20), date(2026, 11, 19)
MODEL = "swing_classifier:v2"


def _instrument(db, symbol: str, *, name: str | None = None, token: int | None = None) -> Instrument:
    row = Instrument(
        instrument_token=token or next(_tokens), tradingsymbol=symbol, exchange="NSE", name=name,
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


# ------------------------------------------------------------------------------ 1. dated history is strict


def test_history_that_misses_the_date_does_not_fall_back_to_the_current_holder():
    store = InMemoryStore()
    current = store.add_security("INE389Z01011", "B Co")
    store.add_symbol(current, "XSYM", date(2023, 6, 1))  # B has held it only since 2023
    store.add_instrument(current, "XSYM")
    with identity.use_store(store):
        assert resolve(None, symbol="XSYM", on_date=date(2022, 6, 1)) is None, "2022: it was another company"
        assert resolve(None, symbol="XSYM", on_date=date(2024, 6, 1)) == current


def test_a_symbol_with_no_history_at_all_still_resolves_through_the_current_row():
    store = InMemoryStore()
    sid = store.add_security(None, "No History Co")
    store.add_instrument(sid, "NOHIST")
    with identity.use_store(store):
        assert resolve(None, symbol="NOHIST", on_date=date(2022, 6, 1)) == sid


def test_the_database_store_is_strict_too(db_session):
    sid = writer.create_security(db_session, name="B Co")
    writer.set_symbol(db_session, sid, "XDB389", date(2023, 6, 1))
    inst = _instrument(db_session, "XDB389", name="B Co")
    writer.add_alias(db_session, sid, "kite_token", str(inst.instrument_token))
    assert resolve(db_session, symbol="XDB389", on_date=date(2022, 6, 1)) is None
    assert resolve(db_session, symbol="XDB389", on_date=date(2024, 6, 1)) == sid


# ------------------------------------------------------------------------------ P3. isin and alias must agree


def test_an_isin_that_two_lookups_answer_differently_is_not_resolved():
    store = InMemoryStore()
    a = store.add_security("INE389Y01012", "A")
    b = store.add_security(None, "B")
    store.add_alias(b, "isin", "INE389Y01012")  # an alias says the same ISIN belongs to B
    with identity.use_store(store):
        assert store.id_by_isin("INE389Y01012") == a and store.id_by_alias("isin", "INE389Y01012") == b
        assert resolve(None, isin="INE389Y01012") is None


# ------------------------------------------------------------------------------ 2. same company or no link


def _dump(token: int, symbol: str, name: str, *others: tuple[int, str]) -> list[dict]:
    rows = [(token, symbol, name), *[(t, s, f"{s} name") for t, s in others]]
    return [
        {
            "instrument_token": t, "exchange_token": t // 256, "tradingsymbol": s, "name": n,
            "exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "lot_size": 1, "tick_size": 0.05,
        }
        for t, s, n in rows
    ]


def _sync(db, monkeypatch, dump):
    monkeypatch.setattr(ingestion, "kite_broker", SimpleNamespace(get_instruments=lambda exchange: dump))
    with db.begin_nested():
        ingestion.sync_instruments(db)


def test_a_reissued_token_for_the_same_company_is_still_applied(db_session, monkeypatch):
    inst = _instrument(db_session, "SAME389", name="Reliance Industries Ltd", token=389_801)
    _sync(db_session, monkeypatch, _dump(389_802, "SAME389", "RELIANCE INDUSTRIES LIMITED"))
    db_session.expire_all()
    assert db_session.get(Instrument, inst.id).instrument_token == 389_802


def test_a_symbol_reused_by_a_new_company_does_not_take_over_the_old_row_in_the_sync(db_session, monkeypatch):
    inst = _instrument(db_session, "REUSE389", name="Old Company Ltd", token=389_811)
    _sync(db_session, monkeypatch, _dump(389_812, "REUSE389", "Brand New Holdings Ltd", (389_813, "OTHER389")))
    db_session.expire_all()
    assert db_session.get(Instrument, inst.id).instrument_token == 389_811, "the old company's row is untouched"
    assert db_session.scalar(select(Instrument.id).where(Instrument.tradingsymbol == "OTHER389")) is not None, "the rest of the batch is kept"


def test_a_row_with_no_name_to_compare_is_skipped_not_assumed_the_same(db_session, monkeypatch):
    inst = _instrument(db_session, "NONAME389", name=None, token=389_821)
    _sync(db_session, monkeypatch, _dump(389_822, "NONAME389", "Some Co"))
    db_session.expire_all()
    assert db_session.get(Instrument, inst.id).instrument_token == 389_821


def test_a_symbol_reused_by_a_new_company_is_not_linked_to_the_old_security(db_session):
    old = _instrument(db_session, "LINK389", name="Old Company Ltd", token=389_831)
    writer.ensure_for_instrument(db_session, old)
    old_sid = resolve(db_session, symbol="LINK389")
    old.instrument_token = 389_832  # the sync (or a person) gave the symbol to a different company
    old.name = "Brand New Holdings Ltd"
    db_session.flush()
    with pytest.raises(writer.IdentityConflictError):
        writer.ensure_for_instrument(db_session, old)
    assert resolve(db_session, token=389_832) is None, "no alias was added to the old company"
    assert resolve(db_session, symbol="LINK389") == old_sid
    assert writer.backfill_instruments(db_session)["skipped"] >= 1


def test_the_same_company_under_a_new_token_is_linked(db_session):
    inst = _instrument(db_session, "LINKOK389", name="Tata Consultancy Services Ltd", token=389_841)
    writer.ensure_for_instrument(db_session, inst)
    sid = resolve(db_session, symbol="LINKOK389")
    inst.instrument_token = 389_842
    inst.name = "TATA CONSULTANCY SERVICES LIMITED"
    db_session.flush()
    assert writer.ensure_for_instrument(db_session, inst) == sid
    assert resolve(db_session, token=389_842) == sid


def test_two_isins_known_on_both_sides_must_match(db_session):
    sid = writer.create_security(db_session, isin="INE389X01013", name="X")
    assert writer.same_company(name_a="X", name_b="Y", isin_a="INE389X01013", isin_b="INE389X01013")
    assert not writer.same_company(name_a="X", name_b="X", isin_a="INE389X01013", isin_b="INE389W01014")
    assert sid


# ------------------------------------------------------------------------------ 3. each stock's own session


def test_a_stale_stock_is_filed_under_its_own_session_not_the_newest_one(db_session, monkeypatch):
    fresh = _instrument(db_session, "FRESH389")
    stale = _instrument(db_session, "STALE389")
    _candle(db_session, fresh, FRIDAY)
    _candle(db_session, stale, THURSDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(fresh.id, 0.8, MODEL), (stale.id, 0.7, MODEL)], 0.4)
    assert [r.session_date for r in _rows(db_session, resolve(db_session, symbol="FRESH389"))] == [FRIDAY]
    assert [r.session_date for r in _rows(db_session, resolve(db_session, symbol="STALE389"))] == [THURSDAY]
    old = {r.instrument_id: r.as_of for r in db_session.scalars(select(StockScore).where(StockScore.instrument_id.in_([fresh.id, stale.id])))}
    assert old == {fresh.id: FRIDAY, stale.id: THURSDAY}


def test_a_candle_dated_after_today_is_capped_at_today(db_session, monkeypatch):
    inst = _instrument(db_session, "FUTURE389")
    _candle(db_session, inst, date(2026, 11, 25))
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(inst.id, 0.7, MODEL)], 0.4)
    assert _rows(db_session, resolve(db_session, symbol="FUTURE389"))[0].session_date == FRIDAY


def test_a_stock_with_no_candle_is_filed_under_today(db_session, monkeypatch):
    inst = _instrument(db_session, "NOBAR389")
    _at(monkeypatch, datetime(2026, 11, 23, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(inst.id, 0.7, MODEL)], 0.4)
    assert _rows(db_session, resolve(db_session, symbol="NOBAR389"))[0].session_date == date(2026, 11, 23)


# ------------------------------------------------------------------------------ 4. missing rows from the scan


def test_a_universe_stock_with_no_score_gets_a_missing_row_in_the_scan_path(db_session, monkeypatch):
    a, b, c = (_instrument(db_session, f"UNIV389{x}") for x in "ABC")
    for inst in (a, b, c):
        _candle(db_session, inst, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(a.id, 0.8, MODEL)], 0.4, universe=[a.id, b.id, c.id])
    sid_b, sid_c, sid_a = (resolve(db_session, symbol=f"UNIV389{x}") for x in "BCA")
    assert [(r.status, r.score, r.session_date) for r in _rows(db_session, sid_b)] == [("missing", None, FRIDAY)]
    assert [r.status for r in _rows(db_session, sid_c)] == ["missing"]
    assert [r.status for r in _rows(db_session, sid_a)] == ["scored"]
    score_history.record_stock_scores(db_session, [(a.id, 0.8, MODEL)], 0.4, universe=[a.id, b.id, c.id])
    assert len(_rows(db_session, sid_b)) == 1, "a repeat writes nothing more"


def test_missing_rows_are_written_even_when_nothing_at_all_was_scored(db_session, monkeypatch):
    a = _instrument(db_session, "ALLMISS389")
    _candle(db_session, a, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    assert score_history.record_stock_scores(db_session, [], 0.4, universe=[a.id]) == 0
    assert [r.status for r in _rows(db_session, resolve(db_session, symbol="ALLMISS389"))] == ["missing"]


def test_without_a_universe_no_missing_rows_are_invented(db_session, monkeypatch):
    a, b = _instrument(db_session, "NOUNI389A"), _instrument(db_session, "NOUNI389B")
    _candle(db_session, a, FRIDAY)
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    score_history.record_stock_scores(db_session, [(a.id, 0.8, MODEL)], 0.4)
    assert resolve(db_session, symbol="NOUNI389B") is None and b.id


def test_a_failing_missing_writer_never_stops_the_scan(db_session, monkeypatch):
    a, b = _instrument(db_session, "BOOM389A"), _instrument(db_session, "BOOM389B")

    def boom(*args, **kwargs):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(ledger, "append_missing_for_universe", boom)
    assert score_history.record_stock_scores(db_session, [(a.id, 0.8, MODEL)], 0.4, today=FRIDAY, universe=[a.id, b.id]) == 1
    assert db_session.scalar(select(StockScore.score).where(StockScore.instrument_id == a.id)) == 0.8


def test_the_followed_stocks_scan_passes_its_whole_universe(db_session, monkeypatch):
    """held_read.score_tracked_stocks: every followed stock is the universe; one that cannot be scored is a gap."""
    from swing_trade_ml.services import held_read

    scored, unscored = _instrument(db_session, "FOL389A"), _instrument(db_session, "FOL389B")
    for inst in (scored, unscored):
        _candle(db_session, inst, FRIDAY)
    user = User(username="fol389", email="fol389@example.com", hashed_password="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    for symbol in ("FOL389A", "FOL389B"):
        db_session.add(UserWatchlistItem(user_id=user.id, symbol=symbol, added_at=date(2026, 11, 1)))
    db_session.flush()

    class _Impl:
        def min_bars_required(self):
            return 1

        def evaluate(self, df, instrument, db):
            if instrument.tradingsymbol == "FOL389B":
                return None
            return SimpleNamespace(features={"probability": 0.66, "model": MODEL})

    strategy = Strategy(name="fol389_strategy", strategy_type="ml_swing", params={}, is_active=True)
    db_session.add(strategy)
    db_session.flush()
    monkeypatch.setattr(held_read, "_reference_strategies", lambda db: {"large": strategy})
    import swing_trade_ml.strategies as strategies

    monkeypatch.setattr(strategies, "get_strategy", lambda s: _Impl())
    import swing_trade_ml.ml.dataset as dataset

    monkeypatch.setattr(dataset, "load_candles", lambda db, iid, interval, limit=None: pd.DataFrame({"close": [1.0]}))
    _at(monkeypatch, datetime(2026, 11, 20, 15, 50, tzinfo=IST))
    held_read.score_tracked_stocks(db_session)
    assert [r.status for r in _rows(db_session, resolve(db_session, symbol="FOL389A"))] == ["scored"]
    assert [r.status for r in _rows(db_session, resolve(db_session, symbol="FOL389B"))] == ["missing"]
