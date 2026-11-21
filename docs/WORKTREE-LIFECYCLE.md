# Worktree and branch lifecycle (#407)

This PC keeps many git worktrees (one per feature, fix or agent). This page describes how they are audited and safely removed, without ever losing work that exists only on this PC.

Tool: `scripts/worktree_lifecycle.py`. Tests: `scripts/test_worktree_lifecycle.py`.

## 1. Audit (read-only, always safe)

```
python scripts/worktree_lifecycle.py audit            # writes .claude/worktree-audit/worktree-audit.md + .json
```

Every worktree gets exactly one class:

| Class | Meaning | Can cleanup remove it? |
|---|---|---|
| uncommitted | has modified or untracked files, **or gitignored files that aren't rebuildable caches** (for example a local `.joblib` model, a `backend/data/` folder or a `.env` copy). Only true caches don't count: `node_modules`, `.venv`, `__pycache__`, the pytest, ruff and mypy caches, `*.pyc`, `*.egg-info`, `*.tsbuildinfo`. Build-output folders such as `dist` or `coverage` **do** count, because they can hold hand-made files. Tracked files marked `--assume-unchanged` or skip-worktree also count, because they can hide local edits. | **Never** |
| unpushed | has commits that exist on no remote and in no merged PR | **Never** |
| active | not merged; a live Claude session is in it, it changed in the last 3 days, or it has an open PR | No |
| abandoned | not merged, but every commit is on GitHub, no open PR, idle over 14 days | No (owner decides) |
| unknown | folder missing, prunable, or unreadable | No |
| merged-clean | clean, and its tip is in `origin/main` or equals the head of a merged PR | Yes, if the checks below pass |

## 2. Two steps: quarantine first, delete later

1. **`cleanup --apply` deletes nothing.** It *moves* each eligible worktree into `../worktree-quarantine/` (`git worktree move`, so every file is kept). It records the move in `manifest.json`. `restore <name>` moves it straight back.
2. **`purge --apply`** permanently removes quarantined worktrees only once they have been there at least 7 days (`--older-than-days`). It re-checks everything first, then deletes the branch.

So a file that appears at the last second, a mistaken eligibility, or a change of mind can always be undone during the quarantine week.

## 3. Safety checks (re-checked immediately before each move and again before each purge)

- class is `merged-clean`
- not locked (`git worktree lock`)
- not listed in `scripts/worktree-protect.txt`. The list is re-read before every action; if it is missing, `--apply` refuses to run at all (fail closed).
- not the main checkout
- no live Claude session inside it (any Claude Code transcript written in the last 3 hours with its folder as cwd)
- not created, checked out or committed in the last 3 days. Naming its merged PR with `--pr` is the only override for the move; quarantine age is the grace period for the purge.
- the same path, **branch and commit** as when it was audited or quarantined

Further rules:
- "Clean" includes gitignored files that aren't true caches, and files marked assume-unchanged or skip-worktree. git's `status.showUntrackedFiles` setting is overridden, so no untracked file can hide.
- `--pr N` only accepts a PR that GitHub reports as **merged**, and the worktree's tip must equal that PR's merged head. If several merged PRs share the branch and tip, any of them qualifies.
- `git worktree remove` (purge only) is **never forced**. Shared `node_modules` / `.venv` links are unlinked first; only the link goes, never its target.
- A branch is deleted (purge only) when all of these hold:
  - no registered worktree, locked or not, still uses it
  - it isn't protected
  - it is in `origin/main`, or its tip is a verified merged PR head
  - it still points at the audited commit. The delete uses an atomic `git update-ref -d <ref> <commit>`.
- `git worktree prune` is never run, because it is repo-wide. The tool doesn't `git fetch` unless `--fetch` is given.
- The report never prints raw git removal commands, only the guarded script steps.
- Any failed or refused action makes the command exit with code 1. Every action goes to `.claude/worktree-audit/cleanup.log`.

## 4. After a PR merges

```
python scripts/worktree_lifecycle.py cleanup --pr 406            # dry run: shows exactly what would happen
python scripts/worktree_lifecycle.py cleanup --pr 406 --apply    # moves that PR's worktree into quarantine
python scripts/worktree_lifecycle.py restore <folder-name>       # undo, if needed
python scripts/worktree_lifecycle.py purge                       # dry run of the weekly purge
python scripts/worktree_lifecycle.py purge --apply               # removes quarantined worktrees >= 7 days old
```

**Automation (proposed, needs owner OK before it is switched on):** when a PR is marked done after the owner merges it (the `update-tickets` step), Claude runs `cleanup --pr <N>` as a dry run, then `--apply` (quarantine only). The weekly purge stays a separate, explicit step.

Bulk cleanup (`cleanup --apply` without `--pr`) runs only after the owner has approved the exact dry-run report.

## 5. Protecting work

1. Add the branch or path to `scripts/worktree-protect.txt`.
2. Lock it: `git worktree lock --reason "<why>" <path>`.
3. Back up local-only work outside the worktrees:
   - commits: `git bundle create <dir>/<branch>.bundle origin/main..<branch>`
   - uncommitted files: `git diff HEAD > <dir>/<branch>.patch`, plus a tar of the untracked files

Backups made 2026-11-21: `D:/machine learning/worktree-backups/2026-11-21/` (`feature/groww-sync` bundle; `fix/5d-plan-honest-levels` patch, untracked files and base commit).
