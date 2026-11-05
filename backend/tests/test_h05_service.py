# ruff: noqa: E501 (long test sentences)
# ruff: noqa: N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""h05 lane: routing, NOT SCORED reasons, recording, outcomes, frozen identities, isolation.

The three production models are replaced by stand-ins here (the real files are checked by `verify_models`
tests with temporary artifacts), so these tests prove the lane's wiring, not any model's quality.
"""

from __future__ import annotations

import ast
import itertools
import pathlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import joblib
import pytest
from sqlalchemy import select

import swing_trade_ml.brain.lanes as lanes_pkg
from swing_trade_ml.brain.lanes import h05_models, h05_report, h05_service
from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.brain.lanes.h05_models import VerifiedModel
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.lanes import H05GroupDay, H05Run, H05Signal
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.session import User
from swing_trade_ml.ml.features import FEATURE_COLUMNS

IST = ZoneInfo("Asia/Kolkata")
SIGNAL = date(2026, 10, 14)  # a Wednesday
NOW = datetime(2026, 10, 14, 13, 0, tzinfo=UTC)  # 18:30 IST on the signal day: after the close, before the entry open
_token = itertools.count(910_000)


def weekdays(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = weekdays(date(2025, 6, 2), date(2026, 12, 31))


def after(day: date, n: int) -> date:
    return SESSIONS[SESSIONS.index(day) + n]


def add_stock(db, symbol, last=SIGNAL, n=230, price=100.0, active=True):
    inst = Instrument(
        instrument_token=next(_token),
        tradingsymbol=symbol,
        exchange="NSE",
        is_active=active,
        instrument_type="EQ",
    )
    db.add(inst)
    db.flush()
    days = [d for d in SESSIONS if d <= last][-n:]
    for d in days:
        add_candle(db, inst, d, (price, price, price, price))
    return inst


def add_candle(db, inst, day, bar):
    db.add(
        Candle(
            instrument_id=inst.id,
            interval="day",
            ts=datetime(day.year, day.month, day.day, tzinfo=IST),
            open=bar[0],
            high=bar[1],
            low=bar[2],
            close=bar[3],
            volume=100_000,
        )
    )
    db.flush()


def fake_models(sha="a" * 64) -> dict[str, VerifiedModel]:
    ids = {
        "large": (2, "swing_classifier"),
        "mid": (16, "swing_classifier_midcap"),
        "small": (17, "swing_classifier_smallcap"),
    }
    return {
        g: VerifiedModel(
            g,
            mid,
            name,
            "v1",
            "ACTIVE",
            sha,
            ["f1", "f2"],
            date(2026, 8, 5),
            frozenset({"TRAINED1"}),
            Path("x"),
            SimpleNamespace(id=mid, name=name, version="v1", artifact_path="x"),
        )
        for g, (mid, name) in ids.items()
    }


@pytest.fixture()
def lane(monkeypatch, db_session):
    """Lane switched on for the test, calendar and models replaced.

    `scores` drives the PRIMARY (training-basis) score; `alt` drives the production-path diagnostic score
    (defaults to the same number). A stock missing from `scores` has invalid features."""
    scores: dict[str, float] = {}
    alt: dict[str, float] = {}
    calls: list[tuple[str, int]] = []

    def last_bar(db, inst):
        return db.execute(
            select(Candle.ts, Candle.close)
            .where(Candle.instrument_id == inst.id)
            .order_by(Candle.ts.desc())
            .limit(1)
        ).one()

    def primary(db, inst, bundle):
        if inst.tradingsymbol not in scores:
            return None
        row = last_bar(db, inst)
        return SimpleNamespace(probability=scores[inst.tradingsymbol], ts=row.ts, price=row.close)

    def production(db, inst, model):
        calls.append((inst.tradingsymbol, model.id))
        if inst.tradingsymbol not in scores:
            return None
        row = last_bar(db, inst)
        p = alt.get(inst.tradingsymbol, scores[inst.tradingsymbol])
        return SimpleNamespace(probability=p, ts=row.ts, price=row.close)

    monkeypatch.setattr(P, "require_runnable", lambda *a, **k: None)
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: list(SESSIONS))
    monkeypatch.setattr(h05_service, "score_training_basis", primary)
    monkeypatch.setattr(h05_service, "predict_instrument", production)
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models())
    return SimpleNamespace(scores=scores, alt=alt, calls=calls)


def make_run(db, groups: dict[str, str], excluded=None, run_no=1) -> H05Run:
    run = H05Run(
        run_no=run_no,
        protocol_code=P.PROTOCOL_CODE,
        protocol_hash=P.protocol_hash(),
        status="active",
        start_day=date(2026, 10, 1),
        end_day=date(2026, 11, 30),
        models={g: m.identity() for g, m in fake_models().items()},
        universe={"groups": groups, "excluded": excluded or {}},
        universe_hash="u1",
    )
    db.add(run)
    db.flush()
    return run


def rows_of(db, run):
    return {s.symbol: s for s in db.execute(select(H05Signal).where(H05Signal.run_id == run.id)).scalars()}


# ----------------------------------------------------------------- routing: each group its own model


def test_each_stock_is_scored_by_the_model_of_its_own_group_and_never_another(db_session, lane):
    groups = {"LRG1": "large", "MID1": "mid", "SML1": "small"}
    for s in groups:
        add_stock(db_session, s)
        lane.scores[s] = 0.6
    run = make_run(db_session, groups)
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    assert sorted(lane.calls) == [("LRG1", 2), ("MID1", 16), ("SML1", 17)]
    rows = rows_of(db_session, run)
    assert (rows["LRG1"].model_id, rows["MID1"].model_id, rows["SML1"].model_id) == (2, 16, 17)


def test_a_missing_group_model_refuses_instead_of_falling_back(db_session, lane, monkeypatch):
    add_stock(db_session, "MID1")
    lane.scores["MID1"] = 0.7
    only_large = {"large": fake_models()["large"]}
    monkeypatch.setattr(h05_service, "verify_models", lambda db: only_large)
    run = make_run(db_session, {"MID1": "mid"})
    with pytest.raises(P.ProtocolError, match="no frozen model"):
        h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    assert lane.calls == [] and not rows_of(db_session, run)


# ----------------------------------------------------------------- NOT SCORED, with a reason


def test_every_not_scored_case_is_recorded_with_its_reason(db_session, lane):
    add_stock(db_session, "OK1")
    add_stock(db_session, "STALE", last=after(SIGNAL, -1))
    add_stock(db_session, "SHORT", n=100)
    add_stock(db_session, "NOFEAT")
    add_stock(db_session, "AHEAD", last=after(SIGNAL, 1))
    add_stock(db_session, "OFF", active=False)
    lane.scores.update({"OK1": 0.8, "STALE": 0.9, "SHORT": 0.9, "AHEAD": 0.9, "OFF": 0.9})  # NOFEAT -> None
    groups = dict.fromkeys(("OK1", "STALE", "SHORT", "NOFEAT", "AHEAD", "OFF", "GHOST"), "large")
    run = make_run(db_session, groups, excluded={"BOTH": "ambiguous_group: in mid and small"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rows = rows_of(db_session, run)
    why = {s: r.not_scored_reason for s, r in rows.items()}
    assert why == {
        "OK1": None,
        "STALE": "stale_data",
        "SHORT": "short_history",
        "NOFEAT": "invalid_features",
        "AHEAD": "signal_day_not_latest_candle",
        "OFF": "instrument_inactive",
        "GHOST": "instrument_not_found",
        "BOTH": "ambiguous_group: in mid and small",
    }
    assert rows["OK1"].status == "scored" and all(r.score is None for s, r in rows.items() if s != "OK1")
    assert "STALE" not in {c[0] for c in lane.calls} and "SHORT" not in {c[0] for c in lane.calls}


# ----------------------------------------------------------------- recording and selection


def test_every_eligible_stock_is_saved_and_the_top_five_per_group_are_selected(db_session, lane):
    groups = {f"L{i}": "large" for i in range(8)} | {f"S{i}": "small" for i in range(3)}
    for i, s in enumerate(groups):
        add_stock(db_session, s)
        lane.scores[s] = 0.5 + i / 100
    run = make_run(db_session, groups)
    summary = h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rows = rows_of(db_session, run)
    assert len(rows) == 11 and all(r.status == "scored" for r in rows.values())  # not only the selected ones
    large = sorted((r for r in rows.values() if r.group == "large"), key=lambda r: r.group_rank)
    assert [r.group_rank for r in large] == list(range(1, 9)) and [r.selected for r in large] == [
        True
    ] * 5 + [False] * 3
    assert large[0].symbol == "L7"  # highest score first
    assert summary["large"]["shortfall"] == 0 and summary["small"]["shortfall"] == 2
    assert summary["mid"] == {
        "universe": 0,
        "scored": 0,
        "not_scored": 0,
        "not_scored_detail": {},
        "selected": [],
        "shortfall": 5,
    }
    gd = {g.group: g for g in db_session.execute(select(H05GroupDay)).scalars()}
    assert gd["small"].selected_n == 3 and gd["small"].shortfall == 2


def test_ranks_never_mix_groups_even_when_raw_scores_are_comparable(db_session, lane):
    groups = {"LRG": "large", "SML": "small"}
    for s in groups:
        add_stock(db_session, s)
    lane.scores.update({"LRG": 0.55, "SML": 0.95})
    run = make_run(db_session, groups)
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rows = rows_of(db_session, run)
    assert rows["LRG"].group_rank == 1 and rows["SML"].group_rank == 1 and rows["LRG"].selected


def test_a_recorded_day_is_never_rewritten_and_future_or_foreign_days_are_refused(db_session, lane, monkeypatch):
    add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    with pytest.raises(P.ProtocolError, match="already recorded"):
        h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    with pytest.raises(P.ProtocolError, match="outside the run"):
        h05_service.score_day(db_session, run, date(2026, 12, 15), now=NOW)
    with pytest.raises(P.ProtocolError, match="not closed"):
        h05_service.score_day(db_session, run, after(SIGNAL, 1), now=datetime(2026, 10, 15, 5, tzinfo=UTC))
    holiday = date(2026, 10, 13)  # a weekday the exchange calendar (NIFTY bars) does not have
    monkeypatch.setattr(h05_service, "market_sessions", lambda db: [d for d in SESSIONS if d != holiday])
    with pytest.raises(P.ProtocolError, match="not a market session"):
        h05_service.score_day(db_session, run, holiday, now=NOW)


def test_a_repeat_inside_five_sessions_is_recorded_but_not_counted(db_session, lane):
    inst = add_stock(db_session, "REP")
    lane.scores["REP"] = 0.9
    run = make_run(db_session, {"REP": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    nxt = after(SIGNAL, 1)
    add_candle(db_session, inst, nxt, (100, 100, 100, 100))
    h05_service.score_day(db_session, run, nxt, now=NOW + timedelta(days=1))
    rep = {s.signal_day: s for s in db_session.execute(select(H05Signal)).scalars()}
    assert rep[SIGNAL].selected and not rep[SIGNAL].repeat_blocked
    assert rep[nxt].selected and rep[nxt].repeat_blocked


# ----------------------------------------------------------------- outcomes


def future(db, inst, **sessions_):
    """Add the five sessions after SIGNAL; n<k> overrides session k's bar, the rest are flat."""
    for k in range(1, 6):
        add_candle(db, inst, after(SIGNAL, k), sessions_.get(f"n{k}", (100, 100, 100, 100)))


def test_outcomes_fill_label_and_trade_separately_and_a_final_outcome_never_changes(db_session, lane):
    names = {
        "WIN": {"n2": (100, 103, 100, 102.5), "n5": (103, 103, 103, 103)},
        "LOSE": {"n1": (100, 100, 94, 95)},
        "RECOVER": {"n1": (100, 100, 94, 95), "n5": (103, 104, 102, 103)},
    }
    insts = {}
    for i, s in enumerate(names):
        insts[s] = add_stock(db_session, s)
        lane.scores[s] = 0.9 - i / 10
    run = make_run(db_session, dict.fromkeys(names, "large"))
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    for s, bars in names.items():
        future(db_session, insts[s], **bars)
    done = h05_service.evaluate(db_session, run)
    assert done == {"label": 3, "trade": 3}
    rows = rows_of(db_session, run)
    assert (rows["WIN"].label_hit, rows["WIN"].trade_status) == (1, "target")
    assert (rows["LOSE"].label_hit, rows["LOSE"].trade_status) == (0, "stop")
    assert (rows["RECOVER"].label_hit, rows["RECOVER"].trade_status) == (
        1,
        "stop",
    )  # YES to the model, loss on the trade
    assert rows["RECOVER"].net_return < 0 < rows["WIN"].net_return
    assert rows["WIN"].label_day5 == after(SIGNAL, 5) and rows["WIN"].exit_day == after(SIGNAL, 2)
    before = {s: (r.label_hit, r.net_return, r.exit_day) for s, r in rows.items()}
    db_session.execute(Candle.__table__.update().values(close=1.0))  # rewrite history
    assert h05_service.evaluate(db_session, run) == {"label": 0, "trade": 0}
    db_session.expire_all()
    assert before == {s: (r.label_hit, r.net_return, r.exit_day) for s, r in rows_of(db_session, run).items()}


def test_an_outcome_stays_pending_until_its_sessions_have_happened(db_session, lane, monkeypatch):
    inst = add_stock(db_session, "PEND")
    lane.scores["PEND"] = 0.9
    run = make_run(db_session, {"PEND": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    for k in (1, 2, 3):
        add_candle(db_session, inst, after(SIGNAL, k), (100, 100, 100, 100))
    monkeypatch.setattr(
        h05_service, "market_sessions", lambda db: SESSIONS[: SESSIONS.index(after(SIGNAL, 3)) + 1]
    )
    assert h05_service.evaluate(db_session, run) == {"label": 0, "trade": 0}
    row = rows_of(db_session, run)["PEND"]
    assert (row.label_status, row.trade_status) == ("pending", "pending")


# ----------------------------------------------------------------- runs: frozen identities


def test_the_lane_is_off_by_default_so_nothing_can_start(db_session, monkeypatch):
    monkeypatch.setenv("LANE_H05_ENABLED", "false")
    with pytest.raises(P.ProtocolError, match="disabled"):
        h05_service.start_run(db_session, 1, date(2026, 10, 1), date(2026, 10, 30))
    assert db_session.scalar(select(H05Run)) is None


@pytest.fixture()
def starter(monkeypatch):
    state = {"universe": ({"A1": "large"}, {}, "uhash-1"), "models": fake_models()}
    monkeypatch.setattr(P, "require_runnable", lambda *a, **k: None)
    monkeypatch.setattr(h05_service, "verify_models", lambda db: state["models"])
    monkeypatch.setattr(h05_service, "build_universe", lambda db: state["universe"])
    state["parity"] = {"ok": True, "groups": {}}
    monkeypatch.setattr(h05_service, "parity_report", lambda db, models: state["parity"])
    return state


def test_runs_two_and_three_must_see_the_models_and_universe_frozen_at_run_one(db_session, starter):
    r1 = h05_service.start_run(db_session, 1, date(2026, 10, 1), date(2026, 10, 30))
    assert r1.models["large"]["model_id"] == 2 and r1.universe_hash == "uhash-1"
    with pytest.raises(P.ProtocolError, match="already exists"):
        h05_service.start_run(db_session, 1, date(2026, 11, 2), date(2026, 11, 30))
    with pytest.raises(P.ProtocolError, match="closed first"):
        h05_service.start_run(db_session, 2, date(2026, 11, 2), date(2026, 11, 30))
    h05_service.close_run(db_session, r1)
    with pytest.raises(P.ProtocolError, match="after the previous run"):
        h05_service.start_run(db_session, 2, date(2026, 10, 20), date(2026, 11, 30))
    starter["universe"] = ({"A1": "large", "NEW": "mid"}, {}, "uhash-2")
    with pytest.raises(P.ProtocolError, match="universe changed"):
        h05_service.start_run(db_session, 2, date(2026, 11, 2), date(2026, 11, 30))
    starter["universe"] = ({"A1": "large"}, {}, "uhash-1")
    starter["models"] = fake_models(sha="b" * 64)  # the model file changed
    with pytest.raises(P.ProtocolError, match="identity changed"):
        h05_service.start_run(db_session, 2, date(2026, 11, 2), date(2026, 11, 30))
    starter["models"] = fake_models()
    assert h05_service.start_run(db_session, 2, date(2026, 11, 2), date(2026, 11, 30)).run_no == 2
    with pytest.raises(P.ProtocolError, match="1, 2 or 3"):
        h05_service.start_run(db_session, 4, date(2026, 12, 1), date(2026, 12, 30))


def test_scoring_stops_if_a_model_changed_during_the_runs(db_session, lane, monkeypatch):
    add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    monkeypatch.setattr(h05_service, "verify_models", lambda db: fake_models(sha="c" * 64))
    result = h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    assert result["stopped"] and "identity changed" in result["reason"]
    assert not rows_of(db_session, run)  # nothing recorded for the day


# ----------------------------------------------------------------- verify_models (real artifacts, temporary)


def _world(db, tmp_path, monkeypatch):
    spec = {
        "large": (37, "swing_classifier", "v2"),
        "mid": (46, "swing_classifier_midcap", "v2"),
        "small": (46, "swing_classifier_smallcap", "v1"),
    }
    expected = {}
    for g, (n, name, ver) in spec.items():
        names = FEATURE_COLUMNS[:n]
        path = tmp_path / f"{name}_{ver}.joblib"
        joblib.dump(
            {
                "estimator": None,
                "scaler": None,
                "feature_names": names,
                "algorithm": "lightgbm",
                "horizon_days": 5,
                "target_return": 0.02,
            },
            path,
        )
        row = MLModel(
            name=name,
            version=ver,
            algorithm="lightgbm",
            status="ACTIVE",
            artifact_path=f"/app/data/models/{path.name}",
            feature_names=names,
            training_symbols=["TRAINED1"],
            label_kind="endpoint",
            prediction_horizon_days=5,
            target_return_pct=0.02,
            stop_return_pct=None,
        )
        db.add(row)
        db.flush()
        expected[g] = {
            "id": row.id,
            "name": name,
            "version": ver,
            "n_features": n,
            "sha256": h05_models.sha256_file(path),
        }
    monkeypatch.setattr(P, "EXPECTED_MODELS", expected)
    monkeypatch.setattr(h05_models, "settings", SimpleNamespace(model_dir=tmp_path))
    return expected


def test_the_three_frozen_models_verify_and_resolve_the_servers_path_to_this_machines_file(
    db_session, tmp_path, monkeypatch
):
    expected = _world(db_session, tmp_path, monkeypatch)
    models = h05_models.verify_models(db_session)
    assert {g: m.model_id for g, m in models.items()} == {g: e["id"] for g, e in expected.items()}
    assert models["large"].identity()["n_features"] == 37 and models["mid"].identity()["n_features"] == 46
    assert models["large"].scorer.artifact_path == str(tmp_path / "swing_classifier_v2.joblib")
    assert "TRAINED1" in models["small"].training_symbols


@pytest.mark.parametrize(
    "change,message",
    [
        ({"label_kind": "barrier"}, "label is"),
        ({"prediction_horizon_days": 15}, "label is"),
        ({"target_return_pct": 0.08}, "target is"),
        ({"stop_return_pct": 0.04}, "stop in its label"),
        ({"version": "v9"}, "expected swing_classifier"),
    ],
)
def test_a_model_that_is_not_the_frozen_endpoint_model_is_refused(
    db_session, tmp_path, monkeypatch, change, message
):
    expected = _world(db_session, tmp_path, monkeypatch)
    row = db_session.get(MLModel, expected["large"]["id"])
    for k, v in change.items():
        setattr(row, k, v)
    db_session.flush()
    with pytest.raises(P.ProtocolError, match=message):
        h05_models.verify_models(db_session)


def test_a_changed_model_file_or_input_list_is_refused(db_session, tmp_path, monkeypatch):
    expected = _world(db_session, tmp_path, monkeypatch)
    path = tmp_path / "swing_classifier_midcap_v2.joblib"
    joblib.dump(
        {
            "estimator": None,
            "scaler": None,
            "feature_names": FEATURE_COLUMNS[:46],
            "algorithm": "lightgbm",
            "horizon_days": 5,
            "target_return": 0.02,
            "note": "retrained",
        },
        path,
    )
    with pytest.raises(P.ProtocolError, match="file hash"):
        h05_models.verify_models(db_session)
    expected["mid"]["sha256"] = h05_models.sha256_file(
        path
    )  # even a matching hash cannot hide a different label
    joblib.dump(
        {
            "estimator": None,
            "scaler": None,
            "feature_names": FEATURE_COLUMNS[:46],
            "algorithm": "lightgbm",
            "horizon_days": 15,
            "target_return": 0.08,
        },
        path,
    )
    expected["mid"]["sha256"] = h05_models.sha256_file(path)
    with pytest.raises(P.ProtocolError, match="5 / \\+2%"):
        h05_models.verify_models(db_session)


def test_a_missing_model_file_is_refused(db_session, tmp_path, monkeypatch):
    _world(db_session, tmp_path, monkeypatch)
    (tmp_path / "swing_classifier_smallcap_v1.joblib").unlink()
    with pytest.raises(P.ProtocolError, match="not found"):
        h05_models.verify_models(db_session)


# ----------------------------------------------------------------- universe


def test_a_stock_in_two_group_lists_is_excluded_not_given_to_one_model(db_session, monkeypatch):
    from swing_trade_ml.db.models.trading import Strategy

    for name, model, symbols in (
        ("a", "swing_classifier", ["X", "Y"]),
        ("b", "swing_classifier_midcap", ["M", "Z"]),
        ("c", "swing_classifier_smallcap", ["S", "Z"]),
    ):
        db_session.add(
            Strategy(
                name=f"h05-{name}",
                strategy_type="ml_swing",
                params={"model_name": model},
                is_active=True,
                mode="paper",
                execution_mode="auto",
                symbols=symbols,
            )
        )
    db_session.flush()
    universe, excluded, digest = h05_models.build_universe(db_session)
    assert universe == {"X": "large", "Y": "large", "M": "mid", "S": "small"}
    assert excluded == {"Z": "ambiguous_group: in mid and small"}
    assert digest == h05_models.build_universe(db_session)[2]


# ----------------------------------------------------------------- reporting


def _row(day, sel, hit, net, status="target", **kw):
    base = {
        "signal_day": day,
        "group": "large",
        "status": "scored",
        "not_scored_reason": None,
        "selected": sel,
        "repeat_blocked": False,
        "trained_on_symbol": True,
        "symbol": "SYM",
        "score": 0.7,
        "score_production_path": 0.6,
        "net_return_stress": None,
        "trade_status_stress": None,
        "label_status": "evaluated",
        "label_hit": hit,
        "trade_status": status,
        "net_return": net,
        "ambiguous": False,
        "gap_fill": False,
        "trade_flags": [],
    }
    return base | kw


def test_the_report_splits_groups_and_never_pronounces_a_verdict(db_session, lane):
    add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    rep = h05_report.build_report(db_session)
    assert rep["title"] == "5 trading days · Existing model evaluation"
    assert set(rep["runs"][0]["groups"]) == {"large", "mid", "small"}
    assert rep["verdict"]["state"] == "not_calculated" and "not been accepted" in rep["verdict_note"]
    assert "not a probability of profit" in rep["score_note"]
    assert (
        "fd-protocol-v1" in rep["earlier_evidence"]["protocol"]
        and "FAIL" in rep["earlier_evidence"]["result"]
    )
    md = h05_report.render_markdown(rep)
    assert (
        md.startswith("# 5 trading days · Existing model evaluation") and "Differences from the v1 bot" in md
    )


def test_group_summary_compares_picks_with_every_eligible_stock_and_counts_ambiguous_cases():
    days = weekdays(date(2026, 10, 1), date(2026, 10, 30))
    rows = []
    for d in days:
        rows += [
            _row(d, True, 1, 0.02),
            *[
                _row(d, False, 0, -0.01, status="stop") for _ in range(10)
            ],  # 11 eligible stocks a day (U2 needs 10)
        ]
    rows.append(
        _row(days[0], True, 1, -0.01, status="stop", ambiguous=True, trade_flags=["same_candle_both_levels"])
    )
    s = h05_report.summarise_group(rows)
    assert s["endpoint_label"]["counted_picks"]["hit_rate"] == 1.0
    assert s["endpoint_label"]["baseline_every_eligible_stock"]["hit_rate"] < 0.5
    assert s["shadow_trade"]["counted_picks"]["ambiguous_same_candle"] == 1
    assert s["shadow_trade"]["picks_vs_random_note"] == "picks average is above the random range"
    assert s["shadow_trade"]["daily_edge_vs_baseline"]["days"] == len(days)
    assert s["endpoint_label"]["daily_edge_vs_baseline"]["low"] is not None


# ----------------------------------------------------------------- isolation


FORBIDDEN = (
    "swing_trade_ml.brokers",
    "swing_trade_ml.strategies",
    "swing_trade_ml.services",
    "swing_trade_ml.workers",
    "swing_trade_ml.db.models.brain",
    "swing_trade_ml.db.models.brain_golive",
    "swing_trade_ml.db.models.safety",
    "swing_trade_ml.brain.modules",
    "swing_trade_ml.brain.service",
    "swing_trade_ml.brain.reader",
    "swing_trade_ml.brain.runner",
    "swing_trade_ml.brain.trial_journal",
)
ALLOWED_EXCEPTIONS = {"swing_trade_ml.strategies.tier"}  # a pure name-to-group helper


def _lane_files() -> list[pathlib.Path]:
    base = pathlib.Path(lanes_pkg.__file__).parent
    return [*base.glob("*.py"), base.parent.parent / "api" / "v1" / "endpoints" / "h05.py"]


def test_the_lane_imports_no_broker_order_slot_risk_or_brain_decision_code():
    files = _lane_files()
    assert len(files) >= 8
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for n in names:
                if n in ALLOWED_EXCEPTIONS or any(n.startswith(a + ".") for a in ALLOWED_EXCEPTIONS):
                    continue
                assert not n.startswith(FORBIDDEN), f"{f.name} imports {n}"


def test_the_lane_reads_only_the_strategy_table_from_the_trading_models():
    for f in _lane_files():
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "swing_trade_ml.db.models.trading":
                assert {a.name for a in node.names} == {"Strategy"}, f.name


def test_nothing_outside_the_lane_imports_it_except_its_own_owner_only_route():
    src = pathlib.Path(lanes_pkg.__file__).parents[2]
    users = []
    for f in src.rglob("*.py"):
        rel = f.relative_to(src).as_posix()
        if rel.startswith("brain/lanes/"):
            continue
        if "brain.lanes" in f.read_text(encoding="utf-8"):
            users.append(rel)
    # the owner-only route, and the scheduler's disabled-by-default hook (tested in test_h05_job.py)
    assert sorted(users) == ["api/v1/endpoints/h05.py", "workers/scheduler.py"]


def test_no_lane_file_is_part_of_the_sealed_trial_freeze():
    from trial_freeze import frozen_paths

    assert not [p for p in frozen_paths() if "lanes" in p or p.endswith("h05.py")]


def test_scoring_and_evaluating_leave_the_bot_book_untouched(db_session, lane):
    from swing_trade_ml.brokers.paper import paper_broker
    from swing_trade_ml.services.portfolio import portfolio_value_and_cash

    inst = add_stock(db_session, "BOOK")
    lane.scores["BOOK"] = 0.9
    before = (paper_broker.get_available_cash(db_session), portfolio_value_and_cash(db_session, "paper"))
    run = make_run(db_session, {"BOOK": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    future(db_session, inst)
    h05_service.evaluate(db_session, run)
    db_session.expire_all()
    assert before == (
        paper_broker.get_available_cash(db_session),
        portfolio_value_and_cash(db_session, "paper"),
    )


# ----------------------------------------------------------------- the owner-only route


def _user(db, owner: bool):
    u = User(username=f"h05-{owner}", hashed_password="x", is_active=True, is_superuser=owner, plan="pro")
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


@pytest.mark.parametrize("path", ["/api/v1/research/h05/protocol", "/api/v1/research/h05/report"])
def test_the_routes_refuse_everyone_but_the_owner(client, db_session, path):
    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers=_user(db_session, False)).status_code in (401, 403)


def test_the_owner_reads_the_protocol_and_an_empty_report(client, db_session):
    owner = _user(db_session, True)
    proto = client.get("/api/v1/research/h05/protocol", headers=owner).json()
    assert proto["title"] == "5 trading days · Existing model evaluation"
    assert proto["enabled"] is False and proto["accepted"] is False and proto["missing_values"] == []
    rep = client.get("/api/v1/research/h05/report", headers=owner).json()
    assert rep["runs"] == [] and rep["verdict"]["state"] == "not_calculated"


def test_the_lane_has_no_write_routes():
    from swing_trade_ml.api.v1.endpoints import h05

    assert {m for r in h05.router.routes for m in r.methods} == {"GET"}


# ----------------------------------------------------------------- selections are stored before their simulated entry


def test_every_scored_selection_is_stored_before_its_simulated_entry(db_session, lane):
    add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    entry_open = h05_service.entry_open_time(SIGNAL)
    assert entry_open == datetime(2026, 10, 15, 9, 15, tzinfo=IST)
    row = rows_of(db_session, run)["A1"]
    gd = db_session.execute(select(H05GroupDay)).scalars().first()
    assert row.recorded_at == NOW == gd.recorded_at and row.recorded_at < entry_open


def test_a_delayed_retry_after_the_entry_open_is_refused_so_no_opening_fill_can_be_backdated(db_session, lane):
    add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    just_before = datetime(2026, 10, 15, 9, 14, tzinfo=IST)
    just_after = datetime(2026, 10, 15, 9, 15, tzinfo=IST)
    with pytest.raises(P.ProtocolError, match="entry session has already opened"):
        h05_service.score_day(db_session, run, SIGNAL, now=just_after)
    with pytest.raises(P.ProtocolError, match="entry session has already opened"):
        h05_service.score_day(db_session, run, SIGNAL, now=datetime(2026, 10, 20, 12, tzinfo=UTC))
    assert not rows_of(db_session, run)  # nothing was written
    h05_service.score_day(db_session, run, SIGNAL, now=just_before)  # one minute earlier is still fine
    assert rows_of(db_session, run)["A1"].recorded_at == just_before


def test_a_friday_signal_may_be_recorded_over_the_weekend_but_not_after_monday_opens(db_session, lane):
    friday = date(2026, 10, 16)
    add_stock(db_session, "A1", last=friday)
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    assert h05_service.entry_open_time(friday) == datetime(2026, 10, 19, 9, 15, tzinfo=IST)
    with pytest.raises(P.ProtocolError, match="already opened"):
        h05_service.score_day(db_session, run, friday, now=datetime(2026, 10, 19, 10, tzinfo=IST))
    h05_service.score_day(db_session, run, friday, now=datetime(2026, 10, 18, 12, tzinfo=IST))
    assert rows_of(db_session, run)["A1"].recorded_at == datetime(2026, 10, 18, 12, tzinfo=IST)


def test_a_row_recorded_at_or_after_its_entry_open_is_never_simulated(db_session, lane):
    inst = add_stock(db_session, "A1")
    lane.scores["A1"] = 0.6
    run = make_run(db_session, {"A1": "large"})
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    row = rows_of(db_session, run)["A1"]
    row.recorded_at = h05_service.entry_open_time(SIGNAL)  # as if a late write had slipped through
    db_session.flush()
    future(db_session, inst, n1=(100, 103, 100, 102))
    h05_service.evaluate(db_session, run)
    assert row.trade_status == "unresolved" and "recorded_late" in row.trade_flags and row.net_return is None


def test_picks_and_baselines_use_the_same_position_size_and_a_too_expensive_stock_leaves_both(db_session, lane):
    cheap_pick = add_stock(db_session, "CHEAPPICK", price=100.0)
    cheap_other = add_stock(db_session, "CHEAPOTHER", price=100.0)
    dear_pick = add_stock(db_session, "DEARPICK", price=150_000.0)
    dear_other = add_stock(db_session, "DEAROTHER", price=150_000.0)
    lane.scores.update({"CHEAPPICK": 0.9, "DEARPICK": 0.8, "CHEAPOTHER": 0.1, "DEAROTHER": 0.05})
    run = make_run(db_session, dict.fromkeys(("CHEAPPICK", "CHEAPOTHER", "DEARPICK", "DEAROTHER"), "large"))
    h05_service.score_day(db_session, run, SIGNAL, now=NOW)
    for inst in (cheap_pick, cheap_other):
        future(db_session, inst)
    for inst in (dear_pick, dear_other):
        for k in range(1, 6):
            add_candle(db_session, inst, after(SIGNAL, k), (150_000.0,) * 4)
    h05_service.evaluate(db_session, run)
    rows = rows_of(db_session, run)
    assert rows["CHEAPPICK"].selected and rows["DEARPICK"].selected  # all four are in the top 5
    assert rows["CHEAPPICK"].net_return == pytest.approx(rows["CHEAPOTHER"].net_return)  # same rule, same number
    for sym in ("DEARPICK", "DEAROTHER"):
        assert rows[sym].trade_status == "unresolved" and "too_expensive" in rows[sym].trade_flags
        assert rows[sym].net_return is None
    summary = h05_report.summarise_group([h05_report._row(r) for r in rows.values()])
    assert summary["shadow_trade"]["counted_picks"]["unresolved"] == 2  # reported, not hidden
    assert summary["shadow_trade"]["baseline_every_eligible_stock"]["unresolved"] == 2
