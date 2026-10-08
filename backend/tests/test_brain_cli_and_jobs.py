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


def test_brain_jobs_register_nightly_intraday_learn_approvals_open_and_run_queue():
    s = BackgroundScheduler()
    add_brain_jobs(s)
    assert {j.id for j in s.get_jobs()} == {
        "brain_nightly",
        "brain_intraday",
        "brain_learn",
        "brain_weekly_health",
        "brain_approvals_open",  # M18: buys approved-while-closed ideas at the open
        "brain_run_queue",  # one-app step 1: runs queued "Run the brain now" requests
    }


def test_m09_is_off_resolves_the_stored_mode_like_sync_episodes_does(db_session):
    """`job_brain_learn` must skip while the owner has switched M09 off —
    resolved the same way `service._sync_episodes` resolves it for its own
    after-run jobs (the stored mode, falling back to the manifest default)."""
    from swing_trade_ml.brain import service
    from swing_trade_ml.workers.jobs import _m09_is_off

    assert _m09_is_off(db_session) is False  # M09's manifest default is ON

    service.set_mode(db_session, "M09", "off", by="test-suite")
    assert _m09_is_off(db_session) is True

    service.set_mode(db_session, "M09", "on", by="test-suite")
    assert _m09_is_off(db_session) is False
