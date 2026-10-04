"""Brain contracts: the decision vocabulary and the shapes modules exchange.

The vocabulary's ordering is what makes the brain's monotonic rule possible —
a fallback or a failed check may only move a decision toward caution — so its
rank functions are tested directly, not only through the runner.
"""

from __future__ import annotations

import pytest

from swing_trade_ml.brain import contracts as c


def test_idea_words_are_ranked_from_most_cautious_to_boldest():
    ranks = [c.rank(w) for w in (c.IdeaWord.AVOID, c.IdeaWord.WAIT, c.IdeaWord.WATCH, c.IdeaWord.TRADE)]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


def test_holding_words_are_ranked_from_most_cautious_to_boldest():
    ranks = [
        c.rank(w)
        for w in (c.HoldingWord.EXIT, c.HoldingWord.REDUCE, c.HoldingWord.MONITOR, c.HoldingWord.HOLD)
    ]
    assert ranks == sorted(ranks)


def _decision(**overrides) -> c.Decision:
    base = {"symbol": "ABC", "kind": "idea", "word": c.IdeaWord.WAIT, "reasons": ("No edge today",)}
    return c.Decision(**{**base, **overrides})


def test_downgrade_lowers_a_trade_and_records_why():
    d = _decision(word=c.IdeaWord.TRADE, reasons=("Model is positive",))
    lowered = c.downgrade(d, c.IdeaWord.WATCH, "Risk gate is not installed")
    assert lowered.word is c.IdeaWord.WATCH
    assert lowered.downgraded_from is c.IdeaWord.TRADE
    assert lowered.downgrade_reason == "Risk gate is not installed"
    assert lowered.reasons[0] == "Risk gate is not installed"


def test_downgrade_never_makes_a_decision_bolder():
    d = _decision(word=c.IdeaWord.WAIT)
    assert c.downgrade(d, c.IdeaWord.TRADE, "should be ignored") == d


def test_validate_rejects_a_holding_word_on_an_idea():
    with pytest.raises(c.ContractError):
        c.validate_record(_decision(word=c.HoldingWord.HOLD))


def test_validate_rejects_a_decision_without_a_reason():
    with pytest.raises(c.ContractError):
        c.validate_record(_decision(reasons=()))


def test_contribution_reports_which_contracts_it_carries():
    contrib = c.Contribution(
        opinions=(c.Opinion(source="test", symbol="ABC", stance=0.2, confidence=0.5, reasons=("x",)),),
    )
    assert contrib.contract_names() == {"Opinion@1"}


def test_empty_contribution_carries_nothing():
    assert c.Contribution().contract_names() == set()
