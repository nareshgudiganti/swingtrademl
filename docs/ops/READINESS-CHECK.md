# Readiness check (owner checklist)

Plain-English checks the owner can run before declaring production healthy and before the next deploy.
Every check is read-only. Nothing here changes production, deploys, or places an order. No password, key or
secret is written in this file: where a key is needed it is read from your own environment and never printed.

Do the checks in order. Stop at the first FAIL, write down what you saw, and do not deploy until it is understood.
Times are IST. Do the deploy-related steps after 16:30 IST on weekdays (the deploy workflow refuses 09:00 to 16:30).

## A. Is the site and the background worker alive?

| # | Check | How | Pass looks like |
|---|---|---|---|
| A1 | Website answers | Open https://swingtrademl.com/api/v1/health in a browser | `200` with a short "ok" style reply |
| A2 | Database answers | Open https://swingtrademl.com/api/v1/ready | `200` |
| A3 | Worker and scheduler are running | Call `/api/v1/status` with your API key from your own terminal (read the key from your environment, do not paste it anywhere) and look at `scheduler_running` and `status_level` | `scheduler_running` is `true`; `status_level` is `ok`. A message saying the scheduler is not running means the worker is stopped |
| A4 | The scheduled jobs are listed | Same `/status` reply, `scheduled_jobs` | The list includes `signal_scan`, `check_exits`, `reconcile_orders`, `heartbeat` and `company_filings` |
| A5 | The outside alarm is working | GitHub, Actions, workflow "Uptime alarm", most recent run | A green run within the last 20 minutes |

## B. Is it still in paper mode?

| # | Check | How | Pass looks like |
|---|---|---|---|
| B1 | Trading mode | Same `/status` reply, `trading_mode` and `live_trading_enabled` | `trading_mode` is `paper` and `live_trading_enabled` is `false`. Anything else is an emergency: going live is the owner's decision only |
| B2 | Brain stage | `/api/v1/brain/stage` (needs the key) | Answers `200` and shows the stage you expect (practice) |

## C. Which build is live?

The app does not report which commit it runs, so the evidence is on GitHub, not on the site.

| # | Check | How | Pass looks like |
|---|---|---|---|
| C1 | Last deploy | GitHub, Actions, workflow "Deploy to production", newest run with a green tick | Its commit (shown under the run title) is the one you believe is live. A merge to `main` does not deploy, so `main` can be ahead of production |
| C2 | A newer failed run | Same list, any red run after that green one | None. If there is one, open it: a red deploy can leave things half changed (see `docs/DEPLOY.md`, step 6) and no Telegram message is sent for a failed deploy job |
| C3 | How far behind is production? | GitHub, the repository's commits on `main` since the commit in C1 | You can name every commit not yet live. Those are exactly what the next deploy would release |

## D. Disk space

| # | Check | How | Pass looks like |
|---|---|---|---|
| D1 | Server disk | DigitalOcean control panel, the droplet, Graphs, Disk (or on the server, `df -h /`) | Comfortably below 80 percent used. A deploy builds new images and writes a database dump, so it needs free space of at least the database size plus the images |
| D2 | Memory | Same graphs, Memory | Not pinned near the top for long periods |

## E. Backups and the off-server copy

Background: `docs/BACKUP-OFFSITE.md` and `docs/DEPLOY.md` ("Database backups and restoring").

| # | Check | How | Pass looks like |
|---|---|---|---|
| E1 | Last nightly backup | GitHub, Actions, workflow "Daily backup", newest run | Green, started about 23:00 IST last night. A failed run sends a Telegram message |
| E2 | Result file | On the server, `cat /root/backups/daily-last.txt` | Starts with `ok`, a time from last night, `offsite=ok`. `offsite=not set up` or `failed` is a FAIL for this check |
| E3 | Off-server copy exists | Your Google Drive backup folder | A file for last night with a plausible size (close to the previous night's) |
| E4 | A copy on this PC | Your PC backup folder | A recent database copy that you could restore from if the server and the Drive were both lost |
| E5 | Restore proof | GitHub, Actions, "Restore drill", newest run (or `scripts/verify_restore.py`, see `docs/BACKUP-OFFSITE.md`) | A green run that is recent enough for you to trust. A backup that has never been restored is not yet proof |
| E6 | Model files copied off the server | Same Drive folder, models and manifests | A manifest dated within the last day or two |

## F. The company filings job (#420)

| # | Check | How | Pass looks like |
|---|---|---|---|
| F1 | The job is scheduled | `/status`, `scheduled_jobs` | `company_filings` is listed. It runs weekdays at 19:40 IST |
| F2 | It has run | The Company and news screen for a tracked company | Filings with dates from the last working day. Empty after 20:00 IST on a working day is a FAIL |
| F3 | It does not touch trading | Display only | No effect on orders, risk or the brain. If this job fails, the rest keeps working |
| F4 | The database change is in | Release notes of the deploy that carried it (C1) | The deploy that added the filings tables completed green |

## G. The nine safety items (#345, S1 to S9)

The list of nine items is kept in the issue, not in this repository, so it cannot be copied here. For each item write
one line: what it protects, the command or screen that shows it works, and what a pass looks like. The owner (or
whoever opens #345) fills this table before the readiness check is called complete.

| Item | What it protects | How to see it works | Pass looks like |
|---|---|---|---|
| S1 to S9 | to fill from #345 | to fill from #345 | to fill from #345 |

## H. The one recovery deploy

Use this only when A to F show the running build is behind and the order below is still the plan. One deploy, not two.

1. Merge the deploy-safety fix by pull request (required checks must be green).
2. Merge the flaky-test fix by pull request.
3. Wait for both to be on `main`, and for it to be after 16:30 IST on a weekday (or any time on a weekend).
4. The owner starts ONE new run: Actions, Deploy to production, Run workflow, branch `main`. Never "Re-run" an old run:
   that redeploys the old commit.
5. Watch the run to the end. Afterwards repeat A1 to A4 and B1.

Pass looks like: the run is green, `scheduler_running` is `true`, `trading_mode` is `paper`, and the worker shows a fresh
heartbeat. If the run is red or the worker is stopped, do not start a second run: read `docs/DEPLOY.md` (Rollback and step 6).

## What this check cannot prove

- Branch protection and the production environment settings live in GitHub, not in the repository. Confirm them in
  GitHub settings.
- The disk, backup file and Drive checks need a person looking at the server or the Drive.
- A green smoke test shows the site answers; it does not prove every scheduled job will run tonight.
