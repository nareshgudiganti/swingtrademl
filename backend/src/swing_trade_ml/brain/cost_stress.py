# backend/src/swing_trade_ml/brain/cost_stress.py
"""Does the result survive dearer trading? (ps3, read-only evidence tool)

The same picks are scored again with charges doubled and every fill 0.3% worse (and both),
using the strict rule's `CostStress`. Picks never depend on costs, so nothing is retuned:

- walk-forward: each fold's model is trained ONCE and its scores are reused for every cost
  setting; only the scoring of the ideas (and of the every-stock and momentum baselines) changes;
- stored replay ideas (e.g. `asof_replay_*.json`): the saved (stock, day) ideas are re-scored from
  daily prices. No model runs at all.

All local data is development data (EXPOSURE-LEDGER.md), so this is a diagnostic: it can show
that a thin edge disappears at real-world costs; it cannot prove an edge. Registers trial models
(`wf_*`, never activated) and changes nothing live.

Run (backend/): python -m swing_trade_ml.brain.cost_stress --wf-from 2023-07-01 --wf-to 2025-01-31
    --replay ../docs/brain/evidence/asof_replay_2026-07-13_2026-08-14.json
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from swing_trade_ml.brain import walk_forward as wf
from swing_trade_ml.brain.replay_score import load_bars
from swing_trade_ml.brain.replay_scoring import NORMAL, CostStress, after_day, strict_score
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

EXTRA_SLIP = 0.003  # "fills 0.3% worse", per fill, on top of the normal slippage
STRESSES = (
    NORMAL,
    CostStress(charges_x=2.0),
    CostStress(extra_slip=EXTRA_SLIP),
    CostStress(charges_x=2.0, extra_slip=EXTRA_SLIP),
)
HARSHEST = STRESSES[-1]
MATCH_TOLERANCE = 1e-6  # a re-scored idea at normal costs must equal the stored result


def stresses_with(extra_slip_bps: float | None) -> tuple[CostStress, ...]:
    """The fixed settings, plus a measured one (ps4: real fill quality) when it is known."""
    if not extra_slip_bps:
        return STRESSES
    measured = CostStress(extra_slip=extra_slip_bps / 10_000.0)
    return (*STRESSES, measured) if measured not in STRESSES else STRESSES


def _compact(result: dict) -> dict:
    """The few numbers the cost question needs from one walk-forward result."""
    pooled = result["pooled"]
    return {
        "model": pooled["model"],
        "every_stock": pooled["every_stock"],
        "momentum": pooled["momentum"],
        "model_edge_per_day": pooled["model_edge_per_day"],
        "model_edge_low": pooled["model_edge_low"],
        "worst_fold_avg": result["worst_fold_avg"],
        "predictive": result["verdict"]["predictive"]["word"],
        "economic": result["verdict"]["economic"]["word"],
        "folds": len(result["folds"]),
    }


def stress_walk_forward(
    db: Session,
    *,
    first_start: date,
    last_end: date,
    stresses: Sequence[CostStress] = STRESSES,
    test_days: int = 28,
    top_k: int = 5,
    train_fn=None,
    score_fn=None,
) -> dict[str, dict]:
    """{stress label: compact walk-forward result}. Every model is trained and scored once."""
    if train_fn is None:
        train_fn = wf._train
    if score_fn is None:
        from swing_trade_ml.ml.asof import score_series as score_fn

    models: dict[tuple, object] = {}
    scores: dict[tuple, dict] = {}

    def cached_train(db_, cutoff, horizon, target, stop):
        key = (cutoff, horizon, target, stop)
        if key not in models:
            models[key] = train_fn(db_, cutoff, horizon, target, stop)
        return models[key]

    def cached_score(db_, instrument, model, after):
        key = (instrument.tradingsymbol, id(model), after)
        if key not in scores:
            scores[key] = score_fn(db_, instrument, model, after)
        return scores[key]

    out: dict[str, dict] = {}
    for stress in stresses:
        log.info("cost_stress.walk_forward", costs=stress.label)
        result = wf.run_walk_forward(
            db,
            first_start=first_start,
            last_end=last_end,
            test_days=test_days,
            top_k=top_k,
            train_fn=cached_train,
            score_fn=cached_score,
            stress=stress,
        )
        out[stress.label] = _compact(result)
    return out


def _summary(returns: list[float], statuses: list[str]) -> dict:
    if not returns:
        return {"ideas": 0, "hit_rate": None, "avg_net": None}
    return {
        "ideas": len(returns),
        "hit_rate": sum(s == "target" for s in statuses) / len(statuses),
        "avg_net": sum(returns) / len(returns),
    }


def stress_ideas(db: Session, ideas: Sequence[dict], stresses: Sequence[CostStress] = STRESSES) -> dict:
    """Re-score stored ideas ({day, symbol, strict_net_return}) at each cost setting. At normal
    costs every idea must reproduce its stored result; mismatches are counted, not hidden."""
    rows = [(date.fromisoformat(str(i["day"])), str(i["symbol"]), i.get("strict_net_return")) for i in ideas]
    if not rows:
        return {"ideas": 0, "by_costs": {}, "reproduced": 0, "mismatched": 0, "no_price_data": 0}
    bars = load_bars(db, sorted({s for _, s, _ in rows}), max(d for d, _, _ in rows) + timedelta(days=60))
    by_costs: dict[str, dict] = {}
    reproduced = mismatched = missing = 0
    for stress in stresses:
        returns: list[float] = []
        statuses: list[str] = []
        for day, sym, stored in rows:
            df = bars.get(sym)
            if df is None or df.empty:
                missing += stress == NORMAL
                continue
            o = strict_score(after_day(df, day), stress=stress)
            if o.net_return is None:
                continue
            returns.append(o.net_return)
            statuses.append(o.status)
            if stress == NORMAL and stored is not None:
                if abs(o.net_return - float(stored)) <= MATCH_TOLERANCE:
                    reproduced += 1
                else:
                    mismatched += 1
        by_costs[stress.label] = _summary(returns, statuses)
    return {
        "ideas": len(rows),
        "by_costs": by_costs,
        "reproduced": reproduced,
        "mismatched": mismatched,
        "no_price_data": missing,
    }


def survives(avg: float | None) -> str:
    if avg is None:
        return "not testable (no finished ideas)"
    return "stays above zero" if avg > 0 else "does not stay above zero"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def plain_report(result: dict) -> str:
    lines = [
        "# Cost stress test (ps3)",
        "",
        f"Protocol: `{result['protocol']}`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).",
        "Same picks, scored again with dearer trading. Normal costs = the settled strict rule.",
        "",
    ]
    harshest = result["harshest"]
    wf_rows = result.get("walk_forward")
    if wf_rows:
        w = result["walk_forward_window"]
        lines += [
            f"## Walk-forward {w['from']} to {w['to']} (model's best {result['top_k']} a day)",
            "",
            "| Costs | Model ideas | Model avg / trade | Every stock avg | Edge / day | Edge low (5%) "
            "| Profit part |",
            "|---|---|---|---|---|---|---|",
        ]
        for label, r in wf_rows.items():
            lines.append(
                f"| {label} | {r['model']['ideas']} | {_pct(r['model']['avg_net'])} | "
                f"{_pct(r['every_stock']['avg_net'])} | {_pct(r['model_edge_per_day'])} | "
                f"{_pct(r['model_edge_low'])} | {r['economic']} |"
            )
        h = wf_rows[harshest]
        lines += [
            "",
            f"**Answer (walk-forward):** at {harshest}, the model's average result per trade "
            f"{survives(h['model']['avg_net'])} ({_pct(h['model']['avg_net'])}); its edge over every stock "
            f"{survives(h['model_edge_per_day'])} ({_pct(h['model_edge_per_day'])} a day).",
            "",
        ]
    ideas = result.get("ideas")
    if ideas:
        lines += [
            f"## Stored replay ideas: `{result['ideas_source']}`",
            "",
            f"{ideas['ideas']} ideas; {ideas['reproduced']} reproduced exactly at normal costs, "
            f"{ideas['mismatched']} did not, {ideas['no_price_data']} had no prices.",
            "",
            "| Costs | Finished ideas | Hit +8% first | Avg / trade |",
            "|---|---|---|---|",
        ]
        for label, r in ideas["by_costs"].items():
            hit = "n/a" if r["hit_rate"] is None else f"{r['hit_rate']:.0%}"
            lines.append(f"| {label} | {r['ideas']} | {hit} | {_pct(r['avg_net'])} |")
        h = ideas["by_costs"].get(harshest, {})
        lines += [
            "",
            f"**Answer (replay ideas):** at {harshest}, the average result per trade "
            f"{survives(h.get('avg_net'))} ({_pct(h.get('avg_net'))}).",
            "",
        ]
    lines += [
        "## Limits",
        "",
        "- Development data only: a pass here would not be evidence; a fail is a real warning.",
        "- Under worse fills the target and stop follow the dearer buy price, as a live order would.",
        "- 0.3% is a round number, not measured. ps4 (real fill quality) will give a measured one.",
    ]
    return "\n".join(lines) + "\n"


PROTOCOL_ID = "ps3-cost-stress-v1"


def run(
    db: Session,
    *,
    wf_from: date | None,
    wf_to: date | None,
    replay_path: Path | None,
    extra_slip_bps: float | None = None,
    top_k: int = 5,
) -> dict:
    stresses = stresses_with(extra_slip_bps)
    harshest = HARSHEST.label  # the answer sentence is read at the fixed both-at-once setting
    result: dict = {
        "protocol": PROTOCOL_ID,
        "settings": [s.label for s in stresses],
        "harshest": harshest,
        "top_k": top_k,
    }
    if wf_from and wf_to:
        result["walk_forward_window"] = {"from": wf_from.isoformat(), "to": wf_to.isoformat()}
        result["walk_forward"] = stress_walk_forward(
            db, first_start=wf_from, last_end=wf_to, stresses=stresses, top_k=top_k
        )
    if replay_path:
        stored = json.loads(replay_path.read_text(encoding="utf-8"))
        result["ideas_source"] = replay_path.name
        result["ideas"] = stress_ideas(db, stored["ideas"], stresses)
    return result


def write_report(result: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md, js = directory / "cost_stress.md", directory / "cost_stress.json"
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="Cost stress test of stored picks (read-only evidence, ps3)")
    p.add_argument("--wf-from", default=None, help="YYYY-MM-DD: first walk-forward test day")
    p.add_argument("--wf-to", default=None, help="YYYY-MM-DD: last walk-forward test day")
    p.add_argument("--replay", default=None, help="stored replay JSON with an 'ideas' list")
    p.add_argument("--extra-slip-bps", type=float, default=None, help="measured extra slippage (ps4)")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--out", default="../docs/brain/evidence/cost_stress")
    a = p.parse_args(argv)
    if bool(a.wf_from) != bool(a.wf_to):
        p.error("--wf-from and --wf-to go together")
    if not (a.wf_from or a.replay):
        p.error("give a walk-forward window, a replay file, or both")
    with SessionLocal() as db:
        result = run(
            db,
            wf_from=date.fromisoformat(a.wf_from) if a.wf_from else None,
            wf_to=date.fromisoformat(a.wf_to) if a.wf_to else None,
            replay_path=Path(a.replay) if a.replay else None,
            extra_slip_bps=a.extra_slip_bps,
            top_k=a.top_k,
        )
    md, js = write_report(result, Path(a.out))
    print(plain_report(result))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
