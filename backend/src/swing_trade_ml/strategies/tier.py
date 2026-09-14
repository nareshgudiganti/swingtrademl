"""Cap-tier convention shared by every backend consumer that groups
strategies or signals by cap size — mirrors frontend/src/lib/tiers.ts's
TIERS list. One definition so "swing_classifier_midcap is midcap" means the
same thing everywhere instead of two call sites agreeing by convention."""

from __future__ import annotations


def cap_tier(model_name: str | None) -> str:
    """Map an ml_swing strategy's params.model_name to a cap tier. Strategies
    with no model (e.g. sma_crossover) or the default large-cap model both
    fall back to "large" — the safest assumption when tier genuinely isn't
    known."""
    name = model_name or ""
    if name.endswith("_smallcap"):
        return "smallcap"
    if name.endswith("_midcap"):
        return "midcap"
    return "large"
