"""Admin model overview (#385): read-only, admin-only, unknown fields shown as such. Scratch test database."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import event
from tests.test_admin_console import enrol, make_user, stepped

from swing_trade_ml.db.models.ml import MLModel

URL = "/api/v1/admin/console/models"


def _model(db, name, horizon, *, status="ACTIVE", **kw):
    m = MLModel(
        name=name, version="v1", algorithm="lightgbm", status=status, prediction_horizon_days=horizon, **kw
    )
    db.add(m)
    db.flush()
    return m


def _headers(client, db):
    _a, hdr, _s, body = enrol(client, db)
    return stepped(hdr, body["step_up_token"])


def test_refuses_non_admin_and_no_sign_in(client, db_session):
    _u, hdr = make_user(db_session, "plain_member")
    assert client.get(URL, headers=hdr).status_code == 403
    assert client.get(URL, headers={"X-API-Key": "test-api-key"}).status_code == 403
    assert client.get(URL).status_code == 401


def test_shape_groups_models_by_horizon_and_unstored_fields_say_so(client, db_session):
    h = _headers(client, db_session)
    _model(db_session, "swing_a", 5)
    _model(db_session, "swing_b", 15, trained_at=datetime(2026, 11, 1, tzinfo=UTC), accuracy=0.61)
    _model(db_session, "old_model", 5, status="ARCHIVED")  # not approved, not final: not listed
    body = client.get(URL, headers=h).json()
    assert set(body["horizons"]) == {"5", "15"}
    five = {m["name"]: m for m in body["horizons"]["5"]}
    assert "swing_a" in five and "old_model" not in five
    a = five["swing_a"]
    assert a["horizon_days"] == 5
    assert a["approval"]["live_approved"] is True
    assert a["approval"]["approved_by"] == "not recorded"
    assert a["evidence"]["accuracy"] == "not recorded"
    assert a["evidence"]["evaluation_report_link"] == "not recorded"
    assert a["last_scored_at"] == "never scored"
    assert a["brain_usage"]["state"] == "unknown"
    b = {m["name"]: m for m in body["horizons"]["15"]}["swing_b"]
    assert b["evidence"]["accuracy"] == 0.61
    assert b["evidence"]["trained_at"].startswith("2026-11-01")
    assert body["not_recorded"]


def test_job_rows_cover_the_scanning_jobs(client, db_session):
    h = _headers(client, db_session)
    jobs = client.get(URL, headers=h).json()["jobs"]
    ids = {j["id"] for j in jobs["rows"]}
    assert {"predict_watchlist", "brain_nightly", "h05_daily", "lane_shadow_daily"} <= ids
    for j in jobs["rows"]:
        assert "scheduled" in j and "next_run" in j and "last_started_at" in j


def test_brain_usage_from_lane_picks_is_shadow_only(client, db_session):
    from swing_trade_ml.db.models.lane_shadow import LanePick

    h = _headers(client, db_session)
    m = _model(db_session, "lane_m", 15, model_role="final")
    db_session.add(
        LanePick(
            model_id=m.id,
            slot_key="15d-large",
            horizon_days=15,
            cap_group="large",
            signal_day=date(2026, 11, 20),
            symbol="TCS",
            rank=1,
            score=0.7,
            model_version="v1",
            entry_assumption={},
            target_pct=0.08,
            stop_pct=0.04,
        )
    )
    db_session.flush()
    row = {x["name"]: x for x in client.get(URL, headers=h).json()["horizons"]["15"]}["lane_m"]
    assert row["brain_usage"]["state"] == "shadow_only"
    assert row["brain_usage"]["last_session"] == "2026-11-20"
    assert row["last_shadow_lane_day"] == "2026-11-20"


def test_the_overview_only_reads(client, db_session):
    from swing_trade_ml.services.admin_model_overview import build_overview

    _model(db_session, "swing_a", 5)
    statements: list[str] = []

    def spy(conn, cursor, statement, *args):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", spy)
    try:
        build_overview(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert statements, "the spy saw nothing"
    assert set(statements) == {"SELECT"}, statements


def test_no_write_verbs_on_the_route(client, db_session):
    h = _headers(client, db_session)
    assert client.post(URL, headers=h, json={}).status_code == 405
    assert client.put(URL, headers=h, json={}).status_code == 405
    assert client.delete(URL, headers=h).status_code == 405
