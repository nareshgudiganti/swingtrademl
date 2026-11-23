# ruff: noqa: E501 (long lines in test code)
"""10D and 15D records never reach a customer reader or a non-owner API call (#387)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from swing_trade_ml.brain.horizons import ModelOutput, run_horizon
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.horizon import HorizonRecordRow
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import horizon_records as hr
from swing_trade_ml.services.identity import writer

API = settings.API_V1_PREFIX
SESSION = date(2026, 1, 2)
SESSIONS = tuple(d for i in range(40) if (d := SESSION + timedelta(days=i)).weekday() < 5)
MARK = {10: "SENTINEL-TEN-DAY-REASON", 15: "SENTINEL-FIFTEEN-DAY-REASON"}


def _person(db, name: str, role: str, plan: str = "free") -> dict[str, str]:
    user = User(username=name, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _stock(db) -> int:
    inst = Instrument(
        instrument_token=387_950, tradingsymbol="HZAPI387", exchange="NSE", instrument_type="EQ", is_active=True
    )
    db.add(inst)
    db.flush()
    return writer.ensure_for_instrument(db, inst)


def _save_all_three(db, security_id: int) -> None:
    for horizon in (5, 10, 15):
        out = ModelOutput(f"m{horizon}", "v1", horizon, "final", "HZAPI387", SESSION, 100.0, 0.95)
        record = run_horizon(horizon, [out], SESSION, SESSIONS, symbol="HZAPI387", research_caller=True)
        if horizon in MARK:
            from dataclasses import replace

            record = replace(record, reason=MARK[horizon])
        hr.save_record(db, record, security_id=security_id, model_id=horizon)


def test_product_records_hold_the_five_day_line_only(db_session):
    sid = _stock(db_session)
    _save_all_three(db_session, sid)
    everything = db_session.scalars(select(HorizonRecordRow).where(HorizonRecordRow.security_id == sid)).all()
    assert sorted(r.horizon_days for r in everything) == [5, 10, 15]  # all three are stored
    product = hr.product_records(db_session, sid)
    assert [r.horizon_days for r in product] == [5]
    assert not any(r.reason in MARK.values() for r in product)
    for view in ("latest", "first", "all"):
        assert [r.horizon_days for r in hr.product_records(db_session, sid, view=view)] == [5]
    assert hr.product_records(db_session, sid, horizon_days=10) == []
    assert hr.product_records(db_session, sid, horizon_days=15) == []


@pytest.mark.parametrize("who", ["tester", "member-free", "member-pro", "anonymous"])
def test_a_non_owner_api_call_never_returns_a_ten_or_fifteen_day_record(client, db_session, who):
    sid = _stock(db_session)
    _save_all_three(db_session, sid)
    headers = {
        "tester": lambda: _person(db_session, "hz-tester", "tester"),
        "member-free": lambda: _person(db_session, "hz-free", "member", "free"),
        "member-pro": lambda: _person(db_session, "hz-pro", "member", "pro"),
        "anonymous": lambda: {},
    }[who]()
    lane_routes = ["/research/lanes", "/research/lane-picks", "/research/lanes/10d-large/picks", "/research/lanes/15d-large/picks"]
    open_routes = ["/signals", "/signals/latest", "/signals/picks", "/signals/buy-list", "/signals/track-record", "/brain/runs/latest"]
    for path in (*lane_routes, *open_routes):
        response = client.get(f"{API}{path}", headers=headers)
        assert not any(m in response.text for m in MARK.values()), (who, path)
        assert "HZAPI387" not in response.text or path in open_routes, (who, path)
    for path in lane_routes:
        assert client.get(f"{API}{path}", headers=headers).status_code in (401, 403), (who, path)
