from datetime import date, datetime
from zoneinfo import ZoneInfo

from swing_trade_ml.api.v1.endpoints.system import _plain_status

IST = ZoneInfo("Asia/Kolkata")


def _status(now: datetime, *, authed: bool = False, candle: date = date(2026, 10, 1)):
    return _plain_status(
        broker_authenticated=authed,
        scheduler_running=True,
        latest_candle_date=candle,
        last_scan_at=datetime(2026, 10, 1, 15, 45, tzinfo=IST),
        now_ist=now,
    )


def test_weekend_logout_is_not_a_warning():
    # Sun 4 Oct 2026: token expired Saturday, auto-login next runs Monday.
    level, msg = _status(datetime(2026, 10, 4, 11, 0, tzinfo=IST))
    assert level == "ok"
    assert "Mon 05 Oct" in msg


def test_trading_day_logout_after_auto_login_is_a_warning():
    level, msg = _status(datetime(2026, 10, 5, 10, 0, tzinfo=IST), candle=date(2026, 10, 3))
    assert level == "warning"
    assert "Not logged into Zerodha" in msg


def test_trading_day_before_auto_login_is_not_a_warning():
    level, _ = _status(datetime(2026, 10, 5, 6, 5, tzinfo=IST), candle=date(2026, 10, 3))
    assert level == "ok"


def test_weekend_still_flags_stale_data():
    level, msg = _status(datetime(2026, 10, 4, 11, 0, tzinfo=IST), candle=date(2026, 9, 25))
    assert level == "warning"
    assert "hasn't updated" in msg
