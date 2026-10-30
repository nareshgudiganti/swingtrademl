# backend/src/swing_trade_ml/brain/lanes/h05_models.py
# ruff: noqa: E501, N812 (short P / R import aliases and long report sentences, as in brain/five_day.py)
"""Which model scores which stock in the h05 lane, and proof that the models are the ones we froze.

Read-only. Nothing here trains, calibrates, activates or edits a model. A stock is routed to the model of
its own size group and never to another: a missing or mismatched model is a refusal, not a fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session

from swing_trade_ml.brain.lanes import h05_protocol as P
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.ml import MLModel
from swing_trade_ml.db.models.trading import Strategy
from swing_trade_ml.ml.features import FEATURE_COLUMNS
from swing_trade_ml.strategies.tier import cap_tier

# strategies/tier.py names the groups "large" / "midcap" / "smallcap"
_TIER_TO_GROUP = {"large": "large", "midcap": "mid", "smallcap": "small"}


@dataclass
class VerifiedModel:
    group: str
    model_id: int
    name: str
    version: str
    status: str
    sha256: str
    feature_names: list[str]
    train_end: Any
    training_symbols: frozenset[str]
    artifact_file: Path
    scorer: Any = field(repr=False, default=None)  # what predict_instrument needs: id + artifact_path
    bundle: Any = field(repr=False, default=None)  # the loaded artifact (estimator, scaler, feature_names)
    train_start: Any = None

    def identity(self) -> dict:
        """What is stored with a run and compared again on every later day."""
        return {
            "group": self.group,
            "model_id": self.model_id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "sha256": self.sha256,
            "n_features": len(self.feature_names),
            "features_sha256": hashlib.sha256(json.dumps(self.feature_names).encode()).hexdigest(),
            "train_end": str(self.train_end),
            "n_training_symbols": len(self.training_symbols),
            "libraries": _library_versions(),
            "primary_basis": P.PRIMARY_BASIS,
            "feature_code": P.FEATURE_CODE_SHA256,
        }


def _library_versions() -> dict[str, str]:
    """A different scikit-learn or LightGBM can nudge a score; a change between days stops the lane."""
    import lightgbm
    import sklearn

    return {"scikit-learn": sklearn.__version__, "lightgbm": lightgbm.__version__}


def artifact_file(row: MLModel) -> Path:
    """The model file inside this machine's model folder. The registry keeps the path as written on the
    machine that trained it (the server's container path); only the file name is used here."""
    name = os.path.basename((row.artifact_path or "").replace("\\", "/"))
    return settings.model_dir / name


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_models(db: Session) -> dict[str, VerifiedModel]:
    """All three models, or ProtocolError naming the first thing that is wrong."""
    from swing_trade_ml.brain.lanes.h05_features import feature_code_sha256

    now_code = feature_code_sha256()
    if now_code != P.FEATURE_CODE_SHA256:
        changed = sorted(k for k in now_code if now_code[k] != P.FEATURE_CODE_SHA256.get(k))
        raise P.ProtocolError(f"feature code changed since the protocol froze it: {changed}")
    out: dict[str, VerifiedModel] = {}
    for group, exp in P.EXPECTED_MODELS.items():
        row = db.get(MLModel, exp["id"])
        where = f"{group} model id {exp['id']}"
        if row is None:
            raise P.ProtocolError(f"{where}: not in the registry")
        if (row.name, row.version) != (exp["name"], exp["version"]):
            raise P.ProtocolError(
                f"{where}: is {row.name} {row.version}, expected {exp['name']} {exp['version']}"
            )
        if _TIER_TO_GROUP.get(cap_tier(row.name)) != group:
            raise P.ProtocolError(f"{where}: name {row.name} does not belong to the {group} group")
        if row.label_kind != P.LABEL_KIND or row.prediction_horizon_days != P.HORIZON:
            raise P.ProtocolError(
                f"{where}: label is {row.label_kind}/{row.prediction_horizon_days}, expected endpoint/5"
            )
        if row.target_return_pct is None or abs(row.target_return_pct - P.LABEL_TARGET) > 1e-9:
            raise P.ProtocolError(f"{where}: target is {row.target_return_pct}, expected {P.LABEL_TARGET}")
        if row.stop_return_pct is not None:
            raise P.ProtocolError(f"{where}: has a stop in its label; the endpoint label has none")
        path = artifact_file(row)
        if not path.is_file():
            raise P.ProtocolError(f"{where}: model file {path.name} not found in {settings.model_dir}")
        digest = sha256_file(path)
        if digest != exp["sha256"]:
            raise P.ProtocolError(f"{where}: file hash {digest[:12]} is not the frozen {exp['sha256'][:12]}")
        bundle = joblib.load(path)
        names = list(bundle["feature_names"])
        if len(names) != exp["n_features"] or names != list(row.feature_names):
            raise P.ProtocolError(f"{where}: input list differs from the registry or the frozen count")
        if not set(names) <= set(FEATURE_COLUMNS):
            raise P.ProtocolError(
                f"{where}: uses inputs the feature builder no longer makes: {sorted(set(names) - set(FEATURE_COLUMNS))}"
            )
        if bundle.get("horizon_days") != P.HORIZON or bundle.get("target_return") != P.LABEL_TARGET:
            raise P.ProtocolError(f"{where}: the file's own label (horizon/target) is not 5 / +2%")
        if bundle.get("stop_return") is not None or bundle.get("calibrated"):
            raise P.ProtocolError(
                f"{where}: the file is calibrated or has a stop; it must be the raw endpoint model"
            )
        out[group] = VerifiedModel(
            group,
            row.id,
            row.name,
            row.version,
            str(row.status),
            digest,
            names,
            row.train_end,
            frozenset(s.upper() for s in (row.training_symbols or [])),
            path,
            # predict_instrument reads only these; the path is this machine's copy of the frozen file
            SimpleNamespace(id=row.id, name=row.name, version=row.version, artifact_path=str(path)),
            bundle,
            row.train_start,
        )
    return out


def assert_same_models(frozen: dict, now: dict[str, VerifiedModel]) -> None:
    """Every later day and every later run: identical identities to the ones frozen at run 1."""
    for group, model in now.items():
        if frozen.get(group) != model.identity():
            raise P.ProtocolError(f"{group} model identity changed since the run was frozen")


# ------------------------------------------------------------------ universe


def build_universe(db: Session) -> tuple[dict[str, str], dict[str, str], str]:
    """{symbol: group}, {symbol: reason excluded}, sha256 of both.

    The groups are the stock lists v1 already uses for its three paper strategies (large / mid / small ml_swing
    strategies that are active, paper and auto). A stock in two lists has no single right model: it is excluded
    and recorded."""
    wanted = {exp["name"]: group for group, exp in P.EXPECTED_MODELS.items()}
    lists: dict[str, list[str]] = {}
    rows = db.execute(
        select(Strategy).where(
            Strategy.is_active.is_(True),
            Strategy.mode == "paper",
            Strategy.execution_mode == "auto",
            Strategy.strategy_type == "ml_swing",
        )
    ).scalars()
    for s in rows:
        group = wanted.get((s.params or {}).get("model_name"))
        if group is None:
            continue
        if group in lists:
            raise P.ProtocolError(f"more than one active ml_swing strategy for the {group} group")
        lists[group] = [x.upper() for x in (s.symbols or [])]
    missing = [g for g in P.GROUPS if g not in lists]
    if missing:
        raise P.ProtocolError(f"no active ml_swing strategy list for: {missing}")
    seen: dict[str, list[str]] = {}
    for group, symbols in lists.items():
        for sym in symbols:
            seen.setdefault(sym, []).append(group)
    universe = {s: g[0] for s, g in seen.items() if len(g) == 1}
    excluded = {s: "ambiguous_group: in " + " and ".join(sorted(g)) for s, g in seen.items() if len(g) > 1}
    blob = json.dumps({"universe": universe, "excluded": excluded}, sort_keys=True)
    return universe, excluded, hashlib.sha256(blob.encode()).hexdigest()
