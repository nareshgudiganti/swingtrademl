# ruff: noqa: E501 (long plain-English test text)
"""#249: watchlists and risk preferences (verification tests; nothing here changes the app).

Findings note: docs/verification/249-watchlists-prefs.md. Existing coverage that this file does not repeat and that the
note cites: test_my_watchlist.py (every role keeps its own list, nobody sees or changes another's list, the API key is
refused, unknown or malformed symbols, adding twice, the 50-stock cap, the global list untouched), test_watchlist_tracker.py,
test_limits.py and #252's tests (the ladder, a strategy may tighten), #463 (a strategy override can loosen).

Here: the tracker and sold-record rows per person, the write routes a member cannot reach, how a list entry behaves through a
symbol change, what limits exist on a list, and what a stored risk setting can and cannot do.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from swing_trade_ml.api.deps import SELF_SERVICE_ROUTES
from swing_trade_ml.api.v1.endpoints.my_watchlist import MAX_ITEMS
from swing_trade_ml.core.plans import default_plan
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem, UserWatchlistSale
from swing_trade_ml.services import ingestion
from swing_trade_ml.services.identity import resolve, writer
from swing_trade_ml.services.limits import RUNGS, limits_for

URL = "/api/v1/me/watchlist"
SRC = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
_TOKEN = iter(range(880_100_000, 880_200_000))


def _as(db, username, role="member", plan="free"):
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _stock(db, symbol, name=None):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, name=name or f"{symbol} Limited", exchange="NSE", instrument_type="EQ")
    db.add(inst)
    db.flush()
    return inst


# ------------------------------------------------------------------------------- limits on a list


def test_the_personal_list_is_capped_at_fifty_and_no_plan_limit_names_a_watchlist():
    assert MAX_ITEMS == 50
    for plan in ("free", "pro"):
        assert not any("watch" in key for key in default_plan(plan)["limits"]), plan  # plan limits: picks, history, cap tiers only


def test_the_bots_own_watchlist_has_no_size_cap_in_code_so_a_ten_stock_limit_is_a_setting_or_a_habit_not_a_rule(db_session):
    """OBSERVED: `ingestion.set_watchlist` and the route have no maximum, and the brain's universe is the watchlist plus the
    stocks the scanning strategies list. The 10-stock figure used for the brain in production is not enforced anywhere in code."""
    symbols = [f"WLCAP{i:03d}" for i in range(60)]
    for s in symbols:
        _stock(db_session, s)
    matched = ingestion.set_watchlist(db_session, symbols)
    assert len(matched) == 60
    assert db_session.scalar(select(Instrument.id).where(Instrument.tradingsymbol == "WLCAP059", Instrument.is_watchlisted.is_(True))) is not None


def test_the_database_itself_refuses_a_second_row_for_the_same_person_and_stock(db_session):
    user, _ = _as(db_session, "wl-dup")
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="DUPSYM"))
    db_session.flush()
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="DUPSYM"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ------------------------------------------------------------------------------- the tracker and sold rows per person


def test_a_persons_buy_price_quantity_tracker_and_sold_records_are_their_own(client, db_session):
    a, ha = _as(db_session, "wl-a")
    b, hb = _as(db_session, "wl-b")
    _stock(db_session, "WLISO")
    assert client.post(URL, json={"symbol": "WLISO"}, headers=ha).status_code == 201
    assert client.patch(f"{URL}/WLISO", json={"buy_price": 100.0, "quantity": 7}, headers=ha).status_code == 200
    assert client.post(f"{URL}/WLISO/sold", json={"sell_price": 120.0}, headers=ha).status_code == 200
    # person B sees nothing of it, anywhere
    assert client.get(f"{URL}/tracker", headers=hb).json()["items"] == []
    assert client.get(f"{URL}/sold", headers=hb).json()["items"] == []
    assert client.get(URL, headers=hb).json()["items"] == []
    # and cannot change, remove or sell A's stock (B has no such row, so each is a "not on your list")
    for method, path, body in (("patch", "WLISO", {"buy_price": 1.0}), ("delete", "WLISO", None), ("post", "WLISO/sold", {"sell_price": 1.0})):
        response = getattr(client, method)(f"{URL}/{path}", headers=hb, **({"json": body} if body else {}))
        assert response.status_code == 404, (method, response.text)
    sales = list(db_session.scalars(select(UserWatchlistSale)))
    assert len(sales) == 1 and sales[0].user_id == a.id and sales[0].sell_price == 120.0
    # B's own row for the same stock is independent of A's
    assert client.post(URL, json={"symbol": "WLISO"}, headers=hb).status_code == 201
    assert client.patch(f"{URL}/WLISO", json={"buy_price": 55.0}, headers=hb).json()["buy_price"] == 55.0
    assert db_session.scalar(select(UserWatchlistSale.sell_price).where(UserWatchlistSale.user_id == a.id)) == 120.0
    assert b.id != a.id


def test_a_sale_keeps_the_entry_price_it_was_made_with_when_the_list_row_is_edited_later(client, db_session):
    _, h = _as(db_session, "wl-keep")
    _stock(db_session, "WLKEEP")
    client.post(URL, json={"symbol": "WLKEEP"}, headers=h)
    client.patch(f"{URL}/WLKEEP", json={"buy_price": 100.0}, headers=h)
    client.post(f"{URL}/WLKEEP/sold", json={"sell_price": 110.0}, headers=h)
    client.post(URL, json={"symbol": "WLKEEP"}, headers=h)  # bought again
    client.patch(f"{URL}/WLKEEP", json={"buy_price": 500.0}, headers=h)
    first = client.get(f"{URL}/sold", headers=h).json()["items"][0]
    assert first["symbol"] == "WLKEEP" and 100.0 in (first.get("entry_price"), first.get("your_price"), first.get("entry"))


@pytest.mark.parametrize("role", ["member", "tester"])
def test_a_member_or_tester_cannot_change_the_bots_watchlist_or_a_strategys_limits(client, db_session, role):
    _, h = _as(db_session, f"wl-guard-{role}", role)
    strat = Strategy(name=f"wl_guard_{role}", strategy_type="ml_swing", mode="paper", params={})
    db_session.add(strat)
    db_session.flush()
    api = "/api/v1"
    assert client.put(f"{api}/instruments/watchlist", json={"symbols": ["RELIANCE"]}, headers=h).status_code == 403
    assert client.post(f"{api}/instruments/watchlist/reset", headers=h).status_code == 403
    assert client.patch(f"{api}/strategies/{strat.id}", json={"capital_allocation": 0.9, "max_positions": 50}, headers=h).status_code == 403
    assert client.post(f"{api}/strategies", json={"name": "x", "strategy_type": "ml_swing"}, headers=h).status_code == 403
    db_session.refresh(strat)
    assert strat.capital_allocation is None and strat.max_positions is None


def test_the_only_routes_open_to_every_person_are_the_eight_watchlist_ones():
    assert {path for _method, path in SELF_SERVICE_ROUTES} <= {
        "/me/watchlist", "/me/watchlist/search", "/me/watchlist/{symbol}", "/me/watchlist/tracker", "/me/watchlist/sold", "/me/watchlist/{symbol}/sold"
    } and len(SELF_SERVICE_ROUTES) == 8


# ------------------------------------------------------------------------------- an entry through a symbol change


def _renamed_stock(db):
    inst = _stock(db, "WLOLDNAME", "Rename Test Limited")
    security = writer.ensure_for_instrument(db, inst)
    inst.tradingsymbol = "WLNEWNAME"
    db.flush()
    writer.set_symbol(db, security, "WLNEWNAME", date(2026, 12, 2))
    return inst, security


def test_the_identity_layer_follows_a_symbol_change_to_one_stock(db_session):
    """Control for the two gaps below (cites #456): the old and the new symbol resolve to ONE stock id."""
    _inst, security = _renamed_stock(db_session)
    assert resolve(db_session, symbol="WLOLDNAME", on_date=date(2026, 11, 30)) == security
    assert resolve(db_session, symbol="WLNEWNAME", on_date=date(2026, 12, 3)) == security


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: a personal list row is keyed by the symbol text (user_watchlist_items.symbol), not by the stock id, so after a "
    "symbol change the entry no longer finds its company name or prices",
)
def test_a_list_entry_still_shows_its_company_after_the_symbol_changes(client, db_session):
    inst, _security = _renamed_stock(db_session)
    inst.tradingsymbol = "WLOLDNAME"  # before the change: the entry resolves
    db_session.flush()
    _, h = _as(db_session, "wl-rename")
    client.post(URL, json={"symbol": "WLOLDNAME"}, headers=h)
    assert client.get(URL, headers=h).json()["items"][0]["name"] == "Rename Test Limited"  # control: this part passes
    inst.tradingsymbol = "WLNEWNAME"
    db_session.flush()
    assert client.get(URL, headers=h).json()["items"][0]["name"] == "Rename Test Limited"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: because the list is keyed by symbol text, adding the new symbol after a change puts the same company on the list "
    "twice (the unique rule is per person and symbol, not per stock)",
)
def test_adding_the_new_symbol_of_a_stock_already_on_the_list_is_refused_as_a_duplicate(client, db_session):
    inst = _stock(db_session, "WLDUPOLD", "Dup Rename Limited")
    _, h = _as(db_session, "wl-rename-dup")
    assert client.post(URL, json={"symbol": "WLDUPOLD"}, headers=h).status_code == 201
    inst.tradingsymbol = "WLDUPNEW"
    db_session.flush()
    client.post(URL, json={"symbol": "WLDUPNEW"}, headers=h)
    active = [i for i in client.get(URL, headers=h).json()["items"] if i["removed_at"] is None]
    assert len(active) == 1  # one company, one entry


# ------------------------------------------------------------------------------- risk preferences


def test_a_person_has_no_stored_risk_setting_only_strategies_and_the_global_settings_carry_limits():
    columns = {c.name for c in User.__table__.columns}
    assert not any(re.search(r"risk|limit|stop|target|drawdown|allocation|position|sector", name) for name in columns), columns
    text = (SRC / "api" / "v1" / "endpoints" / "my_watchlist.py").read_text(encoding="utf-8")
    assert "limits_for" not in text and "RISK_" not in text  # nothing on the personal list reads or sets a limit


@pytest.mark.parametrize("value", [rung.value for rung in RUNGS] + [25_000, 250_000])
def test_an_unset_strategy_setting_gives_the_ladder_unchanged_and_a_zero_cannot_loosen_it(value):
    ladder = limits_for(value)
    for unset in (SimpleNamespace(max_positions=None, capital_allocation=None), SimpleNamespace(max_positions=0, capital_allocation=0.0)):
        got = limits_for(value, unset)
        assert (got.max_positions, got.max_position_pct) == (ladder.max_positions, ladder.max_position_pct)


def test_a_strategy_may_tighten_a_limit_and_the_looser_case_is_the_known_gap_463():
    """Cited, not re-tested here: #252 pins that a tighter value is honoured and that a looser one replaces the ladder (#463)."""
    ladder = limits_for(1_000_000)
    tight = limits_for(1_000_000, SimpleNamespace(max_positions=2, capital_allocation=0.03))
    assert tight.max_positions < ladder.max_positions and tight.max_position_pct < ladder.max_position_pct


def test_the_settled_risk_rules_do_not_come_from_any_person_or_strategy_field():
    lim = limits_for(1_000_000, SimpleNamespace(max_positions=2, capital_allocation=0.03))
    assert lim.max_drawdown_pct == 0.15 and lim.risk_per_trade_pct == 0.01 and lim.sector_cap_pct == 0.25  # untouched by an override


def test_only_the_sma_crossover_benchmark_reads_a_strategys_stored_stop_and_target_percent():
    """Control for the gap below: the benchmark strategy (and the rules watch, which reports on it) read the stored values."""
    sma = (SRC / "strategies" / "sma_crossover.py").read_text(encoding="utf-8")
    assert "self.config.stop_loss_pct or settings.DEFAULT_STOP_LOSS_PCT" in sma


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP: for ml_swing (the production strategy) Strategy.stop_loss_pct is stored and shown (the Strategies screen labels a "
    "strategy Conservative or Aggressive from it) but the entry stop comes from settings.ML_STOP_RETURN_PCT, so the label can "
    "describe a setting that does nothing",
)
def test_the_ml_swing_entry_stop_uses_the_strategys_stored_stop_percent():
    text = (SRC / "strategies" / "ml_swing.py").read_text(encoding="utf-8")
    assert re.search(r"config\.stop_loss_pct|strategy\.stop_loss_pct", text), "ml_swing takes its stop from settings only"


def test_entry_levels_come_from_the_settled_rules_not_from_a_strategys_stored_percent():
    """Control for the gap above: the settled -4% stop / +8% target are model and settings values (core/config.py)."""
    from swing_trade_ml.core.config import settings

    assert (settings.ML_TARGET_RETURN_PCT, settings.ML_STOP_RETURN_PCT, settings.ML_FIRST_TARGET_PCT) == (0.08, 0.04, 0.05)

