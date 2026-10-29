"""Public stock verdict vs the test portfolio's decision.

A customer sees the stock-level verdict. TRADE is recovered ONLY when the stored record proves the one thing
that held the idea back was the account's room or the minimum position size; every other restriction, and any
mixed record, keeps WATCH / WAIT / AVOID. The texts come from the REAL allocator and decision rules, so a
reworded rule breaks a test instead of silently restoring (or hiding) a verdict. The API half proves a
non-owner gets none of the account's numbers, while the owner keeps both answers and every stored row is
untouched."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import IdeaWord, MarketMode
from swing_trade_ml.brain.modules.m07_risk.allocator import Candidate
from swing_trade_ml.brain.modules.m08_decide.engine import decide_idea
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import public_verdict as pv
from swing_trade_ml.services.plans import set_plans_enabled
from test_what_would_change import (
    POLICY,
    _account,
    _allocated,
    _facts,
)  # sibling import, like test_p0_role_matrix

HEADERS = {"X-API-Key": "test-api-key"}


def _decided(verdict: c.RiskVerdict) -> c.Decision:
    d = decide_idea(_facts(verdict=replace(verdict, symbol="ABC")), POLICY)
    assert d.word is IdeaWord.WATCH and d.downgraded_from is IdeaWord.TRADE
    return d


def _verdict_of(d: c.Decision, *, banner="NORMAL", trend=None, extra_reasons=(), overruled=None, word=None):
    return pv.stock_verdict(
        kind=d.kind,
        word=word or d.word.value,
        downgraded_from=d.downgraded_from.value if d.downgraded_from else None,
        downgrade_reason=d.downgrade_reason,
        reasons=[*d.reasons, *extra_reasons],
        overruled_word=overruled,
        banner_mode=banner,
        trend=(lambda: trend) if trend is not None else None,
    )


# ------------------------------------------------------------- the real allocator's refusals --


def _capacity_cases():
    stronger = [Candidate("A1", 100.0, 0.9, None), Candidate("ABC", 100.0, 0.5, None)]
    return {
        "slots_full": _allocated([Candidate("ABC", 100.0, 0.5, None)], _account(free_slots=0))["ABC"],
        "slots_taken": _allocated(stronger, _account(free_slots=1))["ABC"],
        "room_after_stronger": _allocated(stronger, _account(deploy_room=15_000.0))["ABC"],
        "half_size": _allocated(
            [Candidate("ABC", 100.0, 0.9, None)], _account(), MarketMode.DEFENSIVE, qty=150
        )["ABC"],
    }


@pytest.mark.parametrize("name", ["slots_full", "slots_taken", "room_after_stronger", "half_size"])
def test_capacity_only_refusals_give_the_stock_verdict_back(name):
    d = _decided(_capacity_cases()[name])
    assert pv.is_capacity_reason(d.downgrade_reason)
    v = _verdict_of(d, banner="DEFENSIVE" if name == "half_size" else "NORMAL", trend="up")
    assert (v.word, v.restored) == ("TRADE", True)


@pytest.mark.parametrize(
    "name,verdict",
    [
        (
            "market_no_new_trades",
            lambda: _allocated([Candidate("ABC", 100.0, 0.9, None)], _account(), MarketMode.NO_NEW_TRADES)[
                "ABC"
            ],
        ),
        (
            "defensive_limit",
            lambda: _allocated(
                [Candidate(s, 100.0, 0.9 - i / 10, None) for i, s in enumerate(["A1", "A2", "ABC"])],
                _account(),
                MarketMode.DEFENSIVE,
                qty=1000,
            )["ABC"],
        ),
        (
            "one_per_sector",
            lambda: _allocated(
                [Candidate("A1", 100.0, 0.9, "BANK"), Candidate("ABC", 100.0, 0.5, "BANK")],
                _account(sector_rule="one_per_sector", sector_cap_pct=None),
            )["ABC"],
        ),
    ],
)
def test_other_restrictions_keep_watch(name, verdict):
    d = _decided(verdict())
    assert not pv.is_capacity_reason(d.downgrade_reason), name
    assert _verdict_of(d, trend="up").word == "WATCH"


@pytest.mark.parametrize(
    "limit,expected",
    [
        ("market-conditions limit", True),
        ("cash reserve", True),
        ("available cash", True),
        ("concentration cap", True),
        ("sector limit", False),
        ("small-company budget", False),
        ("trading-volume limit", False),
        ("some limit nobody has heard of", False),
    ],
)
def test_minimum_position_only_counts_when_the_limit_is_the_accounts_own(limit, expected):
    text = (
        "Good idea, but the risk check said no: The position would only be ₹9,000 "
        f"(limited by the {limit}) — "
        "below the ₹40,000 minimum that keeps fixed charges from eating the trade at this account size"
    )
    assert pv.is_capacity_reason(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "Good idea, but the risk check said no: Your account is 20% below its peak "
        "— past the 15% safety limit",
        "Good idea, but the risk check said no: Stopped out within the last 5 days — cooling down",
        "Good idea, but the risk check said no: New buys are paused by the owner. "
        "Existing positions still sell normally.",
        "Good idea, but the risk check said no: Position already open in this instrument",
        "Good idea, but the risk check said no: X trades only about ₹12,000 a day, too thin for a position",
        "The risk check has not approved this trade.",
        "Not a risk line at all",
    ],
)
def test_account_halts_stock_specific_and_unknown_texts_are_not_capacity(text):
    assert pv.is_capacity_reason(text) is False


def test_a_mixed_record_is_never_restored():
    d = _decided(_capacity_cases()["room_after_stronger"])
    watch = "On the exchange's watch list (ASM), so the brain stays away."
    assert _verdict_of(d, trend="up", extra_reasons=[watch]).word == "WATCH"
    assert (
        _verdict_of(d, trend="up", extra_reasons=["Results on 28 Oct: the brain avoids new trades"]).word
        == "WATCH"
    )
    # a second capacity line is still capacity-only
    assert _verdict_of(d, trend="up", extra_reasons=[d.downgrade_reason]).restored is True


def test_only_a_watch_idea_downgraded_from_trade_is_restored():
    d = _decided(_capacity_cases()["room_after_stronger"])
    for word in ("WAIT", "AVOID"):
        assert _verdict_of(d, word=word).word == word
    assert _verdict_of(d, overruled="WAIT").word == "WATCH"  # the owner's overrule is respected
    kept = pv.stock_verdict(
        kind="idea",
        word="WATCH",
        downgraded_from=None,
        downgrade_reason=None,
        reasons=[],
        banner_mode="NORMAL",
    )
    assert kept.word == "WATCH"
    holding = pv.stock_verdict(
        kind="holding",
        word="WATCH",
        downgraded_from="TRADE",
        downgrade_reason=d.downgrade_reason,
        reasons=[],
        banner_mode="NORMAL",
    )
    assert holding.restored is False


def test_in_a_careful_market_the_stocks_own_trend_must_be_shown_not_falling():
    d = _decided(_capacity_cases()["half_size"])
    assert _verdict_of(d, banner="DEFENSIVE", trend="down").word == "WATCH"
    assert _verdict_of(d, banner="DEFENSIVE").word == "WATCH"  # trend unknown: not proven, not restored
    assert _verdict_of(d, banner="DEFENSIVE", trend="sideways").word == "TRADE"
    assert _verdict_of(d, banner="DEFENSIVE", trend="up").word == "TRADE"
    assert _verdict_of(d, banner="NORMAL").word == "TRADE"  # the trend rule only exists in careful markets


def test_scrubbed_fields_carry_no_account_number():
    d = _decided(_capacity_cases()["room_after_stronger"])
    out = pv.public_fields(
        kind="idea",
        word="WATCH",
        downgraded_from="TRADE",
        downgrade_reason=d.downgrade_reason,
        reasons=list(d.reasons),
        banner_mode="NORMAL",
    )
    assert out["word"] == "TRADE"
    assert out["downgraded_from"] is None and out["downgrade_reason"] is None
    assert not any("risk check said no" in r or ("₹" in r and "minimum" in r) for r in out["reasons"])
    assert pv.public_what_would_change(out, kind="idea", banner_mode="NORMAL", banner_headline=None) == []


# ------------------------------------------------------------------------------- the API --

RUN = "pubv-run"
ROOM = (
    "Good idea, but the risk check said no: After stronger ideas in this run, the market-conditions limit "
    "leaves room for only ₹5,000 — below the ₹10,000 minimum position."
)
SECTOR = (
    "Good idea, but the risk check said no: A stronger idea in the same sector was approved first, "
    "and at this account size the bot keeps to one stock per sector."
)


@pytest.fixture()
def seeded(db_session):
    now = datetime(2031, 5, 5, 10, 0, tzinfo=UTC)
    db_session.add(
        BrainRun(
            id=RUN,
            kind="nightly",
            as_of=now,
            book="pubv",
            live=True,
            status="done",
            started_at=now,
            banner_mode="NORMAL",
            context={"portfolio": {"cash": 123456, "holdings": 3}},
        )
    )
    db_session.flush()

    def add(symbol, word, **kw):
        db_session.add(
            BrainDecision(
                run_id=RUN,
                symbol=symbol,
                kind=kw.pop("kind", "idea"),
                word=word,
                confidence=0.7,
                score_source="model",
                qty=kw.pop("qty", 0),
                **kw,
            )
        )

    add(
        "ROOMCO",
        "WATCH",
        reasons=[ROOM, "Model score 70%."],
        downgraded_from="TRADE",
        downgrade_reason=ROOM,
        qty=0,
    )
    add("SECTCO", "WATCH", reasons=[SECTOR], downgraded_from="TRADE", downgrade_reason=SECTOR)
    add(
        "MIXCO",
        "WATCH",
        reasons=[ROOM, "On the exchange's watch list (ASM), so the brain stays away."],
        downgraded_from="TRADE",
        downgrade_reason=ROOM,
    )
    add("TRADECO", "TRADE", reasons=["Plan."], qty=40)
    add("HELDCO", "HOLD", kind="holding", reasons=["Holding steady."], qty=100)
    db_session.flush()
    return RUN


def _member(db, name="pubv-pro"):
    set_plans_enabled(db, True)
    user = User(username=name, hashed_password="x", is_active=True, is_superuser=False, plan="pro")
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}


def _by_symbol(body):
    return {d["symbol"]: d for d in body["decisions"]}


def test_non_owner_sees_the_stock_verdict_and_nothing_of_the_account(client, db_session, seeded):
    r = client.get(f"/api/v1/brain/runs/{seeded}", headers=_member(db_session))
    assert r.status_code == 200, r.text
    body = r.json()
    ideas = _by_symbol(body)
    assert ideas["ROOMCO"]["word"] == "TRADE" and ideas["ROOMCO"]["stock_verdict"] == "TRADE"
    assert ideas["SECTCO"]["word"] == "WATCH"  # a sector limit is not capacity
    # ...but its text quotes the account's own holdings rules: a non-owner reads the number-free line
    assert ideas["SECTCO"]["reasons"] == [pv.PUBLIC_RISK_LINE]
    assert ideas["SECTCO"]["downgrade_reason"] == pv.PUBLIC_RISK_LINE
    assert "one stock per sector" not in r.text
    assert ideas["MIXCO"]["word"] == "WATCH"  # mixed reasons are never restored
    assert "HELDCO" not in ideas  # the bot's holdings are the test portfolio's
    assert body["portfolio"] == {}
    assert ideas["TRADECO"]["qty"] == 0 and ideas["ROOMCO"]["qty"] == 0
    text = r.text
    assert "₹5,000" not in text and "minimum position" not in text and "market-conditions limit" not in text
    assert "123456" not in text
    assert ideas["ROOMCO"]["downgraded_from"] is None and ideas["ROOMCO"]["downgrade_reason"] is None
    assert ideas["ROOMCO"]["what_would_change"] == []


def test_owner_keeps_both_answers_and_the_stored_rows_are_untouched(client, db_session, seeded):
    before = [
        (d.symbol, d.word, list(d.reasons), d.downgraded_from, d.qty)
        for d in db_session.query(BrainDecision).filter_by(run_id=seeded).order_by(BrainDecision.symbol)
    ]
    body = client.get(f"/api/v1/brain/runs/{seeded}", headers=HEADERS).json()
    ideas = _by_symbol(body)
    assert ideas["ROOMCO"]["word"] == "WATCH"  # the test portfolio's decision, as stored
    assert ideas["ROOMCO"]["stock_verdict"] == "TRADE" and ideas["ROOMCO"]["stock_verdict_restored"] is True
    assert ideas["SECTCO"]["stock_verdict"] == "WATCH" and ideas["SECTCO"]["stock_verdict_restored"] is False
    assert ideas["ROOMCO"]["downgrade_reason"] == ROOM  # the owner still sees the account's own text
    assert ideas["TRADECO"]["qty"] == 40 and "HELDCO" in ideas
    assert body["portfolio"] == {"cash": 123456, "holdings": 3}
    db_session.expire_all()
    after = [
        (d.symbol, d.word, list(d.reasons), d.downgraded_from, d.qty)
        for d in db_session.query(BrainDecision).filter_by(run_id=seeded).order_by(BrainDecision.symbol)
    ]
    assert after == before


def test_the_changes_endpoint_is_public_too(db_session, seeded):
    from swing_trade_ml.services import brain_changes

    day2 = datetime(2031, 5, 6, 10, 0, tzinfo=UTC)
    db_session.add(
        BrainRun(
            id="pubv-next",
            kind="nightly",
            as_of=day2,
            book="pubv",
            live=True,
            status="done",
            started_at=day2,
            banner_mode="NORMAL",
        )
    )
    db_session.flush()
    db_session.add(
        BrainDecision(
            run_id="pubv-next",
            symbol="ROOMCO",
            kind="idea",
            word="WATCH",
            reasons=[ROOM],
            downgraded_from="TRADE",
            downgrade_reason=ROOM,
        )
    )
    db_session.flush()
    public = brain_changes.changes(db_session, run_id="pubv-next", owner=False)
    side = next(r for r in public["ideas"] if r["symbol"] == "ROOMCO")["now"]
    assert side["word"] == "TRADE" and side["downgrade_reason"] is None
    assert "₹5,000" not in str(public)
    owner = brain_changes.changes(db_session, run_id="pubv-next", owner=True)
    assert next(r for r in owner["ideas"] if r["symbol"] == "ROOMCO")["now"]["word"] == "WATCH"


def test_risk_limits_stay_owner_only(client, db_session):
    assert client.get("/api/v1/risk/limits", headers=_member(db_session, "pubv-lim")).status_code == 403
