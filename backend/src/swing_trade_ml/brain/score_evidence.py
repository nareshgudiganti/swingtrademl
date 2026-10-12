"""What a model score really meant on days the model had not seen (display only).

A raw model score is a ranking, not a chance: in the walk-forward test a "55%" idea reached
+8% before -4% about 14% of the time (docs/brain/evidence/score_reliability.md). This module
turns a raw score into two separate things for the idea cards:

- `honest_chance`: the score passed through the existing M06 honesty map (`HonestyMap`), fitted
  on out-of-time results with every market window counted equally;
- `track_record`: how often ideas in the same score band really hit the target, with the number
  of cases, the period, and how far the hit rate swung between windows.

Nothing here feeds a decision: the stored score, the buy level, orders, sizing and stops all keep
using the raw score. The map is only valid for a model trained on the question it was measured on
(`applies_to`); any other model gets no number.
"""

from __future__ import annotations

import json
from collections import Counter
from itertools import pairwise
from pathlib import Path

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


def build(rows: list[dict], generated_on: str) -> dict:
    """`rows`: one per finished stock-day the model scored on unseen days:
    {"fold": window start, "end": window end, "day", "p": raw score, "hit": 0/1}."""
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
    return {
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
    """True only for a model trained on the question the evidence measured."""
    return (
        model is not None
        and getattr(model, "label_kind", None) == APPLIES_TO["label_kind"]
        and getattr(model, "prediction_horizon_days", None) == APPLIES_TO["horizon_days"]
        and getattr(model, "target_return_pct", None) == APPLIES_TO["target_return"]
        and getattr(model, "stop_return_pct", None) == APPLIES_TO["stop_return"]
    )


def evidence_for(model) -> dict | None:
    """The evidence for the model the brain scored with, or None (then no number is shown)."""
    return load() if model_matches(model) else None


def one_in(rate: float) -> str:
    return f"about 1 in {max(1, round(1 / rate))}" if rate > 0 else "almost none"


def present(raw: float | None, evidence: dict | None) -> dict:
    """Display fields for one raw score. Always returns a status so a card never has to guess."""
    if raw is None:
        return {"status": "no_score"}
    if evidence is None:
        return {
            "status": "not_measured",
            "note": (
                "This model was not trained on the +8% / -4% question, so its score only ranks "
                "stocks. It is not a chance, and there is no measured hit rate for it."
            ),
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
    }
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
