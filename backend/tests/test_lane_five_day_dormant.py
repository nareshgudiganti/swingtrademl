# ruff: noqa: E501 (long lines in test code)
"""The 5-session lane slots exist in the table but change nothing until the owner chooses a model (#387)."""

from __future__ import annotations

import json

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services import lane_slots as ls
from swing_trade_ml.services import model_registry as mr
from swing_trade_ml.shadow_lanes import lane_job

FIVE = ("5d-large-v1", "5d-midcap-v1")


def test_the_five_day_keys_do_not_reuse_the_owner_reports_row_label():
    from swing_trade_ml.shadow_lanes.horizon_report import ROWS

    labels = {row[0] for row in ROWS}
    assert not labels & set(FIVE)
    assert {"5d-large", "5d-mid", "5d-small"} <= labels  # the h05 rows keep their names


def test_a_numbered_variant_key_is_allowed_and_a_lookalike_is_not():
    base = {"horizon": 5, "tier": "smallcap", "universe_group": "small5", "target": 0.02, "stop": 0.04, "half_out": None, "protocol": "x", "candidates": ("F",)}
    ls.register(ls.LaneSlot(key="5d-smallcap-v2", prefixes=("zz5_",), **base))
    try:
        assert ls.research_slot_of("5d-smallcap-v2") == "5d-smallcap"
    finally:
        ls.unregister("5d-smallcap-v2")
    for bad in ("5d-smallcap-x", "5d-smallcap-v", "5d-smallcap-v1x", "5d-small-v1"):
        with pytest.raises(ls.SlotConfigError):
            ls.register(ls.LaneSlot(key=bad, prefixes=("zy5_",), **base))


def test_a_five_day_model_belongs_to_the_registry_research_slot_not_the_lane_key():
    assert mr.slot_for("fd5l_20261205", 5) == "5d-large"
    assert mr.slot_for("fd5m_20261205", 5) == "5d-midcap"
    assert [ls.research_slot_of(k) for k in FIVE] == ["5d-large", "5d-midcap"]
    assert ls.research_slot_of("15d-large") == "15d-large"
    assert ls.research_slot_of("no-such-slot") == "no-such-slot"


def test_the_five_day_slots_are_dormant_and_the_old_ones_are_not():
    assert all(ls.is_dormant(k) for k in FIVE)
    assert not any(ls.is_dormant(k) for k in ("10d-large", "15d-large", "15d-midcap"))


def test_a_dormant_slot_is_ignored_until_the_owner_chooses_a_model(db_session, monkeypatch):
    assert not any(lane_job.slot_in_use(db_session, k) for k in FIVE)
    assert all(lane_job.slot_in_use(db_session, k) for k in ("10d-large", "15d-large", "15d-midcap"))
    monkeypatch.setattr(settings, "LANE_SHADOW_MODELS", json.dumps({"5d-large-v1": 123}))
    assert lane_job.slot_in_use(db_session, "5d-large-v1")
    assert not lane_job.slot_in_use(db_session, "5d-midcap-v1")


def test_the_daily_job_runs_only_the_old_slots_when_nothing_is_chosen(db_session, monkeypatch):
    monkeypatch.setattr(lane_job, "_try_lock", lambda db: True)
    monkeypatch.setattr(
        lane_job.lane_universe, "load_universe", lambda: (_ for _ in ()).throw(lane_job.lane_universe.UniverseError("none"))
    )
    out = lane_job.run_daily(db_session)
    assert set(out["slots"]) == {"10d-large", "15d-large", "15d-midcap"}
