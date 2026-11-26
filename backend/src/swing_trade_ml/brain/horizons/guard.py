"""The one rule that stops a mixed decision (#385): a score may decide a horizon only if its model was trained
for that same horizon. Pure: no database, no clock. A model whose horizon is unknown never decides.
"""

from __future__ import annotations

from dataclasses import dataclass

NO_DECISION_TEXT = "No decision for this horizon"


@dataclass(frozen=True, slots=True)
class HorizonMatch:
    ok: bool
    reason: str  # empty when ok; otherwise the full "No decision for this horizon: ..." sentence


def horizon_refusal(label: str, model_horizon: int | None, requested_horizon: int) -> str | None:
    """Why this model's score cannot decide `requested_horizon`, or None when it can."""
    if model_horizon is None:
        return f"{label} has no recorded forecast horizon"
    if model_horizon != requested_horizon:
        return (
            f"{label} forecasts {model_horizon} sessions; "
            f"this workflow needs a {requested_horizon}-session forecast"
        )
    return None


def check_score_for_horizon(label: str, model_horizon: int | None, requested_horizon: int) -> HorizonMatch:
    """The boundary check for a caller that holds a score and a requested horizon (the Brain run)."""
    why = horizon_refusal(label, model_horizon, requested_horizon)
    return HorizonMatch(True, "") if why is None else HorizonMatch(False, f"{NO_DECISION_TEXT}: {why}")
