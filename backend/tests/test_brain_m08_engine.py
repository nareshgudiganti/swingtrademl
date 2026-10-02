"""M08's pure decision engine: drafts, rules that only lower, levels,
evidence, expected result in R, holdings and opportunity cost."""

from __future__ import annotations

from dataclasses import replace

import pytest

from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.brain.modules.m08_decide.engine import (
    HoldingFacts,
    IdeaFacts,
    decide_holding,
    decide_idea,
    expected_r,
    opportunity_notes,
)
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m08_decide.rules import HOLDING_RULES, IDEA_RULES, Rule

POLICY = DecidePolicy()


def _idea(**kw) -> IdeaFacts:
    base = {
        "symbol": "ABC",
        "snapshot": c.Snapshot(symbol="ABC", as_of="2026-09-25", close=1000.0, atr_14=20.0),
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
        "stock": c.StockState(symbol="ABC", trend="up", rel_strength_vs_nifty=0.03),
        "situations": (),
        "recall": None,
        "market_mode": MarketMode.NORMAL,
    }
    return IdeaFacts(**{**base, **kw})


# --- drafts and levels -------------------------------------------------------------


def test_a_liked_approved_stock_is_a_trade_with_zone_target_stop_and_size():
    d = decide_idea(_idea(), POLICY)
    assert d.word is IdeaWord.TRADE and d.qty == 25
    assert (d.entry_low, d.entry_high) == (995.0, 1005.0)  # plus or minus a quarter of ATR 20
    assert d.target == 1080.0 and d.stop == 960.0 and d.horizon_days == 15


def test_the_entry_zone_is_capped_at_one_percent():
    snap = c.Snapshot(symbol="ABC", as_of="d", close=1000.0, atr_14=200.0)
    d = decide_idea(_idea(snapshot=snap), POLICY)
    assert (d.entry_low, d.entry_high) == (990.0, 1010.0)


def test_below_the_buy_level_is_wait_with_the_score():
    op = c.Opinion(
        source="model",
        symbol="ABC",
        stance=-0.1,
        confidence=0.1,
        probability=0.45,
        threshold=0.6,
        reasons=("x",),
    )
    d = decide_idea(_idea(opinion=op), POLICY)
    assert d.word is IdeaWord.WAIT and "45%" in d.reasons[0]


def test_no_price_or_no_opinion_is_wait():
    assert decide_idea(_idea(snapshot=None), POLICY).word is IdeaWord.WAIT
    assert decide_idea(_idea(opinion=None), POLICY).word is IdeaWord.WAIT


# --- confidence_source (F4): which kind of number `confidence` is --------------------


def test_trade_carries_the_speaking_opinions_source_as_confidence_source():
    d = decide_idea(_idea(), POLICY)
    assert d.confidence == pytest.approx(0.7) and d.confidence_source == "model"


def test_wait_below_the_buy_level_carries_the_opinions_source():
    op = c.Opinion(
        source="model",
        symbol="ABC",
        stance=-0.1,
        confidence=0.1,
        probability=0.45,
        threshold=0.6,
        reasons=("x",),
    )
    d = decide_idea(_idea(opinion=op), POLICY)
    assert d.confidence == pytest.approx(0.45) and d.confidence_source == "model"


def test_calibrated_wait_carries_the_opinions_source():
    op = c.Opinion(
        source="combined",
        symbol="ABC",
        stance=-0.2,
        confidence=0.3,
        probability=0.4,
        threshold=0.55,
        calibrated=True,
        reasons=("x",),
    )
    d = decide_idea(_idea(opinion=op), POLICY)
    assert d.word is IdeaWord.WAIT
    assert d.confidence == pytest.approx(0.4) and d.confidence_source == "combined"


def test_wait_with_only_an_opinions_own_confidence_has_no_score_source():
    """`confidence_source` is only set when `confidence` is a probability; an
    opinion's own confidence (no probability at all) is not one."""
    op = c.Opinion(
        source="combined", symbol="ABC", stance=0.2, confidence=0.15, reasons=("Model yes, rules no",)
    )
    d = decide_idea(_idea(opinion=op), POLICY)
    assert d.word is IdeaWord.WAIT
    assert d.confidence == pytest.approx(0.15) and d.confidence_source is None


def test_no_price_or_no_opinion_has_no_confidence_source():
    assert decide_idea(_idea(snapshot=None), POLICY).confidence_source is None
    assert decide_idea(_idea(opinion=None), POLICY).confidence_source is None


# --- idea rules ------------------------------------------------------------------


def test_an_exchange_watch_list_stock_is_avoid():
    stock = c.StockState(symbol="ABC", trend="up", restrictions=("ASM stage 1",))
    d = decide_idea(_idea(stock=stock), POLICY)
    assert d.word is IdeaWord.AVOID and "ASM stage 1" in d.reasons[0]


def test_results_soon_is_avoid():
    sit = c.Situation(
        scope="stock", subject="ABC", label="results soon", confidence=1.0, evidence=("Results on 2 Oct",)
    )
    d = decide_idea(_idea(situations=(sit,)), POLICY)
    assert d.word is IdeaWord.AVOID and "Results on 2 Oct" in d.reasons[0]


def test_a_refused_risk_check_is_watch_with_its_reason():
    v = c.RiskVerdict(symbol="ABC", allowed=False, rule="SECTOR_CAP", reason="Banks already at 25%")
    d = decide_idea(_idea(verdict=v), POLICY)
    assert d.word is IdeaWord.WATCH and "Banks already at 25%" in d.reasons[0]


def test_weak_conflicting_signals_are_wait():
    op = c.Opinion(
        source="combined", symbol="ABC", stance=0.2, confidence=0.15, reasons=("Model yes, rules no",)
    )
    assert decide_idea(_idea(opinion=op), POLICY).word is IdeaWord.WAIT


def test_a_defensive_market_needs_the_stock_in_an_up_trend():
    falling = c.StockState(symbol="ABC", trend="down")
    d = decide_idea(_idea(stock=falling, market_mode=MarketMode.DEFENSIVE), POLICY)
    assert d.word is IdeaWord.WATCH and "falling" in d.reasons[0]
    assert decide_idea(_idea(market_mode=MarketMode.DEFENSIVE), POLICY).word is IdeaWord.TRADE


def test_negative_expected_result_is_wait():
    recall = c.Recall(symbol="ABC", n_similar=120, hit_rate=0.25, p25=-0.04, p75=0.03)
    d = decide_idea(_idea(recall=recall), POLICY)
    assert d.word is IdeaWord.WAIT and "lost" in d.reasons[0]


# --- flexibility and safety of the rule list ----------------------------------------


def test_switching_a_rule_off_removes_exactly_its_effect():
    falling = c.StockState(symbol="ABC", trend="down")
    facts = _idea(stock=falling, market_mode=MarketMode.DEFENSIVE)
    policy = replace(POLICY, disabled=frozenset({"defensive_needs_uptrend"}))
    assert decide_idea(facts, policy).word is IdeaWord.TRADE


def test_a_rule_can_never_make_a_decision_bolder():
    bold = Rule("bold", "Tries to promote", "idea", lambda d, f, p: (IdeaWord.TRADE, "promote"))
    op = c.Opinion(
        source="model",
        symbol="ABC",
        stance=-0.1,
        confidence=0.1,
        probability=0.45,
        threshold=0.6,
        reasons=("x",),
    )
    d = decide_idea(_idea(opinion=op), POLICY, rules=[*IDEA_RULES, bold])
    assert d.word is IdeaWord.WAIT


def test_a_new_rule_plugs_in_without_touching_the_engine():
    no_fridays = Rule(
        "no_x",
        "Never buy ABC",
        "idea",
        lambda d, f, p: (IdeaWord.WATCH, "Owner rule: not ABC") if f.symbol == "ABC" else None,
    )
    d = decide_idea(_idea(), POLICY, rules=[*IDEA_RULES, no_fridays])
    assert d.word is IdeaWord.WATCH and d.reasons[0] == "Owner rule: not ABC"


def test_every_rule_has_a_unique_id_and_a_plain_name():
    ids = [r.id for r in IDEA_RULES + HOLDING_RULES]
    assert len(ids) == len(set(ids)) and all(r.name for r in IDEA_RULES + HOLDING_RULES)


# --- evidence and expected result ------------------------------------------------------


def test_without_similar_cases_the_evidence_says_the_score_is_not_a_probability():
    d = decide_idea(_idea(), POLICY)
    assert "No similar-case record yet" in d.evidence_text and "70%" in d.evidence_text


def test_with_similar_cases_the_evidence_and_expected_result_are_shown():
    recall = c.Recall(symbol="ABC", n_similar=120, hit_rate=0.45, p25=-0.03, p75=0.07)
    d = decide_idea(_idea(recall=recall), POLICY)
    assert d.word is IdeaWord.TRADE
    assert "120" in d.evidence_text and "45%" in d.evidence_text and "R" in d.evidence_text


def test_expected_r_matches_the_formula():
    # p=0.45: 0.45*2 - 0.55*1 = 0.35, minus 0.4% cost / 4% risk = 0.1 -> 0.25
    assert expected_r(0.45, 0.004, POLICY) == pytest.approx(0.25)


def test_no_promise_words_in_any_text():
    texts = []
    for facts in (
        _idea(),
        _idea(recall=c.Recall(symbol="ABC", n_similar=50, hit_rate=0.5, p25=-0.02, p75=0.06)),
    ):
        d = decide_idea(facts, POLICY)
        texts += [*d.reasons, d.evidence_text]
    assert not any(w in t.lower() for t in texts for w in ("will ", "guarantee", "sure "))


# --- holdings ---------------------------------------------------------------------


def _held(**kw) -> HoldingFacts:
    base = {
        "holding": c.Holding(symbol="HLD", qty=10, avg_price=1000.0, stop=960.0, target=1080.0),
        "snapshot": c.Snapshot(symbol="HLD", as_of="d", close=1010.0),
        "stock": c.StockState(symbol="HLD", trend="up", rel_strength_vs_nifty=0.01),
        "market_mode": MarketMode.NORMAL,
    }
    return HoldingFacts(**{**base, **kw})


def test_a_healthy_holding_is_hold():
    assert decide_holding(_held(), POLICY).word is HoldingWord.HOLD


def test_a_hit_stop_is_exit_and_says_stop_hit():
    d = decide_holding(_held(snapshot=c.Snapshot(symbol="HLD", as_of="d", close=955.0)), POLICY)
    assert d.word is HoldingWord.EXIT and d.reasons[0].startswith("Stop hit")


def test_the_first_target_is_reduce_once():
    up = c.Snapshot(symbol="HLD", as_of="d", close=1060.0)
    assert decide_holding(_held(snapshot=up), POLICY).word is HoldingWord.REDUCE
    done = c.Holding(symbol="HLD", qty=5, avg_price=1000.0, stop=1000.0, scaled_out=True)
    assert decide_holding(_held(snapshot=up, holding=done), POLICY).word is HoldingWord.HOLD


def test_a_falling_holding_in_a_careful_market_is_monitor():
    d = decide_holding(
        _held(
            stock=c.StockState(symbol="HLD", trend="down"),
            snapshot=c.Snapshot(symbol="HLD", as_of="d", close=990.0),
            market_mode=MarketMode.DEFENSIVE,
        ),
        POLICY,
    )
    assert d.word is HoldingWord.MONITOR


def test_a_holding_lagging_nifty_is_monitor():
    d = decide_holding(
        _held(stock=c.StockState(symbol="HLD", trend="sideways", rel_strength_vs_nifty=-0.15)), POLICY
    )
    assert d.word is HoldingWord.MONITOR and "15%" in d.reasons[0]


def test_opportunity_cost_note_only_when_slots_are_full_and_a_strong_idea_waits():
    full = c.RiskVerdict(
        symbol="ABC", allowed=False, rule="POSITION_LIMIT", reason="All position slots are already in use"
    )
    idea_facts = _idea(verdict=full)
    held_facts = _held(stock=c.StockState(symbol="HLD", trend="sideways", rel_strength_vs_nifty=-0.15))
    waiting, weak = decide_idea(idea_facts, POLICY), decide_holding(held_facts, POLICY)
    ideas, holdings = opportunity_notes(
        {"ABC": waiting}, {"ABC": idea_facts}, {"HLD": weak}, {"HLD": held_facts}
    )
    assert "consider replacing" in holdings["HLD"].reasons[-1] and "ABC" in holdings["HLD"].reasons[-1]
    assert holdings["HLD"].word is weak.word  # words only, never a forced sale
    assert "HLD" in ideas["ABC"].reasons[-1]


def test_no_opportunity_note_when_a_slot_is_free():
    idea_facts = _idea()  # approved: a slot exists
    held_facts = _held(stock=c.StockState(symbol="HLD", trend="sideways", rel_strength_vs_nifty=-0.15))
    _ideas, holdings = opportunity_notes(
        {"ABC": decide_idea(idea_facts, POLICY)},
        {"ABC": idea_facts},
        {"HLD": decide_holding(held_facts, POLICY)},
        {"HLD": held_facts},
    )
    assert not any("consider replacing" in r for r in holdings["HLD"].reasons)


# --- honest recall (M05) -----------------------------------------------------------------


def _honest(mean=0.005, honest_mean=0.004, **kw):
    base = {
        "symbol": "ABC",
        "n_similar": 124,
        "hit_rate": 0.38,
        "mean_return": mean,
        "honest_hit_rate": 0.24,
        "honest_mean_return": honest_mean,
        "p25": -0.03,
        "p75": 0.05,
        "median_days": 9.0,
        "key": "market correction · stock trend down",
    }
    return c.Recall(**{**base, **kw})


def test_honest_recall_reads_like_the_build_book_and_says_what_held_up():
    d = decide_idea(_idea(recall=_honest()), POLICY)
    t = d.evidence_text
    assert t.startswith(
        "Similar cases: 124 · reached +8% first in 38% · middle half ended between -3.0% and +5.0%"
    )
    assert "median 9 trading days" in t and "came true about 24%" in t


def test_expected_result_uses_the_average_exit_not_every_miss_as_a_full_loss():
    from swing_trade_ml.brain.modules.m08_decide.money import cost_pct, expected_r_from_mean

    cost = cost_pct(1000.0, 25)
    assert expected_r_from_mean(0.004, cost, POLICY) == pytest.approx((0.004 - cost) / 0.04)
    d = decide_idea(_idea(recall=_honest()), POLICY)
    assert f"{(0.004 - cost) / 0.04:+.2f} R per trade" in d.evidence_text


def test_an_honest_average_below_costs_is_wait():
    d = decide_idea(_idea(recall=_honest(honest_mean=-0.002)), POLICY)
    assert d.word is IdeaWord.WAIT and "lost money on average" in d.reasons[0]
