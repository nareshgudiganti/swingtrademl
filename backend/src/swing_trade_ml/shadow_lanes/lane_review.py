# ruff: noqa: E501 (long report sentences)
"""The 60 to 90 session review of a shadow lane: an evidence checkpoint, never a promotion.

`python -m swing_trade_ml.shadow_lanes.lane_review <slot>`

It reads only the stored picks and outcomes (read-only) and writes a plain-English report with the numbers and their
uncertainty. The words are descriptive ("no clear edge shown yet", "worth continuing to watch"); it never says pass,
approved or promoted, and it cannot change a model, a setting or a lane.

Rules that stop it being used to shop for a good-looking answer:
- a review file exists only from 60 recorded sessions, and only one per checkpoint (60 and 90 sessions);
- an existing review file is never overwritten;
- files are written whole or not at all.
The live dashboard still shows running numbers; the review is the dated, immutable reading.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

REVIEW_DIR = "docs/brain/evidence/lane_reviews"
CHECKPOINTS = (60, 90)
POLICY = (
    "This review is an evidence checkpoint. It never promotes a model. Trading approval needs a portfolio simulation "
    "through the brain's risk gate, liquidity and execution checks, positive after-cost results over enough "
    "independent evidence, and the owner's explicit approval."
)
LIMITS = (
    "Pick-level drawdown is the largest fall in the running total of the picks' results. It is not a portfolio drawdown.",
    "Costs are slippage-adjusted fills with charges; liquidity, circuit limits, halts and volume caps are not modelled and must be resolved before any realistic portfolio simulation.",
    "The benchmark is the average result of every eligible stock in the same cap group on the same day, so it is market-cap appropriate but not a tradable index.",
    "The stock lists are today's lists (survivor bias); history results are partly already seen.",
)


class ReviewError(RuntimeError):
    """The review cannot be written now."""


def checkpoint_for(sessions: int) -> int | None:
    """60 from 60 to 89 recorded sessions, 90 from 90 on, None before 60."""
    hit = [c for c in CHECKPOINTS if sessions >= c]
    return max(hit) if hit else None


def state_for(sessions: int, completed: int) -> str:
    if sessions < CHECKPOINTS[0] or completed < CHECKPOINTS[0]:
        return "too_early"
    return "first_review" if sessions < CHECKPOINTS[1] else "extended_review"


def reading(state: str, net_low: float | None, excess_low: float | None, net_mean: float | None) -> str:
    """Descriptive only. 'Range' = the 5th-95th percentile of the mean from the block bootstrap."""
    if state == "too_early":
        return "Too early to say anything: fewer than 60 recorded sessions or fewer than 60 finished picks."
    if net_low is None or excess_low is None:
        return "Not enough finished picks to put a range on the result yet."
    net_ok, excess_ok = net_low > 0, excess_low > 0
    if net_ok and excess_ok:
        return (
            "Positive after costs and above the group's own average stock, and the uncertainty range stays above "
            "zero for both. Worth continuing and extending the watch. This is not an approval."
        )
    if net_ok:
        return (
            "Makes money after costs, but not clearly better than the group's own average stock, so the market "
            "may explain it more than the model."
        )
    if excess_ok:
        return "Better than the group's own average stock, but not clearly profitable after costs."
    if net_mean is not None and net_mean > 0:
        return "Positive on average, but the uncertainty range includes zero: no clear edge shown yet."
    return "No clear edge shown yet."


def build_review(db, slot_key: str, as_of: date) -> dict:
    """Read-only. Reuses the lane API's own maths so the review and the dashboard can never disagree."""
    from swing_trade_ml.api.v1.endpoints import lanes as lane_api
    from swing_trade_ml.db.models.ml import MLModel
    from swing_trade_ml.shadow_lanes.lane_service import SLOTS

    if slot_key not in SLOTS:
        raise ReviewError(f"unknown slot {slot_key!r}")
    horizon, group = SLOTS[slot_key]
    rows = [(p, o) for p, o in lane_api._rows(db, slot_key) if p.signal_day <= as_of]
    forward, sessions, completed = lane_api.forward_view(rows, horizon, group)
    done = [(p, o) for p, o in rows if o is not None and o.net_return is not None]
    by_day_excess: dict[date, list[float]] = {}
    for p, o in done:
        if o.excess_return is not None:
            by_day_excess.setdefault(p.signal_day, []).append(o.excess_return)
    excess_interval = lane_api.bootstrap_interval([by_day_excess[d] for d in sorted(by_day_excess)], horizon)
    baselines = [o.baseline_net_return for _, o in done if o.baseline_net_return is not None]
    net_low = forward["uncertainty"]["low"]
    state = state_for(sessions, completed)
    model = db.get(MLModel, rows[-1][0].model_id) if rows else None
    return {
        "slot_key": slot_key,
        "horizon_days": horizon,
        "cap_group": group,
        "as_of": as_of.isoformat(),
        "checkpoint": checkpoint_for(sessions),
        "state": state,
        "model": {"id": model.id, "name": model.name, "version": model.version} if model else None,
        "started_on": rows[0][0].signal_day.isoformat() if rows else None,
        "sessions_recorded": sessions,
        "picks": forward["picks"],
        "completed": completed,
        "open": forward["open"],
        "ambiguous": sum(1 for _, o in done if o.ambiguous),
        "hit_rate": forward["hit_rate"],
        "mean_net_return": forward["mean_net_return"],
        "net_range": forward["uncertainty"],
        "group_average_stock_return": (sum(baselines) / len(baselines)) if baselines else None,
        "cash_return": 0.0,
        "excess_over_group_average": forward["benchmark_excess"],
        "excess_range": {"low": excess_interval[0], "high": excess_interval[1]}
        if excess_interval
        else {"low": None, "high": None},
        "pick_level_drawdown": forward["drawdown"],
        "sample_warning": forward["sample_warning"],
        "reading": reading(
            state,
            net_low,
            excess_interval[0] if excess_interval else None,
            forward["mean_net_return"],
        ),
        "policy": POLICY,
        "limits": list(LIMITS),
    }


def _pct(x: float | None, digits: int = 2) -> str:
    return "not measured" if x is None else f"{x * 100:+.{digits}f}%"


def render_markdown(r: dict) -> str:
    m = r["model"]
    rng, ex = r["net_range"], r["excess_range"]
    lines = [
        f"# Lane review: {r['slot_key']} (checkpoint {r['checkpoint'] or 'not reached'} sessions)",
        "",
        f"**Evidence checkpoint as of {r['as_of']}. {r['policy']}**",
        "",
        f"Reading: **{r['reading']}**",
        "",
        f"- Model: {m['name']} {m['version']} (id {m['id']})" if m else "- Model: none recorded",
        f"- Watched since {r['started_on']}: {r['sessions_recorded']} sessions, {r['picks']} picks, {r['completed']} finished, {r['open']} open, {r['ambiguous']} where one bar touched both levels (counted as the stop).",
        f"- Hit rate (picks that made money after costs): {_pct(r['hit_rate'], 1)}",
        f"- Average result after costs: {_pct(r['mean_net_return'])}, could be as low as {_pct(rng['low'])} or as high as {_pct(rng['high'])}",
        f"- Average of every eligible stock in the same group: {_pct(r['group_average_stock_return'])}; cash: {_pct(r['cash_return'])}",
        f"- Excess over the group's own average stock: {_pct(r['excess_over_group_average'])}, could be as low as {_pct(ex['low'])} or as high as {_pct(ex['high'])}",
        f"- Pick-level drawdown: {_pct(r['pick_level_drawdown'])} (not a portfolio drawdown)",
    ]
    if r["sample_warning"]:
        lines += ["", f"**{r['sample_warning']}**"]
    lines += ["", "Limits of this review:"] + [f"- {x}" for x in r["limits"]]
    return "\n".join(lines) + "\n"


def review_paths(repo_root: Path, slot_key: str, checkpoint: int) -> tuple[Path, Path]:
    stem = repo_root / REVIEW_DIR / f"{slot_key}_{checkpoint}sessions"
    return stem.with_suffix(".md"), stem.with_suffix(".json")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_review(db, slot_key: str, as_of: date, *, repo_root: Path) -> tuple[Path, Path]:
    """The dated, immutable review file for the slot's current checkpoint. One per checkpoint, never overwritten."""
    review = build_review(db, slot_key, as_of)
    cp = review["checkpoint"]
    if cp is None:
        raise ReviewError(
            f"{slot_key} has {review['sessions_recorded']} recorded sessions: a review file exists only from {CHECKPOINTS[0]}."
        )
    md, js = review_paths(repo_root, slot_key, cp)
    if md.exists() or js.exists():
        raise ReviewError(f"the {cp}-session review of {slot_key} already exists: one review per checkpoint.")
    _atomic_write(js, json.dumps(review, indent=1) + "\n")
    _atomic_write(md, render_markdown(review))
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.core.market_session import last_closed_trading_day
    from swing_trade_ml.db.session import SessionLocal
    from swing_trade_ml.shadow_lanes.lane_service import SLOTS

    ap = argparse.ArgumentParser(
        description="Write the 60/90-session review of one shadow lane (read-only on data)"
    )
    ap.add_argument("slot", choices=list(SLOTS))
    ap.add_argument("--as-of", help="YYYY-MM-DD; default: the last closed session")
    a = ap.parse_args(argv)
    as_of = date.fromisoformat(a.as_of) if a.as_of else last_closed_trading_day(datetime.now().astimezone())
    with SessionLocal() as db:
        try:
            md, _js = write_review(db, a.slot, as_of, repo_root=REPO_ROOT)
        except ReviewError as exc:
            print(exc)
            return 2
    print(md.read_text(encoding="utf-8"))
    print(f"Written: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
