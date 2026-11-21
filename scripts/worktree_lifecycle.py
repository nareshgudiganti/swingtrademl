#!/usr/bin/env python3
"""Git worktree and branch lifecycle: audit (dry run) and safe cleanup after PR merges (#407).

Usage (run from anywhere inside the repo):
    python scripts/worktree_lifecycle.py audit [--out DIR]          # read-only report (Markdown + JSON)
    python scripts/worktree_lifecycle.py cleanup [--pr N] [--apply]  # dry run unless --apply

Classes (one per worktree, first match wins):
    unknown         path missing, prunable, or git could not read it
    uncommitted     modified or untracked files (ignored files do not count)
    unpushed        commits that exist on no remote and are not in a merged PR
    merged-clean    clean, and its tip is in origin/main or equals the head of a merged PR
    active          not merged: a live Claude session is in it, it changed recently, or it has an open PR
    abandoned       not merged, clean, every commit is on a remote, no open PR, inactive for a while
    unknown         anything else

Cleanup removes a worktree ONLY when, re-checked just before acting: class is merged-clean, it is not
locked, not protected (scripts/worktree-protect.txt), not the main checkout, and no live session is in it.
A branch is deleted only when no worktree uses it any more and its tip is in origin/main or equals the
merged PR head. `git worktree remove` is never forced. Shared node_modules / .venv links are unlinked
first (the link only, never its target). Every action is logged.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ACTIVE_DAYS = 3
ABANDONED_DAYS = 14
LIVE_SESSION_HOURS = 3
CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
LINK_DIRS = ("frontend/node_modules", "backend/.venv", "node_modules")


# --------------------------------------------------------------------------- helpers
def git(cwd: str | Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return r.returncode, r.stdout.strip()


def norm(p: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(p))).replace("\\", "/").rstrip("/")


def repo_root() -> Path:
    rc, out = git(Path.cwd(), "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc:
        sys.exit("not inside a git repository")
    return Path(out).parent


# --------------------------------------------------------------------------- data
@dataclass
class Worktree:
    path: str
    head: str = ""
    branch: str | None = None
    locked: str | None = None
    prunable: bool = False
    is_main: bool = False
    exists: bool = True
    dirty: int = 0
    dirty_sample: list[str] = field(default_factory=list)
    ahead: int = 0
    unpushed: int = 0
    in_main: bool = False
    merged_pr: int | None = None
    open_pr: int | None = None
    last_commit: str = ""
    last_activity_days: float | None = None
    live_session: bool = False
    recent_checkout: bool = False  # worktree created/checked out/committed in the last ACTIVE_DAYS (git admin dir)
    protected: bool = False
    error: str = ""
    cls: str = ""
    reason: str = ""
    removable: bool = False
    branch_deletable: bool = False


def parse_worktrees(porcelain: str) -> list[Worktree]:
    out: list[Worktree] = []
    cur: Worktree | None = None
    for line in porcelain.splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = None
            continue
        key, _, val = line.partition(" ")
        if key == "worktree":
            cur = Worktree(path=val)
        elif cur is None:
            continue
        elif key == "HEAD":
            cur.head = val
        elif key == "branch":
            cur.branch = val.removeprefix("refs/heads/")
        elif key == "locked":
            cur.locked = val or "locked"
        elif key == "prunable":
            cur.prunable = True
    if out:
        out[0].is_main = True
    return out


def classify(w: Worktree) -> tuple[str, str]:
    """Pure classification from collected facts. Returns (class, reason)."""
    if not w.exists or w.prunable or w.error:
        return "unknown", w.error or ("folder missing" if not w.exists else "git marks it prunable")
    if w.dirty:
        return "uncommitted", f"{w.dirty} uncommitted/untracked file(s)"
    merged = w.in_main or w.merged_pr is not None
    if w.unpushed and not merged:
        return "unpushed", f"{w.unpushed} commit(s) exist only on this PC"
    if merged:
        how = "tip is in origin/main" if w.in_main else f"tip equals merged PR #{w.merged_pr}"
        return "merged-clean", how
    recent = w.last_activity_days is not None and w.last_activity_days <= ACTIVE_DAYS
    if w.live_session or recent or w.open_pr:
        bits = [b for b, on in (("live Claude session", w.live_session), (f"changed within {ACTIVE_DAYS} days", recent),
                                (f"open PR #{w.open_pr}", bool(w.open_pr))) if on]
        return "active", ", ".join(bits)
    if w.last_activity_days is not None and w.last_activity_days > ABANDONED_DAYS:
        return "abandoned", f"not merged, all commits on a remote, idle {w.last_activity_days:.0f} days, no open PR"
    return "unknown", f"not merged, pushed, idle {w.last_activity_days or 0:.0f} days, no open PR"


def removal_ok(w: Worktree, explicit_pr: bool = False) -> bool:
    """A recently created/used worktree is never auto-removed; naming its merged PR (--pr) is the only override."""
    return (w.cls == "merged-clean" and not w.locked and not w.protected and not w.is_main
            and not w.live_session and w.exists and (explicit_pr or not w.recent_checkout))


# --------------------------------------------------------------------------- facts
def live_session_paths(hours: int = LIVE_SESSION_HOURS) -> set[str]:
    """cwd of every Claude Code transcript written in the last `hours` (best-effort, read-only)."""
    found: set[str] = set()
    if not CLAUDE_PROJECTS.is_dir():
        return found
    cutoff = time.time() - hours * 3600
    for f in CLAUDE_PROJECTS.glob("*/*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            with f.open("rb") as fh:
                fh.seek(max(0, f.stat().st_size - 200_000))
                tail = fh.read().decode("utf-8", "replace").splitlines()
            for line in reversed(tail):
                if '"cwd"' in line:
                    try:
                        found.add(norm(json.loads(line)["cwd"]))
                        break
                    except (ValueError, KeyError):
                        continue
        except OSError:
            continue
    return found


def pr_index(root: Path) -> tuple[dict[str, set[tuple[int, str]]], dict[str, int]]:
    r = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "2000", "--json", "number,state,headRefName,headRefOid"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    merged: dict[str, set[tuple[int, str]]] = {}
    open_: dict[str, int] = {}
    if r.returncode:
        print("WARNING: gh pr list failed; merged-PR (squash) detection disabled", file=sys.stderr)
        return merged, open_
    for p in json.loads(r.stdout or "[]"):
        if p["state"] == "MERGED":
            merged.setdefault(p["headRefName"], set()).add((p["number"], p["headRefOid"]))
        elif p["state"] == "OPEN":
            open_[p["headRefName"]] = p["number"]
    return merged, open_


def load_protected(root: Path) -> set[str]:
    f = root / "scripts" / "worktree-protect.txt"
    if not f.exists():
        return set()
    return {ln.split("#", 1)[0].strip() for ln in f.read_text(encoding="utf-8").splitlines()} - {""}


def collect(root: Path) -> list[Worktree]:
    git(root, "fetch", "-q", "origin")
    _, porcelain = git(root, "worktree", "list", "--porcelain")
    wts = parse_worktrees(porcelain)
    merged_prs, open_prs = pr_index(root)
    live = live_session_paths()
    protected = load_protected(root)
    now = time.time()
    for w in wts:
        p = Path(w.path)
        w.exists = p.is_dir()
        w.protected = (w.branch in protected) or (norm(w.path) in {norm(x) for x in protected})
        w.live_session = any(s == norm(w.path) or s.startswith(norm(w.path) + "/") for s in live)
        if not w.exists:
            continue
        rc, status = git(p, "status", "--porcelain")
        if rc:
            w.error = "git status failed"
            continue
        files = [ln[3:] for ln in status.splitlines() if ln.strip()]
        w.dirty, w.dirty_sample = len(files), files[:5]
        w.ahead = int(git(p, "rev-list", "--count", "origin/main..HEAD")[1] or 0)
        w.unpushed = int(git(p, "rev-list", "--count", "HEAD", "--not", "--remotes")[1] or 0)
        w.in_main = git(p, "merge-base", "--is-ancestor", "HEAD", "origin/main")[0] == 0
        if w.branch:
            for num, oid in merged_prs.get(w.branch, ()):
                if oid == w.head:
                    w.merged_pr = num
            w.open_pr = open_prs.get(w.branch)
        _, gitdir = git(p, "rev-parse", "--absolute-git-dir")
        admin = [Path(gitdir) / "HEAD", Path(gitdir) / "logs" / "HEAD"]
        admin_times = [f.stat().st_mtime for f in admin if f.exists()]
        w.recent_checkout = bool(admin_times) and (now - max(admin_times)) / 86400 <= ACTIVE_DAYS
        _, ts = git(p, "log", "-1", "--format=%ct")
        times = [int(ts)] if ts.isdigit() else []
        for f in files[:50]:
            try:
                times.append(int((p / f.strip('"')).stat().st_mtime))
            except OSError:
                pass
        if times:
            w.last_commit = dt.datetime.fromtimestamp(int(ts) if ts.isdigit() else times[0]).strftime("%Y-%m-%d")
            w.last_activity_days = round((now - max(times)) / 86400, 1)
    for w in wts:
        w.cls, w.reason = classify(w)
        w.removable = removal_ok(w)
    in_use = {w.branch for w in wts if w.branch and not w.removable}
    for w in wts:
        w.branch_deletable = bool(w.removable and w.branch and w.branch not in in_use
                                  and w.branch not in protected and w.branch not in ("main", "master"))
    return wts


# --------------------------------------------------------------------------- report
ORDER = ["uncommitted", "unpushed", "active", "abandoned", "unknown", "merged-clean"]


def report(wts: list[Worktree], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    counts = {c: sum(w.cls == c for w in wts) for c in ORDER}
    lines = [f"# Worktree audit (dry run): {stamp}", "", f"Worktrees: **{len(wts)}**. Nothing was changed.", "",
             "| Class | Count | Meaning |", "|---|---:|---|"]
    meaning = {
        "uncommitted": "has files not committed: NEVER removed",
        "unpushed": "has commits only on this PC: NEVER removed",
        "active": "recent, live session or open PR: kept",
        "abandoned": "not merged but fully pushed, idle: owner decides, not auto-removed",
        "unknown": "could not be classified safely: kept",
        "merged-clean": "merged and clean: eligible for safe removal (unless locked/protected/live)",
    }
    lines += [f"| {c} | {counts[c]} | {meaning[c]} |" for c in ORDER]
    rem = [w for w in wts if w.removable]
    lines += ["", f"**Eligible for safe removal: {len(rem)} worktrees, {sum(w.branch_deletable for w in rem)} branches.**", ""]
    for c in ORDER:
        group = [w for w in wts if w.cls == c]
        if not group:
            continue
        lines += [f"## {c} ({len(group)})", "", "| Worktree | Branch | Ahead | Unpushed | Dirty | Last activity (days) | Lock/protect | Reason |",
                  "|---|---|---:|---:|---:|---:|---|---|"]
        for w in sorted(group, key=lambda x: (x.last_activity_days if x.last_activity_days is not None else 1e9)):
            lp = ", ".join(x for x in (("LOCKED: " + w.locked) if w.locked else "", "PROTECTED" if w.protected else "",
                                      "MAIN" if w.is_main else "", "LIVE" if w.live_session else "",
                                      "RECENT (kept)" if w.recent_checkout and w.cls == "merged-clean" else "") if x)
            lines.append(f"| `{w.path}` | `{w.branch or 'detached ' + w.head[:7]}` | {w.ahead} | {w.unpushed} | {w.dirty} | "
                         f"{'' if w.last_activity_days is None else w.last_activity_days} | {lp} | {w.reason} |")
        lines.append("")
    lines += ["## Exact commands a cleanup would run (dry run)", "", "```"]
    for w in rem:
        for d in LINK_DIRS:
            lines.append(f"# unlink if link: {w.path}/{d}")
        lines.append(f'git worktree remove "{w.path}"')
        if w.branch_deletable:
            flag = "-d" if w.in_main else "-D  # squash-merged: tip equals merged PR head, re-checked before"
            lines.append(f"git branch {flag} {w.branch}")
    lines += ["```", ""]
    md = out / "worktree-audit.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    (out / "worktree-audit.json").write_text(json.dumps([asdict(w) for w in wts], indent=1), encoding="utf-8")
    return md


# --------------------------------------------------------------------------- cleanup
def unlink_links(path: Path, log) -> None:
    for d in LINK_DIRS:
        p = path / d
        if p.is_symlink():
            p.unlink()
            log(f"  unlinked symlink {p}")
        elif hasattr(os.path, "isjunction") and os.path.isjunction(p):
            os.rmdir(p)  # removes the junction only, never the target
            log(f"  unlinked junction {p}")


def cleanup(root: Path, apply: bool, pr: int | None, log_path: Path) -> int:
    wts = collect(root)
    explicit = pr is not None
    if explicit:
        head = pr_branch(root, pr)
        targets = [w for w in wts if (w.merged_pr == pr or (w.branch and w.in_main and w.branch == head))
                   and removal_ok(w, explicit_pr=True)]
        in_use = {x.branch for x in wts if x.branch and x not in targets}
        for w in targets:
            w.branch_deletable = bool(w.branch and w.branch not in in_use and not w.protected
                                      and w.branch not in ("main", "master"))
    else:
        targets = [w for w in wts if w.removable]
    with log_path.open("a", encoding="utf-8") as fh:
        def log(msg: str) -> None:
            print(msg)
            fh.write(msg + "\n")

        log(f"=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} cleanup {'APPLY' if apply else 'DRY RUN'} pr={pr} targets={len(targets)}")
        for w in targets:
            log(f"- {w.path} [{w.branch}] {w.reason}")
            if not apply:
                continue
            fresh = {x.path: x for x in collect_one(root, w)}
            again = fresh.get(w.path)
            if not again or not removal_ok(again, explicit_pr=explicit):
                log("  SKIP: re-check failed (state changed)")
                continue
            unlink_links(Path(w.path), log)
            rc, out = git(root, "worktree", "remove", w.path)
            log(f"  worktree remove rc={rc} {out[-200:]}")
            if rc == 0 and w.branch_deletable:
                flag = "-d" if git(root, "merge-base", "--is-ancestor", w.branch, "origin/main")[0] == 0 else "-D"
                if flag == "-D" and git(root, "rev-parse", w.branch)[1] != w.head:
                    log("  SKIP branch: tip moved since audit")
                    continue
                rc2, out2 = git(root, "branch", flag, w.branch)
                log(f"  branch {flag} rc={rc2} {out2[-200:]}")
        git(root, "worktree", "prune")
    return 0


def collect_one(root: Path, w: Worktree) -> list[Worktree]:
    """Re-collect facts for the whole list (cheap enough for a handful of targets, simplest correct path)."""
    return [x for x in collect(root) if norm(x.path) == norm(w.path)]


def pr_branch(root: Path, pr: int) -> str | None:
    r = subprocess.run(["gh", "pr", "view", str(pr), "--json", "headRefName", "--jq", ".headRefName"],
                       cwd=str(root), capture_output=True, text=True, check=False)
    return r.stdout.strip() or None if r.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--out", default=None)
    c = sub.add_parser("cleanup")
    c.add_argument("--pr", type=int, default=None, help="only the worktree(s) of this merged PR")
    c.add_argument("--apply", action="store_true", help="actually remove (default: dry run)")
    args = ap.parse_args()
    root = repo_root()
    if args.cmd == "audit":
        out = Path(args.out) if args.out else root / ".claude" / "worktree-audit"
        md = report(collect(root), out)
        print(f"report: {md}")
        return 0
    log_dir = root / ".claude" / "worktree-audit"
    log_dir.mkdir(parents=True, exist_ok=True)
    return cleanup(root, args.apply, args.pr, log_dir / "cleanup.log")


if __name__ == "__main__":
    raise SystemExit(main())
