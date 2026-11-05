"""2026-11-06 owner decisions: C_56 (drop the redundant sector_ret_20d_vs_nifty) and R_37 (verified against the saved model 2).

Research only. No model is fitted, no database is read (the prod facts were read once, read-only, and saved as evidence)."""

from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features
from test_h05_historical_features import SNAPSHOT, SNAPSHOT_SHA256, _context, _ohlcv

REPO = Path(__file__).resolve().parents[2]
EVID = REPO / "docs/brain/evidence/sector_prep"
DROPPED = "sector_ret_20d_vs_nifty"


# ---------------------------------------------------------------------------------------------- C_56
def test_the_challenger_is_the_53_plus_three_sector_inputs():
    assert DROPPED not in sr.SECTOR_COLUMNS and DROPPED not in sr.RESEARCH_COLUMNS
    assert sr.SECTOR_COLUMNS == ("sector_ret_10d_vs_nifty", "sector_rank_10d", "stock_vs_sector_10d")
    assert (
        tuple(sr.RESEARCH_COLUMNS) == (*FEATURE_COLUMNS, *sr.SECTOR_COLUMNS)
        and len(sr.RESEARCH_COLUMNS) == 56
    )
    assert wf.ARM_C == "C_56" and wf.ARM_IDS == ("A_53", "R_37", "C_56")
    arms = wf.build_arms()
    assert [len(arms[a]) for a in wf.ARM_IDS] == [53, 37, 56]


def test_the_builder_still_computes_all_four_but_the_research_path_takes_three():
    assert len(sf.FEATURE_NAMES) == 4 and DROPPED in sf.FEATURE_NAMES
    assert sf.REDUNDANT_WITH_EXISTING == (DROPPED,)
    assert sf.RESEARCH_FEATURE_NAMES == sr.SECTOR_COLUMNS


def _frames(n=330, gap=None):
    stock, nifty, sector = _ohlcv(7, n), _ohlcv(101, n), _ohlcv(202, n)
    if gap is not None:
        sector = sector.drop(sector.index[gap[0] : gap[1]]).reset_index(drop=True)
    return stock, nifty, sector


def _existing_vs_new(stock, nifty, sector):
    _, _, vix, breadth = _context()
    ex = build_features(stock, nifty, sector, vix, breadth)
    old = pd.Series(
        (ex["relative_strength_20d"] - ex["sector_relative_strength_20d"]).to_numpy(),
        index=pd.DatetimeIndex(stock["ts"]).tz_convert("Asia/Kolkata").tz_localize(None).normalize(),
    )
    new = sf.build_sector_features(
        sf.close_series_from_candles(stock[["ts", "close"]]),
        sf.close_series_from_candles(nifty[["ts", "close"]]),
        {"S": sf.close_series_from_candles(sector[["ts", "close"]])},
        "S",
        rank_universe=("S",),
    )[DROPPED].reindex(old.index)
    return old, new


def test_identity_is_exact_when_the_sector_index_has_every_session():
    old, new = _existing_vs_new(*_frames())
    ok = old.notna() & new.notna()
    assert ok.sum() > 250
    assert float((old[ok] - new[ok]).abs().max()) < 1e-12


def test_a_gap_in_the_sector_index_makes_the_two_definitions_differ_for_about_20_sessions_only():
    """The existing input counts 20 ROWS of the sector index; the sector input counts 20 SESSIONS of the shared
    calendar. Same closes, different window when the index lacks sessions. This is the cause of the 13 audit rows."""
    old, new = _existing_vs_new(
        *_frames(gap=(150, 153))
    )  # three consecutive sessions missing from the sector index
    both = old.notna() & new.notna()
    diff = (old - new).abs()[both]
    assert (diff > 1e-9).sum() >= 1
    bad_pos = [old.index.get_loc(d) for d in diff.index[diff > 1e-9]]
    assert (
        min(bad_pos) >= 150 and max(bad_pos) <= 150 + 3 + 20
    )  # only inside the gap and the 20 sessions after it
    assert (
        diff[[old.index.get_loc(d) < 150 or old.index.get_loc(d) > 175 for d in diff.index]] < 1e-12
    ).all()


def test_the_13_audit_rows_are_one_stock_one_sector_index_gap_and_a_definition_difference():
    d = json.loads((EVID / "c56_decision_v3.json").read_text("utf-8"))
    assert d["rows_total"] == 45930 and d["rows_not_equal"] == 13 and len(d["rows"]) == 13
    assert d["classification"] == "definition_difference_not_new_information"
    assert {r["symbol"] for r in d["rows"]} == {"APOLLOHOSP"}
    assert {r["sector_index"] for r in d["rows"]} == {"NIFTY HEALTHCARE"}
    assert max(abs(r["difference"]) for r in d["rows"]) == pytest.approx(d["max_abs_difference"])
    assert d["decision"].startswith("REMOVE sector_ret_20d_vs_nifty")
    assert d["rows_added_by_dropping_the_input"] and len(d["rows_added_by_dropping_the_input"]) == 5


def test_no_old_arm_name_is_left_in_code_manifests_or_new_evidence():
    for p in (
        REPO / "backend/src/swing_trade_ml/ml/sector_walkforward.py",
        REPO / "backend/src/swing_trade_ml/ml/sector_research.py",
    ):
        txt = p.read_text("utf-8")
        assert txt.count("C_57") == txt.count("renamed from C_57"), (
            p
        )  # the old name appears only as a rename note
    for p in EVID.glob("*_v3*.json"):
        txt = p.read_text("utf-8")
        assert txt.count("C_57") == txt.count("renamed from C_57"), p
    for p in (REPO / "docs/superpowers/specs").glob("2026-11-05-sx*"):
        txt = p.read_text("utf-8")
        assert txt.count("C_57") == txt.count("formerly C_57") + txt.count("renamed from C_57"), p


# ---------------------------------------------------------------------------------------------- R_37
SAVED = EVID / "model2_saved_features_v1.json"


def test_r37_equals_the_feature_list_saved_in_prod_model_2_in_count_names_and_order():
    saved = json.loads(SAVED.read_text("utf-8"))
    names = saved["model_2"]["feature_names"]
    assert len(names) == 37 and len(set(names)) == 37
    assert list(wf.REFERENCE_37_COLUMNS) == names  # same names AND same order
    assert [c for c in FEATURE_COLUMNS if c in names] == names  # saved order is the order of the 53
    assert tuple(wf.build_arms()["R_37"]) == tuple(names)
    assert saved["model_2"]["hyperparameters"] == {}
    for k in ("model_16", "model_17"):
        assert len(saved[k]["feature_names"]) == 46 and set(saved[k]["feature_names"]) <= set(FEATURE_COLUMNS)
    assert saved["model_16"]["feature_names"] == saved["model_17"]["feature_names"]


def test_r37_is_labelled_a_research_reference_with_its_known_differences():
    assert wf.ARM_LABELS["R_37"] == "R_37: a 37-feature RESEARCH REFERENCE, not an exact production replay"
    assert wf.ARM_LABELS["A_53"] == "A_53" and wf.ARM_LABELS["C_56"] == "C_56"
    known = {d["input"] for d in wf.R37_KNOWN_SEMANTIC_DIFFERENCES}
    assert "obv_slope" in known
    assert all(d["input"] in wf.REFERENCE_37_COLUMNS for d in wf.R37_KNOWN_SEMANTIC_DIFFERENCES)
    assert wf.R37_SAVED_FEATURES_EVIDENCE.endswith("model2_saved_features_v1.json")


def test_only_obv_slope_of_the_37_differs_between_the_training_era_code_and_the_current_builder():
    raw = SNAPSHOT.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(raw).hexdigest() == SNAPSHOT_SHA256
    old = types.ModuleType("old")
    exec(compile(raw.decode("utf-8"), "old", "exec"), old.__dict__)
    stock, ctx = _ohlcv(7), _context()
    then, now = old.build_features(stock, *ctx), build_features(stock, *ctx)
    differing = [
        c
        for c in wf.REFERENCE_37_COLUMNS
        if not np.allclose(then[c].fillna(-9e9), now[c].fillna(-9e9), rtol=1e-12, atol=0)
    ]
    assert differing == [d["input"] for d in wf.R37_KNOWN_SEMANTIC_DIFFERENCES if d["kind"] == "formula"]


def test_a53_and_r37_manifests_are_pinned_and_unchanged_by_the_c56_decision():
    """Pinned on 2026-11-06 from the values computed BEFORE the C_56 edit (git 6731fb6)."""
    arms = wf.build_arms()
    pins = {
        "A_53": (
            "f5a8d398d56e47d8bce33943ea78d50d949933022d12c2cb6ef24f5792086f29",
            "3bd35e8549ebddcea9f52ee680530cdef80a4bb524cf74b1a04c328e1a7141c4",
        ),
        "R_37": (
            "0615e2fb6c1c9ae120d1455895ad39d3422fcc1bd2053c4bd4b1a1476946d122",
            "b00fc7076853bbd56ba3f32d254a57cfbc89ef19969f27564c4d5ac4939574c5",
        ),
    }
    for arm, (manifest, flist) in pins.items():
        assert hashlib.sha256(json.dumps(list(arms[arm])).encode()).hexdigest() == manifest
        assert wf.feature_list_sha256(arms[arm]) == flist
