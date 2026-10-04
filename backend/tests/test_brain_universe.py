"""Which stocks the brain looks at: the watchlist plus every stock version 1's
active auto-trading strategies scan, so the brain and version 1 are compared
on the same ground. The brain strategy's own scan uses the same list."""

from __future__ import annotations

from datetime import UTC, datetime

from brain_m18_fixtures import brain_strategy, v1_strategy
from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.brain.universe import brain_universe
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.engine import eligible_instruments

AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _inst(db, symbol: str, token: int, *, watch: bool = False, active: bool = True) -> Instrument:
    inst = Instrument(
        instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_watchlisted=watch, is_active=active
    )
    db.add(inst)
    db.flush()
    return inst


def _v1(db, name: str, symbols: list[str], **kw):
    s = v1_strategy(db, name=name, **kw)
    s.symbols = symbols
    db.flush()
    return s


def test_the_brain_looks_at_the_watchlist_and_version_1s_stocks(db_session):
    _inst(db_session, "UNIWATCH", 993001, watch=True)
    _inst(db_session, "UNIMID", 993002)
    _inst(db_session, "UNISMALL", 993003)
    _v1(db_session, "uni-mid", ["unimid"])
    _v1(db_session, "uni-small", ["UNISMALL", "UNIWATCH"])

    universe = brain_universe(db_session)

    assert {"UNIWATCH", "UNIMID", "UNISMALL"} <= set(universe)
    assert list(universe) == sorted(set(universe))  # sorted, each stock once


def test_stocks_only_an_inactive_or_advisory_strategy_scans_are_left_out(db_session):
    _inst(db_session, "UNIOFF", 993011)
    _inst(db_session, "UNIREAL", 993012)
    off = _v1(db_session, "uni-off", ["UNIOFF"])
    off.is_active = False
    _v1(db_session, "uni-real", ["UNIREAL"], execution_mode="advisory")
    db_session.flush()

    universe = brain_universe(db_session)

    assert "UNIOFF" not in universe and "UNIREAL" not in universe


def test_unknown_or_inactive_instruments_are_left_out(db_session):
    _inst(db_session, "UNIGONE", 993021, active=False)
    _v1(db_session, "uni-gone", ["UNIGONE", "UNINOSUCH"])

    universe = brain_universe(db_session)

    assert "UNIGONE" not in universe and "UNINOSUCH" not in universe


def test_the_brains_own_symbol_list_does_not_feed_its_universe(db_session):
    _inst(db_session, "UNISELF", 993031)
    brain_strategy(db_session, name="uni-brain", symbols=["UNISELF"])

    assert "UNISELF" not in brain_universe(db_session)


def test_the_dated_reader_uses_the_brain_universe(db_session):
    _inst(db_session, "UNIREAD", 993041)
    _v1(db_session, "uni-read", ["UNIREAD"])

    assert "UNIREAD" in DatedReader(db_session, as_of=AS_OF, live=False).universe()


def test_the_brain_strategy_scans_the_brain_universe(db_session):
    _inst(db_session, "UNISCAN", 993051)
    _v1(db_session, "uni-scan", ["UNISCAN"])
    brain = brain_strategy(db_session, name="uni-scan-brain")

    symbols = {i.tradingsymbol for i in eligible_instruments(db_session, brain)}

    assert "UNISCAN" in symbols


def test_a_version_1_strategy_with_no_symbols_still_scans_only_the_watchlist(db_session):
    _inst(db_session, "UNIW1", 993061, watch=True)
    _inst(db_session, "UNINOTW", 993062)
    _v1(db_session, "uni-other", ["UNINOTW"])
    plain = _v1(db_session, "uni-plain", [])

    symbols = {i.tradingsymbol for i in eligible_instruments(db_session, plain)}

    assert "UNIW1" in symbols and "UNINOTW" not in symbols
