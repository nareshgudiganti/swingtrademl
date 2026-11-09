"""Which model NAME serves which cap group, and which code reads which model. Read-only: nothing here changes a
model, a strategy, an order or a setting, and nothing imports it yet except its test.

Why it exists: promoting a model must never silently change what another slot serves (the 12 Aug incident). A
promotion archives only versions of the SAME name, so a slot is safe as long as every reader asks for its slot's
name. This table writes that down, and tests/test_model_slots.py proves the code agrees with it.

The 5D lane models (ids 2, 16, 17) are chosen by id inside the lane, not by name, so they are not in this table.
"""

from __future__ import annotations

from typing import Final

from swing_trade_ml.core.plans import BASE_MODEL

#: cap tier -> the registry model NAME that serves it (the 15-day swing classifier family).
SLOT_MODEL_NAME: Final[dict[str, str]] = {
    "large": BASE_MODEL,
    "midcap": f"{BASE_MODEL}_midcap",
    "smallcap": f"{BASE_MODEL}_smallcap",
}

#: The brain's barrier model name (module M06). Frozen with the trial; listed so a promotion check knows it.
BARRIER_MODEL_NAME: Final[str] = f"{BASE_MODEL}_barrier"

#: Readers that ask for a model WITHOUT a name and so follow "newest ACTIVE model of any name". They show or
#: fall back; none of them places an order. A promotion in any slot can change what they return (gap G5).
UNNAMED_LOOKUPS: Final[tuple[str, ...]] = (
    "api/v1/endpoints/portfolio.py",  # horizon shown next to an open position
    "api/v1/endpoints/system.py",  # status page
    "ml/predict.py",  # evaluation helper when model_id is not given
    "cli.py",  # command line report
)


def slot_for_model_name(name: str) -> str | None:
    """The cap tier a model name serves, or None when the name belongs to no slot."""
    for tier, slot_name in SLOT_MODEL_NAME.items():
        if name == slot_name:
            return tier
    return None
