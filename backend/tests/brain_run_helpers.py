"""POST /brain/runs only queues a run (202); the worker's queue job runs it
(brain/queue.py). Tests that need a finished run queue it, run the queue once
on the test's own session, and read the run back as the API reports it."""

from __future__ import annotations

from swing_trade_ml.brain import queue
from swing_trade_ml.db.session import get_db
from swing_trade_ml.main import app


def run_via_api(client, payload: dict, headers: dict) -> dict:
    r = client.post("/api/v1/brain/runs", json=payload, headers=headers)
    assert r.status_code == 202, r.text
    db = next(app.dependency_overrides[get_db]())  # the test's own session (conftest `client`)
    queue.process_next(db)
    return client.get(f"/api/v1/brain/runs/{r.json()['run_id']}", headers=headers).json()
