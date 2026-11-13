# TradeMind AI Task Handoff

## Current task

Task: Set up shared AI engineering rules and standardize the task handoff.
Owner: Codex
Status: Done

## Git snapshot

Branch: `review/local-work-nov12`
Commit: `1498b2c9530e8719357844ecdb67378285a666e8`
Uncommitted changes (snapshot taken 2026-11-13, Asia/Calcutta):

- Modified: `AGENTS.md`, `CLAUDE.md`.
- Untracked: `.claude/`, `.codex/`, `docs/ARCHITECTURE_REVIEW.md`,
  `docs/MASTER-CHECKLIST.md`, `docs/ai/`.
- `.claude/settings.local.json` is gitignored.
- This snapshot includes pre-existing work; it does not attribute every change
  to this task. No commit was created.

## Completed work

- Merged the owner's shared rules, agent roles, critical boundaries, and handoff
  requirements into `AGENTS.md`.
- Configured Codex with `default_permissions = ":read-only"` and
  `approval_policy = "never"`.
- Added the missing local Claude settings file as an empty JSON object.
- Adopted the owner's handoff format in this file.
- Preserved existing `CLAUDE.md`, shared Claude settings, and unrelated work.

## Changed files

- `AGENTS.md`: merged project workflow and shared AI engineering rules.
- `.codex/config.toml`: added the read-only default.
- `.claude/settings.local.json`: added missing local file; remains gitignored.
- `docs/ai/HANDOFF.md`: created and updated this task handoff.
- This latest formatting update changes only `docs/ai/HANDOFF.md`.

## Test results

- Earlier setup checks confirmed that all five requested files exist and local
  Claude settings parse as JSON.
- `git diff --check` passed after the shared-rules update.
- Application tests were not run for these documentation and configuration edits.

## Open findings

- Unrelated working-tree changes remain; preserve them.
- Saved Codex defaults do not change permissions of an already-running session.
- Production state has not been verified during this task.

## Next action

- Await the owner's next task. Codex defaults to independent audits, architecture
  verification, and review; Claude Code defaults to implementation, refactoring,
  frontend work, and test creation.
- Stay read-only during reviews. Explicitly switch to workspace permissions before
  implementation. When writes are permitted, update this handoff with the current
  branch, commit, changed files, actual test results, findings, and next task.
- Read `AGENTS.md`, `CLAUDE.md`, and `docs/architecture/CURRENT-STATE.md` before
  starting work. During read-only reviews, propose handoff updates in the response.

## Restrictions

No production access, deployments, model activation, or order execution without
explicit approval. Never deploy, push, or merge without approval. Require approval
for schema migrations. Never read or expose secrets. Keep trading in paper mode
and preserve all risk controls. Approval requirements do not override the trading
and secrets rules in `CLAUDE.md` and `AGENTS.md`.
