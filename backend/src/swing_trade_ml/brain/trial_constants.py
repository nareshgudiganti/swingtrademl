"""The forward trial's fixed numbers, with no imports of their own.

They live here, not only in `brain.trial_journal`, so `services.trial_seal` (on the
risk-check import path) can read them without importing the replay and journal
code. That top-level import closed a cycle (#359): replay_score -> replay_report ->
brain.modules -> services.risk -> testing_mode -> stage -> trial_seal ->
trial_journal -> horizon_grid -> replay_score. `brain.trial_journal` re-exports
every name, so nothing that reads them there changes.
"""

from __future__ import annotations

from datetime import date

TRIAL_START = date(2026, 10, 14)  # owner decision 2026-10-13 (docs/brain/EXPOSURE-LEDGER.md)
MIN_SESSIONS = 15  # fewer sessions than this is "too early"
GATE_IDEAS = 30  # the M18 gate, shown for reference
# Forward gate, protocol section 5a (docs/superpowers/specs/2026-10-13-layer2-validation-protocol-DRAFT.md).
GATE_MIN_IDEAS = GATE_IDEAS
