# ruff: noqa: E501
"""The one documented way to start the 15-day selection lab (`sl-protocol-v1`).

It runs every start condition, writes one audit line, and only then calls the frozen runner
(`selection_lab_run.main`) with the arguments unchanged. Any check that fails, or cannot be verified, refuses.

This is a guard rail, not a hard lock: someone can still run the frozen runner directly. See
`docs/brain/SELECTION-LAB-START.md`. This file is not part of the sl-protocol-v1 frozen set and never edits it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
EARLIEST_START = date(2026, 12, 5)  # Amendment 2, item 2: IST calendar date
PHASE_B_LOCK_TAG = "wf-protocol-v2"  # evidence plan section 3: the single survivor is locked under this tag
PHASE_B_CANDIDATES = ("B1", "B2", "B3")
# Copied from brain/phase_b.py on purpose: importing phase_b first hits an existing circular import
# (horizon_grid <-> trial_journal), which would make the wrapper refuse forever. A test keeps the copies equal.
PHASE_B_TAGS = ("evidence-defs-v1", "evidence-defs-v2", "phase-b-settings")
PHASE_B_LEDGER_MARKER = "Phase B candidate {cid}"
LEDGER = "docs/brain/EXPOSURE-LEDGER.md"
AUDIT_REL = "backend/data/lab_start_audit.jsonl"

GitFn = Callable[..., tuple[int, str]]  # git(*args) -> (return code, stdout)


class CheckError(RuntimeError):
    """A check could not be verified."""


def _repo() -> Path:
    from swing_trade_ml.core.config import REPO_ROOT

    return REPO_ROOT


def make_git(repo_root: Path) -> GitFn:
    def git(*args: str) -> tuple[int, str]:
        p = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False)
        return p.returncode, p.stdout

    return git


def _git_ok(git: GitFn, *args: str) -> str:
    rc, out = git(*args)
    if rc != 0:
        raise CheckError(f"git {' '.join(args)} failed (exit {rc})")
    return out.strip()


def _result(name: str, ok: bool, reasons: list[str], warnings: list[str] | None = None) -> dict:
    return {"check": name, "ok": ok, "reasons": reasons, "warnings": warnings or []}


def _guarded(name: str, fn: Callable[[], dict]) -> dict:
    """Fail closed: an exception is a refusal."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return _result(name, False, [f"{name} could not be verified: {type(e).__name__}: {e}"])


# ------------------------------------------------------------------ checks


def check_date(now: datetime) -> dict:
    if now.tzinfo is None:
        raise CheckError("the clock is not timezone-aware")
    today = now.astimezone(IST).date()
    if today < EARLIEST_START:
        return _result(
            "date", False, [f"Too early: today is {today} (IST); the lab may start from {EARLIEST_START}."]
        )
    return _result("date", True, [])


def check_phase_b_lock(git: GitFn, repo_root: Path) -> dict:
    """Phase B writes no 'finished' marker. Closest real artifacts: the tag `wf-protocol-v2` (the locked single
    survivor, plan section 3, due 2026-12-04), the Phase B tags, and the three Phase B exposure-ledger rows."""
    reasons: list[str] = []
    for tag in (*PHASE_B_TAGS, PHASE_B_LOCK_TAG):
        rc, _ = git("merge-base", "--is-ancestor", f"refs/tags/{tag}", "HEAD")
        if rc == 1:
            reasons.append(f"Phase B: git tag {tag} is missing or not in HEAD's history.")
        elif rc != 0:
            reasons.append(f"Phase B: git tag {tag} could not be verified (exit {rc}); treated as missing.")
    text = (repo_root / LEDGER).read_text(encoding="utf-8")
    for cid in PHASE_B_CANDIDATES:
        if PHASE_B_LEDGER_MARKER.format(cid=cid) not in text:
            reasons.append(
                f"Phase B: no exposure-ledger row for candidate {cid} in {LEDGER}: Phase B has not finished."
            )
    return _result("phase_b_lock", not reasons, reasons)


def check_protocol_tag(git: GitFn, tag: str) -> dict:
    rc, out = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if rc != 0 or not out.strip():
        return _result("protocol_tag", False, [f"The git tag {tag} does not exist."])
    rc, _ = git("merge-base", "--is-ancestor", f"refs/tags/{tag}", "HEAD")
    if rc == 1:
        return _result("protocol_tag", False, [f"The git tag {tag} is not an ancestor of HEAD."])
    if rc != 0:
        raise CheckError(f"ancestor test for {tag} failed (exit {rc})")
    return _result("protocol_tag", True, [])


def check_clean_tree(git: GitFn) -> dict:
    out = _git_ok(git, "status", "--porcelain", "--untracked-files=all")
    if out:
        n = len(out.splitlines())
        return _result("clean_tree", False, [f"The working tree has {n} uncommitted or untracked change(s)."])
    return _result("clean_tree", True, [])


def _blob(git: GitFn, rev: str, path: str) -> str | None:
    out = _git_ok(git, "ls-tree", rev, "--", path)
    if not out:
        return None
    return out.split("\t")[0].split()[2]


def check_frozen_files(git: GitFn, tag: str, files: Sequence[str]) -> dict:
    reasons: list[str] = []
    warnings: list[str] = []
    for path in files:
        at_head, at_tag = _blob(git, "HEAD", path), _blob(git, f"refs/tags/{tag}", path)
        if at_head is None and at_tag is None:
            warnings.append(
                f"{path} is absent at both the tag and HEAD (consistent, but the file is missing)."
            )
        elif at_head is None or at_tag is None:
            where = "HEAD" if at_head is None else "the tag"
            reasons.append(f"{path} is absent at {where} but present at the other: frozen file changed.")
        elif at_head != at_tag:
            reasons.append(f"{path} at HEAD differs from the tagged version.")
    return _result("frozen_files", not reasons, reasons, warnings)


def check_runner_guard(runner: Any, repo_root: Path, candidate: str | None) -> dict:
    """The frozen runner's own helpers, called not copied. Cross-check only; the runner repeats them itself."""
    tag_on_head, changed, dirty = runner.git_state(repo_root)
    signed = runner.amendment_signed(repo_root)
    reasons = runner.refusal_reasons(
        candidate=candidate or "",
        tag_on_head=tag_on_head,
        changed_since_tag=changed,
        dirty=dirty,
        amendment=signed,
        unclassified=[],  # the runner checks gaps, prior runs and comparisons itself, with the database
        already_ran=[],
        comparison_missing=None,
    )
    return _result("runner_guard", not reasons, list(reasons))


# ------------------------------------------------------------------ audit


def _audit_path(repo_root: Path, git: GitFn) -> Path:
    path = (repo_root / AUDIT_REL).resolve()
    base = (repo_root / "backend" / "data").resolve()
    if base not in path.parents:
        raise CheckError("audit path escapes backend/data")
    rc, _ = git("check-ignore", "-q", AUDIT_REL)
    if rc != 0:
        raise CheckError(f"{AUDIT_REL} is not git-ignored (check-ignore exit {rc}); it would dirty the tree")
    return path


def write_audit(path: Path, record: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        f.flush()


def _stamp(now: datetime) -> dict:
    return {"utc": now.astimezone(UTC).isoformat(), "ist": now.astimezone(IST).isoformat()}


# ------------------------------------------------------------------ main


def evaluate(
    runner: Any, git: GitFn, repo_root: Path, now_fn: Callable[[], datetime], candidate: str | None
) -> list[dict]:
    tag = runner.TAG
    return [
        _guarded("date", lambda: check_date(now_fn())),
        _guarded("phase_b_lock", lambda: check_phase_b_lock(git, repo_root)),
        _guarded("protocol_tag", lambda: check_protocol_tag(git, tag)),
        _guarded("clean_tree", lambda: check_clean_tree(git)),
        _guarded("frozen_files", lambda: check_frozen_files(git, tag, runner.FROZEN_FILES)),
        _guarded("runner_guard", lambda: check_runner_guard(runner, repo_root, candidate)),
    ]


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Any = None,
    git: GitFn | None = None,
    repo_root: Path | None = None,
    now_fn: Callable[[], datetime] | None = None,  # tests only; there is no environment override
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check-only" in args
    passthrough = [a for a in args if a != "--check-only"]
    candidate = next((a for a in passthrough if not a.startswith("-")), None)

    if runner is None:
        from swing_trade_ml.brain import selection_lab_run as runner
    repo_root = repo_root or _repo()
    git = git or make_git(repo_root)
    now_fn = now_fn or (lambda: datetime.now(UTC))

    try:
        now = now_fn()
        now.astimezone(IST)
    except Exception:  # noqa: BLE001
        now = datetime.now(UTC)  # only for the timestamp; the date check itself will refuse
    results = evaluate(runner, git, repo_root, now_fn, candidate)
    reasons = [r for res in results for r in res["reasons"]]
    allowed = all(res["ok"] for res in results)
    if check_only:
        decision = "would_permit" if allowed else "refused"
    else:
        decision = "permitted" if allowed else "refused"

    try:
        head = _git_ok(git, "rev-parse", "HEAD")
    except Exception as e:  # noqa: BLE001
        head = f"unknown ({e})"
    try:
        tag_commit = _git_ok(git, "rev-parse", "--verify", "--quiet", f"refs/tags/{runner.TAG}^{{commit}}")
    except Exception:  # noqa: BLE001
        tag_commit = None
    record = {
        **_stamp(now),
        "event": "start_attempt",
        "candidate": candidate,
        "args": passthrough,
        "check_only": check_only,
        "git_head": head,
        "tag": runner.TAG,
        "tag_commit": tag_commit,
        "checks": results,
        "decision": decision,
    }
    try:
        audit = _audit_path(repo_root, git)
        write_audit(audit, record)
    except Exception as e:  # noqa: BLE001
        print(
            f"REFUSED: the audit log could not be written ({type(e).__name__}: {e}). The lab was not started."
        )
        return 2

    for res in results:
        for w in res["warnings"]:
            print(f"warning [{res['check']}]: {w}")
    if not allowed:
        print("REFUSED. The lab was not started:")
        for r in reasons:
            print(f"  - {r}")
        return 2
    if check_only:
        print("All checks passed (check-only: the runner was not called).")
        return 0

    code = runner.main(passthrough)
    code = 0 if code is None else int(code)
    done = {
        **_stamp(datetime.now(UTC)),
        "event": "runner_finished",
        "candidate": candidate,
        "exit_code": code,
    }
    try:
        write_audit(audit, done)
    except Exception as e:  # noqa: BLE001
        print(f"warning: the runner finished (exit {code}) but the audit log could not record it: {e}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
