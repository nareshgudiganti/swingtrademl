# Deploying to production

Written for: whoever is releasing this bot — including Claude in a future session.

Production is the DigitalOcean droplet behind <https://swingtrademl.com>. There
is no manual deploy step: **pushing to `main` is the deploy.**
`.github/workflows/deploy.yml` re-runs the whole test suite and only releases to
the droplet if it passes, so a red commit cannot reach production.

Prod configuration (`.env`) lives on the droplet at `/root/app/.env` and is *not*
in this repo. Nothing here can change it, and SSH from a dev machine is blocked —
so any fix that has to change prod behaviour must be a **code** change.

## The routine

1. **Branch off the current `origin/main`.** Never off a stale local `main`.

   ```bash
   git fetch origin
   git worktree add -b fix/<short-name> <tmp-dir> origin/main
   ```

   A worktree keeps whatever is half-finished in the main checkout untouched.
   More than one person (or session) edits this repo, so assume the working tree
   is not yours alone.

2. **Make the change, tests first.** See `CLAUDE.md` for the TDD expectation.

3. **Verify — all three, every time.** A green run of the one file you touched is
   not a green suite.

   ```bash
   backend/.venv/Scripts/python.exe -m pytest -q          # needs Docker Postgres up
   cd frontend && npm run typecheck && npm run build
   backend/.venv/Scripts/python.exe -m ruff check <changed files>
   ```

   - The backend suite needs the Docker Postgres on port 5433. If it is down,
     DB tests hang for ~264s and then fail confusingly. A port check is not a
     liveness check — actually connect.
   - If the test DB schema is stale (errors like `column ... does not exist`),
     drop and recreate the schema of **`swing_trade_ml_test` only**.
   - `npm run lint` currently fails for lack of an eslint config. That is
     pre-existing; `typecheck` and `build` are the real gates.
   - Ruff has known pre-existing findings. Compare against `main` (stash and
     re-run) and only fix the ones you added.

4. **Rebase onto `origin/main` again before pushing.** It moves often.

   ```bash
   git fetch origin && git rebase origin/main
   ```

   Then re-run the suite — a clean rebase is not a passing one.

5. **Push, and let CI deploy.**

   ```bash
   git push origin fix/<short-name>:main      # fast-forward = deploy
   ```

   Or open a PR and merge it. Same result; the PR just gives a review surface.

6. **Watch the release, don't assume it.**

   ```bash
   curl -s "https://api.github.com/repos/nareshgudiganti/swingtrademl/actions/runs?per_page=5"
   ```

   Wait for `Deploy to production` on your SHA to reach
   `completed / success`. `script_stop: true` means a failed release step fails
   the run rather than half-applying.

7. **Confirm prod is actually serving it.**

   ```bash
   KEY=$(grep '^API_KEY=' .env | cut -d= -f2-)
   curl -s -H "X-API-Key: $KEY" https://swingtrademl.com/api/v1/status
   curl -s https://swingtrademl.com/api/v1/health
   ```

   `/status` does not expose the released commit, so a green deploy run plus a
   healthy `/health` is the available evidence. Where the change is
   behavioural, name the observation that will confirm it and when it happens —
   for a scan change, that is the next 15:45 IST run.

8. **Clean up.** `git worktree remove <tmp-dir> --force && git worktree prune`.
   Leave the main checkout as you found it.

## Timing

The scan that trades runs at **15:45 IST, Mon–Fri**. Deploying during market
hours is fine — the scheduler runs inside the app and restarts with it — but a
deploy landing between 15:40 and 15:50 can interrupt the ingest → predict →
scan → fills chain for that day. Prefer outside that window.

## When the push is blocked

Claude Code's auto mode classifies a push to `main` as a production deploy and
blocks it unless the operator has granted permission. Claude **cannot grant
itself that permission** — writing the permission file is itself blocked as
self-modification, by design.

So either the operator merges/pushes, or they add the rules in
`.claude/settings.local.json` themselves (gitignored — never commit deploy
permissions to this public repo). See the "Letting Claude deploy" section of
whatever onboarding note the operator keeps; the rules needed are
`Bash(git push origin *)`, `Bash(git fetch *)` and `Bash(git rebase *)`, with
`Bash(git push --force*)` denied.

## Rollback

Revert the commit and push that — it is the same pipeline, and it re-runs the
tests on the way back:

```bash
git revert <bad-sha>
git push origin HEAD:main
```

Do not force-push `main`. It would skip the tested path and can silently drop
whatever else landed since.
