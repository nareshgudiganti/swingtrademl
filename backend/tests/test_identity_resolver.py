"""The identity resolver contract (#389, IDENTITY-CONTRACTS.md section 1), on an in-memory store. No DB."""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.services import identity
from swing_trade_ml.services.identity import resolve
from swing_trade_ml.services.identity.memory import InMemoryStore

RELIANCE_ISIN = "INE002A01018"
TCS_ISIN = "INE467B01029"
LONG_AGO = date(2000, 1, 1)


@pytest.fixture()
def store():
    s = InMemoryStore()
    with identity.use_store(s):
        yield s


@pytest.fixture()
def two_stocks(store):
    ril = store.add_security(RELIANCE_ISIN, "Reliance")
    store.add_symbol(ril, "RELIANCE", LONG_AGO)
    store.add_alias(ril, "kite_token", "738561")
    store.add_alias(ril, "groww", RELIANCE_ISIN)
    tcs = store.add_security(TCS_ISIN, "TCS")
    store.add_symbol(tcs, "TCS", LONG_AGO)
    store.add_alias(tcs, "kite_token", "2953217")
    return {"ril": ril, "tcs": tcs}


def test_the_default_store_knows_nothing():
    assert resolve(None, symbol="RELIANCE") is None
    assert resolve(None, isin=RELIANCE_ISIN) is None


def test_nothing_given_is_nothing_found(two_stocks):
    assert resolve(None) is None


def test_one_stock_resolves_by_isin_token_or_symbol_to_the_same_id(two_stocks):
    ids = {
        resolve(None, isin=RELIANCE_ISIN),
        resolve(None, token=738561),
        resolve(None, token="738561"),
        resolve(None, symbol="RELIANCE"),
        resolve(None, symbol=" reliance "),
        resolve(None, symbol="RELIANCE", isin=RELIANCE_ISIN, token=738561),
    }
    assert ids == {two_stocks["ril"]}
    assert resolve(None, symbol="TCS") == two_stocks["tcs"] != two_stocks["ril"]


def test_an_unknown_stock_is_none_never_created(store, two_stocks):
    assert resolve(None, symbol="NOSUCH") is None
    assert resolve(None, isin="INE000000000") is None
    assert resolve(None, token=1) is None
    assert store.id_by_isin("INE000000000") is None  # still nothing created


@pytest.mark.parametrize(
    "kwargs",
    [
        {"isin": "not-an-isin"},
        {"isin": "INE002A0101"},  # 11 characters
        {"isin": ""},
        {"token": "abc"},
        {"token": 0},
        {"token": -5},
        {"token": True},
        {"symbol": ""},
        {"symbol": "has space"},
        {"symbol": "X" * 65},
    ],
)
def test_a_malformed_identifier_is_refused_not_guessed(two_stocks, kwargs):
    assert resolve(None, **kwargs) is None


def test_a_malformed_identifier_refuses_even_when_another_would_resolve(two_stocks):
    assert resolve(None, symbol="RELIANCE", isin="garbage") is None


def test_an_unknown_identifier_is_ignored_when_another_one_resolves(two_stocks):
    """A freshly re-issued token is not recorded yet: the symbol still finds the stock."""
    assert resolve(None, token=999999, symbol="RELIANCE") == two_stocks["ril"]


def test_identifiers_that_name_different_stocks_give_none(two_stocks):
    assert resolve(None, symbol="TCS", isin=RELIANCE_ISIN) is None
    assert resolve(None, token=738561, symbol="TCS") is None


def test_a_rename_keeps_the_id_and_old_dates_resolve_by_the_old_symbol(store):
    sid = store.add_security("INE111A01011", "Renamed Co")
    store.add_symbol(sid, "OLDNAME", date(2010, 1, 1), date(2026, 5, 31))
    store.add_symbol(sid, "NEWNAME", date(2026, 6, 1))
    assert resolve(None, symbol="OLDNAME", on_date=date(2025, 1, 1)) == sid
    assert resolve(None, symbol="NEWNAME", on_date=date(2026, 7, 1)) == sid
    assert resolve(None, symbol="OLDNAME", on_date=date(2026, 7, 1)) is None  # not valid any more
    assert resolve(None, symbol="NEWNAME", on_date=date(2025, 1, 1)) is None  # not valid yet
    ref = identity.get_ref(None, sid, on_date=date(2025, 1, 1))
    assert ref is not None and ref.symbol == "OLDNAME" and ref.id == sid
    assert identity.get_ref(None, sid, on_date=date(2026, 7, 1)).symbol == "NEWNAME"


def test_a_symbol_reused_by_another_company_resolves_by_date(store):
    first = store.add_security("INE222A01012", "First Co")
    store.add_symbol(first, "SHARED", date(2010, 1, 1), date(2020, 12, 31))
    second = store.add_security("INE333A01013", "Second Co")
    store.add_symbol(second, "SHARED", date(2021, 1, 1))
    assert resolve(None, symbol="SHARED", on_date=date(2015, 6, 1)) == first
    assert resolve(None, symbol="SHARED", on_date=date(2023, 6, 1)) == second


def test_a_reissued_token_is_an_alias_of_the_same_stock(store):
    sid = store.add_security("INE444A01014", "Token Co")
    store.add_symbol(sid, "TOKCO", LONG_AGO)
    store.add_alias(sid, "kite_token", "100")
    store.add_alias(sid, "kite_token", "200")  # the new token; the old one still resolves
    assert resolve(None, token=100) == resolve(None, token=200) == sid


def test_a_delisted_stock_still_resolves_and_keeps_its_history(store):
    sid = store.add_security("INE555A01015", "Gone Co", status="delisted")
    store.add_symbol(sid, "GONE", date(2010, 1, 1), date(2024, 3, 31))
    assert resolve(None, symbol="GONE", on_date=date(2023, 1, 1)) == sid
    assert identity.get_ref(None, sid, on_date=date(2023, 1, 1)).status == "delisted"


def test_a_symbol_with_no_history_row_resolves_through_the_instruments_row(store):
    sid = store.add_security(None, "Pending ISIN Co")
    store.add_instrument(sid, "PENDING")
    assert resolve(None, symbol="PENDING") == sid
    assert identity.get_ref(None, sid).isin is None


def test_the_same_isin_cannot_belong_to_two_securities(store):
    store.add_security("INE666A01016")
    with pytest.raises(ValueError):
        store.add_security("INE666A01016")


def test_two_exchanges_one_isin_one_security(store):
    sid = store.add_security("INE777A01017", "Dual Co")
    store.add_symbol(sid, "DUALCO", LONG_AGO, exchange="NSE")
    store.add_symbol(sid, "DUALCO-BSE", LONG_AGO, exchange="BSE")
    assert resolve(None, symbol="DUALCO") == sid
    assert resolve(None, symbol="DUALCO-BSE", exchange="BSE") == sid
    assert resolve(None, isin="INE777A01017") == sid


def test_resolve_never_writes(store, two_stocks):
    before = (dict(store._aliases), dict(store._securities), dict(store._instruments))
    for _ in range(3):
        resolve(None, symbol="RELIANCE", isin=RELIANCE_ISIN, token=738561)
        resolve(None, symbol="UNKNOWN")
    assert (store._aliases, store._securities, store._instruments) == before
