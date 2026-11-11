# Operations and launch guide

Written 2026-11-10 for the owner. Plain English. Status words: **done** = a document or commit proves it; **not done**
= known to be missing; **unverified** = nothing in the repo proves it, so check before relying on it. Current project
status lives in `docs/brain/PROJECT_COMPLETION_MATRIX.md` and `docs/architecture/CURRENT-STATE.md`.

Safety reminders: the app is paper only. Never set `TRADING_MODE=live` or `ALLOW_LIVE_TRADING=true`. Never paste secrets
(keys, tokens, passwords) into chat, files or documents.

---

## Part A: Daily and weekly operating guide

### Every trading day, after the market closes (about 5 minutes)

| When (IST) | What happens by itself | What you do |
|---|---|---|
| 15:45 | The v1 bot's scan runs (paper trades). | Nothing. |
| about 15:50 | Nightly brain run records the day's ideas. | Nothing. |
| 16:20 | The **daily check** runs on the server and sends one Telegram message. | Read it. |
| 17:15 | **Daily check watch** (GitHub) looks for today's daily-check record and messages you if it is missing. | If you get a message, the 16:20 job did not run: see "When something looks wrong". |
| 19:45 (every day) | **h05 watch** (GitHub) reads the 5-day evaluation report and messages you if a session was missed or an event was recorded. | Read it if it arrives. Silence means all fine. |
| every 10 min | **Uptime** check on the site. | Telegram says "down" or "back up". |
| 23:00 | **Nightly database backup** on the server (kept 14 days). | Nothing. A Telegram message only if it fails. |

Your five-minute look in the app is "Level 1" in `docs/brain/TESTING.md`: Brain page loads, latest nightly is the last
trading day, the banner shows one of NORMAL / DEFENSIVE / NO NEW TRADES, one stock card has a word and reasons, stage
still says Practice (shadow), and the TradeMind brain strategy is Active. A mostly-WAIT day with a NO NEW TRADES banner is
the safety rules working, not a failure.

### Every Saturday

At 11:00 IST the **weekly brain health report** arrives on Telegram (also `GET /brain/weekly-health`). Each line is OK or
CHECK. If everything is OK you can skip the manual checklist. If no message arrives, that itself means the worker or
Telegram needs a look. Detail: `docs/brain/weekly_health_checklist.md`. The "Model backup" line only looks at a
backup folder and warns if none is set up.

### What the Telegram messages mean

| Message | Meaning | Where it is described |
|---|---|---|
| Daily check (16:20) | Summary of the day's data, brain run and server health, with warnings. | `docs/QUALITY-CHECKS.md` (error watch, disk and memory alarm) |
| Brain daily check missing | The 16:20 job did not store a result. Nothing on the server could warn you about other problems that day. | `.github/workflows/daily-check-watch.yml` |
| h05 watch alert | A 5-day evaluation session was missed or an event was recorded. | `.github/workflows/h05-watch.yml` |
| Site down / back up | The uptime check could not reach the site, or it recovered. | `docs/QUALITY-CHECKS.md` |
| Backup failed | The nightly copy failed (no copy, damaged copy, or Drive upload failed). | `docs/BACKUP-OFFSITE.md`, "What gets messaged" |
| After-deploy smoke test failed | A deploy went out but the outside checks failed. | `docs/QUALITY-CHECKS.md`, "After-deploy smoke test" |
| Disk or memory warning | The 4 GB server is running low. | `docs/QUALITY-CHECKS.md` |
| Weekly brain health (Saturday) | OK / CHECK lines, see above. | `docs/brain/weekly_health_checklist.md` |

The Telegram token is a single point of failure: if it breaks, every alarm goes quiet (`docs/brain/DECEMBER-READINESS-CHECK.md`).

### When something looks wrong

Start with `docs/brain/TESTING.md` (Levels 1 and 2), then `docs/brain/DECEMBER-RUNBOOK.md` section 7 ("if X breaks") and
`docs/brain/DECEMBER-READINESS-CHECK.md`. Read-only API checks use the `X-API-Key` header with your own key from the
server settings; never write the key into a file. Public check: `GET https://swingtrademl.com/api/v1/health`.

---

## Part B: Deploy and rollback

Full steps are in `docs/DEPLOY.md`. In short: **a merge to `main` is the deploy.** The workflow re-runs all tests and only
releases if they pass; a red run means nothing was deployed.

- **Deploy window rule:** a deploy restarts the worker, so on weekdays between **09:00 and 16:30 IST** the workflow
  **refuses** to deploy (`.github/workflows/deploy.yml`). Merge outside that time, or open the refused run and "Re-run all
  jobs" after 16:30. For an emergency only, run the workflow by hand with the "force" box ticked. Do not deploy around
  15:40-15:50 (the scan). Note: `docs/DEPLOY.md` still says deploying during market hours is fine; the workflow rule
  above is the newer behaviour and wins.
- **Database migrations:** run the "Restore drill" workflow with `upgrade_check` on the branch first
  (`docs/QUALITY-CHECKS.md`, qa5). Do not deploy if it fails.
- **Rollback:** revert the bad commit and push the revert through the same pipeline (`git revert <sha>`, then merge). Never
  force-push `main`. The tag `v1` (`64fcb05`) is a reference, not a rollback button. The deploy script itself rolls back to
  the previous images if the release step fails.
- **Backups and restore:** `docs/DEPLOY.md` ("Database backups and restoring") and `docs/BACKUP-OFFSITE.md`. A plain replay
  of the dump is not a correct restore; use the Timescale procedure or `infra/deploy/restore-drill.sh`.
- **Watch the result:** wait for "Deploy to production" to finish green, then check `/health`; the smoke job does this for you.
- **Frozen files:** while the trial is sealed, trial-frozen files only change through `scripts/approve_trial_change.py`
  (owner approval). Changes to order placement, sizing, stops or limits need a test and your approval.

---

## Part C: Launch checklist for a future customer launch

Nothing here has started a launch. The app today is a private, paper-only tool: sign-up is closed, nobody pays, and the
Telegram goes to one chat. **No outside-facing feature should be designed until the SEBI assessment (D0a) is back, and no
outside user should see a pilot until the detailed written opinion (D0b) is back** (`docs/compliance/2026-10-21-sebi-d0a-briefing-pack.md`).
Lead times below are planning guesses unless a document says otherwise.

| # | Item | Owner | Lead time | Status |
|---|---|---|---|---|
| 1 | SEBI assessment D0a: hand the briefing pack to a SEBI compliance professional | You | Unknown (their turnaround) | Pack written 2026-10-21; whether it has been sent: **unverified** |
| 2 | SEBI opinion D0b: written opinion on the exact pilot design | You + professional | Unknown; only after D0a | Not started (**unverified**) |
| 3 | Release switch `ALLOW_SIGNUP` (sign-up page) | You | Minutes to flip | Off (code default); prod value not directly checked: **unverified** |
| 4 | Release switch `ALLOW_REAL_HOLDINGS_ORDERS` (manual real orders) | You | Minutes | Off; owner-verified on droplet 2026-11-09 (matrix) |
| 5 | Release switch `ALLOW_CUSTOMER_SCREENS` | You | Unknown | Name not found in the code on `9deb26a`: may not exist yet; decide what it should gate |
| 6 | Release switch `ALLOW_MODEL_PROMOTION` | You | Unknown | Name not found in the code on `9deb26a`: may not exist yet |
| 7 | Payments and billing | Developer | Months (guess) | **NOT BUILT**, dropped from the 2026 build; also a regulatory trigger (roadmap risk R13) |
| 8 | Email provider (sign-up, resets, notices) | You | Days (guess) | Not chosen |
| 9 | Privacy notice and DPDP consent for mobile numbers | You + professional | Weeks (guess) | Not done |
| 10 | Terms of use and investor disclaimers | You + professional | Weeks (guess) | Not done: no investor disclaimer exists in the app (briefing pack section 2) |
| 11 | Off-site backup set up (`docs/BACKUP-OFFSITE.md`) | You | About 10 minutes | Not done (readiness check 2026-11-10) |
| 12 | Backup restore drill passes after its fix | You | Under an hour | Last two runs failed 1 Nov; no run since (readiness check) |
| 13 | Monitoring: uptime, daily check, h05 watch, disk and memory alarm, Telegram | You | Already running | Running per readiness check 2026-11-10; a second alert path besides Telegram: not done |
| 14 | Model promotion evidence gate: a new model reaches customers only after its written evidence (5D run 1 verdict, 15D lab, Phase B record, SX5) | You | Months | Not met: 5D inconclusive, 10D failed, 15D starts 2026-12-05 |
| 15 | Paper-to-real go-live decision: manual approval trial first, ₹10K manual start | You | After evidence | Not started; owner's call only |
| 16 | Smoke tests: after-deploy smoke test, browser and accessibility tests, bad-data drills | Developer | Already automated | Run on every deploy (`docs/QUALITY-CHECKS.md`) |
| 17 | Multi-user rules: only the owner sees My Holdings and real orders; others are secondary | Developer | Weeks (guess) | Security part on `main`; later releases are design only (matrix P3) |
| 18 | Public repo review (code and research are public) | You | Days | Not done (**unverified**) |

Order of work: items 1-2 first (they decide what is allowed at all), then 7-10, then the switches (3-6) last, one at a time,
with a smoke test after each.
