"""GET /strategies/performance — see
docs/superpowers/specs/2026-09-14-strategies-tab-design.md §5b."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Strategy, Trade

HEADERS = {"X-API-Key": "test-api-key"}


def _instrument(db_session, tradingsymbol="TEST") -> Instrument:
    inst = Instrument(
        instrument_token=hash(tradingsymbol) % 1_000_000,
        tradingsymbol=tradingsymbol,
        exchange="NSE",
        is_watchlisted=True,
    )
    db_session.add(inst)
    db_session.flush()
    return inst


def _strategy(db_session, *, name, model_name=None, is_active=True, execution_mode="auto") -> Strategy:
    strat = Strategy(
        name=name,
        strategy_type="ml_swing",
        mode="paper",
        is_active=is_active,
        execution_mode=execution_mode,
        params={"model_name": model_name} if model_name else {},
    )
    db_session.add(strat)
    db_session.flush()
    return strat


def _trade(db_session, *, strategy_id, instrument_id, is_win, net_pnl, exit_at) -> Trade:
    trade = Trade(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        mode="paper",
        symbol="TEST",
        quantity=10,
        entry_price=100.0,
        exit_price=110.0 if is_win else 90.0,
        entry_at=exit_at - timedelta(days=5),
        exit_at=exit_at,
        holding_days=5,
        gross_pnl=net_pnl,
        charges=0.0,
        net_pnl=net_pnl,
        return_pct=net_pnl / 1000,
        is_win=is_win,
    )
    db_session.add(trade)
    db_session.flush()
    return trade


def test_strategy_with_no_trades_shows_zeroed_windows(client, db_session):
    _strategy(db_session, name="ml_swing_main")
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    row = next(s for s in body["strategies"] if s["name"] == "ml_swing_main")
    assert row["cap_tier"] == "large"
    assert row["windows"]["all_time"] == {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "net_pnl": 0.0}


def test_below_trade_threshold_gives_no_recommendation(client, db_session):
    strat = _strategy(db_session, name="ml_swing_midcap", model_name="swing_classifier_midcap")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(5):  # below the 10-trade threshold
        _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_strategy_id"] is None
    assert "10" in body["recommendation_reason"] or "more" in body["recommendation_reason"]


def test_highest_win_rate_active_strategy_is_recommended(client, db_session):
    good = _strategy(db_session, name="ml_swing_midcap", model_name="swing_classifier_midcap")
    bad = _strategy(db_session, name="ml_swing_smallcap", model_name="swing_classifier_smallcap")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(9):
        _trade(db_session, strategy_id=good.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    _trade(db_session, strategy_id=good.id, instrument_id=inst.id, is_win=False, net_pnl=-50.0, exit_at=now)
    for _ in range(2):
        _trade(db_session, strategy_id=bad.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    for _ in range(8):
        _trade(db_session, strategy_id=bad.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["recommended_strategy_id"] == good.id


def test_advisory_strategy_is_never_recommended(client, db_session):
    """real_trading-style strategies (execution_mode=advisory) track personal
    holdings, not a competing cap-tier approach — never eligible."""
    advisory = _strategy(db_session, name="real_trading", execution_mode="advisory")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(15):
        _trade(db_session, strategy_id=advisory.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    assert resp.json()["recommended_strategy_id"] is None


def test_inactive_strategy_is_never_recommended(client, db_session):
    strat = _strategy(db_session, name="ml_swing_main", is_active=False)
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    for _ in range(15):
        _trade(db_session, strategy_id=strat.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended_strategy_id"] is None
    # The inactive strategy has 15 closed trades (well past the 10-trade
    # threshold), but being inactive must disqualify it from the "closest
    # candidate" fallback too — otherwise the reason text would claim a
    # nonsensical negative number of trades still needed. With no other
    # ml_swing/auto strategy in play, there's no candidate at all, so the
    # reason must fall through to the generic message and must not mention
    # this strategy by name.
    assert body["recommendation_reason"] == "Not enough closed trades yet to recommend a strategy."
    assert strat.name not in body["recommendation_reason"]


def test_90d_window_falls_back_to_all_time_below_trade_threshold(client, db_session):
    """Global constraint: the 90-day window is only trusted for ranking once
    it has >= 3 trades of its own; a strategy whose trades are all older than
    90 days must still be ranked on its all-time win rate, not treated as a
    0.0 win rate from an empty 90-day window."""
    old_strong = _strategy(db_session, name="ml_swing_midcap", model_name="swing_classifier_midcap")
    recent_weak = _strategy(db_session, name="ml_swing_smallcap", model_name="swing_classifier_smallcap")
    inst = _instrument(db_session)
    now = datetime.now(UTC)
    long_ago = now - timedelta(days=100)  # outside the 90-day window entirely

    # old_strong: 9/10 wins (90%), but every trade closed >90 days ago, so
    # last_90d.trades == 0 and ranking must fall back to all_time.
    for _ in range(9):
        _trade(db_session, strategy_id=old_strong.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=long_ago)
    _trade(db_session, strategy_id=old_strong.id, instrument_id=inst.id, is_win=False, net_pnl=-50.0, exit_at=long_ago)

    # recent_weak: 5/10 wins (50%), all closed recently, so last_90d has
    # plenty (>=3) of trades and is used directly.
    for _ in range(5):
        _trade(db_session, strategy_id=recent_weak.id, instrument_id=inst.id, is_win=True, net_pnl=100.0, exit_at=now)
    for _ in range(5):
        _trade(db_session, strategy_id=recent_weak.id, instrument_id=inst.id, is_win=False, net_pnl=-100.0, exit_at=now)
    db_session.commit()

    resp = client.get("/api/v1/strategies/performance", headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    old_strong_row = next(s for s in body["strategies"] if s["id"] == old_strong.id)
    assert old_strong_row["windows"]["last_90d"]["trades"] == 0
    assert old_strong_row["windows"]["all_time"]["win_rate"] == 0.9
    # If the fallback weren't implemented, old_strong would rank at
    # win_rate 0.0 (empty 90d window) and lose to recent_weak's 50%.
    assert body["recommended_strategy_id"] == old_strong.id
