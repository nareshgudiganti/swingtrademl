"""Pure tests for ml/sx_recipe.py on RANDOM SYNTHETIC data only. Nothing real is read or fitted."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sx_recipe as rc

from test_sector_walkforward import spec_for  # noqa: E402

pytest.importorskip("lightgbm")


def synth(n=1500, k=12, seed=0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(n, k)), columns=[f"f{i}" for i in range(k)])
    y = pd.Series((X["f0"] + rng.normal(0, 1, n) > 0.8).astype(int))
    return X, y


@pytest.fixture
def approval(tmp_path):
    sp = spec_for()
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "protocol_id": "t",
                "approved_by": "unit",
                "candidate": "SX5",
                "config_sha256": sp.config_sha256(),
            }
        )
    )
    return sp, p


def test_recipe_values_match_the_production_defaults_in_ml_train():
    """VERIFIED against ml/train._build_estimator (read from the code, not copied by hand)."""
    from swing_trade_ml.ml import train as T

    prod = T._build_estimator("lightgbm", None).get_params()
    mine = rc.SXRecipe().lgbm_params()
    for k, v in mine.items():
        if k in ("n_jobs", "subsample_freq"):
            continue
        assert prod[k] == v, k
    assert prod["n_jobs"] == -1 and mine["n_jobs"] == 1  # the one deliberate difference
    assert (
        prod["subsample_freq"] == 0 == mine["subsample_freq"]
    )  # production leaves it at the LightGBM default
    assert prod["random_state"] == 42 == rc.SXRecipe().seed


def test_canonical_json_and_hash_are_stable_and_change_with_any_field():
    r = rc.SXRecipe()
    assert (
        r.sha256()
        == rc.SXRecipe().sha256()
        == __import__("hashlib").sha256(r.canonical_json().encode()).hexdigest()
    )
    assert json.loads(r.canonical_json())["n_estimators"] == 400
    assert replace(r, n_estimators=401).sha256() != r.sha256()
    assert replace(r, n_jobs=2).sha256() != r.sha256()


def test_hash_includes_library_versions_and_a_mismatch_is_detected(approval):
    r = rc.SXRecipe()
    assert set(r.versions) == set(rc.TRACKED_LIBRARIES)
    other = replace(r, versions={**r.versions, "lightgbm": "0.0.1"})
    assert other.sha256() != r.sha256()
    rc.verify_environment(r)
    with pytest.raises(rc.RecipeVersionMismatch, match="lightgbm"):
        rc.verify_environment(other)
    sp, p = approval
    with pytest.raises(rc.RecipeVersionMismatch):
        rc.build_fit_fn(other, spec=sp, approval_path=p)


def test_build_fit_fn_is_only_available_through_the_approval_gate(approval, tmp_path):
    sp, p = approval
    with pytest.raises(sr.ResearchApprovalRequired):
        rc.build_fit_fn(rc.SXRecipe(), spec=sp, approval_path=None)
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"protocol_id": "t", "approved_by": "u", "candidate": "SX5", "config_sha256": "0" * 64})
    )
    with pytest.raises(sr.ResearchApprovalRequired):
        rc.build_fit_fn(rc.SXRecipe(), spec=sp, approval_path=bad)
    fn = rc.build_fit_fn(rc.SXRecipe(), spec=sp, approval_path=p)
    assert fn.recipe_sha256 == rc.SXRecipe().sha256()


def test_fit_fn_refuses_database_data_wrong_seed_missing_values_and_one_class(approval):
    sp, p = approval
    fn = rc.build_fit_fn(rc.SXRecipe(), spec=sp, approval_path=p)
    X, y = synth(400)
    meta = None
    with pytest.raises(rc.RecipeRefused, match="seed"):
        fn(X, y, meta, seed=1)
    Xd = X.copy()
    Xd.attrs["inputs_source"] = "database"
    with pytest.raises(rc.RecipeRefused, match="database"):
        fn(Xd, y, meta, seed=42)
    Xn = X.copy()
    Xn.iloc[3, 2] = np.nan
    with pytest.raises(rc.RecipeRefused, match="missing"):
        fn(Xn, y, meta, seed=42)
    with pytest.raises(rc.RecipeRefused, match="both classes"):
        fn(X, pd.Series(np.zeros(len(X), dtype=int)), meta, seed=42)
    pred = fn(X, y, meta, seed=42)
    with pytest.raises(rc.RecipeRefused, match="missing"):
        pred(Xn)
    out = pred(X.iloc[:50])
    assert out.shape == (50,) and np.isfinite(out).all() and ((0 <= out) & (out <= 1)).all()


def test_two_fits_give_identical_predictions(approval):
    sp, p = approval
    X, y = synth()
    fn = rc.build_fit_fn(rc.SXRecipe(), spec=sp, approval_path=p)
    a, b = fn(X, y, None, seed=42)(X), fn(X, y, None, seed=42)(X)
    assert np.array_equal(a, b)


def test_a_different_seed_changes_predictions_because_colsample_is_active():
    X, y = synth()
    a = rc.fit_parts(rc.SXRecipe(), X, y).predict(X)
    b = rc.fit_parts(replace(rc.SXRecipe(), seed=7), X, y).predict(X)
    assert not np.array_equal(a, b)


def test_subsample_is_inactive_without_subsample_freq__documented_property_not_fixed():
    """With LightGBM's default bagging frequency 0, `subsample=0.8` changes nothing. Recorded, not 'fixed'."""
    X, y = synth()
    base = rc.fit_parts(rc.SXRecipe(), X, y).predict(X)
    full = rc.fit_parts(replace(rc.SXRecipe(), subsample=1.0), X, y).predict(X)
    active = rc.fit_parts(replace(rc.SXRecipe(), subsample_freq=1), X, y).predict(X)
    assert np.array_equal(base, full)
    assert not np.array_equal(base, active)


def test_scaler_and_class_weights_use_training_rows_only():
    X, y = synth(1200)
    tr, te = X.iloc[:900], X.iloc[900:].copy()
    fitted = rc.fit_parts(rc.SXRecipe(), tr, y.iloc[:900])
    mean0, scale0 = fitted.scaler.mean_.copy(), fitted.scaler.scale_.copy()
    p_before = fitted.predict(tr)
    te.iloc[:, :] = 1e6  # mutate the test rows wildly
    fitted.predict(te)
    assert np.array_equal(fitted.scaler.mean_, mean0) and np.array_equal(fitted.scaler.scale_, scale0)
    assert np.allclose(mean0, tr.to_numpy().mean(axis=0)) and not np.allclose(
        mean0, X.to_numpy().mean(axis=0)
    )
    assert np.array_equal(fitted.predict(tr), p_before)
    # a fit on identical training rows is unaffected by whatever the other rows held
    X2 = X.copy()
    X2.iloc[900:, :] = -5.0
    again = rc.fit_parts(rc.SXRecipe(), X2.iloc[:900], y.iloc[:900])
    assert np.array_equal(again.predict(tr), p_before)


def test_balanced_class_weights_equal_explicit_weights_from_the_training_labels():
    from lightgbm import LGBMClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.utils.class_weight import compute_sample_weight

    X, y = synth(900)
    fitted = rc.fit_parts(rc.SXRecipe(), X, y)
    r = rc.SXRecipe()
    params = {**r.lgbm_params(), "class_weight": None}
    sc = StandardScaler().fit(X.to_numpy())
    est = LGBMClassifier(**params).fit(
        sc.transform(X.to_numpy()), y, sample_weight=compute_sample_weight("balanced", y)
    )
    assert np.array_equal(est.predict_proba(sc.transform(X.to_numpy()))[:, 1], fitted.predict(X))


def test_recipe_states_no_tuning_no_early_stopping_no_calibration_no_validation():
    r = rc.SXRecipe()
    assert (r.tuning, r.early_stopping, r.calibration, r.validation_split) == ("none",) * 4
    assert "eval_set" not in json.dumps(r.lgbm_params())


def test_recipe_module_is_isolated_from_production_and_the_database():
    import inspect

    src = inspect.getsource(rc)
    for bad in ("ml.predict", "SessionLocal", "brain.", "kite", "paper"):
        assert bad not in src, bad
