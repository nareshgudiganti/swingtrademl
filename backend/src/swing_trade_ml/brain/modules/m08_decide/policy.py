"""Every number the decision engine uses, in one place.

Changing a threshold or switching a rule off is a change here (or a
`replace(DEFAULT_POLICY, ...)` by a caller), never an edit to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DecidePolicy:
    # The locked trade rule.
    target_pct: float = 0.08
    stop_pct: float = 0.04
    first_target_pct: float = 0.05  # half is booked here (v1's ML_FIRST_TARGET_PCT)
    horizon_days: int = 15
    # Entry zone around the close: a quarter of the typical daily range, at most 1%.
    entry_atr_fraction: float = 0.25
    entry_cap_pct: float = 0.01
    # Opinions without a probability below this confidence count as "signals disagree".
    uncertain_below: float = 0.3
    # Similar-case evidence is only used with at least this many cases.
    min_similar_cases: int = 30
    # A holding trailing NIFTY by this much over 60 days is watched closely.
    lagging_vs_nifty: float = -0.10
    # Ids of rules to switch off (see rules.py), e.g. {"defensive_needs_uptrend"}.
    disabled: frozenset[str] = field(default_factory=frozenset)

    @property
    def reward_r(self) -> float:
        """What a target hit is worth in R (1 R = the stop distance)."""
        return self.target_pct / self.stop_pct


DEFAULT_POLICY = DecidePolicy()
