"""Day-by-day strength score for held positions: the trail and the alerts.

The motivating case: bought at 91, then 89, 80, 70, 50 on consecutive days.
The owner must see that whole slide on the position, and hear about it when
it matters — not on ordinary one-day jitter.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from swing_trade_ml.core.enums import PositionStatus
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import Position, Strategy
from swing_trade_ml.services import execution, score_history
from swing_trade_ml.services.score_history import band_worsened, score_band

HEADERS = {"X-API-Key": "test-api-key"}
EXIT = 0.35
MIN = 0.60
_TOKENS = iter(range(770_001, 770_999))


def test_bands_follow_the_same_thresholds_as_the_position_badge():
    assert score_band(0.91, EXIT, MIN) == "strong"
    assert score_band(0.60, EXIT, MIN) == "strong"
    assert score_band(0.50, EXIT, MIN) == "easing"
    assert score_band(0.475, EXIT, MIN) == "easing"
    assert score_band(0.47, EXIT, MIN) == "weak"


def test_only_a_move_toward_caution_counts_as_worse():
    assert band_worsened("strong", "easing")
    assert band_worsened("easing", "weak")
    assert not band_worsened("weak", "easing")  # recovery is not an alarm
    assert not band_worsened("strong", "strong")
    assert not band_worsened(None, "weak")  # nothing to compare against


def _held(db_session, symbol, entry=0.91):
    strat = Strategy(
        name=f"s_{symbol}",
        strategy_type="ml_swing",
        mode="paper",
        is_active=True,
        params={"model_name": "swing_classifier_test"},
    )
    db_session.add(strat)
    db_session.flush()
    inst = Instrument(
        instrument_token=next(_TOKENS), tradingsymbol=symbol, exchange="NSE", is_watchlisted=True
    )
    db_session.add(inst)
    db_session.flush()
    pos = Position(
        strategy_id=strat.id,
        instrument_id=inst.id,
        mode="paper",
        quantity=100,
        entry_price=200.0,
        current_price=200.0,
        stop_loss=192.0,
        entry_at=datetime.now(UTC),
        status=PositionStatus.OPEN,
        entry_confidence=entry,
        last_confidence=entry,
    )
    db_session.add(pos)
    db_session.commit()
    return pos


def _day(db_session, pos, offset, score):
    day = date(2026, 10, 1) + timedelta(days=offset)
    rec = score_history.record_score(
        db_session, pos.id, score, EXIT, model_version="m1", today=day, entry_score=pos.entry_confidence
    )
    db_session.commit()
    return rec


def test_the_91_to_50_slide_alerts_twice_and_not_on_jitter(db_session):
    pos = _held(db_session, "BANDHANBNK")
    recs = [_day(db_session, pos, i, s) for i, s in enumerate([0.91, 0.89, 0.80, 0.70, 0.50])]
    # 91, 89, 80: normal drift, silent. 70: first time 15+ points under entry. 50: strong -> easing.
    assert [r.worsened for r in recs] == [False, False, False, True, True]
    assert [r.band for r in recs] == ["strong", "strong", "strong", "strong", "easing"]


def test_a_big_fall_from_entry_alerts_only_the_first_time(db_session):
    pos = _held(db_session, "FALLONCE")
    recs = [_day(db_session, pos, i, s) for i, s in enumerate([0.91, 0.74, 0.72, 0.70])]
    assert [r.worsened for r in recs] == [False, True, False, False]


def test_a_second_scan_the_same_day_replaces_the_row_and_knows_it_alerted(db_session):
    pos = _held(db_session, "SAMEDAY")
    _day(db_session, pos, 0, 0.91)
    first = _day(db_session, pos, 1, 0.70)
    score_history.mark_alerted(db_session, pos.id, today=date(2026, 10, 2))
    db_session.commit()
    second = _day(db_session, pos, 1, 0.69)
    assert first.worsened and second.already_alerted
    trail = score_history.trails_for(db_session, [pos.id])[pos.id]
    assert [round(t["score"], 2) for t in trail] == [0.91, 0.69]  # one row per day


def test_missing_days_stay_gaps_in_the_trail(db_session):
    pos = _held(db_session, "GAPPY")
    _day(db_session, pos, 0, 0.91)
    _day(db_session, pos, 3, 0.80)  # nothing scanned on days 1-2
    trail = score_history.trails_for(db_session, [pos.id])[pos.id]
    assert [t["date"] for t in trail] == ["2026-10-01", "2026-10-04"]


def test_daily_refresh_sends_one_message_for_the_slide(db_session, monkeypatch):
    pos = _held(db_session, "REFRESH")
    sent: list[str] = []
    monkeypatch.setattr(execution.notifier, "send_sync", lambda msg, kind: sent.append(msg))
    strat = db_session.get(Strategy, pos.strategy_id)
    inst = db_session.get(Instrument, pos.instrument_id)

    execution._check_confidence_decay(db_session, pos, strat, inst, 0.89, "paper")
    assert sent == []
    execution._check_confidence_decay(db_session, pos, strat, inst, 0.70, "paper")
    assert len(sent) == 1 and "SCORE SLIPPING" in sent[0] and "91%" in sent[0] and "70%" in sent[0]
    execution._check_confidence_decay(db_session, pos, strat, inst, 0.69, "paper")  # same day again
    assert len(sent) == 1


def test_positions_api_returns_the_trail_and_band(client, db_session):
    pos = _held(db_session, "APITRAIL")
    _day(db_session, pos, 0, 0.91)
    _day(db_session, pos, 1, 0.80)
    pos.last_confidence = 0.80
    db_session.commit()

    resp = client.get("/api/v1/portfolio/positions/detailed", headers=HEADERS)
    row = next(r for r in resp.json() if r["symbol"] == "APITRAIL")
    assert [round(t["score"], 2) for t in row["score_trail"]] == [0.91, 0.80]
    assert row["score_band"] == "strong"
