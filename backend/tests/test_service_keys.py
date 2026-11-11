"""Scoped service keys against the scratch test database (Docker Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.audit import AuditLog
from swing_trade_ml.db.models.service_keys import ServiceKey
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services import service_keys

LEGACY = {"X-API-Key": "test-api-key"}


def make_user(db, name, role="member"):
    u = User(username=name, hashed_password="x", is_active=True, role=role)
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def key_header(raw):
    return {"X-API-Key": raw}


def new_key(db, scope="read_status", name="uptime-watch", **kw):
    return service_keys.create_key(db, name=name, scope=scope, created_by="owner1", **kw)


# ---- pure policy ---------------------------------------------------------------------------


def test_scopes_only_allow_get_and_never_private_areas():
    for scope in service_keys.SCOPES:
        assert not service_keys.scope_allows(scope, "POST", "/status")
        assert not service_keys.scope_allows(scope, "PUT", "/brain/stage")
        assert not service_keys.scope_allows(scope, "DELETE", "/me/watchlist/X")
        for path in (
            "/admin/service-keys",
            "/finance/summary",
            "/auth/kite/login",
            "/safety/status",
            "/me/watchlist",
        ):
            assert not service_keys.scope_allows(scope, "GET", path), (scope, path)
    assert service_keys.scope_allows("read_status", "GET", "/status")
    assert not service_keys.scope_allows("read_status", "GET", "/portfolio/positions")
    assert service_keys.scope_allows("read_all", "GET", "/portfolio/positions")
    assert not service_keys.scope_allows("nonsense", "GET", "/status")


def test_only_the_hash_is_stored_and_the_key_is_unguessable(db_session):
    row, raw = new_key(db_session)
    assert raw.startswith("stk_") and len(raw) > 40
    assert row.key_hash == service_keys.hash_key(raw) != raw
    assert raw not in str(list(row.__dict__.values()))
    _, raw2 = new_key(db_session)
    assert raw2 != raw


def test_unknown_scope_and_blank_name_refused(db_session):
    with pytest.raises(ValueError):
        service_keys.create_key(db_session, name="x", scope="write_all", created_by="o")
    with pytest.raises(ValueError):
        service_keys.create_key(db_session, name="  ", scope="read_all", created_by="o")


# ---- using a key ---------------------------------------------------------------------------


def test_read_status_key_reads_status_and_nothing_else(client, db_session):
    _, raw = new_key(db_session)
    assert client.get("/api/v1/status", headers=key_header(raw)).status_code == 200
    assert client.get("/api/v1/portfolio/positions", headers=key_header(raw)).status_code == 403
    assert client.get("/api/v1/status").status_code == 401


def test_service_key_cannot_write_or_reach_owner_areas(client, db_session):
    _, raw = new_key(db_session, scope="read_all", name="reader")
    h = key_header(raw)
    assert client.put("/api/v1/brain/stage", json={"stage": "auto"}, headers=h).status_code == 403
    assert client.get("/api/v1/admin/service-keys", headers=h).status_code == 403
    assert client.get("/api/v1/admin/release-switches", headers=h).status_code == 403
    assert client.get("/api/v1/finance/transactions", headers=h).status_code == 403
    assert client.post("/api/v1/safety/kill-switch", headers=h).status_code in (403, 404, 405)


def test_unknown_stk_key_is_401_not_a_fallback_to_the_shared_key(client):
    assert client.get("/api/v1/status", headers=key_header("stk_doesnotexist")).status_code == 401


def test_revoked_and_expired_keys_stop_working(client, db_session):
    row, raw = new_key(db_session)
    assert client.get("/api/v1/status", headers=key_header(raw)).status_code == 200
    service_keys.revoke(db_session, row.id)
    assert client.get("/api/v1/status", headers=key_header(raw)).status_code == 401
    row2, raw2 = new_key(db_session, name="short")
    row2.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()
    assert client.get("/api/v1/status", headers=key_header(raw2)).status_code == 401


def test_last_used_is_recorded_but_not_on_every_call(client, db_session):
    row, raw = new_key(db_session)
    assert row.last_used_at is None
    client.get("/api/v1/status", headers=key_header(raw))
    db_session.refresh(row)
    first = row.last_used_at
    assert first is not None
    client.get("/api/v1/status", headers=key_header(raw))
    db_session.refresh(row)
    assert row.last_used_at == first


# ---- legacy shared key ---------------------------------------------------------------------


def test_legacy_key_still_works_by_default_and_is_refused_when_turned_off(client, monkeypatch):
    assert settings.LEGACY_API_KEY_ENABLED is True
    assert client.get("/api/v1/status", headers=LEGACY).status_code == 200
    monkeypatch.setattr(settings, "LEGACY_API_KEY_ENABLED", False)
    assert client.get("/api/v1/status", headers=LEGACY).status_code == 401


def test_turning_legacy_off_leaves_scoped_keys_and_user_logins_working(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "LEGACY_API_KEY_ENABLED", False)
    _, raw = new_key(db_session)
    owner = make_user(db_session, "boss", role="owner")
    assert client.get("/api/v1/status", headers=key_header(raw)).status_code == 200
    assert client.get("/api/v1/status", headers=owner).status_code == 200


# ---- admin management ----------------------------------------------------------------------


def test_only_a_signed_in_owner_manages_keys(client, db_session):
    member = make_user(db_session, "mem")
    owner = make_user(db_session, "boss", role="owner")
    body = {"name": "uptime-watch", "scope": "read_status"}
    assert client.post("/api/v1/admin/service-keys", json=body, headers=member).status_code == 403
    assert client.get("/api/v1/admin/service-keys", headers=member).status_code == 403
    # The shared key (which these keys replace) may not mint new keys.
    assert client.post("/api/v1/admin/service-keys", json=body, headers=LEGACY).status_code == 403
    r = client.post("/api/v1/admin/service-keys", json=body, headers=owner)
    assert r.status_code == 201 and r.json()["key"].startswith("stk_")


def test_list_never_shows_secret_and_create_is_audited(client, db_session):
    owner = make_user(db_session, "boss", role="owner")
    created = client.post(
        "/api/v1/admin/service-keys",
        json={"name": "smoke", "scope": "read_all", "expires_in_days": 30},
        headers=owner,
    ).json()
    listing = client.get("/api/v1/admin/service-keys", headers=owner)
    assert created["key"] not in listing.text
    assert "key_hash" not in listing.text
    item = listing.json()["keys"][0]
    assert item["status"] == "active" and item["scope"] == "read_all" and item["expires_at"]
    assert listing.json()["legacy_api_key_enabled"] is True
    log = db_session.query(AuditLog).filter(AuditLog.action == "service_key.create").one()
    assert log.actor_label == "boss" and created["key"] not in str(log.after)


def test_rotate_overlaps_then_old_key_dies(client, db_session):
    owner = make_user(db_session, "boss", role="owner")
    first = client.post(
        "/api/v1/admin/service-keys", json={"name": "uptime-watch", "scope": "read_status"}, headers=owner
    ).json()
    rot = client.post(
        f"/api/v1/admin/service-keys/{first['item']['id']}/rotate", json={"overlap_hours": 24}, headers=owner
    ).json()
    assert rot["key"] != first["key"] and rot["item"]["name"] == "uptime-watch"
    # During the overlap both work.
    assert client.get("/api/v1/status", headers=key_header(first["key"])).status_code == 200
    assert client.get("/api/v1/status", headers=key_header(rot["key"])).status_code == 200
    # Past the overlap the old one is gone.
    old = db_session.get(ServiceKey, first["item"]["id"])
    old.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert client.get("/api/v1/status", headers=key_header(first["key"])).status_code == 401
    assert client.get("/api/v1/status", headers=key_header(rot["key"])).status_code == 200


def test_rotate_with_zero_overlap_and_revoke(client, db_session):
    owner = make_user(db_session, "boss", role="owner")
    a = client.post(
        "/api/v1/admin/service-keys", json={"name": "a", "scope": "read_status"}, headers=owner
    ).json()
    rot = client.post(
        f"/api/v1/admin/service-keys/{a['item']['id']}/rotate", json={"overlap_hours": 0}, headers=owner
    ).json()
    assert client.get("/api/v1/status", headers=key_header(a["key"])).status_code == 401
    r = client.post(f"/api/v1/admin/service-keys/{rot['item']['id']}/revoke", headers=owner)
    assert r.json()["item"]["status"] == "revoked"
    assert client.get("/api/v1/status", headers=key_header(rot["key"])).status_code == 401
    assert client.post("/api/v1/admin/service-keys/99999/revoke", headers=owner).status_code == 404
    gone = client.post(f"/api/v1/admin/service-keys/{a['item']['id']}/rotate", json={}, headers=owner)
    assert gone.status_code == 404


def test_invalid_scope_rejected_by_the_api(client, db_session):
    owner = make_user(db_session, "boss", role="owner")
    r = client.post("/api/v1/admin/service-keys", json={"name": "x", "scope": "write_all"}, headers=owner)
    assert r.status_code == 422


def test_migration_chains_from_billing01_and_head_is_single():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_revision("servicekeys01").down_revision == "billing01"
    # acctdelete01 later joins servicekeys01 and adminmfa01, so it is the single head now.
    assert script.get_heads() == ["acctdelete01"]
