# ruff: noqa: E501 (long lines in test code)
"""#389 step S1: securities, dated symbol history, aliases and the database-backed resolver (IDENTITY-CONTRACTS 1)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from swing_trade_ml.db.models.identity import Security, SecurityAlias, SecuritySymbol
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import identity
from swing_trade_ml.services.identity import resolve, writer

_tokens = iter(range(389_300, 389_900))
LONG_AGO = date(2000, 1, 1)


def _instrument(db, symbol: str, *, exchange: str = "NSE", token: int | None = None) -> Instrument:
    row = Instrument(
        instrument_token=token or next(_tokens),
        tradingsymbol=symbol,
        name=f"{symbol} Ltd",  # the same name under a new token is the same company
        exchange=exchange,
        instrument_type="EQ",
        segment=exchange,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _count(db, model) -> int:
    return len(list(db.scalars(select(model))))


def test_a_real_session_resolves_through_the_database(db_session):
    sid = writer.create_security(db_session, isin="INE389A01010", name="Alpha Co")
    writer.set_symbol(db_session, sid, "ALPHA389", LONG_AGO)
    writer.add_alias(db_session, sid, "kite_token", "389001")
    assert resolve(db_session, isin="INE389A01010") == sid
    assert resolve(db_session, symbol="ALPHA389") == sid
    assert resolve(db_session, token=389001) == sid
    assert resolve(db_session, symbol="alpha389", isin="INE389A01010", token="389001") == sid
    assert resolve(db_session, symbol="NOSUCH389") is None
    ref = identity.get_ref(db_session, sid)
    assert ref is not None and ref.isin == "INE389A01010" and ref.symbol == "ALPHA389"


def test_resolve_never_writes_to_the_database(db_session):
    before = (_count(db_session, Security), _count(db_session, SecurityAlias), _count(db_session, SecuritySymbol))
    for _ in range(2):
        assert resolve(db_session, symbol="NEVERMADE389", token=389_999, isin="INE000000000") is None
    after = (_count(db_session, Security), _count(db_session, SecurityAlias), _count(db_session, SecuritySymbol))
    assert after == before


def test_a_rename_keeps_the_id_and_old_dates_resolve_by_the_old_symbol(db_session):
    sid = writer.create_security(db_session, name="Renamer")
    writer.set_symbol(db_session, sid, "OLD389R", date(2010, 1, 1))
    writer.set_symbol(db_session, sid, "NEW389R", date(2026, 6, 1))
    assert resolve(db_session, symbol="OLD389R", on_date=date(2025, 1, 1)) == sid
    assert resolve(db_session, symbol="NEW389R", on_date=date(2026, 7, 1)) == sid
    assert resolve(db_session, symbol="OLD389R", on_date=date(2026, 7, 1)) is None
    assert identity.get_ref(db_session, sid, on_date=date(2025, 1, 1)).symbol == "OLD389R"
    writer.set_symbol(db_session, sid, "NEW389R", date(2026, 6, 1))  # idempotent
    assert _count(db_session, SecuritySymbol) >= 2


def test_a_symbol_reused_by_another_company_resolves_by_date(db_session):
    first = writer.create_security(db_session, name="First")
    writer.set_symbol(db_session, first, "SHARE389", date(2010, 1, 1))
    writer.mark_delisted(db_session, first, date(2020, 12, 31))
    second = writer.create_security(db_session, name="Second")
    writer.set_symbol(db_session, second, "SHARE389", date(2021, 1, 1))
    assert first != second
    assert resolve(db_session, symbol="SHARE389", on_date=date(2015, 6, 1)) == first
    assert resolve(db_session, symbol="SHARE389", on_date=date(2023, 6, 1)) == second
    assert identity.get_ref(db_session, first, on_date=date(2015, 6, 1)).status == "delisted"


def test_a_symbol_currently_used_by_another_security_is_a_conflict_not_a_guess(db_session):
    a = writer.create_security(db_session, name="A")
    b = writer.create_security(db_session, name="B")
    writer.set_symbol(db_session, a, "CLASH389", LONG_AGO)
    with pytest.raises(writer.IdentityConflictError):
        writer.set_symbol(db_session, b, "CLASH389", date(2026, 1, 1))


def test_an_isin_belongs_to_one_security(db_session):
    a = writer.create_security(db_session, isin="INE389B01011")
    assert writer.create_security(db_session, isin="INE389B01011") == a  # same ISIN, same security
    b = writer.create_security(db_session, name="No ISIN yet")
    with pytest.raises(writer.IdentityConflictError):
        writer.attach_isin(db_session, b, "INE389B01011")
    writer.attach_isin(db_session, b, "INE389C01012")
    writer.attach_isin(db_session, b, "INE389C01012")  # repeat: nothing changes
    assert resolve(db_session, isin="INE389C01012") == b
    with pytest.raises(writer.IdentityConflictError):
        writer.attach_isin(db_session, b, "INE389D01013")  # it already has one: never silently changed
    with pytest.raises(ValueError):
        writer.create_security(db_session, isin="bad")


def test_an_alias_belongs_to_one_security(db_session):
    a = writer.create_security(db_session)
    b = writer.create_security(db_session)
    writer.add_alias(db_session, a, "kite_token", "389777")
    writer.add_alias(db_session, a, "kite_token", "389777")
    with pytest.raises(writer.IdentityConflictError):
        writer.add_alias(db_session, b, "kite_token", "389777")


def test_the_backfill_gives_each_instrument_one_security_and_is_idempotent(db_session):
    inst = _instrument(db_session, "BACK389A")
    first = writer.backfill_instruments(db_session)
    assert first["added"] >= 1 and first["skipped"] == 0
    sid = resolve(db_session, symbol="BACK389A")
    assert sid is not None and resolve(db_session, token=inst.instrument_token) == sid
    counts = (_count(db_session, Security), _count(db_session, SecurityAlias), _count(db_session, SecuritySymbol))
    second = writer.backfill_instruments(db_session)
    assert second["added"] == 0
    assert (_count(db_session, Security), _count(db_session, SecurityAlias), _count(db_session, SecuritySymbol)) == counts


def test_a_reissued_token_is_another_alias_of_the_same_security(db_session):
    inst = _instrument(db_session, "REISSUE389", token=389_501)
    writer.backfill_instruments(db_session)
    sid = resolve(db_session, symbol="REISSUE389")
    inst.instrument_token = 389_502  # what the S0 sync does to the stored row
    db_session.flush()
    writer.backfill_instruments(db_session)
    assert resolve(db_session, token=389_502) == resolve(db_session, token=389_501) == sid
    assert resolve(db_session, symbol="REISSUE389") == sid, "still one security for the stock"
    assert len([s for s in db_session.scalars(select(Security)) if s.id == sid]) == 1


def test_a_renamed_instrument_keeps_its_security(db_session):
    inst = _instrument(db_session, "OLDINST389", token=389_511)
    writer.backfill_instruments(db_session)
    sid = resolve(db_session, symbol="OLDINST389")
    inst.tradingsymbol = "NEWINST389"  # the sync renames by token
    db_session.flush()
    writer.backfill_instruments(db_session)
    assert resolve(db_session, symbol="NEWINST389") == sid
    assert resolve(db_session, symbol="OLDINST389", on_date=date(2000, 6, 1)) in (None, sid)


def test_two_exchanges_one_isin_one_security(db_session):
    sid = writer.create_security(db_session, isin="INE389E01014")
    writer.set_symbol(db_session, sid, "DUAL389", LONG_AGO, exchange="NSE")
    writer.set_symbol(db_session, sid, "DUAL389B", LONG_AGO, exchange="BSE")
    assert resolve(db_session, symbol="DUAL389") == sid
    assert resolve(db_session, symbol="DUAL389B", exchange="BSE") == sid
    assert resolve(db_session, isin="INE389E01014") == sid


def test_discover_the_watchlist_and_a_report_row_resolve_one_security(db_session):
    """Cross-module identity: the instruments row (Discover), a watchlist row and a tracker symbol all resolve to
    the same security, with no new column on either table."""
    from swing_trade_ml.db.models.session import User

    inst = _instrument(db_session, "CROSS389")
    writer.backfill_instruments(db_session)
    user = User(username="iso389", email="iso389@example.com", hashed_password="x", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="CROSS389", added_at=date(2026, 11, 1)))
    db_session.flush()
    from_discover = resolve(db_session, token=inst.instrument_token)
    watch_symbol = db_session.scalar(select(UserWatchlistItem.symbol).where(UserWatchlistItem.user_id == user.id))
    from_watchlist = resolve(db_session, symbol=watch_symbol)
    from_report = resolve(db_session, symbol="cross389")
    assert from_discover is not None and from_discover == from_watchlist == from_report


def test_a_freshly_seeded_stock_resolves_for_dates_before_it_was_seeded(db_session):
    """The first symbol row is open-ended: the sync date says nothing about when the stock started trading."""
    inst = _instrument(db_session, "EARLY389")
    writer.ensure_for_instrument(db_session, inst)
    sid = resolve(db_session, symbol="EARLY389")
    assert sid is not None
    assert resolve(db_session, symbol="EARLY389", on_date=date(2019, 3, 4)) == sid
    assert resolve(db_session, symbol="EARLY389", on_date=date(2026, 11, 20)) == sid
    first = db_session.scalar(select(SecuritySymbol).where(SecuritySymbol.security_id == sid))
    assert first.valid_from == writer.EARLIEST and first.valid_to is None


def test_a_real_rename_seen_later_starts_the_new_symbol_today_and_keeps_the_old_one_for_before(db_session):
    from datetime import datetime

    from swing_trade_ml.core.market_session import IST

    inst = _instrument(db_session, "BEFORE389", token=389_551)
    writer.ensure_for_instrument(db_session, inst)
    sid = resolve(db_session, symbol="BEFORE389")
    inst.tradingsymbol = "AFTER389"
    db_session.flush()
    writer.ensure_for_instrument(db_session, inst)
    today = datetime.now(IST).date()
    assert resolve(db_session, symbol="AFTER389", on_date=today) == sid
    assert resolve(db_session, symbol="BEFORE389", on_date=date(2019, 3, 4)) == sid
    assert resolve(db_session, symbol="AFTER389", on_date=date(2019, 3, 4)) is None
