"""Groww Tracker: pure rules (no DB) plus endpoint tests (DB)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from swing_trade_ml.api.v1.endpoints.my_watchlist import EXCHANGE
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import StockScore
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import watchlist_tracker as t

D = date(2026, 11, 2)


def _days(n: int, start: float = 100.0, step: float = 0.0):
    return [(D + timedelta(days=i), start + step * i) for i in range(n)]


# ---- pure rules ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ret", "days", "first", "today", "want"),
    [
        (-3.0, 0, None, None, "stop"),
        (-5.0, 0, None, None, "stop"),
        (-2.9, 0, None, None, "ok"),
        (5.0, 0, None, None, "target"),
        (4.9, 0, None, None, "ok"),
        (0.0, 13, None, None, "time"),
        (0.0, 12, None, None, "ok"),
        (0.0, 3, 70.0, 60.0, "weak"),
        (0.0, 3, 70.0, 60.1, "ok"),
        (0.0, 3, None, 40.0, "ok"),
        (None, 3, None, None, "ok"),
        (None, 14, 80.0, 50.0, "time"),
        (-3.5, 14, 80.0, 50.0, "stop"),  # stop beats time and weak
        (6.0, 14, 80.0, 50.0, "target"),  # target beats time
    ],
)
def test_state_priority(ret, days, first, today, want):
    assert t.state(ret, days, first, today) == want


def test_return_and_today_pct():
    assert t.return_pct(100.0, 105.0) == pytest.approx(5.0)
    assert t.return_pct(None, 105.0) is None
    assert t.return_pct(0.0, 105.0) is None
    assert t.today_pct([(D, 100.0), (D + timedelta(days=1), 102.0)]) == pytest.approx(2.0)
    assert t.today_pct([(D, 100.0)]) is None


def test_entry_fallbacks():
    closes = _days(4, 100, 1)
    # added on a candle day -> that day's close
    assert t.pick_entry(D, None, closes)[:2] == (100.0, "added_close")
    # added on a gap day -> first close after
    price, src, after = t.pick_entry(D - timedelta(days=2), None, closes)
    assert (price, src, len(after)) == (100.0, "added_close", 4)
    # added after the last candle -> nothing yet
    assert t.pick_entry(D + timedelta(days=9), None, closes) == (None, None, [])
    # user price wins
    assert t.pick_entry(D, 95.5, closes)[:2] == (95.5, "your_price")
    assert t.pick_entry(D, 0.0, closes)[1] == "added_close"  # a non-positive price is ignored


def test_days_done():
    assert t.days_done([]) == 0
    assert t.days_done(_days(1)) == 0
    assert t.days_done(_days(6)) == 5
    assert t.days_done(_days(40)) == t.HORIZON_DAYS


def test_ist_midnight_candle_maps_to_ist_date():
    ts = datetime(2026, 11, 1, 18, 30, tzinfo=UTC)  # IST midnight of 2 Nov
    assert t.ist_date(ts) == date(2026, 11, 2)


def test_build_item_shape_and_scores():
    added = datetime(2026, 11, 2, 5, 0, tzinfo=UTC)
    candles = [(D - timedelta(days=1), 99.0), *_days(3, 100, 2)]  # 99, 100, 102, 104
    scores = [(D - timedelta(days=3), 90.0), (D, 70.0), (D + timedelta(days=2), 55.0)]
    it = t.build_item(
        symbol="X", name="X Ltd", added_at=added, note=None, buy_price=None, candles=candles, scores=scores
    )
    assert it["entry_price"] == 100.0 and it["entry_source"] == "added_close"
    assert it["last_price"] == 104.0 and it["return_pct"] == pytest.approx(4.0)
    assert it["today_pct"] == pytest.approx((104 / 102 - 1) * 100)
    assert it["days_done"] == 2
    assert [c["date"] for c in it["closes"]] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert [s["date"] for s in it["scores"]] == ["2026-11-02", "2026-11-04"]  # none before added
    got = (it["score_first"], it["score_today"], it["score_prev"], it["score_delta"])
    assert got == (70.0, 55.0, 70.0, -15.0)
    assert it["state"] == "weak"


def test_build_item_without_data_is_safe():
    it = t.build_item(
        symbol="X", name=None, added_at=datetime(2026, 11, 2, tzinfo=UTC), note=None,
        buy_price=None, candles=[], scores=[],
    )
    assert it["return_pct"] is None and it["entry_price"] is None and it["state"] == "ok"
    assert it["closes"] == [] and it["scores"] == [] and it["last_price"] is None


# ---- endpoints (need the test DB) ----------------------------------------------------------

URL = "/api/v1/me/watchlist"


def _as(db, username):
    user = User(username=username, hashed_password="x", is_active=True, role="member", plan="free")
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def test_tracker_and_patch_endpoints(client, db_session):
    inst = Instrument(instrument_token=991_001, tradingsymbol="GRWTEST", name="Groww Test", exchange=EXCHANGE)
    db_session.add(inst)
    db_session.flush()
    start = datetime(2026, 11, 2, tzinfo=IST)
    for i, close in enumerate([100.0, 101.0, 96.0]):
        db_session.add(Candle(instrument_id=inst.id, interval="day", ts=start + timedelta(days=i),
                              open=close, high=close, low=close, close=close, volume=1))
    for i, sc in enumerate([70.0, 65.0]):
        day = D + timedelta(days=i)
        db_session.add(StockScore(instrument_id=inst.id, as_of=day, score=sc, band="strong"))
    user, me = _as(db_session, "grw-a")
    _, other = _as(db_session, "grw-b")
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="GRWTEST", added_at=start + timedelta(hours=6)))
    db_session.flush()

    r = client.get(f"{URL}/tracker", headers=me)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["horizon_days"] == 15 and body["as_of"] == "2026-11-04"
    item = body["items"][0]
    assert item["entry_price"] == 100.0 and item["entry_source"] == "added_close"
    assert item["return_pct"] == pytest.approx(-4.0) and item["state"] == "stop"
    assert item["days_done"] == 2 and item["score_delta"] == -5.0 and len(item["closes"]) == 3

    assert client.get(f"{URL}/tracker", headers=other).json()["items"] == []
    assert client.patch(f"{URL}/GRWTEST", json={"buy_price": 95.0}, headers=other).status_code == 404
    assert client.patch(f"{URL}/GRWTEST", json={"buy_price": -1}, headers=me).status_code == 422

    r = client.patch(f"{URL}/GRWTEST", json={"buy_price": 95.0}, headers=me)
    assert r.status_code == 200 and r.json()["buy_price"] == 95.0
    r = client.patch(f"{URL}/GRWTEST", json={"note": "bought in Groww"}, headers=me)
    assert r.json()["buy_price"] == 95.0 and r.json()["note"] == "bought in Groww"  # buy_price untouched
    item = client.get(f"{URL}/tracker", headers=me).json()["items"][0]
    assert item["entry_source"] == "your_price" and item["state"] == "ok"
    r = client.patch(f"{URL}/GRWTEST", json={"buy_price": None}, headers=me)
    assert r.json()["buy_price"] is None

    assert client.get(f"{URL}/tracker", headers={"X-API-Key": "test-api-key"}).status_code == 403
