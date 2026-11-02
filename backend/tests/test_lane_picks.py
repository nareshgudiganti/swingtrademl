"""Horizon picks: owner-only, read-only, selected picks only, honest status, isolated from money and brain."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from swing_trade_ml.api.v1.endpoints import lane_picks
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.lanes import H05Run, H05Signal
from swing_trade_ml.db.models.session import User

URL = "/api/v1/research/lane-picks"


def headers(db, role):
    u = User(
        username=f"lp-{role}",
        hashed_password="x",
        is_active=True,
        is_superuser=role == "owner",
        plan="pro",
        role=role,
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


def sig(run, day, symbol, group, rank, selected=True, **kw):
    return H05Signal(
        run_id=run.id,
        signal_day=day,
        symbol=symbol,
        group=group,
        status="scored",
        score=0.7,
        group_rank=rank,
        selected=selected,
        model_id=2,
        model_version="v2",
        **kw,
    )


@pytest.fixture()
def seeded(db_session):
    run = H05Run(
        run_no=1,
        protocol_code="T",
        protocol_hash="0" * 64,
        status="active",
        start_day=date(2026, 11, 2),
        end_day=date(2027, 1, 28),
        models={},
        universe={},
        universe_hash="0" * 64,
    )
    db_session.add(run)
    db_session.flush()
    d = date(2026, 11, 3)
    db_session.add_all(
        [
            sig(run, d, "AAA", "large", 1, trade_status="hit", net_return=0.02, entry_fill=100.0),
            sig(run, d, "BBB", "large", 2, trade_status="stopped", net_return=-0.04, entry_fill=50.0),
            sig(run, d, "CCC", "mid", 1),
            sig(run, d, "NOTPICKED", "mid", 9, selected=False),
        ]
    )
    db_session.flush()
    return db_session


def test_only_the_owner_gets_in(client, seeded):
    assert client.get(URL).status_code in (401, 403)
    for role in ("member", "tester"):
        assert client.get(URL, headers=headers(seeded, role)).status_code == 403, role


def test_shows_only_selected_picks_with_tags(client, seeded):
    out = client.get(URL, headers=headers(seeded, "owner")).json()
    assert {r["symbol"] for r in out["rows"]} == {"AAA", "BBB", "CCC"}
    assert all(r["horizon_days"] == 5 for r in out["rows"])
    by = {r["symbol"]: r for r in out["rows"]}
    assert by["AAA"]["cap_label"] == "Large cap" and by["CCC"]["cap_label"] == "Mid cap"
    assert "not advice" in out["note"].lower()


def test_pending_pick_is_open_and_has_no_result(client, seeded):
    by = {r["symbol"]: r for r in client.get(URL, headers=headers(seeded, "owner")).json()["rows"]}
    assert by["CCC"]["status"] == "open" and by["CCC"]["net_return"] is None
    assert by["AAA"]["status"] == "hit" and by["BBB"]["status"] == "stopped"


def test_summary_counts_only_finished_trades(client, seeded):
    s = client.get(URL, headers=headers(seeded, "owner")).json()["summary"]
    assert (s["picks"], s["finished"], s["open"], s["wins"]) == (3, 2, 1, 1)
    assert s["mean_net_return"] == pytest.approx((0.02 - 0.04) / 2)


def test_filters_by_cap_and_horizon(client, seeded):
    own = headers(seeded, "owner")
    mid = client.get(URL, params={"cap": "mid"}, headers=own).json()
    assert [r["symbol"] for r in mid["rows"]] == ["CCC"]
    none = client.get(URL, params={"horizon": 10}, headers=own).json()
    assert none["rows"] == [] and none["summary"]["picks"] == 0 and none["summary"]["mean_net_return"] is None
    assert client.get(URL, params={"cap": "huge"}, headers=own).status_code == 422


def test_reading_changes_nothing(client, seeded):
    own = headers(seeded, "owner")
    before = seeded.scalar(select(func.count()).select_from(H05Signal))
    client.get(URL, headers=own)
    assert seeded.scalar(select(func.count()).select_from(H05Signal)) == before


def test_endpoint_is_get_only_and_isolated_from_money_and_brain():
    assert [list(r.methods) for r in lane_picks.router.routes] == [["GET"]]
    tree = ast.parse(Path(lane_picks.__file__).read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    banned = ("brain", "brokers", "services.execution", "services.risk", "workers", "db.models.trading")
    assert not [m for m in imported if any(b in m for b in banned)], imported
