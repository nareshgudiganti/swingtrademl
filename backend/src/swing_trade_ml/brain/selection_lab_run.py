# backend/src/swing_trade_ml/brain/selection_lab_run.py
# ruff: noqa: E501 (long lines are report sentences)
"""Selection lab runner (`sl-protocol-v1.1`, Amendment 3, ranking only): the guard, the data, the fold loop and the report.

Design: `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (rev 3, with the owner's
2026-11-02 decision: no money management, ranking only). The pure rules live in `brain/selection_lab.py`; this
file adds what touches the world: git, files and the database. Nothing in it runs by itself.

A real run refuses unless ALL of these hold: today (IST) is 2026-12-05 or later; Phase B has its verified terminal
record (the `phase-b-result` tag, `PHASE_B_RESULT.json`, manifests and ledger, checked by
`brain/selection_lab_start.py`, the same code the wrapper runs: `run` and `main` call it themselves, so running this
file directly does not skip it); the git tag `sl-protocol-v1.1` is in HEAD's history; the frozen files
are unchanged since the tag; the working tree is clean; the signed Amendment 3 marker exists; every overnight
move over 20% in the 177 stocks has a written classification; the candidate has not run before; and, for S1 and
S2, the comparison candidate's result exists. It records an exposure-ledger row BEFORE any model is scored.
Candidates built: S0, S1, S2 (large group, the 49) and S0M, S1M, S2M (the same three ideas on the 14-stock mid-cap
group; a limited experiment). S2r and S3 are not built (S3 is blocked by the owner until data are verified). The
held-back 129 are never loaded, trained on or scored (asserted in `run` and `collect_db`).

Technical rerun (same rules as ten_day.py): an attempt that left an exposure-ledger row but no finished run folder can
be rerun with `--technical-rerun`, at most twice, each needing one valid incident note per failed attempt in
`docs/brain/evidence/sl_v1/incidents/`. A finished run is never rerun. A run folder is written whole or not at all.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path

from swing_trade_ml.brain import selection_lab as sl

PROTOCOL = "sl-protocol-v1.1"
TAG = PROTOCOL
SPEC = "docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md"
AMENDMENT_TEXT = "docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md"
FROZEN_FILES = (
    "backend/src/swing_trade_ml/brain/selection_lab.py",
    "backend/src/swing_trade_ml/brain/selection_lab_run.py",
    "backend/src/swing_trade_ml/brain/selection_lab_start.py",  # the start checks this runner calls itself
    SPEC,
    AMENDMENT_TEXT,
)
OUT_DIR = "docs/brain/evidence/sl_v1"
AMENDMENT_2 = (
    f"{OUT_DIR}/EVIDENCE_PLAN_AMENDMENT_SIGNED.md"  # signed 2026-11-02; stays in place, never edited
)
AMENDMENT = f"{OUT_DIR}/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md"
GAP_FILE = f"{OUT_DIR}/gap_classification.json"
SPLIT_DIR = "docs/brain/evidence/stock_split"
HELD_BACK_KEY = "reject_set"  # key in the locked split file; its members are excluded, never used
DEV_WINDOW = (date(2023, 7, 1), date(2026, 8, 15))
CANDIDATES = ("S0", "S1", "S2", "S0M", "S1M", "S2M")
MID_CANDIDATES = ("S0M", "S1M", "S2M")
COMPARE_WITH = {
    "S1": "S0",
    "S2": "S1",
    "S1M": "S0M",
    "S2M": "S1M",
}  # R4: S1 beats S0, S2 beats S1 (mid alike)
LEDGER_MARKER = PROTOCOL + " {cand}, {first} to {last}"
RERUN_MARKER = PROTOCOL + " technical rerun {n} {cand}, {first} to {last}"
MAX_TECHNICAL_RERUNS = 2
INCIDENT_DIR = "incidents"
INCIDENT_KINDS = ("execution_failure", "data_integrity_failure")
MID_MODEL_NAME = "swing_classifier_midcap"


def is_mid(candidate: str) -> bool:
    return candidate in MID_CANDIDATES


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


def load_held_back(repo_root: Path) -> list[str]:
    """The held-back 129 from the locked split file. Used ONLY to prove they are absent from every list; never loaded."""
    from swing_trade_ml.brain.stock_split import FILE_NAME

    data = json.loads((repo_root / SPLIT_DIR / FILE_NAME).read_text(encoding="utf-8"))
    return list(data[HELD_BACK_KEY])


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
    """True only when the Amendment 2 marker exists AND the Amendment 3 marker has a line starting
    `SIGNED by the owner on <ISO date>` and names `sl-protocol-v1.1` and `Amendment 3`. ('UNSIGNED' does not count.)"""
    a2, a3 = repo_root / AMENDMENT_2, repo_root / AMENDMENT
    if not (a2.exists() and a3.exists()):
        return False
    text = a3.read_text(encoding="utf-8")
    return (
        re.search(r"^SIGNED by the owner on \d{4}-\d{2}-\d{2}", text, re.M) is not None
        and PROTOCOL in text
        and "Amendment 3" in text
    )


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
        f"{p} differs from the tagged version: a changed rule is a new protocol version, not {PROTOCOL}."
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


def ledger_row(
    candidate: str, first: date, last: date, *, run_day: date, run_id: str, rerun: int = 0, incident: str = ""
) -> str:
    what = (
        f"{LEDGER_MARKER.format(cand=candidate, first=first, last=last)}: 15-day selection lab, ranking only; run once"
        if rerun == 0
        else f"{RERUN_MARKER.format(n=rerun, cand=candidate, first=first, last=last)}: after incident {incident}; "
        "same code and rules; no result was read in the failed attempt"
    )
    stocks = "14 mid-cap stocks" if is_mid(candidate) else "49 stocks"
    return (
        f"| {first.isoformat()} to {last.isoformat()} ({stocks}) | {what} | "
        "Owner's decision: to be written after reading | "
        f"{run_day.isoformat()} | `sl_v1/{run_id}/` |"
    )


def ledger_attempts(text: str, candidate: str, first: date, last: date) -> int:
    """How many times this candidate has been started for this window: the first run plus any technical reruns."""
    first_run = LEDGER_MARKER.format(cand=candidate, first=first, last=last) in text
    reruns = sum(
        1
        for n in range(1, MAX_TECHNICAL_RERUNS + 2)
        if RERUN_MARKER.format(n=n, cand=candidate, first=first, last=last) in text
    )
    return (1 if first_run else 0) + reruns


def validate_incident(path: Path) -> list[str]:
    """An incident note must say what failed and that no result was read; it can never excuse a result someone saw."""
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    kind = re.search(r"^Kind:\s*(\S+)", text, re.M)
    if not kind or kind.group(1) not in INCIDENT_KINDS:
        problems.append(f"{path.name}: 'Kind:' must be one of {', '.join(INCIDENT_KINDS)}")
    cause = re.search(r"^Cause:\s*(\S.+)", text, re.M)
    if not cause or len(cause.group(1).strip()) < 15:
        problems.append(f"{path.name}: 'Cause:' must state what failed (at least a sentence)")
    if not re.search(r"^Result read:\s*none\s*$", text, re.M | re.I):
        problems.append(f"{path.name}: it must say 'Result read: none'")
    if not re.search(r"^Same code and rules:\s*yes\s*$", text, re.M | re.I):
        problems.append(f"{path.name}: it must say 'Same code and rules: yes'")
    return problems


def incident_notes(out_dir: Path, candidate: str) -> list[Path]:
    d = out_dir / INCIDENT_DIR
    return sorted(d.glob(f"incident_{candidate}_*.md")) if d.exists() else []


def plan_attempt(
    ledger_path: Path, out_dir: Path, candidate: str, first: date, last: date, technical_rerun: bool
) -> int:
    """0 for the first run; n >= 1 for the nth technical rerun. A finished run never reaches here (the guard refused
    it): a rerun is possible only after an attempt that left a ledger row but no run folder, and only with one valid
    incident note per failed attempt of this candidate."""
    attempts = ledger_attempts(ledger_path.read_text(encoding="utf-8"), candidate, first, last)
    if attempts == 0:
        if technical_rerun:
            raise RunRefusedError(f"{PROTOCOL} {candidate} refused: there is no earlier attempt to rerun.")
        return 0
    if not technical_rerun:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: an earlier attempt left a ledger row but no result. If infrastructure "
            f"failed (not a result you disliked), write an incident note in {OUT_DIR}/{INCIDENT_DIR}/ and rerun "
            "with --technical-rerun."
        )
    if attempts - 1 >= MAX_TECHNICAL_RERUNS:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: {MAX_TECHNICAL_RERUNS} technical reruns are already used. Anything "
            f"more is a new protocol version, not {PROTOCOL}."
        )
    notes = incident_notes(out_dir, candidate)
    if len(notes) < attempts:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: {attempts} failed attempt(s) need {attempts} incident note(s); "
            f"found {len(notes)} in {OUT_DIR}/{INCIDENT_DIR}/."
        )
    problems = [x for n in notes for x in validate_incident(n)]
    if problems:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: incident note problems:\n"
            + "\n".join(f"- {x}" for x in problems)
        )
    return attempts


def add_ledger_row(
    path: Path,
    candidate: str,
    first: date,
    last: date,
    *,
    run_day: date,
    run_id: str,
    rerun: int = 0,
    incident: str = "",
) -> None:
    """Write the attempt's row before any result exists. The first attempt cannot be written twice; a technical
    rerun adds its own row naming its incident note."""
    text = path.read_text(encoding="utf-8")
    marker = LEDGER_MARKER.format(cand=candidate, first=first, last=last)
    if rerun == 0 and marker in text:
        raise RunRefusedError(f"{marker} already has a row in the exposure ledger: it has had its one run.")
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## Local data"))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last_row = max(i for i in range(start, end) if lines[i].startswith("|"))
    lines.insert(
        last_row + 1,
        ledger_row(candidate, first, last, run_day=run_day, run_id=run_id, rerun=rerun, incident=incident),
    )
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


LIMITS = (
    "Survivor bias: the stock lists are today's lists, so stocks that fell out of favour are missing from the past.",
    "Ranking only: no costs, no capital, no position sizes. It says nothing about money.",
    "No liquidity or price-limit checks beyond the lab's turnover filter on reference stocks.",
    "The mid-cap group is a small, limited experiment (14 stocks); results carry wide uncertainty.",
    "The history is partly seen: earlier work on these stocks and dates informed the design, so this is not a fresh test.",
)


def plain_report(result: Mapping, manifest: Mapping) -> str:
    r1, r2, r3 = result["r1"], result["r2"], result["r3"]
    lines = [f"# {manifest['Candidate']}: 15-day stock selection lab, ranking only", ""]
    if result.get("sample_warning"):
        lines += [f"**{result['sample_warning']}**", ""]
    lines += [
        result["statement"],
        "",
        f"**Money: {result['money']}**",
        "",
        f"Best label this result can carry: **{result.get('label', sl.FULL_LABEL)}**. It cannot qualify a winner and is never a PASS.",
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
    if result.get("by_cap_group"):
        lines += ["", "By size group (each group is compared only with its own stocks):"]
        for name, g in sorted(result["by_cap_group"].items()):
            lines.append(
                f"- {name}: {g['stocks_scored']} stocks scored, {g['days']} days, mean rank correlation {_pct(g['mean_ic'])} "
                f"(cautious lower bound {_pct(g['lower_bound'])}); best-5 excess over the group's median {_pct(g['top5_excess_over_median'], 4)}, "
                f"over the group's own average stock {_pct(g['top5_excess_over_group_average'], 4)}; hit share {_pct(g['hit_share'], 2)}"
            )
        lines.append(f"- {result['benchmark']}")
    lines += ["", "Limits of this test:"] + [f"- {x}" for x in LIMITS]
    lines += ["", "Run record:"]
    lines += [f"- {k}: {v}" for k, v in manifest.items()]
    return "\n".join(lines)


def _trained_on(candidate: str) -> str:
    return {
        "S0M": "14 mid-cap stocks",
        "S1M": "14 mid-cap stocks",
        "S2M": "the 14 mid-cap stocks plus the extra 128 (union)",
        "S2": "177 (49 + 128 extra)",
    }.get(candidate, "49")


def run(
    candidate: str,
    *,
    repo_root: Path,
    collect_fn: Callable[[], tuple[dict, list[str], list[str]]],
    model_scores_fn: Callable[[str, dict], Callable[[sl.Fold], dict[str, dict[date, float]]]],
    mid_fn: Callable[[], Sequence[str]] | None = None,
    state: tuple[bool, list[str], bool] | None = None,
    today: date | None = None,
    first: date = DEV_WINDOW[0],
    last: date = DEV_WINDOW[1],
    commit: str = "unknown",
    technical_rerun: bool = False,
    start_check: Callable[[str, Path], Sequence[str]] | None = None,
) -> Path:
    """The one real run of `candidate`: guard, ledger row, folds, report. `collect_fn()` returns (bars of the
    stocks, the 49, the 128 extras); `mid_fn()` returns the 14-stock mid-cap group (mid candidates only);
    `model_scores_fn(candidate, bars)` returns the per-fold scoring callback. A failed attempt (ledger row, no run
    folder) can be rerun with `technical_rerun=True`, see `plan_attempt`.

    Before anything is read, `start_check(candidate, repo_root)` must return no refusal reasons. The default is the
    real start check (date, Phase B terminal record, protocol tag, clean tree, frozen files; see `start_conditions`),
    so calling `run` directly is guarded exactly like the wrapper. `start_check` exists only so unit tests can run
    this function on a synthetic repository; production code never passes it."""
    reasons_to_start = (start_check or start_conditions)(candidate, repo_root)
    if reasons_to_start:
        raise RunRefusedError(
            f"{PROTOCOL} {candidate} refused: nothing was trained or scored.\n"
            + "\n".join(f"- {r}" for r in reasons_to_start)
        )
    out_dir = repo_root / OUT_DIR
    tag_on_head, changed, dirty = state if state is not None else git_state(repo_root)
    used, extra, split_sha = load_split(repo_root)
    held_back = load_held_back(repo_root)
    record = load_gap_record(repo_root / GAP_FILE)
    bars, used49, extra128 = collect_fn()
    mid = list(mid_fn()) if (mid_fn and is_mid(candidate)) else []
    if is_mid(candidate) and not mid:
        raise RunRefusedError(f"{PROTOCOL} {candidate} refused: no mid-cap group was supplied.")
    scored_list = mid if is_mid(candidate) else used49
    try:
        sl.assert_no_held_back(
            held_back, bars=list(bars), used49=used49, extra128=extra128, mid=mid, scored=scored_list
        )
    except ValueError as e:
        raise RunRefusedError(f"{PROTOCOL} {candidate} refused: {e}") from e
    unclassified: list[tuple[str, date]] = []
    for sym in [*used49, *extra128, *mid]:
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
        unclassified=sorted(set(unclassified)),
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
    ledger = repo_root / "docs" / "brain" / "EXPOSURE-LEDGER.md"
    rerun = plan_attempt(ledger, out_dir, candidate, first, last, technical_rerun)
    run_id = f"sl1-{candidate}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    notes = incident_notes(out_dir, candidate) if rerun else []
    add_ledger_row(
        ledger,
        candidate,
        first,
        last,
        run_day=day,
        run_id=run_id,
        rerun=rerun,
        incident=notes[-1].name if notes else "",
    )
    scored_bars = {s: bars[s] for s in scored_list if s in bars}
    group = "mid" if is_mid(candidate) else "large"
    result = sl.evaluate_ranking(
        scored_bars,
        sl.make_folds(first, last),
        model_scores_fn(candidate, bars),
        scored_list,
        comparison_ic=read_ic(compare_file) if compare_file else None,
        r4_mode="better" if compare else None,
        groups={group: scored_list},
    )
    manifest = {
        "Candidate": candidate,
        "Protocol": f"{PROTOCOL} (tag in this commit's history)",
        "Compared with": compare,
        "Code commit": commit,
        "Window": f"{first} to {last}",
        "Split file hash": split_sha,
        "Group": f"{group} ({len(scored_list)} stocks listed)",
        "Stocks scored": len(scored_bars),
        "Trained on": _trained_on(candidate),
        "Technical rerun": rerun,
        "Held-back 129": "not used",
        "Models": "registered TRAINED, never activated",
    }
    # Whole or not at all: build the folder under a hidden name (never matched as a finished run), then rename it.
    run_dir = out_dir / run_id
    tmp_dir = out_dir / f".tmp-{run_id}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    (tmp_dir / "metrics.json").write_text(to_json(result), encoding="utf-8")
    (tmp_dir / "report.md").write_text(plain_report(result, manifest), encoding="utf-8")
    (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    os.replace(tmp_dir, run_dir)
    return run_dir


# ---------------------------------------------------------------- the real data and models (database)


def collect_db(db, last: date = DEV_WINDOW[1]):
    """(bars of the stocks with volume, the 49, the 128, the mid-cap 14). The lists come from the locked split file and
    the app's mid-cap model; the held-back 129 are never loaded (asserted before any bar is read)."""
    from datetime import timedelta

    from sqlalchemy import select

    import swing_trade_ml.services.risk  # noqa: F401  # load order only: avoids a circular import when run on its own
    from swing_trade_ml.brain.five_day import load_bars_with_volume
    from swing_trade_ml.core.config import REPO_ROOT
    from swing_trade_ml.core.enums import ModelStatus
    from swing_trade_ml.db.models.ml import MLModel

    used, extra, _sha = load_split(REPO_ROOT)
    held_back = load_held_back(REPO_ROOT)
    model = (
        db.execute(
            select(MLModel)
            .where(MLModel.name == MID_MODEL_NAME, MLModel.status == ModelStatus.ACTIVE)
            .order_by(MLModel.trained_at.desc())
        )
        .scalars()
        .first()
    )
    if model is None:
        raise RunRefusedError(f"No active {MID_MODEL_NAME} model: the mid-cap group cannot be built.")
    mid = sl.mid_group_from(model.training_symbols or [], held_back, used)
    symbols = sorted({*used, *extra, *mid})
    sl.assert_no_held_back(held_back, symbols=symbols)
    bars = {
        s: df for s, df in load_bars_with_volume(db, symbols, last + timedelta(days=40)).items() if len(df)
    }
    return bars, used, extra, mid


def model_scores_db(db, used: Sequence[str], extra: Sequence[str], mid: Sequence[str] = ()):
    """Per-fold scoring callback factory. Large: S0 trains the raw 15-day barrier model on the 49; S1 trains the excess
    label on the 49; S2 on the 177. Mid: S0M raw barrier model on the 14 mid stocks, S1M excess label on the 14
    (reference group = the 14), S2M excess label on the 14 plus the 128 extras. All models are registered TRAINED, never
    activated. Only the candidate's own group is scored."""
    from sqlalchemy import select

    from swing_trade_ml.db.models.market import Instrument
    from swing_trade_ml.ml.asof import score_series
    from swing_trade_ml.ml.train import train_model

    def instruments(symbols: Sequence[str]):
        return list(
            db.execute(select(Instrument).where(Instrument.tradingsymbol.in_(list(symbols)))).scalars()
        )

    def factory(candidate: str, bars: dict):
        scored = list(mid) if is_mid(candidate) else list(used)
        insts = instruments(scored)
        base = candidate.rstrip("M")  # S0 / S1 / S2

        def scores(fold: sl.Fold) -> dict[str, dict[date, float]]:
            name = f"sl1_{candidate}_{fold.cutoff:%Y%m%d}"
            if base == "S0":
                model = train_model(
                    db, name=name, symbols=scored, horizon_days=sl.HORIZON_BARS, target_return=0.08,
                    stop_return=0.04, cutoff=fold.cutoff, auto_activate=False,
                )  # fmt: skip
            else:
                train_symbols = sorted({*scored, *extra}) if base == "S2" else scored
                if base == "S2" and not is_mid(candidate):
                    train_symbols = [*used, *extra]
                model = sl.train_lab_model(
                    db,
                    name=name,
                    cutoff=fold.cutoff,
                    symbols=train_symbols,
                    candidates=scored,
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


def start_conditions(candidate: str, repo_root: Path, *, via: str = "run") -> list[str]:
    """Refusal reasons from the shared start checks (empty = allowed). One implementation, in
    `brain/selection_lab_start.py`, which the wrapper also uses; imported here at call time (that module imports
    this one only inside its own `main`, so there is no import cycle). Fail closed: any error is a refusal."""
    import sys

    try:
        from swing_trade_ml.brain import selection_lab_start as start

        return start.guard_for_runner(candidate, runner=sys.modules[__name__], repo_root=repo_root, via=via)
    except Exception as e:  # noqa: BLE001
        return [f"the start conditions could not be verified: {type(e).__name__}: {e}"]


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description=f"{PROTOCOL}: 15-day selection lab, one candidate (ranking only)"
    )
    ap.add_argument("candidate", choices=CANDIDATES)
    ap.add_argument(
        "--technical-rerun",
        action="store_true",
        help="rerun a candidate whose earlier attempt failed technically (needs an incident note; max 2)",
    )
    a = ap.parse_args(argv)
    repo = _repo()
    early = start_conditions(a.candidate, repo, via="cli")  # before any data is read
    if early:
        print(f"{PROTOCOL} {a.candidate} refused: nothing was trained or scored.")
        for r in early:
            print(f"- {r}")
        return 2
    from swing_trade_ml.db.session import SessionLocal

    with SessionLocal() as db:
        bars, used, extra, mid = collect_db(db)
        factory = model_scores_db(db, used, extra, mid)
        try:
            run_dir = run(
                a.candidate, repo_root=repo, collect_fn=lambda: (bars, used, extra), model_scores_fn=factory,
                mid_fn=lambda: mid, technical_rerun=a.technical_rerun,
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
