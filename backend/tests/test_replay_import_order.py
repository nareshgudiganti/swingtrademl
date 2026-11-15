"""#359: each replay/trial module must import cleanly when it is the FIRST thing a fresh
process loads. The full suite hid the import cycle because earlier tests had already
loaded the chain in a safe order, so each module is checked in its own subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

MODULES = [
    "swing_trade_ml.brain.replay_report",
    "swing_trade_ml.brain.replay_score",
    "swing_trade_ml.brain.horizon_grid",
    "swing_trade_ml.brain.trial_journal",
    "swing_trade_ml.services.trial_seal",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_in_a_fresh_process(module):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    done = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert done.returncode == 0, done.stderr[-1500:]
