# ruff: noqa: E501, N812, C408 (long test sentences; S is the service alias)
"""Shared shadow lanes: append-only storage, top-5 recording, matured outcomes under the pinned rules."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, date, datetime, timedelta
from itertools import count
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

import swing_trade_ml.brain.ten_day  # noqa: F401  (first: replay_scoring has an import cycle that only resolves from here)

from swing_trade_ml.brain.replay_scoring import CostStress, strict_score  # isort: skip
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.lane_shadow import LaneOutcome, LanePick
from swing_trade_ml.db.models.market import Candle, Instrument
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.services import model_registry as reg
from swing_trade_ml.shadow_lanes import lane_job
from swing_trade_ml.shadow_lanes import lane_service as S

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20261102_1200_lane_shadow.py"
SIGNAL = date(2026, 9, 1)  # a Tuesday
NOW = datetime(2026, 9, 1, 13, 30, tzinfo=UTC)  # 19:00 IST: session closed, next open not yet
_tok = count(910_000_000)


def _migration():
    spec = importlib.util.spec_from_file_location("lane_migration", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(db, fn):
    with Operations.context(MigrationContext.configure(db.connection())):
        fn()


@pytest.fixture()
def db(db_session):
    # create_all builds the tables without triggers; install the migration's triggers (rolled back with the test)
    _migration().install_triggers(db_session.connection())
    return db_session


def sessions(n: int, start: date = SIGNAL) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def add_candles(db, inst, bars: dict[date, tuple[float, float, float, float]]):
    for d, (o, h, lo, c) in bars.items():
        ts = datetime(d.year, d.month, d.day, tzinfo=IST)
        db.add(
            Candle(instrument_id=inst.id, interval="day", ts=ts, open=o, high=h, low=lo, close=c, volume=1000)
        )
    db.flush()


def instrument(db, symbol):
    inst = Instrument(instrument_token=next(_tok), tradingsymbol=symbol, exchange="NSE", is_active=True)
    db.add(inst)
    db.flush()
    return inst


def ml_model(db, name="td_h10_t1", horizon=10, status="TRAINED", version="v1"):
    m = MLModel(
        name=name,
        version=version,
        algorithm="lightgbm",
        status=status,
        prediction_horizon_days=horizon,
        feature_names=["a"],
        training_symbols=["X"],
    )
    db.add(m)
    db.flush()
    return m


def fake_scorer(scores: dict[str, float | None]):
    return lambda db, inst, model, day: scores.get(inst.tradingsymbol)


def setup_universe(db, symbols):
    for s in symbols:
        instrument(db, s)


# ------------------------------------------------------------------ triggers and constraints


def _picks(db, model, n=1):
    setup_universe(db, [f"S{i}" for i in range(n)])
    S.record_day(
        db,
        model,
        "10d-large",
        {"large": [f"S{i}" for i in range(n)]},
        SIGNAL,
        NOW,
        scorer=fake_scorer({f"S{i}": 0.5 + i / 100 for i in range(n)}),
    )


def test_triggers_block_update_delete_truncate_on_both_tables(db):
    m = ml_model(db)
    _picks(db, m, 2)
    pick = db.scalars(select(LanePick)).first()
    db.add(LaneOutcome(pick_id=pick.id, matured_day=SIGNAL, status="timeout", net_return=0.01))
    db.flush()
    for table in ("lane_picks", "lane_outcomes"):
        for sql in (f"UPDATE {table} SET id = id", f"DELETE FROM {table}", f"TRUNCATE {table} CASCADE"):
            sp = db.begin_nested()
            with pytest.raises(DBAPIError) as exc:
                db.execute(text(sql))
            sp.rollback()
            assert "append-only" in str(exc.value), sql
    assert db.scalar(select(func.count()).select_from(LanePick)) == 2


def test_duplicate_model_day_symbol_and_rank_are_rejected(db):
    m = ml_model(db)
    _picks(db, m, 1)
    base = db.scalars(select(LanePick)).first()

    def clone(**kw):
        vals = dict(
            model_id=m.id,
            slot_key="10d-large",
            horizon_days=10,
            cap_group="large",
            signal_day=SIGNAL,
            symbol="ZZ",
            rank=2,
            score=0.1,
            model_version="v1",
            entry_assumption={},
            target_pct=0.06,
            stop_pct=0.035,
        )
        vals.update(kw)
        return LanePick(**vals)

    for bad in (clone(symbol=base.symbol, rank=3), clone(rank=base.rank)):
        sp = db.begin_nested()
        db.add(bad)
        with pytest.raises(Exception):  # noqa: B017 - IntegrityError on flush
            db.flush()
        sp.rollback()


# ------------------------------------------------------------------ recording


def test_top5_per_group_with_symbol_tiebreak_and_idempotent(db):
    m = ml_model(db)
    syms = ["E", "D", "C", "B", "A", "F", "G"]
    setup_universe(db, syms)
    scores = {"A": 0.9, "B": 0.9, "C": 0.8, "D": 0.7, "E": 0.6, "F": 0.5, "G": 0.4}
    r = S.record_day(db, m, "10d-large", {"large": syms}, SIGNAL, NOW, scorer=fake_scorer(scores))
    assert r["recorded"] == 5
    rows = db.scalars(select(LanePick).order_by(LanePick.rank)).all()
    assert [(p.symbol, p.rank) for p in rows] == [("A", 1), ("B", 2), ("C", 3), ("D", 4), ("E", 5)]
    assert "shortfall" not in rows[0].flags and rows[0].flags["eligible_n"] == 7
    assert rows[0].entry_assumption["entry"] == "next_session_open"
    # second call with different scores changes nothing
    r2 = S.record_day(
        db, m, "10d-large", {"large": syms}, SIGNAL, NOW, scorer=fake_scorer(dict.fromkeys(syms, 0.1))
    )
    assert r2["recorded"] == 0 and r2["skipped"]
    again = db.scalars(select(LanePick).order_by(LanePick.rank)).all()
    assert [(p.symbol, p.score) for p in again] == [(p.symbol, p.score) for p in rows]


def test_ineligible_stocks_are_skipped_and_shortfall_is_flagged(db):
    m = ml_model(db)
    setup_universe(db, ["A", "B", "C", "D"])
    scores = {"A": 0.9, "B": 0.8, "C": None, "D": float("nan")}
    r = S.record_day(
        db,
        m,
        "10d-large",
        {"large": ["A", "B", "C", "D", "MISSING"]},
        SIGNAL,
        NOW,
        scorer=fake_scorer(scores),
    )
    assert r["recorded"] == 2 and r["groups"]["large"]["shortfall"] == 3
    rows = db.scalars(select(LanePick)).all()
    assert {p.symbol for p in rows} == {"A", "B"}
    assert all(p.flags["shortfall"] == 3 and p.flags["eligible_n"] == 2 for p in rows)


def test_record_day_never_changes_the_model_row(db):
    m = ml_model(db, status="TRAINED")
    before = (m.status, m.version, m.name, m.metrics, m.prediction_horizon_days)
    n_active = db.scalar(select(func.count()).select_from(MLModel).where(MLModel.status == "ACTIVE"))
    _picks(db, m, 3)
    db.expire_all()
    m2 = db.get(MLModel, m.id)
    assert (m2.status, m2.version, m2.name, m2.metrics, m2.prediction_horizon_days) == before
    assert db.scalar(select(func.count()).select_from(MLModel).where(MLModel.status == "ACTIVE")) == n_active


def test_refuses_wrong_slot_unregistered_model_and_timing(db):
    m = ml_model(db)
    other = ml_model(db, name="swing_classifier_experimental", horizon=10, version="v9")
    setup_universe(db, ["A"])
    sc = fake_scorer({"A": 0.9})
    with pytest.raises(S.LaneError):
        S.record_day(db, m, "15d-large", {"large": ["A"]}, SIGNAL, NOW, scorer=sc)
    with pytest.raises(S.LaneError):
        S.record_day(db, other, "10d-large", {"large": ["A"]}, SIGNAL, NOW, scorer=sc)
    with pytest.raises(S.LaneError):
        S.record_day(db, m, "10d-large", {"mid": ["A"]}, SIGNAL, NOW, scorer=sc)
    late = datetime(2026, 9, 2, 4, 30, tzinfo=UTC)  # 10:00 IST next day: entry already open
    with pytest.raises(S.LaneError):
        S.record_day(db, m, "10d-large", {"large": ["A"]}, SIGNAL, late, scorer=sc)
    with pytest.raises(S.LaneError):
        S.record_day(db, m, "10d-large", {"large": ["A"]}, date(2026, 9, 3), NOW, scorer=sc)
    assert db.scalar(select(func.count()).select_from(LanePick)) == 0


# ------------------------------------------------------------------ outcomes


def flat(days, px=100.0):
    return dict.fromkeys(days, (px, px, px, px))


def bars_df(bars: dict):
    import pandas as pd

    return pd.DataFrame(
        [{"day": d, "open": o, "high": h, "low": lo, "close": c} for d, (o, h, lo, c) in sorted(bars.items())]
    )


def build_lane(db, model, slot, symbols, scores, overrides, n_days):
    """NIFTY + stocks with flat bars over the window; `overrides` replaces some days of some stocks."""
    days = sessions(n_days + 1)  # signal day + window
    nifty = instrument(db, settings.BENCHMARK_INDEX_SYMBOL)
    add_candles(db, nifty, flat(days))
    for s in symbols:
        inst = instrument(db, s)
        bars = flat(days[1:])
        bars.update(overrides.get(s, {}))
        add_candles(db, inst, bars)
    group = "mid" if slot.endswith("midcap") else "large"
    S.record_day(db, model, slot, {group: symbols}, SIGNAL, NOW, scorer=fake_scorer(scores))
    return days


def test_evaluate_only_matured_one_outcome_each_pinned_10d_rule_and_baseline(db):
    m = ml_model(db)
    syms = ["A", "B", "C", "D", "E", "F", "G"]
    scores = {s: 0.9 - i / 100 for i, s in enumerate(syms)}
    days = sessions(11)
    w = days[1:]
    ov = {
        "B": {w[1]: (100.0, 100.0, 95.0, 96.0)},  # stop (-3.5% level 96.5)
        "C": {w[2]: (100.0, 107.0, 100.0, 106.0)},  # target (+6%)
        "D": {w[1]: (100.0, 110.0, 90.0, 100.0)},  # touches both: counted as the stop, ambiguous
    }
    build_lane(db, m, "10d-large", syms, scores, ov, 10)
    # not matured: as_of one session short of the 10th window session
    assert S.evaluate_matured(db, w[-2])["outcomes"] == 0
    assert db.scalar(select(func.count()).select_from(LaneOutcome)) == 0
    out = S.evaluate_matured(db, w[-1])
    assert out["outcomes"] == 5
    assert S.evaluate_matured(db, w[-1])["outcomes"] == 0  # one outcome each, ever
    got = {
        p.symbol: o
        for p, o in db.execute(
            select(LanePick, LaneOutcome).join(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
        )
    }
    assert set(got) == {"A", "B", "C", "D", "E"}
    assert got["B"].status == "stop" and not got["B"].ambiguous
    assert got["C"].status == "target"
    assert got["D"].status == "stop" and got["D"].ambiguous
    assert got["A"].status == "timeout" and got["A"].sessions_held == 10
    # pinned rule, computed independently
    stress = CostStress(extra_slip=0.0005)
    expect = {}
    for s in syms:
        bars = flat(w)
        bars.update(ov.get(s, {}))
        expect[s] = strict_score(
            bars_df(bars), horizon=10, target=0.06, stop=0.035, half_out=None, stress=stress
        ).net_return
    assert got["B"].net_return == pytest.approx(expect["B"])
    assert got["C"].net_return == pytest.approx(expect["C"])
    baseline = sum(expect.values()) / len(expect)  # ALL eligible stocks of the group, not just the picks
    for s, o in got.items():
        assert o.baseline_net_return == pytest.approx(baseline)
        assert o.excess_return == pytest.approx(expect[s] - baseline)
    assert got["B"].gross_return > got["B"].net_return


def test_15d_rule_keeps_half_out_and_entry_is_next_open(db):
    m = ml_model(db, name="sl1_S0_t1", horizon=15)
    syms = ["A", "B"]
    days = sessions(16)
    w = days[1:]
    # +5.6% high on day 3 sells half, then the stock drifts back to flat and times out
    ov = {"A": {w[2]: (100.0, 105.6, 100.0, 101.0)}}
    build_lane(db, m, "15d-large", syms, {"A": 0.9, "B": 0.8}, ov, 15)
    assert S.evaluate_matured(db, w[-1])["outcomes"] == 2
    a = db.scalars(select(LaneOutcome).join(LanePick).where(LanePick.symbol == "A")).one()
    bars = flat(w)
    bars.update(ov["A"])
    exp = strict_score(
        bars_df(bars), horizon=15, target=0.08, stop=0.04, stress=CostStress(extra_slip=0.0005)
    )
    assert a.net_return == pytest.approx(exp.net_return)
    with_half = exp.net_return
    no_half = strict_score(
        bars_df(bars), horizon=15, target=0.08, stop=0.04, half_out=None, stress=CostStress(extra_slip=0.0005)
    ).net_return
    assert with_half != pytest.approx(no_half)  # the half-out really is part of the rule
    assert a.entry_fill == pytest.approx(100.0 * 1.0005 * 1.0005)
    assert a.matured_day == w[-1]


def test_a_missing_window_bar_gives_unresolved_and_is_excluded_from_the_baseline(db):
    m = ml_model(db)
    days = sessions(11)
    w = days[1:]
    nifty = instrument(db, settings.BENCHMARK_INDEX_SYMBOL)
    add_candles(db, nifty, flat(days))
    add_candles(db, instrument(db, "A"), flat(w))
    add_candles(db, instrument(db, "B"), flat(w[:4]))  # delisted / no data after day 4
    S.record_day(
        db, m, "10d-large", {"large": ["A", "B"]}, SIGNAL, NOW, scorer=fake_scorer({"A": 0.9, "B": 0.8})
    )
    S.evaluate_matured(db, w[-1])
    rows = {
        p.symbol: o
        for p, o in db.execute(
            select(LanePick, LaneOutcome).join(LaneOutcome, LaneOutcome.pick_id == LanePick.id)
        )
    }
    assert (
        rows["B"].status == "unresolved" and rows["B"].net_return is None and rows["B"].excess_return is None
    )
    assert rows["A"].baseline_net_return == pytest.approx(rows["A"].net_return)


# ------------------------------------------------------------------ pure helpers


def test_rank_top_pure():
    assert S.rank_top([("B", 1.0), ("A", 1.0), ("C", float("inf")), ("D", 0.5)], 2) == [
        ("A", 1.0, 1),
        ("B", 1.0, 2),
    ]
    assert S.maturity_window(sessions(5), SIGNAL, 3) == sessions(5)[1:4]
    assert S.maturity_window(sessions(3), SIGNAL, 3) is None
    assert S.group_baseline([None, 0.02, 0.04]) == pytest.approx(0.03)
    assert S.group_baseline([None]) is None


# ------------------------------------------------------------------ registry link


@pytest.mark.parametrize(
    ("name", "horizon", "slot"),
    [
        ("td_h10_v1", 10, "10d-large"),
        ("sl1_S0_a", 15, "15d-large"),
        ("sl1_S1_a", 15, "15d-large"),
        ("sl1_S2_a", 15, "15d-large"),
        ("sl1_S0M_a", 15, "15d-midcap"),
        ("sl1_S1M_a", 15, "15d-midcap"),
        ("sl1_S2M_a", 15, "15d-midcap"),
        ("swing_classifier", 5, "5d-large"),
    ],
)
def test_lane_names_map_to_slots(name, horizon, slot):
    assert reg.slot_for(name, horizon) == slot


@pytest.mark.parametrize(
    ("name", "horizon"),
    [
        ("td_h10_v1", 15),
        ("sl1_S0_a", 10),
        ("sl1_S3_a", 15),
        ("xsl1_S0_a", 15),
        ("sl1_S0", 15),
        ("td_h10", 10),
    ],
)
def test_lane_names_need_the_right_horizon_and_prefix(name, horizon):
    assert reg.slot_for(name, horizon) is None


# ------------------------------------------------------------------ migration


def test_migration_idempotent_with_triggers_and_single_head(db):
    mod = _migration()
    _run(db, mod.upgrade)
    _run(db, mod.upgrade)  # second run is safe
    n = db.scalar(text("select count(*) from pg_trigger where tgname like 'trg_lane_%' and not tgisinternal"))
    assert n == 6
    _run(db, mod.downgrade)  # no-op: tables stay
    assert db.scalar(text("select count(*) from lane_picks")) == 0
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert mod.down_revision == "mrs5p1a8c3d2"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == [mod.revision]


# ------------------------------------------------------------------ isolation and job


def test_new_modules_do_not_import_money_brain_modules_or_h05():
    files = [
        ROOT / "src/swing_trade_ml/shadow_lanes/lane_service.py",
        ROOT / "src/swing_trade_ml/shadow_lanes/lane_job.py",
        ROOT / "src/swing_trade_ml/api/v1/endpoints/lanes.py",
        ROOT / "src/swing_trade_ml/db/models/lane_shadow.py",
    ]
    banned = ("brain.modules", "services.risk", "execution", "brokers", "strategies", "h05")
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                names.append(n.module or "")
                names += [f"{n.module}.{a.name}" for a in n.names]
            elif isinstance(n, ast.Import):
                names += [a.name for a in n.names]
        assert not [m for m in names if any(b in m for b in banned)], (f.name, names)


def test_register_is_a_noop_unless_enabled_and_scheduler_does_not_call_it(monkeypatch):
    class Sched:
        def __init__(self):
            self.jobs = []

        def add_job(self, *a, **k):
            self.jobs.append((a, k))

    monkeypatch.setattr(settings, "LANE_SHADOW_ENABLED", False)
    s = Sched()
    assert lane_job.register(s) is False and s.jobs == []
    monkeypatch.setattr(settings, "LANE_SHADOW_ENABLED", True)
    assert lane_job.register(s) is True and len(s.jobs) == 1
    assert "lane_job" not in (ROOT / "src/swing_trade_ml/workers/scheduler.py").read_text(encoding="utf-8")
    assert settings.__class__.model_fields["LANE_SHADOW_ENABLED"].default is False


def test_job_picks_lane_models_without_activating_and_keeps_a_slots_model(db):
    old = ml_model(db, name="sl1_S0_a", horizon=15, version="v1")
    ml_model(db, name="swing_classifier", horizon=15, version="prod", status="ACTIVE")
    assert lane_job.lane_model_for(db, "15d-large").id == old.id
    newer = ml_model(db, name="sl1_S1_b", horizon=15, version="v2")
    assert lane_job.lane_model_for(db, "15d-large").id == newer.id
    assert lane_job.lane_model_for(db, "15d-midcap") is None
    assert old.status == "TRAINED" and newer.status == "TRAINED"
