"""NSE index constituent lists — the source of every stock's cap tier."""

from __future__ import annotations

from datetime import date

import pytest

from swing_trade_ml.db.models.feeds import IndexMembershipSnapshot
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services.market_feeds import INDEX_LISTS, parse_index_list

SAMPLE = (
    b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
    b"ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022\r\n"
    b"Adani Enterprises Ltd.,Metals & Mining,ADANIENT,EQ,INE423A01024\r\n"
)


def test_parses_symbol_tier_and_industry():
    rows = parse_index_list(SAMPLE, "large")
    assert rows == [
        {"symbol": "ABB", "tier": "large", "industry": "Capital Goods"},
        {"symbol": "ADANIENT", "tier": "large", "industry": "Metals & Mining"},
    ]


def test_all_three_tiers_have_urls():
    assert set(INDEX_LISTS) == {"large", "midcap", "smallcap"}
    for url in INDEX_LISTS.values():
        assert url.startswith("https://nsearchives.nseindia.com/")


def test_html_block_page_raises_rather_than_returning_no_rows():
    """NSE blocks bots without notice. An empty list would look like a
    successful empty day and silently wipe every tier on load."""
    with pytest.raises(ValueError, match="not a constituent CSV"):
        parse_index_list(b"<html><body>Access Denied</body></html>", "large")


def test_row_missing_symbol_is_skipped_not_fatal():
    content = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
        b"Broken Ltd.,Power,,EQ,INE000A01001\r\n"
        b"Good Ltd.,Power,GOOD,EQ,INE000A01002\r\n"
    )
    assert parse_index_list(content, "midcap") == [
        {"symbol": "GOOD", "tier": "midcap", "industry": "Power"}
    ]


def test_symbol_is_uppercased_and_stripped():
    content = (
        b"Company Name,Industry,Symbol,Series,ISIN Code\r\n"
        b"Spaced Ltd.,Power, good ,EQ,INE000A01002\r\n"
    )
    assert parse_index_list(content, "midcap")[0]["symbol"] == "GOOD"


def test_instrument_carries_tier_and_sector(db_session):
    inst = Instrument(
        instrument_token=99001, tradingsymbol="TIERTEST", exchange="NSE",
        cap_tier="midcap", sector="Power",
    )
    db_session.add(inst)
    db_session.flush()
    assert inst.cap_tier == "midcap"
    assert inst.sector == "Power"


def test_snapshot_is_unique_per_day_and_symbol(db_session):
    from sqlalchemy.exc import IntegrityError

    day = date(2026, 9, 25)
    db_session.add(
        IndexMembershipSnapshot(fetched_on=day, symbol="ABB", tier="large", industry="Capital Goods")
    )
    db_session.flush()
    db_session.add(
        IndexMembershipSnapshot(fetched_on=day, symbol="ABB", tier="midcap", industry="Capital Goods")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
