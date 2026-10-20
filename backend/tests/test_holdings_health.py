"""Holdings health check (tracker ux7): plain-English warnings about what is held.

The rules are the settled ones, read from the code that already enforces them
(services/limits.py for the stock and sector caps, settings for the -4% stop and
the 15-trading-day plan) — never numbers of its own. Read-only: nothing here
places an order or changes a stop, a size or a limit. Each book is checked on
its own, and the real (My Holdings) book stays private to REAL_ACCOUNT_USERS.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services import holdings_health as hh
from swing_trade_ml.services.limits import limits_for

# --------------------------------------------------------------------------
# Pure rules
# --------------------------------------------------------------------------

SMALL = limits_for(10_000)  # one stock per sector
MID = limits_for(1_000_000)  # 10% per stock, 25% per sector


def _h(symbol="TCS", value=10_000.0, entry=100.0, stop=96.0, day=3, cap=None, sector="IT", results_on=None):
    return hh.Holding(
        symbol=symbol,
        value=value,
        entry_price=entry,
        stop_loss=stop,
        day=day,
        max_position_pct=MID.max_position_pct if cap is None else cap,
        sector=sector,
        sector_name={"IT": "IT", "BANKS": "Banks"}.get(sector or "", sector),
        results_on=results_on,
    )


def _kinds(issues):
    return [i.kind for i in issues]


def _check(holdings, account=1_000_000.0, limits=MID):
    return hh.check(holdings, account, limits)


def test_nothing_held_means_no_issues():
    assert _check([]) == []


def test_a_healthy_holding_raises_nothing():
    assert _check([_h()]) == []


def test_rules_come_from_the_settled_code():
    assert MID.max_position_pct == pytest.approx(0.10)
    assert MID.sector_cap_pct == pytest.approx(0.25)
    assert SMALL.sector_rule == "one_per_sector"
    assert pytest.approx(0.04) == settings.ML_STOP_RETURN_PCT
    assert hh.PLAN_TRADING_DAYS == settings.ML_PREDICTION_HORIZON_DAYS == 15


# ---- one stock too big ----


def test_stock_exactly_at_its_cap_is_fine():
    assert "stock_too_big" not in _kinds(_check([_h(value=100_000)]))


def test_stock_over_its_cap_is_flagged_in_plain_words():
    issues = _check([_h(value=101_000)])
    assert _kinds(issues) == ["stock_too_big"]
    assert "TCS" in issues[0].title and "10%" in issues[0].detail and "10.1%" in issues[0].detail


def test_per_strategy_override_is_respected():
    # A strategy that deliberately allows 20% in one stock is not flagged at 15%.
    assert _check([_h(value=150_000, cap=0.20)]) == []


# ---- sector ----


def test_sector_at_exactly_25pct_is_fine():
    held = [_h("TCS", 100_000), _h("INFY", 100_000), _h("WIPRO", 50_000)]
    assert "sector_too_big" not in _kinds(_check(held))


def test_sector_over_25pct_is_flagged_once_naming_the_stocks():
    held = [_h("TCS", 100_000), _h("INFY", 100_000), _h("WIPRO", 51_000)]
    issues = [i for i in _check(held) if i.kind == "sector_too_big"]
    assert len(issues) == 1
    assert set(issues[0].symbols) == {"TCS", "INFY", "WIPRO"}
    assert "25%" in issues[0].detail and "IT" in issues[0].title


def test_unmapped_stocks_are_never_lumped_into_one_sector():
    held = [_h("AAA", 100_000, sector=None), _h("BBB", 100_000, sector=None), _h("CCC", 100_000, sector=None)]
    assert "sector_too_big" not in _kinds(_check(held))


def test_small_account_one_stock_per_sector():
    one = [_h("TCS", 3_000, cap=SMALL.max_position_pct), _h("HDFCBANK", 3_000, sector="BANKS", cap=0.5)]
    assert _check(one, 10_000, SMALL) == []
    two = [_h("TCS", 3_000, cap=0.5), _h("INFY", 3_000, cap=0.5)]
    issues = _check(two, 10_000, SMALL)
    assert _kinds(issues) == ["two_in_one_sector"]
    assert "one stock per sector" in issues[0].detail


# ---- stop-loss ----


def test_stop_at_the_agreed_4pct_is_fine():
    assert _check([_h(entry=100, stop=96)]) == []


def test_stop_within_the_rounding_slack_is_fine():
    # Buy fills can differ slightly from the signal price; a quarter of a point is allowed.
    assert _check([_h(entry=100, stop=95.75)]) == []


def test_stop_further_than_the_slack_is_flagged():
    issues = _check([_h(entry=100, stop=95.70)])
    assert _kinds(issues) == ["stop_too_far"]
    assert "4.3%" in issues[0].detail and "4%" in issues[0].detail


def test_stop_above_entry_is_fine():
    assert _check([_h(entry=100, stop=104)]) == []


def test_no_stop_at_all_is_flagged():
    assert _kinds(_check([_h(stop=None)])) == ["no_stop"]


# ---- 15-trading-day plan ----


def test_day_15_is_still_inside_the_plan():
    assert _check([_h(day=15)]) == []


def test_day_16_is_past_the_plan_and_not_called_a_bug():
    issues = _check([_h(day=16)])
    assert _kinds(issues) == ["past_plan"]
    assert "30 calendar days" in issues[0].detail
    assert "bug" not in issues[0].detail.lower()


# ---- results day ----


def test_results_inside_the_window_are_flagged():
    issues = _check([_h(results_on=date(2026, 10, 23))])
    assert _kinds(issues) == ["results_soon"]
    assert "23 Oct" in issues[0].title


# ---- account value ----


def test_unknown_account_value_falls_back_to_what_is_held():
    issues = hh.check([_h("TCS", 5_000), _h("HDFCBANK", 5_000, sector="BANKS")], 0.0, MID)
    assert "stock_too_big" in _kinds(issues)  # each is 50% of what is held


# ---- window ----


def test_plan_last_day_counts_15_trading_days_from_entry():
    # Bought Mon 5 Oct 2026: day 15 is 14 trading days after the entry day (weekends and holidays skipped).
    last = hh.plan_last_day(datetime(2026, 10, 5, 4, 0, tzinfo=UTC))
    from swing_trade_ml.core.market_session import trading_days_between

    assert trading_days_between(date(2026, 10, 5), last) == 14


# --------------------------------------------------------------------------
# Endpoint: books kept apart, real book private
# --------------------------------------------------------------------------

API = "/api/v1/portfolio/health"
HEADERS = {"X-API-Key": "test-api-key"}


def _seed(db_session):
    from swing_trade_ml.core.enums import PositionStatus, TradingMode
    from swing_trade_ml.db.models.feeds import UpcomingEvent
    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.db.models.trading import Position, Strategy
    from swing_trade_ml.services.portfolio import REAL_TRADING_STRATEGY_NAME
    from swing_trade_ml.services.tester_paper import TESTER_PAPER_STRATEGY_NAME

    bot = Strategy(name="hh_bot", strategy_type="ml_swing", mode="paper", is_active=True, params={})
    real = Strategy(
        name=REAL_TRADING_STRATEGY_NAME,
        strategy_type="ml_swing",
        mode="live",
        is_active=True,
        execution_mode="advisory",
        params={},
    )
    tester = Strategy(
        name=TESTER_PAPER_STRATEGY_NAME, strategy_type="ml_swing", mode="paper", is_active=False, params={}
    )
    db_session.add_all([bot, real, tester])
    db_session.flush()
    insts = {}
    for n, sym in enumerate(["HHBOTNOSTOP", "HHREALFAR", "HHTESTOK"]):
        insts[sym] = Instrument(instrument_token=887_100 + n, tradingsymbol=sym, exchange="NSE")
    db_session.add_all(insts.values())
    db_session.flush()
    now = datetime.now(UTC)

    def pos(strategy, sym, mode, stop):
        return Position(
            strategy_id=strategy.id,
            instrument_id=insts[sym].id,
            mode=mode,
            status=PositionStatus.OPEN,
            quantity=1,
            entry_price=100.0,
            current_price=100.0,
            stop_loss=stop,
            entry_at=now,
        )

    db_session.add_all(
        [
            pos(bot, "HHBOTNOSTOP", TradingMode.PAPER, None),
            pos(real, "HHREALFAR", TradingMode.LIVE, 80.0),
            pos(tester, "HHTESTOK", TradingMode.PAPER, 96.0),
            UpcomingEvent(
                symbol="HHTESTOK", kind="results", event_date=now.date() + timedelta(days=1), detail=""
            ),
        ]
    )
    db_session.commit()


def _symbols(body):
    return {s for i in body["issues"] for s in i["symbols"]}


def test_each_book_is_checked_on_its_own(client, db_session):
    _seed(db_session)
    bot = client.get(f"{API}?book=bot", headers=HEADERS).json()
    real = client.get(f"{API}?book=real", headers=HEADERS).json()
    tester = client.get(f"{API}?book=tester", headers=HEADERS).json()

    assert "HHBOTNOSTOP" in _symbols(bot) and not ({"HHREALFAR", "HHTESTOK"} & _symbols(bot))
    assert "HHREALFAR" in _symbols(real) and not ({"HHBOTNOSTOP", "HHTESTOK"} & _symbols(real))
    assert _symbols(tester) <= {"HHTESTOK"}
    assert any(i["kind"] == "results_soon" for i in tester["issues"])
    assert real["book"] == "real" and real["is_real_money"] is True and bot["is_real_money"] is False
    assert tester["results_checked"] is True


def test_books_cannot_be_added_together(client, db_session):
    assert client.get(f"{API}?book=all", headers=HEADERS).status_code == 422


def test_empty_book_reports_nothing_held(client, db_session):
    body = client.get(f"{API}?book=bot", headers=HEADERS).json()
    assert body["holdings_checked"] == 0 and body["issues"] == []


def test_real_book_refused_for_anyone_not_named(client, db_session, monkeypatch):
    from swing_trade_ml.core.security import create_access_token
    from swing_trade_ml.db.models.session import User

    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "sudeeksha")
    for name, owner in (("vijay", True), ("someone", False)):
        user = User(username=name, hashed_password="x", is_active=True, is_superuser=owner, plan="free")
        db_session.add(user)
        db_session.flush()
        h = {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}
        assert client.get(f"{API}?book=real", headers=h).status_code == 403, name


def test_health_check_writes_nothing(client, db_session):
    from sqlalchemy import func, select

    from swing_trade_ml.db.models.trading import Order, Position

    _seed(db_session)
    before = (
        db_session.execute(select(func.count()).select_from(Order)).scalar_one(),
        [(p.id, p.stop_loss, p.quantity) for p in db_session.execute(select(Position)).scalars()],
    )
    for book in ("bot", "real", "tester"):
        client.get(f"{API}?book={book}", headers=HEADERS)
    db_session.expire_all()
    after = (
        db_session.execute(select(func.count()).select_from(Order)).scalar_one(),
        [(p.id, p.stop_loss, p.quantity) for p in db_session.execute(select(Position)).scalars()],
    )
    assert before == after
