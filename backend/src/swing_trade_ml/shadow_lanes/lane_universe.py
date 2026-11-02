# ruff: noqa: E501 (long explanatory lines)
"""The frozen stock lists of the daily shadow lanes.

A lane must judge the SAME stocks as the history test it follows: the large group is exactly the locked 49 and the
mid group is the app's mid-cap model's stocks minus the held-back set (the 14). Both lists live in one committed file
with a hash; a lane run refuses (records nothing) if the file is missing, changed, or breaks a rule:

- the large list equals the locked 49;
- no held-back stock (the 129) is in either list;
- the mid list shares nothing with the 49 and has at least 10 stocks.

Writing the file is a one-off, owner-reviewed step (`python -m swing_trade_ml.shadow_lanes.lane_universe write`); it
never overwrites an existing file. Nothing here touches the database except that one command's read of the active
mid-cap model.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

UNIVERSE_FILE = "docs/brain/evidence/lane_universe/lane_universe_v1.json"
MIN_MID = 10
MID_MODEL_NAME = "swing_classifier_midcap"


class UniverseError(RuntimeError):
    """The frozen lane universe is missing, changed or breaks a rule: a lane run records nothing."""


def universe_sha(large: Sequence[str], mid: Sequence[str]) -> str:
    text = "L:" + ",".join(sorted(large)) + "|M:" + ",".join(sorted(mid))
    return hashlib.sha256(text.encode()).hexdigest()


def problems(
    large: Sequence[str], mid: Sequence[str], used_49: Sequence[str], reject_set: Sequence[str]
) -> list[str]:
    out: list[str] = []
    if sorted(large) != sorted(used_49):
        out.append("the large list is not exactly the locked 49 stocks")
    held = set(reject_set)
    for name, lst in (("large", large), ("mid", mid)):
        bad = sorted(set(lst) & held)
        if bad:
            out.append(f"{len(bad)} held-back stock(s) in the {name} list: {', '.join(bad[:5])}")
        if len(set(lst)) != len(lst):
            out.append(f"the {name} list has duplicates")
    shared = sorted(set(mid) & set(used_49))
    if shared:
        out.append(f"the mid list shares {len(shared)} stock(s) with the 49: {', '.join(shared[:5])}")
    if len(mid) < MIN_MID:
        out.append(f"the mid list has {len(mid)} stocks, fewer than {MIN_MID}")
    return out


def build(used_49: Sequence[str], reject_set: Sequence[str], mid_training_symbols: Sequence[str]) -> dict:
    """The universe from the locked split and the active mid-cap model's training list. Refuses a bad build."""
    large = sorted(used_49)
    mid = sorted({s.upper() for s in mid_training_symbols} - set(reject_set))
    bad = problems(large, mid, used_49, reject_set)
    if bad:
        raise UniverseError("; ".join(bad))
    return {
        "version": "lane_universe_v1",
        "large": large,
        "mid": mid,
        "source": f"large = the locked 49 (stock_split_ev15); mid = {MID_MODEL_NAME} training symbols minus the 129 held-back stocks",
        "mid_model_training_symbols_n": len(set(mid_training_symbols)),
        "sha256": universe_sha(large, mid),
    }


def load_universe(repo_root: Path | None = None) -> dict:
    """The frozen universe, re-checked against the locked split file on every call."""
    from swing_trade_ml.core.config import REPO_ROOT

    root = repo_root or REPO_ROOT
    path = root / UNIVERSE_FILE
    if not path.exists():
        raise UniverseError(f"{UNIVERSE_FILE} does not exist: the lane universe has not been frozen")
    from swing_trade_ml.brain.selection_lab_run import RunRefusedError, load_split

    try:
        used_49, _extra, _sha = load_split(root)
        reject = json.loads(
            (root / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text(encoding="utf-8")
        )["reject_set"]
    except (RunRefusedError, FileNotFoundError, KeyError) as exc:
        raise UniverseError(f"the locked stock split cannot be verified: {exc}") from exc
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sha256") != universe_sha(data.get("large", []), data.get("mid", [])):
        raise UniverseError("the lane universe file does not match its recorded hash: it was changed")
    bad = problems(data["large"], data["mid"], used_49, reject)
    if bad:
        raise UniverseError("; ".join(bad))
    return data


def group_symbols(universe: dict, cap_group: str) -> list[str]:
    if cap_group not in ("large", "mid"):
        raise UniverseError(f"unknown cap group {cap_group!r}")
    return list(universe[cap_group])


def main(argv: Sequence[str] | None = None) -> int:
    """`write`: build the file from the locked split and the active mid-cap model, once. Review before committing."""
    import argparse

    from sqlalchemy import select

    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.db.session import SessionLocal

    ap = argparse.ArgumentParser(description="Freeze the shadow-lane stock lists (never overwrites)")
    ap.add_argument("action", choices=["write"])
    ap.parse_args(argv)
    path = REPO_ROOT / UNIVERSE_FILE
    if path.exists():
        print(f"{UNIVERSE_FILE} already exists: it is frozen and is never overwritten.")
        return 2
    from swing_trade_ml.brain.selection_lab_run import load_split

    used_49, _extra, _sha = load_split(REPO_ROOT)
    reject = json.loads(
        (REPO_ROOT / "docs/brain/evidence/stock_split/stock_split_ev15.json").read_text(encoding="utf-8")
    )["reject_set"]
    with SessionLocal() as db:
        mid_model = db.scalar(
            select(MLModel).where(MLModel.name == MID_MODEL_NAME, MLModel.status == "ACTIVE").limit(1)
        )
        if mid_model is None:
            print(f"No ACTIVE {MID_MODEL_NAME} model: cannot build the mid list.")
            return 2
        data = build(used_49, reject, list(mid_model.training_symbols or []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"Written {path}: large {len(data['large'])}, mid {len(data['mid'])}, sha256 {data['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
