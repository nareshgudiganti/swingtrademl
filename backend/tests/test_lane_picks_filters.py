"""Horizon picks filters: date, horizon and cap run in SQL, the summary equals a hand count (#322 slice 3a).

`signal_day` is the Indian session date of the pick, so `from` and `to` are plain dates, both ends inclusive,
with no timestamp conversion. The unfiltered response is frozen in tests/snapshots/lane_picks_unfiltered.json
(written before the filters were added); regenerate only on purpose with LANE_PICKS_SNAPSHOT_UPDATE=1.

Totals against the outcome ledger are step 3b (after #263 merges). Where this route differs from the
ledger, the differences are listed in test_known_differences_from_the_ledger_for_step_3b, with this
route's definitions unchanged.
"""

from __future__ import annotations

import json
import os
from datetime import date
from itertools import count
from pathlib import Path

import pytest

from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.lanes import H05Run, H05Signal
from swing_trade_ml.db.models.session import User
from swing_trade_ml.shadow_lanes import lane_review

_NAMES = count()
URL = "/api/v1/research/lane-picks"
SNAPSHOT = Path(__file__).parent / "snapshots" / "lane_picks_unfiltered.json"
D2, D3, D4, D5 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)

# (symbol, day, group, rank, selected, trade_status, net_return): the fixture and the hand count's source.
PICKS = [
    ("AAA", D2, "large", 1, True, "hit", 0.02),
    ("BBB", D3, "large", 1, True, "stopped", -0.04),
    ("CCC", D3, "mid", 1, True, None, None),
    ("DDD", D3, "small", 1, True, "expired", 0.01),
    ("NOTPICKED", D3, "mid", 9, False, None, None),
    ("EEE", D4, "mid", 1, True, "hit", 0.03),
    ("FFF", D4, "large", 1, True, "pending", None),
    ("GGG", D5, "small", 1, True, "stopped", -0.02),
]


def owner(db):
    u = User(
        username=f"lpf-owner-{next(_NAMES)}",
        hashed_password="x",
        is_active=True,
        is_superuser=True,
        plan="pro",
        role="owner",
    )
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


@pytest.fixture()
def seeded(db_session):
    run = H05Run(
        run_no=1,
        protocol_code="T",
        protocol_hash="0" * 64,
        status="active",
        start_day=D2,
        end_day=date(2027, 1, 28),
        models={},
        universe={},
        universe_hash="0" * 64,
    )
    db_session.add(run)
    db_session.flush()
    for symbol, day, group, rank, selected, status, net in PICKS:
        db_session.add(
            H05Signal(
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
                trade_status=status,
                net_return=net,
                entry_fill=100.0 if status else None,
            )
        )
    db_session.flush()
    return db_session

REVIEW_FLOOR = lane_review.CHECKPOINTS[0]  # the lane review's first reading: 60 finished picks


def hand_count(day_from=None, day_to=None, cap=None):
    """The summary worked out from PICKS alone, by the definitions the route has always used."""
    rows = [
        p
        for p in PICKS
        if p[4]
        and (day_from is None or p[1] >= day_from)
        and (day_to is None or p[1] <= day_to)
        and (cap is None or p[2] == cap)
    ]
    finished = [p for p in rows if p[5] not in (None, "pending") and p[6] is not None]
    wins = [p for p in finished if p[6] > 0]
    return {
        "picks": len(rows),
        "finished": len(finished),
        "open": len(rows) - len(finished),
        "wins": len(wins),
        # below the review floor (60 finished picks) no average is shown (#474)
        "mean_net_return": (
            (sum(p[6] for p in finished) / len(finished)) if len(finished) >= REVIEW_FLOOR else None
        ),
        "symbols": sorted(p[0] for p in rows),
    }


def seen(response):
    s = response["summary"]
    return {**s, "symbols": sorted(r["symbol"] for r in response["rows"])}


# ---------------------------------------------------------------------------------------------- (a) unchanged


def test_unfiltered_response_is_identical_to_what_main_returned(client, seeded):
    now = json.loads(json.dumps(client.get(URL, headers=owner(seeded)).json(), sort_keys=True))
    if os.environ.get("LANE_PICKS_SNAPSHOT_UPDATE") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert SNAPSHOT.exists(), (
        "snapshot missing: generate it with LANE_PICKS_SNAPSHOT_UPDATE=1 before changing the route"
    )
    assert now == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


# -------------------------------------------------------------------------- (a) the filters, in SQL

WINDOWS = [
    (None, None, None),
    (D3, None, None),
    (None, D3, None),
    (D3, D4, None),
    (D4, D4, None),  # both ends inclusive, one day
    (D2, D5, "mid"),
    (None, None, "small"),
    (D3, D3, "large"),
    (D5, D5, "large"),  # a day with picks, none of this size
    (date(2030, 1, 1), None, None),  # after every pick
]


def ask(client, db, day_from=None, day_to=None, cap=None, horizon=None):
    params = {}
    if day_from:
        params["from"] = day_from.isoformat()
    if day_to:
        params["to"] = day_to.isoformat()
    if cap:
        params["cap"] = cap
    if horizon:
        params["horizon"] = horizon
    return client.get(URL, params=params, headers=owner(db))


@pytest.mark.parametrize(("day_from", "day_to", "cap"), WINDOWS)
def test_the_filtered_rows_and_summary_equal_a_hand_count(client, seeded, day_from, day_to, cap):
    out = ask(client, seeded, day_from, day_to, cap).json()
    want = hand_count(day_from, day_to, cap)
    got = seen(out)
    assert got["symbols"] == want["symbols"]
    assert {k: got[k] for k in ("picks", "finished", "open", "wins")} == {
        k: want[k] for k in ("picks", "finished", "open", "wins")
    }
    assert (
        got["mean_net_return"] == pytest.approx(want["mean_net_return"])
        if want["mean_net_return"] is not None
        else (got["mean_net_return"] is None)
    )


def test_both_ends_are_inclusive_and_the_unselected_pick_never_counts(client, seeded):
    out = ask(client, seeded, D3, D3).json()
    assert sorted(r["symbol"] for r in out["rows"]) == ["BBB", "CCC", "DDD"]  # NOTPICKED is on D3 too


def test_the_horizon_filter_keeps_the_only_lane_and_empties_any_other(client, seeded):
    assert seen(ask(client, seeded, horizon=5).json()) == seen(ask(client, seeded).json())
    out = ask(client, seeded, horizon=10).json()
    assert out["rows"] == [] and out["summary"]["picks"] == 0 and out["summary"]["mean_net_return"] is None


def test_to_before_from_is_refused_and_one_day_is_fine(client, seeded):
    own = owner(seeded)
    r = client.get(URL, params={"from": "2026-11-05", "to": "2026-11-04"}, headers=own)
    assert r.status_code == 422 and "to" in r.text.lower()
    assert client.get(URL, params={"from": "2026-11-04", "to": "2026-11-04"}, headers=own).status_code == 200
    assert client.get(URL, params={"from": "not-a-date"}, headers=own).status_code == 422


def test_the_filtered_route_is_still_owner_only(client, seeded):
    params = {"from": "2026-11-03", "to": "2026-11-04", "cap": "mid"}
    assert client.get(URL, params=params).status_code in (401, 403)
    for role in ("member", "tester"):
        u = User(username=f"lpf-{role}", hashed_password="x", is_active=True, plan="pro", role=role)
        seeded.add(u)
        seeded.flush()
        h = {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}
        assert client.get(URL, params=params, headers=h).status_code == 403, role


def test_the_date_cap_and_horizon_filters_run_in_sql(client, seeded):
    from test_report_sql_filters import sql_of, watching  # sibling import: row load counter and SQL recorder

    own = owner(seeded)
    with watching(seeded, H05Signal) as (loaded, statements):
        client.get(URL, params={"from": "2026-11-03", "to": "2026-11-04", "cap": "mid"}, headers=own)
    # mid picks on 3 and 4 Nov: CCC and EEE. The row not selected, and every other row, stays in the database.
    assert loaded["H05Signal"] == 2
    where = " ".join(sql_of(statements, "h05_signals"))
    assert "signal_day >=" in where and "signal_day <=" in where and '"group" =' in where
    with watching(seeded, H05Signal) as (loaded, statements):
        client.get(URL, params={"horizon": 10}, headers=own)
    assert loaded["H05Signal"] == 0 and not sql_of(
        statements, "h05_signals"
    )  # no 10-day lane: nothing to read


# ------------------------------------------------------------------- (d) differences listed for step 3b


def test_known_differences_from_the_ledger_for_step_3b(client, seeded):
    """Not changed here; listed for the ledger comparison (#263, step 3b). This route's own definitions:
    1. a repeat pick the lane blocked (selected, `repeat_blocked`) is COUNTED here; the ledger lists it as
       `blocked` and does not count it;
    2. "wins" is `net_return > 0` of the shadow trade; the ledger's `passed` is the close of session 5
       reaching +2%, a different question, so a pick can be a win here and not passed there;
    3. "open" is a trade with no status or `pending`; the ledger splits what is not completed into
       immature, missing and blocked;
    4. the horizon is always 5 here; the ledger has no horizon field."""
    run = seeded.query(H05Run).one()
    seeded.add(
        H05Signal(
            run_id=run.id,
            signal_day=D5,
            symbol="REPEAT",
            group="large",
            status="scored",
            score=0.7,
            group_rank=2,
            selected=True,
            model_id=2,
            model_version="v2",
            trade_status="hit",
            net_return=0.05,
            entry_fill=100.0,
            repeat_blocked=True,
        )
    )
    seeded.add(
        H05Signal(
            run_id=run.id,
            signal_day=D5,
            symbol="MISSED5",
            group="large",
            status="scored",
            score=0.7,
            group_rank=3,
            selected=True,
            model_id=2,
            model_version="v2",
            trade_status="hit",
            net_return=0.01,
            entry_fill=100.0,
            label_status="matured",
            label_hit=0,
        )
    )
    seeded.flush()
    out = ask(client, seeded, D5, D5, "large").json()
    assert [r["symbol"] for r in out["rows"]] == [
        "REPEAT",
        "MISSED5",
    ]  # 1: the blocked pick is listed and counted
    assert (
        out["summary"]["picks"] == 2 and out["summary"]["wins"] == 2
    )  # 2: net_return > 0, whatever label_hit says
    assert all(r["horizon_days"] == 5 for r in out["rows"])  # 4
