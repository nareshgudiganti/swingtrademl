"""The read-only ops digest: content, key auth, writes refused, and the seal (Docker Postgres)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import ops_digest, service_keys, trial_seal

URL = "/api/v1/ops/digest"
LEGACY = {"X-API-Key": "test-api-key"}


def _key(db, scope):
    return {"X-API-Key": service_keys.create_key(db, name="t", scope=scope, created_by="o")[1]}


def _person(db, name, role):
    u = User(username=name, hashed_password="x", is_active=True, role=role)
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def _run_with_ideas(db):
    now = datetime.now(UTC)
    run = BrainRun(
        id="ops-test-run",
        kind="nightly",
        as_of=now,
        book="paper",
        live=True,
        started_at=now,
        finished_at=now,
        status="done",
        banner_mode="NORMAL",
        banner_headline="All clear",
    )
    db.add(run)
    db.flush()
    for sym, word, conf in (("AAA", "TRADE", 0.8), ("BBB", "WATCH", 0.5), ("CCC", "AVOID", 0.1)):
        db.add(
            BrainDecision(
                run_id=run.id,
                symbol=sym,
                kind="idea",
                word=word,
                confidence=conf,
                reasons=["because"],
                outcome="WIN",
                outcome_return=0.08,
                max_up=0.1,
                max_down=-0.01,
            )
        )
    db.flush()


# ---- key auth ---------------------------------------------------------------------------


def test_no_credentials_is_401(client):
    assert client.get(URL).status_code == 401


def test_wrong_key_is_refused(client):
    assert client.get(URL, headers={"X-API-Key": "stk_wrong"}).status_code == 401
    assert client.get(URL, headers={"X-API-Key": "nope"}).status_code == 401


def test_unset_key_fails_closed_with_no_keys_in_the_database(client):
    # No ops key exists, so no stk_ value can open it.
    assert client.get(URL, headers={"X-API-Key": "stk_" + "a" * 43}).status_code == 401


@pytest.mark.parametrize("scope", ["read_ops", "read_all"])
def test_ops_capable_keys_read_the_digest(client, db_session, scope):
    r = client.get(URL, headers=_key(db_session, scope))
    assert r.status_code == 200
    body = r.json()
    for k in (
        "needs_attention",
        "brain",
        "v1_scan",
        "trading_paper",
        "scheduler",
        "data_freshness",
        "risk",
        "market",
    ):
        assert k in body


def test_read_status_key_cannot_read_the_digest(client, db_session):
    assert client.get(URL, headers=_key(db_session, "read_status")).status_code == 403


def test_read_ops_key_can_call_only_ops(client, db_session):
    h = _key(db_session, "read_ops")
    for path in ("/status", "/portfolio/positions", "/brain/stage", "/risk/limits", "/admin/service-keys"):
        assert client.get("/api/v1" + path, headers=h).status_code == 403, path


def test_read_ops_key_rejected_for_every_write_method(client, db_session):
    h = _key(db_session, "read_ops")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, URL, headers=h, json={}).status_code in (403, 405)
        assert client.request(method, "/api/v1/orders", headers=h, json={}).status_code in (403, 405)
    assert client.post("/api/v1/ops/digest", headers=_key(db_session, "read_all"), json={}).status_code in (
        403,
        405,
    )


def test_owner_login_and_shared_key_can_read(client, db_session):
    assert client.get(URL, headers=LEGACY).status_code == 200
    assert client.get(URL, headers=_person(db_session, "ops-owner", "owner")).status_code == 200


@pytest.mark.parametrize("role", ["member", "tester"])
def test_members_and_testers_cannot_read(client, db_session, role):
    assert client.get(URL, headers=_person(db_session, f"ops-{role}", role)).status_code == 403


def test_revoked_ops_key_stops_working(client, db_session):
    row, raw = service_keys.create_key(db_session, name="t", scope="read_ops", created_by="o")
    assert client.get(URL, headers={"X-API-Key": raw}).status_code == 200
    service_keys.revoke(db_session, row.id)
    assert client.get(URL, headers={"X-API-Key": raw}).status_code == 401


def test_scope_policy_is_get_only_and_ops_only():
    assert service_keys.scope_allows("read_ops", "GET", "/ops/digest")
    assert not service_keys.scope_allows("read_ops", "GET", "/opsx")
    assert not service_keys.scope_allows("read_ops", "POST", "/ops/digest")
    assert not service_keys.scope_allows("read_ops", "GET", "/status")


# ---- content and seal -------------------------------------------------------------------


def test_digest_counts_ideas_by_word_and_shows_banner(client, db_session):
    _run_with_ideas(db_session)
    body = client.get(URL, headers=LEGACY).json()
    run = body["brain"]["latest_run"]
    assert run["id"] == "ops-test-run"
    assert run["ideas_by_word"] == {"TRADE": 1, "WATCH": 1, "WAIT": 0, "AVOID": 1}
    assert run["market_banner"]["mode"] == "NORMAL"
    assert run["top_ideas"][0]["symbol"] == "AAA"


@pytest.mark.parametrize("sealed", [False, True])
def test_digest_never_contains_outcomes_or_profit(client, db_session, monkeypatch, sealed):
    monkeypatch.setattr(trial_seal, "SEALED", sealed)
    _run_with_ideas(db_session)
    r = client.get(URL, headers=LEGACY)
    assert r.json()["trial_seal"]["active"] is sealed
    text = json.dumps({k: v for k, v in r.json().items() if k != "trial_seal"}).lower()
    for banned in (
        "outcome",
        "return",
        "pnl",
        "profit",
        "win_rate",
        "hit_rate",
        "max_up",
        "max_down",
        "net_pnl",
    ):
        assert banned not in text, banned


def test_a_broken_section_does_not_hide_the_others(client, db_session, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(ops_digest, "_v1_scan_section", boom)
    body = client.get(URL, headers=LEGACY).json()
    assert "error" in body["v1_scan"] and "secret detail" not in json.dumps(body)
    assert "drawdown_pct" in body["risk"]


def test_digest_is_read_only_no_rows_written(client, db_session):
    from sqlalchemy import func, select

    n = db_session.execute(select(func.count(BrainRun.id))).scalar_one()
    client.get(URL, headers=LEGACY)
    assert db_session.execute(select(func.count(BrainRun.id))).scalar_one() == n
