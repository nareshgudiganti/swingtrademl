"""bx10: the brain API carries "what would change this?" on each idea — display only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain_run_helpers import run_via_api
from swing_trade_ml.db.models.brain import BrainDecision
from swing_trade_ml.db.models.market import Candle, Instrument

HEADERS = {"X-API-Key": "test-api-key"}
AS_OF = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture()
def stock(db_session):
    inst = Instrument(
        instrument_token=992101, tradingsymbol="BXTENAPI", exchange="NSE", is_watchlisted=True, is_active=True
    )
    db_session.add(inst)
    db_session.flush()
    db_session.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=AS_OF - timedelta(days=1),
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1,
        )
    )
    db_session.commit()
    return inst


def test_latest_run_lists_what_would_change_for_a_wait_idea(client, db_session, stock):
    run_id = run_via_api(
        client, {"kind": "nightly", "symbols": ["BXTENAPI"], "as_of": AS_OF.isoformat()}, HEADERS
    )["run_id"]
    before = [(d.word, list(d.reasons)) for d in db_session.query(BrainDecision).filter_by(run_id=run_id)]

    latest = client.get("/api/v1/brain/runs/latest?kind=nightly&include_replays=true", headers=HEADERS).json()
    decision = latest["decisions"][0]
    assert decision["word"] == "WAIT"
    items = decision["what_would_change"]
    assert items, "a WAIT idea always gets at least one line (or 'Not known')"
    assert all(set(i) == {"key", "text"} and i["text"].strip() for i in items)

    # Reading it changes nothing that was stored.
    db_session.expire_all()
    after = [(d.word, list(d.reasons)) for d in db_session.query(BrainDecision).filter_by(run_id=run_id)]
    assert after == before


def test_why_also_carries_it(client, stock):
    body = client.get("/api/v1/brain/why/BXTENAPI", headers=HEADERS).json()
    assert isinstance(body["decision"]["what_would_change"], list)
