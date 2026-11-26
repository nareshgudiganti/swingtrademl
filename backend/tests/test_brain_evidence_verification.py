# ruff: noqa: E501 (long plain-English test text)
"""#242: Brain decisions carry evidence that matches what decided them, and every non-TRADE idea explains itself in plain words
(verification tests; nothing here changes the Brain, a model or the sealed trial).

Findings note: docs/verification/242-brain-evidence.md. Existing coverage the note cites and re-runs: test_brain_m08_engine.py,
test_what_would_change.py (every mapping pinned from hand-copied texts), test_brain_what_would_change_api.py,
test_brain_caution_only.py (the 7,776-situation caution grid), test_brain_api.py.

What is new here: (1) every decision rule is run through the REAL engine and the real "what would change" mapper, and a new rule
without a scenario fails; (2) every v1 risk refusal is produced by the REAL `risk.check_entry` (not copied text) and mapped;
(3) thresholds in the explanations equal the thresholds the rules use; (4) banners explain themselves.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

import swing_trade_ml
from swing_trade_ml.brain import constitution
from swing_trade_ml.brain import contracts as c
from swing_trade_ml.brain.context import BrainContext
from swing_trade_ml.brain.contracts import HoldingWord, IdeaWord, MarketMode
from swing_trade_ml.brain.modules.m07_risk.module import DEFENSIVE_SIZE_FACTOR
from swing_trade_ml.brain.modules.m08_decide.engine import HoldingFacts, decide_holding, decide_idea
from swing_trade_ml.brain.modules.m08_decide.policy import DecidePolicy
from swing_trade_ml.brain.modules.m08_decide.rules import HOLDING_RULES, IDEA_RULES
from swing_trade_ml.core.config import settings
from swing_trade_ml.services import risk
from swing_trade_ml.services.limits import format_inr
from swing_trade_ml.services.what_would_change import UNKNOWN, what_would_change
from test_brain_m08_engine import _idea

SRC = Path(swing_trade_ml.__file__).parent
POLICY = DecidePolicy()
GENERIC = {
    "",
    UNKNOWN,
    "The brain says wait.",
    "Not now.",
    "The risk check said no.",
    "Not a good time.",
}


def _first_key(decision, **kwargs) -> str:
    items = what_would_change(decision, **kwargs)
    assert items, "a non-TRADE idea must have at least one 'what would change' line"
    return items[0]["key"]


# ------------------------------------------------------------------------------- ideas: one scenario per rule


def _situation(label: str, evidence: str) -> c.Situation:
    return c.Situation(scope="stock", subject="ABC", label=label, confidence=0.9, evidence=(evidence,))


def _weak_opinion() -> c.Opinion:
    return c.Opinion(source="combined", symbol="ABC", stance=0.2, confidence=0.1, reasons=("A weak view.",))


def _lost_money_recall() -> c.Recall:
    return c.Recall(symbol="ABC", n_similar=40, hit_rate=0.05)  # 5% reach the target: a negative expected result


RULE_SCENARIOS = {
    # rule id: (facts, word, text the FIRST reason must contain, key of the first what-would-change line)
    "exchange_watch_list": (
        lambda: _idea(stock=c.StockState(symbol="ABC", trend="up", restrictions=("ASM Stage 1",))),
        IdeaWord.AVOID, "ASM Stage 1", "exchange_watch_list",
    ),
    "event_window": (
        lambda: _idea(situations=(_situation("results soon", "Results on 28 Oct: the brain avoids new trades"),)),
        IdeaWord.AVOID, "28 Oct", "results",
    ),
    "weak_signals": (lambda: _idea(opinion=_weak_opinion()), IdeaWord.WAIT, "0.10", "weak_signals"),
    "risk_check": (
        lambda: _idea(verdict=c.RiskVerdict(symbol="ABC", allowed=False, rule="POSITION_LIMIT", reason="You already hold 5 positions — the most allowed for an account of ₹10,00,000 is 5")),
        IdeaWord.WATCH, "You already hold 5 positions", "slots_full",
    ),
    "negative_expected_result": (lambda: _idea(recall=_lost_money_recall()), IdeaWord.WAIT, "lost money on average", "similar_cases_lost"),
    "defensive_needs_uptrend": (
        lambda: _idea(market_mode=MarketMode.DEFENSIVE, stock=c.StockState(symbol="ABC", trend="down")),
        IdeaWord.WATCH, "this stock is falling", "careful_market_falling",
    ),
    "sector_gate": (lambda: _idea(sector_rank=7, sector_total=15), IdeaWord.WAIT, "ranks 7 of 15", "sector_rank"),
    "playbook_gate": (lambda: _idea(playbook_match=False), IdeaWord.WAIT, "No classic setup", "no_setup"),
}


def test_every_idea_rule_has_a_scenario_so_a_new_rule_cannot_ship_unexplained():
    assert set(RULE_SCENARIOS) == {rule.id for rule in IDEA_RULES}


@pytest.mark.parametrize("rule_id", sorted(RULE_SCENARIOS))
def test_each_idea_rule_gives_a_word_a_named_reason_evidence_and_a_what_would_change_line(rule_id, monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 3)
    monkeypatch.setattr(settings, "BRAIN_PLAYBOOK_GATE", True)
    make, word, needle, key = RULE_SCENARIOS[rule_id]
    facts = make()
    if facts.sector_rank is None:
        # With the sector gate on, an unranked sector is held back too (#488); give the other rules a top
        # sector so each scenario shows its own rule.
        facts = replace(facts, sector_rank=1, sector_total=15)
    d = decide_idea(facts, POLICY)
    assert d.word is word and d.qty == 0
    assert needle in d.reasons[0], d.reasons  # the FIRST reason names the real cause
    assert d.reasons[0] not in GENERIC and d.downgrade_reason == d.reasons[0] and d.downgraded_from is IdeaWord.TRADE
    assert d.evidence_text.strip(), "an idea carries its evidence line even when it is held back"
    assert _first_key(d) == key
    assert all(item["text"].strip() for item in what_would_change(d))


def test_the_sector_line_quotes_the_same_top_n_the_rule_used(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 3)
    d = decide_idea(_idea(sector_rank=7, sector_total=15), POLICY)
    line = what_would_change(d)[0]["text"]
    assert "top 3" in line and "7 of 15" in line


def test_an_unranked_sector_waits_and_explains_itself_when_the_gate_is_on(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_SECTOR_GATE_TOP_N", 3)
    d = decide_idea(_idea(), POLICY)  # no sector rank: missing data never lets an idea through (#488)
    assert d.word is IdeaWord.WAIT and "no strength rank" in d.reasons[0]
    items = what_would_change(d)
    assert items[0]["key"] == "sector_unranked" and "top 3" in items[0]["text"]


def test_the_weak_signal_and_negative_result_reasons_quote_the_numbers_the_rules_used():
    weak = decide_idea(_idea(opinion=_weak_opinion()), POLICY)
    assert f"{0.1:.2f}" in weak.reasons[0] and POLICY.uncertain_below > 0.1  # below the policy's own threshold
    lost = decide_idea(_idea(recall=_lost_money_recall()), POLICY)
    assert "R per trade" in lost.reasons[0] and POLICY.min_similar_cases <= 40


@pytest.mark.parametrize(
    "kwargs,word,needle,key",
    [
        ({"snapshot": None}, IdeaWord.WAIT, "No price data", "no_price"),
        ({"opinion": None}, IdeaWord.WAIT, "No opinion", "no_opinion"),
        (
            {"opinion": c.Opinion(source="model", symbol="ABC", stance=-0.1, confidence=0.1, probability=0.45, threshold=0.6, reasons=("x",))},
            IdeaWord.WAIT, "45%", "below_buy_level",
        ),
        (
            {"opinion": c.Opinion(source="combined", symbol="ABC", stance=-0.2, confidence=0.2, probability=0.4, threshold=0.55, calibrated=True, reasons=("x",))},
            IdeaWord.WAIT, "Calibrated chance 40%", "chance_too_low",
        ),
        (
            {"opinion": c.Opinion(source="combined", symbol="ABC", stance=-0.3, confidence=0.4, reasons=("x",))},
            IdeaWord.WAIT, "do not favour", "signals_not_favourable",
        ),
    ],
)
def test_each_draft_wait_names_its_real_cause_and_maps_to_a_line(kwargs, word, needle, key):
    d = decide_idea(_idea(**kwargs), POLICY)
    assert d.word is word and needle in d.reasons[0] and d.reasons[0] not in GENERIC
    assert _first_key(d) == key


def test_a_trade_states_its_plan_and_a_score_that_is_not_called_a_probability():
    d = decide_idea(_idea(), POLICY)
    assert d.word is IdeaWord.TRADE and d.qty > 0
    assert any(r.startswith("Plan: buy around") and "+8%" in r and "-4%" in r for r in d.reasons)
    assert "that score ranks stocks, it is not a probability" in d.evidence_text  # no calibrated record: says so


def test_a_held_back_idea_keeps_its_levels_as_the_would_be_plan_but_has_no_size():
    """OBSERVED: a downgraded idea keeps the entry zone, target and stop of the draft and loses only its size (`contracts.downgrade`).
    The words WATCH/WAIT/AVOID say it is not a trade; a screen must not show the levels as an instruction."""
    d = decide_idea(_idea(verdict=c.RiskVerdict(symbol="ABC", allowed=False, rule="DEPLOYABLE", reason="x")), POLICY)
    assert d.word is IdeaWord.WATCH and d.qty == 0 and d.target is not None and d.stop is not None


# ------------------------------------------------------------------------------- holdings: one scenario per rule


def _holding(**kw) -> HoldingFacts:
    base = {
        "holding": c.Holding(symbol="HLD", qty=10, avg_price=100.0, stop=96.0, target=108.0),
        "snapshot": c.Snapshot(symbol="HLD", as_of="2026-09-25", close=100.0, atr_14=2.0),
        "stock": c.StockState(symbol="HLD", trend="up", rel_strength_vs_nifty=0.0),
        "market_mode": MarketMode.NORMAL,
    }
    return HoldingFacts(**{**base, **kw})


def _snap(close: float) -> c.Snapshot:
    return c.Snapshot(symbol="HLD", as_of="2026-09-25", close=close, atr_14=2.0)


HOLDING_SCENARIOS = {
    "stop_hit": (lambda: _holding(snapshot=_snap(95.0)), HoldingWord.EXIT, "Stop hit"),
    "first_target": (lambda: _holding(snapshot=_snap(106.0)), HoldingWord.REDUCE, "first target (+5%)"),
    "off_track": (
        lambda: _holding(track=c.TrackPoint(symbol="HLD", day_n=6, ret=-0.02, status="drift", reason="Trailing similar trades.")),
        HoldingWord.MONITOR, "What has changed",
    ),
    "careful_market_falling": (
        lambda: _holding(market_mode=MarketMode.DEFENSIVE, stock=c.StockState(symbol="HLD", trend="down", rel_strength_vs_nifty=0.0)),
        HoldingWord.MONITOR, "market is careful and this stock is falling",
    ),
    "lagging_nifty": (
        lambda: _holding(stock=c.StockState(symbol="HLD", trend="up", rel_strength_vs_nifty=-0.12)),
        HoldingWord.MONITOR, "Trailing NIFTY by 12%",
    ),
}


def test_every_holding_rule_has_a_scenario():
    assert set(HOLDING_SCENARIOS) == {rule.id for rule in HOLDING_RULES}


@pytest.mark.parametrize("rule_id", sorted(HOLDING_SCENARIOS))
def test_each_holding_rule_gives_a_word_and_a_first_reason_that_names_the_cause(rule_id):
    make, word, needle = HOLDING_SCENARIOS[rule_id]
    d = decide_holding(make(), POLICY)
    assert d.word is word and needle in d.reasons[0], d.reasons
    assert d.reasons[0] not in GENERIC and d.downgrade_reason == d.reasons[0] and d.downgraded_from is HoldingWord.HOLD


def test_a_holding_on_track_says_so_with_its_price_and_gain():
    d = decide_holding(_holding(snapshot=_snap(102.0)), POLICY)
    assert d.word is HoldingWord.HOLD and "On track" in d.reasons[0] and "+2.0%" in d.reasons[0]
    no_price = decide_holding(_holding(snapshot=None), POLICY)
    assert no_price.word is HoldingWord.MONITOR and "No price today" in no_price.reasons[0]


@pytest.mark.parametrize(
    "close,expected",
    [(104.99, HoldingWord.HOLD), (105.0, HoldingWord.REDUCE), (96.01, HoldingWord.HOLD), (96.0, HoldingWord.EXIT)],
)
def test_the_first_target_and_the_stop_fire_exactly_at_their_levels(close, expected):
    assert decide_holding(_holding(snapshot=_snap(close)), POLICY).word is expected
    assert POLICY.first_target_pct == 0.05


@pytest.mark.parametrize("rel,expected", [(-0.099, HoldingWord.HOLD), (-0.10, HoldingWord.MONITOR)])
def test_the_lagging_threshold_in_the_reason_is_the_threshold_the_rule_uses(rel, expected):
    d = decide_holding(_holding(stock=c.StockState(symbol="HLD", trend="up", rel_strength_vs_nifty=rel)), POLICY)
    assert d.word is expected and POLICY.lagging_vs_nifty == -0.10


# ------------------------------------------------------------------------------- v1 refusals through the REAL risk gate


def _watch_from_refusal(reason: str):
    """What the engine does with a refused idea: a WATCH whose first reason is the risk gate's own words."""
    d = decide_idea(_idea(verdict=c.RiskVerdict(symbol="ABC", allowed=False, rule="X", reason=reason)), POLICY)
    assert d.word is IdeaWord.WATCH and reason in d.reasons[0]
    return d


def _real_refusal(db, monkeypatch, *, value=1_000_000.0, price=500.0, setup=None, cash=None, fraction=1.0, params=None, symbol=None):
    from test_portfolio_risk_layer import _flat_deployable, _instrument, _strategy

    _flat_deployable(monkeypatch, fraction)
    tag = abs(hash((value, price, setup, cash, fraction, symbol))) % 10**8
    strat = _strategy(db, name=f"s242_{tag}", **({"params": params} if params else {}))
    inst = _instrument(db, symbol or f"S242{tag}")
    if setup:
        setup(db, strat, inst)
        db.commit()
    return risk.check_entry(
        db, mode="paper", instrument_id=inst.id, price=price, stop_loss=price * 0.96, portfolio_value=value,
        available_cash=value if cash is None else cash, strategy=strat,
    )


def _bank_held(share: float, symbol: str = "ICICIBANK", price: float = 1000.0):
    def setup(db, strat, inst):
        from test_portfolio_risk_layer import _instrument, _open_position

        _open_position(db, strat, _instrument(db, symbol), quantity=max(1, int(share / price)), entry_price=price)

    return setup


def _invested(amount: float):
    def setup(db, strat, inst):
        from test_portfolio_risk_layer import _instrument, _open_position

        _open_position(db, strat, _instrument(db, f"S242INV{inst.id}"), quantity=int(amount / 1000), entry_price=1000.0)

    return setup


def _feed(model, **fields):
    def setup(db, strat, inst):
        db.add(model(symbol=inst.tradingsymbol, **fields))

    return setup


def _on_watch_list(db, strat, inst):
    from datetime import date

    from swing_trade_ml.db.models.feeds import TradingRestriction

    db.add(TradingRestriction(symbol=inst.tradingsymbol, kind="ASM", stage="Stage 1", as_of=date.today()))


def _delivery_only(db, strat, inst):
    from datetime import date

    from swing_trade_ml.db.models.feeds import DailyDelivery

    db.add(DailyDelivery(symbol=inst.tradingsymbol, series="BE", trade_date=date.today()))


def _event(kind: str, detail: str):
    def setup(db, strat, inst):
        from datetime import date, timedelta

        from swing_trade_ml.db.models.feeds import UpcomingEvent

        db.add(UpcomingEvent(symbol=inst.tradingsymbol, kind=kind, event_date=date.today() + timedelta(days=1), detail=detail))

    return setup


def _fill_slots(db, strat, inst):
    from test_portfolio_risk_layer import _instrument, _open_position

    for i in range(risk.limits_for(1_000_000.0).max_positions):
        _open_position(db, strat, _instrument(db, f"S242SL{i}{inst.id}"), quantity=1, entry_price=10.0)


def _open_same(db, strat, inst):
    from test_portfolio_risk_layer import _open_position

    _open_position(db, strat, inst, quantity=1, entry_price=10.0)


def _stopped_out(db, strat, inst):
    from datetime import UTC, datetime

    from swing_trade_ml.db.models.trading import Position

    db.add(Position(strategy_id=strat.id, instrument_id=inst.id, mode="paper", status="CLOSED", quantity=1, entry_price=10.0, entry_at=datetime.now(UTC), exit_reason="STOP_LOSS_HIT", exit_at=datetime.now(UTC)))


def _halt(db, strat, inst):
    from swing_trade_ml.db.models.safety import SystemState

    existing = db.get(SystemState, 1)
    if existing is not None:
        existing.new_entries_enabled, existing.halt_reason = False, "test halt"
    else:
        db.add(SystemState(id=1, new_entries_enabled=False, exits_enabled=True, halt_reason="test halt"))
    db.flush()


def _drawdown(db, strat, inst):
    from datetime import UTC, datetime, timedelta

    from swing_trade_ml.db.models.trading import PortfolioSnapshot

    db.add(PortfolioSnapshot(mode="paper", ts=datetime.now(UTC) - timedelta(days=1), cash=1_000_000.0, holdings_value=0.0, total_value=2_000_000.0, peak_value=2_000_000.0, drawdown_pct=0.0))


REAL_REFUSALS = [
    ("POSITION_LIMIT", {"setup": _fill_slots}, "slots_full"),
    ("ALREADY_OPEN", {"setup": _open_same}, "already_open"),
    ("COOLDOWN", {"setup": _stopped_out}, "cooldown"),
    ("HALTED", {"setup": _halt}, "owner_paused"),
    ("DRAWDOWN", {"setup": _drawdown}, "drawdown"),
    ("SHARE_PRICE", {"value": 10_000.0, "price": 3_000.0}, "share_price"),
    ("MIN_POSITION", {"value": 10_000.0, "price": 500.0}, "min_position"),
    ("SECTOR_CAP", {"price": 1000.0, "symbol": "HDFCBANK", "setup": _bank_held(240_000)}, "sector_cap"),
    ("SECTOR_CAP", {"value": 10_000.0, "price": 100.0, "symbol": "HDFCBANK", "setup": _bank_held(1_000, price=100.0)}, "one_per_sector_held"),
    ("CASH_FLOOR", {"cash": 110_000.0}, "cash_reserve"),
    ("DEPLOYABLE", {"fraction": 0.1, "setup": _invested(80_000)}, "deployable_room"),
    ("CAP_TIER", {"value": 100_000.0, "params": {"model_name": "swing_classifier_smallcap"}}, "cap_tier_off"),
    ("AVOID", {"setup": _on_watch_list}, "exchange_watch_list"),
    ("AVOID", {"setup": _delivery_only}, "delivery_only"),
    ("AVOID", {"setup": _event("results", "")}, "results"),
    ("AVOID", {"setup": _event("corporate_action", "Bonus 1:1")}, "corporate_action"),
]


@pytest.mark.parametrize(("rule", "kwargs", "key"), REAL_REFUSALS, ids=[f"{r[0]}-{r[2]}" for r in REAL_REFUSALS])
def test_a_real_risk_gate_refusal_is_a_watch_that_names_its_cause_and_maps_to_a_specific_line(db_session, monkeypatch, rule, kwargs, key):
    decision = _real_refusal(db_session, monkeypatch, **kwargs)
    assert decision.allowed is False and decision.rule == rule, decision
    watch = _watch_from_refusal(decision.reason)
    assert _first_key(watch) == key, what_would_change(watch)
    assert _first_key(watch) not in {"account_limits", "unknown"}


def test_every_risk_rule_the_gate_can_return_has_a_mapped_line_or_is_listed_here_as_untested_by_construction():
    """The gate's rule names are read from its source, so a new rule cannot appear without this list changing."""
    tree = ast.parse((SRC / "services" / "risk.py").read_text(encoding="utf-8"))
    literal = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_reject" and node.args and isinstance(node.args[0], ast.Constant)
    }
    rules = literal | set(risk._CEILING_RULES.values()) | {"MIN_POSITION"}  # the ceiling rules are named through a table
    produced_above = {r[0] for r in REAL_REFUSALS}
    # Not reachable through the real gate in a test: LIQUIDITY needs stored traded value, and CASH ("not enough cash")
    # is believed to be shadowed by the cash-sized ceiling (not tested). Both are mapped by copied text in test_what_would_change.py; the note says so.
    covered_elsewhere = {"LIQUIDITY", "CASH"}
    assert rules == produced_above | covered_elsewhere, sorted(rules ^ (produced_above | covered_elsewhere))


def test_the_drawdown_and_minimum_position_lines_quote_the_numbers_the_real_gate_uses(db_session, monkeypatch):
    drawdown = _real_refusal(db_session, monkeypatch, setup=_drawdown)
    limit = f"{settings.MAX_PORTFOLIO_DRAWDOWN_PCT:.0%}"
    assert f"past the {limit} safety limit" in drawdown.reason  # the gate's own words use the setting
    line = what_would_change(_watch_from_refusal(drawdown.reason))[0]
    assert line["key"] == "drawdown" and f"less than {limit} below its peak" in line["text"]


def test_the_minimum_position_line_quotes_the_minimum_the_real_gate_uses(db_session, monkeypatch):
    small = _real_refusal(db_session, monkeypatch, value=10_000.0, price=500.0)
    minimum = format_inr(risk.limits_for(10_000.0).min_position_inr)
    assert f"below the {minimum} minimum" in small.reason
    line = what_would_change(_watch_from_refusal(small.reason))[0]
    assert line["key"] == "min_position" and f"Needs about {minimum} of room" in line["text"]


def test_the_defensive_half_size_line_needs_the_minimum_divided_by_the_size_factor():
    reason = "After stronger ideas in this run, the sector limit leaves room for only ₹12,000 — below the ₹40,000 minimum position"
    watch = _watch_from_refusal(reason)
    line = what_would_change(watch, banner_mode="DEFENSIVE")[0]
    assert line["key"] == "room_after_stronger"
    assert f"Needs about {format_inr(40_000 / DEFENSIVE_SIZE_FACTOR)}" in line["text"] and "twice" in line["text"]
    normal = what_would_change(watch, banner_mode="NORMAL")[0]["text"]
    assert "Needs about ₹40,000" in normal  # outside a defensive market the minimum itself


# ------------------------------------------------------------------------------- banners explain themselves


def _ctx(**kw) -> BrainContext:
    from datetime import UTC, datetime

    ctx = BrainContext(
        request=c.RunRequest(run_id="s242", kind="nightly", as_of=datetime(2026, 9, 25, 12, 0, tzinfo=UTC), universe=("AAA",)),
        reader=None,
        risk_gate_ran=kw.pop("gate", True),
    )
    for k, v in kw.items():
        setattr(ctx, k, v)
    ctx.decisions["AAA"] = c.Decision(
        symbol="AAA", kind="idea", word=IdeaWord.TRADE, reasons=("The model scores this stock 70%.",),
        entry_low=100.0, entry_high=101.0, target=108.0, stop=96.0, qty=10,
    )
    ctx.verdicts["AAA"] = c.RiskVerdict(symbol="AAA", allowed=True, max_qty=10)
    ctx.quality["AAA"] = c.DataQuality(symbol="AAA", score=1.0, fresh=True)
    return ctx


def test_no_risk_gate_gives_a_no_new_trades_banner_that_says_why_and_a_watch_that_maps_to_it():
    ctx = _ctx(gate=False)
    constitution.enforce(ctx)
    assert ctx.banner.mode is MarketMode.NO_NEW_TRADES and ctx.banner.headline == constitution.NO_RISK_GATE
    assert constitution.NO_RISK_GATE in ctx.banner.reasons
    d = ctx.decisions["AAA"]
    assert d.word is IdeaWord.WATCH and d.reasons[0] == constitution.NO_RISK_GATE
    assert _first_key(d, banner_mode=ctx.banner.mode.value, banner_headline=ctx.banner.headline) == "no_risk_gate"


def test_an_owner_pause_and_stale_market_data_each_name_themselves_in_the_banner():
    paused = _ctx(system=c.SystemState(entries_halted=True, halt_reason="testing the pause"))
    constitution.enforce(paused)
    assert paused.banner.mode is MarketMode.NO_NEW_TRADES and "Owner paused new buys: testing the pause" in paused.banner.headline
    assert _first_key(paused.decisions["AAA"]) == "owner_paused"
    stale = _ctx()
    stale.quality["*"] = c.DataQuality(symbol="*", score=0.2, fresh=False, issues=("benchmark is two days old",))
    constitution.enforce(stale)
    assert stale.banner.mode is MarketMode.NO_NEW_TRADES and "Market data is not reliable today" in stale.banner.headline
    assert "benchmark is two days old" in stale.banner.headline
    assert _first_key(stale.decisions["AAA"]) == "market_data_not_reliable"


def test_a_banner_a_module_wrote_keeps_its_own_headline_and_a_missing_one_says_the_state_is_unknown():
    wrote = _ctx(banner=c.Banner(mode=MarketMode.NO_NEW_TRADES, headline="NIFTY fell 5% today — a crash day, so no new buys."))
    wrote.quality["*"] = c.DataQuality(symbol="*", score=1.0, fresh=True)
    constitution.enforce(wrote)
    d = wrote.decisions["AAA"]
    assert wrote.banner.headline.startswith("NIFTY fell 5%") and d.word is IdeaWord.WATCH
    assert wrote.banner.headline in d.reasons[0]
    assert _first_key(d, banner_mode="NO_NEW_TRADES", banner_headline=wrote.banner.headline) == "market_no_new_trades"
    unknown = _ctx()
    unknown.quality["*"] = c.DataQuality(symbol="*", score=1.0, fresh=True)
    constitution.enforce(unknown)
    assert unknown.banner.mode is MarketMode.DEFENSIVE and unknown.banner.headline == "Market state is unknown."


def test_a_defensive_suggestion_from_a_market_situation_becomes_the_banner_headline():
    ctx = _ctx(
        banner=c.Banner(mode=MarketMode.NORMAL, headline="Steady."),
        market=c.MarketState(mode=MarketMode.NORMAL),
        situations=[c.Situation(scope="market", subject="NIFTY", label="crash", confidence=0.9, suggest_defensive=True, evidence=("NIFTY dropped sharply on heavy volume.",))],
    )
    ctx.quality["*"] = c.DataQuality(symbol="*", score=1.0, fresh=True)
    constitution.enforce(ctx)
    assert ctx.banner.mode is MarketMode.DEFENSIVE and ctx.banner.headline == "NIFTY dropped sharply on heavy volume."
    assert ctx.banner.reasons == ("NIFTY dropped sharply on heavy volume.",)  # the banner says why it changed


# ------------------------------------------------------------------------------- the 15-day label on 5-day scores (#385)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#385): the plan line always says 15 trading days, whatever horizon the score was trained for",
)
def test_385_the_plan_line_states_the_horizon_the_score_was_trained_for():
    """Intended: a score trained for 5 days is not presented as a 15-day plan. Today every plan says 15."""
    opinion = c.Opinion(source="model", symbol="ABC", stance=0.5, confidence=0.8, probability=0.8, threshold=0.6, horizon_days=5, reasons=("x",))
    d = decide_idea(_idea(opinion=opinion), POLICY)
    assert not any("up to 15 trading days" in r for r in d.reasons), d.reasons


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="GAP (#385): no Brain opinion is given its model's horizon, so the field stays at its default of 15",
)
def test_385_opinions_in_the_brain_are_given_their_models_horizon():
    offenders = []
    for path in (SRC / "brain").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_opinion = isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "Opinion"
            if is_opinion and any(k.arg == "horizon_days" for k in node.keywords):
                offenders.append(path.relative_to(SRC).as_posix())
    assert offenders != []
