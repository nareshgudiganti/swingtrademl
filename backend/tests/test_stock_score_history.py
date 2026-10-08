"""Per-stock strength score trail (stock page): gaps, same-day replace, API shape."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.trading import StockScore
from swing_trade_ml.services import score_history

HEADERS = {"X-API-Key": "test-api-key"}
EXIT = 0.35
_TOKENS = iter(range(771_001, 771_999))


def _stock(db_session, symbol):
    inst = Instrument(
        instrument_token=next(_TOKENS), tradingsymbol=symbol, exchange="NSE", is_watchlisted=True
    )
    db_session.add(inst)
    db_session.commit()
    return inst


def test_gap_days_stay_gaps_and_trail_is_oldest_first(db_session):
    inst = _stock(db_session, "TRAILGAP")
    for d, s in ((1, 0.91), (2, 0.80), (6, 0.50)):  # days 3-5 never scanned
        score_history.record_stock_scores(db_session, [(inst.id, s, "m:1")], EXIT, today=date(2026, 10, d))
    db_session.commit()
    trail = score_history.stock_trail(db_session, inst.id)
    assert [t["date"] for t in trail] == ["2026-10-01", "2026-10-02", "2026-10-06"]
    assert [t["band"] for t in trail] == ["strong", "strong", "easing"]


def test_second_scan_same_day_replaces_the_row(db_session):
    inst = _stock(db_session, "TRAILDAY")
    day = date(2026, 10, 3)
    score_history.record_stock_scores(db_session, [(inst.id, 0.70, "m:1")], EXIT, today=day)
    db_session.commit()
    score_history.record_stock_scores(db_session, [(inst.id, 0.40, "m:2")], EXIT, today=day)
    db_session.commit()
    count = db_session.execute(
        select(func.count()).select_from(StockScore).where(StockScore.instrument_id == inst.id)
    ).scalar_one()
    assert count == 1
    only = score_history.stock_trail(db_session, inst.id)[0]
    assert only["score"] == 0.40 and only["band"] == "weak" and only["model_version"] == "m:2"


def test_recorder_never_raises(db_session):
    # Unknown instrument id violates the foreign key; must be swallowed.
    assert score_history.record_stock_scores(db_session, [(99_999_999, 0.7, None)], EXIT) == 0
    db_session.rollback()


def test_api_returns_trail_and_current_band(client, db_session):
    inst = _stock(db_session, "TRAILAPI")
    score_history.record_stock_scores(db_session, [(inst.id, 0.91, "m:1")], EXIT, today=date(2026, 10, 1))
    score_history.record_stock_scores(db_session, [(inst.id, 0.50, "m:1")], EXIT, today=date(2026, 10, 2))
    db_session.commit()
    resp = client.get("/api/v1/ml/score-trail/trailapi", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "TRAILAPI"
    assert [t["score"] for t in body["score_trail"]] == [0.91, 0.50]
    assert set(body["score_trail"][0]) == {"date", "score", "band", "model_version"}
    assert body["score_band"] == "easing"
    assert client.get("/api/v1/ml/score-trail/NOPE_X", headers=HEADERS).status_code == 404


def test_api_empty_trail_for_unscored_stock(client, db_session):
    _stock(db_session, "TRAILNONE")
    body = client.get("/api/v1/ml/score-trail/TRAILNONE", headers=HEADERS).json()
    assert body["score_trail"] == [] and body["score_band"] is None
