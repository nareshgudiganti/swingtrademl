# ruff: noqa: E501 (long explanatory lines)
"""Freeze one model for a shadow lane: train it once, after its history test has passed.

`python -m swing_trade_ml.shadow_lanes.lane_freeze <slot> <candidate> --report <history report>`

What it guarantees (each is a refusal, not a warning):
- the history report passed for exactly this candidate (10-day: both parts of the verdict; 15-day: the ranking verdict),
  so a model that failed its history test can never reach a lane;
- the slot and candidate belong together (10d-large <- TD10; 15d-large <- S0, S1, S2; 15d-midcap <- S0M, S1M, S2M);
- the slot has no frozen model yet: a lane model is frozen once, never retrained to look better;
- the frozen stock lists load and are used as the explicit training lists (the held-back 129 are never named);
- the model is trained as of the last closed session, from fully matured labels only, and registered TRAINED, never
  activated. Nothing here changes `ml_models` rows other than adding this one.

It writes a committed-style record `docs/brain/evidence/lane_models/<slot>.json` and tells the owner the setting to
add (`LANE_SHADOW_MODELS`). It does not turn the lane on, schedule anything or touch the brain.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path

MODEL_DIR = "docs/brain/evidence/lane_models"
#: slot -> the candidates whose history test may feed it (a live view over services/lane_slots.py). A NEW candidate
#: also needs its own training recipe below: that is a model, not infrastructure.
from swing_trade_ml.services.lane_slots import CANDIDATES_VIEW as SLOT_CANDIDATES  # noqa: E402

BARRIER = {"TD10": (10, 0.06, 0.035), "S0": (15, 0.08, 0.04), "S0M": (15, 0.08, 0.04)}


class FreezeRefusedError(RuntimeError):
    """The lane model may not be frozen: nothing was trained."""


def record_path(repo_root: Path, slot_key: str) -> Path:
    return repo_root / MODEL_DIR / f"{slot_key}.json"


def read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def history_passed(candidate: str, report: dict, manifest: dict | None = None) -> tuple[bool, str]:
    """(passed, why not). 10-day: both parts of the signed verdict. 15-day: the ranking verdict, for this candidate."""
    if candidate == "TD10":
        v = report.get("verdict") or {}
        pred, econ = (v.get("predictive") or {}).get("word"), (v.get("economic") or {}).get("word")
        if pred == "pass" and econ == "pass":
            return True, ""
        return False, f"the 10-day verdict is predictive={pred}, economic={econ}; both must be pass"
    named = (manifest or {}).get("Candidate")
    if named != candidate:
        return False, f"the report is for candidate {named!r}, not {candidate!r}"
    if report.get("ranking_verdict") == "pass":
        return True, ""
    return False, f"the ranking verdict is {report.get('ranking_verdict')!r}, not 'pass'"


def refusal_reasons(
    slot_key: str,
    candidate: str,
    *,
    report_ok: tuple[bool, str],
    already_frozen: bool,
    universe_error: str | None,
) -> list[str]:
    out: list[str] = []
    if slot_key not in SLOT_CANDIDATES:
        out.append(f"unknown slot {slot_key!r}; slots: {', '.join(SLOT_CANDIDATES)}")
    elif candidate not in SLOT_CANDIDATES[slot_key]:
        out.append(
            f"{candidate} does not belong to slot {slot_key}; allowed: {', '.join(SLOT_CANDIDATES[slot_key])}"
        )
    if not report_ok[0]:
        out.append(f"history test not passed: {report_ok[1]}")
    if already_frozen:
        out.append(
            f"slot {slot_key} already has a frozen model: a lane model is frozen once, never retrained"
        )
    if universe_error:
        out.append(f"the frozen stock lists cannot be loaded: {universe_error}")
    return out


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def default_trainer(db, candidate: str, cutoff: date, universe: dict, name: str):
    """Train the passed candidate on an explicit stock list, as of `cutoff`. Registered TRAINED, never activated."""
    from swing_trade_ml.brain import selection_lab as sl
    from swing_trade_ml.brain.selection_lab_run import collect_db
    from swing_trade_ml.ml.train import train_model

    large, mid = list(universe["large"]), list(universe["mid"])
    if candidate in BARRIER:
        horizon, target, stop = BARRIER[candidate]
        symbols = mid if candidate == "S0M" else large
        return train_model(
            db,
            name=name,
            symbols=symbols,
            horizon_days=horizon,
            target_return=target,
            stop_return=stop,
            cutoff=cutoff,
            auto_activate=False,
        )
    bars, used, extra, mid_group = collect_db(db)
    if candidate == "S1":
        symbols, ref = used, used
    elif candidate == "S2":
        symbols, ref = [*used, *extra], used
    elif candidate == "S1M":
        symbols, ref = mid_group, mid_group
    elif candidate == "S2M":
        symbols, ref = sorted(set(mid_group) | set(extra)), mid_group
    else:
        raise FreezeRefusedError(f"no trainer for {candidate}")
    return sl.train_lab_model(db, name=name, cutoff=cutoff, symbols=symbols, candidates=ref, bars=bars)


def _mark_final(db, model, slot_key: str, candidate: str, report_path: Path, stamp: str) -> None:
    """Record that this model is the frozen final one, and which passed history report qualified it. Adds data only:
    status, files and scoring are untouched. A software step; it is not itself a model validation."""
    model.model_role = "final"
    metrics = dict(model.metrics) if isinstance(getattr(model, "metrics", None), dict) else {}
    metrics["qualification"] = {
        "slot_key": slot_key,
        "candidate": candidate,
        "history_report": str(report_path),
        "frozen_at": stamp,
    }
    model.metrics = metrics  # a new dict, so the JSON column registers the change
    if db is not None:
        db.commit()


def model_name(candidate: str, cutoff: date) -> str:
    """Names the registry maps to the right slot: td_h10_* for the 10-day model, sl1_<cand>_* for the 15-day ones."""
    return f"td_h10_lane_{cutoff:%Y%m%d}" if candidate == "TD10" else f"sl1_{candidate}_lane_{cutoff:%Y%m%d}"


def freeze(
    db,
    slot_key: str,
    candidate: str,
    report_path: Path,
    *,
    repo_root: Path,
    cutoff: date,
    trainer: Callable | None = None,
    commit: str = "unknown",
    now: datetime | None = None,
) -> Path:
    """Train and record the lane model for `slot_key`. Raises FreezeRefusedError before training on any problem."""
    from swing_trade_ml.shadow_lanes import lane_universe
    from swing_trade_ml.shadow_lanes.lane_service import slot_parts  # noqa: F401  (validates slot shape)

    manifest_path = report_path.parent / "manifest.json"
    manifest = read_report(manifest_path) if manifest_path.exists() else None
    report = read_report(report_path)
    universe, universe_error = None, None
    try:
        universe = lane_universe.load_universe(repo_root)
    except lane_universe.UniverseError as exc:
        universe_error = str(exc)
    reasons = refusal_reasons(
        slot_key,
        candidate,
        report_ok=history_passed(candidate, report, manifest),
        already_frozen=record_path(repo_root, slot_key).exists(),
        universe_error=universe_error,
    )
    if reasons:
        raise FreezeRefusedError(
            "Lane model not frozen; nothing was trained:\n" + "\n".join(f"- {r}" for r in reasons)
        )
    name = model_name(candidate, cutoff)
    model = (trainer or default_trainer)(db, candidate, cutoff, universe, name)
    from swing_trade_ml.services.model_registry import slot_for

    if slot_for(model.name, model.prediction_horizon_days) != slot_key:
        raise FreezeRefusedError(f"trained model {model.name!r} is not registered for slot {slot_key}")
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    _mark_final(db, model, slot_key, candidate, report_path, stamp)
    record = {
        "slot_key": slot_key,
        "candidate": candidate,
        "model_id": model.id,
        "model_name": model.name,
        "model_version": model.version,
        "status_at_freeze": str(model.status),
        "trained_as_of": cutoff.isoformat(),
        "history_report": str(report_path),
        "universe_sha256": universe["sha256"],
        "code_commit": commit,
        "frozen_at": stamp,
        "note": "Registered TRAINED and never activated. Add it to LANE_SHADOW_MODELS to let the lane use it.",
    }
    path = record_path(repo_root, slot_key)
    _atomic_write(path, json.dumps(record, indent=1) + "\n")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import subprocess

    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.core.market_session import last_closed_trading_day

    ap = argparse.ArgumentParser(
        description="Freeze one model for a shadow lane (after its history test passed)"
    )
    ap.add_argument("slot", choices=list(SLOT_CANDIDATES))
    ap.add_argument("candidate", choices=[c for cs in SLOT_CANDIDATES.values() for c in cs])
    ap.add_argument(
        "--report", required=True, help="the history report JSON (ten_day_*.json or sl_v1/<run>/metrics.json)"
    )
    a = ap.parse_args(argv)
    from swing_trade_ml.db.session import SessionLocal

    commit = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    with SessionLocal() as db:
        try:
            path = freeze(
                db,
                a.slot,
                a.candidate,
                Path(a.report),
                repo_root=REPO_ROOT,
                cutoff=last_closed_trading_day(datetime.now().astimezone()),
                commit=commit or "unknown",
            )
        except FreezeRefusedError as exc:
            print(exc)
            return 2
    rec = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"Frozen {rec['model_name']} ({rec['model_version']}, id {rec['model_id']}) for {a.slot}. Record: {path}"
    )
    print(f'To let the lane use it, set LANE_SHADOW_MODELS to include "{a.slot}": {rec["model_id"]}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
