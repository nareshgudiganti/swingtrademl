# TradeMind AI Engineering Rules

## Start here

This file is the repository entry point for Codex and other AI coding agents.
Project rules live in [`CLAUDE.md`](CLAUDE.md); read that file before writing code,
especially **Risk rules** and **Secrets and API keys**. Treat it as the source of
truth for project policy. The reminders below do not replace it.
The shared rules below add the owner's approval and agent-role requirements.

At the start of each task:

1. Read `CLAUDE.md`, `docs/architecture/CURRENT-STATE.md`, and
   `docs/ai/HANDOFF.md` for the latest session handoff.
2. Check `git status --short` and preserve existing user changes.
3. Read any more specific `AGENTS.md` instructions in the directories you touch.
4. Inspect the relevant implementation and tests before making a focused change.

## Shared rules

- Read existing code before proposing changes.
- Keep changes focused and backward-compatible.
- Do not overwrite another agent's work.
- Report verified findings with file and line references.
- Never read or expose secrets.
- Never access production systems without approval, including read-only checks.
  Codex never queries prod. The read-only `API_KEY` exception in `CLAUDE.md`
  applies to Claude Code only.
- Never deploy, push, or merge without approval.

## Claude Code

Default owner of implementation, refactoring, frontend development, and test
creation.

## Codex

Default owner of independent code audits, architecture verification, and review.
Stay read-only during review tasks.

## Review loop (Claude implements, Codex reviews)

1. Claude implements on a branch, runs the checks, updates `docs/ai/HANDOFF.md`,
   and stops. Claude does not merge, push, or deploy.
2. Codex reviews the diff read-only against the critical boundaries below and
   writes findings (file and line, verified only) to `docs/ai/REVIEW.md`. If the
   session is fully read-only, Codex gives the findings in its reply and the owner
   pastes them into `REVIEW.md`.
3. Claude verifies each finding against the code before acting
   (`superpowers:receiving-code-review`), fixes the valid ones, and marks each as
   fixed, rejected (with reason), or deferred in `REVIEW.md`.
4. The owner approves before anything reaches `main`, because a push to `main`
   deploys to production.

## TradeMind critical boundaries

- Protect model evaluation and experiment evidence.
- Avoid look-ahead leakage in financial market data.
- Preserve trading calendar correctness.
- Protect Brain decision and order execution separation.
- Preserve risk checks and trading safety controls.
- Require approval for schema migrations and model activation.

## Safety reminders

- Keep trading in paper mode. Never enable live trading or place real orders.
- Do not loosen risk limits. Changes to order placement, sizing, stops, or limits
  require tests and owner approval before reaching `main`.
- Pushing to `main` deploys to production. Do not push or deploy as part of routine
  local editing unless the owner has authorized it.
- Never read or display the root `.env` file or expose credentials. Use
  `.env.example` to inspect available settings. The shared rules above require
  approval for production access; credential-handling exceptions in `CLAUDE.md`
  do not grant that approval or permission to read secrets.
- Keep brain modules pure and point-in-time reads bounded by `as_of`. Preserve
  the existing v1 data and trading path.

## Working and verification

- Follow the architecture, branch, formatting, and testing rules in `CLAUDE.md`.
- Keep edits scoped to the task; do not overwrite unrelated work or use bare
  `git stash`.
- Format only touched backend files. Do not run Prettier on existing frontend
  files; use the TypeScript check specified in `CLAUDE.md`.
- Use `backend/.venv/Scripts/python.exe` for backend tests. Unset `API_KEY`,
  `DATABASE_URL`, `JWT_SECRET_KEY`, and `TRADING_MODE` in the test process as
  instructed in `CLAUDE.md`. Ensure Docker Postgres is running before DB tests.
- Consult the skills listed in `CLAUDE.md` when applicable. If a required skill
  is unavailable, report that limitation and do not claim to have used it.
- Verify the change before claiming success. For documentation-only edits,
  inspect the diff and run `git diff --check`; application tests are unnecessary.
- Finish with a plain-English summary of changes, checks performed, and any
  remaining limitations. Never claim a check passed unless it was run.

## Handoff

Use `docs/ai/HANDOFF.md` for task information. Include the current branch, changed
files, test results, remaining issues, and the next agent's task. Update it only
when the session permits writes; during read-only reviews, provide proposed
handoff updates in the response.
