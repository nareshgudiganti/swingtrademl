"""The blind trial's seal (services/trial_seal.py; evidence plan amendment 1, A4).

Brain ideas from the trial's days are seeded with distinctive results (+7.77% at target, best +73.16492%,
worst -2.33%; 1.94 R). Then EVERY GET route of the app is called as the owner, plus the reports and the
daily check, and none of those numbers may appear in any format. The same rows on a day before the trial
must still show them (nothing over-sealed), and the go-live gate's real decision is unchanged.

Routes that need an outside service, or that run the brain instead of reading, are skipped by name below.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from brain_m18_fixtures import brain_strategy
from swing_trade_ml.core.enums import SignalType
from swing_trade_ml.db.models.brain import BrainDailyCheck, BrainDecision, BrainProposal, BrainRun
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.trading import Signal
from swing_trade_ml.services import brain_daily_check as daily
from swing_trade_ml.services import trial_seal
from swing_trade_ml.services.brain_golive import stage

API_KEY = {"X-API-Key": "test-api-key"}
IST = ZoneInfo("Asia/Kolkata")
SEALED_DAY = date(2026, 10, 15)  # a trial day (TRIAL_START is 2026-10-14)
OPEN_DAY = date(2026, 10, 9)  # a Friday before the trial
NOW = datetime(2026, 10, 28, 18, 0, tzinfo=IST)
# BEST is a number that appears nowhere else in the app (evidence amendment 1, A4: "plant a distinctive
# result"); RETURN and WORST are realistic results so the gate and the reports really compute with them.
RETURN, BEST, WORST = 0.0777, 0.7316492, -0.0233
# Every way those numbers could be written: raw, as a percentage, rounded, signed, in R (0.0777 / 0.04).
LEAKS = (
    "0.0777", "7.77", "7.8%", "+7.8", "0.078", "0.7316", "73.16", "73.2%", "0.0233", "2.33", "2.3%", "1.94",
)  # fmt: skip

# Skipped, by name, with why. Everything else is called.
SKIPPED = {
    "/api/v1/auth/kite/login": "redirects to Zerodha (outside service)",
    "/api/v1/auth/kite/callback": "Zerodha login callback (outside service)",
    "/api/v1/auth/kite/session": "Zerodha session (outside service)",
    "/api/v1/auth/google/login": "redirects to Google (outside service)",
    "/api/v1/auth/google/callback": "Google login callback (outside service)",
    "/api/v1/market-data/quote/{symbol}": "live quote from Kite (outside service)",
    "/api/v1/market-data/ltp": "live prices from Kite (outside service)",
    "/api/v1/portfolio/real/quote": "live quote from Kite (outside service)",
    "/api/v1/portfolio/real/account": "real Zerodha account (outside service)",
    "/api/v1/portfolio/real/orders-status": "real Zerodha orders (outside service)",
    "/api/v1/mutual-funds/search": "mutual fund search API (outside service)",
    "/api/v1/mutual-funds/{scheme_id}/history": "mutual fund NAV API (outside service)",
    "/api/v1/ml/backup/models.zip": "model files download (binary, no brain results)",
    "/api/v1/brain/why/{symbol}": "runs the whole brain and stores a run; its answer has no outcome fields",
}
QUERY = {
    "from": "2026-10-01",
    "to": "2026-10-31",
    "date": SEALED_DAY.isoformat(),
    "month": "2026-10",
    "category": "practice",
    "horizon_days": "15",
    "symbol": "SEALX",
    "symbols": "SEALX",
    "q": "SEALX",
}
EXTRA = (  # the same routes again with the parameters that reach the sealed rows
    "/api/v1/brain/compare?since=2026-10-01",
    "/api/v1/brain/learning?since=2026-10-01",
    "/api/v1/brain/trial-journal?from=2026-10-14&to=2026-11-15",
    "/api/v1/brain/trial-journal?from=2026-09-20&to=2026-11-15",
    "/api/v1/brain/observatory/outcomes?from=2026-10-14&to=2026-10-31&category=practice",
    "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-31&category=backtest",
    "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-31&category=paper",
    "/api/v1/brain/observatory/score-bands?from=2026-10-14&to=2026-10-31",
    "/api/v1/brain/observatory/learning?from=2026-10-14&to=2026-10-31",
    "/api/v1/ml/calibration?source=signals",
    "/api/v1/ml/calibration?source=signals&mode=paper",
    "/api/v1/ml/calibration?source=predictions",
    "/api/v1/brain/runs/latest?kind=nightly",
    "/api/v1/brain/runs/latest?include_replays=true",
    "/api/v1/brain/proposals?status=open",
    "/api/v1/brain/daily-checks?days=366",
    "/api/v1/beginner/insights?period=day",
    "/api/v1/beginner/insights?period=week",
)


@pytest.fixture(autouse=True)
def _brain_on(monkeypatch):
    from swing_trade_ml.core.config import settings

    monkeypatch.setattr(settings, "BRAIN_ENABLED", True)


@pytest.fixture()
def obs_client(client, db_session):
    """The Observatory reads through its own read-only session: point it at the test transaction."""
    from swing_trade_ml.api.v1.endpoints import brain_observatory as ep
    from swing_trade_ml.main import app
    from swing_trade_ml.services.brain_observatory.db import get_readonly_db

    app.dependency_overrides[get_readonly_db] = lambda: db_session
    app.dependency_overrides[ep.get_now] = lambda: NOW
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_readonly_db, None)
        app.dependency_overrides.pop(ep.get_now, None)


def _ist(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST).astimezone(UTC)


def _seed(db, day: date) -> dict:
    """One live nightly brain run on `day` with a finished TRADE idea, the brain strategy's matching
    Signal, a learning proposal made that day, and prices that rise Rs 2 a day around it."""
    inst = Instrument(
        instrument_token=771_177, tradingsymbol="SEALX", name="Seal X", exchange="NSE", is_watchlisted=True
    )
    db.add(inst)
    db.flush()
    price, d = 100.0, day - timedelta(days=45)
    while d <= day + timedelta(days=45):
        if d.weekday() < 5:
            db.add(
                Candle(
                    instrument_id=inst.id,
                    interval="day",
                    ts=datetime.combine(d, time(0, 0), tzinfo=IST),
                    open=price,
                    high=price + 3,
                    low=price - 1,
                    close=price + 2,
                    volume=100_000,
                )
            )
            price += 2  # whole rupees, so no price can look like a sealed result
        d += timedelta(days=1)
    run_id = f"seal-run-{day.isoformat()}"
    db.add(
        BrainRun(
            id=run_id,
            kind="nightly",
            live=True,
            status="done",
            book="paper",
            as_of=_ist(day, 16, 30),
            started_at=_ist(day, 16, 30),
            banner_mode="NORMAL",
        )
    )
    db.flush()
    dec = BrainDecision(
        run_id=run_id,
        symbol="SEALX",
        kind="idea",
        word="TRADE",
        confidence=0.85,
        score_source="model",
        stop=96.0,
        target=108.0,
        horizon_days=15,
        reasons=["Strong trend with room to the target."],
        outcome="target",
        outcome_return=RETURN,
        outcome_days=7,
        max_up=BEST,
        max_down=WORST,
        resolved_on=day + timedelta(days=9),
    )
    db.add(dec)
    strategy = brain_strategy(db, name="seal-brain", symbols=["SEALX"])
    db.add(
        Signal(
            strategy_id=strategy.id,
            instrument_id=inst.id,
            signal_type=SignalType.BUY,
            mode="paper",
            price=100.0,
            confidence=0.6,
            suggested_quantity=12,
            stop_loss=96.0,
            take_profit=108.0,
            horizon_days=15,
            reason="r",
            features={},
            advisory_only=True,
            outcome="TARGET_HIT",
            outcome_pct=RETURN,
            outcome_at=_ist(day + timedelta(days=9), 15, 30),
            generated_at=_ist(day, 16, 35),
        )
    )
    db.add(
        BrainProposal(
            kind="buy_level",
            title="Raise the buy level to 65%",
            evidence=f"Among 40 past ideas scored 65% or more, the average was +{RETURN / 0.04:.2f} R.",
            change={"buy_level": 0.65},
            created_at=_ist(day, 20, 0),
        )
    )
    db.flush()
    return {"run_id": run_id, "decision_id": dec.id, "strategy_id": strategy.id}


def _get_routes(app) -> list[str]:
    return [p for p, ops in app.openapi()["paths"].items() if "get" in ops]


def _fill(path: str, ids: dict, spec: dict) -> str | None:
    params = {p["name"]: p for p in spec["paths"][path]["get"].get("parameters", [])}
    out = path
    for name in re.findall(r"{(\w+)}", path):
        value = {
            "run_id": ids["run_id"],
            "decision_id": ids["decision_id"],
            "strategy_id": ids["strategy_id"],
            "symbol": "SEALX",
        }.get(name, "1")
        out = out.replace("{" + name + "}", str(value))
    query = []
    for name, p in params.items():
        if p["in"] == "query" and p.get("required"):
            if name not in QUERY:
                return None
            query.append(f"{name}={QUERY[name]}")
    return out + ("?" + "&".join(query) if query else "")


def _call_everything(obs_client, ids: dict) -> dict[str, str]:
    from swing_trade_ml.main import app

    spec = app.openapi()
    bodies: dict[str, str] = {}
    unfilled = []
    for path in _get_routes(app):
        if path in SKIPPED:
            continue
        url = _fill(path, ids, spec)
        if url is None:
            unfilled.append(path)
            continue
        r = obs_client.get(url, headers=API_KEY, follow_redirects=False)
        assert r.status_code < 500, (url, r.status_code, r.text[:300])
        bodies[url] = r.text
    for url in EXTRA:
        r = obs_client.get(url, headers=API_KEY)
        assert r.status_code < 500, (url, r.status_code, r.text[:300])
        bodies[url] = r.text
    assert unfilled == [], f"routes with a required parameter this test does not fill: {unfilled}"
    return bodies


CLOCK = re.compile(r"\d{2}:\d{2}:\d{2}(\.\d+)?")  # times of day: "10:20:17.771" is not a result


def _leaks(text: str) -> list[str]:
    text = CLOCK.sub("", text)
    return [x for x in LEAKS if x in text]


def _daily_check_texts(db_session, client, tmp_path, day: date) -> dict[str, str]:
    now = datetime.combine(day + timedelta(days=1), time(16, 20), tzinfo=IST)
    result = daily.compute(db_session, now, backup_dir=str(tmp_path))
    daily.store(db_session, result)
    return {
        "daily.compute": json.dumps(result, default=str),
        "daily-checks/latest": client.get("/api/v1/brain/daily-checks/latest", headers=API_KEY).text,
    }


# --- nothing from the trial leaks ------------------------------------------------------------------


def test_no_route_shows_a_sealed_result(obs_client, db_session, tmp_path):
    ids = _seed(db_session, SEALED_DAY)
    # A daily check stored before the seal existed, holding the trial's results: must be stripped.
    gate = {"word": "too early", "sessions": 3, "finished": 1, "profit": True, "beats_random": True}
    trade = {
        "picked": 1,
        "ideas": 1,
        "still_open": 0,
        "hit_rate": 1.0,
        "avg_net": RETURN,
        "edge_vs_every_stock": BEST,
    }
    trial = {
        "start": "2026-10-14",
        "sessions": 3,
        "gate": gate,
        "sets": {"brain_trade": trade},
        "nifty": {"finished": 1, "open": 0, "avg": WORST},
    }
    db_session.add(
        BrainDailyCheck(
            day=SEALED_DAY + timedelta(days=2), status="ok", checks=[], run={}, intraday={}, trial=trial
        )
    )
    db_session.flush()
    texts = _call_everything(obs_client, ids)
    texts.update(_daily_check_texts(db_session, obs_client, tmp_path, SEALED_DAY + timedelta(days=3)))
    found = {url: _leaks(t) for url, t in texts.items() if _leaks(t)}
    assert found == {}, f"sealed results shown: {found}"
    assert len(texts) > 100  # every GET route was really called


RESULT_KEYS = {
    "hit_rate", "avg_net", "avg_net_by_day", "edge_vs_every_stock", "avg_outcome_pct", "stopped", "outcome",
    "outcome_pct", "gross_return", "max_up", "max_down", "profit", "beats_random", "clearly_worse",
    "avg_gross_return", "net", "so_far", "avg", "hit", "avg_r", "mean", "lower_bound",
}  # fmt: skip


def _results_in(node, path="") -> list[str]:
    """Every result key holding a value (not None) anywhere in a response."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in RESULT_KEYS and v not in (None, {}, []) and "cash" not in path:
                found.append(f"{path}.{k}={v}")
            found += _results_in(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _results_in(v, f"{path}[{i}]")
    return found


def test_brain_result_screens_hold_counts_only(obs_client, db_session):
    _seed(db_session, SEALED_DAY)
    for url in (
        "/api/v1/brain/compare",
        "/api/v1/brain/stage",
        "/api/v1/brain/trial-journal?from=2026-10-14&to=2026-11-15",
        "/api/v1/brain/observatory/forward-gate",
        "/api/v1/brain/observatory/outcomes?from=2026-10-14&to=2026-10-31&category=practice",
        "/api/v1/brain/learning",
        "/api/v1/signals/track-record",
    ):
        body = obs_client.get(url, headers=API_KEY).json()
        assert _results_in(body) == [], url
    journal = obs_client.get(
        "/api/v1/brain/trial-journal?from=2026-10-14&to=2026-11-15", headers=API_KEY
    ).json()
    assert (
        journal["journal"]["sessions"] == 1 and journal["journal"]["summaries"]["brain_trade"]["picked"] == 1
    )
    assert journal["journal"]["gate"]["word"] == "too early"
    assert trial_seal.SEALED_TEXT in journal["report"] and "profit after costs" not in journal["report"]
    row = obs_client.get("/api/v1/signals/track-record", headers=API_KEY).json()[0]
    assert row["sealed"] is True and row["outcome"] is None and row["current_price"] is None
    gate = obs_client.get("/api/v1/brain/stage", headers=API_KEY).json()
    assert gate["sealed"] is True and gate["finished"] == 1 and "profit" not in json.dumps(gate["trial"])
    compare = obs_client.get("/api/v1/brain/compare", headers=API_KEY).json()
    assert compare["brain"]["finished"] == 1 and compare["brain"]["hit_rate"] is None and compare["sealed"]


def test_the_journal_report_and_the_pack_report_are_sealed(db_session):
    from swing_trade_ml.brain.trial_journal import journal_for, plain_report
    from swing_trade_ml.services.brain_observatory import pack

    _seed(db_session, SEALED_DAY)
    journal = journal_for(db_session, date(2026, 10, 14), date(2026, 11, 15))
    assert journal["summaries"]["brain_trade"]["hit_rate"] is not None  # the real figures exist ...
    sealed = trial_seal.seal_journal(journal)
    text = plain_report(sealed) + json.dumps(sealed, default=str)
    assert _leaks(text) == [] and _results_in(sealed) == []  # ... and are never shown
    built = pack.build_pack(db_session, "2026-10", NOW.date())
    report = pack.plain_report(built)
    assert _leaks(report + json.dumps(built, default=str)) == []
    assert trial_seal.SEALED_TEXT in report


# --- learning proposals made during the trial: title, evidence and change are sealed ----------------

PROPOSAL_LEAKS = ("Raise the buy level", "buy level to 73%", "buy level to 65%", "Switch M05", "0.73")


def _plant_proposals(db, day: date) -> list[int]:
    """Two proposals made on `day` whose titles and changes say which way the results went."""
    rows = [
        BrainProposal(
            kind="buy_level",
            title="Raise the buy level to 73%",
            evidence="Among 40 past ideas scored 73% or more, the average was +1.94 R.",
            change={"buy_level": 0.73},
            created_at=_ist(day, 20, 5),
        ),
        BrainProposal(
            kind="module_mode",
            title="Switch M05 to shadow: its ideas did worse",
            evidence="M05 ideas reached the target less often.",
            change={"module": "M05", "mode": "shadow"},
            created_at=_ist(day, 20, 6),
        ),
    ]
    db.add_all(rows)
    db.flush()
    return [r.id for r in rows]


def test_proposals_made_during_the_trial_are_sealed_everywhere(obs_client, db_session):
    ids = _seed(db_session, SEALED_DAY)  # also holds "Raise the buy level to 65%"
    planted = _plant_proposals(db_session, SEALED_DAY)
    texts = _call_everything(obs_client, ids)
    found = {url: [x for x in PROPOSAL_LEAKS if x in t] for url, t in texts.items()}
    assert {u: f for u, f in found.items() if f} == {}, "a sealed proposal's title or change was shown"

    listed = obs_client.get("/api/v1/brain/proposals", headers=API_KEY).json()
    assert len(listed) == 3
    for p in listed:  # the record stays: id, kind, status, date; the content is sealed
        assert p["sealed"] is True and p["evidence_sealed"] is True
        assert p["title"] == trial_seal.PROPOSAL_SEALED_TITLE and p["evidence"] == trial_seal.SEALED_TEXT
        assert p["change"] == {} and p["status"] == "open" and p["created_at"]
    assert {p["kind"] for p in listed} == {"buy_level", "module_mode"}
    # Deciding one (through the API) answers sealed too.
    r = obs_client.post(f"/api/v1/brain/proposals/{planted[1]}/reject", json={}, headers=API_KEY)
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert not [x for x in PROPOSAL_LEAKS if x in r.text]


def test_the_owners_own_revert_is_not_sealed(obs_client, db_session):
    """Going back to the default buy level is the owner's click, not a trial result."""
    r = obs_client.post("/api/v1/brain/proposals/buy-level/revert", json={}, headers=API_KEY)
    assert r.status_code == 200
    body = r.json()
    assert body["sealed"] is False and body["title"] == "Go back to the default buy level"
    assert body["change"] == {"buy_level": None}


def test_the_learning_command_line_seals_new_proposal_titles():
    shown = trial_seal.seal_proposal(
        {"id": 1, "kind": "buy_level", "title": "Raise the buy level to 73%", "evidence": "+1.94 R"},
        NOW.astimezone(UTC),
    )
    assert shown["title"] == trial_seal.PROPOSAL_SEALED_TITLE and "1.94" not in json.dumps(shown)


# --- nothing before the trial is over-sealed -------------------------------------------------------


def test_results_from_before_the_trial_still_show(obs_client, db_session):
    ids = _seed(db_session, OPEN_DAY)
    run, dec = ids["run_id"], ids["decision_id"]

    def text(url: str) -> str:
        r = obs_client.get(url, headers=API_KEY)
        assert r.status_code == 200, (url, r.text[:300])
        return r.text

    assert "0.0777" in text(f"/api/v1/brain/observatory/runs/{run}/stocks/{dec}")
    assert "0.7316492" in text(f"/api/v1/brain/observatory/runs/{run}/stocks/{dec}")
    assert "0.0777" in text(
        "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-13&category=practice"
    )
    assert "0.0777" in text("/api/v1/brain/compare")
    assert "0.0777" in text("/api/v1/signals/track-record")
    assert "1.94" in text("/api/v1/brain/learning")
    assert "1.94" in text("/api/v1/brain/proposals")
    _plant_proposals(db_session, OPEN_DAY)
    shown = text("/api/v1/brain/proposals")
    assert "Raise the buy level to 73%" in shown and "Raise the buy level to 65%" in shown
    assert "Switch M05 to shadow" in shown and "0.73" in shown and '"sealed":false' in shown
    assert "0.0777" in text("/api/v1/ml/calibration?source=signals")
    # A range reaching into the trial keeps the days before it.
    straddle = obs_client.get(
        "/api/v1/brain/observatory/outcomes?from=2026-10-01&to=2026-10-31&category=practice", headers=API_KEY
    ).json()
    assert straddle["stored_grades"]["avg_gross_return"] == pytest.approx(RETURN)
    assert straddle["results_period"] == {"from": "2026-10-01", "to": "2026-10-13"}
    assert straddle["sealed"]["sessions"] == 0


def test_switching_the_seal_off_shows_the_trial_again(obs_client, db_session, monkeypatch):
    """The one switch: unsealing (owner's call, recorded) restores every figure."""
    monkeypatch.setattr(trial_seal, "SEALED", False)
    ids = _seed(db_session, SEALED_DAY)
    url = f"/api/v1/brain/observatory/runs/{ids['run_id']}/stocks/{ids['decision_id']}"
    assert "0.0777" in obs_client.get(url, headers=API_KEY).text
    assert "0.0777" in obs_client.get("/api/v1/brain/compare", headers=API_KEY).text


# --- the gate's real decision is unchanged ----------------------------------------------------------


def _thirty_finished(db) -> None:
    s = brain_strategy(db, name="seal-gate")
    inst = Instrument(
        instrument_token=771_178, tradingsymbol="SEALG", name="Seal G", exchange="NSE", is_watchlisted=True
    )
    db.add(inst)
    db.flush()
    for i in range(30):
        db.add(
            Signal(
                strategy_id=s.id,
                instrument_id=inst.id,
                signal_type=SignalType.BUY,
                mode="paper",
                price=100.0,
                confidence=0.6,
                stop_loss=96.0,
                take_profit=108.0,
                horizon_days=15,
                reason="r",
                features={},
                advisory_only=True,
                outcome="TARGET_HIT",
                outcome_pct=0.08,
                generated_at=_ist(date(2026, 8, 3) + timedelta(days=i), 15, 55),
            )
        )
    db.flush()


@pytest.mark.parametrize(
    ("gate", "allowed"),
    [
        ({"word": "pass", "sessions": 15, "finished": 30, "profit": True, "beats_random": True}, True),
        ({"word": "behind", "sessions": 15, "finished": 30, "profit": False, "beats_random": True}, False),
        ({"word": "too early", "sessions": 4, "finished": 3, "profit": True, "beats_random": True}, False),
    ],
)
def test_the_gate_decides_exactly_as_before(db_session, monkeypatch, gate, allowed):
    _thirty_finished(db_session)
    monkeypatch.setattr(stage, "trial_gate", lambda db: gate)
    shown = stage.stage_overview(db_session)
    assert shown["sealed"] is True and "profit" not in shown["trial"] and "beats_random" not in shown["trial"]
    assert shown["trial"]["word"] in ("sealed", "too early")
    if allowed:
        stage.set_stage(db_session, "approval", by="owner", reason="Trial passed")
        assert stage.current_stage(db_session) == "approval"
    else:
        with pytest.raises(stage.StageRefusedError) as refused:
            stage.set_stage(db_session, "approval", by="owner", reason="Try")
        message = str(refused.value)
        assert trial_seal.GATE_SEALED_TEXT in message
        assert not re.search(r"profit|beat|behind|pass", message.replace("passed", ""))
        assert stage.current_stage(db_session) == "shadow"


# --- Telegram and the daily summary ----------------------------------------------------------------


def test_telegram_messages_hold_no_sealed_result(db_session, tmp_path, monkeypatch):
    """Every Telegram text that reports on the brain or the day: the daily check's problem message, the
    Saturday health message and the end-of-day summary. Built from a day holding a sealed trial result."""
    import asyncio

    from swing_trade_ml.notifications.telegram import notifier
    from swing_trade_ml.services import brain_weekly_health as weekly
    from swing_trade_ml.services import portfolio

    _seed(db_session, SEALED_DAY)
    now = datetime.combine(SEALED_DAY + timedelta(days=3), time(16, 20), tzinfo=IST)
    result = daily.compute(db_session, now, backup_dir=str(tmp_path))
    texts = {"daily check": daily.message_if_problem({**result, "status": "check"}) or ""}
    texts["weekly health"] = weekly.format_message(weekly.compute_checks(db_session, now, str(tmp_path)))
    sent: list[str] = []

    async def capture(text, *args, **kwargs):
        sent.append(text)
        return True

    monkeypatch.setattr(notifier, "send", capture)
    stats = portfolio.performance_stats(db_session)
    asyncio.run(notifier.notify_daily_summary(stats, stats["mode"], []))
    texts["daily summary"] = "\n".join(sent)
    assert all(texts.values()), texts  # each message was really built
    found = {name: _leaks(t) for name, t in texts.items() if _leaks(t)}
    assert found == {}, f"sealed results in a Telegram message: {found}"
