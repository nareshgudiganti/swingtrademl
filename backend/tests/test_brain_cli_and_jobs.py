"""`swingtrade brain ...` and the brain's scheduled jobs.

The jobs are only registered when BRAIN_ENABLED is true, so production keeps
running exactly as before until the owner turns the brain on.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from swing_trade_ml.cli import build_parser
from swing_trade_ml.core.config import Settings
from swing_trade_ml.workers.scheduler import add_brain_jobs


def test_brain_run_command_parses():
    args = build_parser().parse_args(["brain", "run", "--kind", "nightly", "--as-of", "2026-09-15"])
    assert args.brain_command == "run" and args.kind == "nightly" and args.as_of == "2026-09-15"


def test_brain_set_command_parses():
    args = build_parser().parse_args(["brain", "set", "M02", "off"])
    assert (args.module_id, args.mode) == ("M02", "off")


def test_brain_why_command_parses():
    args = build_parser().parse_args(["brain", "why", "RELIANCE"])
    assert args.symbol == "RELIANCE"


def test_brain_learn_command_parses():
    args = build_parser().parse_args(["brain", "learn", "--since", "2026-09-01"])
    assert args.brain_command == "learn" and args.since == "2026-09-01"


def test_brain_is_off_by_default():
    assert Settings(API_KEY="x", JWT_SECRET_KEY="x").BRAIN_ENABLED is False


def test_brain_jobs_register_nightly_intraday_and_learn():
    s = BackgroundScheduler()
    add_brain_jobs(s)
    assert {j.id for j in s.get_jobs()} == {"brain_nightly", "brain_intraday", "brain_learn"}
