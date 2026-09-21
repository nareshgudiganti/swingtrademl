from datetime import UTC, date, datetime

import pytest

from swing_trade_ml.db.models.fills import BrokerFill
from swing_trade_ml.services import fills as fills_service
from swing_trade_ml.services.real_report import build_report


def _fill(db, tid, side, qty, price, when, symbol="ABC"):
    db.add(
        BrokerFill(
            trade_id=tid, symbol=symbol, exchange="NSE", side=side, quantity=qty,
            price=price, product="CNC", executed_at=when, source="api",
        )
    )
    db.flush()


def _at(y, m, d, h=10):
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def test_sale_is_matched_to_oldest_shares_first(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2026, 1, 5))
    _fill(db_session, "b2", "BUY", 10, 110, _at(2026, 2, 5))
    _fill(db_session, "s1", "SELL", 15, 120, _at(2026, 3, 5))

    report = build_report(db_session, None, None, None)

    slices = sorted(report["closed"], key=lambda c: c["buy_price"])
    assert [(c["quantity"], c["buy_price"], c["gross_pnl"]) for c in slices] == [
        (10, 100.0, 200.0),
        (5, 110.0, 50.0),
    ]
    assert report["summary"]["gross_pnl"] == 250.0
    assert report["summary"]["realized_pnl"] < 250.0  # charges came off
    assert report["summary"]["winning_sales"] == 2
    assert report["unmatched_sales"] == []


def test_period_reports_only_sales_in_it_but_matches_earlier_buys(db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2026, 1, 5))
    _fill(db_session, "s1", "SELL", 4, 90, _at(2026, 2, 5))
    _fill(db_session, "s2", "SELL", 6, 130, _at(2026, 4, 5))

    report = build_report(db_session, date(2026, 4, 1), date(2026, 4, 30), None)

    assert len(report["closed"]) == 1
    assert report["closed"][0]["buy_price"] == 100.0  # bought in January
    assert report["closed"][0]["gross_pnl"] == 180.0
    assert report["summary"]["sell_count"] == 1
    assert report["summary"]["buy_count"] == 0


def test_sale_with_no_recorded_buy_is_listed_not_guessed(db_session):
    _fill(db_session, "s1", "SELL", 5, 200, _at(2026, 3, 5), symbol="OLD")

    report = build_report(db_session, None, None, None)

    assert report["closed"] == []
    assert report["summary"]["realized_pnl"] == 0
    assert report["unmatched_sales"][0]["symbol"] == "OLD"
    assert report["unmatched_sales"][0]["quantity"] == 5


def test_open_holdings_come_from_zerodha(db_session):
    holdings = [{"symbol": "ABC", "quantity": 10, "average_price": 100, "last_price": 110, "pnl": 100}]

    report = build_report(db_session, None, None, holdings)

    assert report["summary"]["open_pnl"] == 100.0
    assert report["summary"]["open_value"] == 1100.0
    row = report["by_stock"][0]
    assert (row["symbol"], row["open_qty"], row["open_pnl"]) == ("ABC", 10, 100.0)


TRADEBOOK = (
    "symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time\n"
    "ABC,INE000A01011,2026-01-05,NSE,EQ,EQ,buy,false,10,100,T1,O1,2026-01-05T10:15:33\n"
    "ABC,INE000A01011,2026-03-05,NSE,EQ,EQ,sell,false,10,120,T2,O2,2026-03-05T11:00:00\n"
    "NIFTY,,2026-03-05,NFO,FO,,buy,false,50,10,T3,O3,2026-03-05T11:00:00\n"
)


def test_tradebook_import_reads_share_trades_and_ignores_the_rest(db_session):
    result = fills_service.import_tradebook_csv(db_session, TRADEBOOK.encode())

    assert (result.added, result.skipped) == (2, 1)
    report = build_report(db_session, None, None, None)
    assert report["closed"][0]["gross_pnl"] == 200.0


def test_importing_the_same_file_twice_stores_each_trade_once(db_session):
    fills_service.import_tradebook_csv(db_session, TRADEBOOK.encode())
    again = fills_service.import_tradebook_csv(db_session, TRADEBOOK.encode())

    assert again.added == 0
    assert again.already_stored == 2


def test_a_file_that_is_not_a_tradebook_is_refused(db_session):
    with pytest.raises(fills_service.TradebookError):
        fills_service.import_tradebook_csv(db_session, b"date,amount\n2026-01-01,5\n")


def test_daily_capture_keeps_only_delivery_trades_and_dedupes_with_the_file(db_session):
    fills_service.import_tradebook_csv(db_session, TRADEBOOK.encode())
    kite_trades = [
        {"trade_id": "T1", "order_id": "O1", "tradingsymbol": "ABC", "exchange": "NSE",
         "product": "CNC", "transaction_type": "BUY", "quantity": 10, "average_price": 100.0,
         "fill_timestamp": datetime(2026, 1, 5, 10, 15, 33)},
        {"trade_id": "T9", "order_id": "O9", "tradingsymbol": "XYZ", "exchange": "NSE",
         "product": "CNC", "transaction_type": "BUY", "quantity": 3, "average_price": 50.0,
         "fill_timestamp": datetime(2026, 9, 21, 10, 0, 0)},
        {"trade_id": "T10", "order_id": "O10", "tradingsymbol": "XYZ", "exchange": "NSE",
         "product": "MIS", "transaction_type": "BUY", "quantity": 3, "average_price": 50.0,
         "fill_timestamp": datetime(2026, 9, 21, 10, 0, 0)},
    ]

    result = fills_service.store_kite_trades(db_session, kite_trades)

    assert (result.added, result.already_stored, result.skipped) == (1, 1, 1)


HEADERS = {"X-API-Key": "test-api-key"}


def test_report_endpoint_requires_auth(client):
    assert client.get("/api/v1/real-report").status_code in (401, 403)


def test_report_endpoint_works_without_a_zerodha_login(client, db_session):
    _fill(db_session, "b1", "BUY", 10, 100, _at(2026, 1, 5))
    _fill(db_session, "s1", "SELL", 10, 120, _at(2026, 3, 5))

    resp = client.get("/api/v1/real-report", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["gross_pnl"] == 200.0
    assert body["summary"]["open_pnl"] is None
    assert body["holdings_note"]


def test_tradebook_upload_endpoint(client):
    resp = client.post(
        "/api/v1/real-report/import-tradebook",
        headers=HEADERS,
        files={"file": ("tradebook.csv", TRADEBOOK.encode(), "text/csv")},
    )
    assert resp.status_code == 200
    assert "Added 2 trades" in resp.json()["message"]

    bad = client.post(
        "/api/v1/real-report/import-tradebook",
        headers=HEADERS,
        files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert bad.status_code == 400
