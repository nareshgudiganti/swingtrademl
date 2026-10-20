"""Tax export of real (My Holdings / Zerodha) sales, one Indian financial year at a time.

Only the real Zerodha trades in `broker_fills` count. Sales are matched to the
oldest shares first (FIFO). Charges are the app's cost-model estimate. Nothing
here works out tax owed; it only sorts sales into short-term and long-term.
"""

from __future__ import annotations

import codecs
import csv
import io
from datetime import UTC, date, datetime

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Position, Strategy, Trade
from swing_trade_ml.services import tax_export
from swing_trade_ml.services.costs import compute_charges

HEADERS = {"X-API-Key": "test-api-key"}
URL = "/api/v1/real-report/tax"


def _fill(db, tid, side, qty, price, when, symbol="ABC"):
    db.add(
        BrokerFill(
            trade_id=tid,
            symbol=symbol,
            exchange="NSE",
            side=side,
            quantity=qty,
            price=price,
            product="CNC",
            executed_at=when,
            source="api",
        )
    )
    db.flush()


def _at(y, m, d, h=5):
    """05:00 UTC = 10:30 IST, safely inside the IST day."""
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def _cost(value, side):
    b, t = compute_charges(value, side)
    return b + t


# ----------------------------------------------------------- pure helpers --


def test_financial_year_runs_1_april_to_31_march():
    assert tax_export.fy_label(date(2026, 3, 31)) == "2025-26"
    assert tax_export.fy_label(date(2026, 4, 1)) == "2026-27"
    assert tax_export.fy_bounds("2025-26") == (date(2025, 4, 1), date(2026, 3, 31))


@pytest.mark.parametrize("bad", ["2025", "2025-27", "25-26", "abcd-ef", "2025-2026"])
def test_a_badly_written_year_is_refused(bad):
    with pytest.raises(ValueError):
        tax_export.fy_bounds(bad)


def test_twelve_months_or_less_is_short_term_more_is_long_term():
    buy = date(2025, 4, 10)
    assert tax_export.holding_type(buy, date(2026, 4, 10)) == "Short-term"  # exactly 12 months
    assert tax_export.holding_type(buy, date(2026, 4, 11)) == "Long-term"
    assert tax_export.holding_type(buy, date(2025, 4, 11)) == "Short-term"
    assert tax_export.holding_type(buy, buy) == "Same day (intraday)"
    # A leap-day buy: the year is up on 28 Feb.
    assert tax_export.holding_type(date(2024, 2, 29), date(2025, 2, 28)) == "Short-term"
    assert tax_export.holding_type(date(2024, 2, 29), date(2025, 3, 1)) == "Long-term"


# --------------------------------------------------------------- the build --


def test_sale_at_ist_midnight_belongs_to_the_new_year(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2026, 1, 5))
    # 31 Mar 18:45 UTC = 1 Apr 00:15 IST: the new financial year.
    _fill(db_session, "s1", "SELL", 5, 120, datetime(2026, 3, 31, 18, 45, tzinfo=UTC))
    # 31 Mar 18:15 UTC = 31 Mar 23:45 IST: still the old year.
    _fill(db_session, "s2", "SELL", 5, 130, datetime(2026, 3, 31, 18, 15, tzinfo=UTC))

    old = tax_export.build_tax_export(db_session, "2025-26")
    new = tax_export.build_tax_export(db_session, "2026-27")

    assert [(r["sell_date"], r["quantity"]) for r in old["rows"]] == [(date(2026, 3, 31), 5)]
    assert [(r["sell_date"], r["quantity"]) for r in new["rows"]] == [(date(2026, 4, 1), 5)]
    assert "2025-26" in old["years"] and "2026-27" in old["years"]


def test_partial_sells_are_matched_oldest_first_across_buys(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2025, 4, 7))
    _fill(db_session, "b2", "BUY", 10, 110, _at(2025, 5, 7))
    _fill(db_session, "s1", "SELL", 6, 120, _at(2025, 6, 2))  # 6 from b1
    _fill(db_session, "s2", "SELL", 9, 130, _at(2025, 7, 1))  # 4 from b1 + 5 from b2

    ex = tax_export.build_tax_export(db_session, "2025-26")

    got = [
        (r["buy_date"], r["sell_date"], r["quantity"], r["buy_value"], r["sell_value"]) for r in ex["rows"]
    ]
    assert got == [
        (date(2025, 4, 7), date(2025, 6, 2), 6, 600.0, 720.0),
        (date(2025, 4, 7), date(2025, 7, 1), 4, 400.0, 520.0),
        (date(2025, 5, 7), date(2025, 7, 1), 5, 550.0, 650.0),
    ]
    assert all(r["type"] == "Short-term" for r in ex["rows"])


def test_charges_come_off_the_gain(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2025, 4, 7))
    _fill(db_session, "s1", "SELL", 10, 120, _at(2025, 6, 2))

    ex = tax_export.build_tax_export(db_session, "2025-26")

    row = ex["rows"][0]
    expected = _cost(1000, "BUY") + _cost(1200, "SELL")
    assert row["charges"] == pytest.approx(expected, abs=0.01)
    assert row["charges"] > 0
    assert row["gain"] == pytest.approx(200 - expected, abs=0.01)
    assert ex["totals"]["charges"] == row["charges"]
    assert ex["totals"]["short_term"] == row["gain"]
    assert ex["totals"]["long_term"] == 0
    assert ex["charges_are_estimates"] is True


def test_long_and_short_term_have_separate_totals(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2024, 4, 1), symbol="OLD")
    _fill(db_session, "b2", "BUY", 10, 100, _at(2025, 9, 1), symbol="NEW")
    _fill(db_session, "s1", "SELL", 10, 150, _at(2025, 10, 1), symbol="OLD")
    _fill(db_session, "s2", "SELL", 10, 90, _at(2025, 10, 1), symbol="NEW")

    ex = tax_export.build_tax_export(db_session, "2025-26")

    by = {r["stock"]: r for r in ex["rows"]}
    assert by["OLD"]["type"] == "Long-term"
    assert by["NEW"]["type"] == "Short-term"
    assert ex["totals"]["long_term"] == by["OLD"]["gain"] > 0
    assert ex["totals"]["short_term"] == by["NEW"]["gain"] < 0


def test_a_sale_with_no_recorded_buy_is_flagged_not_guessed(db_session):
    _fill(db_session, "b1", "BUY", 3, 100, _at(2025, 5, 1))
    _fill(db_session, "s1", "SELL", 5, 200, _at(2025, 6, 1))  # 2 shares have no buy on record

    ex = tax_export.build_tax_export(db_session, "2025-26")

    matched = [r for r in ex["rows"] if not r["buy_missing"]]
    missing = [r for r in ex["rows"] if r["buy_missing"]]
    assert [r["quantity"] for r in matched] == [3]
    assert len(missing) == 1
    m = missing[0]
    assert (m["quantity"], m["sell_value"], m["buy_date"], m["buy_value"], m["gain"]) == (
        2,
        400.0,
        None,
        None,
        None,
    )
    assert m["type"] is None
    assert ex["totals"]["missing_buy_count"] == 1
    assert ex["totals"]["short_term"] == matched[0]["gain"]  # the flagged row is left out


def test_paper_and_tester_trades_are_never_included(db_session):
    """Bot and tester trades live in positions/trades, never in broker_fills."""
    inst = Instrument(instrument_token=771001, tradingsymbol="PAPERONLY", exchange="NSE")
    db_session.add(inst)
    books = []
    for name in ("tax_test_bot_book", "tester_paper"):
        s = db_session.query(Strategy).filter_by(name=name).one_or_none()
        if s is None:
            s = Strategy(name=name, strategy_type="ml_swing", mode="paper", params={})
            db_session.add(s)
        books.append(s)
    db_session.flush()
    for s in books:
        pos = Position(
            strategy_id=s.id,
            instrument_id=inst.id,
            mode="paper",
            quantity=10,
            entry_price=100.0,
            current_price=120.0,
            entry_at=_at(2025, 5, 1),
            status=PositionStatus.CLOSED,
        )
        db_session.add(pos)
        db_session.flush()
        db_session.add(
            Trade(
                position_id=pos.id,
                strategy_id=s.id,
                instrument_id=inst.id,
                mode="paper",
                symbol="PAPERONLY",
                quantity=10,
                entry_price=100.0,
                exit_price=120.0,
                entry_at=_at(2025, 5, 1),
                exit_at=_at(2025, 6, 1),
                holding_days=31,
                gross_pnl=200.0,
                charges=1.0,
                net_pnl=199.0,
                return_pct=1.99,
                is_win=True,
            )
        )
    db_session.flush()
    _fill(db_session, "b1", "BUY", 1, 100, _at(2025, 5, 1), symbol="REAL")
    _fill(db_session, "s1", "SELL", 1, 110, _at(2025, 6, 1), symbol="REAL")

    ex = tax_export.build_tax_export(db_session, "2025-26")

    assert [r["stock"] for r in ex["rows"]] == ["REAL"]


# --------------------------------------------------------------------- CSV --


def _csv_lines(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.lstrip(chr(0xFEFF)))))


def test_csv_header_is_plain_english_and_names_with_commas_stay_whole(db_session):
    _fill(db_session, "b1", "BUY", 2, 100, _at(2025, 5, 1), symbol="ODD,NAME")
    _fill(db_session, "s1", "SELL", 2, 110, _at(2025, 6, 1), symbol="ODD,NAME")
    _fill(db_session, "s2", "SELL", 1, 50, _at(2025, 6, 2), symbol="=CMD")

    text = tax_export.to_csv(tax_export.build_tax_export(db_session, "2025-26"))
    lines = _csv_lines(text)

    assert lines[0] == tax_export.CSV_HEADER
    assert lines[0][0] == "Stock"
    assert "Estimated charges (₹)" in lines[0]
    assert lines[1][0] == "ODD,NAME"
    assert len(lines[1]) == len(tax_export.CSV_HEADER)
    flagged = lines[2]
    assert flagged[0] == "'=CMD"  # a spreadsheet will not run it as a formula
    assert "Buy details missing" in flagged[-1]
    joined = "\n".join(",".join(line) for line in lines)
    assert "Short-term gain or loss after charges (₹)" in joined
    assert "check against Zerodha's Tax P&L (Console) and ask a tax adviser" in joined
    assert "first in, first out" in joined.lower()


# --------------------------------------------------------------------- API --


def test_api_returns_the_year_and_a_csv_download(client, db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2025, 4, 7))
    _fill(db_session, "s1", "SELL", 10, 120, _at(2025, 6, 2))

    r = client.get(f"{URL}?year=2025-26", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["year"] == "2025-26" and len(body["rows"]) == 1
    assert body["start"] == "2025-04-01" and body["end"] == "2026-03-31"

    c = client.get(f"{URL}.csv?year=2025-26", headers=HEADERS)
    assert c.status_code == 200
    assert c.headers["content-type"].startswith("text/csv")
    assert c.content.startswith(codecs.BOM_UTF8)  # Excel needs this to show the rupee sign
    assert "real-trades-tax-2025-26.csv" in c.headers["content-disposition"]
    assert _csv_lines(c.text)[0] == tax_export.CSV_HEADER


def test_api_defaults_to_this_year_and_refuses_a_bad_one(client):
    r = client.get(URL, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["year"] == tax_export.current_fy()
    assert client.get(f"{URL}?year=2025-27", headers=HEADERS).status_code == 400
    assert client.get(f"{URL}.csv?year=nope", headers=HEADERS).status_code == 400


@pytest.mark.parametrize("name,owner", [("vijay", True), ("someone", False)])
def test_only_the_real_account_user_may_export(client, db_session, monkeypatch, name, owner):
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "sudeeksha")
    user = User(username=name, hashed_password="x", is_active=True, is_superuser=owner, plan="free")
    db_session.add(user)
    db_session.flush()
    h = {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}
    assert client.get(URL, headers=h).status_code == 403
    assert client.get(f"{URL}.csv", headers=h).status_code == 403


def test_the_export_writes_nothing(client, db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2025, 4, 7))
    before = db_session.query(BrokerFill).count()
    client.get(f"{URL}.csv?year=2025-26", headers=HEADERS)
    assert db_session.query(BrokerFill).count() == before
    assert client.post(f"{URL}.csv", headers=HEADERS).status_code == 405
