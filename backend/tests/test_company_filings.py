"""The Company and news tab: parsing NSE filings and the plain-words rules. No database, no network."""

from datetime import date

from swing_trade_ml.services import company_filings as cf

# Shapes copied from NSE's real answers for KEI on 26 Oct 2026 (trimmed).
ANN = {
    "symbol": "KEI",
    "seq_id": "106825358",
    "an_dt": "22-Oct-2026 19:08:27",
    "desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
    "attchmntText": "KEI Industries Limited has informed the Exchange about Schedule of meet",
    "attchmntFile": "https://nsearchives.nseindia.com/corporate/KEI_22102026190810_INTIMATION.pdf",
}
SH = {
    "symbol": "KEI",
    "date": "30-SEP-2026",
    "submissionDate": "16-OCT-2026",
    "pr_and_prgrp": "35",
    "public_val": "65",
}


def test_announcements_parse_in_ist_newest_first():
    older = {**ANN, "seq_id": "1", "an_dt": "08-Oct-2026 16:18:43"}
    rows = cf.parse_announcements([older, ANN])
    assert [r["seq_id"] for r in rows] == ["106825358", "1"]
    assert rows[0]["announced_at"].utcoffset().total_seconds() == 19800  # +05:30
    assert rows[0]["announced_at"].hour == 19
    assert rows[0]["source"] == "nse"


def test_announcement_without_id_or_time_is_dropped():
    assert cf.parse_announcements([{**ANN, "seq_id": ""}, {**ANN, "an_dt": "not a date"}]) == []


def test_shareholding_parses():
    rows, rejected = cf.parse_shareholding([SH])
    assert rejected == []
    assert rows[0]["as_of"] == date(2026, 9, 30)
    assert rows[0]["filed_on"] == date(2026, 10, 16)
    assert (rows[0]["promoter_pct"], rows[0]["public_pct"]) == (35.0, 65.0)


def test_shareholding_that_does_not_add_to_100_is_rejected_and_reported():
    rows, rejected = cf.parse_shareholding([{**SH, "public_val": "50"}])
    assert rows == []
    assert "not 100%" in rejected[0]


def test_shareholding_with_a_missing_field_is_rejected():
    rows, rejected = cf.parse_shareholding([{**SH, "pr_and_prgrp": ""}])
    assert rows == [] and rejected


def test_a_quarter_filed_twice_keeps_the_later_filing():
    later = {**SH, "submissionDate": "20-OCT-2026", "pr_and_prgrp": "34.9", "public_val": "65.1"}
    rows, _ = cf.parse_shareholding([SH, later])
    assert len(rows) == 1 and rows[0]["promoter_pct"] == 34.9


def test_price_position_wording():
    near_low = "37% below its 1-year high, close to its lowest point of the year"
    assert cf.price_position_text(63, 100, 60) == near_low
    assert cf.price_position_text(80, 100, 60) == "20% below its 1-year high"
    assert cf.price_position_text(99, 100, 60) == "At or very close to its 1-year high"


def test_wording_is_deterministic_and_never_gives_advice():
    facts = ["37% below its 1-year high", "founders and promoters hold 35%"]
    first = cf.headline_text(facts)
    assert first == cf.headline_text(facts)
    assert cf.headline_text([]) is None
    text = " ".join([first, cf.ownership_text(35, 65), cf.price_position_text(63, 100, 60)]).lower()
    for word in ("buy", "sell", "cheap", "expensive", "undervalued", "overvalued"):
        assert word not in text


def test_freshness_states():
    today = date(2026, 10, 26)
    assert cf._state(None, today, 60) == "not_available"
    assert cf._state(date(2026, 10, 22), today, 60) == "ok"
    assert cf._state(date(2026, 6, 1), today, 60) == "out_of_date"


# ------------------------------------------------------------------ database --

from datetime import UTC, datetime, time  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from swing_trade_ml.db.models.market import Candle, Instrument  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
TODAY = date(2026, 10, 26)


def _stock(db, symbol="KEI", token=910001):
    inst = Instrument(instrument_token=token, tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def _bar(db, inst, day, close, high, low):
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime.combine(day, time(0, 0), tzinfo=IST).astimezone(UTC),
            open=close,
            high=high,
            low=low,
            close=close,
            volume=1000,
        )
    )


def test_storing_the_same_filings_twice_adds_nothing(db_session):
    first = cf.store(db_session, "KEI", [ANN], [SH])
    again = cf.store(db_session, "KEI", [ANN], [SH])
    assert (first.announcements_added, first.shareholding_added) == (1, 1)
    assert (again.announcements_added, again.shareholding_added) == (0, 0)


def test_view_with_no_data_says_not_available_never_a_guess(db_session):
    view = cf.build_view(db_session, "ZZNODATA", TODAY)
    assert view["headline"] is None
    assert view["results"]["state"] == "not_available"
    for key in ("price_position", "ownership", "announcements"):
        assert view[key]["state"] == "not_available"


def test_view_fills_blocks_with_source_and_date(db_session):
    inst = _stock(db_session)
    _bar(db_session, inst, date(2026, 3, 2), 6000, 6100, 5900)  # year high
    _bar(db_session, inst, date(2026, 10, 23), 3700, 3750, 3650)
    cf.store(db_session, "KEI", [ANN], [SH])
    view = cf.build_view(db_session, "KEI", TODAY)
    assert view["price_position"]["state"] == "ok"
    assert view["price_position"]["as_of"] == date(2026, 10, 23)
    assert view["price_position"]["text"].startswith("39% below its 1-year high")
    assert view["ownership"]["as_of"] == date(2026, 9, 30)
    assert view["ownership"]["text"].startswith("Founders and promoters hold 35%")
    assert view["announcements"]["as_of"] == date(2026, 10, 22)
    assert view["announcements"]["items"][0]["category"].startswith("Analysts")
    assert view["headline"].startswith("From the company's own filings")
    assert view["results"]["state"] == "not_available"


def test_old_shareholding_is_flagged_out_of_date_and_left_out_of_the_headline(db_session):
    cf.store(db_session, "KEI", [], [{**SH, "date": "31-MAR-2026", "submissionDate": "20-APR-2026"}])
    view = cf.build_view(db_session, "KEI", TODAY)
    assert view["ownership"]["state"] == "out_of_date"
    assert view["headline"] is None


def test_company_route_needs_a_login_and_returns_the_blocks(client, db_session):
    from swing_trade_ml.core.security import create_access_token
    from swing_trade_ml.db.models.session import User

    assert client.get("/api/v1/company/KEI").status_code in (401, 403)
    user = User(username="cotest", hashed_password="x", is_active=True, role="owner", plan="pro")
    db_session.add(user)
    db_session.flush()
    token = create_access_token(user.username, {"uid": user.id, "tv": 0})
    r = client.get("/api/v1/company/KEI", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "KEI"
    assert body["results"]["state"] == "not_available"
    assert "does not change the brain" in body["note"]
