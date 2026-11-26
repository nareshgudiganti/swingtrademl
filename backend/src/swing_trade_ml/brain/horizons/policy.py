"""The approved decision policy for each horizon, in one table.

Each horizon keeps its own pinned trade rule. The numbers are copies of the rules that are already
pinned elsewhere (copied, not imported: the h05 lane allows no outside importers), and a test checks
they still match:

- 5D: the h05 lane's fixed-rule shadow trade (brain/lanes/h05_protocol.py): +2% / -4% within 5 sessions.
- 10D: the 10d lane slot (services/lane_slots.py): +6% / -3.5% within 10 sessions.
- 15D: the 15d lane slot and the brain's locked rule: +8% / -4%, half out at +5%, within 15 sessions.

The score thresholds turn a model score (0..1) into the Brain's idea words: TRADE >= 0.80, WATCH >= 0.60,
else WAIT, the same for every horizon (owner decision 2026-11-20, #387). Changing one is an edit here,
never in the workflow.
"""

from __future__ import annotations

from dataclasses import dataclass

HORIZONS = (5, 10, 15)


@dataclass(frozen=True, slots=True)
class HorizonPolicy:
    horizon: int  # exchange sessions
    code: str  # names the policy on every stored record
    target_pct: float
    stop_pct: float
    half_out_pct: float | None
    max_sessions: int
    trade_min_score: float = 0.80  # the owner reads ideas scored above 80 only
    watch_min_score: float = 0.60
    approved: bool = True  # False = the workflow records "No decision for this horizon"
    # Registry roles whose models may decide. Only a model frozen after a passed history test (`final`) may,
    # for every horizon. Letting 5D also take a production-marked model is owner decision D1, still PENDING
    # (the plan recommends it); until the owner approves it, no horizon accepts `prod`.
    eligible_roles: frozenset[str] = frozenset({"final"})


DEFAULT_POLICIES: dict[int, HorizonPolicy] = {
    5: HorizonPolicy(
        5,
        "h5-policy-v1",
        target_pct=0.02,
        stop_pct=0.04,
        half_out_pct=None,
        max_sessions=5,
    ),
    10: HorizonPolicy(
        10, "h10-policy-v1", target_pct=0.06, stop_pct=0.035, half_out_pct=None, max_sessions=10
    ),
    15: HorizonPolicy(
        15, "h15-policy-v1", target_pct=0.08, stop_pct=0.04, half_out_pct=0.05, max_sessions=15
    ),
}
