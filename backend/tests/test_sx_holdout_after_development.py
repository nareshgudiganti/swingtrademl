"""Owner checklist decision 8 (sx-owner-review-checklist.md): the SEPARATE holdout run after a development-only run.

SYNTHETIC data and a stub fit only (tmp_path, no database, no real model, no real holdout, the real registry is never
written). It shows, end to end, that:

  1. a development-only run needs no holdout authorisation, scores no holdout fold and never creates the registry;
  2. a verdict on those development records alone says PENDING_HOLDOUT and never calls the holdout reader;
  3. a holdout-only run is refused without the owner's authorisation (and fits nothing), runs once with it, and writes
     only `holdout` records on the SAME dataset / arm feature lists / recipe as the development run;
  4. the development records on disk are not touched by the holdout run (bytes and read-only flags are unchanged);
  5. the final verdict reads the holdout only when the registry says COMPLETED, and PASS / INCONCLUSIVE follow R4;
  6. the holdout cannot be run a second time.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from swing_trade_ml.brain import service as _brain_service  # noqa: F401  (import order: avoids a repo circular import)
from swing_trade_ml.ml import holdout_registry as hr
from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml import sx_verdict as v

from test_holdout_registry import RECIPE, matrix, recipe_fit  # noqa: F401  (matrix is a module-scoped fixture)
from test_sector_walkforward import HOLD, lstsq_fit, spec_for  # noqa: E402

DEV_FOLDS = [f for f in HOLD if f.kind == "dev"]
HOLDOUT_ONLY = [f for f in HOLD if f.kind == "holdout"]
EID = "decision8"


@pytest.fixture(autouse=True)
def _lock_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "LOCK_PATH", tmp_path / "lk" / "l.lock")


@pytest.fixture
def ctx(tmp_path):
    protocol = tmp_path / "protocol.md"
    protocol.write_text("sx protocol text (synthetic test)", encoding="utf-8")
    approval = tmp_path / "appr.json"
    approval.write_text(
        json.dumps(
            {
                "protocol_id": "t",
                "approved_by": "unit",
                "candidate": "SX5",
                "config_sha256": spec_for().config_sha256(),
            }
        )
    )
    return {"protocol": protocol, "approval": approval, "registry": tmp_path / "reg" / "R.jsonl", "tmp": tmp_path}


def run_kwargs(ctx, sub, folds, fit=None):
    t = ctx["tmp"]
    return dict(
        fit_fn=fit or recipe_fit(),
        code_version="commit-1",
        folds=folds,
        approval_path=ctx["approval"],
        out_root=t / sub,
        marker_dir=t / (sub + "_markers"),
        holdout_protocol_path=ctx["protocol"],
        holdout_registry_path=ctx["registry"],
    )


def tree_state(root: Path) -> dict[str, tuple[str, bool]]:
    """relative path -> (sha256 of the bytes, read-only?)"""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            mode = p.stat().st_mode
            out[p.relative_to(root).as_posix()] = (
                hashlib.sha256(p.read_bytes()).hexdigest(),
                not bool(mode & stat.S_IWRITE),
            )
    return out


def inject_signal(records, c_edge, a_edge=0.0):
    """Synthetic edge written into the recorded daily excess (structure, ids and days stay the harness's own)."""
    recs = copy.deepcopy(list(records))
    for r in recs:
        for d in r["daily"] or []:
            d["excess_vs_all"] = c_edge if r["arm"] == "C_56" else a_edge
    return recs


def small_params():
    # Synthetic folds are far fewer/shorter than the 34 real ones, so the sizes (not the rules) are scaled down.
    return v.VerdictParams(
        horizon=5,
        mde_h=0.0018,
        burn_in_folds=0,
        last_fold_index=len(DEV_FOLDS) - 1,
        min_eligible_folds=1,
        min_picks=1,
        min_fold_picks=1,
        min_holdout_days=20,
    )


def test_holdout_only_run_after_a_development_only_run(matrix, ctx, monkeypatch):  # noqa: F811
    t, reg = ctx["tmp"], ctx["registry"]
    lock = t / "lk" / "l.lock"
    marker = t / "ho_markers" / "SX5.holdout_used.json"

    # 1. development-only run: no authorisation exists, none is needed, the registry is never created
    dev = wf.run_walkforward(spec_for(), matrix, **run_kwargs(ctx, "dev", DEV_FOLDS))
    assert len(dev.records) == 3 * len(DEV_FOLDS)
    assert {r["fold"]["kind"] for r in dev.records} == {"dev"}
    assert not reg.exists() and not marker.exists()
    dev_before = tree_state(t / "dev")

    # 2. dev-only verdict -> PENDING_HOLDOUT, and the holdout reader is never called
    p = small_params()
    dev_recs = inject_signal(dev.records, 0.003)

    def never():
        raise AssertionError("the holdout was read before it was COMPLETED")

    pending = v.compute_verdict(dev_recs, p, holdout_records=never, holdout_completed=False)
    assert pending["outcome"] == v.PENDING_HOLDOUT
    assert pending["r4"]["evaluated"] is False

    # 3a. holdout-only run without authorisation: refused before any fit; nothing is written
    fits = []

    def counting_fit(X, y, meta, *, seed):
        fits.append(1)
        return lstsq_fit(X, y, meta, seed=seed)

    counting_fit.recipe_sha256 = RECIPE
    seen = {}
    orig_gate = hr.gate_for_run

    def spy(**kw):
        seen.update(kw["run"])
        return orig_gate(**kw)

    monkeypatch.setattr(hr, "gate_for_run", spy)
    with pytest.raises(hr.HoldoutRefused, match="no owner authorisation"):
        wf.run_walkforward(
            spec_for(), matrix, **run_kwargs(ctx, "ho", HOLDOUT_ONLY, fit=counting_fit)
        )
    assert fits == [] and not reg.exists() and not marker.exists()

    # 3b. the owner authorises exactly the values the holdout run would bind
    bound = {
        **{k: seen[k] for k in hr.BOUND_SCALARS if k not in ("protocol_id", "protocol_sha256")},
        "protocol_id": "sx-protocol-test",
        "protocol_sha256": hr.sha256_file(ctx["protocol"]),
        "arms": {
            a: {"feature_list_sha256": s, "fit_recipe_sha256": RECIPE}
            for a, s in seen["arm_feature_shas"].items()
        },
    }
    hr.append_authorisation(
        EID,
        authorisation_text="owner authorises the one holdout run (synthetic test)",
        signer="owner",
        signed_date="2026-11-06",
        reason="decision 8 synthetic test",
        bound=bound,
        registry_path=reg,
        lock_path=lock,
    )

    # 3c. the holdout-only run: one run, only holdout records, same dataset / feature lists / recipe as development
    ho = wf.run_walkforward(spec_for(), matrix, **run_kwargs(ctx, "ho", HOLDOUT_ONLY))
    assert hr.event_states(reg, lock) == {EID: "COMPLETED"}
    assert len(ho.records) == 3 * len(HOLDOUT_ONLY)
    assert {r["fold"]["kind"] for r in ho.records} == {"holdout"}
    assert all(r["status"] == "ok" for r in ho.records)
    for key in ("dataset_sha256", "harness_config_sha256", "code_version"):
        assert ho.manifest[key] == dev.manifest[key], key
    assert {r["arm"]: r["feature_list_sha256"] for r in ho.records} == {
        r["arm"]: r["feature_list_sha256"] for r in dev.records
    }
    assert ho.manifest["fold_definition_sha256"] != dev.manifest["fold_definition_sha256"]  # each run binds its own folds

    # 4. the development records are untouched by the holdout run
    assert tree_state(t / "dev") == dev_before
    assert all(ro for _, ro in dev_before.values())  # immutable (read-only) files
    assert marker.exists()

    # 5. the final verdict reads the holdout only because the registry says COMPLETED
    def completed():
        return hr.event_states(reg, lock).get(EID) == "COMPLETED"

    holdout_good = inject_signal(ho.records, 0.002)
    final = v.compute_verdict(dev_recs, p, holdout_records=lambda: holdout_good, holdout_completed=completed)
    assert final["outcome"] == v.PASS and final["r4"]["evaluated"] and final["r4"]["met"]
    holdout_bad = inject_signal(ho.records, -0.001)
    final_bad = v.compute_verdict(dev_recs, p, holdout_records=lambda: holdout_bad, holdout_completed=completed)
    assert final_bad["outcome"] == v.INCONCLUSIVE and final_bad["r4"]["met"] is False
    # a record of the wrong kind can never stand in for the other set
    with pytest.raises(v.VerdictRefused):
        v.compute_verdict(dev_recs, p, holdout_records=dev_recs, holdout_completed=True)

    # 6. the holdout cannot be run again, with or without a fresh output folder or a new authorisation request
    with pytest.raises(hr.HoldoutRefused, match="CONSUMED"):
        wf.run_walkforward(spec_for(), matrix, **run_kwargs(ctx, "ho_again", HOLDOUT_ONLY))
    with pytest.raises(wf.HoldoutAlreadyUsed):
        wf.run_walkforward(spec_for(), matrix, **run_kwargs(ctx, "ho", HOLDOUT_ONLY))
    assert os.path.exists(marker)


def test_development_only_run_cannot_reach_into_the_holdout_window(matrix, ctx):  # noqa: F811
    """A 'dev' fold that overlaps the (real) holdout window is refused even when no holdout fold is named."""
    from datetime import date

    sneaky = wf.make_folds(date(2026, 1, 1), date(2026, 3, 1))
    with pytest.raises(hr.HoldoutRefused, match="not a holdout fold"):
        wf.run_walkforward(spec_for(), matrix, **run_kwargs(ctx, "sneak", sneaky))
    assert not ctx["registry"].exists()
