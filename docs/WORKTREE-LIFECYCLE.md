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
| uncommitted | has modified or untracked files | **Never** |
| unpushed | has commits that exist on no remote and in no merged PR | **Never** |
| active | not merged; a live Claude session is in it, it changed in the last 3 days, or it has an open PR | No |
| abandoned | not merged, but every commit is on GitHub, no open PR, idle over 14 days | No (owner decides) |
| unknown | folder missing, prunable, or unreadable | No |
| merged-clean | clean, and its tip is in `origin/main` or equals the head of a merged PR | Yes, if the checks below pass |

## 2. Safety checks before any removal

A worktree is removed only if **all** of these hold. They are re-checked immediately before acting:

- class is `merged-clean`
- not locked (`git worktree lock`)
- not listed in `scripts/worktree-protect.txt`
- not the main checkout
- no live Claude session inside it (any Claude Code transcript written in the last 3 hours with its folder as cwd)
- not created, checked out or committed in the last 3 days. **The only override** is naming its merged PR with `--pr`.

Further rules:
- `git worktree remove` is **never forced**, so git itself refuses a folder that has changed.
- Shared `node_modules` / `.venv` links are unlinked first. Only the link goes, never its target.
- A branch is deleted only if no other worktree uses it and its tip is in `origin/main` or equals the merged PR head (squash merges). Every action goes to `.claude/worktree-audit/cleanup.log`.

## 3. Cleanup after a PR merges

```
python scripts/worktree_lifecycle.py cleanup --pr 406            # dry run: shows exactly what would happen
python scripts/worktree_lifecycle.py cleanup --pr 406 --apply    # removes that PR's worktree + branch
```

**Automation (proposed, needs owner OK before it is switched on):** when a PR is marked done after the owner merges it (the `update-tickets` step), Claude runs `cleanup --pr <N>` as a dry run, shows the result, then `--apply`. That removes only that PR's own folder and branch, and only if nothing local-only is left.

Bulk cleanup (`cleanup --apply` without `--pr`) runs only after the owner has approved the exact dry-run report.

## 4. Protecting work

1. Add the branch or path to `scripts/worktree-protect.txt`.
2. Lock it: `git worktree lock --reason "<why>" <path>`.
3. Back up local-only work outside the worktrees:
   - commits: `git bundle create <dir>/<branch>.bundle origin/main..<branch>`
   - uncommitted files: `git diff HEAD > <dir>/<branch>.patch`, plus a tar of the untracked files

Backups made 2026-11-21: `D:/machine learning/worktree-backups/2026-11-21/` (`feature/groww-sync` bundle; `fix/5d-plan-honest-levels` patch, untracked files and base commit).
