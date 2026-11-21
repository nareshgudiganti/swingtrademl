#!/usr/bin/env python3
"""Git worktree and branch lifecycle: audit (dry run) and safe cleanup after PR merges (#407).

Usage (run from anywhere inside the repo):
    python scripts/worktree_lifecycle.py audit [--out DIR]          # read-only report (Markdown + JSON)
    python scripts/worktree_lifecycle.py cleanup [--pr N] [--apply]  # quarantine; dry run unless --apply
    python scripts/worktree_lifecycle.py restore <name>              # undo a quarantine move
    python scripts/worktree_lifecycle.py purge [--apply]             # remove quarantined (>= 7 days), re-checked

Classes (one per worktree, first match wins):
    unknown         path missing, prunable, or git could not read it
    uncommitted     modified or untracked files (ignored files do not count)
    unpushed        commits that exist on no remote and are not in a merged PR
    merged-clean    clean, and its tip is in origin/main or equals the head of a merged PR
    active          not merged: a live Claude session is in it, it changed recently, or it has an open PR
    abandoned       not merged, clean, every commit is on a remote, no open PR, inactive for a while
    unknown         anything else

Cleanup MOVES a worktree into a quarantine folder (git worktree move; nothing is deleted, `restore` undoes it)
ONLY when, re-checked just before acting: class is merged-clean, it is not
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
# Ignored paths that are pure, rebuildable caches. ANY other ignored file (models, .env copies, data, notes)
# is treated as possible local-only work and blocks removal.
REGENERABLE_DIRS = {"node_modules", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def shell_quote(text: str) -> str:
    """Single-quote for copy-paste into bash or PowerShell (both treat single quotes literally)."""
    return "'" + text.replace("'", "''") + "'"


def regenerable(path: str) -> bool:
    """True only for rebuildable caches/build output; anything else ignored may be the only copy of something."""
    p = path.replace("\\", "/").rstrip("/")
    if p.endswith((".pyc", ".tsbuildinfo")):
        return True
    return any(part in REGENERABLE_DIRS or part.endswith(".egg-info") for part in p.split("/"))


# --------------------------------------------------------------------------- helpers
def git(cwd: str | Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(
        ["git", "--no-optional-locks", "-c", "status.showUntrackedFiles=all", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
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
    merged_prs: list[int] = field(default_factory=list)
    open_pr: int | None = None
    last_commit: str = ""
    last_activity_days: float | None = None
    live_session: bool = False
    recent_checkout: bool = False  # worktree created/checked out/committed in the last ACTIVE_DAYS (git admin dir)
    ignored_local: int = 0  # gitignored files that are NOT regenerable caches; they count as uncommitted
    hidden_by_index_flags: int = 0  # tracked files marked assume-unchanged/skip-worktree: may hide local edits
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
        extra = f" incl. {w.ignored_local} ignored non-cache file(s)" if w.ignored_local else ""
        return "uncommitted", f"{w.dirty} uncommitted/untracked file(s){extra}"
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
    try:
        r = _gh_pr_list(root)
    except FileNotFoundError:
        print("WARNING: GitHub CLI not found; merged-PR (squash) detection disabled", file=sys.stderr)
        return {}, {}
    return _parse_prs(r)


def _gh_pr_list(root: Path):
    return subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "2000", "--json", "number,state,headRefName,headRefOid"],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _parse_prs(r) -> tuple[dict[str, set[tuple[int, str]]], dict[str, int]]:
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


PROTECT_FILE: Path | None = None  # set by --protect; default: the copy next to this script


def protect_file() -> Path:
    return PROTECT_FILE or Path(__file__).with_name("worktree-protect.txt")


def load_protected(root: Path) -> set[str] | None:
    """None when the protection list is missing: callers must then refuse to delete anything (fail closed)."""
    f = protect_file()
    if not f.exists():
        return None
    return {ln.split("#", 1)[0].strip() for ln in f.read_text(encoding="utf-8").splitlines()} - {""}


@dataclass
class Context:
    merged_prs: dict[str, set[tuple[int, str]]]
    open_prs: dict[str, int]
    protected: set[str]
    protect_loaded: bool


FETCH = False  # set by --fetch; by default nothing (not even origin/main) is updated


def context(root: Path) -> Context:
    if FETCH:
        git(root, "fetch", "-q", "origin")
    merged_prs, open_prs = pr_index(root)
    loaded = load_protected(root)
    if loaded is None:
        print(f"WARNING: protection list not found at {protect_file()}; cleanup --apply will refuse to run",
              file=sys.stderr)
    return Context(merged_prs, open_prs, loaded or set(), loaded is not None)


def inspect(w: Worktree, ctx: Context, live: set[str], now: float) -> None:
    """Fill the facts for one worktree, then classify it (read-only)."""
    p = Path(w.path)
    w.exists = p.is_dir()
    w.protected = (w.branch in ctx.protected) or (norm(w.path) in {norm(x) for x in ctx.protected})
    w.live_session = any(s == norm(w.path) or s.startswith(norm(w.path) + "/") for s in live)
    if w.exists:
        rc, status = git(p, "status", "--porcelain", "--ignored", "--untracked-files=all")
        if rc:
            w.error = "git status failed"
        else:
            files: list[str] = []
            for ln in status.splitlines():
                if not ln.strip():
                    continue
                name = ln[3:].strip().strip('"')
                if ln.startswith("!!"):
                    if regenerable(name):
                        continue
                    w.ignored_local += 1  # ignored but not a cache: could be the only copy (e.g. a .joblib model)
                files.append(name)
            _, flagged = git(p, "ls-files", "-v")
            hidden = [ln[2:] for ln in flagged.splitlines() if ln[:1].islower() or ln[:1] == "S"]
            w.hidden_by_index_flags = len(hidden)
            files += [f"(assume-unchanged/skip-worktree) {h}" for h in hidden]
            w.dirty, w.dirty_sample = len(files), files[:5]
            w.ahead = int(git(p, "rev-list", "--count", "origin/main..HEAD")[1] or 0)
            w.unpushed = int(git(p, "rev-list", "--count", "HEAD", "--not", "--remotes")[1] or 0)
            w.in_main = git(p, "merge-base", "--is-ancestor", "HEAD", "origin/main")[0] == 0
            if w.branch:
                w.merged_prs = sorted(num for num, oid in ctx.merged_prs.get(w.branch, ()) if oid == w.head)
                w.merged_pr = w.merged_prs[0] if w.merged_prs else None
                w.open_pr = ctx.open_prs.get(w.branch)
            _, gitdir = git(p, "rev-parse", "--absolute-git-dir")
            admin_times = [f.stat().st_mtime for f in (Path(gitdir) / "HEAD", Path(gitdir) / "logs" / "HEAD")
                           if f.exists()]
            w.recent_checkout = bool(admin_times) and (now - max(admin_times)) / 86400 <= ACTIVE_DAYS
            _, ts = git(p, "log", "-1", "--format=%ct")
            times = [int(ts)] if ts.isdigit() else []
            for f in files[:50]:
                try:
                    times.append(int((p / f).stat().st_mtime))
                except OSError:
                    pass
            if ts.isdigit():
                w.last_commit = dt.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
            if times:
                w.last_activity_days = round((now - max(times)) / 86400, 1)
    w.cls, w.reason = classify(w)


def collect(root: Path, ctx: Context | None = None) -> list[Worktree]:
    ctx = ctx or context(root)
    _, porcelain = git(root, "worktree", "list", "--porcelain")
    wts = parse_worktrees(porcelain)
    live, now = live_session_paths(), time.time()
    qprefix = norm(quarantine_dir(root)) + "/"
    for w in wts:
        inspect(w, ctx, live, now)
        w.removable = removal_ok(w) and not norm(w.path).startswith(qprefix)
    in_use = {w.branch for w in wts if w.branch and not w.removable}
    for w in wts:
        w.branch_deletable = bool(w.removable and w.branch and w.branch not in in_use
                                  and w.branch not in ctx.protected and w.branch not in ("main", "master"))
    return wts


def recheck(root: Path, original: Worktree, ctx: Context, explicit: bool) -> tuple[bool, str]:
    """Re-inspect ONE worktree right before acting. Same path, branch and commit, and still removable."""
    _, porcelain = git(root, "worktree", "list", "--porcelain")
    match = [w for w in parse_worktrees(porcelain) if norm(w.path) == norm(original.path) and not w.is_main]
    if not match:
        return False, "worktree no longer registered"
    w = match[0]
    if w.branch != original.branch or w.head != original.head:
        return False, "branch or commit changed since the audit"
    fresh_protect = load_protected(root)
    if fresh_protect is None:
        return False, "protection list missing at re-check"
    ctx = Context(ctx.merged_prs, ctx.open_prs, fresh_protect, True)
    inspect(w, ctx, live_session_paths(), time.time())
    if not removal_ok(w, explicit_pr=explicit):
        return False, f"no longer removable ({w.cls}: {w.reason})"
    return True, "ok"


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
    lines += ["## What a cleanup would do (dry run)", "",
              "Raw git removal commands are deliberately NOT printed: they would skip the safety re-checks.",
              "Step 1 MOVES each worktree below into a quarantine folder (nothing deleted; `restore` undoes it):", "",
              "```", "python scripts/worktree_lifecycle.py cleanup            # dry run",
              "python scripts/worktree_lifecycle.py cleanup --apply    # quarantine", "```", "",
              f"Step 2, at least {QUARANTINE_DAYS} days later, permanently removes them after re-checking everything:", "",
              "```", "python scripts/worktree_lifecycle.py purge --apply", "```", "",
              "| Would be quarantined | Branch | Commit | Branch deleted at purge? |", "|---|---|---|---|"]
    for w in rem:
        lines.append(f"| `{w.path}` | `{w.branch or 'detached'}` | `{w.head[:7]}` | {'yes' if w.branch_deletable else 'no'} |")
    lines.append("")
    md = out / "worktree-audit.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    (out / "worktree-audit.json").write_text(json.dumps([asdict(w) for w in wts], indent=1), encoding="utf-8")
    return md


# --------------------------------------------------------------------------- cleanup (quarantine, restore, purge)
QUARANTINE_DAYS = 7


def quarantine_dir(root: Path) -> Path:
    """Same drive as the repo (git worktree move cannot cross drives)."""
    return root.parent / "worktree-quarantine"


def manifest_path(root: Path) -> Path:
    return quarantine_dir(root) / "manifest.json"


def load_manifest(root: Path) -> list[dict]:
    f = manifest_path(root)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def save_manifest(root: Path, entries: list[dict]) -> None:
    quarantine_dir(root).mkdir(parents=True, exist_ok=True)
    target = manifest_path(root)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    os.replace(tmp, target)  # atomic: a crash leaves either the old or the new file, never a broken one


class QuarantineLock:
    """Exclusive lock file so two cleanup/restore/purge runs never edit the manifest at the same time."""

    def __init__(self, root: Path):
        self.path = quarantine_dir(root) / ".lock"
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SystemExit(f"REFUSED: another run holds {self.path} (delete it only if no run is active)") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        self.acquired = True
        return self

    def __exit__(self, *exc):
        if self.acquired:  # a refused run must never delete the lock held by another run
            self.path.unlink(missing_ok=True)
            self.acquired = False


def unique_dest(qdir: Path, name: str) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    for i in range(1000):
        dest = qdir / (f"{name}__{stamp}" + (f"_{i}" if i else ""))
        if not dest.exists():
            return dest
    raise SystemExit("REFUSED: could not find a free quarantine folder name")


def unlink_links(path: Path, log) -> None:
    for d in LINK_DIRS:
        p = path / d
        if p.is_symlink():
            p.unlink()
            log(f"  unlinked symlink {p}")
        elif hasattr(os.path, "isjunction") and os.path.isjunction(p):
            os.rmdir(p)  # removes the junction only, never the target
            log(f"  unlinked junction {p}")


def merged_pr_branch(root: Path, pr: int) -> str | None:
    """Head branch of PR `pr` ONLY if GitHub says it is merged; otherwise None (open/closed PRs never qualify)."""
    try:
        r = subprocess.run(["gh", "pr", "view", str(pr), "--json", "state,headRefName"], cwd=str(root),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    except FileNotFoundError:
        return None
    if r.returncode:
        return None
    data = json.loads(r.stdout or "{}")
    return data.get("headRefName") if data.get("state") == "MERGED" else None


def _logger(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = log_path.open("a", encoding="utf-8")

    def log(msg: str) -> None:
        print(msg)
        fh.write(msg + "\n")
        fh.flush()

    return log, fh


def cleanup(root: Path, apply: bool, pr: int | None, log_path: Path) -> int:
    """Step 1: MOVE eligible worktrees into quarantine (nothing is deleted; `restore` undoes it).

    Returns 0 when every intended action succeeded (or a dry run), 1 when anything failed or was refused.
    """
    ctx = context(root)
    if apply and not ctx.protect_loaded:
        print(f"REFUSED: protection list missing ({protect_file()}); nothing moved.", file=sys.stderr)
        return 1
    wts = collect(root, ctx)
    explicit = pr is not None
    if explicit:
        head = merged_pr_branch(root, pr)
        if head is None:
            print(f"REFUSED: PR #{pr} is not merged (or could not be read); nothing moved.", file=sys.stderr)
            return 1
        targets = [w for w in wts if w.branch == head and pr in w.merged_prs and removal_ok(w, explicit_pr=True)]
    else:
        targets = [w for w in wts if w.removable]
    qdir = quarantine_dir(root)
    targets = [w for w in targets if not norm(w.path).startswith(norm(qdir) + "/")]
    failures = 0
    log, fh = _logger(log_path)
    lock = None
    try:
        log(f"=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} cleanup {'APPLY (quarantine)' if apply else 'DRY RUN'} "
            f"pr={pr} targets={len(targets)} quarantine={qdir}")
        lock = QuarantineLock(root) if apply else None
        if lock:
            lock.__enter__()
        manifest = load_manifest(root)
        for w in targets:
            log(f"- {w.path} [{w.branch or 'detached'} @ {w.head[:7]}] {w.reason}")
            if not apply:
                continue
            if Path(w.path).drive.lower() != qdir.drive.lower():
                log("  SKIP: worktree is on a different drive than the quarantine folder")
                failures += 1
                continue
            ok, why = recheck(root, w, ctx, explicit)
            if not ok:
                log(f"  SKIP: {why}")
                failures += 1
                continue
            dest = unique_dest(qdir, Path(w.path).name)
            entry = {"original": w.path, "quarantined": str(dest).replace("\\", "/"), "branch": w.branch,
                     "head": w.head, "in_main": w.in_main, "merged_prs": w.merged_prs,
                     "moved_at": dt.datetime.now().isoformat(timespec="seconds")}
            manifest.append(entry)
            save_manifest(root, manifest)  # restore record exists BEFORE anything moves
            rc, out = git(root, "worktree", "move", w.path, str(dest))  # keeps every file; reversible
            log(f"  moved to quarantine rc={rc} {out[-200:]}")
            if rc:
                manifest = [x for x in manifest if x is not entry]
                save_manifest(root, manifest)
                failures += 1
                continue
        log(f"=== done: failures={failures}")
    finally:
        if lock:
            lock.__exit__(None, None, None)
        fh.close()
    return 1 if failures else 0


def restore(root: Path, name: str, log_path: Path) -> int:
    """Move a quarantined worktree back to its original path."""
    manifest = load_manifest(root)
    hits = [e for e in manifest if Path(e["quarantined"]).name == name or norm(e["original"]) == norm(name)]
    if len(hits) != 1:
        print(f"REFUSED: expected exactly one quarantine entry for {name!r}, found {len(hits)}", file=sys.stderr)
        return 1
    e = hits[0]
    if Path(e["original"]).exists():
        print(f"REFUSED: {e['original']} already exists", file=sys.stderr)
        return 1
    log, fh = _logger(log_path)
    try:
        src = e["quarantined"]
        if not Path(src).exists() and e.get("previous_path") and Path(e["previous_path"]).exists():
            src = e["previous_path"]
        with QuarantineLock(root):
            rc, out = git(root, "worktree", "move", src, e["original"])
            log(f"=== restore {e['quarantined']} -> {e['original']} rc={rc} {out[-200:]}")
            if rc == 0:
                save_manifest(root, [x for x in load_manifest(root) if x["quarantined"] != e["quarantined"]])
    finally:
        fh.close()
    return 1 if rc else 0


def purge(root: Path, apply: bool, older_than_days: int, log_path: Path) -> int:
    """Step 2: permanently remove quarantined worktrees older than `older_than_days`, re-checking everything."""
    if older_than_days < QUARANTINE_DAYS:
        print(f"REFUSED: quarantine must last at least {QUARANTINE_DAYS} days (got {older_than_days}).", file=sys.stderr)
        return 1
    ctx = context(root)
    if apply and not ctx.protect_loaded:
        print(f"REFUSED: protection list missing ({protect_file()}); nothing purged.", file=sys.stderr)
        return 1
    now = dt.datetime.now()
    failures = 0
    log, fh = _logger(log_path)
    lock = None
    try:
        lock = QuarantineLock(root) if apply else None
        if lock:
            lock.__enter__()
        manifest = load_manifest(root)  # read under the lock: no stale snapshot can be written back
        due = [e for e in manifest
               if (now - dt.datetime.fromisoformat(e["moved_at"])).total_seconds() >= older_than_days * 86400]
        log(f"=== {now:%Y-%m-%d %H:%M:%S} purge {'APPLY' if apply else 'DRY RUN'} older_than={older_than_days}d "
            f"due={len(due)} of {len(manifest)}")
        keep = list(manifest)
        for e in due:
            log(f"- {e['quarantined']} [{e['branch'] or 'detached'} @ {e['head'][:7]}] from {e['original']}")
            if not apply:
                continue
            prot = load_protected(root) or set()
            if e["branch"] in prot or norm(e["original"]) in {norm(x) for x in prot}:
                log("  KEEP: original path or branch is now protected")
                continue
            orig = Worktree(path=e["quarantined"], head=e["head"], branch=e["branch"])
            ok, why = recheck(root, orig, ctx, explicit=True)  # quarantine age replaces the recency grace
            if not ok:
                log(f"  SKIP: {why}")
                failures += 1
                continue
            # Rename first: on Windows this fails while any process has a file open inside, and writers that
            # address the old path can no longer reach the folder. Then re-check under the new name.
            staging = unique_dest(quarantine_dir(root), Path(e["quarantined"]).name + "__purging")
            before = e["quarantined"]
            e["previous_path"] = before  # restore/purge fall back to this if the move never happened
            e["quarantined"] = str(staging).replace("\\", "/")
            save_manifest(root, keep)  # restore record points at the new path BEFORE the move
            rc, out = git(root, "worktree", "move", before, str(staging))
            if rc:
                e["quarantined"] = before
                save_manifest(root, keep)
                log(f"  SKIP: could not stage for purge (in use?) rc={rc} {out[-200:]}")
                failures += 1
                continue
            ok, why = recheck(root, Worktree(path=e["quarantined"], head=e["head"], branch=e["branch"]), ctx,
                              explicit=True)
            if not ok:
                log(f"  SKIP after staging: {why} (left at {e['quarantined']})")
                failures += 1
                continue
            unlink_links(Path(e["quarantined"]), log)
            rc, out = git(root, "worktree", "remove", e["quarantined"])  # never --force
            log(f"  worktree remove rc={rc} {out[-200:]}")
            if rc:
                failures += 1
                continue
            keep = [x for x in keep if x is not e]
            save_manifest(root, keep)
            failures += delete_branch_if_safe(root, e, log)
        log(f"=== done: failures={failures}")
    finally:
        if lock:
            lock.__exit__(None, None, None)
        fh.close()
    return 1 if failures else 0


def delete_branch_if_safe(root: Path, e: dict, log) -> int:
    """Delete the branch ref only if no registered worktree (locked or not) still uses it, it is protected by
    nothing, and it is merged (in origin/main, or its tip equals a merged PR head). Atomic against the audited
    commit. Returns 1 on a refused/failed delete, 0 otherwise (including 'nothing to do')."""
    b = e["branch"]
    if not b or b in ("main", "master"):
        return 0
    protected = load_protected(root)
    if protected is None or b in protected:
        log(f"  KEEP branch {b}: protected or protection list missing")
        return 0
    list_rc, porcelain = git(root, "worktree", "list", "--porcelain")
    if list_rc or not porcelain.strip():
        log(f"  KEEP branch {b}: could not list worktrees (rc={list_rc})")
        return 1
    if any(w.branch == b for w in parse_worktrees(porcelain)):
        log(f"  KEEP branch {b}: still checked out in another worktree")
        return 0
    anc_rc = git(root, "merge-base", "--is-ancestor", e["head"], "origin/main")[0]
    if anc_rc not in (0, 1):
        log(f"  SKIP branch: ancestry check failed (rc={anc_rc})")
        return 1
    if anc_rc == 1 and not e.get("merged_prs"):
        log("  SKIP branch: not in origin/main and no verified merged PR")
        return 1
    rc, out = git(root, "update-ref", "-d", f"refs/heads/{b}", e["head"])  # deletes only if still at that commit
    log(f"  branch {b} delete (expected {e['head'][:7]}) rc={rc} {out[-200:]}")
    return 1 if rc else 0


def main() -> int:
    global PROTECT_FILE, FETCH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--protect", default=None, help="path to the protection list (default: next to this script)")
    ap.add_argument("--fetch", action="store_true", help="git fetch origin first (otherwise fully read-only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--out", default=None)
    c = sub.add_parser("cleanup", help="move eligible worktrees into quarantine (dry run unless --apply)")
    c.add_argument("--pr", type=int, default=None, help="only the worktree(s) of this MERGED PR")
    c.add_argument("--apply", action="store_true")
    r = sub.add_parser("restore", help="move a quarantined worktree back")
    r.add_argument("name", help="quarantine folder name or original path")
    p = sub.add_parser("purge", help="permanently remove quarantined worktrees (dry run unless --apply)")
    p.add_argument("--older-than-days", type=int, default=QUARANTINE_DAYS)
    p.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.protect:
        PROTECT_FILE = Path(args.protect)
    FETCH = args.fetch
    root = repo_root()
    log_path = root / ".claude" / "worktree-audit" / "cleanup.log"
    if args.cmd == "audit":
        out = Path(args.out) if args.out else root / ".claude" / "worktree-audit"
        print(f"report: {report(collect(root), out)}")
        return 0
    if args.cmd == "cleanup":
        return cleanup(root, args.apply, args.pr, log_path)
    if args.cmd == "restore":
        return restore(root, args.name, log_path)
    return purge(root, args.apply, args.older_than_days, log_path)


if __name__ == "__main__":
    raise SystemExit(main())
