# ruff: noqa: F811
"""Spec 3.3, 3.5, R3, C3, C5-C7: the Observatory API: owner-only, GET-only, bounded, read-only, honest."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from observatory_fixtures import (  # noqa: F401 — fixtures
    RUN_PREFIX,
    SYM_PREFIX,
    TOKEN_BASE,
    committed,
    committed_realistic_runs,
    make_decision,
    make_run,
    obs_ns,
)
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.brain import BrainModuleSetting, BrainTrack, FeatureSnapshot
from swing_trade_ml.db.models.market import Instrument
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import engine

OWNER = {"X-API-Key": "test-api-key"}
BASE = "/api/v1/brain/observatory"
THU = date(2026, 10, 15)
AS_OF = datetime(2026, 10, 15, 10, 20, tzinfo=UTC)  # 15:50 IST
A, B = f"{SYM_PREFIX}A", f"{SYM_PREFIX}B"
TRACE = [
    {"step": "perceive", "module_id": "M01", "status": "used", "reason": "", "ms": 5, "version": "1"},
    {
        "step": "reason",
        "module_id": "M06",
        "status": "shadow",
        "reason": "recorded, not used",
        "ms": 9,
        "version": "1",
    },
]

pytestmark = pytest.mark.usefixtures("obs_ns")


@pytest.fixture()
def now_after_deadline():
    from swing_trade_ml.api.v1.endpoints import brain_observatory as ep
    from swing_trade_ml.main import app

    app.dependency_overrides[ep.get_now] = lambda: datetime(2026, 10, 15, 18, 0, tzinfo=ep.IST)
    yield
    app.dependency_overrides.pop(ep.get_now, None)


def seed(**run_kw):
    run = make_run(
        "n1",
        as_of=AS_OF,
        modules={"M01": "on", "M06": "shadow"},
        trace=TRACE,
        context={"data_manifest": {"universe_count": 3}, "sectors": []},
        quality={"overall": {"score": 1.0, "fresh": True, "issues": []}, "stale": [B]},
        **run_kw,
    )
    return (
        run,
        make_decision("n1", A, word="TRADE", reasons=["Model score 70% clears 60%."]),
        make_decision(
            "n1",
            B,
            word="WAIT",
            reasons=["error: token=abc123"],
            downgraded_from="TRADE",
            downgrade_reason="Sector is weak.",
        ),
        make_decision("n1", A, kind="holding", word="HOLD"),
        FeatureSnapshot(
            symbol=A,
            bar_date=THU,
            feature_set_version="v1",
            run_id=f"{RUN_PREFIX}n1",
            close=100.0,
            atr_14=2.0,
            adv_inr_20=1e8,
            features={"rsi": 55},
        ),
    )


def test_non_owner_is_refused_on_every_route(client, db_session):
    user = User(username="obs-guest", hashed_password="x", is_active=True, is_superuser=False, plan="free")
    db_session.add(user)
    db_session.flush()
    guest = {"Authorization": f"Bearer {create_access_token(user.username, {'uid': user.id})}"}
    for path in (
        "/days?from=2026-10-15&to=2026-10-15",
        "/runs?date=2026-10-15",
        "/runs/x",
        "/runs/x/stocks",
        "/runs/x/stocks/1",
        "/learning?from=2026-10-15&to=2026-10-15",
        "/outcomes?from=2026-10-15&to=2026-10-15&category=practice",
        "/forward-gate",
        "/effectiveness",
        "/score-bands?from=2026-10-01&to=2026-10-15",
    ):
        assert client.get(BASE + path, headers=guest).status_code == 403, path


def test_only_get_routes_exist():
    from swing_trade_ml.api.v1.endpoints.brain_observatory import router

    assert {m for r in router.routes for m in r.methods} == {"GET"}


def test_range_over_92_days_is_refused(client):
    assert client.get(f"{BASE}/days?from=2026-01-01&to=2026-04-04", headers=OWNER).status_code == 422
    assert client.get(f"{BASE}/days?from=2026-10-15&to=2026-10-14", headers=OWNER).status_code == 422
    assert (
        client.get(f"{BASE}/outcomes?from=2026-10-15&to=2026-10-15&category=bogus", headers=OWNER).status_code
        == 422
    )


def test_run_detail_recording_card_and_health(client, now_after_deadline):
    with committed(*seed()):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1", headers=OWNER).json()
    assert body["recording"]["card"] == "Existing records only — partial visibility."
    assert "decision path" in " ".join(body["recording"]["not_recorded"]).lower()
    m06 = next(r for r in body["modules"] if r["module_id"] == "M06")
    assert m06["flags"]["executed"] and not m06["flags"]["used"]
    assert body["counts"]["used"] == 1 and body["counts"]["shadow"] == 1
    assert body["universe_relation"] == {
        "state": "within_range",
        "universe": 3,
        "ideas": 2,
        "holdings": 1,
        "allowed": [2, 3],
    }
    assert body["headline"] == "completed"  # both listed modules ran; the rest were not installed then


def test_a_listed_module_missing_from_the_step_log_is_degraded(client):
    run = make_run("dg", as_of=AS_OF, modules={"M01": "on", "M08": "on"}, trace=TRACE[:1])
    with committed(run):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}dg", headers=OWNER).json()
    m08 = next(r for r in body["modules"] if r["module_id"] == "M08")
    assert m08["flags"]["not_observed"] and m08["inferred"]["not_observed"]
    assert body["headline"] == "degraded"


def test_a_running_run_shows_its_status_and_keeps_recorded_modules(client):
    with committed(*seed(status="running")):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1", headers=OWNER).json()
    assert body["headline"] == "running"
    assert next(r for r in body["modules"] if r["module_id"] == "M01")["flags"]["executed"]
    assert next(o for o in body["outside_steps"] if o["module_id"] == "M00")["state"] == "in_progress"


def test_stock_detail_is_honest_and_redacted(client):
    with committed(*seed()):
        listing = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol={B}", headers=OWNER).json()
        did = listing["items"][0]["id"]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).json()
    assert "abc123" not in str(body["decision"]["reasons"])
    assert body["redacted_fields"] == ["decision.reasons[0]"]
    assert body["decision"]["downgraded_from"] == "TRADE"
    assert body["influence"]["text"] == "Influence on this stock: Not recorded in Phase 1A."
    assert (
        body["not_recorded"]["decision_path"]
        == "Not recorded — decision-path recording deferred during trial"
    )
    assert body["not_recorded"]["opinions"] == "Not recorded in Phase 1A"
    assert body["stale"]["listed_stale"] is True
    assert body["features"]["state"] == "not_observed"  # the snapshot belongs to A, not B


def test_symbol_as_idea_and_holding_lists_both(client):
    with committed(*seed()):
        items = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol={A}", headers=OWNER).json()["items"]
    assert sorted(i["kind"] for i in items) == ["holding", "idea"]


def test_foreign_decision_id_is_404(client):
    other = make_run("n2", as_of=AS_OF)
    with committed(*seed(), other, make_decision("n2", f"{SYM_PREFIX}C")):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}n2/stocks", headers=OWNER).json()["items"][0]["id"]
        assert client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).status_code == 404
    assert client.get(f"{BASE}/runs/{RUN_PREFIX}missing", headers=OWNER).status_code == 404


def test_paging_cursor_is_typed_and_stable(client):
    with committed(*seed()):
        p1 = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?limit=2", headers=OWNER).json()
        assert isinstance(p1["next_cursor"]["after_id"], int)
        p2 = client.get(
            f"{BASE}/runs/{RUN_PREFIX}n1/stocks?limit=2&after_id={p1['next_cursor']['after_id']}",
            headers=OWNER,
        ).json()
    assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None


def test_cursor_pages_runs_with_equal_start_times(client, now_after_deadline):
    rows = [make_run(f"p{i}", as_of=AS_OF, kind="intraday", started_at=AS_OF) for i in range(3)]
    with committed(*rows):
        seen, cursor = [], None
        for _ in range(5):
            q = f"{BASE}/runs?date=2026-10-15&limit=1"
            if cursor:
                q += f"&after_started_at={cursor['after_started_at']}&after_id={cursor['after_id']}"
            body = client.get(q.replace("+", "%2B"), headers=OWNER).json()
            seen += [i["id"] for i in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                break
    assert len(seen) == 3 and len(set(seen)) == 3


def test_nightly_state_is_for_the_whole_day_not_the_page(client, now_after_deadline):
    early = make_run("i0", as_of=AS_OF, kind="intraday", started_at=AS_OF - timedelta(hours=6))
    nightly = make_run("n9", as_of=AS_OF, started_at=AS_OF)
    with committed(early, nightly):
        body = client.get(f"{BASE}/runs?date=2026-10-15&limit=1", headers=OWNER).json()
    assert [i["kind"] for i in body["items"]] == ["intraday"]
    assert body["nightly"]["state"] == "observed"


def test_days_counts_and_missing_runs(client, now_after_deadline):
    with committed(*seed()):
        days = client.get(f"{BASE}/days?from=2026-10-14&to=2026-10-17", headers=OWNER).json()["days"]
    by = {d["day"]: d for d in days}
    assert by["2026-10-15"]["nightly"]["state"] == "observed"
    assert by["2026-10-15"]["counts"]["ideas_total"] == 2 and by["2026-10-15"]["universe"] == 3
    assert by["2026-10-14"]["nightly"]["state"] == "not_observed"
    assert by["2026-10-17"]["nightly"]["state"] == "not_applicable"  # Saturday
    assert by["2026-10-15"]["signals"]["label"] == "not linked to a specific run"
    assert by["2026-10-15"]["signals"]["by_mode"] == {}


def test_day_with_no_runs(client, now_after_deadline):
    r = client.get(f"{BASE}/runs?date=2026-10-17", headers=OWNER)
    assert (
        r.status_code == 200 and r.json()["items"] == [] and r.json()["nightly"]["state"] == "not_applicable"
    )


def test_old_run_without_context(client):
    with committed(make_run("old", as_of=AS_OF, context=None, modules={}, trace=[])):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}old", headers=OWNER).json()
    assert body["universe_relation"]["state"] == "not_observed"
    assert body["sectors"]["state"] == "not_observed"
    assert all(m["flags"]["unknown"] for m in body["modules"] if not m["flags"]["not_applicable"])


def test_failed_run_error_is_redacted(client):
    err = "OperationalError postgresql://u:pw123@db/x"
    with committed(make_run("bad", as_of=AS_OF, status="failed", error=err)):
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}bad", headers=OWNER).json()
    assert body["headline"] == "failed" and "pw123" not in body["run"]["error"]
    assert "run.error" in body["redacted_fields"]


def test_symbol_on_two_exchanges(client):
    rows = (
        *seed(),
        Instrument(instrument_token=TOKEN_BASE + 1, tradingsymbol=A, exchange="NSE"),
        Instrument(instrument_token=TOKEN_BASE + 2, tradingsymbol=A, exchange="BSE"),
    )
    with committed(*rows):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks?symbol={A}", headers=OWNER).json()["items"][0][
            "id"
        ]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}n1/stocks/{did}", headers=OWNER).json()
    assert sorted(i["exchange"] for i in body["instrument"]["current"]) == ["BSE", "NSE"]
    assert body["instrument"]["label"].startswith("current instrument master")


def test_tracker_rows_follow_the_run_book(client):
    sym = f"{SYM_PREFIX}H"
    run = make_run("t1", as_of=AS_OF, modules={"M15": "on"})
    holding = make_decision("t1", sym, kind="holding", word="HOLD")
    paper_row = BrainTrack(
        book="paper",
        symbol=sym,
        opened_on=date(2026, 10, 1),
        day=THU,
        day_n=10,
        ret=0.02,
        status="on_track",
        reason="",
        stop=None,
        band=[],
    )
    live_row = BrainTrack(
        book="live",
        symbol=sym,
        opened_on=date(2026, 10, 1),
        day=THU,
        day_n=10,
        ret=-0.03,
        status="watch",
        reason="",
        stop=None,
        band=[],
    )
    with committed(run, holding, paper_row, live_row):
        did = client.get(f"{BASE}/runs/{RUN_PREFIX}t1/stocks", headers=OWNER).json()["items"][0]["id"]
        body = client.get(f"{BASE}/runs/{RUN_PREFIX}t1/stocks/{did}", headers=OWNER).json()
        day = client.get(f"{BASE}/days?from=2026-10-15&to=2026-10-15", headers=OWNER).json()["days"][0]
    assert [r["ret"] for r in body["tracker"]["rows"]] == [0.02]
    assert body["tracker"]["book"] == "paper"
    assert day["tracked"]["by_book"] == {"paper": 1, "live": 1}


def test_effectiveness_route(client):
    body = client.get(f"{BASE}/effectiveness", headers=OWNER).json()
    claims = {c["claim"]: c for c in body["claims"]}
    assert claims["model_ranking_predictive"]["word"] == "Not proven"
    assert claims["full_brain"]["word"] == "No frozen protocol yet"
    assert body["rejected_entries"] == []


def test_forward_gate_route_uses_the_trial_cohort_not_a_range(client, now_after_deadline):
    body = client.get(f"{BASE}/forward-gate", headers=OWNER).json()
    assert body["cohort_from"] == "2026-10-14" and body["cohort_to"] == "2026-10-15"
    assert body["word"] == "Insufficient evidence"


def test_learning_route_keeps_three_numbers_apart(client):
    body = client.get(f"{BASE}/learning?from=2026-10-01&to=2026-10-15", headers=OWNER).json()
    assert {"results_collected", "changes_proposed", "learning_checks", "proven_improvement"} <= set(body)
    assert body["proven_improvement"]["word"] == "No frozen protocol yet"


def test_days_over_92_days_counts_everything(client, now_after_deadline, committed_realistic_runs):
    c = committed_realistic_runs
    body = client.get(f"{BASE}/days?from={c.start}&to={c.end}", headers=OWNER).json()
    assert sum(d["intraday"].get("recorded", 0) for d in body["days"]) == c.intraday_total
    assert sum((d["counts"] or {}).get("ideas_total", 0) for d in body["days"]) == c.ideas_total


def test_statement_count_is_bounded(client, now_after_deadline):
    counter = {"n": 0}

    def count(*_a, **_k):
        counter["n"] += 1

    with committed(*seed()):
        event.listen(engine, "before_cursor_execute", count)
        try:
            for path in (
                f"/runs/{RUN_PREFIX}n1",
                f"/runs/{RUN_PREFIX}n1/stocks",
                f"/runs/{RUN_PREFIX}n1/stocks/1",
                "/days?from=2026-08-01&to=2026-10-31",
                "/runs?date=2026-10-15",
                "/effectiveness",
                "/learning?from=2026-08-01&to=2026-10-31",
            ):
                counter["n"] = 0
                client.get(BASE + path, headers=OWNER)
                assert counter["n"] <= 12, (path, counter["n"])
        finally:
            event.remove(engine, "before_cursor_execute", count)


def test_a_write_attempt_through_a_route_is_refused(client, monkeypatch):
    from swing_trade_ml.services.brain_observatory import queries

    def sneaky(db, *a, **k):
        db.execute(text("INSERT INTO brain_modules (module_id, mode) VALUES ('OBSR', 'on')"))
        return []

    monkeypatch.setattr(queries, "runs_on", sneaky)
    with pytest.raises(DBAPIError, match="read-only"):
        client.get(f"{BASE}/runs?date=2026-10-15", headers=OWNER)
    with Session(engine) as check:
        assert check.get(BrainModuleSetting, "OBSR") is None


# --- review finding 1 through the API: no counts for a run that did not finish ----------------------


def test_a_failed_nightly_shows_failed_and_no_zero_counts(client, now_after_deadline):
    with committed(make_run("fl", as_of=AS_OF, status="failed", error="boom")):
        day = client.get(f"{BASE}/days?from=2026-10-15&to=2026-10-15", headers=OWNER).json()["days"][0]
        page = client.get(f"{BASE}/runs?date=2026-10-15", headers=OWNER).json()
    assert day["nightly"]["state"] == "failed"
    assert day["counts"] is None and day["universe"] is None  # missing is not zero
    assert page["nightly"]["state"] == "failed"


def test_a_done_run_beside_a_failed_one_keeps_its_counts(client, now_after_deadline):
    failed = make_run("fl2", as_of=AS_OF, status="failed", started_at=AS_OF - timedelta(minutes=30))
    with committed(*seed(), failed):
        day = client.get(f"{BASE}/days?from=2026-10-15&to=2026-10-15", headers=OWNER).json()["days"][0]
    assert day["nightly"]["state"] == "observed" and day["counts"]["ideas_total"] == 2
    assert [r["id"] for r in day["other_runs"]] == [f"{RUN_PREFIX}fl2"]


# --- review finding 4: the learning count is one book, live runs only -------------------------------


def test_learning_counts_only_live_runs_of_the_paper_book(client):
    from swing_trade_ml.db.models.brain import BrainRun  # noqa: F401

    live_paper = make_run("lp", as_of=AS_OF)
    replay = make_run("rp", as_of=AS_OF, live=False)
    live_book = make_run("lb", as_of=AS_OF, book="live")
    graded = {"outcome": "target", "outcome_return": 0.08, "resolved_on": THU}
    rows = (
        live_paper,
        make_decision("lp", f"{SYM_PREFIX}L1", **graded),
        replay,
        make_decision("rp", f"{SYM_PREFIX}L2", **graded),
        live_book,
        make_decision("lb", f"{SYM_PREFIX}L3", **graded),
    )
    with committed(*rows):
        body = client.get(f"{BASE}/learning?from=2026-10-15&to=2026-10-15", headers=OWNER).json()
    assert body["results_collected"] == 1
    assert "live runs of the paper book" in body["results_collected_label"]
