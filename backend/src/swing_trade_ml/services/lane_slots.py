# ruff: noqa: E501 (long explanatory lines)
"""The one table that says which shadow-lane slots exist.

A slot is a (horizon, cap tier) pair with its pinned trade rule, the model-name prefixes that may belong to it, the
stock group it is scored on and the protocol that qualifies its model. Everything else (the registry's name matching,
the lane's slot list, the per-horizon rule, the fold-name check) is derived from this table, so a newly qualified
model for a new horizon or cap group is one entry here, not new infrastructure.

Adding a slot does NOT enable it: a lane still needs LANE_SHADOW_ENABLED, an owner-chosen model in
LANE_SHADOW_MODELS, and a model whose role is "final" (see model_registry.role_of). Nothing here validates a model.

This module imports nothing from the app, so every other module can use it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HORIZONS = (15, 10, 5)
TIERS = ("large", "midcap", "smallcap")


@dataclass(frozen=True)
class LaneSlot:
    key: str  # "15d-midcap" = f"{horizon}d-{tier}"
    horizon: int  # sessions
    tier: str  # registry cap tier: large / midcap / smallcap
    universe_group: str  # key of the group in the frozen lane universe file ("large", "mid", ...)
    target: float
    stop: float
    half_out: float | None
    prefixes: tuple[str, ...]  # model names must START with one; each ends in "_"
    protocol: str  # the history-test protocol a model must pass to be frozen into this slot (informational)
    candidates: tuple[
        str, ...
    ] = ()  # the history-test candidates whose pass may feed this slot (lane_freeze)


def slot_key(horizon: int, tier: str) -> str:
    return f"{horizon}d-{tier}"


# ---------------------------------------------------------------- the table

_RULE_10 = {"target": 0.06, "stop": 0.035, "half_out": None}
_RULE_15 = {"target": 0.08, "stop": 0.04, "half_out": 0.05}

_INITIAL: tuple[LaneSlot, ...] = (
    LaneSlot(
        "10d-large",
        10,
        "large",
        "large",
        **_RULE_10,
        prefixes=("td_h10_",),
        protocol="td-protocol-v1",
        candidates=("TD10",),
    ),
    LaneSlot(
        "15d-large",
        15,
        "large",
        "large",
        **_RULE_15,
        prefixes=("sl1_S0_", "sl1_S1_", "sl1_S2_"),
        protocol="sl-protocol-v1",
        candidates=("S0", "S1", "S2"),
    ),
    LaneSlot(
        "15d-midcap",
        15,
        "midcap",
        "mid",
        **_RULE_15,
        prefixes=("sl1_S0M_", "sl1_S1M_", "sl1_S2M_"),
        protocol="sl-protocol-v1",
        candidates=("S0M", "S1M", "S2M"),
    ),
)

_SLOTS: dict[str, LaneSlot] = {}
#: Live views over the table, mutated in place by register/unregister so importers keep one object.
SLOTS_VIEW: dict[str, tuple[int, str]] = {}  # slot key -> (horizon, universe group)
RULES_VIEW: dict[int, dict] = {}  # horizon -> pinned trade rule
CANDIDATES_VIEW: dict[str, tuple[str, ...]] = {}  # slot key -> history-test candidates that may feed it


class SlotConfigError(ValueError):
    """A slot entry is malformed or clashes with an existing one; nothing was changed."""


def _check(slot: LaneSlot) -> None:
    if slot.horizon not in HORIZONS:
        raise SlotConfigError(f"horizon {slot.horizon} is not one of {HORIZONS}")
    if slot.tier not in TIERS:
        raise SlotConfigError(f"cap tier {slot.tier!r} is not one of {TIERS}")
    if slot.key != slot_key(slot.horizon, slot.tier):
        raise SlotConfigError(f"slot key {slot.key!r} must be {slot_key(slot.horizon, slot.tier)!r}")
    if slot.key in _SLOTS:
        raise SlotConfigError(f"slot {slot.key!r} already exists")
    if not slot.prefixes or any(not p.endswith("_") or len(p) < 3 for p in slot.prefixes):
        raise SlotConfigError("every model-name prefix must be non-empty and end with '_'")
    for other in _SLOTS.values():
        for a in slot.prefixes:
            for b in other.prefixes:
                if a.startswith(b) or b.startswith(a):
                    raise SlotConfigError(f"prefix {a!r} overlaps {b!r} of slot {other.key!r}")
    if not (0 < slot.stop < 1 and 0 < slot.target < 1):
        raise SlotConfigError("target and stop must be fractions between 0 and 1")
    rule = {"target": slot.target, "stop": slot.stop, "half_out": slot.half_out}
    if slot.horizon in RULES_VIEW and RULES_VIEW[slot.horizon] != rule:
        raise SlotConfigError(f"horizon {slot.horizon} already has a different pinned trade rule")


def register(slot: LaneSlot) -> LaneSlot:
    """Add a slot. Validates first; on any error nothing changes."""
    _check(slot)
    _SLOTS[slot.key] = slot
    SLOTS_VIEW[slot.key] = (slot.horizon, slot.universe_group)
    CANDIDATES_VIEW[slot.key] = slot.candidates
    RULES_VIEW.setdefault(slot.horizon, {"target": slot.target, "stop": slot.stop, "half_out": slot.half_out})
    return slot


def unregister(key: str) -> None:
    """Remove a slot (tests and tooling). Drops the horizon rule when no other slot uses that horizon."""
    slot = _SLOTS.pop(key, None)
    if slot is None:
        return
    SLOTS_VIEW.pop(key, None)
    CANDIDATES_VIEW.pop(key, None)
    if not any(s.horizon == slot.horizon for s in _SLOTS.values()):
        RULES_VIEW.pop(slot.horizon, None)


def get(key: str) -> LaneSlot | None:
    return _SLOTS.get(key)


def all_slots() -> tuple[LaneSlot, ...]:
    return tuple(_SLOTS.values())


def prefix_table() -> tuple[tuple[str, int, str], ...]:
    """(name prefix, horizon, cap tier), in table order: what model_registry matches a lane model name against."""
    return tuple((p, s.horizon, s.tier) for s in _SLOTS.values() for p in s.prefixes)


def fold_name_pattern() -> re.Pattern[str]:
    """Evaluation-fold names: a lane prefix followed straight by a date, e.g. sl1_S1_20230701 (never 'lane_')."""
    prefixes = sorted((p for s in _SLOTS.values() for p in s.prefixes), key=len, reverse=True)
    return re.compile(r"^(?:" + "|".join(re.escape(p) for p in prefixes) + r")\d{8}$")


for _slot in _INITIAL:
    register(_slot)
