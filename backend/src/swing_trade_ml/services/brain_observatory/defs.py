"""Baseline and calculation definitions, `evidence-defs-v1` (evidence plan section 3a, locked 2026-10-15).

Every report this package produces carries `EVIDENCE_DEFS_VERSION`. Changing any value here is a new
`evidence-defs` version with a dated entry in the plan's change log; a test pins the values to the plan.
Candidate-specific settings (score line, training stocks, breadth line) do not belong here: they are
locked later in `wf-protocol-v2`.
"""

from __future__ import annotations

EVIDENCE_DEFS_VERSION = "evidence-defs-v1"
PLAN_FILE = "docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md"

# Exit rule shared by every set and baseline (the settled rule; values come from replay_scoring).
TOP_N = 5  # random 5 and momentum 5 pick this many stocks a day
MOMENTUM_BARS = 20  # "5 strongest 20-day risers"

# Random baselines
TRADE_RANDOM_DRAWS = 1_000  # trade level: draws of 5 random stocks on each day the candidate trades
PORTFOLIO_RANDOM_RUNS = 200  # portfolio level: random-5 accounts, reported as median and 5th-95th
RANDOM_SEED = 20_261_015  # recorded so every run gives the same draws

# Confidence (as wf-protocol-v1)
BLOCK_DAYS = 15
BOOTSTRAP_DRAWS = 2_000
BOOTSTRAP_SEED = 7
MIN_CONFIDENCE_DAYS = 30  # fewer trading days with ideas -> "insufficient"

# Market types, labelled after the fact for reporting only
RISING_OVER = 0.03
FALLING_UNDER = -0.03
FOLD_DAYS = 28

# Portfolio replay
MAX_DRAWDOWN_HALT = 0.15

OBSERVED_NOT_PROOF = "Observed, not proof"
