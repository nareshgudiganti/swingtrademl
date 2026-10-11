from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from swing_trade_ml.brain.replay_report import LIMITATIONS, plain_summary, track_stats
from swing_trade_ml.brain.replay_score import ReplayWindowError, run_replay_score

MODEL = SimpleNamespace(
    id=1, name="swing_classifier_asof_20260710", version="1", metrics={"asof_cutoff": "2026-07-10"}
)


def _stub(db, **kw):
    return []


def test_a_window_inside_the_training_period_is_refused(db_session):
    with pytest.raises(ReplayWindowError, match="2026-07-10"):
        run_replay_score(
            db_session, start=date(2026, 7, 8), end=date(2026, 7, 20), replay=_stub, asof_model=MODEL
        )


def test_the_first_day_after_the_cutoff_is_allowed(db_session):
    report = run_replay_score(
        db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, asof_model=MODEL, draws=5
    )
    assert report["model"]["cutoff"] == "2026-07-10" and report["model"]["in_sample"] is False


def test_in_sample_is_allowed_only_when_asked_and_is_labelled(db_session):
    report = run_replay_score(
        db_session,
        start=date(2026, 7, 8),
        end=date(2026, 7, 9),
        replay=_stub,
        asof_model=MODEL,
        allow_in_sample=True,
        draws=5,
    )
    assert report["model"]["in_sample"] is True
    assert plain_summary(report).splitlines()[0].startswith("IN-SAMPLE")


def test_a_model_without_a_cutoff_is_refused_for_replays(db_session):
    plain = SimpleNamespace(id=2, name="swing_classifier", version="3", metrics={})
    with pytest.raises(ReplayWindowError, match="cutoff"):
        run_replay_score(
            db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, asof_model=plain
        )


def test_the_summary_names_the_model_and_its_training_window():
    report = {
        "window": {"from": "2026-07-13", "to": "2026-08-14", "days_replayed": 25, "failed_days": []},
        "model": {
            "name": "swing_classifier_asof_20260710",
            "version": "1",
            "cutoff": "2026-07-10",
            "in_sample": False,
            "days_scored": 24,
            "days_without_score": 1,
        },
        "track_a": track_stats([]),
        "track_b": track_stats([]),
        "baselines": {},
        "limitations": list(LIMITATIONS),
    }
    text = plain_summary(report)
    assert "swing_classifier_asof_20260710" in text and "2026-07-10" in text and "1 day" in text


def test_no_model_given_keeps_the_report_as_before(db_session):
    report = run_replay_score(
        db_session, start=date(2026, 7, 11), end=date(2026, 7, 11), replay=_stub, draws=5
    )
    assert report["model"] is None
