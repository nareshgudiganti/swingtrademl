# ruff: noqa: E501 (long explanatory lines)
"""The slot table (services/lane_slots.py): the three existing slots resolve exactly as the old hard-coded tables did,
and a new slot is one entry. Software tests only: nothing here says any model is good or enables any lane."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from swing_trade_ml.services import lane_slots as ls
from swing_trade_ml.services import model_registry as mr
from swing_trade_ml.shadow_lanes import lane_freeze, lane_job, lane_service, lane_universe

# ---- the values the code hard-coded BEFORE the table existed (copied verbatim from the previous version)
OLD_SLOTS = {"10d-large": (10, "large"), "15d-large": (15, "large"), "15d-midcap": (15, "mid")}
OLD_RULES = {
    10: {"target": 0.06, "stop": 0.035, "half_out": None},
    15: {"target": 0.08, "stop": 0.04, "half_out": 0.05},
}
OLD_PREFIXES = (
    ("td_h10_", 10, "large"),
    ("sl1_S0_", 15, "large"),
    ("sl1_S1_", 15, "large"),
    ("sl1_S2_", 15, "large"),
    ("sl1_S0M_", 15, "midcap"),
    ("sl1_S1M_", 15, "midcap"),
    ("sl1_S2M_", 15, "midcap"),
)
OLD_FOLD_NAME = re.compile(r"^(?:sl1_S[012]M?|td_h10)_\d{8}$")
OLD_CANDIDATES = {
    "10d-large": ("TD10",),
    "15d-large": ("S0", "S1", "S2"),
    "15d-midcap": ("S0M", "S1M", "S2M"),
}


def test_existing_slots_resolve_exactly_as_before():
    assert dict(lane_service.SLOTS) == OLD_SLOTS
    assert dict(lane_service.RULES) == OLD_RULES
    assert ls.prefix_table() == OLD_PREFIXES
    assert dict(lane_freeze.SLOT_CANDIDATES) == OLD_CANDIDATES
    assert lane_service.slot_parts("15d-midcap") == (15, "mid")


def test_the_views_are_the_same_objects_other_modules_import():
    assert lane_service.SLOTS is ls.SLOTS_VIEW
    assert lane_service.RULES is ls.RULES_VIEW
    assert lane_freeze.SLOT_CANDIDATES is ls.CANDIDATES_VIEW


@pytest.mark.parametrize(
    "name,horizon",
    [
        ("td_h10_lane_20261205", 10),
        ("td_h10_lane_20261205", 15),  # right family, wrong horizon
        ("sl1_S1_lane_20261205", 15),
        ("sl1_S2M_lane_20261205", 15),
        ("sl1_S1M_20230701", 15),
        ("sl1_S3_20230701", 15),
        ("swing_classifier", 15),
        ("swing_classifier_midcap", 10),
        ("swing_classifier_smallcap", 5),
        ("swing_classifier_v9", 15),
        ("", 15),
        (None, 15),
        ("sl1_S1_x", 3),
    ],
)
def test_slot_for_matches_the_old_rule(name, horizon):
    def old(n, h):
        if h not in (15, 10, 5) or not n:
            return None
        if n in mr.VERIFIED_NAMES:
            return mr.slot_key(h, mr.VERIFIED_NAMES[n])
        for prefix, lane_h, tier in OLD_PREFIXES:
            if n.startswith(prefix) and h == lane_h:
                return mr.slot_key(h, tier)
        return None

    assert mr.slot_for(name, horizon) == old(name, horizon)


@pytest.mark.parametrize(
    "name",
    [
        "sl1_S0_20230701",
        "sl1_S1M_20260815",
        "sl1_S2M_20240101",
        "td_h10_20240101",
        "sl1_S1_lane_20261205",  # frozen final, not a fold
        "sl1_S3_20230701",
        "sl1_S1_2023070",
        "sl1_S1_202307011",
        "td_h10_lane_20261205",
        "swing_classifier",
        "xsl1_S1_20230701",
    ],
)
def test_fold_name_pattern_matches_the_old_regex(name):
    assert bool(ls.fold_name_pattern().match(name)) == bool(OLD_FOLD_NAME.match(name))


def test_role_gate_still_refuses_a_fold_a_lookalike_and_an_unmarked_model():
    slot = "15d-large"
    fold = SimpleNamespace(id=1, name="sl1_S1_20230701", model_role=None)
    lookalike = SimpleNamespace(id=2, name="sl1_S1_lane_20261205", model_role=None)
    marked_fold = SimpleNamespace(id=3, name="sl1_S1_20230701", model_role="fold")
    final = SimpleNamespace(id=4, name="sl1_S1_lane_20261205", model_role="final")
    for bad in (fold, lookalike, marked_fold):
        with pytest.raises(lane_service.LaneError):
            lane_job.require_eligible_role(bad, slot)
    lane_job.require_eligible_role(final, slot)  # no error


# ---- a new slot is one entry
def _synthetic(**over):
    base = {
        "key": "5d-large",
        "horizon": 5,
        "tier": "large",
        "universe_group": "large",
        "target": 0.02,
        "stop": 0.01,
        "half_out": None,
        "prefixes": ("fd5_",),
        "protocol": "fd-protocol-synthetic",
        "candidates": ("F5",),
    }
    base.update(over)
    return ls.LaneSlot(**base)


@pytest.fixture
def synthetic_slot():
    ls.register(_synthetic())
    try:
        yield "5d-large"
    finally:
        ls.unregister("5d-large")


def test_one_entry_adds_a_slot_everywhere_and_removal_restores_the_old_state(synthetic_slot):
    assert lane_service.SLOTS["5d-large"] == (5, "large")
    assert lane_service.RULES[5] == {"target": 0.02, "stop": 0.01, "half_out": None}
    assert lane_service.slot_parts("5d-large") == (5, "large")
    assert mr.slot_for("fd5_lane_20261205", 5) == "5d-large"
    assert mr.slot_for("fd5_lane_20261205", 10) is None  # the family is valid for one horizon only
    assert lane_freeze.SLOT_CANDIDATES["5d-large"] == ("F5",)
    assert ls.fold_name_pattern().match("fd5_20260101")
    assert not ls.fold_name_pattern().match("fd5_lane_20261205")
    # the role gate applies to the new slot exactly as to the old ones
    with pytest.raises(lane_service.LaneError):
        lane_job.require_eligible_role(
            SimpleNamespace(id=9, name="fd5_20260101", model_role=None), "5d-large"
        )
    lane_job.require_eligible_role(
        SimpleNamespace(id=9, name="fd5_lane_20261205", model_role="final"), "5d-large"
    )
    # a new slot enables nothing by itself
    assert frozenset() == lane_job.PROD_ALLOWED_SLOTS


def test_removing_the_synthetic_slot_restores_everything():
    ls.register(_synthetic())
    ls.unregister("5d-large")
    assert dict(lane_service.SLOTS) == OLD_SLOTS
    assert dict(lane_service.RULES) == OLD_RULES
    assert ls.prefix_table() == OLD_PREFIXES
    assert dict(lane_freeze.SLOT_CANDIDATES) == OLD_CANDIDATES


def test_a_midcap_10d_slot_is_also_just_an_entry():
    ls.register(
        _synthetic(
            key="10d-midcap",
            horizon=10,
            tier="midcap",
            universe_group="mid",
            target=0.06,
            stop=0.035,
            prefixes=("td_h10M_",),
            candidates=("TD10M",),
        )
    )
    try:
        assert lane_service.SLOTS["10d-midcap"] == (10, "mid")
        assert mr.slot_for("td_h10M_lane_20270101", 10) == "10d-midcap"
        assert mr.slot_for("td_h10_lane_20270101", 10) == "10d-large"  # old family unaffected
    finally:
        ls.unregister("10d-midcap")
    assert "10d-midcap" not in lane_service.SLOTS
    assert dict(lane_service.RULES) == OLD_RULES


@pytest.mark.parametrize(
    "bad,why",
    [
        ({"horizon": 7}, "horizon"),
        ({"tier": "tiny"}, "tier"),
        ({"key": "5d-midcap"}, "key"),
        ({"prefixes": ()}, "prefix"),
        ({"prefixes": ("fd5",)}, "prefix"),
        ({"prefixes": ("sl1_S1_x_",)}, "overlaps"),  # starts with an existing prefix
        ({"prefixes": ("sl1_",)}, "overlaps"),  # existing prefix starts with it
        ({"target": 1.5}, "fraction"),
        ({"stop": 0.0}, "fraction"),
        (
            {"key": "15d-large", "horizon": 15, "target": 0.08, "stop": 0.04, "half_out": 0.05},
            "already exists",
        ),
    ],
)
def test_a_malformed_or_clashing_entry_is_refused_and_changes_nothing(bad, why):
    before = (dict(ls.SLOTS_VIEW), dict(ls.RULES_VIEW), ls.prefix_table())
    with pytest.raises(ls.SlotConfigError):
        ls.register(_synthetic(**bad))
    assert (dict(ls.SLOTS_VIEW), dict(ls.RULES_VIEW), ls.prefix_table()) == before


def test_two_slots_of_one_horizon_must_share_the_pinned_rule():
    with pytest.raises(ls.SlotConfigError):
        ls.register(
            _synthetic(key="15d-smallcap", horizon=15, tier="smallcap", prefixes=("sl1x_",), target=0.09)
        )
    assert "15d-smallcap" not in ls.SLOTS_VIEW


def test_group_symbols_follows_the_table():
    universe = {"large": ["A", "B"], "mid": ["C"]}
    assert lane_universe.group_symbols(universe, "large") == ["A", "B"]
    assert lane_universe.group_symbols(universe, "mid") == ["C"]
    with pytest.raises(lane_universe.UniverseError):
        lane_universe.group_symbols(universe, "tiny")
    ls.register(_synthetic(universe_group="small5"))
    try:
        with pytest.raises(lane_universe.UniverseError):  # declared by a slot but absent from the frozen file
            lane_universe.group_symbols(universe, "small5")
        assert lane_universe.group_symbols({**universe, "small5": ["Z"]}, "small5") == ["Z"]
    finally:
        ls.unregister("5d-large")
