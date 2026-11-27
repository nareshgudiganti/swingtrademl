"""#310 slice A: saved screens (per-person settings) and the Brain-idea "what changed" digest.

Privacy is the point: every handler keys on the user id from the credential, never from the body or path.
The digest is read only, uses only finished live nightly brain runs, never selects an outcome column and
never promises gain. Runs in its own book so other tests' runs never match.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, func, select

from swing_trade_ml.api.deps import SELF_SERVICE_ROUTES
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.plans import ROUTE_RULES
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.saved_screen import SavedScreen
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.models.user_watchlist import UserWatchlistItem
from swing_trade_ml.services import saved_screens as svc
from swing_trade_ml.services import screen_digest

URL = "/api/v1/me/screens"
API_KEY = {"X-API-Key": "test-api-key"}
IST = ZoneInfo("Asia/Kolkata")
BOOK = "f2sv"
TUE = datetime(2031, 3, 11, 10, 20, tzinfo=UTC)
WED = datetime(2031, 3, 12, 10, 20, tzinfo=UTC)
BANNED = re.compile(r"profit|return|chance|gain|\bwill\b|likely|guarantee", re.I)


@pytest.fixture(autouse=True)
def _brain_on(monkeypatch):
    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)


def _as(db, username, role="member", plan="free"):
    user = User(username=username, hashed_password="x", is_active=True, role=role, plan=plan)
    db.add(user)
    db.flush()
    return user, {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id, 'tv': 0})}"}


def _spec(**kw):
    return {"horizon": "15d", "word": "ALL", **kw}


def _save(client, headers, name="My screen", **spec):
    return client.post(URL, json={"name": name, "spec": _spec(**spec)}, headers=headers)


# ------------------------------------------------------------------ routes are classified


def test_crud_routes_are_self_service_and_digests_are_plan_gated():
    for key in [
        ("GET", "/me/screens"),
        ("POST", "/me/screens"),
        ("GET", "/me/screens/{screen_id}"),
        ("PATCH", "/me/screens/{screen_id}"),
        ("DELETE", "/me/screens/{screen_id}"),
    ]:
        assert key in SELF_SERVICE_ROUTES, key
    for key in [("GET", "/me/screens/{screen_id}/digest"), ("GET", "/me/watchlist/digest")]:
        assert ROUTE_RULES[key][0] == "screen_digest", key


# ------------------------------------------------------------------ save, restore, rename, delete


@pytest.mark.parametrize("role", ["owner", "tester", "member"])
def test_every_role_saves_opens_renames_and_deletes_its_own_screen(client, db_session, role):
    _, me = _as(db_session, f"ss-{role}", role)
    assert client.get(URL, headers=me).json()["screens"] == []
    made = _save(
        client,
        me,
        "Five day",
        word="TRADE",
        sector="Banks",
        query="HDF",
        layout="slides",
        cap_tiers=["large"],
        patterns=["base"],
        watch_only=True,
    )
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    got = client.get(f"{URL}/{sid}", headers=me).json()
    assert got["name"] == "Five day"
    assert got["spec"] == {
        "horizon": "15d",
        "cap_tiers": ["large"],
        "patterns": ["base"],
        "word": "TRADE",
        "sector": "Banks",
        "query": "HDF",
        "layout": "slides",
        "watch_only": True,
    }
    renamed = client.patch(f"{URL}/{sid}", json={"name": "Renamed"}, headers=me)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    assert renamed.json()["spec"] == got["spec"]
    replaced = client.patch(f"{URL}/{sid}", json={"spec": _spec(word="WATCH")}, headers=me)
    assert replaced.json()["spec"]["word"] == "WATCH" and replaced.json()["name"] == "Renamed"
    assert client.delete(f"{URL}/{sid}", headers=me).status_code == 200
    assert client.get(f"{URL}/{sid}", headers=me).status_code == 404


def test_deleting_a_screen_never_touches_the_watchlist(client, db_session):
    user, me = _as(db_session, "ss-wl")
    db_session.add(UserWatchlistItem(user_id=user.id, symbol="AAA"))
    db_session.flush()
    sid = _save(client, me).json()["id"]
    client.delete(f"{URL}/{sid}", headers=me)
    left = db_session.scalar(
        select(func.count()).select_from(UserWatchlistItem).where(UserWatchlistItem.user_id == user.id)
    )
    assert left == 1


def test_the_api_key_with_no_person_is_refused_everywhere(client):
    assert client.get(URL, headers=API_KEY).status_code == 403
    assert client.post(URL, json={"name": "x", "spec": _spec()}, headers=API_KEY).status_code == 403
    assert client.get(f"{URL}/1", headers=API_KEY).status_code == 403
    assert client.patch(f"{URL}/1", json={"name": "y"}, headers=API_KEY).status_code == 403
    assert client.delete(f"{URL}/1", headers=API_KEY).status_code == 403
    assert client.get(f"{URL}/1/digest", headers=API_KEY).status_code == 403
    assert client.get("/api/v1/me/watchlist/digest", headers=API_KEY).status_code == 403


def test_signed_out_callers_are_refused(client):
    assert client.get(URL).status_code in (401, 403)


# ------------------------------------------------------------------ A3 isolation


def test_nobody_reads_changes_deletes_or_digests_someone_elses_screen(client, db_session):
    _, owner = _as(db_session, "iso-owner", "owner")
    _, tester = _as(db_session, "iso-tester", "tester")
    _, alice = _as(db_session, "iso-alice", "member", "pro")
    _, bob = _as(db_session, "iso-bob", "member", "pro")
    viewers = {"owner": owner, "tester": tester, "alice": alice, "bob": bob}
    ids = {who: _save(client, h, f"{who} private").json()["id"] for who, h in viewers.items()}
    for who, headers in viewers.items():
        listed = client.get(URL, headers=headers).json()["screens"]
        assert [s["name"] for s in listed] == [f"{who} private"]
        for other, sid in ids.items():
            if other == who:
                continue
            assert client.get(f"{URL}/{sid}", headers=headers).status_code == 404
            assert client.patch(f"{URL}/{sid}", json={"name": "hijack"}, headers=headers).status_code == 404
            assert client.delete(f"{URL}/{sid}", headers=headers).status_code == 404
            assert client.get(f"{URL}/{sid}/digest", headers=headers).status_code in (403, 404)
    names = {s.name for s in db_session.scalars(select(SavedScreen).where(SavedScreen.id.in_(ids.values())))}
    assert names == {f"{k} private" for k in ids}


def test_a_user_id_in_the_body_is_ignored(client, db_session):
    _, a = _as(db_session, "body-alice")
    bob, _ = _as(db_session, "body-bob")
    r = client.post(URL, json={"name": "x", "spec": _spec(), "user_id": bob.id}, headers=a)
    assert r.status_code in (201, 422)
    owned = db_session.scalar(
        select(func.count()).select_from(SavedScreen).where(SavedScreen.user_id == bob.id)
    )
    assert owned == 0


def test_the_digest_of_a_pro_members_own_screen_is_theirs_alone(client, db_session):
    _, alice = _as(db_session, "dg-alice", plan="pro")
    _, bob = _as(db_session, "dg-bob", plan="pro")
    sid = _save(client, alice).json()["id"]
    assert client.get(f"{URL}/{sid}/digest", headers=bob).status_code == 404
    assert client.get(f"{URL}/{sid}/digest", headers=alice).status_code == 200


# ------------------------------------------------------------------ A5 names, limits, values


def test_names_are_unique_per_person_ignoring_case_but_not_across_people(client, db_session):
    _, a = _as(db_session, "nm-a")
    _, b = _as(db_session, "nm-b")
    assert _save(client, a, "Swing ideas").status_code == 201
    assert _save(client, a, "swing IDEAS").status_code == 409
    assert _save(client, b, "Swing ideas").status_code == 201
    other = _save(client, a, "Second").json()["id"]
    assert client.patch(f"{URL}/{other}", json={"name": " SWING ideas "}, headers=a).status_code == 409
    assert client.patch(f"{URL}/{other}", json={"name": "Second"}, headers=a).status_code == 200


@pytest.mark.parametrize("name", ["", "   ", "x" * 61])
def test_names_must_be_1_to_60_characters(client, db_session, name):
    _, me = _as(db_session, "nm-len")
    assert _save(client, me, name).status_code == 422
    assert _save(client, me, "y" * 60).status_code == 201


def test_free_gets_3_screens_pro_and_owner_get_10(client, db_session):
    _, free = _as(db_session, "lim-free", plan="free")
    _, pro = _as(db_session, "lim-pro", plan="pro")
    _, owner = _as(db_session, "lim-owner", "owner")
    assert client.get(URL, headers=free).json()["limit"] == 3
    for i in range(3):
        assert _save(client, free, f"s{i}").status_code == 201
    over = _save(client, free, "s3")
    assert over.status_code == 422 and "3" in over.json()["detail"]
    for who, headers in (("pro", pro), ("owner", owner)):
        assert client.get(URL, headers=headers).json()["limit"] == svc.MAX_SCREENS == 10
        for i in range(10):
            assert _save(client, headers, f"{who}{i}").status_code == 201
        assert _save(client, headers, f"{who}-over").status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"horizon": "7d"},
        {"word": "BUY"},
        {"word": "hold"},
        {"cap_tiers": ["huge"]},
        {"patterns": ["moonshot"]},
        {"layout": "grid"},
        {"query": "x" * 33},
        {"sector": "s" * 61},
        {"watch_only": "maybe"},
        {"profit": 5},
        {"cap_tiers": "large"},
    ],
)
def test_invalid_values_are_rejected_with_422(client, db_session, bad):
    _, me = _as(db_session, "bad-spec")
    assert _save(client, me, **bad).status_code == 422


def test_no_result_score_or_price_can_be_stored(client, db_session):
    _, me = _as(db_session, "no-results")
    for field in ("score", "price", "results", "profit"):
        assert _save(client, me, **{field: 1}).status_code == 422


# ------------------------------------------------------------------ A4 account deletion and export


def test_screens_go_with_the_account_row(db_session):
    user, _ = _as(db_session, "casc")
    db_session.add(SavedScreen(user_id=user.id, name="gone", spec=_spec()))
    db_session.flush()
    db_session.delete(user)
    db_session.flush()
    assert (
        db_session.scalar(select(func.count()).select_from(SavedScreen).where(SavedScreen.name == "gone"))
        == 0
    )


def test_account_deletion_removes_and_export_includes_my_screens_only(db_session):
    from swing_trade_ml.services import account_deletion as deletion

    me, _ = _as(db_session, "acct-me")
    other, _ = _as(db_session, "acct-other")
    db_session.add_all(
        [
            SavedScreen(user_id=me.id, name="mine", spec=_spec(word="TRADE")),
            SavedScreen(user_id=other.id, name="theirs", spec=_spec()),
        ]
    )
    db_session.flush()
    exported = deletion.export_data(db_session, me)
    assert [s["name"] for s in exported["saved_screens"]] == ["mine"]
    assert exported["saved_screens"][0]["spec"]["word"] == "TRADE"
    deletion.anonymise(db_session, me)
    left = db_session.scalars(
        select(SavedScreen.name).where(SavedScreen.user_id.in_([me.id, other.id]))
    ).all()
    assert left == ["theirs"]


# ------------------------------------------------------------------ migration


def test_migration_chain_and_round_trip(db_session):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import inspect

    path = Path(__file__).parents[1] / "alembic/versions/20261127_1200_saved_screens.py"
    spec = spec_from_file_location("saved_screens_migration", path)
    mig = module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == "savedscreen01"
    assert mig.down_revision == "signalkey01"  # lands after the #260 PR (scanrank01, scanrank02)
    conn = db_session.connection()
    mig.op = Operations(MigrationContext.configure(conn))
    mig.downgrade()
    assert "saved_screens" not in inspect(conn).get_table_names()
    mig.upgrade()
    cols = {c["name"] for c in inspect(conn).get_columns("saved_screens")}
    assert {"id", "user_id", "name", "spec", "filters_version", "created_at", "updated_at"} <= cols


# ------------------------------------------------------------------ plan gate for the digest


def test_digest_is_pro_only_free_is_refused_and_pro_may_read(client, db_session):
    _, free = _as(db_session, "gate-free", plan="free")
    _, pro = _as(db_session, "gate-pro", plan="pro")
    sid = _save(client, free).json()["id"]
    r = client.get(f"{URL}/{sid}/digest", headers=free)
    assert r.status_code == 403 and "isn't included in the free plan" in r.json()["detail"]
    assert client.get("/api/v1/me/watchlist/digest", headers=free).status_code == 403
    psid = _save(client, pro).json()["id"]
    ok = client.get(f"{URL}/{psid}/digest", headers=pro)
    assert ok.status_code == 200 and "comparable" in ok.json()
    assert client.get("/api/v1/me/watchlist/digest", headers=pro).status_code == 200


def test_saved_screens_still_open_for_free_when_the_brain_is_off(client, db_session, monkeypatch):
    _, free = _as(db_session, "off-free")
    sid = _save(client, free).json()["id"]
    monkeypatch.setattr(settings, "BRAIN_ENABLED", False)
    assert client.get(f"{URL}/{sid}", headers=free).status_code == 200


# ------------------------------------------------------------------ the digest


def _run(db, rid, as_of, *, kind="nightly", live=True, status="done", book=BOOK, quality=None):
    run = BrainRun(
        id=f"f2-{rid}",
        kind=kind,
        as_of=as_of,
        book=book,
        live=live,
        status=status,
        started_at=as_of,
        banner_mode="NORMAL",
        quality=quality or {},
    )
    db.add(run)
    db.flush()
    return run


def _idea(db, run, symbol, word, conf=None, **kw):
    db.add(
        BrainDecision(
            run_id=run.id,
            symbol=symbol,
            kind=kw.pop("kind", "idea"),
            word=word,
            reasons=kw.pop("reasons", [f"{symbol} stored reason"]),
            confidence=conf,
            score_source="model" if conf is not None else None,
            **kw,
        )
    )
    db.flush()


_TOKEN = iter(range(880_000, 889_999))


def _instrument(db, symbol):
    inst = db.scalar(
        select(Instrument).where(Instrument.tradingsymbol == symbol, Instrument.exchange == "NSE")
    )
    if inst is None:
        inst = Instrument(instrument_token=next(_TOKEN), tradingsymbol=symbol, name=symbol, exchange="NSE")
        db.add(inst)
        db.flush()
    return inst


def _bar(db, inst, day: date, base: float = 100.0):
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST),
            open=base,
            high=base + 1,
            low=base,
            close=base + 0.5,
            volume=1000,
        )
    )


def _candles(db, symbol, last_day: date, n=70):
    """n flat daily bars ending on last_day (IST midnight stamps): a tight base once there are 60 of them."""
    inst = _instrument(db, symbol)
    for i in range(n):
        _bar(db, inst, last_day - timedelta(days=n - 1 - i))
    db.flush()


def _fresh(db, *symbols):
    for s in symbols:
        _candles(db, s, date(2031, 3, 12))


@pytest.fixture()
def days(db_session):
    return _run(db_session, "tue", TUE), _run(db_session, "wed", WED)


def _digest(db, spec=None, *, owner=True, user_id=None):
    return screen_digest.digest(
        db, svc.normalise_spec(spec or {}), user_id=user_id or 0, owner=owner, book=BOOK
    )


def test_came_in_and_dropped_out_by_word_with_a_stored_reason(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "WAIT", 0.40, reasons=["Model score is below the buy level."])
    _idea(db_session, tue, "BBB", "TRADE", 0.70)
    _idea(db_session, tue, "CCC", "WATCH", 0.60)
    _idea(db_session, wed, "AAA", "TRADE", 0.72)
    _idea(db_session, wed, "BBB", "WATCH", 0.65, downgraded_from="TRADE", downgrade_reason="risk said no")
    _idea(db_session, wed, "CCC", "WATCH", 0.30)
    _fresh(db_session, "AAA", "BBB", "CCC")
    out = _digest(db_session, {"word": "TRADE"})
    assert out["comparable"] is True
    assert [r["symbol"] for r in out["came_in"]] == ["AAA"]
    assert [r["symbol"] for r in out["dropped_out"]] == ["BBB"]
    came, dropped = out["came_in"][0], out["dropped_out"][0]
    assert came["reason_code"] == "word_changed" and "WAIT" in came["reason"] and "BUY" in came["reason"]
    assert dropped["reason_code"] == "word_changed" and "risk said no" in dropped["reason"]
    assert came["rank"] == 1 and came["rank_of"] == 3
    assert out["not_compared"] == []
    assert out["current"]["day"] == "2031-03-12" and out["previous"]["day"] == "2031-03-11"
    assert "not a chance of profit" in out["footer"] and "ranking" in out["footer"]


def test_unchanged_stocks_are_not_listed(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "TRADE", 0.7)
    _idea(db_session, wed, "AAA", "TRADE", 0.7)
    _fresh(db_session, "AAA")
    out = _digest(db_session, {"word": "TRADE"})
    assert out["came_in"] == [] and out["dropped_out"] == []


def test_a_stock_new_to_the_run_has_the_reason_not_recorded(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "WAIT", 0.5)
    _idea(db_session, wed, "AAA", "WAIT", 0.5)
    _idea(db_session, wed, "NEW", "WAIT", 0.4)
    _fresh(db_session, "AAA", "NEW")
    out = _digest(db_session, {})
    assert [r["symbol"] for r in out["came_in"]] == ["NEW"]
    assert (
        out["came_in"][0]["reason_code"] == "not_recorded" and "Not recorded" in out["came_in"][0]["reason"]
    )


def test_pattern_filter_uses_each_runs_own_candles_and_explains_the_change(db_session, days):
    tue, wed = days
    for sym in ("PAT", "APP", "THIN"):
        _idea(db_session, tue, sym, "WATCH", 0.5)
        _idea(db_session, wed, sym, "WATCH", 0.5)
    # PAT: a tight base on Tuesday; Wednesday's wild bar breaks it -> dropped out (pattern gone)
    _candles(db_session, "PAT", date(2031, 3, 11), 70)
    _bar(db_session, _instrument(db_session, "PAT"), date(2031, 3, 12), 300.0)
    # APP: 59 bars on Tuesday (too few for any pattern), the 60th on Wednesday -> a base -> came in
    _candles(db_session, "APP", date(2031, 3, 11), 59)
    _bar(db_session, _instrument(db_session, "APP"), date(2031, 3, 12))
    # THIN: too few bars on both days -> never counts as matching
    _candles(db_session, "THIN", date(2031, 3, 12), 20)
    db_session.flush()
    out = _digest(db_session, {"patterns": ["base"]})
    assert "THIN" not in {r["symbol"] for r in out["came_in"] + out["dropped_out"] + out["not_compared"]}
    assert [(r["symbol"], r["reason_code"]) for r in out["came_in"]] == [("APP", "pattern_changed")]
    assert [(r["symbol"], r["reason_code"]) for r in out["dropped_out"]] == [("PAT", "pattern_changed")]
    assert "tight base" in out["came_in"][0]["reason"].lower()


def test_pattern_reads_nothing_stamped_after_the_run_date(db_session, days):
    from swing_trade_ml.brain.reader import DatedReader

    tue, _wed = days
    _candles(db_session, "LATE", date(2031, 3, 12), 70)
    bars = DatedReader(db_session, tue.as_of, True).ohlcv("LATE", 400)
    assert bars["ts"].max().astimezone(IST).date() <= date(2031, 3, 11)


def test_stale_or_missing_data_never_comes_in_and_is_listed_as_not_compared(db_session):
    tue = _run(db_session, "tue", TUE)
    wed = _run(db_session, "wed", WED, quality={"stale": ["STALE"]})
    for sym in ("OLD", "STALE", "NOBARS", "OK"):
        _idea(db_session, tue, sym, "WAIT", 0.4)
        _idea(db_session, wed, sym, "TRADE", 0.8)
    _candles(db_session, "OLD", date(2031, 2, 20), 70)  # last bar three weeks old
    _candles(db_session, "STALE", date(2031, 3, 12), 70)  # listed stale by the run's own data check
    _candles(db_session, "OK", date(2031, 3, 12), 70)
    out = _digest(db_session, {"word": "TRADE"})
    assert [r["symbol"] for r in out["came_in"]] == ["OK"]
    assert {r["symbol"] for r in out["not_compared"]} == {"OLD", "STALE", "NOBARS"}
    assert all("Data not fresh" in r["reason"] for r in out["not_compared"])


def test_a_dropped_stock_with_stale_data_is_dropped_for_data_not_fresh(db_session):
    tue = _run(db_session, "tue", TUE)
    wed = _run(db_session, "wed", WED, quality={"stale": ["DRP"]})
    _idea(db_session, tue, "DRP", "TRADE", 0.8)
    _idea(db_session, wed, "DRP", "WAIT", 0.3)
    _candles(db_session, "DRP", date(2031, 3, 12), 70)
    out = _digest(db_session, {"word": "TRADE"})
    assert [r["symbol"] for r in out["dropped_out"]] == ["DRP"]
    assert out["dropped_out"][0]["reason_code"] == "data_not_fresh"


def test_fewer_than_two_runs_says_so_and_lists_nothing(db_session):
    out = _digest(db_session)
    assert out["comparable"] is False and out["came_in"] == out["dropped_out"] == out["not_compared"] == []
    _run(db_session, "only", WED)
    out = _digest(db_session)
    assert out["comparable"] is False and "no earlier" in out["note"].lower()
    assert out["came_in"] == [] and out["dropped_out"] == []


def test_replay_failed_superseded_and_intraday_runs_never_feed_the_digest(db_session):
    _run(db_session, "tue", TUE)
    wed = _run(db_session, "wed", WED)
    _idea(db_session, wed, "AAA", "TRADE", 0.9)
    odd = {
        "replay": {"live": False},
        "failed": {"status": "failed"},
        "sup": {"status": "superseded"},
        "intra": {"kind": "intraday"},
    }
    for rid, kw in odd.items():
        later = _run(db_session, rid, WED + timedelta(hours=1), **kw)
        _idea(db_session, later, "ZZZ", "TRADE", 0.99)
    _fresh(db_session, "AAA", "ZZZ")
    out = _digest(db_session, {"word": "TRADE"})
    assert out["current"]["run_id"] == wed.id
    assert {r["symbol"] for r in out["came_in"]} == {"AAA"}


def test_a_window_with_no_supported_ideas_is_not_replaced_by_another(db_session, days):
    _tue, wed = days
    _idea(db_session, wed, "AAA", "TRADE", 0.9)
    out = _digest(db_session, {"horizon": "5d"})
    assert out["comparable"] is False and "window" in out["note"].lower()
    assert out["came_in"] == out["dropped_out"] == []


def test_word_query_sector_and_company_size_filters(db_session, days):
    from swing_trade_ml.db.models.trading import Strategy

    tue, wed = days
    for sym in ("HDFCBANK", "INFY", "TINY"):
        _idea(db_session, tue, sym, "WAIT", 0.4)
        _idea(db_session, wed, sym, "TRADE", 0.8)
    _fresh(db_session, "HDFCBANK", "INFY", "TINY")
    db_session.add_all(
        [
            Strategy(
                name="f2sv-large",
                strategy_type="ml_swing",
                params={"model_name": "swing_classifier"},
                symbols=["HDFCBANK", "INFY"],
            ),
            Strategy(
                name="f2sv-small",
                strategy_type="ml_swing",
                params={"model_name": "x_smallcap"},
                symbols=["TINY"],
            ),
        ]
    )
    db_session.flush()

    def came(spec):
        return sorted(r["symbol"] for r in _digest(db_session, spec)["came_in"])

    assert came({"word": "TRADE"}) == ["HDFCBANK", "INFY", "TINY"]
    assert came({"word": "WAIT"}) == []
    assert came({"word": "TRADE", "query": "inf"}) == ["INFY"]
    assert came({"word": "TRADE", "cap_tiers": ["smallcap"]}) == ["TINY"]
    assert came({"word": "TRADE", "cap_tiers": ["large"]}) == ["HDFCBANK", "INFY"]
    from swing_trade_ml.ml.sector_map import get_sector_bucket, sector_display_name

    bucket = get_sector_bucket("HDFCBANK")
    assert bucket
    got = came({"word": "TRADE", "sector": sector_display_name(bucket)})
    assert "HDFCBANK" in got and "TINY" not in got


def test_watchlist_only_uses_the_callers_own_list(db_session, days):
    tue, wed = days
    mine, _ = _as(db_session, "wo-me")
    other, _ = _as(db_session, "wo-other")
    for sym in ("AAA", "BBB"):
        _idea(db_session, tue, sym, "WAIT", 0.4)
        _idea(db_session, wed, sym, "TRADE", 0.8)
    _fresh(db_session, "AAA", "BBB")
    db_session.add_all(
        [UserWatchlistItem(user_id=mine.id, symbol="AAA"), UserWatchlistItem(user_id=other.id, symbol="BBB")]
    )
    db_session.flush()
    got = _digest(db_session, {"watch_only": True, "word": "TRADE"}, user_id=mine.id)
    assert [r["symbol"] for r in got["came_in"]] == ["AAA"]


def test_non_owner_gets_no_account_room_text_and_no_owner_note(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "BBB", "TRADE", 0.7)
    _idea(
        db_session,
        wed,
        "BBB",
        "WATCH",
        0.6,
        downgraded_from="TRADE",
        downgrade_reason="plain downgrade",
        overruled_word="WAIT",
        overrule_reason="owner private note xyzzy",
        overruled_by="owner",
        reasons=["Safety check: your account cannot add another position, 3 of 3 slots are used."],
    )
    _fresh(db_session, "BBB")
    for owner in (True, False):
        text = json.dumps(_digest(db_session, {"word": "TRADE"}, owner=owner), default=str)
        assert "xyzzy" not in text, owner


def test_no_digest_text_promises_gain_and_words_are_the_four(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "WAIT", 0.4, reasons=["Good chance of profit, will rise, big return"])
    _idea(
        db_session,
        wed,
        "AAA",
        "TRADE",
        0.9,
        reasons=["Strong chance of gain, will rise"],
        downgrade_reason="return to profit chance",
    )
    _idea(db_session, tue, "BBB", "TRADE", 0.9, reasons=["profit"])
    _idea(db_session, wed, "BBB", "WAIT", 0.2, reasons=["a chance of gain"])
    _fresh(db_session, "AAA", "BBB")
    out = _digest(db_session, {"word": "TRADE"})
    assert [r["symbol"] for r in out["came_in"]] == ["AAA"]
    assert [r["symbol"] for r in out["dropped_out"]] == ["BBB"]
    texts = [out["note"] or "", out["footer"].replace("not a chance of profit", "")]
    for rows in (out["came_in"], out["dropped_out"], out["not_compared"]):
        for r in rows:
            texts.append(r["reason"])
            assert r["reason_code"] in {"data_not_fresh", "word_changed", "pattern_changed", "not_recorded"}
            for side in (r["now"], r["before"]):
                assert side is None or side["word"] in {"TRADE", "WATCH", "WAIT", "AVOID"}
    for t in texts:
        assert not BANNED.search(t), t


def test_ranks_are_places_never_the_raw_score(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "WAIT", 0.4)
    _idea(db_session, wed, "AAA", "TRADE", 0.77123)
    _idea(db_session, wed, "BBB", "WAIT", 0.9)
    _fresh(db_session, "AAA", "BBB")
    out = _digest(db_session, {"word": "TRADE"})
    assert "0.77" not in json.dumps(out, default=str) and "77%" not in json.dumps(out, default=str)
    assert out["came_in"][0]["rank"] == 2 and out["came_in"][0]["rank_of"] == 2


def test_the_digest_writes_nothing_and_never_selects_an_outcome(db_session, days):
    tue, wed = days
    _idea(db_session, tue, "AAA", "WAIT", 0.4, outcome="target", outcome_return=0.08, max_up=0.1)
    _idea(db_session, wed, "AAA", "TRADE", 0.8, outcome="stop", outcome_return=-0.04, max_down=-0.05)
    _fresh(db_session, "AAA")
    statements: list[str] = []
    writes: list[str] = []

    def spy(conn, cursor, statement, params, context, executemany):
        statements.append(statement)
        if re.match(r"\s*(insert|update|delete)", statement, re.I):
            writes.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", spy)
    try:
        out = _digest(db_session, {"word": "TRADE"})
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert out["came_in"]
    assert writes == []
    joined = " ".join(statements).lower()
    for col in ("outcome", "max_up", "max_down", "resolved_on"):
        assert col not in joined, col
    blob = json.dumps(out, default=str)
    assert "0.08" not in blob and "-0.04" not in blob


def test_the_two_digest_routes_answer_with_no_runs(client, db_session):
    _, pro = _as(db_session, "empty-pro", plan="pro")
    sid = _save(client, pro, word="TRADE").json()["id"]
    body = client.get(f"{URL}/{sid}/digest", headers=pro).json()
    assert set(body) >= {
        "comparable",
        "note",
        "current",
        "previous",
        "came_in",
        "dropped_out",
        "not_compared",
        "footer",
        "screen",
    }
    wl = client.get("/api/v1/me/watchlist/digest", headers=pro).json()
    assert set(wl) >= {"comparable", "came_in", "dropped_out", "footer"}
