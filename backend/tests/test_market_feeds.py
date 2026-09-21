import json
from datetime import date

from sqlalchemy import func, select

from swing_trade_ml.db.models.feeds import BlockDeal, DailyDelivery, InstitutionalFlow
from swing_trade_ml.services import market_feeds

BHAVCOPY = (
    b"SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE,"
    b" AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
    b"20MICRONS, EQ, 18-Sep-2026, 205.71, 207.77, 209.00, 204.62, 206.50, 208.28, 207.02, 45744, 94.70, 1711, 21567, 47.15\n"
    b"TRADEBE, BE, 18-Sep-2026, 10.0, 10.0, 10.5, 9.9, 10.2, 10.2, 10.1, 1000, 1.0, 20, 900, 90.00\n"
    b"NODELIV, EQ, 18-Sep-2026, 50, 50, 51, 49, 50, 50, 50, 100, 0.5, 5, -, -\n"
    b"BONDX, N1, 18-Sep-2026, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 5, 0.5, 1, -, -\n"
    b"OLDDAY, EQ, 17-Sep-2026, 5, 5, 5, 5, 5, 5, 5, 5, 0.1, 1, 5, 100\n"
)

BULK = (
    b"Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
    b"18-SEP-2026,AHCL,Anlon Healthcare Limited,NK SECURITIES,BUY,5160805,23.52,-\n"
)


def test_bhavcopy_keeps_equity_series_and_reads_missing_delivery_as_none():
    rows = market_feeds.parse_bhavcopy(BHAVCOPY)

    by_symbol = {r["symbol"]: r for r in rows}
    assert set(by_symbol) == {"20MICRONS", "TRADEBE", "NODELIV", "OLDDAY"}  # bond series dropped
    assert by_symbol["20MICRONS"]["delivery_pct"] == 47.15
    assert by_symbol["20MICRONS"]["trade_date"] == date(2026, 9, 18)
    assert by_symbol["TRADEBE"]["series"] == "BE"  # trade-for-trade stays visible
    assert by_symbol["NODELIV"]["delivery_pct"] is None


def test_loading_a_day_stores_only_that_day_and_twice_is_a_no_op(db_session, monkeypatch):
    monkeypatch.setattr(market_feeds, "fetch", lambda url: BHAVCOPY)

    first = market_feeds.load_bhavcopy(db_session, date(2026, 9, 18))
    second = market_feeds.load_bhavcopy(db_session, date(2026, 9, 18))

    assert first == 3  # the 17 Sep row inside the file is not this day's
    assert second == 0
    assert db_session.execute(select(func.count(DailyDelivery.id))).scalar_one() == 3


def test_a_day_nse_has_no_file_for_is_none_not_an_error(db_session, monkeypatch):
    monkeypatch.setattr(market_feeds, "fetch", lambda url: None)

    assert market_feeds.load_bhavcopy(db_session, date(2026, 9, 19)) is None


def test_deals_are_stored_once(db_session, monkeypatch):
    monkeypatch.setattr(market_feeds, "fetch", lambda url: BULK)

    market_feeds.load_deals(db_session)
    market_feeds.load_deals(db_session)

    # bulk and block both point at the same fake file: two kinds, each once.
    assert db_session.execute(select(func.count(BlockDeal.id))).scalar_one() == 2
    kinds = set(db_session.execute(select(BlockDeal.kind)).scalars())
    assert kinds == {"bulk", "block"}


def test_fii_dii_flows_are_parsed_and_deduplicated(db_session, monkeypatch):
    payload = json.dumps(
        [
            {"buyValue": "17310.04", "category": "DII", "date": "18-Sep-2026",
             "netValue": "1019.69", "sellValue": "16290.35"},
            {"buyValue": "38461.63", "category": "FII/FPI", "date": "18-Sep-2026",
             "netValue": "-599.54", "sellValue": "37862.09"},
        ]
    ).encode()
    monkeypatch.setattr(market_feeds, "fetch", lambda url: payload)

    market_feeds.load_fii_dii(db_session)
    market_feeds.load_fii_dii(db_session)

    rows = {r.category: r for r in db_session.execute(select(InstitutionalFlow)).scalars()}
    assert set(rows) == {"FII", "DII"}
    assert rows["FII"].net_value == -599.54


def test_one_failing_feed_does_not_stop_the_others(db_session, monkeypatch):
    def fetch(url):
        if "fiidii" in url:
            raise RuntimeError("NSE blocked us")
        if "bhavdata" in url:
            return None
        return BULK

    monkeypatch.setattr(market_feeds, "fetch", fetch)

    run = market_feeds.run_daily_feeds(db_session, today=date(2026, 9, 21))

    assert "institutional_flows" in run.errors
    assert run.added["deals"] == 2
    assert "delivery" not in run.errors


def test_status_endpoint_reports_latest_dates(client, db_session):
    resp = client.get("/api/v1/market-data/feeds/status", headers={"X-API-Key": "test-api-key"})

    assert resp.status_code == 200
    assert resp.json()["delivery"]["rows"] == 0


def test_history_backfill_is_bounded_per_call(db_session, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(market_feeds, "fetch", lambda url: calls.append(url))
    monkeypatch.setattr(market_feeds, "BACKFILL_PAUSE_SECONDS", 0)

    result = market_feeds.backfill_history_step(
        db_session, today=date(2026, 9, 21), lookback_days=60, max_fetches=5
    )

    assert len(calls) == 5
    assert result["still_missing"] > 0
