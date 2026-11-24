# ruff: noqa: E501 (long plain-English test text)
"""#486 (from the #239 verification): the buy list and the top picks list only fresh, still-current BUYs.

- A BUY older than the pick window (`PICK_MAX_AGE`, the one /signals/picks uses) is not listed.
- A strategy's own newer HOLD (or weaker signal) removes its older BUY. Another strategy's HOLD does NOT: the brain's
  nightly HOLD for every stock it did not mark TRADE, and hand-book or advisory HOLDs, are other books' opinions.
- Both read the broker mode, as /signals/picks and the buy list did; top-picks hard-coded paper.

These are recommendations only: nothing here places an order. They failed on `5de3b9c` and pass with the fix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from types import SimpleNamespace

import pytest

from swing_trade_ml.api.v1.endpoints import signals as signals_endpoint
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Signal, Strategy

KEY = {"X-API-Key": "test-api-key"}
BUY_LIST = "/api/v1/signals/buy-list"
TOP_PICKS = "/api/v1/signals/top-picks"
_tokens = count(486_000)
_names = count()


def strategy(
    db, mode: str = "paper", kind: str = "ml_swing", name: str | None = None, execution_mode: str = "auto",
    private: bool = False,
) -> Strategy:
    row = Strategy(
        name=name or f"s486-{next(_names)}",
        strategy_type=kind,
        params={},
        is_active=True,
        mode=mode,
        execution_mode=execution_mode,
        owner_private=private,  # member-facing unless said otherwise
    )
    db.add(row)
    db.flush()
    return row


def stock(db, symbol: str) -> Instrument:
    row = Instrument(instrument_token=next(_tokens), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(row)
    db.flush()
    return row


def signal(db, strat: Strategy, inst: Instrument, kind: str, age: timedelta, mode: str = "paper") -> Signal:
    row = Signal(
        strategy_id=strat.id,
        instrument_id=inst.id,
        signal_type=kind,
        mode=mode,
        price=100.0,
        confidence=0.9,
        stop_loss=96.0,
        take_profit=108.0,
        horizon_days=15,
        generated_at=datetime.now(UTC) - age,
        features={},
    )
    db.add(row)
    db.flush()
    return row


def listed(client, url: str) -> set[str]:
    response = client.get(url, headers=KEY)
    assert response.status_code == 200, response.text
    return {row["symbol"] for row in response.json()}


BOTH = pytest.mark.parametrize("url", [BUY_LIST, TOP_PICKS])


@BOTH
def test_a_fresh_buy_is_listed_and_a_forty_day_old_buy_is_not(client, db_session, url):
    strat = strategy(db_session)
    signal(db_session, strat, stock(db_session, "FRESH486"), "BUY", timedelta(days=1))
    signal(db_session, strat, stock(db_session, "OLD486"), "BUY", timedelta(days=40))
    assert listed(client, url) >= {"FRESH486"}
    assert "OLD486" not in listed(client, url)


@BOTH
def test_the_age_limit_is_the_one_the_picks_list_uses(client, db_session, url):
    strat = strategy(db_session)
    edge = signals_endpoint.PICK_MAX_AGE
    signal(db_session, strat, stock(db_session, "INSIDE486"), "BUY", edge - timedelta(hours=1))
    signal(db_session, strat, stock(db_session, "OUTSIDE486"), "BUY", edge + timedelta(hours=1))
    found = listed(client, url)
    assert "INSIDE486" in found and "OUTSIDE486" not in found


@BOTH
def test_a_strategys_own_newer_hold_removes_its_older_buy(client, db_session, url):
    model = strategy(db_session)
    inst = stock(db_session, "SAMEHOLD486")
    signal(db_session, model, inst, "BUY", timedelta(days=2))
    signal(db_session, model, inst, "HOLD", timedelta(days=1))
    assert "SAMEHOLD486" not in listed(client, url)


@BOTH
def test_a_brain_type_hold_after_a_model_buy_leaves_the_buy_listed(client, db_session, url):
    model = strategy(db_session)
    brain = strategy(db_session, kind="brain", execution_mode="advisory")
    inst = stock(db_session, "BRAINHOLD486")
    signal(db_session, model, inst, "BUY", timedelta(days=2))
    signal(db_session, brain, inst, "HOLD", timedelta(days=1))  # the brain's nightly fallback for a stock it did not pick
    assert "BRAINHOLD486" in listed(client, url)


@BOTH
def test_an_advisory_or_hand_book_hold_after_a_model_buy_leaves_the_buy_listed(client, db_session, url):
    model = strategy(db_session)
    book = strategy(db_session, name="real_trading", execution_mode="advisory")
    inst = stock(db_session, "BOOKHOLD486")
    signal(db_session, model, inst, "BUY", timedelta(days=2))
    signal(db_session, book, inst, "HOLD", timedelta(days=1))
    assert "BOOKHOLD486" in listed(client, url)


def test_the_visibility_filter_applies_to_the_overtaking_check(client, db_session):
    """A member's list is built only from what that member may see: a private strategy's newer HOLD changes nothing."""
    from swing_trade_ml.core.security import create_access_token
    from swing_trade_ml.db.models.session import User
    from swing_trade_ml.services.plans import set_plans_enabled

    set_plans_enabled(db_session, True)
    member = User(username="m486", hashed_password="x", is_active=True, role="member", plan="pro")
    db_session.add(member)
    db_session.flush()
    headers = {"Authorization": f"Bearer {create_access_token(member.username, {'uid': member.id, 'tv': 0})}"}
    model = strategy(db_session)
    private = strategy(db_session, name="real_trading", execution_mode="advisory", private=True)
    inst = stock(db_session, "PRIVHOLD486")
    signal(db_session, model, inst, "BUY", timedelta(days=2))
    signal(db_session, private, inst, "HOLD", timedelta(days=1))
    rows = client.get(BUY_LIST, headers=headers)
    assert rows.status_code == 200 and "PRIVHOLD486" in {r["symbol"] for r in rows.json()}


@BOTH
def test_an_older_hold_does_not_remove_a_newer_buy(client, db_session, url):
    model, rules = strategy(db_session), strategy(db_session)
    inst = stock(db_session, "HOLDOLD486")
    signal(db_session, rules, inst, "HOLD", timedelta(days=3))
    signal(db_session, model, inst, "BUY", timedelta(days=1))
    assert "HOLDOLD486" in listed(client, url)


@BOTH
def test_a_hold_on_a_different_stock_changes_nothing(client, db_session, url):
    model, rules = strategy(db_session), strategy(db_session)
    signal(db_session, model, stock(db_session, "KEEP486"), "BUY", timedelta(days=2))
    signal(db_session, rules, stock(db_session, "OTHER486"), "HOLD", timedelta(days=1))
    assert "KEEP486" in listed(client, url)


@BOTH
def test_both_lists_read_the_brokers_mode_so_they_never_disagree(client, db_session, monkeypatch, url):
    strat_paper, strat_live = strategy(db_session), strategy(db_session, mode="live")
    signal(db_session, strat_paper, stock(db_session, "PAPER486"), "BUY", timedelta(days=1), mode="paper")
    signal(db_session, strat_live, stock(db_session, "LIVE486"), "BUY", timedelta(days=1), mode="live")
    assert listed(client, url) >= {"PAPER486"} and "LIVE486" not in listed(
        client, url
    )  # paper broker, as today
    monkeypatch.setattr(signals_endpoint, "get_broker", lambda: SimpleNamespace(mode="live"))
    assert "LIVE486" in listed(client, url) and "PAPER486" not in listed(client, url)
