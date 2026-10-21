# backend/src/swing_trade_ml/brain/module_ablation.py
"""Which modules really help? Switch one off at a time and replay (ps1, read-only evidence tool).

The brain is replayed over the same past days once with every module (the base) and once per module
with that module left out of the registry. The runner then uses the module's safe fallback, exactly as
it would live if the module failed. For each variant against the base:

- decisions whose final word changed;
- ideas the brain liked (TRADE, or a TRADE something lowered) that were added or dropped;
- the liked ideas' result after costs (strict rule: next-day open, +8% / -4%, half out at +5%, 15 days).

A module whose removal changes no decision adds nothing on these days. Leaving out the mandatory risk
gate (M07) is the check that its fallback is safe: no TRADE at all.

Only modules switched ON can change a decision; shadow modules are listed as not testable, and so are
modules a replay cannot judge (see NOT_JUDGEABLE). Replays are non-live brain runs in the local
database, under the brain run lock; nothing live changes and nothing counts toward the 30-idea gate.
Each variant is saved as soon as it finishes, so a stopped run resumes where it was.

Run (backend/): python -m swing_trade_ml.brain.module_ablation --from 2026-07-13 --to 2026-08-14
    --asof-model swing_classifier_asof_20260710
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from swing_trade_ml.brain.module import REGISTRY, Mode, ModuleRegistry, resolve_mode
from swing_trade_ml.brain.replay_scoring import StrictOutcome
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

PROTOCOL_ID = "ps1-module-ablation-v1"
BASE = "all modules"
RISK_GATE = "M07"
NOT_JUDGEABLE = {
    "M09": "learns after the decision; it changes no word in the same run",
    "M14": "reads today's account in a replay, not the account of the replayed day",
    "M15": "follows holdings; a replay has no holdings from the past",
}


@dataclass(frozen=True, slots=True)
class Judged:
    """One stock's final word on one day, and whether the brain liked it."""

    symbol: str
    day: date
    word: str
    liked: bool


def registry_without(module_id: str | None, base: ModuleRegistry = REGISTRY) -> ModuleRegistry:
    reg = ModuleRegistry()
    for cls in base.all():
        if cls.manifest.id != module_id:
            reg.register(cls)
    return reg


def plan(base: ModuleRegistry, modes: dict) -> tuple[list[str], dict[str, str]]:
    """(modules to switch off one at a time, {module: why it is not tested})."""
    test: list[str] = []
    skip: dict[str, str] = {}
    for cls in base.all():
        m = cls.manifest
        if m.id in NOT_JUDGEABLE:
            skip[m.id] = NOT_JUDGEABLE[m.id]
        elif resolve_mode(m, modes.get(m.id)) is not Mode.ON:
            skip[m.id] = "in shadow mode: it cannot change a decision"
        else:
            test.append(m.id)
    return test, skip


def judged_from(decisions: Iterable, day: date) -> list[Judged]:
    """Stock ideas of one run. Liked = the final word is TRADE, or a TRADE that something lowered."""
    out = []
    for d in decisions:
        if d.kind != "idea":
            continue
        word = d.overruled_word or d.word
        out.append(Judged(d.symbol, day, word, word == "TRADE" or d.downgraded_from == "TRADE"))
    return out


def compare(
    base: Sequence[Judged], variant: Sequence[Judged], outcomes: dict[tuple[str, date], StrictOutcome | None]
) -> dict:
    """The variant against the base, on the stock-days both judged."""
    b = {(j.symbol, j.day): j for j in base}
    v = {(j.symbol, j.day): j for j in variant}
    both = b.keys() & v.keys()
    liked = [k for k in v if v[k].liked]
    done = [o for k in liked if (o := outcomes.get(k)) is not None and o.net_return is not None]
    return {
        "judged": len(v),
        "trade_words": sum(j.word == "TRADE" for j in v.values()),
        "liked": len(liked),
        "changed_words": sum(b[k].word != v[k].word for k in both),
        "liked_added": sum(v[k].liked and not b[k].liked for k in both),
        "liked_dropped": sum(b[k].liked and not v[k].liked for k in both),
        "finished": len(done),
        "hit_rate": sum(o.status == "target" for o in done) / len(done) if done else None,
        "avg_net": sum(o.net_return for o in done) / len(done) if done else None,
    }


def reading(module_id: str, row: dict, base_row: dict) -> str:
    if module_id == RISK_GATE:
        return (
            "safe fallback: no TRADE without the risk gate"
            if row["trade_words"] == 0
            else f"UNSAFE: {row['trade_words']} TRADE words without the risk gate"
        )
    # In a replay the risk check refuses every idea, so final words can stay the
    # same while the module still decides which ideas the brain wanted.
    if row["changed_words"] == 0 and (row.get("liked_added") or row.get("liked_dropped")):
        if row.get("liked") == 0:
            return "makes every idea: without it the brain wants none"
        return (
            f"changes which ideas the brain wants (+{row['liked_added']} / -{row['liked_dropped']}); "
            "final words unchanged because the replay's risk check refuses them all"
        )
    if row["changed_words"] == 0:
        return "adds nothing on these days (no decision changed)"
    a, b = row["avg_net"], base_row["avg_net"]
    if a is None or b is None:
        return f"changes {row['changed_words']} decisions; result not comparable"
    better = "helps" if b > a else "hurts" if b < a else "neutral"
    return (
        f"changes {row['changed_words']} decisions; with it the liked ideas do {b - a:+.2%} "
        f"per idea ({better})"
    )


def run_variant(
    db: Session, days: Sequence[date], without: str | None, *, asof_model, replay: Callable | None = None
) -> list[Judged]:
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.replay_week import run_replay_week

    replay = replay or run_replay_week
    reg = registry_without(without)
    out: list[Judged] = []
    for day in days:
        (row,) = replay(db, start=day, end=day, asof_model=asof_model, registry=reg)
        out.extend(judged_from(service.decisions_for(db, row.run_id), day))
    return out


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        k: [Judged(j["symbol"], date.fromisoformat(j["day"]), j["word"], j["liked"]) for j in v]
        for k, v in raw.items()
    }


def _save(path: Path, done: dict[str, list[Judged]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        k: [{"symbol": j.symbol, "day": j.day.isoformat(), "word": j.word, "liked": j.liked} for j in v]
        for k, v in done.items()
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def run(
    db: Session,
    *,
    days: Sequence[date],
    asof_model,
    checkpoint: Path,
    upto: date,
    only: Sequence[str] | None = None,
    replay: Callable | None = None,
) -> dict:
    from swing_trade_ml.brain import service
    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.brain.replay_scoring import strict_for

    to_test, skipped = plan(REGISTRY, service.load_modes(db))
    if only:
        to_test = [m for m in to_test if m in only]
    variants = [BASE, *to_test]
    done = _load(checkpoint)
    for name in variants:
        if name in done:
            continue
        log.info("module_ablation.variant", without=name)
        done[name] = run_variant(
            db, days, None if name == BASE else name, asof_model=asof_model, replay=replay
        )
        _save(checkpoint, done)

    keys = {(j.symbol, j.day) for v in done.values() for j in v if j.liked}
    bars = load_bars(db, sorted({s for s, _ in keys}), upto)
    outcomes = {(s, d): (strict_for(bars[s], d) if s in bars and len(bars[s]) else None) for s, d in keys}
    base_row = compare(done[BASE], done[BASE], outcomes)
    rows = {}
    for name in to_test:
        row = compare(done[BASE], done[name], outcomes)
        rows[name] = {**row, "reading": reading(name, row, base_row)}
    return {
        "protocol": PROTOCOL_ID,
        "days": [d.isoformat() for d in days],
        "asof_model": getattr(asof_model, "name", None),
        "base": base_row,
        "without": rows,
        "not_tested": skipped,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def plain_report(result: dict) -> str:
    b = result["base"]
    days = result["days"]
    lines = [
        "# Which modules really help? (ps1)",
        "",
        f"Protocol: `{result['protocol']}`. Diagnostic on development data, not proof (EXPOSURE-LEDGER.md).",
        f"{len(days)} replayed days, {days[0] if days else '-'} to {days[-1] if days else '-'}, "
        f"model `{result['asof_model']}` (trained before these days).",
        f"With every module: {b['judged']} stock-days judged, {b['liked']} ideas liked, "
        f"{b['finished']} finished, average {_pct(b['avg_net'])} per idea after costs.",
        "",
        "| Module switched off | Decisions changed | Liked ideas added / dropped | Liked ideas | Avg / idea "
        "| Reading |",
        "|---|---|---|---|---|---|",
    ]
    for mid, r in result["without"].items():
        lines.append(
            f"| {mid} | {r['changed_words']} | {r['liked_added']} / {r['liked_dropped']} | {r['liked']} | "
            f"{_pct(r['avg_net'])} | {r['reading']} |"
        )
    lines += ["", "## Not tested", "", "| Module | Why |", "|---|---|"]
    lines += [f"| {m} | {why} |" for m, why in sorted(result["not_tested"].items())]
    lines += [
        "",
        "## Limits",
        "",
        "- Development data only. 'Helps' here is not evidence; 'adds nothing' or 'hurts' is a real warning.",
        "- In a replay the risk check uses today's account, so no replayed idea is ever approved; 'liked' "
        "counts the ideas the brain wanted before that check.",
        "- One switch at a time: two modules that do the same job would each look useless.",
        "- Only one as-of model exists locally, so only the days after its cutoff whose ideas have finished.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.brain.replay_week import iter_ist_trading_days
    from swing_trade_ml.cli import _load_asof_model
    from swing_trade_ml.db.session import SessionLocal
    from swing_trade_ml.ml.asof import asof_cutoff

    p = argparse.ArgumentParser(description="Module on/off replay (read-only evidence, ps1)")
    p.add_argument("--from", dest="start", required=True)
    p.add_argument("--to", dest="end", required=True)
    p.add_argument("--asof-model", required=True)
    p.add_argument("--upto", default="2026-09-07", help="last day of prices used to score ideas")
    p.add_argument("--only", nargs="*", default=None, help="test only these modules (e.g. M10 M07)")
    p.add_argument("--out", default="../docs/brain/evidence/module_ablation")
    a = p.parse_args(argv)
    days = list(iter_ist_trading_days(date.fromisoformat(a.start), date.fromisoformat(a.end)))
    out = Path(a.out)
    with SessionLocal() as db:
        model = _load_asof_model(db, a.asof_model)
        if model is None:
            p.error(f"no model named {a.asof_model}")
        cutoff = asof_cutoff(model)
        if cutoff is None or not days or days[0] <= cutoff:
            p.error(f"the days must start after the model's cutoff ({cutoff}), or it has seen them")
        result = run(
            db,
            days=days,
            asof_model=model,
            checkpoint=out / "checkpoint.json",
            upto=date.fromisoformat(a.upto),
            only=a.only,
        )
    out.mkdir(parents=True, exist_ok=True)
    (out / "module_ablation.md").write_text(plain_report(result), encoding="utf-8")
    (out / "module_ablation.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")
    print(plain_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
