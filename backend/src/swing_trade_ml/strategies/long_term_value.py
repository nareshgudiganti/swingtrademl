"""Long-term stock picks — see
docs/superpowers/specs/2026-09-12-long-term-stock-picks-design.md.

Phase 1: reuses ml_swing's exact pipeline (same build_features, same
train_model) with a longer horizon and a wider percentage-based stop/target
appropriate to a multi-month hold rather than ATR-based day-to-day noise.
Phase 2 (a follow-up task, gated on docs/superpowers/research/2026-09-12-
fundamentals-vendor-decision.md) layers fundamentals features on top.

No return-multiple promise ("10X" or any number) appears anywhere in this
module's signal text — confidence and a real tracked hit-rate only, same
standard as every other signal in the app.
"""

from __future__ import annotations

# 250 trading days (~1 year) — long enough to be a genuinely different
# horizon from the swing model's ~5-20 days, short enough that the model
# still trains on a meaningful number of non-overlapping examples given the
# watchlist's available history.
LONG_TERM_HORIZON_DAYS = 250

# The swing model's DEFAULT_TAKE_PROFIT_PCT is 0.15 (core/config.py) — a
# 1-year hold should target a materially larger move than a 2-week swing,
# not the same one scaled by time. 30% is the starting point; revisit once
# backtested (spec §10 open items).
LONG_TERM_TARGET_RETURN_PCT = 0.30
