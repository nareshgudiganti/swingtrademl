# ruff: noqa: E501
"""The one documented way to start the 15-day selection lab (`sl-protocol-v1`).

It runs every start condition, writes one audit line, and only then calls the frozen runner
(`selection_lab_run.main`) with the arguments unchanged. Any check that fails, or cannot be verified, refuses.

This is a guard rail, not a hard lock: someone can still run the frozen runner directly. See
`docs/brain/SELECTION-LAB-START.md`. This file is not part of the sl-protocol-v1 frozen set and never edits it.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
EARLIEST_START = date(2026, 12, 5)  # Amendment 2, item 2: IST calendar date
PHASE_B_LOCK_TAG = "wf-protocol-v2"  # exists only for a verified survivor (never after NO_SURVIVOR)
PHASE_B_CANDIDATES = ("B1", "B2", "B3")
PHASE_B_RESULT_TAG = "phase-b-result"
PHASE_B_RESULT_DIR = "docs/brain/evidence/phase_b"
PHASE_B_RESULT_REL = f"{PHASE_B_RESULT_DIR}/PHASE_B_RESULT.json"
PHASE_B_RESULT_SCHEMA = "phase-b-result-v1"
PHASE_B_OUTCOMES = ("SURVIVOR_SELECTED", "NO_SURVIVOR")
PHASE_B_RESULT_ROW_MARKER = "Phase B result record"  # as written by brain/phase_b_finish.py
PHASE_B_MANIFEST_SCHEMA = "phase-b-candidate-manifest-v1"
PHASE_B_RANK_METHOD = "phase-b-completion-v1"
PHASE_B_NO_WARNING = "NO WARNING (diagnostic)"  # phase_b.NO_WARNING; survives = beats and reject both this
PHASE_B_BEATS_ID, PHASE_B_REJECT_ID = "phase_b_beats_every_stock_and_momentum", "reject_set"
PHASE_B_DEADLINE = datetime(2026, 12, 4, 23, 59, 59, tzinfo=IST)
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


def _tag_exists(git: GitFn, tag: str) -> bool:
    rc, out = git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if rc == 0 and out.strip():
        return True
    if rc == 1:
        return False
    raise CheckError(f"could not look up tag {tag} (exit {rc})")


def _require_annotated_ancestor(git: GitFn, tag: str, reasons: list[str]) -> bool:
    """Tag exists, is annotated (a tag object, not lightweight) and is an ancestor of HEAD."""
    if not _tag_exists(git, tag):
        reasons.append(f"Phase B: git tag {tag} does not exist.")
        return False
    if _git_ok(git, "cat-file", "-t", f"refs/tags/{tag}") != "tag":
        reasons.append(f"Phase B: git tag {tag} is lightweight; it must be annotated.")
        return False
    rc, _ = git("merge-base", "--is-ancestor", f"refs/tags/{tag}", "HEAD")
    if rc == 1:
        reasons.append(f"Phase B: git tag {tag} is not in HEAD's history.")
        return False
    if rc != 0:
        raise CheckError(f"ancestor test for {tag} failed (exit {rc})")
    return True


def _tag_object(git: GitFn, tag: str) -> tuple[dict[str, str], dict[str, str], str]:
    """Return (header fields, message key=value lines, raw message) of an annotated tag."""
    rc, out = git("cat-file", "-p", f"refs/tags/{tag}")
    if rc != 0:
        raise CheckError(f"could not read tag {tag} (exit {rc})")
    head, _, msg = out.replace("\r\n", "\n").partition("\n\n")
    headers = {}
    for line in head.splitlines():
        k, _, v = line.partition(" ")
        headers[k] = v
    kv = {}
    for line in msg.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip()
    return headers, kv, msg


def _tagger_time(headers: dict[str, str]) -> datetime:
    parts = headers.get("tagger", "").split()
    if len(parts) < 2 or not parts[-2].isdigit():
        raise CheckError("tag has no readable tagger date")
    return datetime.fromtimestamp(int(parts[-2]), UTC)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _same_blob_at_tag_and_head(git: GitFn, tag: str, rel: str, reasons: list[str]) -> bool:
    at_tag, at_head = _blob(git, f"refs/tags/{tag}", rel), _blob(git, "HEAD", rel)
    if at_tag is None:
        reasons.append(f"Phase B: {rel} is not in the commit tagged {tag}.")
        return False
    if at_head != at_tag:
        reasons.append(f"Phase B: {rel} at HEAD differs from the version at tag {tag}.")
        return False
    return True


def _check_survival_rule(rec: dict, cands: dict, outcome: str, survivor, reasons: list[str]) -> None:
    """Re-derive 'survives' from the stored check labels (the signed rule), and check the selection block."""
    derived = []
    for cid in PHASE_B_CANDIDATES:
        rows = cands[cid].get("pass_rows")
        if not isinstance(rows, dict):
            reasons.append(f"Phase B: candidate {cid} has no pass_rows to re-derive survival from.")
            continue
        ok = (
            rows.get(PHASE_B_BEATS_ID) == PHASE_B_NO_WARNING
            and rows.get(PHASE_B_REJECT_ID) == PHASE_B_NO_WARNING
        )
        if ok != (cands[cid].get("survives") is True):
            reasons.append(f"Phase B: candidate {cid}: stored survives differs from its stored check labels.")
        if ok:
            derived.append(cid)
    sel = rec.get("selection")
    if not isinstance(sel, dict) or sel.get("method") != PHASE_B_RANK_METHOD:
        reasons.append(f"Phase B: the selection block is missing or not method {PHASE_B_RANK_METHOD}.")
        return
    if sel.get("outcome") != outcome or sel.get("survivor") != survivor:
        reasons.append("Phase B: the selection block disagrees with the record's outcome or survivor.")
    if sel.get("survivors") != derived:
        reasons.append("Phase B: the selection block's survivors differ from those derived from the labels.")
    if outcome == "NO_SURVIVOR" and derived:
        reasons.append("Phase B: NO_SURVIVOR but the stored labels show a survivor.")
    if outcome == "SURVIVOR_SELECTED":
        ranking = sel.get("ranking")
        top = ranking[0] if isinstance(ranking, list) and ranking else None
        if not isinstance(top, dict) or top.get("candidate") != survivor:
            reasons.append("Phase B: the selection ranking does not put the named survivor first.")


def _check_manifests(
    git: GitFn, repo_root: Path, rec: dict, cands: dict, ledger_lines: list[str], reasons: list[str]
) -> None:
    """MANIFEST_Bn.json per candidate (written by phase_b_finish.py): present, unchanged since the tag, hashes
    agree with the record, and each candidate's evidence commit holds its four items and precedes the next."""
    per = (rec.get("evidence_manifest") or {}).get("per_candidate_sha256")
    split = (rec.get("split") or {}).get("sha256")
    commits: dict[str, str] = {}
    for cid in PHASE_B_CANDIDATES:
        c = cands[cid]
        name = f"MANIFEST_{cid}.json"
        rel = f"{PHASE_B_RESULT_DIR}/{name}"
        if c.get("manifest_file") != name:
            reasons.append(f"Phase B: candidate {cid} manifest_file is not {name}.")
            continue
        if not _same_blob_at_tag_and_head(git, PHASE_B_RESULT_TAG, rel, reasons):
            continue
        f = repo_root / rel
        if not f.is_file():
            reasons.append(f"Phase B: {rel} is missing from the working tree.")
            continue
        got = _sha256_file(f)
        if got != c.get("manifest_sha256") or (isinstance(per, dict) and per.get(cid) != got):
            reasons.append(f"Phase B: {rel} sha256 differs from the record.")
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            reasons.append(f"Phase B: {rel} is not valid JSON.")
            continue
        if not isinstance(m, dict) or m.get("schema") != PHASE_B_MANIFEST_SCHEMA or m.get("candidate") != cid:
            reasons.append(f"Phase B: {rel} has the wrong schema or candidate.")
            continue
        if m.get("files") != c.get("result_files"):
            reasons.append(f"Phase B: {rel} file hashes differ from the record's result_files.")
        if m.get("split_sha256") != split:
            reasons.append(f"Phase B: {rel} split hash differs from the record.")
        row = m.get("ledger_row")
        if (
            not isinstance(row, str)
            or row not in ledger_lines
            or hashlib.sha256(row.encode("utf-8")).hexdigest() != m.get("ledger_row_sha256")
        ):
            reasons.append(f"Phase B: {rel} ledger row is not in the ledger or its hash is wrong.")
        ev = c.get("evidence_commit")
        if not isinstance(ev, str) or not re.fullmatch(r"[0-9a-f]{40}", ev):
            reasons.append(f"Phase B: candidate {cid} has no valid evidence_commit.")
            continue
        commits[cid] = ev
        rc, _ = git("merge-base", "--is-ancestor", ev, "HEAD")
        if rc == 1:
            reasons.append(f"Phase B: candidate {cid} evidence commit is not in HEAD's history.")
        elif rc != 0:
            raise CheckError(f"ancestor test for evidence commit of {cid} failed (exit {rc})")
        for item in (*(c.get("result_files") or {}), name):
            if _blob(git, ev, f"{PHASE_B_RESULT_DIR}/{item}") is None:
                reasons.append(f"Phase B: candidate {cid} evidence commit does not contain {item}.")
        if _blob(git, ev, LEDGER) is None:
            reasons.append(f"Phase B: candidate {cid} evidence commit does not contain the ledger.")
    # each candidate committed before the next ran: strict ancestor chain, in ledger-row order
    order = sorted(
        (
            next((i for i, ln in enumerate(ledger_lines) if PHASE_B_LEDGER_MARKER.format(cid=cid) in ln), -1),
            cid,
        )
        for cid in commits
    )
    for (_, a), (_, b) in itertools.pairwise(order):
        if commits[a] == commits[b]:
            reasons.append(
                f"Phase B: {a} and {b} were committed together; each must be committed before the next run."
            )
            continue
        rc, _ = git("merge-base", "--is-ancestor", commits[a], commits[b])
        if rc == 1:
            reasons.append(f"Phase B: the evidence commit of {a} is not before that of {b}.")
        elif rc != 0:
            raise CheckError(f"ancestor test between evidence commits failed (exit {rc})")


def check_phase_b_lock(git: GitFn, repo_root: Path) -> dict:
    """Phase B is finished when its terminal record exists: annotated tag `phase-b-result`, the committed
    PHASE_B_RESULT.json and one ledger row, all agreeing. Both outcomes (SURVIVOR_SELECTED, NO_SURVIVOR) are
    accepted. `wf-protocol-v2` must exist for a survivor and must NOT exist after NO_SURVIVOR."""
    reasons: list[str] = []
    for tag in PHASE_B_TAGS:
        _require_annotated_ancestor(git, tag, reasons)
    if not _require_annotated_ancestor(git, PHASE_B_RESULT_TAG, reasons):
        return _result("phase_b_lock", False, reasons)

    headers, kv, _ = _tag_object(git, PHASE_B_RESULT_TAG)
    if _tagger_time(headers) > PHASE_B_DEADLINE:
        reasons.append(f"Phase B: tag {PHASE_B_RESULT_TAG} was created after 2026-12-04 IST.")
    if not _same_blob_at_tag_and_head(git, PHASE_B_RESULT_TAG, PHASE_B_RESULT_REL, reasons):
        return _result("phase_b_lock", False, reasons)
    path = repo_root / PHASE_B_RESULT_REL
    if not path.is_file():
        reasons.append(f"Phase B: {PHASE_B_RESULT_REL} is missing from the working tree.")
        return _result("phase_b_lock", False, reasons)
    digest = _sha256_file(path)
    if kv.get("result_sha256") != digest:
        reasons.append(f"Phase B: sha256 of {PHASE_B_RESULT_REL} does not match the tag message.")
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        reasons.append(f"Phase B: {PHASE_B_RESULT_REL} is not valid JSON ({e}).")
        return _result("phase_b_lock", False, reasons)
    if not isinstance(rec, dict) or rec.get("schema") != PHASE_B_RESULT_SCHEMA:
        reasons.append(f"Phase B: {PHASE_B_RESULT_REL} does not have schema {PHASE_B_RESULT_SCHEMA}.")
        return _result("phase_b_lock", False, reasons)

    outcome, survivor = rec.get("outcome"), rec.get("survivor")
    if outcome not in PHASE_B_OUTCOMES:
        reasons.append(f"Phase B: outcome {outcome!r} is not one of {', '.join(PHASE_B_OUTCOMES)}.")
        return _result("phase_b_lock", False, reasons)
    if kv.get("outcome") != outcome:
        reasons.append("Phase B: the outcome in the tag message differs from the record.")
    if kv.get("survivor") != (survivor if survivor else "none"):
        reasons.append("Phase B: the survivor in the tag message differs from the record.")
    if kv.get("ledger_row") != PHASE_B_RESULT_ROW_MARKER:
        reasons.append("Phase B: the tag message has no ledger_row line naming the result row.")
    try:
        written = datetime.fromisoformat(str(rec.get("written_at_ist")))
        if written.tzinfo is None or written > PHASE_B_DEADLINE:
            raise ValueError("naive or after deadline")
    except ValueError:
        reasons.append("Phase B: written_at_ist is missing, has no timezone, or is after 2026-12-04 IST.")

    cands = rec.get("candidates")
    if not isinstance(cands, dict) or any(not isinstance(cands.get(c), dict) for c in PHASE_B_CANDIDATES):
        reasons.append("Phase B: the record does not contain all of B1, B2, B3.")
        return _result("phase_b_lock", False, reasons)
    survivors = [c for c in PHASE_B_CANDIDATES if cands[c].get("survives") is True]
    if outcome == "NO_SURVIVOR" and (survivor is not None or survivors):
        reasons.append("Phase B: NO_SURVIVOR but the record names or marks a surviving candidate.")
    if outcome == "SURVIVOR_SELECTED" and (survivor not in PHASE_B_CANDIDATES or survivor not in survivors):
        reasons.append("Phase B: SURVIVOR_SELECTED but the named survivor is missing or did not survive.")
    for cid in PHASE_B_CANDIDATES:
        files = cands[cid].get("result_files")
        if not isinstance(files, dict) or not files:
            reasons.append(f"Phase B: no result files recorded for candidate {cid}.")
            continue
        for name, want in files.items():
            rel = f"{PHASE_B_RESULT_DIR}/{name}"
            if "/" in name or "\\" in name or ".." in name:
                reasons.append(f"Phase B: unsafe result file name {name!r}.")
            elif _same_blob_at_tag_and_head(git, PHASE_B_RESULT_TAG, rel, reasons):
                f = repo_root / rel
                if not f.is_file() or _sha256_file(f) != want:
                    reasons.append(f"Phase B: {rel} is missing or its sha256 differs from the record.")

    rc, ledger = git("show", f"refs/tags/{PHASE_B_RESULT_TAG}^{{commit}}:{LEDGER}")
    if rc != 0:
        raise CheckError(f"could not read {LEDGER} at tag {PHASE_B_RESULT_TAG} (exit {rc})")
    lines = ledger.splitlines()
    _check_survival_rule(rec, cands, outcome, survivor, reasons)
    _check_manifests(git, repo_root, rec, cands, lines, reasons)
    for cid in PHASE_B_CANDIDATES:
        n = sum(PHASE_B_LEDGER_MARKER.format(cid=cid) in ln for ln in lines)
        if n != 1:
            reasons.append(f"Phase B: {LEDGER} has {n} rows for candidate {cid} (exactly 1 required).")
    result_rows = [ln for ln in lines if PHASE_B_RESULT_ROW_MARKER in ln]
    if len(result_rows) != 1 or digest not in result_rows[0]:
        reasons.append(
            f"Phase B: the ledger needs exactly one '{PHASE_B_RESULT_ROW_MARKER}' row holding the record's sha256."
        )

    wf_exists = _tag_exists(git, PHASE_B_LOCK_TAG)
    if outcome == "NO_SURVIVOR" and wf_exists:
        reasons.append(f"Phase B: NO_SURVIVOR but tag {PHASE_B_LOCK_TAG} exists: inconsistent, refused.")
    if outcome == "SURVIVOR_SELECTED" and _require_annotated_ancestor(git, PHASE_B_LOCK_TAG, reasons):
        _, wkv, _ = _tag_object(git, PHASE_B_LOCK_TAG)
        if survivor and wkv.get("survivor") != survivor:
            reasons.append(f"Phase B: tag {PHASE_B_LOCK_TAG} does not name survivor {survivor}.")
        if wkv.get("result_tag") != PHASE_B_RESULT_TAG:
            reasons.append(f"Phase B: tag {PHASE_B_LOCK_TAG} does not name result_tag={PHASE_B_RESULT_TAG}.")
    notes: list[str] = []
    if outcome == "NO_SURVIVOR" and not reasons:
        notes.append(
            "Phase B ended with NO_SURVIVOR: this lab run is independent experimental research only. "
            "No Phase B candidate is promoted, approved or enabled by it."
        )
    return _result("phase_b_lock", not reasons, reasons, notes)


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
