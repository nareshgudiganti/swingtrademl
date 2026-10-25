"""bx10 "What would change this?" — display-only lines for WATCH / WAIT / AVOID ideas.

Every brain rule that can lower an idea is run for real here and its stored text is fed
to the mapper, so a change to a rule's wording breaks a test instead of quietly showing
"Not known" (or the wrong line) to the customer. Pure: no database.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import IdeaWord, MarketMode
from swing_trade_ml.brain.modules.m07_risk.allocator import Account, Candidate, CheckResult, Policy, allocate
from swing_trade_ml.brain.modules.m08_decide.engine import IdeaFacts, decide_idea
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.core.config import settings
from swing_trade_ml.services.what_would_change import (
    UNKNOWN,
    ModelRank,
    model_ranks,
    what_would_change,
)

POLICY = DecidePolicy()


def _facts(**kw) -> IdeaFacts:
    base = {
        "symbol": "ABC",
        "snapshot": c.Snapshot(symbol="ABC", as_of="2026-10-20", close=1000.0, atr_14=20.0),
        "opinion": c.Opinion(
            source="model",
            symbol="ABC",
            stance=0.4,
            confidence=0.4,
            probability=0.7,
            threshold=0.6,
            reasons=("The model scores this stock 70%.",),
        ),
        "verdict": c.RiskVerdict(symbol="ABC", allowed=True, max_qty=25, reason="Sized by risk-per-trade"),
        "quality": c.DataQuality(symbol="ABC", score=1.0, fresh=True),
        "stock": c.StockState(symbol="ABC", trend="up"),
        "situations": (),
        "recall": None,
        "market_mode": MarketMode.NORMAL,
    }
    return IdeaFacts(**{**base, **kw})


def _row(d: c.Decision, **kw) -> SimpleNamespace:
    """A decision as stored (BrainDecision): plain strings, list of reasons."""
    base = {
        "id": 1,
        "symbol": d.symbol,
        "kind": d.kind,
        "word": d.word.value,
        "reasons": list(d.reasons),
        "downgrade_reason": d.downgrade_reason,
        "confidence": d.confidence,
        "score_source": d.confidence_source,
    }
    return SimpleNamespace(**{**base, **kw})


def _keys(items) -> list[str]:
    return [i["key"] for i in items]


def _texts(items) -> list[str]:
    return [i["text"] for i in items]


def _one(facts: IdeaFacts, **kw) -> tuple[c.Decision, list[dict]]:
    d = decide_idea(facts, POLICY)
    return d, what_would_change(_row(d), **kw)


# --- every idea rule (rules.py), run for real ------------------------------------------


def test_exchange_watch_list_names_the_list():
    d, items = _one(_facts(stock=c.StockState(symbol="ABC", trend="up", restrictions=("ASM (Stage 1)",))))
    assert d.word is IdeaWord.AVOID
    assert items[0] == {
        "key": "exchange_watch_list",
        "text": "Only if the exchange removes it from its watch list (ASM (Stage 1)).",
    }


def test_results_soon_gives_the_date():
    sit = c.Situation(
        scope="stock",
        subject="ABC",
        label="results soon",
        confidence=1.0,
        evidence=("Results on 28 Oct: the brain avoids new trades 5 trading days before results",),
    )
    d, items = _one(_facts(situations=(sit,)))
    assert d.word is IdeaWord.AVOID
    assert items[0] == {"key": "results", "text": "After the results on 28 Oct."}


def test_event_blackout_names_the_action_and_date():
    sit = c.Situation(
        scope="stock",
        subject="ABC",
        label="event blackout",
        confidence=1.0,
        evidence=("Bonus 1:1 on 23 Oct resets the share price",),
    )
    d, items = _one(_facts(situations=(sit,)))
    assert d.word is IdeaWord.AVOID
    assert items[0] == {"key": "corporate_action", "text": "After the Bonus 1:1 on 23 Oct has taken effect."}


def test_event_without_details_still_maps():
    sit = c.Situation(scope="stock", subject="ABC", label="event blackout", confidence=1.0)
    _, items = _one(_facts(situations=(sit,)))
    assert items[0]["key"] == "event"


def test_weak_signals():
    op = c.Opinion(source="reason", symbol="ABC", stance=0.5, confidence=0.1, reasons=("x",))
    d, items = _one(_facts(opinion=op))
    assert d.word is IdeaWord.WAIT
    assert items[0]["key"] == "weak_signals"


def test_risk_check_missing_verdict():
    d, items = _one(_facts(verdict=None))
    assert d.word is IdeaWord.WATCH
    assert items == [
        {"key": "not_approved", "text": "The risk check would need to approve a trade in this stock."}
    ]


def test_negative_expected_result():
    recall = c.Recall(symbol="ABC", n_similar=50, hit_rate=0.1)
    d, items = _one(_facts(recall=recall))
    assert d.word is IdeaWord.WAIT
    assert items[0]["key"] == "similar_cases_lost"
    assert "%" not in items[0]["text"] and "R" not in items[0]["text"].split()


def test_careful_market_and_falling_stock():
    d, items = _one(_facts(market_mode=MarketMode.DEFENSIVE, stock=c.StockState(symbol="ABC", trend="down")))
    assert d.word is IdeaWord.WATCH
    assert items[0] == {
        "key": "careful_market_falling",
        "text": "The stock would need to start rising, or the market mode return to NORMAL.",
    }


def test_sector_gate(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 5)
    d, items = _one(_facts(sector_rank=9))
    assert d.word is IdeaWord.WAIT
    assert items[0] == {
        "key": "sector_rank",
        "text": "Its sector would need to climb into the top 5 (today it ranks 9 of 15).",
    }


def test_playbook_gate(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_PLAYBOOK_GATE", True)
    d, items = _one(_facts(playbook_match=False))
    assert d.word is IdeaWord.WAIT
    assert items[0]["key"] == "no_setup"


# --- the engine's own WAIT drafts ------------------------------------------------------


def _below(prob: float = 0.45) -> c.Opinion:
    return c.Opinion(
        source="model",
        symbol="ABC",
        stance=-0.1,
        confidence=0.1,
        probability=prob,
        threshold=0.6,
        reasons=("x",),
    )


def test_below_buy_level_is_a_ranking_never_a_chance():
    d, items = _one(_facts(opinion=_below()))
    assert d.word is IdeaWord.WAIT
    assert items == [
        {
            "key": "below_buy_level",
            "text": "The model would need to rank this stock higher (today it is below the buy level).",
        }
    ]
    assert "%" not in items[0]["text"]


def test_below_buy_level_with_its_position():
    d = decide_idea(_facts(opinion=_below()), POLICY)
    items = what_would_change(_row(d), rank=ModelRank(position=37, scored=120, above_buy_level=5))
    assert items[0]["text"].endswith(
        "Today it ranks 37th of 120 stocks the model scored; only the top 5 were above the buy level."
    )
    assert "%" not in items[0]["text"]


def test_calibrated_chance_below_the_needed_level():
    op = replace(_below(), calibrated=True)
    d, items = _one(_facts(opinion=op))
    assert d.word is IdeaWord.WAIT and items[0]["key"] == "chance_too_low"
    assert "%" not in items[0]["text"]


def test_signals_not_in_favour():
    op = c.Opinion(source="reason", symbol="ABC", stance=-0.5, confidence=0.6, reasons=("x",))
    _, items = _one(_facts(opinion=op))
    assert items[0]["key"] == "signals_not_favourable"


def test_no_price_and_no_opinion():
    assert _keys(_one(_facts(snapshot=None))[1]) == ["no_price"]
    assert _keys(_one(_facts(opinion=None))[1]) == ["no_opinion"]


# --- several rules at once: all listed, the deciding one first ---------------------------


def test_several_conditions_are_all_listed_most_important_first():
    d, items = _one(
        _facts(
            verdict=c.RiskVerdict(
                symbol="ABC",
                allowed=False,
                rule="POSITION_LIMIT",
                reason="All position slots are already in use by your current holdings.",
            ),
            recall=c.Recall(symbol="ABC", n_similar=50, hit_rate=0.1),
        )
    )
    # The risk check lowered it to WATCH, then similar cases lowered it to WAIT: the reason
    # that set the final word comes first.
    assert d.word is IdeaWord.WAIT
    assert _keys(items) == ["similar_cases_lost", "slots_full"]


def test_informational_lines_are_not_conditions():
    d, items = _one(_facts(verdict=None))
    # The plan line and the model's own reason are on the decision but are not conditions.
    assert any(r.startswith("Plan:") for r in d.reasons)
    assert _keys(items) == ["not_approved"]


# --- the risk gate (M07 allocator), run for real -------------------------------------------


def _account(**kw) -> Account:
    base = {
        "portfolio_value": 1_000_000.0,
        "cash": 1_000_000.0,
        "free_slots": 10,
        "min_position_inr": 10_000.0,
        "sector_rule": "pct_cap",
        "sector_cap_pct": 0.25,
        "sector_exposure": {},
        "deploy_room": 1_000_000.0,
    }
    return Account(**{**base, **kw})


def _allocated(cands, account, mode=MarketMode.NORMAL, qty=100) -> dict[str, c.RiskVerdict]:
    def check(cand, cash_left):
        return CheckResult(allowed=True, qty=qty, reason="Sized by risk-per-trade")

    verdicts = allocate(cands, account, check, Policy(mode=mode), lambda p, q: p * q)
    return {v.symbol: v for v in verdicts}


def _risk_items(verdict: c.RiskVerdict) -> list[dict]:
    d = decide_idea(_facts(verdict=replace(verdict, symbol="ABC")), POLICY)
    assert d.word is IdeaWord.WATCH
    return what_would_change(_row(d))


def test_allocator_no_new_trades():
    v = _allocated([Candidate("ABC", 100.0, 0.9, None)], _account(), MarketMode.NO_NEW_TRADES)["ABC"]
    assert _keys(_risk_items(v)) == ["market_no_new_trades"]


def test_allocator_defensive_limit():
    cands = [Candidate(s, 100.0, 0.9 - i / 10, None) for i, s in enumerate(["A1", "A2", "ABC"])]
    v = _allocated(cands, _account(), MarketMode.DEFENSIVE, qty=1000)["ABC"]
    items = _risk_items(v)
    assert items[0]["key"] == "defensive_limit" and "2 strongest" in items[0]["text"]


def test_allocator_slots():
    cands = [Candidate("A1", 100.0, 0.9, None), Candidate("ABC", 100.0, 0.5, None)]
    v = _allocated(cands, _account(free_slots=1))["ABC"]
    assert _keys(_risk_items(v)) == ["slots_taken_by_stronger"]
    v = _allocated([Candidate("ABC", 100.0, 0.5, None)], _account(free_slots=0))["ABC"]
    assert _keys(_risk_items(v)) == ["slots_full"]


def test_allocator_one_per_sector():
    cands = [Candidate("A1", 100.0, 0.9, "BANK"), Candidate("ABC", 100.0, 0.5, "BANK")]
    v = _allocated(cands, _account(sector_rule="one_per_sector", sector_cap_pct=None))["ABC"]
    assert _keys(_risk_items(v)) == ["one_per_sector_run"]


def test_allocator_room_quotes_the_stored_amounts():
    cands = [Candidate("A1", 100.0, 0.9, None), Candidate("ABC", 100.0, 0.5, None)]
    v = _allocated(cands, _account(deploy_room=15_000.0))["ABC"]
    items = _risk_items(v)
    assert items == [
        {
            "key": "room_after_stronger",
            "text": "Needs about ₹10,000 of free room under the market-conditions limit (today ₹5,000).",
        }
    ]


def _defensive_items(verdict: c.RiskVerdict) -> list[dict]:
    d = decide_idea(_facts(verdict=replace(verdict, symbol="ABC")), POLICY)
    return what_would_change(_row(d), banner_mode="DEFENSIVE")


def test_careful_market_room_needs_about_twice_the_minimum():
    # M07 fits the buy to the free room first and halves it after, but still compares it with the
    # full minimum: in a careful market about twice the minimum must be free, not the minimum.
    cands = [Candidate("ABC", 100.0, 0.9, None)]
    v = _allocated(cands, _account(deploy_room=15_000.0), MarketMode.DEFENSIVE, qty=1000)["ABC"]
    assert _defensive_items(v) == [
        {
            "key": "room_after_stronger",
            "text": "Needs about ₹20,000 of free room under the market-conditions limit: in a careful market "
            "each buy is cut to half size, so the room must be about twice the ₹10,000 minimum "
            "(today a half-size buy would be ₹7,500).",
        }
    ]


def test_careful_market_half_size_alone_below_the_minimum():
    # Plenty of room; the risk-sized buy (₹15,000) halved to ₹7,500 is what falls short.
    v = _allocated([Candidate("ABC", 100.0, 0.9, None)], _account(), MarketMode.DEFENSIVE, qty=150)["ABC"]
    assert _defensive_items(v) == [
        {
            "key": "defensive_half_size",
            "text": "The market would need to return to NORMAL: in a careful market each buy is cut to half "
            "size, and half of this one (₹7,500) is below the ₹10,000 minimum.",
        }
    ]


def test_normal_market_room_line_is_unchanged():
    cands = [Candidate("A1", 100.0, 0.9, None), Candidate("ABC", 100.0, 0.5, None)]
    v = _allocated(cands, _account(deploy_room=15_000.0))["ABC"]
    d = decide_idea(_facts(verdict=replace(v, symbol="ABC")), POLICY)
    assert what_would_change(_row(d), banner_mode="NORMAL")[0]["text"] == (
        "Needs about ₹10,000 of free room under the market-conditions limit (today ₹5,000)."
    )


# --- version 1's risk.check_entry refusals (texts copied from services/risk.py) ----------

V1_REFUSALS = [
    ("New buys are paused: owner test. Existing positions still sell normally.", "owner_paused", None),
    ("Position already open in this instrument", "already_open", None),
    ("Stopped out within the last 5 days — cooling down", "cooldown", "5-day"),
    (
        "The exchange has put ABC on its extra-watch list (ASM, Stage 1). Trading in it can be "
        "restricted, so it may be hard to sell.",
        "exchange_watch_list",
        None,
    ),
    ("ABC is in delivery-only trading right now, which limits how it can be sold.", "delivery_only", None),
    (
        "ABC announces its results on 28 Oct. The price can jump either way on the news, past any stop-loss.",
        "results",
        "28 Oct",
    ),
    (
        "ABC has a corporate action on 23 Oct (Bonus 1:1) that resets its share price.",
        "corporate_action",
        "Bonus 1:1",
    ),
    (
        "You already hold 5 positions — the most allowed for an account of ₹10,00,000 is 5",
        "slots_full",
        None,
    ),
    (
        "TradeMind brain already holds 2 of its 2 positions — the rest of the 5 allowed for an account "
        "of ₹10,00,000 are left for your other strategies",
        "slots_full",
        None,
    ),
    (
        "Your account is 16% below its peak — past the 15% safety limit, so new buys are paused "
        "until it recovers",
        "drawdown",
        "15%",
    ),
    (
        "One share costs ₹42,000 — at this account size the bot skips shares above ₹5,000, because a "
        "sensible position can't be built from one or two shares",
        "share_price",
        "₹5,000",
    ),
    (
        "Small-company stocks are switched off for an account of ₹50,000 — they unlock as the account grows, "
        "once one bad pick can't do outsized damage",
        "cap_tier_off",
        "small-company",
    ),
    (
        "Small-company stocks already take ₹1,00,000 (10%) of your money — another position would go over "
        "your 10% limit for them",
        "small_company_budget",
        None,
    ),
    (
        "You already hold HDFCBANK in Banks. At this account size the bot keeps to one stock per sector, "
        "so one bad day for a sector can't hit two positions at once",
        "one_per_sector_held",
        "HDFCBANK",
    ),
    (
        "Banks would go to 27% of your money — over your 25% limit for one sector (you already hold "
        "₹2,40,000 there)",
        "sector_cap",
        "25%",
    ),
    (
        "ABC trades only about ₹3,00,000 a day. A position may be at most 2% of that (₹6,000), below the "
        "₹10,000 minimum — too thinly traded to get in and out cleanly",
        "liquidity",
        "₹3,00,000",
    ),
    (
        "The market looks shaky right now, so the bot keeps at most 50% of your money invested (₹5,00,000). "
        "You already have ₹4,95,000 invested, leaving ₹5,000 — less than the ₹10,000 minimum position",
        "deployable_room",
        "₹10,000",
    ),
    (
        "Buying would leave less than ₹20,000 in cash — the reserve kept aside for an account of ₹10,00,000. "
        "You have ₹25,000 in cash",
        "cash_reserve",
        "₹25,000",
    ),
    (
        "The position would only be ₹4,000 (limited by the sector limit) — below the ₹10,000 minimum that "
        "keeps fixed charges from eating the trade at this account size",
        "min_position",
        "₹4,000",
    ),
    (
        "Not enough cash: buying costs ₹50,120 including charges, and you have ₹30,000",
        "cash",
        "₹50,120",
    ),
    ("No price for this stock, so it cannot be sized.", "no_price", None),
    ("Data is not reliable today (stale prices).", "data_not_reliable", None),
    ("This stock is not in the instrument list.", "no_instrument", None),
    (
        "Risk checks use today's account, so a replay of a past date never approves a trade.",
        "replay",
        None,
    ),
    ("The risk check failed for this stock (boom), so it is refused to stay safe.", "risk_error", None),
    ("Some brand-new limit nobody mapped yet.", "account_limits", None),
]


@pytest.mark.parametrize(("reason", "key", "quoted"), V1_REFUSALS)
def test_v1_refusals(reason, key, quoted):
    items = _risk_items(c.RiskVerdict(symbol="ABC", allowed=False, reason=reason))
    assert items[0]["key"] == key
    if quoted is not None:
        assert quoted in items[0]["text"]


# --- the constitution (C1, C2, C5, C12) and the fallback ----------------------------------


def _watch(reason: str, word: str = "WATCH") -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        symbol="ABC",
        kind="idea",
        word=word,
        reasons=[reason, "Plan: buy around ₹990"],
        downgrade_reason=reason,
        confidence=None,
        score_source=None,
    )


@pytest.mark.parametrize(
    ("reason", "key"),
    [
        (constitution.NO_RISK_GATE, "no_risk_gate"),
        (constitution.NOT_APPROVED, "not_approved"),
        (constitution.DATA_NOT_CHECKED, "data_not_checked"),
        ("Data is not reliable today (prices are 3 days old).", "data_not_reliable"),
        (constitution.BAD_PLAN, "bad_plan"),
        ("Owner paused new buys: holiday.", "owner_paused"),
        ("Market data is not reliable today: NIFTY is 2 days old", "market_data_not_reliable"),
        ("No decision was produced for this stock.", "no_decision"),
    ],
)
def test_constitution_reasons(reason, key):
    assert _keys(what_would_change(_watch(reason))) == [key]


def test_no_new_trades_banner_headline_is_recognised_only_with_that_banner():
    headline = "Most stocks are falling; no new trades today."
    assert _keys(
        what_would_change(_watch(headline), banner_mode="NO_NEW_TRADES", banner_headline=headline)
    ) == ["market_no_new_trades"]
    assert _keys(what_would_change(_watch(headline), banner_mode="NORMAL", banner_headline=headline)) == [
        "unknown"
    ]


# --- honesty: never guess, only ideas that are not TRADE -----------------------------------


def test_an_unknown_deciding_reason_says_so_first():
    items = what_would_change(_watch("A reason from a rule written next year."))
    assert items == [{"key": "unknown", "text": UNKNOWN}]


def test_unknown_deciding_reason_then_known_ones():
    row = _watch("Something new.")
    row.reasons = ["Something new.", "The risk check has not approved this trade."]
    assert _keys(what_would_change(row)) == ["unknown", "not_approved"]


def test_trade_and_holdings_get_nothing():
    d = decide_idea(_facts(), POLICY)
    assert d.word is IdeaWord.TRADE
    assert what_would_change(_row(d)) == []
    holding = SimpleNamespace(kind="holding", word="MONITOR", reasons=["x"], downgrade_reason="x")
    assert what_would_change(holding) == []


def test_no_line_mentions_profit_or_hit_rate():
    """Sealed results: these lines never quote outcomes."""
    for reason, _key, _q in V1_REFUSALS:
        for item in _risk_items(c.RiskVerdict(symbol="ABC", allowed=False, reason=reason)):
            low = item["text"].lower()
            assert "hit rate" not in low and "profit" not in low and "win" not in low.split()


# --- ranks ----------------------------------------------------------------------------------


def _scored(i: int, conf: float, below: bool, source: str = "model") -> SimpleNamespace:
    reasons = ["Model score 40% is below the buy level 60%."] if below else ["The model scores this 70%."]
    return SimpleNamespace(
        id=i,
        symbol=f"S{i}",
        kind="idea",
        word="WAIT" if below else "TRADE",
        reasons=reasons,
        confidence=conf,
        score_source=source,
    )


def test_model_ranks_count_only_raw_model_scores():
    rows = [
        _scored(1, 0.9, False),
        _scored(2, 0.7, False),
        _scored(3, 0.5, True),
        _scored(4, 0.3, True),
        _scored(5, 0.95, False, source="combined"),  # a calibrated chance, not comparable
        SimpleNamespace(
            id=6, symbol="H", kind="holding", word="HOLD", reasons=[], confidence=0.99, score_source="model"
        ),
    ]
    ranks = model_ranks(rows)
    assert set(ranks) == {1, 2, 3, 4}
    assert ranks[3] == ModelRank(position=3, scored=4, above_buy_level=2)


@pytest.mark.parametrize(
    ("above", "tail"),
    [
        (0, "none were above the buy level."),
        (1, "only the top 1 was above the buy level."),
        (3, "only the top 3 were above the buy level."),
    ],
)
def test_rank_wording(above, tail):
    d = decide_idea(_facts(opinion=_below()), POLICY)
    text = what_would_change(_row(d), rank=ModelRank(position=22, scored=40, above_buy_level=above))[0][
        "text"
    ]
    assert "22nd of 40" in text and text.endswith(tail)
