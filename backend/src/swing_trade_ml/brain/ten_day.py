# backend/src/swing_trade_ml/brain/ten_day.py
# ruff: noqa: E501 (long lines are report sentences)
"""Ten-day strategy protocol (td-protocol-v1), the history gate: the 10-day large-cap model judged on history.

Spec: `docs/superpowers/specs/2026-10-26-td-protocol-v1-PROPOSAL.md` (signed 2026-11-02). Read-only evidence
tool, the 10-day twin of `walk_forward` (wf-protocol-v1) and `five_day`, both of which stay exactly as they were.

- The model's question and the trade are the same (a barrier label): does the stock reach +6% before -3.5%
  within 10 trading days? Each fold trains a fresh model with outcomes known by its cutoff (`ml.train.train_model`,
  never activated) and scores the 49 watchlisted stocks (today's list: survivor bias, stated in the report).
- The trade: enter at the next trading day's open; stop checked before target on a day touching both; gaps fill
  at the open; no half-out; sold at the close of the 10th bar otherwise. Costs per `services/costs.py`, with
  slippage 0.10% per side in total (the code default 0.05% plus 0.05% extra), pinned below.
- Picks: the best 5 by model score each day. The decision rule is wf-protocol-v1's (same thresholds, so horizons
  are judged alike) with 10-day bootstrap blocks (the hold length).
- This gate decides only whether a shadow lane may be proposed. It is never proof (the 10D history is contaminated,
  protocol section 3).

GUARD. A real run refuses unless the git tag `td-protocol-v1` is in HEAD's history, the frozen files are unchanged
since the tag, and no report exists for the window. Nothing here is imported by live code, writes to the database,
or activates a model.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# isort: off
import swing_trade_ml.services.risk  # noqa: F401  # load order only: without it the brain package has a circular import when this file runs on its own
import swing_trade_ml.brain.walk_forward as wf

# isort: on
from swing_trade_ml.brain import splits
from swing_trade_ml.brain.horizon_grid import _days_beaten, _group, _index_after, summarise, top_k_by_day
from swing_trade_ml.brain.replay_scoring import CostStress, StrictOutcome, strict_score
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

PROTOCOL_VERSION = "td-protocol-v1"
TAG = PROTOCOL_VERSION  # the owner tags the merge commit with this name; no real run before it
SPEC = "docs/superpowers/specs/2026-10-26-td-protocol-v1-PROPOSAL.md"
FROZEN_FILES = (
    "backend/src/swing_trade_ml/brain/ten_day.py",
    SPEC,
)
CONFIRMATION = (date(2023, 7, 1), date(2025, 1, 31))  # section 5: the only pass-or-fail sample
OUT_DIR = "docs/brain/evidence/td_v1"

HORIZON_BARS = 10
TARGET = 0.06  # T1-c, pinned: a local .env must not change a result
STOP = 0.035
TOP_K = 5
BLOCK_DAYS = 10  # the hold length: days closer than this are not independent
LOAD_EXTRA_DAYS = 40  # calendar days of prices loaded after the last test day so its trades can finish
CODE_DEFAULT_SLIPPAGE_BPS = 5.0
STRESS = CostStress(
    extra_slip=0.0005
)  # 0.05% code default + 0.05% = 0.10% per side (protocol section 6, rule 4)


class RunRefusedError(RuntimeError):
    """A real td-protocol-v1 run was asked for before it is allowed."""


def assert_costs_pinned() -> None:
    """The scorer reads settings, which a local .env can override: refuse rather than score at other costs."""
    if settings.PAPER_SLIPPAGE_BPS != CODE_DEFAULT_SLIPPAGE_BPS:
        raise RunRefusedError(
            f"{PROTOCOL_VERSION} refused: PAPER_SLIPPAGE_BPS is {settings.PAPER_SLIPPAGE_BPS}, "
            f"the protocol pins the code default {CODE_DEFAULT_SLIPPAGE_BPS} (plus 0.05% extra = 0.10% per side)."
        )


make_folds = wf.make_folds


def score_trade(bars: pd.DataFrame, stress: CostStress = STRESS) -> StrictOutcome:
    """`bars`: the entry day first (the day after the decision). +6% / -3.5%, 10 bars, no half-out."""
    return strict_score(bars, horizon=HORIZON_BARS, target=TARGET, stop=STOP, half_out=None, stress=stress)


def outcomes_ten(
    bars: dict[str, pd.DataFrame], days: Sequence[date], stress: CostStress = STRESS
) -> dict[tuple[str, date], StrictOutcome]:
    out: dict[tuple[str, date], StrictOutcome] = {}
    for sym, df in bars.items():
        bar_days = list(df["day"])
        have = set(bar_days)
        for day in days:
            if day not in have:
                continue
            k = _index_after(bar_days, day)
            if k is not None:
                out[(sym, day)] = score_trade(df.iloc[k : k + HORIZON_BARS], stress)
    return out


def evaluate(
    bars: dict[str, pd.DataFrame],
    folds: Sequence[wf.Fold],
    model_scores: Callable[[wf.Fold], dict[str, dict[date, float]]],
    stress: CostStress = STRESS,
) -> dict:
    """`model_scores(fold)` returns {symbol: {day: score}} from a model trained only on data known by the
    fold's cutoff (replaceable in tests). Picks never depend on costs."""
    fold_rows: list[dict] = []
    pooled: dict[str, dict[date, list[StrictOutcome]]] = {"model": {}, "momentum": {}, "every": {}}
    diffs: dict[str, list[float]] = {"model": [], "momentum": []}
    split_rows: dict[str, list[tuple[str, str, StrictOutcome]]] = {"model": [], "every_stock": []}
    labels: list[str] = []
    for fold in folds:
        days = sorted({d for df in bars.values() for d in df["day"] if fold.start <= d <= fold.end})
        if not days:
            continue
        outcomes = outcomes_ten(bars, days, stress)
        everyone = {d: [s for (s, dd) in outcomes if dd == d] for d in days}
        scores = model_scores(fold)
        picks = {
            "model": top_k_by_day(scores, days, TOP_K),
            "momentum": top_k_by_day(wf.momentum_scores(bars, days), days, TOP_K),
        }
        grouped = {name: _group(p, outcomes) for name, p in picks.items()}
        grouped["every"] = _group(everyone, outcomes)
        for name, g in grouped.items():
            pooled[name].update(g)
        for name in ("model", "momentum"):
            diffs[name].extend(wf.daily_edge(picks[name], everyone, outcomes))
        regime = wf.classify_regime(bars, fold.start, fold.end)
        labels.append(regime["label"])
        for name, chosen in (("model", picks["model"]), ("every_stock", everyone)):
            split_rows[name].extend(
                (regime["label"], s, outcomes[(s, d)])
                for d, syms in chosen.items()
                for s in syms
                if (s, d) in outcomes
            )
        fold_rows.append(
            {
                "cutoff": fold.cutoff.isoformat(),
                "start": fold.start.isoformat(),
                "end": fold.end.isoformat(),
                "days": len(days),
                "regime": regime,
                "model": summarise(grouped["model"]),
                "momentum": summarise(grouped["momentum"]),
                "every_stock": summarise(grouped["every"]),
                "model_days_better": _days_beaten(picks["model"], everyone, outcomes),
            }
        )
    eligible = [r for r in fold_rows if wf.is_eligible(r)]
    model_all = summarise(pooled["model"])
    edge_low = wf.bootstrap_low(diffs["model"], block=BLOCK_DAYS)
    by_regime: dict[str, dict] = defaultdict(lambda: {"folds": 0, "better": 0})
    for r in fold_rows:
        b = by_regime[r["regime"]["label"]]
        b["folds"] += 1
        b["better"] += 1 if wf._fold_better(r) else 0
    return {
        "protocol": PROTOCOL_VERSION,
        "top_k": TOP_K,
        "rule": {
            "horizon": HORIZON_BARS,
            "target": TARGET,
            "stop": STOP,
            "half_out": None,
            "block_days": BLOCK_DAYS,
        },
        "costs": f"slippage 0.10% per side in total; {stress.label}",
        "stocks": len(bars),
        "folds": fold_rows,
        "pooled": {
            "model": model_all,
            "momentum": summarise(pooled["momentum"]),
            "every_stock": summarise(pooled["every"]),
            "model_edge_per_day": wf._mean(diffs["model"]),
            "model_edge_low": edge_low,
            "momentum_edge_per_day": wf._mean(diffs["momentum"]),
        },
        "by_regime": dict(by_regime),
        "splits": {
            name: {
                "by_market_type": splits.by_market_type(rows, labels),
                "by_sector": splits.by_sector((s, o) for _, s, o in rows),
            }
            for name, rows in split_rows.items()
        },
        "worst_fold_avg": min(
            (r["model"]["avg_net_by_day"] for r in eligible if r["model"]["avg_net_by_day"] is not None),
            default=None,
        ),
        "not_yet_reported": "random-5 accounts, 5 strongest risers by account, NIFTY 50 held and cash (protocol section 5) are added before the tag",
        "verdict": wf.verdict(
            model_ideas=model_all["ideas"],
            eligible=len(eligible),
            predictive_wins=sum(1 for r in eligible if wf._fold_better(r)),
            economic_wins=sum(1 for r in eligible if wf._fold_profitable(r)),
            edge_low=edge_low,
            pooled_avg_net=model_all["avg_net"],
        ),
    }


# ---------------------------------------------------------------- the guard


def refusal_reasons(
    *, tag_on_head: bool, changed_since_tag: Sequence[str], already_ran: Sequence[str]
) -> list[str]:
    reasons: list[str] = []
    if not tag_on_head:
        reasons.append(
            f"The git tag {TAG} is not in this commit's history: the protocol is not frozen yet. "
            "The owner tags the merge commit first; only then does the one history run happen."
        )
    for path in changed_since_tag:
        reasons.append(
            f"{path} differs from the tagged version: a changed setting is td-protocol-v2, not v1."
        )
    for path in already_ran:
        reasons.append(f"{path} already exists: the history gate runs once, with no re-runs.")
    return reasons


def git_guard_state(repo_root: Path) -> tuple[bool, list[str]]:
    import subprocess

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo_root), *a], capture_output=True, text=True, check=False)

    if TAG not in git("tag", "--merged", "HEAD", "-l", TAG).stdout.split():
        return False, []
    return True, git("diff", "--name-only", TAG, "--", *FROZEN_FILES).stdout.split()


def output_paths(out_dir: Path, first: date, last: date) -> tuple[Path, Path]:
    stem = f"ten_day_{first.isoformat()}_{last.isoformat()}"
    return out_dir / f"{stem}.md", out_dir / f"{stem}.json"


def check_run_allowed(
    out_dir: Path, first: date, last: date, *, state: tuple[bool, list[str]] | None = None
) -> None:
    from swing_trade_ml.core.config import REPO_ROOT

    tag_on_head, changed = state if state is not None else git_guard_state(REPO_ROOT)
    ran = [str(p) for p in output_paths(out_dir, first, last) if p.exists()]
    reasons = refusal_reasons(tag_on_head=tag_on_head, changed_since_tag=changed, already_ran=ran)
    if reasons:
        raise RunRefusedError(
            f"{PROTOCOL_VERSION} refused: nothing was scored and no result was produced.\n"
            + "\n".join(f"- {r}" for r in reasons)
            + "\nUse --dry-run to see the folds and settings without scoring anything."
        )


def dry_run_plan(
    first_start: date, last_end: date, *, state: tuple[bool, list[str]] | None = None, out_dir: Path
) -> str:
    from swing_trade_ml.core.config import REPO_ROOT

    tag_on_head, changed = state if state is not None else git_guard_state(REPO_ROOT)
    ran = [str(p) for p in output_paths(out_dir, first_start, last_end) if p.exists()]
    reasons = refusal_reasons(tag_on_head=tag_on_head, changed_since_tag=changed, already_ran=ran)
    folds = make_folds(first_start, last_end)
    return "\n".join(
        [
            f"{PROTOCOL_VERSION} dry run (nothing scored).",
            f"Sample {first_start} to {last_end}: "
            + (
                "the confirmation sample."
                if (first_start, last_end) == CONFIRMATION
                else "not the confirmation sample."
            ),
            f"{len(folds)} folds: " + ", ".join(f"{f.start}..{f.end}" for f in folds),
            f"Rule: reach +{TARGET:.0%} before -{STOP:.1%} within {HORIZON_BARS} trading days, no half-out, "
            "enter the next open, gaps fill at the open, slippage 0.10% per side, best 5 a day.",
            "A real run is "
            + ("allowed." if not reasons else "refused:\n" + "\n".join(f"- {r}" for r in reasons)),
        ]
    )


# ---------------------------------------------------------------- the real run (database; read-only)


def _train(db, cutoff: date):
    from swing_trade_ml.ml.train import train_model

    return train_model(
        db,
        name=f"td_h{HORIZON_BARS}_{cutoff:%Y%m%d}",
        cutoff=cutoff,
        horizon_days=HORIZON_BARS,
        target_return=TARGET,
        stop_return=STOP,
        auto_activate=False,
    )


def collect(db, first_start: date, last_end: date):
    from sqlalchemy import select

    from swing_trade_ml.brain.replay_score import load_bars
    from swing_trade_ml.db.models.market import Instrument

    instruments = list(
        db.execute(
            select(Instrument).where(Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True))
        ).scalars()
    )
    bars = {
        s: df
        for s, df in load_bars(
            db, [i.tradingsymbol for i in instruments], last_end + timedelta(days=LOAD_EXTRA_DAYS)
        ).items()
        if len(df)
    }
    return instruments, bars


def run(db, *, first_start: date, last_end: date, out_dir: Path) -> tuple[Path, Path]:
    from swing_trade_ml.ml.asof import score_series

    assert_costs_pinned()
    check_run_allowed(out_dir, first_start, last_end)
    instruments, bars = collect(db, first_start, last_end)

    def model_scores(fold: wf.Fold) -> dict[str, dict[date, float]]:
        model = _train(db, fold.cutoff)
        return {
            i.tradingsymbol: {
                d: p
                for d, p in score_series(db, i, model, fold.cutoff).items()
                if fold.start <= d <= fold.end
            }
            for i in instruments
        }

    result = evaluate(bars, make_folds(first_start, last_end), model_scores)
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = output_paths(out_dir, first_start, last_end)
    md.write_text(plain_report(result), encoding="utf-8")
    js.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    return md, js


def _pct(x: float | None) -> str:
    return "not measured" if x is None else f"{x * 100:+.2f}%"


def plain_report(result: dict) -> str:
    p, v = result["pooled"], result["verdict"]
    m, e = p["model"], p["every_stock"]
    return "\n".join(
        [
            f"# {PROTOCOL_VERSION}: 10-day model, history gate",
            "",
            "**This gate only decides whether a shadow lane may be proposed. It is never proof.**",
            "**Ranking and trading are different questions.** The first part asks whether the model's best 5 beat every stock "
            "on the same days; the second asks whether the actual trade (+6% / -3.5%, out by day 10, after costs) made money.",
            "",
            f"Rule: reach +{TARGET:.0%} before -{STOP:.1%} within {HORIZON_BARS} trading days. Costs: {result['costs']}.",
            f"Stocks: {result['stocks']} (today's watchlist: survivor bias). Folds: {len(result['folds'])}.",
            "",
            f"- Picks beat every stock: **{v['predictive']['word']}** ({v['predictive']['folds_won']} of {v['predictive']['eligible_folds']} eligible folds; lower bound {_pct(p['model_edge_low'])}).",
            f"- Trades made money after costs: **{v['economic']['word']}** (average per trade {_pct(m['avg_net'])}; {m['ideas']} finished ideas).",
            f"- Every stock, same days: average per trade {_pct(e['avg_net'])}.",
            f"- Reading: {v['reading']}",
            "",
            f"Not yet reported: {result['not_yet_reported']}.",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.core.config import REPO_ROOT

    ap = argparse.ArgumentParser(
        description=f"{PROTOCOL_VERSION}: the 10-day history gate (read-only evidence)"
    )
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    first, last = date.fromisoformat(a.start), date.fromisoformat(a.end)
    out_dir = REPO_ROOT / OUT_DIR
    if a.dry_run:
        print(dry_run_plan(first, last, out_dir=out_dir))
        return 0
    try:
        check_run_allowed(out_dir, first, last)
        assert_costs_pinned()
    except RunRefusedError as e:
        print(e)
        return 2
    from swing_trade_ml.db.session import SessionLocal

    with SessionLocal() as db:
        md, js = run(db, first_start=first, last_end=last, out_dir=out_dir)
    print(md.read_text(encoding="utf-8"))
    print(f"Written: {md} and {js}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
