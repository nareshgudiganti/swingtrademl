"""RESEARCH-ONLY: the ONE fixed model recipe for the sector experiments (SX5 / SX10), as data plus a fit-function builder.

NOT production; nothing in the app imports it. NO model is fitted by importing or building anything here. The recipe
is the same LightGBM recipe the production-style models use (ml/train._build_estimator defaults via
ml/train.fit_and_score), written out in full so that it can be reviewed, hashed and bound into the holdout
registry. Documents: docs/superpowers/specs/2026-11-06-sx-model-recipe-FINAL-DRAFT.md (unsigned).

  * Frozen dataclass; canonical JSON; sha256 that includes the exact library versions.
  * `build_fit_fn` returns the harness's `fit_fn(X, y, meta, *, seed)` ONLY through the approval gate of
    sector_research (an approval file naming this exact DatasetSpec), after checking the installed library versions
    equal the recipe's. The returned function refuses data stamped as coming from the database unless the caller
    explicitly passes allow_real_data=True (a later, signed step; a best-effort second guard, the harness gate is
    the real one).
  * Every fitted transformation (the scaler, the balanced class weights) is computed from the TRAINING rows passed to
    fit only. Missing values are refused (never imputed): the harness drops such rows before the matrix exists.
  * No tuning, no early stopping, no validation split, no calibration: nothing here looks at any outcome other than
    the training labels.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from importlib import metadata
from typing import Any

import numpy as np
import pandas as pd

from swing_trade_ml.ml import sector_research as sr

RECIPE_VERSION = "sx_recipe_v1"
TRACKED_LIBRARIES = ("lightgbm", "scikit-learn", "numpy", "pandas", "scipy")


class RecipeVersionMismatch(RuntimeError):
    pass


class RecipeRefused(RuntimeError):
    pass


def installed_versions() -> dict[str, str]:
    return {lib: metadata.version(lib) for lib in TRACKED_LIBRARIES}


@dataclass(frozen=True)
class SXRecipe:
    recipe_version: str = RECIPE_VERSION
    algorithm: str = "lightgbm.LGBMClassifier (binary)"
    n_estimators: int = 400
    learning_rate: float = 0.05
    max_depth: int = 6
    num_leaves: int = 31
    subsample: float = 0.8
    # Left at LightGBM's default 0 exactly as production leaves it: with bagging frequency 0, `subsample` is NOT applied
    # (documented property, verified on synthetic data; deliberately not "fixed").
    subsample_freq: int = 0
    colsample_bytree: float = 0.8
    min_child_samples: int = 50
    reg_alpha: float = 0.1
    reg_lambda: float = 0.1
    class_weight: str = "balanced"  # computed by sklearn from the y of the training rows passed to fit
    n_jobs: int = 1  # production uses -1; 1 is chosen for run-to-run determinism
    seed: int = 42
    scaler: str = "sklearn.preprocessing.StandardScaler, fitted on training rows only"
    missing_values: str = (
        "refused (no imputation); rows with a missing input are dropped before the matrix exists"
    )
    feature_selection: str = "none (ordered column lists come from the arm manifests)"
    validation_split: str = "none"
    early_stopping: str = "none"
    tuning: str = "none"
    calibration: str = "none"
    versions: dict[str, str] = field(default_factory=installed_versions)

    def to_config(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_json(self) -> str:
        return json.dumps(self.to_config(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def lgbm_params(self) -> dict[str, Any]:
        return {
            "n_estimators": self.n_estimators,
            "learning_rate": self.learning_rate,
            "max_depth": self.max_depth,
            "num_leaves": self.num_leaves,
            "subsample": self.subsample,
            "subsample_freq": self.subsample_freq,
            "colsample_bytree": self.colsample_bytree,
            "min_child_samples": self.min_child_samples,
            "reg_alpha": self.reg_alpha,
            "reg_lambda": self.reg_lambda,
            "class_weight": self.class_weight,
            "random_state": self.seed,
            "n_jobs": self.n_jobs,
            "verbose": -1,
        }


def verify_environment(recipe: SXRecipe) -> None:
    """Refuse if any tracked library is not the exact version the recipe (and so its hash) names."""
    have = installed_versions()
    bad = {k: (recipe.versions.get(k), have[k]) for k in have if recipe.versions.get(k) != have[k]}
    if bad:
        raise RecipeVersionMismatch(f"library versions differ from the recipe (recipe, installed): {bad}")


@dataclass(frozen=True)
class FittedSX:
    scaler: Any
    estimator: Any

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        arr = _as_array(X, "X_test")
        return self.estimator.predict_proba(self.scaler.transform(arr))[:, 1]


def _as_array(X, name: str) -> np.ndarray:
    arr = np.asarray(X, dtype="float64")
    if not np.isfinite(arr).all():
        raise RecipeRefused(f"{name} holds missing or non-finite values: refused (no imputation)")
    return arr


def fit_parts(recipe: SXRecipe, X: pd.DataFrame, y) -> FittedSX:
    """The whole recipe, on the rows passed in and nothing else. Scaler and class weights see only these rows."""
    from lightgbm import LGBMClassifier
    from sklearn.preprocessing import StandardScaler

    xa = _as_array(X, "X_train")
    ya = np.asarray(y)
    if set(np.unique(ya).tolist()) != {0, 1}:
        raise RecipeRefused("the training labels must contain both classes 0 and 1")
    scaler = StandardScaler().fit(xa)
    est = LGBMClassifier(**recipe.lgbm_params()).fit(scaler.transform(xa), ya)
    return FittedSX(scaler, est)


def build_fit_fn(
    recipe: SXRecipe, *, spec: sr.DatasetSpec, approval_path=None, allow_real_data: bool = False
):
    """The harness `fit_fn`. Constructible only through sector_research's approval gate for this exact `spec`."""
    ok, why = sr._approval_valid(spec, approval_path)
    if not ok:
        raise sr.ResearchApprovalRequired(f"sx_recipe.build_fit_fn refused: {why}")
    verify_environment(recipe)

    def fit_fn(X: pd.DataFrame, y, meta, *, seed: int):
        if seed != recipe.seed:
            raise RecipeRefused(f"seed must be {recipe.seed} (the recipe's), got {seed}")
        if not allow_real_data and getattr(X, "attrs", {}).get("inputs_source") == "database":
            raise RecipeRefused("this fit function is not enabled for database-built data in this session")
        fitted = fit_parts(recipe, X, y)
        return fitted.predict

    fit_fn.recipe_sha256 = recipe.sha256()
    fit_fn.recipe = recipe
    return fit_fn
