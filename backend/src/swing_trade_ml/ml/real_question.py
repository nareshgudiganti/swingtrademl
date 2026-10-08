"""Switch for the "real question" calibrated models (OFF by default).

The real question is the one the app actually trades: does the stock touch
+8% before -4% within 15 trading days. Those models are trained with
`swingtrade train --calibrate`, so their score is a real hit rate (about 15%
on average) instead of the inflated 0.60-0.90 scores the older models give.

Everything here is a no-op while `ML_REAL_QUESTION_SUFFIX` is empty. When it
is set (for example "_barrier_cal"), each ml_swing strategy keeps its own
`model_name` but is scored by the model called `<model_name><suffix>`, and the
buy bar / weakness line move to values that make sense for a calibrated score.
Nothing about orders, sizing, stops or limits lives here.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings


def enabled() -> bool:
    return bool(settings.ML_REAL_QUESTION_SUFFIX.strip())


def resolve_model_name(name: str | None) -> str | None:
    """The model a strategy should be scored by. Unchanged while the switch is off."""
    if not enabled() or not name:
        return name
    suffix = settings.ML_REAL_QUESTION_SUFFIX.strip()
    return name if name.endswith(suffix) else f"{name}{suffix}"


def min_confidence() -> float:
    """The score needed to buy (when the strategy row does not set its own)."""
    if enabled():
        return settings.ML_REAL_QUESTION_MIN_CONFIDENCE
    return settings.ML_MIN_CONFIDENCE


def exit_confidence() -> float:
    """The score at or below which the model signals weakness."""
    if enabled():
        return settings.ML_REAL_QUESTION_EXIT_CONFIDENCE
    return settings.ML_EXIT_CONFIDENCE
