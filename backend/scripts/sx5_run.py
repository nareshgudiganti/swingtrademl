"""SX5 development-run driver: the "thin signed caller" of protocol section 11. RESEARCH ONLY.

    PYTHONPATH=src python scripts/sx5_run.py                 # DRY RUN (the default): prints the plan and every check
    PYTHONPATH=src python scripts/sx5_run.py --with-data     # DRY RUN that also reads the data (SELECT only) to count rows
    PYTHONPATH=src python scripts/sx5_run.py --run --approval A.json --authorisation T.json   # the real development run

What it does, and only this: assembles the SX5 matrix (47 stocks, read-only), runs the three arms A_53, C_56, R_37 over
the 34 DEVELOPMENT folds with the existing, unchanged harness (`sector_walkforward.run_walkforward`) and recipe
(`sx_recipe`), then calls the mechanical verdict (`sx_verdict.compute_verdict`) exactly ONCE with development records
only, and writes the verdict write-once beside the records.

What it never does: touch the holdout (it passes no holdout fold, never opens a holdout record, never writes the
holdout registry; a PENDING_HOLDOUT outcome ends here and the owner's separate holdout steps are not performed by this
script), train or replace a production model, write to the database or to any production path (records go only under
backend/data/research_models/, gitignored), edit signed text, or commit / tag / sign anything.

A real run is REFUSED unless ALL of these hold (each is printed with PASS / FAIL on every dry run):
  1. today (India time) is 2026-12-04 or later;
  2. an approval file (the harness's own) names SX5 and the complete config_sha256, and carries `code_commit`;
  3. a SEPARATE training-authorisation file (schema sx5-training-authorisation-v1) names the candidate, says
     scope=development_only and training_authorised=true, is dated 2026-12-04..today, never authorises the holdout,
     and binds the hashes below;
  4. the working tree is clean (nothing modified, nothing untracked);
  5. `git rev-parse HEAD` (full 40-hex) equals `code_commit` in BOTH files; it is also the records' code_version;
  6. the recomputed protocol-file, DatasetSpec config, verdict-parameter, verdict-code, recipe and lock-file hashes all
     equal the authorisation's; after the data load and BEFORE any fit, the row-list hash and the matrix hash too;
  7. the holdout registry verifies and shows no consumed event.
It is written by the assistant for the owner; nothing here is a signature or a training approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from swing_trade_ml.brain import service as _brain_service  # noqa: F401  (import order: avoids a repo circular import)
from swing_trade_ml.ml import holdout_registry as hr
from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml import sector_research as sr
from swing_trade_ml.ml import sector_walkforward as wf
from swing_trade_ml.ml import sx_recipe
from swing_trade_ml.ml import sx_verdict as v
from swing_trade_ml.ml.sector_reconcile import keys_sha256

RUN_VERSION = "sx5_run_v1"
CANDIDATE = "SX5"
REPO = Path(__file__).resolve().parents[2]
EVID_REL = "docs/brain/evidence/sector_prep"
STOCK_SPLIT_REL = "docs/brain/evidence/stock_split/stock_split_ev15.json"
PROTOCOL_REL = "docs/superpowers/specs/sx5-research-protocol-FINAL-DRAFT-for-review.md"
LOCK_REL = "backend/requirements-research.lock"
EARLIEST_REAL_DATE = date(2026, 12, 4)
CUTOFF = date(2026, 12, 31)  # the DatasetSpec data_cutoff the signed config hash was computed with
AUTH_SCHEMA = "sx5-training-authorisation-v1"
DEFAULT_MDE_H = (
    0.0018  # PROPOSED default (owner decision 1); a real run takes the SIGNED value from the authorisation
)
OPEN_STATES = ("AUTHORISED", "RECOVERY_AUTHORISED")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REPORT_HEADER = (
    "Cohort: 47 large stocks, today's list applied to the past (2022-09 to 2026-08). Survivors only: delisted, merged "
    "and dropped names are missing. Results apply to this cohort only. Not evidence about other stocks, other sizes "
    "of company, or the future market."
)
BOUND_KEYS = (
    "protocol_sha256",
    "config_sha256",
    "verdict_params_sha256",
    "verdict_code_sha256",
    "recipe_sha256",
    "lock_file_sha256",
    "rowlist_sha256",  # after the data load, before any fit
    "dataset_sha256",  # after the data load, before any fit (depends on the pandas build)
)
LOAD_TIME_KEYS = ("rowlist_sha256", "dataset_sha256")


class RunRefused(RuntimeError):
    """A start condition does not hold: nothing was trained, nothing was written."""


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


# ----------------------------------------------------------------------------------------------- small helpers
def ist_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def sha256_lf(path: Path) -> str:
    """sha256 of a TEXT file with CRLF turned into LF (same convention as scripts/final_hash_sheet.py)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_state(repo: Path) -> tuple[str, str]:
    """(HEAD full sha, `git status --porcelain --untracked-files=all` text)."""

    def run(*a: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout

    return run("rev-parse", "HEAD").strip(), run("status", "--porcelain", "--untracked-files=all")


def symbols_47(repo: Path) -> list[str]:
    used = json.loads((repo / STOCK_SPLIT_REL).read_text("utf-8"))["used_49"]
    return [s for s in used if sf.resolve_sector_index(s) is not None]


def build_spec(repo: Path = REPO) -> sr.DatasetSpec:
    kind, target, stop = sr.PROTOCOL_LABELS[CANDIDATE]
    return sr.DatasetSpec(
        candidate=CANDIDATE,
        symbols=tuple(symbols_47(repo)),
        horizon_days=sr.CANDIDATE_HORIZON[CANDIDATE],
        target_return=target,
        stop_return=stop,
        label_kind=kind,
        data_cutoff=CUTOFF,
        exclusions=sr.load_exclusions_csv(repo / EVID_REL / "excluded_rows_h5_v2.csv"),
    )


def build_params(mde_h: float) -> v.VerdictParams:
    """The signed verdict parameter set: every default of VerdictParams, only MDE_H supplied (a FRACTION)."""
    return v.VerdictParams(horizon=5, mde_h=mde_h)


def bound_values(repo: Path, spec: sr.DatasetSpec, params: v.VerdictParams, protocol: Path) -> dict:
    """Every hash the authorisation must repeat that can be recomputed WITHOUT the data."""
    return {
        "protocol_sha256": sha256_lf(protocol),
        "config_sha256": spec.config_sha256(),
        "verdict_params_sha256": params.sha256(),
        "verdict_code_sha256": v.verdict_code_sha256(),
        "recipe_sha256": sx_recipe.SXRecipe().sha256(),
        "lock_file_sha256": sha256_lf(repo / LOCK_REL),
    }


def matrix_keys(matrix) -> list[str]:
    return [
        f"{s}|{pd_day:%Y-%m-%d}" for s, pd_day in zip(matrix["symbol"], matrix["decision_date"], strict=True)
    ]


def load_time_values(matrix) -> dict:
    return {
        "rowlist_sha256": keys_sha256(sorted(matrix_keys(matrix))),
        "dataset_sha256": sr.matrix_sha256(matrix),
    }


# ----------------------------------------------------------------------------------------------------- the checks
@dataclass
class Context:
    repo: Path = REPO
    today: date | None = None
    approval_path: Path | None = None
    authorisation_path: Path | None = None
    protocol_path: Path | None = None
    registry_path: Path | None = None
    lock_path: Path | None = None
    git: Callable[[Path], tuple[str, str]] = git_state

    def day(self) -> date:
        return self.today or ist_today()

    def protocol(self) -> Path:
        return Path(self.protocol_path) if self.protocol_path else self.repo / PROTOCOL_REL


def _auth_problems(auth: dict, today: date) -> list[str]:
    bad = []
    if auth.get("schema") != AUTH_SCHEMA:
        bad.append(f"schema must be {AUTH_SCHEMA!r}")
    if auth.get("candidate") != CANDIDATE:
        bad.append(f"candidate must be {CANDIDATE!r}")
    if auth.get("scope") != "development_only":
        bad.append("scope must be 'development_only' (this script never runs the holdout)")
    if auth.get("training_authorised") is not True:
        bad.append("training_authorised must be true")
    if auth.get("holdout_authorised"):
        bad.append("holdout_authorised must be absent or false: this script cannot run the holdout")
    for k in ("protocol_id", "authorised_by", "statement"):
        if not isinstance(auth.get(k), str) or not auth[k].strip():
            bad.append(f"{k} must be a non-empty text")
    try:
        d = date.fromisoformat(str(auth.get("authorised_on")))
        if d < EARLIEST_REAL_DATE:
            bad.append(f"authorised_on {d} is before {EARLIEST_REAL_DATE}")
        if d > today:
            bad.append(f"authorised_on {d} is in the future")
    except ValueError:
        bad.append("authorised_on must be a date YYYY-MM-DD (India time)")
    if not HEX40.match(str(auth.get("code_commit", ""))):
        bad.append("code_commit must be a full 40-hex commit")
    for k in BOUND_KEYS:
        if not HEX64.match(str(auth.get(k, ""))):
            bad.append(f"{k} must be a full 64-hex sha256")
    m = auth.get("mde_h")
    if isinstance(m, bool) or not isinstance(m, (int, float)):
        bad.append("mde_h must be a number (a FRACTION of one holding return, e.g. 0.0018)")
    return bad


def preflight(ctx: Context) -> tuple[list[Check], dict]:
    """Every start condition. Never raises. Returns the checks and the hash values this tree would need."""
    out: list[Check] = []

    def add(name: str, ok: bool, detail: str) -> None:
        out.append(Check(name, bool(ok), detail))

    today = ctx.day()
    add(
        "date",
        today >= EARLIEST_REAL_DATE,
        f"today (India time) is {today}; a real run is allowed from {EARLIEST_REAL_DATE}",
    )
    spec = build_spec(ctx.repo)
    approval, auth = None, None
    if ctx.approval_path and Path(ctx.approval_path).is_file():
        try:
            approval = read_json(ctx.approval_path)
        except (OSError, ValueError):
            approval = None
    ok, why = sr._approval_valid(spec, ctx.approval_path)
    add("approval file", ok, why)
    if ctx.authorisation_path and Path(ctx.authorisation_path).is_file():
        try:
            auth = read_json(ctx.authorisation_path)
        except (OSError, ValueError):
            auth = None
    problems = (
        ["no authorisation file given or it is not valid JSON"]
        if auth is None
        else _auth_problems(auth, today)
    )
    add("separate training authorisation", not problems, "; ".join(problems) or "present and well formed")
    if approval is None or auth is None:
        add("protocol id", False, "needs both the approval file and the authorisation file")
    elif approval.get("protocol_id") != auth.get("protocol_id"):
        add("protocol id", False, "approval and authorisation name different protocol ids")
    else:
        add("protocol id", True, "same protocol id in both files")

    try:
        head, porcelain = ctx.git(ctx.repo)
    except Exception as exc:  # noqa: BLE001
        head, porcelain = "", f"git failed: {exc}"
    add(
        "clean tree",
        porcelain.strip() == "",
        "nothing modified or untracked" if not porcelain.strip() else porcelain.strip()[:300],
    )
    commits = {
        "HEAD": head,
        "approval.code_commit": (approval or {}).get("code_commit"),
        "authorisation.code_commit": (auth or {}).get("code_commit"),
    }
    add(
        "commit",
        bool(HEX40.match(head)) and len(set(commits.values())) == 1,
        "HEAD, approval and authorisation name the same full commit"
        if len(set(commits.values())) == 1 and HEX40.match(head)
        else f"differ or missing: {commits}",
    )

    mde = (auth or {}).get("mde_h", DEFAULT_MDE_H)
    try:
        params = build_params(mde)
        params_note = "verdict parameters accepted"
    except v.VerdictRefused as exc:
        params, params_note = None, f"MDE_H refused: {exc}"
    add("MDE_H (fraction)", params is not None, params_note)
    params = params or build_params(DEFAULT_MDE_H)

    try:
        have = bound_values(ctx.repo, spec, params, ctx.protocol())
    except OSError as exc:
        have = {}
        add("hashes", False, f"cannot compute: {exc}")
    if have:
        if auth is None:
            add("hashes", False, "no authorisation to compare against")
        else:
            diff = [k for k, val in have.items() if auth.get(k) != val]
            add(
                "hashes",
                not diff,
                "all recomputed hashes equal the authorisation" if not diff else f"differ: {diff}",
            )
    try:
        # READ-ONLY: `hr.verify` would create the lock file, so the dry run uses the same loader without the lock.
        entries = hr._load(Path(ctx.registry_path or hr.REGISTRY_PATH), Path(ctx.lock_path or hr.LOCK_PATH))
        states = {k: e["state"] for k, e in hr._replay(entries).items()}
        used = {k: s for k, s in states.items() if s not in OPEN_STATES}
        add(
            "holdout registry",
            not used,
            f"verifies; events: {states}" if not used else f"consumed events: {used}",
        )
    except Exception as exc:  # noqa: BLE001
        add("holdout registry", False, f"does not verify: {exc}")
    return out, {**have, **dict.fromkeys(LOAD_TIME_KEYS, "(computed after the data load)")}


def format_checks(checks: Sequence[Check]) -> str:
    return "\n".join(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}" for c in checks)


# -------------------------------------------------------------------------------------------------------- the plan
def plan(ctx: Context, *, data: dict | None = None) -> dict:
    """The DRY RUN. Reads no market data (unless `data` was loaded by --with-data), fits and writes nothing."""
    spec = build_spec(ctx.repo)
    folds = wf.default_folds(include_holdout=False)
    arms = wf.build_arms()
    checks, required = preflight(ctx)
    params = build_params(DEFAULT_MDE_H)
    return {
        "driver": RUN_VERSION,
        "candidate": CANDIDATE,
        "mode": "DRY RUN (nothing fitted, nothing written)",
        "stocks": len(spec.symbols),
        "label": f"{spec.label_kind}, +{spec.target_return:.0%} in {spec.horizon_days} sessions",
        "development_folds": len(folds),
        "first_fold": folds[0].test_start.isoformat(),
        "last_fold": folds[-1].test_end.isoformat(),
        "holdout": "never touched by this script",
        "arms": {a: len(c) for a, c in arms.items()},
        "seed": wf.PINNED_SEED,
        "embargo_sessions": spec.horizon_days,
        "records_would_be": f"{len(folds)} folds x {len(arms)} arms = {len(folds) * len(arms)} JSON files",
        "would_write_under": str(sr.RESEARCH_ROOT / "walkforward" / CANDIDATE),
        "verdict_params_default_shown": json.loads(params.canonical_json()),
        "data": data or "not read (use --with-data for a read-only row count)",
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        "real_run_allowed_now": all(c.ok for c in checks),
        "authorisation_must_repeat": required,
    }


# ------------------------------------------------------------------------------------------------------ real run
def _write_once(path: Path, text: str) -> None:
    """Exclusive create (never overwrites), LF line endings, then read-only."""
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")
    path.chmod(stat.S_IREAD)


def run_real(
    ctx: Context,
    *,
    load_inputs: Callable[[Sequence[str]], sr.ResearchInputs] | None = None,
    fit_builder: Callable[..., Callable] | None = None,
    out_root: Path | None = None,
) -> dict:
    checks, _ = preflight(ctx)
    failed = [c for c in checks if not c.ok]
    if failed:
        raise RunRefused("a real run is refused:\n" + format_checks(failed))
    auth = read_json(ctx.authorisation_path)
    head, _ = ctx.git(ctx.repo)
    spec = build_spec(ctx.repo)
    params = build_params(auth["mde_h"])

    inputs = (load_inputs or sr.load_inputs_readonly)(spec.symbols)  # SELECT only
    matrix = sr.assemble_training_matrix(spec, inputs)
    seen = load_time_values(matrix)
    wrong = [k for k in LOAD_TIME_KEYS if auth[k] != seen[k]]
    if wrong:  # BEFORE any fit
        raise RunRefused(f"the assembled data differs from the authorisation in {wrong}; nothing was fitted")

    recipe = sx_recipe.SXRecipe()
    fit_fn = (fit_builder or sx_recipe.build_fit_fn)(
        recipe, spec=spec, approval_path=ctx.approval_path, allow_real_data=True
    )
    folds = wf.default_folds(include_holdout=False)
    if any(f.kind != "dev" for f in folds) or len(folds) != params.last_fold_index + 1:
        raise RunRefused("the development folds are not the 34 signed ones; nothing was fitted")
    result = wf.run_walkforward(
        spec,
        matrix,
        fit_fn=fit_fn,
        code_version=head,
        folds=folds,
        include_holdout=False,
        out_root=out_root,
        approval_path=ctx.approval_path,
        seed=wf.PINNED_SEED,
    )
    if {r["fold"]["kind"] for r in result.records} != {"dev"}:
        raise RunRefused("a non-development record exists; the verdict was not computed")

    verdict = v.compute_verdict(result.records, params)  # ONE call, development records only
    run_dir = Path(result.run_dir)
    code_sha = v.verdict_code_sha256()
    _write_once(run_dir / "VERDICT_dev.json", v.render_json(verdict, code_sha))
    _write_once(
        run_dir / "VERDICT_dev.txt",
        f"{REPORT_HEADER}\n\n{v.render_plain_english(verdict)}\n\nOutcome word: {verdict['outcome']}\n",
    )
    _write_once(
        run_dir / "RUN_CONTEXT.json",
        json.dumps(
            {
                "driver": RUN_VERSION,
                "run_id": result.run_id,
                "code_commit": head,
                "authorisation_sha256": sha256_lf(ctx.authorisation_path),
                "approval_sha256": sha256_lf(ctx.approval_path),
                "verdict_code_sha256": code_sha,
                "verdict_params_sha256": params.sha256(),
                "outcome": verdict["outcome"],
                "holdout": "not touched; a PENDING_HOLDOUT outcome ends this script",
            },
            indent=1,
            sort_keys=True,
        ),
    )
    return {
        "run_dir": str(run_dir),
        "run_id": result.run_id,
        "outcome": verdict["outcome"],
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------------------------------------- CLI
def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true", help="the real development run (default: dry run)")
    ap.add_argument(
        "--with-data", action="store_true", help="dry run only: read the data (SELECT) and count rows"
    )
    ap.add_argument(
        "--approval", default=None, help="the harness approval file (or env SECTOR_RESEARCH_APPROVAL_FILE)"
    )
    ap.add_argument("--authorisation", default=None, help="the separate sx5 training authorisation file")
    ap.add_argument(
        "--protocol", default=None, help="the signed protocol file (default: the FINAL-DRAFT path)"
    )
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--registry", default=None)
    a = ap.parse_args(argv)
    import os

    approval = a.approval or os.environ.get(sr.APPROVAL_ENV)
    ctx = Context(
        repo=Path(a.repo),
        approval_path=Path(approval) if approval else None,
        authorisation_path=Path(a.authorisation) if a.authorisation else None,
        protocol_path=Path(a.protocol) if a.protocol else None,
        registry_path=Path(a.registry) if a.registry else None,
    )
    if a.run:
        try:
            res = run_real(ctx)
        except (RunRefused, sr.ResearchApprovalRequired, wf.HarnessRefused, v.VerdictRefused) as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
        print(f"Run {res['run_id']} written under {res['run_dir']}. Outcome word: {res['outcome']}")
        return 0
    data = None
    if a.with_data:
        spec = build_spec(ctx.repo)
        matrix = sr.assemble_training_matrix(spec, sr.load_inputs_readonly(spec.symbols))
        data = {"rows": len(matrix), **load_time_values(matrix)}
    p = plan(ctx, data=data)
    print(json.dumps(p, indent=1, sort_keys=True))
    print("\nChecks:\n" + format_checks([Check(c["name"], c["ok"], c["detail"]) for c in p["checks"]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
