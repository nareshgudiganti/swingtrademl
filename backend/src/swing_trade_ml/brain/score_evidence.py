"""What a model score really meant on days the model had not seen (display only).

A raw model score is a ranking, not a chance: in the walk-forward test a "55%" idea reached
+8% before -4% about 14% of the time (docs/brain/evidence/score_reliability.md). This module
turns a raw score into two separate things for the idea cards:

- `honest_chance`: the score passed through the existing M06 honesty map (`HonestyMap`), fitted
  on out-of-time results with every market window counted equally;
- `track_record`: how often ideas in the same score band really hit the target, with the number
  of cases, the period, and how far the hit rate swung between windows.

Nothing here feeds a decision: the stored score, the buy level, orders, sizing and stops all keep
using the raw score.

The evidence belongs to the one model it was measured on (issue #377). An evidence file records that
model in `measured_on` (id, name, version, artifact hash, inputs fingerprint, protocol); a score gets
the number only when the model that PRODUCED it (recorded with its run, see `run_model_identity`) is
that same model. A model that only shares the target, stop and horizon gets no number, an evidence file
without `measured_on` is never a match, and a score whose model cannot be confirmed is "unverified".
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression

from swing_trade_ml.brain.modules.m06_reason.trainer import HonestyMap, fit_honesty

EVIDENCE_FILE = Path(__file__).parent / "score_evidence_barrier.json"
BANDS = (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0001)
MIN_BAND_CASES = 100  # fewer comparable ideas than this is too few to quote a hit rate
MIN_BAND_WINDOWS = 3  # ...or fewer market windows than this
APPLIES_TO = {"label_kind": "barrier", "horizon_days": 15, "target_return": 0.08, "stop_return": 0.04}
RULE = "+8% target before the -4% stop, within 15 trading days"
CAVEAT = "Past results do not guarantee future results."


def _band(p: float) -> int:
    for i, (lo, hi) in enumerate(pairwise(BANDS)):
        if lo <= p < hi:
            return i
    return len(BANDS) - 2


def build(rows: list[dict], generated_on: str, measured_on: dict | None = None) -> dict:
    """`rows`: one per finished stock-day the model scored on unseen days:
    {"fold": window start, "end": window end, "day", "p": raw score, "hit": 0/1}.
    `measured_on`: the one model the rows came from (`model_identity` keys plus a "protocol" line).
    Without it the file is still written, but no model will ever be given its numbers."""
    p = np.array([r["p"] for r in rows], dtype=float)
    y = np.array([r["hit"] for r in rows], dtype=float)
    days = np.array([r["day"] for r in rows], dtype="datetime64[D]")
    cell = [(r["fold"], _band(r["p"])) for r in rows]
    size = Counter(cell)
    weights = np.array([1.0 / size[c] for c in cell])  # each window counts equally within a band
    honesty = fit_honesty(p, y, days, weights=weights)
    iso = honesty.iso
    bands = []
    for i, (lo, hi) in enumerate(pairwise(BANDS)):
        idx = [k for k, c in enumerate(cell) if c[1] == i]
        if not idx:
            continue
        per_window: dict[str, list[int]] = {}
        for k in idx:
            per_window.setdefault(rows[k]["fold"], []).append(rows[k]["hit"])
        rates = [sum(v) / len(v) for v in per_window.values() if len(v) >= 10]
        bands.append(
            {
                "low": lo,
                "high": min(hi, 1.0),
                "n": len(idx),
                "hit_rate": float(y[idx].mean()),
                "windows": len(per_window),
                "lowest_window": min(rates) if rates else None,
                "highest_window": max(rates) if rates else None,
            }
        )
    out = {
        "version": 1,
        "applies_to": APPLIES_TO,
        "rule": RULE,
        "generated_on": generated_on,
        "stock_days": len(rows),
        "windows": len({r["fold"] for r in rows}),
        "first_day": min(r["day"] for r in rows),
        "last_day": max(r["day"] for r in rows),
        "overall_hit_rate": float(y.mean()),
        "honesty": {
            "x": [float(v) for v in iso.X_thresholds_],
            "y": [float(v) for v in iso.y_thresholds_],
            "ceiling": honesty.ceiling,
            "max_seen": honesty.max_seen,
            "min_days": honesty.min_days,
        },
        "bands": bands,
    }
    if measured_on is not None:
        out["version"] = 2
        out["measured_on"] = measured_on
    return out


def load(path: Path = EVIDENCE_FILE) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _honesty_map(evidence: dict) -> HonestyMap:
    h = evidence["honesty"]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(h["x"], h["y"])
    return HonestyMap(iso, h["ceiling"], h["max_seen"], h["min_days"])


def model_matches(model) -> bool:
    """True when a model was trained on the question the evidence measured. Necessary, never enough:
    the evidence must also have been measured on this very model (`choose`)."""
    return (
        model is not None
        and getattr(model, "label_kind", None) == APPLIES_TO["label_kind"]
        and getattr(model, "prediction_horizon_days", None) == APPLIES_TO["horizon_days"]
        and getattr(model, "target_return_pct", None) == APPLIES_TO["target_return"]
        and getattr(model, "stop_return_pct", None) == APPLIES_TO["stop_return"]
    )


# --- which model produced a score, and which evidence it may quote ------------------------------

IDENTITY_KEYS = ("model_id", "name", "version")  # must be recorded by the evidence and equal
CHECKED_IF_RECORDED = ("artifact_sha256", "inputs_fingerprint")  # recorded by the evidence -> must match


def model_identity(model) -> dict | None:
    """What identifies a registered model: row id, name, version, the artifact hash stored at training
    (`metrics["artifact_sha256"]`; None when not recorded, never invented), a fingerprint of its input
    list, and the question it was trained on."""
    if model is None:
        return None
    # Read straight from the row: the brain must not import services.model_registry (its isolation test).
    # The inputs fingerprint is the same formula as model_registry.provenance, so the two always agree.
    features = list(model.feature_names or [])
    file_fp = (model.metrics or {}).get("artifact_sha256")
    return {
        "model_id": model.id,
        "name": model.name,
        "version": model.version,
        "artifact_sha256": file_fp if isinstance(file_fp, str) else None,
        "inputs_fingerprint": (
            hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest()
            if features
            else None
        ),
        "label_kind": model.label_kind,
        "horizon_days": model.prediction_horizon_days,
        "target_return": model.target_return_pct,
        "stop_return": model.stop_return_pct,
    }


def scoring_model(reader: Any):
    """The model whose scores a finished run's reader handed out: the as-of model in a replay, the
    active model it loaded in a live run, or None when it scored nothing (or its file failed).
    Reads the DatedReader's own fields: brain/reader.py is frozen for the trial."""
    if getattr(reader, "live", None) is False:
        return getattr(reader, "asof_model", None)
    if getattr(reader, "_model_loaded", False):
        return getattr(reader, "_model", None)
    return None


def scoring_model_record(reader: Any) -> dict | None:
    """`model_identity` of the run's scoring model, for the run's data manifest. A display record never
    fails a run: anything unreadable is stored as None, which later shows as "unverified"."""
    try:
        return model_identity(scoring_model(reader))
    except Exception:  # noqa: BLE001
        return None


# The model label the fallback and M08 write into a TRADE idea's reasons (brain/fallbacks.reason).
_MODEL_REASON = re.compile(r"^The active model \((?P<label>.+)\) scores this stock ")


def run_model_identity(db, run, decisions: Iterable[Any] | None = None) -> dict | None:
    """The model that produced a stored run's model scores, from what the run stored, never from what
    is active now: the identity recorded in its data manifest (runs since #377), else the one model
    label its reasons name (looked up by its unique name + version). None when neither says."""
    if run is None:
        return None
    manifest = (run.context or {}).get("data_manifest") or {}
    if "score_model" in manifest:
        recorded = manifest["score_model"]
        return {**recorded, "source": "recorded_with_run"} if isinstance(recorded, dict) else None
    if decisions is None:
        from swing_trade_ml.brain.service import decisions_for

        decisions = decisions_for(db, run.id)
    labels = {
        m["label"]
        for d in decisions
        for r in d.reasons or []
        if isinstance(r, str) and (m := _MODEL_REASON.match(r))
    }
    if len(labels) != 1:
        return None  # no label (or two, which one run cannot have): unverified
    name, _, version = labels.pop().rpartition(" ")
    if not name:
        return None
    from sqlalchemy import select

    from swing_trade_ml.db.models.ml import MLModel

    row = db.execute(
        select(MLModel).where(MLModel.name == name, MLModel.version == version)
    ).scalar_one_or_none()
    identity = model_identity(row)
    return {**identity, "source": "reason_text"} if identity else None


@dataclass(frozen=True, slots=True)
class Choice:
    """`status`: match | unverified_model | unverified_evidence | other_question | other_model | none."""

    evidence: dict | None
    status: str
    identity: dict | None = None


def choose(identity: dict | None, evidence: dict | None) -> Choice:
    """The evidence a score may quote, given the identity of the model that produced it."""
    if evidence is None:
        return Choice(None, "none", identity)
    if identity is None:
        return Choice(None, "unverified_model", None)
    if any(identity.get(k) != v for k, v in APPLIES_TO.items()):
        return Choice(None, "other_question", identity)
    measured_on = evidence.get("measured_on")
    if not isinstance(measured_on, dict) or not measured_on.get("protocol"):
        return Choice(None, "unverified_evidence", identity)  # old file: says nothing of its model
    if any(measured_on.get(k) is None for k in IDENTITY_KEYS):
        return Choice(None, "unverified_evidence", identity)
    if any(identity.get(k) != measured_on[k] for k in IDENTITY_KEYS):
        return Choice(None, "other_model", identity)
    for k in CHECKED_IF_RECORDED:
        if measured_on.get(k) is None:
            continue  # not recorded when measured (models older than artifact hashes)
        if identity.get(k) is None:
            return Choice(None, "unverified_evidence", identity)
        if identity[k] != measured_on[k]:
            return Choice(None, "other_model", identity)
    return Choice(evidence, "match", identity)


def evidence_for(identity: dict | None) -> Choice:
    """The evidence for the model that produced a score, by that model's recorded identity."""
    return choose(identity, load())


def one_in(rate: float) -> str:
    return f"about 1 in {max(1, round(1 / rate))}" if rate > 0 else "almost none"


_NOTES = {
    "other_question": (
        "This model was not trained on the +8% / -4% question, so its score only ranks "
        "stocks. It is not a chance, and there is no measured hit rate for it."
    ),
    "none": "No measured hit rate is on file, so this score only ranks stocks. It is not a chance.",
    "other_model": (
        "There is no measured hit rate for the model that produced this score, so its score only "
        "ranks stocks. It is not a chance."
    ),
    "unverified_model": (
        "We could not confirm which model produced this score, so no measured hit rate is shown. "
        "The score only ranks stocks; it is not a chance."
    ),
    "unverified_evidence": (
        "The measured hit rate on file cannot be confirmed as measured on the model that produced "
        "this score, so it is not shown. The score only ranks stocks; it is not a chance."
    ),
}


def _who(identity: dict | None) -> dict | None:
    if not identity:
        return None
    return {
        "model_id": identity.get("model_id"),
        "name": identity.get("name"),
        "version": identity.get("version"),
        "artifact_sha256": identity.get("artifact_sha256") or "not recorded",
    }


def present(
    raw: float | None, evidence: dict | None, *, reason: str | None = None, scored_by: dict | None = None
) -> dict:
    """Display fields for one raw score. Always returns a status so a card never has to guess.
    `reason`: the `Choice.status` that left `evidence` empty; `scored_by`: the scoring model's identity."""
    if raw is None:
        return {"status": "no_score"}
    extra = {"scored_by": {**_who(scored_by), "source": scored_by.get("source")}} if scored_by else {}
    if evidence is None:
        return {
            "status": "unverified"
            if reason in ("unverified_model", "unverified_evidence")
            else "not_measured",
            "note": _NOTES.get(reason or "", _NOTES["other_question"]),
            **extra,
        }
    honesty = _honesty_map(evidence)
    honest = float(honesty.apply(np.array([raw]))[0])
    b = next((b for b in evidence["bands"] if b["low"] <= raw < b["high"] or raw >= b["high"] == 1.0), None)
    out: dict = {
        "status": "measured",
        "honest_chance": honest,
        "rule": evidence["rule"],
        "period": {"from": evidence["first_day"], "to": evidence["last_day"]},
        "caveat": CAVEAT,
        **extra,
    }
    measured_on = evidence.get("measured_on")
    if isinstance(measured_on, dict):
        out["measured_on"] = {**_who(measured_on), "protocol": measured_on.get("protocol")}
    if raw > honesty.max_seen:
        out["note"] = "This score is higher than anything seen in testing, so treat it with care."
    if b is None or b["n"] < MIN_BAND_CASES or b["windows"] < MIN_BAND_WINDOWS:
        out["track_record"] = {"enough_evidence": False}
        return out
    swing = (
        f" It ranged from {b['lowest_window']:.0%} to {b['highest_window']:.0%} between market windows."
        if b["lowest_window"] is not None
        else ""
    )
    out["track_record"] = {
        "enough_evidence": True,
        "hit_rate": b["hit_rate"],
        "n": b["n"],
        "windows": b["windows"],
        "lowest_window": b["lowest_window"],
        "highest_window": b["highest_window"],
        "text": (
            f"Of {b['n']:,} ideas the model scored {b['low']:.0%} to {min(b['high'], 1):.0%} on days it "
            f"had not seen ({evidence['first_day']} to {evidence['last_day']}), {b['hit_rate']:.0%} "
            f"({one_in(b['hit_rate'])}) reached the target first.{swing}"
        ),
    }
    return out
