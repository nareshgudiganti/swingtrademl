"""Groww sync API (owner only), the tracker's Groww status, and the 15:35 / daily-ingest jobs.

Display/tracking only: nothing here places or changes an order.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from swing_trade_ml.api.v1.endpoints import groww as groww_api
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.base import utcnow
from swing_trade_ml.db.models.groww import (
    HELD,
    MATCH_CONFIRMED,
    MATCH_NEEDS,
    MATCH_SUGGESTED,
    SOURCE_GROWW,
    SYNC_COMPLETE,
    SYNC_EMPTY,
    SYNC_FAILED,
    GrowwHolding,
    GrowwSync,
)
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services.groww import sync as gsync
from swing_trade_ml.workers import jobs

API = "/api/v1"
OWNER = "gw-realowner"
_token = 960000


@pytest.fixture(autouse=True)
def _real_owner(monkeypatch):
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", f"{OWNER}, someoneelse")


def _as(db, username: str, role: str = "owner") -> tuple[User, dict[str, str]]:
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan="free")
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _inst(db, symbol):
    global _token
    _token += 1
    inst = Instrument(instrument_token=_token, tradingsymbol=symbol, name=f"{symbol} Ltd", exchange="NSE")
    db.add(inst)
    db.flush()
    return inst


def _sync(db, status=SYNC_COMPLETE, started=None, finished=None, count=0):
    started = started or utcnow() - timedelta(hours=1)
    sync = GrowwSync(
        started_at=started,
        finished_at=finished or started + timedelta(seconds=2),
        trigger="manual",
        status=status,
        holdings_count=count,
    )
    db.add(sync)
    db.flush()
    return sync


def _aware(value: str) -> bool:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None


ROUTES = [
    ("post", "/groww/sync", None),
    ("get", "/groww/status", None),
    ("get", "/groww/matching", None),
    ("post", "/groww/matching/INE000A01011", {"instrument_id": 1}),
    ("post", "/groww/matching/confirm-all", None),
    ("post", "/groww/syncs/1/confirm-empty", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
@pytest.mark.parametrize(
    ("username", "role"), [("gw-plainowner", "owner"), ("gw-tester", "tester"), ("gw-member", "member")]
)
def test_every_groww_route_403_for_non_owner(client, db_session, method, path, body, username, role):
    _, hdr = _as(db_session, username, role)
    kwargs = {"headers": hdr}
    if body is not None:
        kwargs["json"] = body
    r = getattr(client, method)(API + path, **kwargs)
    assert r.status_code == 403, r.text


def test_no_credentials_refused(client):
    assert client.get(API + "/groww/status").status_code == 401


def test_concurrent_refresh_returns_already_running(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)

    def busy(db, *, user_id, trigger):
        raise gsync.SyncAlreadyRunning()

    monkeypatch.setattr(groww_api.groww_sync, "run_sync", busy)
    r = client.post(API + "/groww/sync", headers=hdr)
    assert r.status_code == 409
    assert r.json() == {"detail": "already refreshing"}


def test_refresh_rate_limited(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    _sync(db_session, status=SYNC_FAILED, started=utcnow() - timedelta(seconds=10))
    calls = []
    monkeypatch.setattr(groww_api.groww_sync, "run_sync", lambda *a, **k: calls.append(1))
    r = client.post(API + "/groww/sync", headers=hdr)
    assert r.status_code == 429
    assert calls == []


def test_refresh_not_configured_is_503(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: False)
    r = client.post(API + "/groww/sync", headers=hdr)
    assert r.status_code == 503
    assert "Groww" in r.json()["detail"]


def test_refresh_runs_a_manual_sync(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    _sync(db_session, status=SYNC_FAILED, started=utcnow() - timedelta(minutes=5))

    def boom():
        raise ConnectionError("no redis")

    monkeypatch.setattr(gsync, "_get_redis", boom)
    monkeypatch.setattr(gsync, "fetch_holdings", lambda: [])
    r = client.post(API + "/groww/sync", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == SYNC_EMPTY and body["holdings_count"] == 0
    assert _aware(body["finished_at"])
    latest = db_session.query(GrowwSync).order_by(GrowwSync.id.desc()).first()
    assert latest.trigger == "manual"


def test_status_and_tracker_groww_object(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    ok = _sync(db_session, status=SYNC_COMPLETE, started=utcnow() - timedelta(hours=3))
    last = _sync(db_session, status=SYNC_FAILED, started=utcnow() - timedelta(hours=1))
    s = client.get(API + "/groww/status", headers=hdr).json()
    assert s["configured"] is True
    assert s["last_status"] == SYNC_FAILED and s["last_sync_id"] == last.id
    assert datetime.fromisoformat(s["last_success_at"]) == ok.finished_at
    assert datetime.fromisoformat(s["last_attempt_at"]) == last.started_at
    assert _aware(s["last_success_at"]) and _aware(s["last_attempt_at"])


def test_status_with_no_syncs(client, db_session, monkeypatch):
    _, hdr = _as(db_session, OWNER)
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: False)
    s = client.get(API + "/groww/status", headers=hdr).json()
    if s["last_sync_id"] is None:  # a clean DB; other rows may exist from a shared dev DB
        assert s == {
            "configured": False,
            "last_success_at": None,
            "last_status": None,
            "last_attempt_at": None,
            "last_sync_id": None,
        }


def test_tracker_includes_groww_status_for_owner_only(client, db_session, monkeypatch):
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    owner, hdr = _as(db_session, OWNER)
    _, plain = _as(db_session, "gw-plainowner2")
    _, member = _as(db_session, "gw-member2", "member")
    sync = _sync(db_session, status=SYNC_COMPLETE)

    # Empty list: the owner still needs the status (to run the first sync).
    t = client.get(API + "/me/watchlist/tracker", headers=hdr).json()
    assert t["groww"]["last_sync_id"] == sync.id and t["groww"]["configured"] is True
    for h in (plain, member):
        assert "groww" not in client.get(API + "/me/watchlist/tracker", headers=h).json()

    _inst(db_session, "GWTRK")
    synced = datetime(2026, 11, 20, 10, 5, tzinfo=UTC)
    db_session.add(
        UserWatchlistItem(
            user_id=owner.id,
            symbol="GWTRK",
            source=SOURCE_GROWW,
            groww_isin="INE111A01011",
            held_state=HELD,
            quantity=5,
            buy_price=100.0,
            groww_synced_at=synced,
        )
    )
    db_session.flush()
    t = client.get(API + "/me/watchlist/tracker", headers=hdr).json()
    item = t["items"][0]
    assert item["source"] == SOURCE_GROWW and item["held_state"] == HELD
    assert item["pending_sale_qty"] is None
    assert _aware(item["groww_synced_at"])
    assert datetime.fromisoformat(item["groww_synced_at"]) == synced
    assert _aware(t["groww"]["last_success_at"]) and _aware(t["groww"]["last_attempt_at"])


def test_matching_lists_latest_non_confirmed_rows(client, db_session):
    _, hdr = _as(db_session, OWNER)
    a = _inst(db_session, "GWMATCHA")
    sync = _sync(db_session, status=SYNC_COMPLETE, count=3)
    db_session.add_all(
        [
            GrowwHolding(
                sync_id=sync.id,
                isin="INE900A01011",
                trading_symbol="GWMATCHA-EQ",
                quantity=2,
                average_price=10.0,
                instrument_id=a.id,
                match_state=MATCH_SUGGESTED,
            ),
            GrowwHolding(
                sync_id=sync.id,
                isin="INE900A01012",
                trading_symbol="ODD",
                quantity=1,
                average_price=5.0,
                instrument_id=None,
                match_state=MATCH_NEEDS,
            ),
            GrowwHolding(
                sync_id=sync.id,
                isin="INE900A01013",
                trading_symbol="DONE",
                quantity=1,
                average_price=5.0,
                instrument_id=a.id,
                match_state=MATCH_CONFIRMED,
            ),
        ]
    )
    db_session.flush()
    items = client.get(API + "/groww/matching", headers=hdr).json()["items"]
    by = {i["isin"]: i for i in items}
    assert set(by) == {"INE900A01011", "INE900A01012"}
    assert by["INE900A01011"]["suggested_symbol"] == "GWMATCHA"
    assert by["INE900A01011"]["suggested_instrument_id"] == a.id
    assert by["INE900A01012"]["suggested_symbol"] is None and by["INE900A01012"]["match_state"] == MATCH_NEEDS

    r = client.post(API + "/groww/matching/INE900A01012", json={"instrument_id": a.id}, headers=hdr)
    assert r.status_code == 200, r.text
    r = client.post(API + "/groww/matching/confirm-all", headers=hdr)
    assert r.status_code == 200 and r.json()["confirmed"] == 1
    assert client.get(API + "/groww/matching", headers=hdr).json()["items"] == []
    bad = client.post(API + "/groww/matching/INE900A01012", json={"instrument_id": 0}, headers=hdr)
    assert bad.status_code == 404


def test_confirm_empty_only_latest(client, db_session):
    _, hdr = _as(db_session, OWNER)
    old = _sync(db_session, status=SYNC_EMPTY, started=utcnow() - timedelta(hours=2))
    _sync(db_session, status=SYNC_FAILED, started=utcnow() - timedelta(hours=1))
    r = client.post(API + f"/groww/syncs/{old.id}/confirm-empty", headers=hdr)
    assert r.status_code == 409 and "newer" in r.json()["detail"]
    new = _sync(db_session, status=SYNC_EMPTY, started=utcnow() - timedelta(minutes=5))
    r = client.post(API + f"/groww/syncs/{new.id}/confirm-empty", headers=hdr)
    assert r.status_code == 200, r.text
    db_session.refresh(new)
    assert new.status == SYNC_COMPLETE


# --- jobs ----------------------------------------------------------------------------------------


def _use_test_session(monkeypatch, db_session):
    @contextmanager
    def scope():
        yield db_session

    monkeypatch.setattr(jobs, "session_scope", scope)


def test_groww_held_symbols_backfilled_but_not_watchlisted(db_session, monkeypatch):
    _use_test_session(monkeypatch, db_session)
    owner, _ = _as(db_session, OWNER)
    inst = _inst(db_session, "GWPRICE")
    inst.is_watchlisted = False
    db_session.add(
        UserWatchlistItem(user_id=owner.id, symbol="GWPRICE", source=SOURCE_GROWW, held_state=HELD)
    )
    db_session.flush()

    calls: list[list[str]] = []
    monkeypatch.setattr(jobs.ingestion, "backfill_watchlist", lambda db, **k: {})
    monkeypatch.setattr(jobs.ingestion, "backfill_index", lambda db, **k: 0)
    monkeypatch.setattr(jobs.ingestion, "backfill_context_indices", lambda db, **k: {})
    monkeypatch.setattr(
        jobs.ingestion, "backfill_symbols", lambda db, symbols, **k: calls.append(list(symbols)) or {}
    )
    import swing_trade_ml.services.watchlist_snapshots as snaps

    monkeypatch.setattr(snaps, "record_watchlist_snapshot", lambda db: None)
    jobs.job_daily_ingest()
    assert any("GWPRICE" in c for c in calls)
    db_session.refresh(inst)
    assert inst.is_watchlisted is False


def test_groww_backfill_failure_does_not_block_ingest(db_session, monkeypatch):
    _use_test_session(monkeypatch, db_session)
    owner, _ = _as(db_session, OWNER)
    _inst(db_session, "GWPRICE2")
    db_session.add(
        UserWatchlistItem(user_id=owner.id, symbol="GWPRICE2", source=SOURCE_GROWW, held_state=HELD)
    )
    db_session.flush()
    monkeypatch.setattr(jobs.ingestion, "backfill_watchlist", lambda db, **k: {})
    monkeypatch.setattr(jobs.ingestion, "backfill_index", lambda db, **k: 0)
    monkeypatch.setattr(jobs.ingestion, "backfill_context_indices", lambda db, **k: {})

    def boom(db, symbols, **k):
        raise RuntimeError("kite down")

    monkeypatch.setattr(jobs.ingestion, "backfill_symbols", boom)
    import swing_trade_ml.services.watchlist_snapshots as snaps

    snapped = []
    monkeypatch.setattr(snaps, "record_watchlist_snapshot", lambda db: snapped.append(1))
    errors = []
    monkeypatch.setattr(jobs, "_report_error", lambda ctx, exc: errors.append(ctx))
    jobs.job_daily_ingest()
    assert snapped == [1] and errors == []


def test_job_groww_sync_runs_for_first_real_account_owner(db_session, monkeypatch):
    _use_test_session(monkeypatch, db_session)
    owner, _ = _as(db_session, OWNER)
    monkeypatch.setattr(jobs.groww_client, "is_configured", lambda: True)
    seen = []
    monkeypatch.setattr(
        jobs.groww_sync, "run_sync", lambda db, *, user_id, trigger: seen.append((user_id, trigger))
    )
    jobs.job_groww_sync()
    assert seen == [(owner.id, "scheduled")]


def test_job_groww_sync_skips_when_not_configured_or_no_owner(db_session, monkeypatch):
    _use_test_session(monkeypatch, db_session)
    seen = []
    monkeypatch.setattr(jobs.groww_sync, "run_sync", lambda db, **k: seen.append(k))
    monkeypatch.setattr(jobs.groww_client, "is_configured", lambda: False)
    jobs.job_groww_sync()
    monkeypatch.setattr(jobs.groww_client, "is_configured", lambda: True)
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "gw-nobody-here")
    jobs.job_groww_sync()
    assert seen == []


def test_groww_sync_scheduled_weekdays_1535_ist():
    from apscheduler.schedulers.background import BackgroundScheduler

    from swing_trade_ml.workers.scheduler import add_groww_job

    s = BackgroundScheduler()
    add_groww_job(s)
    job = s.get_job("groww_sync")
    assert job is not None and job.func is jobs.job_groww_sync
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "15" and fields["minute"] == "35" and fields["day_of_week"] == "mon-fri"
    assert str(job.trigger.timezone) == "Asia/Kolkata"


# --- one Groww tracker: writes always go to the Groww account owner ------------------------------


WRITE_ROUTES = [
    ("/groww/sync", None),
    ("/groww/matching/INE000A01011", {"instrument_id": 1}),
    ("/groww/matching/confirm-all", None),
    ("/groww/syncs/1/confirm-empty", None),
]


@pytest.mark.parametrize(("path", "body"), WRITE_ROUTES)
def test_second_real_account_owner_cannot_write(client, db_session, monkeypatch, path, body):
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    monkeypatch.setattr(groww_api.groww_sync, "run_sync", lambda *a, **k: pytest.fail("must not sync"))
    _as(db_session, OWNER)
    _, other = _as(db_session, "someoneelse")  # also in REAL_ACCOUNT_USERS, but not first
    r = client.post(API + path, json=body, headers=other) if body else client.post(API + path, headers=other)
    assert r.status_code == 403
    assert r.json()["detail"] == "Only the Groww account owner can do this."
    # Reading the status is still fine for them.
    assert client.get(API + "/groww/status", headers=other).status_code == 200


def test_writes_target_the_groww_owner_tracker(client, db_session, monkeypatch):
    monkeypatch.setattr(groww_api.groww_client, "is_configured", lambda: True)
    owner, hdr = _as(db_session, OWNER)
    seen = []

    def fake_run(db, *, user_id, trigger):
        seen.append(user_id)
        return GrowwSync(status=SYNC_FAILED, holdings_count=None, finished_at=utcnow(), trigger=trigger)

    monkeypatch.setattr(groww_api.groww_sync, "run_sync", fake_run)
    assert client.post(API + "/groww/sync", headers=hdr).status_code == 200
    assert client.post(API + "/groww/sync", headers={"X-API-Key": "test-api-key"}).status_code in (200, 429)
    assert seen and all(uid == owner.id for uid in seen)


def test_owner_user_id_requires_owner_role(db_session, monkeypatch):
    member, _ = _as(db_session, OWNER, "member")
    assert gsync.owner_user_id(db_session) is None
    member.role = "owner"
    db_session.flush()
    assert gsync.owner_user_id(db_session) == member.id
    monkeypatch.setattr(settings, "REAL_ACCOUNT_USERS", "")
    assert gsync.owner_user_id(db_session) is None
