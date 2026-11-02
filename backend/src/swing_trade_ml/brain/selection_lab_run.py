# backend/src/swing_trade_ml/brain/selection_lab_run.py
# ruff: noqa: E501 (long lines are report sentences)
"""Selection lab runner (draft `sl-protocol-v1`): the guard, the data, the fold loop and the report.

Design: `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (rev 3, with the owner's
2026-11-02 decision: no money management, ranking only). The pure rules live in `brain/selection_lab.py`; this
file adds what touches the world: git, files and the database. Nothing in it runs by itself.

A real run refuses unless ALL of these hold: the git tag `sl-protocol-v1` is in HEAD's history; the frozen files
are unchanged since the tag; the working tree is clean; the evidence-plan amendment is signed; every overnight
move over 20% in the 177 stocks has a written classification; the candidate has not run before; and, for S1 and
S2, the comparison candidate's result exists. It records an exposure-ledger row BEFORE any model is scored.
Candidates built: S0, S1, S2. S2r and S3 are not built (S3 is blocked by the owner until data are verified).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from swing_trade_ml.brain import selection_lab as sl

PROTOCOL = "sl-protocol-v1"
TAG = PROTOCOL
SPEC = "docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md"
FROZEN_FILES = (
    "backend/src/swing_trade_ml/brain/selection_lab.py",
    "backend/src/swing_trade_ml/brain/selection_lab_run.py",
    SPEC,
)
OUT_DIR = "docs/brain/evidence/sl_v1"
AMENDMENT = f"{OUT_DIR}/EVIDENCE_PLAN_AMENDMENT_SIGNED.md"
GAP_FILE = f"{OUT_DIR}/gap_classification.json"
SPLIT_DIR = "docs/brain/evidence/stock_split"
DEV_WINDOW = (date(2023, 7, 1), date(2026, 8, 15))
CANDIDATES = ("S0", "S1", "S2")
COMPARE_WITH = {"S1": "S0", "S2": "S1"}  # R4: S1 must beat S0, S2 must beat S1
LEDGER_MARKER = "sl-protocol-v1 {cand}, {first} to {last}"


class RunRefusedError(RuntimeError):
    """A real lab run was asked for before it is allowed."""


def load_split(repo_root: Path) -> tuple[list[str], list[str], str]:
    """(the 49, the 128 extra training stocks, file hash). Refuses if the file's hash differs from the one the
    locked note records: the split is never regenerated."""
    from swing_trade_ml.brain.stock_split import FILE_NAME, NOTE_NAME, file_sha256

    js, note = repo_root / SPLIT_DIR / FILE_NAME, repo_root / SPLIT_DIR / NOTE_NAME
    sha = file_sha256(js)
    recorded = re.search(r"SHA-256 of file \| `([0-9a-f]{64})`", note.read_text(encoding="utf-8"))
    if not recorded or recorded.group(1) != sha:
        raise RunRefusedError(
            f"{js.name} does not match the hash its locked note records: the split changed."
        )
    data = json.loads(js.read_text(encoding="utf-8"))
    return list(data["used_49"]), list(data["extra_training_set"]), sha


def load_gap_record(path: Path) -> dict[tuple[str, date], str]:
    """{(symbol, day): class} from a JSON object whose keys read 'SYMBOL|YYYY-MM-DD'. Missing file = empty."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for key, kind in raw.items():
        sym, day = key.split("|")
        out[(sym, date.fromisoformat(day))] = kind
    return out


def git_state(repo_root: Path) -> tuple[bool, list[str], bool]:
    """(tag in HEAD's history, frozen files changed since the tag, working tree dirty)."""

    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo_root), *a], capture_output=True, text=True, check=False)

    dirty = bool(git("status", "--porcelain").stdout.strip())
    if TAG not in git("tag", "--merged", "HEAD", "-l", TAG).stdout.split():
        return False, [], dirty
    return True, git("diff", "--name-only", TAG, "--", *FROZEN_FILES).stdout.split(), dirty


def amendment_signed(repo_root: Path) -> bool:
    p = repo_root / AMENDMENT
    return p.exists() and "SIGNED" in p.read_text(encoding="utf-8")


def refusal_reasons(
    *,
    candidate: str,
    tag_on_head: bool,
    changed_since_tag: Sequence[str],
    dirty: bool,
    amendment: bool,
    unclassified: Sequence[tuple[str, date]],
    already_ran: Sequence[str],
    comparison_missing: str | None,
) -> list[str]:
    reasons: list[str] = []
    if candidate not in CANDIDATES:
        reasons.append(
            f"{candidate} is not built. Built candidates: {', '.join(CANDIDATES)} (S2r and S3 are not built)."
        )
    if not tag_on_head:
        reasons.append(
            f"The git tag {TAG} is not in this commit's history: the protocol is not signed and frozen."
        )
    reasons += [
        f"{p} differs from the tagged version: a changed rule is sl-protocol-v2, not v1."
        for p in changed_since_tag
    ]
    if dirty:
        reasons.append(
            "The working tree has uncommitted changes: a run must come from a clean, committed tree."
        )
    if not amendment:
        reasons.append(
            f"The evidence-plan amendment is not signed ({AMENDMENT} is missing or not marked SIGNED)."
        )
    if unclassified:
        shown = ", ".join(f"{s} {d}" for s, d in list(unclassified)[:8])
        reasons.append(
            f"{len(unclassified)} overnight move(s) over 20% have no written classification in {GAP_FILE}: {shown}"
        )
    reasons += [f"{p} already exists: each candidate runs once, with no re-runs." for p in already_ran]
    if comparison_missing:
        reasons.append(
            f"{candidate} is compared with {comparison_missing}, whose result does not exist yet: run it first."
        )
    return reasons


def existing_runs(out_dir: Path, candidate: str) -> list[Path]:
    return sorted(out_dir.glob(f"sl1-{candidate}-*")) if out_dir.exists() else []


def ledger_row(candidate: str, first: date, last: date, *, run_day: date, run_id: str) -> str:
    return (
        f"| {first.isoformat()} to {last.isoformat()} (49 stocks) | "
        f"{LEDGER_MARKER.format(cand=candidate, first=first, last=last)}: 15-day selection lab, ranking only; "
        "run once | Owner's decision: to be written after reading | "
        f"{run_day.isoformat()} | `sl_v1/{run_id}/` |"
    )


def add_ledger_row(
    path: Path, candidate: str, first: date, last: date, *, run_day: date, run_id: str
) -> None:
    """Write the run's row before any result exists. A window that already has a row has had its one run."""
    text = path.read_text(encoding="utf-8")
    marker = LEDGER_MARKER.format(cand=candidate, first=first, last=last)
    if marker in text:
        raise RunRefusedError(f"{marker} already has a row in the exposure ledger: it has had its one run.")
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Local data"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last_row = max(i for i in range(start, end) if lines[i].startswith("|"))
    lines.insert(last_row + 1, ledger_row(candidate, first, last, run_day=run_day, run_id=run_id))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def to_json(result: Mapping) -> str:
    """The result as JSON: dates in `ic_by_day` become ISO strings (a later candidate's R4 reads them back)."""
    out = dict(result)
    out["ic_by_day"] = {d.isoformat(): v for d, v in result["ic_by_day"].items()}
    return json.dumps(out, indent=1, default=str)


def read_ic(result_file: Path) -> dict[date, float]:
    raw = json.loads(result_file.read_text(encoding="utf-8"))["ic_by_day"]
    return {date.fromisoformat(d): v for d, v in raw.items()}


def _pct(x: float | None, digits: int = 3) -> str:
    return "not measured" if x is None else f"{x:+.{digits}f}"


def plain_report(result: Mapping, manifest: Mapping) -> str:
    r1, r2, r3 = result["r1"], result["r2"], result["r3"]
    lines = [
        f"# {manifest['Candidate']}: 15-day stock selection lab, ranking only",
        "",
        result["statement"],
        "",
        f"**Money: {result['money']}**",
        "",
        "Best label this result can carry: **NO WARNING (diagnostic)**. It cannot qualify a winner and is never a PASS.",
        f"Ranking verdict: **{result['ranking_verdict']}**.",
        "",
        f"- R1 does a higher score pick better stocks? mean rank correlation {_pct(r1['mean_ic'])} over {r1['days']} days; "
        f"cautious lower bound {_pct(r1['lower_bound'])} ({'passes' if r1['passes'] else 'does not pass'}).",
        f"- R2 is the best 5 better than the day's median and than momentum? best-5 excess {_pct(r2['excess'], 4)} vs momentum "
        f"{_pct(r2['momentum_excess'], 4)} ({'passes' if r2['passes'] else 'does not pass'}).",
        f"- R3 consistent across test periods? positive in {r3['positive']} of {r3['eligible']} eligible periods "
        f"({r3['state']}; {'passes' if r3['passes'] else 'does not pass'}).",
    ]
    if "r4" in result:
        r4 = result["r4"]
        lines.append(
            f"- R4 against {manifest.get('Compared with')} ({r4['mode'].replace('_', ' ')}): difference {_pct(r4['mean_difference'])}, "
            f"lower bound {_pct(r4['lower_bound'])} over {r4['days']} days ({'passes' if r4['passes'] else 'does not pass'})."
        )
    lines += ["", "By market condition (labelled afterwards; reporting only):"]
    for label, v in sorted(result["by_market_condition"].items()):
        lines.append(
            f"- {label}: {v['days']} days, mean rank correlation {_pct(v['mean_ic'])}, best-5 excess {_pct(v['top5_excess'], 4)}"
        )
    lines += ["", "Run record:"]
    lines += [f"- {k}: {v}" for k, v in manifest.items()]
    return "\n".join(lines)


def run(
    candidate: str,
    *,
    repo_root: Path,
    collect_fn: Callable[[], tuple[dict, list[str], list[str]]],
    model_scores_fn: Callable[[str, dict], Callable[[sl.Fold], dict[str, dict[date, float]]]],
    state: tuple[bool, list[str], bool] | None = None,
    today: date | None = None,
    first: date = DEV_WINDOW[0],
    last: date = DEV_WINDOW[1],
    commit: str = "unknown",
) -> Path:
    """The one real run of `candidate`: guard, ledger row, folds, report. `collect_fn()` returns (bars of the
    177, the 49, the 128 extras); `model_scores_fn(candidate, bars)` returns the per-fold scoring callback."""
    out_dir = repo_root / OUT_DIR
    tag_on_head, changed, dirty = state if state is not None else git_state(repo_root)
    used, extra, split_sha = load_split(repo_root)
    record = load_gap_record(repo_root / GAP_FILE)
    bars, used49, extra128 = collect_fn()
    unclassified: list[tuple[str, date]] = []
    for sym in [*used49, *extra128]:
        if sym in bars:
            unclassified += sl.unclassified(sym, sl.overnight_flags(bars[sym]), record)
    compare = COMPARE_WITH.get(candidate)
    compare_file = None
    if compare:
        runs = existing_runs(out_dir, compare)
        compare_file = (runs[-1] / "metrics.json") if runs else None
    reasons = refusal_reasons(
        candidate=candidate,
        tag_on_head=tag_on_head,
        changed_since_tag=changed,
        dirty=dirty,
        amendment=amendment_signed(repo_root),
        unclassified=unclassified,
        already_ran=[str(p) for p in existing_runs(out_dir, candidate)],
        comparison_missing=compare
        if compare and (compare_file is None or not compare_file.exists())
        else None,
    )
    if used49 != used or sorted(extra128) != sorted(extra):
        reasons.append("The stock lists loaded for this run differ from the locked split file.")
    if reasons:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: nothing was trained or scored.\n"
            + "\n".join(f"- {r}" for r in reasons)
        )
    day = today or date.today()
    run_id = f"sl1-{candidate}-{datetime.now().strftime('%Y%m%dT%H%M')}"
    add_ledger_row(
        repo_root / "docs" / "brain" / "EXPOSURE-LEDGER.md",
        candidate,
        first,
        last,
        run_day=day,
        run_id=run_id,
    )
    scored_bars = {s: bars[s] for s in used49 if s in bars}
    result = sl.evaluate_ranking(
        scored_bars,
        sl.make_folds(first, last),
        model_scores_fn(candidate, bars),
        used49,
        comparison_ic=read_ic(compare_file) if compare_file else None,
        r4_mode="better" if compare else None,
    )
    manifest = {
        "Candidate": candidate,
        "Protocol": f"{PROTOCOL} (tag in this commit's history)",
        "Compared with": compare,
        "Code commit": commit,
        "Window": f"{first} to {last}",
        "Split file hash": split_sha,
        "Stocks scored": len(scored_bars),
        "Trained on": "177 (49 + 128 extra)" if candidate == "S2" else "49",
        "Held-back 129": "not used",
        "Models": "registered TRAINED, never activated",
    }
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "metrics.json").write_text(to_json(result), encoding="utf-8")
    (run_dir / "report.md").write_text(plain_report(result, manifest), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------- the real data and models (database)


def collect_db(db, last: date = DEV_WINDOW[1]):
    """(bars of the 177 stocks with volume, the 49, the 128). The lists come from the locked split file; the held-back
    129 are never loaded."""
    from datetime import timedelta

    import swing_trade_ml.services.risk  # noqa: F401  # load order only: avoids a circular import when run on its own
    from swing_trade_ml.brain.five_day import load_bars_with_volume
    from swing_trade_ml.core.config import REPO_ROOT

    used, extra, _sha = load_split(REPO_ROOT)
    bars = {
        s: df
        for s, df in load_bars_with_volume(db, [*used, *extra], last + timedelta(days=40)).items()
        if len(df)
    }
    return bars, used, extra


def model_scores_db(db, used: Sequence[str], extra: Sequence[str]):
    """Per-fold scoring callback factory: S0 trains the raw 15-day barrier model on the 49; S1 trains the excess
    label on the 49; S2 trains it on the 177. All models are registered TRAINED, never activated. Only the 49 are
    scored."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.asof import score_series
    from swing_trade_ml.ml.train import train_model

    insts = list(db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(list(used)))).scalars())

    def factory(candidate: str, bars: dict):
        def scores(fold: sl.Fold) -> dict[str, dict[date, float]]:
            name = f"sl1_{candidate}_{fold.cutoff:%Y%m%d}"
            if candidate == "S0":
                model = train_model(
                    db, name=name, symbols=list(used), horizon_days=sl.HORIZON_BARS, target_return=0.08,
                    stop_return=0.04, cutoff=fold.cutoff, auto_activate=False,
                )  # fmt: skip
            else:
                model = sl.train_lab_model(
                    db,
                    name=name,
                    cutoff=fold.cutoff,
                    symbols=[*used, *extra] if candidate == "S2" else list(used),
                    candidates=list(used),
                    bars=bars,
                    record=load_gap_record(_repo() / GAP_FILE),
                )
            return {
                i.tradingsymbol: {
                    d: p
                    for d, p in score_series(db, i, model, fold.cutoff).items()
                    if fold.start <= d <= fold.end
                }
                for i in insts
            }

        return scores

    return factory


def _repo() -> Path:
    from swing_trade_ml.core.config import REPO_ROOT

    return REPO_ROOT


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=f"{PROTOCOL}: 15-day selection lab, one candidate (ranking only)"
    )
    ap.add_argument("candidate", choices=CANDIDATES)
    a = ap.parse_args(argv)
    repo = _repo()
    from swing_trade_ml.db.session import SessionLocal

    with SessionLocal() as db:
        bars, used, extra = collect_db(db)
        factory = model_scores_db(db, used, extra)
        try:
            run_dir = run(
                a.candidate, repo_root=repo, collect_fn=lambda: (bars, used, extra), model_scores_fn=factory,
                commit=subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip(),
            )  # fmt: skip
        except RunRefusedError as e:
            print(e)
            return 2
    print((run_dir / "report.md").read_text(encoding="utf-8"))
    print(f"Written: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
