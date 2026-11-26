"""Late and corrected candles shown to a person (#565, requirements #282 G10 / A2). Read-only, admin-only.

A bar is "late" when it first reached us after the next trading session opened (09:15 IST on the next trading
day), so it could not have been used before that morning's decisions. Scratch test database."""

from __future__ import annotations

from datetime import UTC, datetime

from swing_trade_ml.db.models.market import CandleArrival, CandleCorrection, Instrument
from swing_trade_ml.services.admin_candle_log import build_candle_log
from test_admin_console import enrol, make_user, stepped

URL = "/api/v1/admin/console/candle-log"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
# Daily candles are stamped IST midnight = 18:30 UTC the previous day.
DAY_25 = datetime(2026, 11, 24, 18, 30, tzinfo=UTC)  # bar for Wed 25 Nov (24 Nov was a holiday)
DAY_26 = datetime(2026, 11, 25, 18, 30, tzinfo=UTC)  # bar for Thu 26 Nov


def _inst(db, sym, token):
    inst = Instrument(instrument_token=token, tradingsymbol=sym, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def _arrive(db, inst, ts, received):
    db.add(CandleArrival(instrument_id=inst.id, interval="day", ts=ts, received_at=received))
    db.flush()


def test_a_bar_received_after_the_next_session_opened_is_late_and_an_on_time_one_is_not(db_session):
    a = _inst(db_session, "LATE565", 985651)
    b = _inst(db_session, "ONTIME565", 985652)
    # 25 Nov bar first seen 26 Nov 10:00 IST (04:30 UTC): after the 09:15 open, late by about 45 minutes
    _arrive(db_session, a, DAY_25, datetime(2026, 11, 26, 4, 30, tzinfo=UTC))
    # 25 Nov bar first seen 25 Nov 19:00 IST: in time
    _arrive(db_session, b, DAY_25, datetime(2026, 11, 25, 13, 30, tzinfo=UTC))
    out = build_candle_log(db_session, now=NOW)
    late = [r for r in out["late"] if r["symbol"] in {"LATE565", "ONTIME565"}]
    assert [(r["symbol"], r["day"]) for r in late] == [("LATE565", "2026-11-25")]
    assert late[0]["due_by"].startswith("2026-11-26T09:15")
    assert late[0]["received_at"].startswith("2026-11-26T10:00")


def test_a_correction_shows_the_old_and_new_close_on_its_india_day(db_session):
    inst = _inst(db_session, "FIX565", 985653)
    db_session.add(
        CandleCorrection(
            instrument_id=inst.id,
            interval="day",
            ts=DAY_26,
            old_open=1,
            old_high=1,
            old_low=1,
            old_close=100.0,
            old_volume=10,
            new_open=1,
            new_high=1,
            new_low=1,
            new_close=102.0,
            new_volume=12,
            corrected_at=datetime(2026, 11, 26, 14, 0, tzinfo=UTC),
        )
    )
    db_session.flush()
    rows = [r for r in build_candle_log(db_session, now=NOW)["corrections"] if r["symbol"] == "FIX565"]
    assert len(rows) == 1
    r = rows[0]
    assert r["day"] == "2026-11-26"  # IST day, not the UTC stamp's 25 Nov
    assert (r["old_close"], r["new_close"], r["close_change_pct"]) == (100.0, 102.0, 0.02)
    assert (r["old_volume"], r["new_volume"]) == (10, 12)


def test_only_the_window_is_listed_and_the_rule_is_stated(db_session):
    inst = _inst(db_session, "OLD565", 985654)
    old = datetime(2026, 9, 1, 18, 30, tzinfo=UTC)
    _arrive(db_session, inst, old, datetime(2026, 9, 10, 4, 30, tzinfo=UTC))
    out = build_candle_log(db_session, now=NOW, days=30)
    assert all(r["symbol"] != "OLD565" for r in out["late"])
    assert out["window_days"] == 30
    assert "09:15" in out["late_rule"]
    assert out["unknown_note"]  # bars stored before arrivals were recorded have no arrival time


def test_route_is_admin_only_and_read_only(client, db_session):
    _u, hdr = make_user(db_session, "plain_member")
    assert client.get(URL, headers=hdr).status_code == 403
    assert client.get(URL, headers={"X-API-Key": "test-api-key"}).status_code == 403
    assert client.get(URL).status_code == 401
    _a, h, _s, body = enrol(client, db_session)
    res = client.get(URL, headers=stepped(h, body["step_up_token"]))
    assert res.status_code == 200
    assert set(res.json()) >= {"late", "corrections", "late_rule", "window_days"}
    assert client.post(URL, headers=stepped(h, body["step_up_token"])).status_code == 405
