"""`python -m swing_trade_ml.brain.scoreboard` must start (it failed with a circular ImportError until the
import order was fixed). Runs in a fresh interpreter: the cycle only shows when scoreboard is the first module
imported, so an in-process import cannot catch it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_scoreboard_module_help_exits_zero_in_a_fresh_interpreter():
    env = {k: v for k, v in os.environ.items() if k not in ("API_KEY", "JWT_SECRET_KEY", "TRADING_MODE")}
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    run = subprocess.run(
        [sys.executable, "-m", "swing_trade_ml.brain.scoreboard", "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr[-800:]
    assert "S1/S2 scoreboards" in run.stdout
    assert "circular import" not in run.stderr
