"""Prediction Reliability readers against the real SQL, on synthetic rows inside the rolled-back test
transaction (conftest `db_session`: nothing persists). Only inserts are used; the append-only lane tables are
never updated or deleted. These test wiring (what is read, what is excluded), not any model's quality."""

from __future__ import annotations

import itertools
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from swing_trade_ml.brain import prediction_reliability as pr
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.lanes import H05Run, H05Signal
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services import trial_seal

IST = ZoneInfo("Asia/Kolkata")
_tok = itertools.count(960_000)
SEALED_DAY = date(2026, 10, 20)  # on or after trial_seal.SEALED_FROM (2026-10-14)


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture(autouse=True)
def _seal_on(monkeypatch):
    monkeypatch.setattr(trial_seal, "SEALED", True)


def _require_empty(db, *models):
    for m in models:
        if db.scalar(select(func.count()).select_from(m)):
            pytest.skip(f"{m.__tablename__} already has rows in the test database")


# ----------------------------------------------------------------------------- empty database


def test_empty_database_gives_insufficient_data(db_session):
    _require_empty(db_session, LanePick, H05Signal, BrainRun)
    assert pr.lane_series(db_session) == [] and pr.h05_series(db_session) == []
    assert pr.brain_series(db_session, date(2026, 9, 1), date(2026, 10, 31)) == []
    rep = pr.build_report(pr.collect(db_session, date(2026, 9, 1), date(2026, 10, 31)))
    assert rep["series"] == [] and rep["empty"]["state"] == pr.INSUFFICIENT
    assert "INSUFFICIENT DATA" in pr.plain_report(rep)


# ----------------------------------------------------------------------------- Brain Top-5


def _bar(db, inst, day, high=100.0):
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST),
            open=100.0,
            high=high,
            low=100.0,
            close=100.0,
            volume=100_000,
        )
    )


def test_brain_top5_reader_excludes_open_sealed_and_replay_rows(db_session):
    db = db_session
    _require_empty(db, BrainRun)
    sessions = weekdays(date(2026, 8, 17), date(2026, 12, 31))
    insts = {}
    for sym in ("RLB1", "RLB2", "RLB3", "RLB4", "RLB5", "RLB6"):
        insts[sym] = Instrument(
            instrument_token=next(_tok),
            tradingsymbol=sym,
            exchange="NSE",
            is_active=True,
            instrument_type="EQ",
        )
        db.add(insts[sym])
    db.flush()
    for sym, inst in insts.items():
        for d in sessions:
            if sym == "RLB1" and d > date(2026, 10, 13):
                continue  # RLB1's prices stop early: its later ideas are still open
            # RLB2 reaches +8% on every bar after the first decision day (a target); the rest stay flat
            _bar(db, inst, d, high=112.0 if sym == "RLB2" and d > date(2026, 9, 14) else 100.0)
    db.flush()
    decision_days = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 10, 9), SEALED_DAY]
    scores = {"RLB1": 0.9, "RLB2": 0.85, "RLB3": 0.8, "RLB4": 0.7, "RLB5": 0.6, "RLB6": 0.5}
    for n, d in enumerate(decision_days):
        run = BrainRun(
            id=f"rlb-{n}",
            kind="nightly",
            as_of=datetime(d.year, d.month, d.day, 18, 0, tzinfo=IST),
            book=settings.TRADING_MODE,
            live=True,
            status="done",
        )
        db.add(run)
        db.flush()
        for sym, sc in scores.items():
            db.add(
                BrainDecision(
                    run_id=run.id,
                    symbol=sym,
                    kind="idea",
                    word="TRADE" if sym == "RLB2" else "WATCH",
                    confidence=sc,
                    score_source="model",
                )
            )
    # a replayed (not live) run must never be read
    replay = BrainRun(
        id="rlb-replay",
        kind="nightly",
        as_of=datetime(2026, 9, 16, 18, 0, tzinfo=IST),
        book=settings.TRADING_MODE,
        live=False,
        status="done",
    )
    db.add(replay)
    db.flush()
    db.add(
        BrainDecision(
            run_id=replay.id, symbol="RLB3", kind="idea", word="TRADE", confidence=0.99, score_source="model"
        )
    )
    db.flush()

    series = pr.brain_series(db, date(2026, 9, 1), date(2026, 10, 31))
    assert len(series) == 1
    key, recs, source, has_pool = series[0]
    assert key["horizon"] == 15 and source == "brain" and has_pool
    assert len(recs) == 24 and {r.day for r in recs} == set(decision_days)  # the replay's day is absent
    rep = pr.report_series(key, recs, source, has_baseline_pool=has_pool)
    top = rep["sets"]["top5"]
    # unsealed days 14 Sep, 15 Sep, 9 Oct: 15 picks; RLB1 is open on 9 Oct, so 14 completed, 3 targets
    assert (top["picked"], top["completed"], top["open"], top["days"]) == (15, 14, 1, 3)
    assert top["hit_rate"] == pytest.approx(3 / 14)
    trade = rep["sets"]["trade"]
    assert trade["picked"] == 3 and trade["completed"] == 3 and trade["hit_rate"] == 1.0
    assert rep["sets"]["baseline"]["picked"] == 18
    # the sealed day is counts only: 5 picked, RLB1 open (no prices), 4 completed
    sc = rep["sealed_counts"]["top5"]
    assert (sc["picked"], sc["finished"], sc["open"], sc["avg_net"], sc["hit_rate"]) == (5, 4, 1, None, None)
    # figures equal those worked out with the sealed day absent from the database altogether
    unsealed = [r for r in recs if not trial_seal.is_sealed_day(r.day)]
    again = pr.report_series(key, unsealed, source, has_baseline_pool=has_pool)
    assert again["sets"] == rep["sets"] and again["health"] == rep["health"]
    assert all(h["state"] == pr.INSUFFICIENT for h in rep["health"].values())  # below the sample gates


# ----------------------------------------------------------------------------- lanes


def _model(db, name, horizon):
    m = MLModel(
        name=name,
        version="v1",
        algorithm="lightgbm",
        status="TRAINED",
        prediction_horizon_days=horizon,
        feature_names=["a"],
        training_symbols=["X"],
    )
    db.add(m)
    db.flush()
    return m


def _pick(db, model, slot, horizon, day, rank, outcome=None, baseline=None):
    p = LanePick(
        model_id=model.id,
        slot_key=slot,
        horizon_days=horizon,
        cap_group="large",
        signal_day=day,
        symbol=f"L{rank}",
        rank=rank,
        score=0.9 - rank / 100,
        model_version="v1",
        entry_assumption={},
        target_pct=0.08,
        stop_pct=0.04,
    )
    db.add(p)
    db.flush()
    if outcome is not None:
        status, net = outcome
        db.add(
            LaneOutcome(
                pick_id=p.id, matured_day=day, status=status, net_return=net, baseline_net_return=baseline
            )
        )


def test_lane_reader_open_sealed_horizons_and_missing_baseline(db_session):
    db = db_session
    _require_empty(db, LanePick)
    m10, m15 = _model(db, "rlb_h10", 10), _model(db, "rlb_h15", 15)
    unsealed = weekdays(date(2026, 9, 1), date(2026, 9, 16))  # 12 days
    assert len(unsealed) == 12
    for d in unsealed:
        # 10-day lane: with a stored baseline. rank 4 unresolved, rank 5 no outcome row at all (both open)
        _pick(db, m10, "10d-large", 10, d, 1, ("target", 0.05), 0.01)
        _pick(db, m10, "10d-large", 10, d, 2, ("stop", -0.04), 0.01)
        _pick(db, m10, "10d-large", 10, d, 3, ("timeout", 0.0), 0.01)
        _pick(db, m10, "10d-large", 10, d, 4, ("unresolved", None), None)
        _pick(db, m10, "10d-large", 10, d, 5)
        # 15-day lane: same shape but it never stored a baseline
        _pick(db, m15, "15d-large", 15, d, 1, ("target", 0.30), None)
        _pick(db, m15, "15d-large", 15, d, 2, ("stop", -0.20), None)
    for d in weekdays(date(2026, 10, 14), date(2026, 10, 16)):  # sealed days with extreme results
        _pick(db, m10, "10d-large", 10, d, 1, ("target", 0.9876), 0.0)
    db.flush()

    series = pr.lane_series(db)
    assert [s[0]["horizon"] for s in series] == [10, 15]  # two horizons, two series, never pooled
    (k10, r10, src10, pool10), (k15, r15, _, _) = series
    assert src10 == "lane" and not pool10 and k10["group"] == "10d-large"
    assert len(r10) == 12 * 5 + 3 and len(r15) == 12 * 2
    rep10 = pr.report_series(k10, r10, "lane", has_baseline_pool=False)
    top = rep10["sets"]["top5"]
    assert (top["picked"], top["completed"], top["open"]) == (60, 36, 24)  # unresolved + no row = open
    assert top["hit_rate"] == pytest.approx(12 / 36)
    assert top["avg_net"] == pytest.approx(0.01 / 3)
    assert top["avg_excess"] == pytest.approx(-0.02 / 3) and top["excess_days"] == 12
    assert rep10["sealed_counts"]["top5"]["picked"] == 3
    blob = json.dumps(rep10, default=str) + pr.plain_report({"disclaimer": "", "series": [rep10]})
    assert "0.9876" not in blob and "98.8" not in blob
    # missing baseline stays None (never 0), and the state cannot be better than INSUFFICIENT
    rep15 = pr.report_series(k15, r15, "lane", has_baseline_pool=False)
    t15 = rep15["sets"]["top5"]
    assert t15["avg_excess"] is None and t15["baseline_avg_net"] is None and t15["completed"] == 24
    assert rep15["sealed_counts"] is None
    assert rep15["health"]["top5"]["state"] == pr.INSUFFICIENT
    assert rep10["sets"]["ranks_6_20"] == pr.NOT_RECORDED


# ----------------------------------------------------------------------------- 5D h05


def _h05(db, run, day, group, version, rank, *, hit=None, net=None, scored=True):
    db.add(
        H05Signal(
            run_id=run.id,
            signal_day=day,
            symbol=f"{group[0].upper()}{rank}",
            group=group,
            status="scored" if scored else "not_scored",
            model_version=version,
            score=0.9 - rank / 100 if scored else None,
            group_rank=rank if scored else None,
            selected=scored and rank <= 5,
            label_status="evaluated" if hit is not None else "pending",
            label_hit=hit,
            trade_status="target"
            if net is not None and net > 0
            else ("timeout" if net is not None else "pending"),
            net_return=net,
        )
    )


def test_h05_reader_open_sealed_models_and_missing_values(db_session):
    db = db_session
    _require_empty(db, H05Signal)
    run = H05Run(
        run_no=9901,
        protocol_code="test",
        protocol_hash="x",
        start_day=date(2026, 9, 1),
        end_day=date(2026, 12, 1),
        models={},
        universe={},
        universe_hash="u",
    )
    db.add(run)
    db.flush()
    unsealed = weekdays(date(2026, 9, 1), date(2026, 9, 10))  # 8 days
    assert len(unsealed) == 8
    for d in unsealed:
        for rank in range(1, 9):
            if rank == 8:  # still pending: neither label nor trade finished
                _h05(db, run, d, "large", "v1", rank)
            else:
                _h05(
                    db,
                    run,
                    d,
                    "large",
                    "v1",
                    rank,
                    hit=1 if rank == 1 else 0,
                    net=0.03 if rank == 1 else -0.01,
                )
        _h05(db, run, d, "large", "v1", 99, scored=False)  # not scored: never counted
        # a different group and model: labels finished but no trade result stored at all
        for rank in range(1, 7):
            _h05(db, run, d, "mid", "v2", rank, hit=1 if rank <= 2 else 0)
    for rank in range(1, 9):  # one sealed day, extreme result
        _h05(db, run, SEALED_DAY, "large", "v1", rank, hit=1, net=0.7777)
    db.flush()

    series = pr.h05_series(db)
    keys = [(s[0]["group"], s[0]["model"]) for s in series]
    assert keys == [("large", "v1"), ("mid", "v2")]  # separate groups/models, never pooled
    (kl, rl, _, pl), (km, rm, _, _) = series
    assert kl["horizon"] == 5 and pl
    assert len(rl) == 8 * 8 + 8 and len(rm) == 8 * 6  # the not_scored rows are absent
    repl = pr.report_series(kl, rl, "h05", has_baseline_pool=True)
    top, rest, base = repl["sets"]["top5"], repl["sets"]["ranks_6_20"], repl["sets"]["baseline"]
    assert (top["picked"], top["completed"], top["open"]) == (40, 40, 0)
    assert (rest["picked"], rest["completed"], rest["open"]) == (24, 16, 8)  # rank 8 is pending
    assert base["picked"] == 64
    assert top["hit_rate"] == pytest.approx(8 / 40)
    assert repl["sealed_counts"]["top5"]["picked"] == 5
    assert "0.7777" not in json.dumps(repl, default=str) + pr.plain_report(
        {"disclaimer": "", "series": [repl]}
    )
    assert repl["ranking"]["net_gap_days"] == 8
    # mid: no trade result stored: net stays None, not 0, and the paired excess is None
    repm = pr.report_series(km, rm, "h05", has_baseline_pool=True)
    tm = repm["sets"]["top5"]
    assert tm["avg_net"] is None and tm["avg_excess"] is None and tm["completed"] == 40
    assert repm["health"]["top5"]["state"] == pr.INSUFFICIENT
    assert all(s["health"]["top5"]["state"] == pr.INSUFFICIENT for s in pr.build_report(series)["series"])
