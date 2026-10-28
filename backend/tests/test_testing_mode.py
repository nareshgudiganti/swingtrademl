"""Testing mode: during the practice stage the brain's idea words ignore the account's money limits.

Only the brain's risk gate (M07) asks for the waiver. Version 1's own order path never does, the
switch is off by default, and it can never be on while trading is live or after practice ends.
"""

from __future__ import annotations

import itertools
import math

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.services import deployable, risk, testing_mode
from swing_trade_ml.services.limits import limits_for

_TOKEN = itertools.count(995000)


@pytest.fixture
def gate(db_session, monkeypatch):
    """A stressed market (20% ceiling), no drawdown history, nothing on the avoid list."""
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="stressed", fraction=0.20, context_available=True),
    )
    monkeypatch.setattr(risk, "drawdown_peak", lambda db, mode: None)
    monkeypatch.setattr(risk.avoid, "avoid_reason", lambda db, symbol, day: None)
    return db_session


def _inst(db, symbol):
    inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


# --- when the waiver is allowed ------------------------------------------------------


def _allowed(monkeypatch, *, flag=True, mode="paper", live=False, stage="shadow"):
    monkeypatch.setattr(settings, "TESTING_NO_LIMITS", flag)
    monkeypatch.setattr(settings, "TRADING_MODE", mode)
    monkeypatch.setattr(settings, "ALLOW_LIVE_TRADING", live)
    monkeypatch.setattr(testing_mode, "current_stage", lambda db: stage)
    return testing_mode.limits_waived(object())


def test_off_by_default():
    assert settings.TESTING_NO_LIMITS is False


def test_waived_only_when_switched_on_in_paper_practice(monkeypatch):
    assert _allowed(monkeypatch) is True
    assert _allowed(monkeypatch, flag=False) is False


def test_never_waived_in_live_mode(monkeypatch):
    assert _allowed(monkeypatch, mode="live") is False
    assert _allowed(monkeypatch, mode="live", live=True) is False


@pytest.mark.parametrize("stage", ["approval", "auto", "something-unknown"])
def test_limits_return_when_practice_ends(monkeypatch, stage):
    assert _allowed(monkeypatch, stage=stage) is False


def test_an_unreadable_stage_keeps_the_limits(monkeypatch):
    def boom(db):
        raise RuntimeError("db down")

    monkeypatch.setattr(settings, "TESTING_NO_LIMITS", True)
    monkeypatch.setattr(testing_mode, "current_stage", boom)
    assert testing_mode.limits_waived(object()) is False


# --- what the waiver relaxes ---------------------------------------------------------


def test_relaxed_limits_drop_every_money_percentage_but_keep_the_minimum_position():
    base = limits_for(1_000_000.0)
    free = testing_mode.relaxed(base)
    assert free.max_positions > 1000
    assert free.max_position_pct == 1.0
    assert free.sector_cap_pct is None and free.sector_rule == "pct_cap"
    assert free.max_adv_pct is None and free.max_share_price_inr is None
    assert free.small_cap_budget_pct is None
    assert free.cash_floor_pct == 0.0
    assert math.isinf(free.max_drawdown_pct)
    assert {"large", "midcap", "smallcap"} <= set(free.allowed_cap_tiers)
    assert free.min_position_inr == base.min_position_inr  # not a percentage: it keeps fixed charges sane
    assert free.risk_per_trade_pct == base.risk_per_trade_pct


# --- check_entry ---------------------------------------------------------------------


def test_stressed_market_ceiling_refuses_without_the_waiver_and_not_with_it(gate, monkeypatch):
    inst = _inst(gate, "TMODE1")
    # Squeeze the market-conditions room below the minimum position with a 1% ceiling.
    monkeypatch.setattr(
        deployable,
        "current_deployable",
        lambda db: deployable.DeployableCapital(regime="stressed", fraction=0.01, context_available=True),
    )
    normal = risk.check_entry(gate, "paper", inst.id, 1000.0, 960.0, 1_000_000.0, 1_000_000.0)
    assert (normal.allowed, normal.rule) == (False, "DEPLOYABLE")

    waived = risk.check_entry(
        gate, "paper", inst.id, 1000.0, 960.0, 1_000_000.0, 1_000_000.0, waive_limits=True
    )
    assert waived.allowed and waived.quantity >= 1


def test_share_price_cap_is_waived(gate):
    inst = _inst(gate, "TMODE2")
    normal = risk.check_entry(gate, "paper", inst.id, 3_000.0, None, 10_000.0, 10_000.0)
    assert (normal.allowed, normal.rule) == (False, "SHARE_PRICE")
    waived = risk.check_entry(gate, "paper", inst.id, 3_000.0, 2880.0, 10_000.0, 10_000.0, waive_limits=True)
    assert waived.rule != "SHARE_PRICE"


def test_cash_is_never_waived(gate):
    inst = _inst(gate, "TMODE3")
    verdict = risk.check_entry(
        gate, "paper", inst.id, 1000.0, 960.0, 1_000_000.0, 500.0, waive_limits=True
    )
    assert not verdict.allowed


def test_the_owner_halt_is_never_waived(gate, monkeypatch):
    inst = _inst(gate, "TMODE4")
    monkeypatch.setattr(risk.system_state, "is_entries_halted", lambda db: True)
    verdict = risk.check_entry(
        gate, "paper", inst.id, 1000.0, 960.0, 1_000_000.0, 1_000_000.0, waive_limits=True
    )
    assert (verdict.allowed, verdict.rule) == (False, "HALTED")


def test_check_entry_ignores_the_waiver_in_live_mode(gate, monkeypatch):
    monkeypatch.setattr(settings, "TRADING_MODE", "live")
    inst = _inst(gate, "TMODE5")
    verdict = risk.check_entry(gate, "paper", inst.id, 3_000.0, 2880.0, 10_000.0, 10_000.0, waive_limits=True)
    assert (verdict.allowed, verdict.rule) == (False, "SHARE_PRICE")
