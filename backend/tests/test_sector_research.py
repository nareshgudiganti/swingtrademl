"""Research-only sector path (SX5 / SX10): pure tests. NO model is fitted anywhere in this file."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr

SRC = Path(sr.__file__).resolve().parents[1]  # .../swing_trade_ml
N = 520
DAYS = pd.bdate_range("2024-01-01", periods=N)
STOCKS = ["TCS", "HDFCBANK", "SUNPHARMA", "ASIANPAINT"]  # ASIANPAINT: unmapped, must give no rows


def _ohlcv(rng, start=100.0):
    close = start * np.exp(np.cumsum(rng.normal(0.0003, 0.012, N)))
    open_ = close * (1 + rng.normal(0, 0.003, N))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, N)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, N)))
    ts = [pd.Timestamp(d.date().isoformat() + " 00:00", tz="Asia/Kolkata").tz_convert("UTC") for d in DAYS]
    return pd.DataFrame(
        {
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1e5, 1e6, N),
        }
    )


@pytest.fixture(scope="module")
def inputs():
    rng = np.random.default_rng(42)
    frames = {u: _ohlcv(rng) for u in sf.DEFAULT_RANK_UNIVERSE}
    raw = {s: _ohlcv(rng, 50.0 + 30 * i) for i, s in enumerate(STOCKS)}
    nifty, vix = _ohlcv(rng), _ohlcv(rng, 15.0)
    breadth = pd.DataFrame(
        {
            "ts": nifty["ts"],
            "breadth_pct_above_sma50": rng.uniform(0.2, 0.8, N),
            "breadth_advance_pct": rng.uniform(0.2, 0.8, N),
        }
    )
    return sr.ResearchInputs(raw=raw, index_df=nifty, index_frames=frames, vix_df=vix, breadth_df=breadth)


def _spec(**kw):
    base = dict(
        candidate="SX5",
        symbols=tuple(STOCKS),
        horizon_days=5,
        target_return=0.02,
        stop_return=0.02,
        data_cutoff=date(2026, 1, 30),
        min_history=252,
    )
    base.update(kw)
    return sr.DatasetSpec(**base)


@pytest.fixture(scope="module")
def matrix(inputs):
    return sr.assemble_training_matrix(_spec(), inputs)


def test_matrix_has_existing_columns_then_three_sector_columns(matrix):
    assert list(sr.RESEARCH_COLUMNS) == [*sr.FEATURE_COLUMNS, *sr.SECTOR_COLUMNS]
    assert len(sr.RESEARCH_COLUMNS) == len(sr.FEATURE_COLUMNS) + 3
    assert not matrix[list(sr.RESEARCH_COLUMNS)].isna().to_numpy().any()
    assert len(matrix) > 300
    assert "ASIANPAINT" not in set(matrix["symbol"])  # unmapped stays missing -> row dropped, never guessed
    assert matrix["decision_date"].min() >= DAYS[252]  # warm-up skipped


def test_asof_row_has_same_columns_and_same_values_as_training_row(matrix, inputs):
    checked = 0
    for sym in ("TCS", "SUNPHARMA"):
        sub = matrix[matrix["symbol"] == sym]
        for t in list(sub["decision_date"].iloc[[0, 50, 120, -1]]):
            row = sr.assemble_asof_row(inputs, sym, t)
            assert row is not None
            assert list(row.columns) == list(sr.RESEARCH_COLUMNS)
            train = sub[sub["decision_date"] == t][list(sr.RESEARCH_COLUMNS)].reset_index(drop=True)
            # the three sector inputs: exactly equal (one builder)
            pd.testing.assert_frame_equal(
                row[list(sr.SECTOR_COLUMNS)], train[list(sr.SECTOR_COLUMNS)], check_exact=True
            )
            # existing columns: same code, history cut at t instead of full: equal to float precision
            np.testing.assert_allclose(row.to_numpy(float), train.to_numpy(float), rtol=1e-9, atol=1e-12)
            checked += 1
    assert checked == 8


def test_asof_row_is_none_when_stock_has_no_bar_or_is_unmapped(inputs):
    assert sr.assemble_asof_row(inputs, "TCS", DAYS[300]) is not None
    assert sr.assemble_asof_row(inputs, "TCS", pd.Timestamp("2024-01-06")) is None  # Saturday
    assert sr.assemble_asof_row(inputs, "ASIANPAINT", DAYS[400]) is None  # sector inputs missing: no guess
    assert sr.assemble_asof_row(inputs, "NOSUCH", DAYS[400]) is None


def test_asof_row_refuses_when_the_decision_day_index_bars_are_missing(inputs):
    t = DAYS[400]
    assert sr.assemble_asof_row(inputs, "TCS", t) is not None
    # NIFTY 50 has no bar for the decision day: its value would be a stale carry-forward, so refuse
    no_nifty = sr.ResearchInputs(
        inputs.raw,
        inputs.index_df[inputs.index_df.index != 400],
        inputs.index_frames,
        inputs.vix_df,
        inputs.breadth_df,
    )
    assert sr.assemble_asof_row(no_nifty, "TCS", t) is None
    # the stock's own sector index (TCS -> NIFTY IT) has no bar that day
    frames = dict(inputs.index_frames)
    frames["NIFTY IT"] = frames["NIFTY IT"][frames["NIFTY IT"].index != 400]
    no_sector = sr.ResearchInputs(inputs.raw, inputs.index_df, frames, inputs.vix_df, inputs.breadth_df)
    assert sr.assemble_asof_row(no_sector, "TCS", t) is None


def test_asof_row_refuses_a_day_whose_bar_may_still_be_partial(inputs):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    t = DAYS[400]  # a business day (weekday)
    ist = ZoneInfo("Asia/Kolkata")
    during = datetime(t.year, t.month, t.day, 14, 0, tzinfo=ist)
    after = datetime(t.year, t.month, t.day, 15, 41, tzinfo=ist)
    assert sr.assemble_asof_row(inputs, "TCS", t, now=during) is None  # the day's bar is not final yet
    assert sr.assemble_asof_row(inputs, "TCS", t, now=after) is not None
    assert sr.assemble_asof_row(inputs, "TCS", t) is not None  # no clock given: research replay, unchanged


def test_asof_row_ignores_future_data(inputs):
    t = DAYS[400]
    a = sr.assemble_asof_row(inputs, "TCS", t)
    raw = {k: v.copy() for k, v in inputs.raw.items()}
    raw["TCS"].loc[raw["TCS"].index > 400, "close"] *= 5.0
    frames = {k: v.copy() for k, v in inputs.index_frames.items()}
    for v in frames.values():
        v.loc[v.index > 400, "close"] *= 3.0
    mutated = sr.ResearchInputs(raw, inputs.index_df, frames, inputs.vix_df, inputs.breadth_df)
    pd.testing.assert_frame_equal(a, sr.assemble_asof_row(mutated, "TCS", t), check_exact=True)


def test_exclusions_cutoff_and_label_rule_are_applied(inputs, matrix):
    drop = {("TCS", matrix[matrix["symbol"] == "TCS"]["decision_date"].iloc[10].strftime("%Y-%m-%d"))}
    m2 = sr.assemble_training_matrix(_spec(exclusions=frozenset(drop)), inputs)
    assert len(m2) == len(matrix) - 1
    early = sr.assemble_training_matrix(_spec(data_cutoff=DAYS[400].date()), inputs)
    ends = pd.to_datetime(early["label_end_ts"], utc=True)
    assert (ends <= pd.Timestamp(f"{DAYS[400].date()} 23:59", tz="Asia/Kolkata")).all()
    assert len(early) < len(matrix)
    with pytest.raises(ValueError):
        _spec(candidate="SX10")  # SX10 is a 10-day candidate
    with pytest.raises(ValueError):
        _spec(candidate="B1")  # Phase B's B1 is a different thing


# ------------------------------------------------------------------ dry run, refusal, approval
def _tree(root: Path):
    return sorted(str(p) for p in root.rglob("*")) if root.exists() else None


def test_dry_run_is_default_and_writes_nothing(matrix, tmp_path):
    before_default = _tree(sr.RESEARCH_ROOT)
    plan = sr.train_research_candidate(_spec(), matrix, out_root=tmp_path)
    assert plan["dry_run"] is True and plan["rows"] == len(matrix) and plan["candidate"] == "SX5"
    assert plan["config_sha256"] == _spec().config_sha256() and plan["matrix_sha256"]
    assert "no approval file" in plan["approval"]
    assert list(tmp_path.iterdir()) == []
    plan2 = sr.train_research_candidate(_spec(), matrix)  # default location: still nothing created
    assert _tree(sr.RESEARCH_ROOT) == before_default and plan2["dry_run"]


def test_refuses_to_train_without_an_approval_file_and_calls_no_fit(matrix, tmp_path, monkeypatch):
    called = []

    def fit(x, y):
        called.append(1)
        return b"x"

    monkeypatch.delenv(sr.APPROVAL_ENV, raising=False)
    with pytest.raises(sr.ResearchApprovalRequired):
        sr.train_research_candidate(_spec(), matrix, dry_run=False, out_root=tmp_path, fit_fn=fit)
    monkeypatch.setenv(sr.APPROVAL_ENV, str(tmp_path / "does_not_exist.json"))  # env path that does not exist
    with pytest.raises(sr.ResearchApprovalRequired):
        sr.train_research_candidate(_spec(), matrix, dry_run=False, out_root=tmp_path, fit_fn=fit)
    assert called == [] and list(tmp_path.iterdir()) == []


def test_approval_must_match_candidate_and_exact_configuration(matrix, tmp_path):
    spec = _spec()
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"protocol_id": "p", "approved_by": "o", "candidate": "SX5", "config_sha256": "0" * 64})
    )
    out = tmp_path / "o"
    with pytest.raises(sr.ResearchApprovalRequired, match="does not match"):
        sr.train_research_candidate(
            spec, matrix, dry_run=False, approval_path=bad, out_root=out, fit_fn=lambda x, y: b"x"
        )
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"protocol_id": "p"}))
    with pytest.raises(sr.ResearchApprovalRequired, match="lacks"):
        sr.train_research_candidate(
            spec, matrix, dry_run=False, approval_path=partial, out_root=out, fit_fn=lambda x, y: b"x"
        )
    assert not out.exists()


def test_with_valid_token_and_stub_writes_only_a_manifest_under_the_research_root(matrix, tmp_path):
    spec = _spec()
    tok = tmp_path / "ok.json"
    tok.write_text(
        json.dumps(
            {
                "protocol_id": "TEST-STUB",
                "approved_by": "unit-test",
                "candidate": "SX5",
                "config_sha256": spec.config_sha256(),
            }
        )
    )
    seen = {}

    def stub(X, y):  # a stub, NOT a model fit
        seen["shape"] = X.shape
        return b"stub-artifact"

    out = tmp_path / "research_models"
    man = sr.train_research_candidate(
        spec, matrix, dry_run=False, approval_path=tok, out_root=out, fit_fn=stub
    )
    assert seen["shape"] == (len(matrix), len(sr.RESEARCH_COLUMNS))
    assert man["artifact_sha256"] == hashlib.sha256(b"stub-artifact").hexdigest()
    assert man["data_cutoff"] == "2026-01-30" and man["version"] == sr.RESEARCH_VERSION and man["config"]
    files = [p for p in out.rglob("*") if p.is_file()]
    assert {p.name for p in files} == {"artifact.bin", "manifest.json"}
    on_disk = json.loads(next(p for p in files if p.name == "manifest.json").read_text())
    assert on_disk["artifact_sha256"] == man["artifact_sha256"]
    # no recipe supplied -> refuses even with a valid token
    with pytest.raises(NotImplementedError):
        sr.train_research_candidate(spec, matrix, dry_run=False, approval_path=tok, out_root=tmp_path / "o2")


def test_refuses_production_model_locations(matrix, tmp_path):
    from swing_trade_ml.core.config import settings

    for bad in (
        Path(settings.MODEL_ARTIFACT_DIR),
        tmp_path / "ml_models",
        tmp_path / "x" / "ML_Models" / "y",
    ):
        with pytest.raises(sr.ResearchPathRefused):
            sr.train_research_candidate(_spec(), matrix, out_root=bad)  # even a dry run refuses
    assert sr.RESEARCH_ROOT.parts[-3:] == ("backend", "data", "research_models")


def test_research_root_is_gitignored():
    r = subprocess.run(
        ["git", "check-ignore", "-q", "backend/data/research_models/SX5/manifest.json"],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
    )
    assert r.returncode == 0


# ------------------------------------------------------------------ hard guard: nothing imports it
RESEARCH_SIBLINGS = {"sector_research.py", "sector_walkforward.py", "feature_audit.py"}


def test_no_production_module_imports_sector_research():
    offenders = []
    for p in SRC.rglob("*.py"):
        if p.name in RESEARCH_SIBLINGS:  # the research-only modules may use each other; nothing else may
            continue
        if re.search(r"sector_research", p.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(p.relative_to(SRC)))
    assert offenders == []
    # the frozen feature / predict / dataset files do not use the sector builder either
    for rel in ("ml/features.py", "ml/predict.py", "ml/dataset.py"):
        txt = (SRC / rel).read_text(encoding="utf-8")
        assert "sector_features" not in txt and "sector_research" not in txt
    for area in ("workers", "strategies", "brain", "shadow_lanes", "services", "api"):
        for p in (SRC / area).rglob("*.py"):
            txt = p.read_text(encoding="utf-8", errors="ignore")
            assert "sector_research" not in txt and "ml.sector_features" not in txt, str(p)
    sched = (SRC / "workers" / "scheduler.py").read_text(encoding="utf-8")
    assert "sector_research" not in sched


def test_module_does_not_use_the_database_layer_or_production_predict():
    txt = (SRC / "ml" / "sector_research.py").read_text(encoding="utf-8")
    for forbidden in ("sqlalchemy", "swing_trade_ml.db", "ml.predict", "ml.trainer", "Session"):
        assert forbidden not in txt, forbidden
    assert "import psycopg" not in txt  # the read-only loader reuses sector_features_loader
