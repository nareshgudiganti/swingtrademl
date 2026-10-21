"""ps5: ideas by model score vs how often +8% came first; the blind trial stays counts only."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.services.brain_observatory import score_bands as sb
from test_brain_observatory_evidence import API_KEY, URL, obs_client  # noqa: F401 - obs_client is a fixture

EVIDENCE = Path(__file__).resolve().parents[2] / "docs/brain/evidence/score_reliability.json"


@pytest.mark.parametrize(
    "score,band",
    [(0.0, "0%-30%"), (0.2999, "0%-30%"), (0.3, "30%-40%"), (0.7999, "70%-80%"), (1.0, "80%-100%")],
)
def test_bands_have_no_gaps_or_overlaps(score, band):
    assert sb.band_of(score) == band


def test_the_development_table_is_the_committed_evidence_file():
    rows = json.loads(EVIDENCE.read_text(encoding="utf-8"))["raw_table_all_folds"]
    assert [(r["band"], r["n"], r["really_hit"]) for r in rows] == [
        (b["band"], b["ideas"], b["hit_rate"]) for b in sb.DEVELOPMENT["bands"]
    ]
    assert [b["band"] for b in sb.DEVELOPMENT["bands"]] == [label for label, _, _ in sb.BANDS]


def test_a_sealed_period_shows_counts_but_never_a_result():
    rows = [(0.85, "target"), (0.85, "stop"), (0.85, None), (0.45, "target")]
    sealed = {b["band"]: b for b in sb.summarise(rows, sealed=True)}
    assert (sealed["80%-100%"]["ideas"], sealed["80%-100%"]["finished"]) == (3, 2)
    assert all(b["hit_rate"] is None for b in sealed.values())
    open_ = {b["band"]: b for b in sb.summarise(rows, sealed=False)}
    assert open_["80%-100%"]["hit_rate"] == 0.5 and open_["40%-50%"]["hit_rate"] == 1.0
    assert open_["0%-30%"]["hit_rate"] is None  # no ideas: no number, never 0


def _seed(db):
    for run_id, as_of in (
        ("sb-before", datetime(2026, 10, 9, 11, 0, tzinfo=UTC)),
        ("sb-trial", datetime(2026, 10, 15, 11, 0, tzinfo=UTC)),
    ):
        db.add(BrainRun(id=run_id, kind="nightly", live=True, status="done", book="paper", as_of=as_of))
        db.flush()
        for n, (score, outcome) in enumerate(((0.9, "target"), (0.9, "stop"), (0.5, "stop"), (0.5, None))):
            db.add(
                BrainDecision(
                    run_id=run_id,
                    symbol=f"SB{n}",
                    kind="idea",
                    word="TRADE",
                    confidence=score,
                    score_source="model",
                    outcome=outcome,
                )
            )
        db.add(
            BrainDecision(
                run_id=run_id,
                symbol="SBX",
                kind="idea",
                word="WAIT",
                confidence=0.9,
                score_source="combined",
                outcome="target",
            )
        )  # not a raw model score: left out
    db.flush()


def test_before_the_trial_shows_results_and_the_trial_is_sealed(db_session):
    _seed(db_session)
    out = sb.build(db_session, date(2026, 10, 1), date(2026, 10, 20), "paper")
    before, trial = out["live"]
    assert (before["period"], before["to"], trial["period"], trial["from"]) == (
        "before_trial",
        "2026-10-13",
        "trial",
        "2026-10-14",
    )
    b = {r["band"]: r for r in before["bands"]}
    assert (b["80%-100%"]["ideas"], b["80%-100%"]["hit_rate"]) == (2, 0.5)
    t = {r["band"]: r for r in trial["bands"]}
    assert (t["80%-100%"]["ideas"], t["80%-100%"]["finished"], t["80%-100%"]["hit_rate"]) == (2, 2, None)
    assert t["50%-60%"]["finished"] == 1


def test_the_route_never_returns_a_trial_result(obs_client, db_session):  # noqa: F811
    _seed(db_session)
    body = obs_client.get(f"{URL}/score-bands?from=2026-10-14&to=2026-10-20", headers=API_KEY).json()
    assert [p["period"] for p in body["live"]] == ["trial"]
    assert all(r["hit_rate"] is None for r in body["live"][0]["bands"])
    assert body["development"]["bands"][-1]["band"] == "80%-100%"
