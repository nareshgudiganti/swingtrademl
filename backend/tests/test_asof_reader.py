from __future__ import annotations

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from swing_trade_ml.brain.reader import DatedReader
from swing_trade_ml.core.config import settings
from swing_trade_ml.ml import asof

IST = ZoneInfo("Asia/Kolkata")


def _as_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59), tzinfo=IST).astimezone(UTC)


class _Instr:
    id = 1
    tradingsymbol = "AAA"


def _reader(db, day, model, live=False):
    r = DatedReader(db, _as_of(day), live=live, asof_model=model)
    r._instrument = lambda symbol: _Instr()  # the lookup is not under test
    return r


def _model(cutoff="2026-07-10"):
    return SimpleNamespace(
        id=1, name="swing_classifier_asof_20260710", version="1", metrics={"asof_cutoff": cutoff}
    )


def test_after_the_cutoff_a_replay_gets_the_score_and_the_plain_threshold(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda db, inst, model, after: {date(2026, 7, 14): 0.71})
    got = _reader(db_session, date(2026, 7, 14), _model()).model_probability("AAA")
    assert got == (0.71, settings.ML_MIN_CONFIDENCE, "swing_classifier_asof_20260710 1")


def test_on_or_before_the_cutoff_there_is_no_score(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {date(2026, 7, 10): 0.9})
    for day in (date(2026, 7, 10), date(2026, 7, 1)):
        assert _reader(db_session, day, _model()).model_probability("AAA") is None


def test_a_model_without_a_recorded_cutoff_is_never_used_in_a_replay(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {date(2026, 7, 14): 0.9})
    plain = SimpleNamespace(id=2, name="swing_classifier", version="3", metrics={})
    assert _reader(db_session, date(2026, 7, 14), plain).model_probability("AAA") is None


def test_no_model_given_means_no_score_as_before(db_session):
    assert _reader(db_session, date(2026, 7, 14), None).model_probability("AAA") is None


def test_a_day_with_no_score_is_none_not_a_guess(db_session, monkeypatch):
    monkeypatch.setattr(asof, "score_series", lambda *a, **k: {})
    assert _reader(db_session, date(2026, 7, 14), _model()).model_probability("AAA") is None
