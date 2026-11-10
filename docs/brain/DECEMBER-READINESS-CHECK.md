# December readiness check (can the system run unattended?)

Written 2026-11-10 from `origin/main` 768a66e. Read-only: nothing was changed, deployed or posted to prod.
From December there is no coding assistant, so this answers: what runs by itself, what tells the owner when it breaks, and
where the owner would be blind.

How to read the labels: **VERIFIED** = I saw it in code, in GitHub Actions logs or in a live read-only call today.
**UNVERIFIED** = it happens on the droplet and I cannot SSH; the exact read-only command for the owner is given.
Related files: `docs/brain/DECEMBER-RUNBOOK.md` (section 7 is the main "if X breaks" table; this file adds rows),
`docs/BACKUP-OFFSITE.md`, `docs/DEPLOY.md`.

## Short answer

- The daily machinery is healthy today (prod answers, scheduler running, brain ran, Zerodha logged in, 27 of the last 27 nightly backups green).
- **Biggest real risks for December:**
  1. The off-site (Google Drive) backup is **not set up**. Every nightly "success" is only a copy on the same droplet (VERIFIED from the 10 Nov log).
  2. The droplet disk is filling: free space fell from 17 GB (8 Nov) to 9.5 GB (10 Nov) after the 9 Nov deploys (VERIFIED, backup logs).
  3. The Telegram token is a single point of failure: if it breaks, **every** alarm goes quiet and nothing tells you.
  4. GitHub switches off scheduled workflows in a repository with no commits for 60 days. After development stops on 30 Nov, the uptime alarm, nightly backup and daily-check watch could stop around late January (GitHub rule; the date is my calculation, UNVERIFIED for this repo).
  5. The restore drill has not passed since its fix (last two runs failed on 1 Nov; fix is on main, no run since).

## 1. Scheduled jobs

### 1a. GitHub workflows (all VERIFIED from `.github/workflows` and `gh run list`)

| Workflow | When (IST) | What it does | Last 5 results (newest first) | Secrets it needs (names only) |
|---|---|---|---|---|
| `uptime.yml` | every 10 min | Checks /health, /ready, then /status (scheduler running; Zerodha connected 09:15-15:30 weekdays). Telegram on down, hourly reminder, back-up message | 10 Nov x2, 9 Nov x3, all success | `API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `daily-check-watch.yml` | weekdays 17:15 | Telegram if no 16:20 daily-check record exists for a trading day | 10 Nov (manual, holiday) ok; 9 Nov, 6, 5, 4 Nov scheduled, all success | `API_KEY`, `TELEGRAM_*` |
| `daily-backup.yml` | daily 23:00 | SSH to droplet, run `infra/deploy/daily-backup.sh`; Telegram on failure | 10, 8, 7, 6, 5 Nov all success (27 of the last 27 success) | `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (environment `production`), `TELEGRAM_*` |
| `dependency-audit.yml` | Monday 09:00 | Library security audit (fails on high/critical) | success on every PR run today | none |
| `restore-drill.yml` | **manual only** (no schedule) | Restores last nightly backup in a throw-away container on the droplet | 1 Nov fail, 1 Nov fail, 30 Oct success, 20 Oct success, 20 Oct fail | `DEPLOY_*` |
| `deploy.yml` | on push to main | Window guard, tests, SSH deploy, smoke test, Telegram | 10 Nov success, 9 Nov one failure then success | `DEPLOY_*`, `API_KEY`, `TELEGRAM_*` |
| `test.yml`, `secret-scan.yml` | on PRs/push | Tests and history scan for leaked secrets | pass (test.yml showed two PR failures today, unrelated to prod) | none |

Secret names present (`gh secret list`): repository: `API_KEY` (added 2026-11-10), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (14 Oct).
Environment `production`: `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_USER` (18 Oct). None of these has an expiry date in GitHub.

### 1b. Backend scheduler (VERIFIED, `backend/src/swing_trade_ml/workers/scheduler.py`)

All jobs: one run at a time, missed runs are merged, a run may start up to 5 minutes late (`scheduler.py:30-33`).
On failure the common path `_report_error` logs, marks the job failed in Admin > Jobs and sends a Telegram "Job failed" message
(`workers/jobs.py:56-61`). It is only as good as Telegram (see section 3).

| Job | Schedule (IST) | If it fails | Matters in December |
|---|---|---|---|
| Kite auto-login (`scheduler.py:~74`) | Mon-Fri 06:10 | Telegram "Job failed"; then nag every 30 min 06:15-15:45 until a session exists | Yes |
| Nag missing Kite session | Mon-Fri 06:15-15:45, :15 and :45 | It is the alarm itself | Yes |
| Heartbeat, Kite-login check, alert flush, server watch | every 1 / 1 / 5 / 5 min | server watch failure is logged only, never messaged (by design) | Yes (memory) |
| Morning feeds | Mon-Fri 08:30 | Data check; evening 22:05 job is the "still missing" alarm | Yes |
| Daily candles ingest | Mon-Fri 15:40 | Telegram "Job failed" | Yes |
| Predict, signal scan | 15:42, 15:45 (default) | Telegram "Job failed" | Yes (paper trading) |
| Brain nightly run | Mon-Fri 15:50 (`add_brain_jobs`) | Telegram "Job failed"; daily check reports a missing run | **Yes, core** |
| Brain intraday | Mon-Fri every 15 min 09:30-15:15 | same | Yes |
| Brain daily check | Mon-Fri 16:20 (skips holidays) | Telegram "Job failed"; the outside watcher covers "never ran" | **Yes** |
| Models backup (local copy) | Mon-Fri 16:30 | Telegram; weekly health also checks its age | Yes |
| Evening fills, feeds, filings | 19:20 / 19:30 / 19:40 | 22:05 final feeds job is the alarm | Yes |
| **h05 daily job** (`brain/lanes/h05_job.py:48`) | **Mon-Sat 07:30, 08:30, 18:30, 20:30, 22:30**, only if lane enabled AND protocol accepted | It catches every error and writes only a log line (`h05_job.py:248-250`); **no Telegram** | **Yes, the evidence** |
| Experiments scoring | Mon-Fri 20:40 | Telegram | Low |
| Brain learning (Saturday 10:00), weekly health Telegram (Saturday 11:00) | Saturday | Telegram "Job failed" | Yes |
| Weekly paper report | Sunday 09:30 | Telegram | Low |
| Instruments sync | Sunday 08:00 | Telegram | Low |
| Retention / cleanup | **No cleanup job exists** in the scheduler. Cleanup is inside `daily-backup.sh` (old backups) only | n/a | See disk risk |

Not verified: that these jobs have actually run on the droplet in the last days (only indirect proof today: `last_scan_at` 10 Nov, `last_nightly_ok` 10 Nov, see section 5).
Owner command: `docker logs --since 24h stml-worker 2>&1 | grep -E "job.failed|h05\." | tail -30`.

Note: 10 Nov 2026 is an NSE holiday (the app says `holiday`), yet `last_scan_at` shows a scan on 10 Nov 15:54 IST. The job fired on a holiday; I did not check whether it correctly did nothing (UNVERIFIED, P2).

## 2. Backups

| Item | Finding | Status |
|---|---|---|
| Nightly run | 27 of the last 27 runs of `daily-backup.yml` succeeded; last run 10 Nov 00:46 UTC (scheduled 23:00 IST; GitHub starts it late) | VERIFIED |
| What it makes | `pg_dumpall`, gzip, checked for damage and minimum size, `/root/backups/daily-*/database.sql.gz` (about 82 MB). `daily-backup.sh:35-45` | VERIFIED |
| Local retention | Newest 14 daily copies kept; deploy-time `database.sql` copies kept for the 5 newest releases (`daily-backup.sh:47-51`) | VERIFIED |
| Off-site (Google Drive, encrypted) | **Not set up.** 10 Nov log line: "Off-server copy not set up yet (rclone remote 'gdrive' or passphrase missing)" then "DAILY BACKUP OK (off-server: not set up)". The script exits 0 in that case, so the workflow is green and no Telegram is sent (`daily-backup.sh:78-80`) | VERIFIED |
| Off-site retention (once set up) | Database copies 15 days; model files and manifests kept forever (`daily-backup.sh:55-58`) | VERIFIED in code only |
| Model-file copy off-site | OFF by default; runs only if `/root/.backup-models-enabled` exists (`daily-backup.sh:63-70`, PR #175) | VERIFIED in code; flag file UNVERIFIED |
| Restore drill | Manual only. 1 Nov two runs failed (script bug, `restore-drill.sh:107`, temp file deleted too early). Fix `5b6a95b` dated 1 Nov is on main. **No drill run since the fix** (last success 30 Oct) | VERIFIED |
| `scripts/verify_restore.py` | Exists (PC tool, needs Docker); `BACKUP-OFFSITE.md` says it was only rehearsed locally on 3 Nov, never against a real Drive | VERIFIED |
| Restore procedure the owner can follow alone | Partly. `docs/BACKUP-OFFSITE.md` "Getting a copy back" decrypts a copy; it then says "restore exactly as the restore drill does" and points at `restore-drill.sh`. There is **no single step-by-step "my droplet is gone, rebuild it" page**. `docs/DEPLOY.md` is written for developers (git, worktrees) and its "Timing" section still says deploying in market hours is fine, which contradicts the real guard | VERIFIED |
| Disk and memory | 4 GB droplet. Free disk before the nightly backup: 16 GB (5 Nov), 17 GB (6, 7, 8 Nov), **9.5 GB (10 Nov)**. A drop of about 7 GB came with the 9 Nov deploys (image builds). On 1 Nov the drill saw 77 GB total, 60 GB used, 78% | VERIFIED |
| Disk alarm | The 16:20 daily check warns at 80% used and flags bad at 90% (`services/server_health.py:22-23`) and sends Telegram when something needs a look. Memory: server watch warns below 12% available and restarts a bloated worker at 1.7 GB (`server_watch.py:43,47`) | VERIFIED in code |
| Owner check on droplet | `df -h /` ; `docker system df` ; `cat /root/backups/daily-last.txt` ; `ls /root/.backup-models-enabled /root/.backup-passphrase ; rclone listremotes` | UNVERIFIED |

Documented prune advice ("prune Docker builder cache first", DECEMBER-RUNBOOK section 7) has **no exact command** and `docs/DEPLOY.md` has no disk section (searched). No scheduled prune exists in the repo or workflows.

## 3. Failure alerts (Telegram paths)

Backend sender: `notifications/telegram.py` ("best-effort": failures are logged and swallowed). Workflows send with `curl`
and only print the HTTP code; they do **not** fail when Telegram rejects the message.

| Alert | Trigger | What silence means | Gap |
|---|---|---|---|
| "Job failed" from any backend job | `_report_error` (`workers/jobs.py:56`) | Jobs fine, OR Telegram broken | none if Telegram works |
| Brain daily check problem message | 16:20 weekdays when a check fails (`job_brain_daily_check`) | All checks ok, OR job never ran (covered next row), OR Telegram broken | |
| Daily check watch | 17:15 weekdays, no record stored for the trading day | Record exists | Needs `API_KEY` secret (added 10 Nov; a manual run on the 10 Nov holiday correctly said "not a trading day", VERIFIED) |
| Uptime | every 10 min, site down, scheduler off, or Zerodha not connected in market hours | All up | GitHub may start runs 5-20 min late; **it is the only alarm that works when the whole droplet is down** |
| Kite login nag | 06:15-15:45 every 30 min with no session | Logged in | Telegram-dependent |
| Server watch memory warning | server short of memory, 1 per hour | Memory fine | Telegram-dependent |
| Daily-backup failure | Workflow fails | Backup ran, **or only "not set up"** | Does not fire when off-site is not set up (P0-1) |
| Deploy result | after each deploy | | Only when someone merges |
| Saturday 11:00 health summary | weekly | **Silence on Saturday is the signal** | Only noticed if the owner remembers |
| Disk warning | inside the 16:20 daily check message | | Only weekday evenings |

Gaps:

- **Telegram token breaks:** nothing alerts. The backend swallows errors; workflows ignore the HTTP code; no heartbeat message. The owner would only
  notice by absence. Nothing else in the repo watches the token (searched `TELEGRAM` in backend and workflows). (P0-3)
- **h05 lane misses a session:** known, being fixed in another PR, not duplicated here. Today's report already shows 1 missed session (section 5).
- **Silent success on missing off-site copy:** see above (P0-1).
- **Droplet down and Telegram ok:** covered by the uptime alarm only; GitHub's 60-day rule below can switch it off.

## 4. Credentials, expiry and housekeeping risks

| Risk | What I found | Status |
|---|---|---|
| Kite access token | Expires about 06:00 IST daily. Auto-login (TOTP) runs Mon-Fri 06:10; on failure the nag messages every 30 minutes until a login exists; uptime also alarms if Zerodha is not connected 09:15-15:30. Today `broker_authenticated` is true. The manual "Log in to Kite" button is the fallback. Paper mode: no real money. Zerodha password or TOTP secret changes are not detectable in advance | VERIFIED (code + live) |
| Website login (JWT) | `JWT_EXPIRE_MINUTES = 720` (12 h) (`core/config.py:57`); owner just logs in again. The `API_KEY` used by workflows has no expiry in code | VERIFIED |
| GitHub secret rotation | No expiry on any secret; nothing reminds the owner to rotate. If the SSH key or token is rotated on the droplet, backup/deploy fail and Telegram says so (backup) | VERIFIED |
| GitHub schedules switching off | GitHub disables scheduled workflows after 60 days with no repository activity. Last dev commit is expected 30 Nov, so around 29 Jan 2027 the uptime alarm, daily backup and daily-check watch could silently stop. h05 run 2 is due after 2027-01-28 (runbook section 5), so the owner may be active, but do not rely on it | UNVERIFIED (GitHub rule, my date) |
| Dependabot | `.github/dependabot.yml`: pip and npm weekly, GitHub Actions monthly; frontend majors ignored. PRs never merge themselves. A merge in December would deploy (see next row) | VERIFIED |
| Deploy window guard | `deploy.yml:25-37`: refused Mon-Fri 09:00-16:30 IST unless "force" is ticked. So a stray merge in market hours does not restart the worker. A merge after 16:30 deploys and restarts the worker anyway | VERIFIED. The brain (15:50) and daily check (16:20) are inside the guarded window |
| TLS certificate | Public site cert: issuer Let's Encrypt, expires **5 Feb 2027** (read from the live handshake). That date implies it was renewed about 7 Nov, so renewal has worked recently. The renewal mechanism (certbot timer or similar on the host nginx) is **not in the repo** and no workflow checks expiry | Expiry VERIFIED; mechanism UNVERIFIED |
| Docker and OS updates | Not in repo. Whether `unattended-upgrades` is on, or a reboot is pending, is unknown. Containers use `restart: unless-stopped` for at least the frontend (`docker-compose.prod.yml:63`) | UNVERIFIED |
| Disk and memory alarms | See section 2: both exist, both rely on Telegram and the weekday daily check (disk) | VERIFIED |

## 5. Live read-only prod check (2026-11-10 about 21:15 IST, GET only, no secrets printed)

| Call | Result |
|---|---|
| /status | 200; production, paper mode, live trading off, scheduler running, broker (Kite) logged in, Telegram enabled, 2 open positions, latest candle 2026-11-09, last scan 10 Nov 15:54 IST, level ok |
| /brain/health | 200; last nightly ok 10 Nov, failed runs in last 7 days: 0, stale count: 0 |
| /brain/daily-checks/latest | day 2026-11-09, status `check` ("needs a look"; detail not read here). No 10 Nov record is expected: 10 Nov is a holiday |
| /research/h05/report | 200; protocol_accepted: true; one run: days_recorded 6, sessions_in_window 7, missed_sessions 1, events 1 (counts only; trial results not printed) |
| Market calendar | state `holiday`, last closed trading day 2026-11-09 |

The daily check status `check` on 9 Nov is consistent with the disk warning but I did not read why. Owner: open the app's daily check page, or read the Telegram message sent at 16:20 on 9 Nov.

## 6. December "if X breaks" table (companion to `DECEMBER-RUNBOOK.md` section 7)

Runbook section 7 stays as it is. These rows are additions.

| What you see (or do not see) | What it probably means | What to do (plain English) |
|---|---|---|
| "Nightly database backup FAILED" on Telegram | The droplet copy or its upload failed | Open the Actions run link, read the red line. Then on the droplet run `cat /root/backups/daily-last.txt` and `df -h /` |
| No backup message at all, but you never set up Google Drive | The backups are green but only live on the same droplet | Set up Drive (`docs/BACKUP-OFFSITE.md`) before 30 Nov, or accept the risk that losing the droplet loses everything |
| Disk warning in the 16:20 message | Docker images and backups are filling the disk | On the droplet: `docker builder prune -f` then `docker image prune -f` (these remove only unused build cache and unused images, never volumes). Never run `docker volume prune` or `docker system prune --volumes`: that can delete the database |
| Memory warning or "worker restarted" | The 4 GB server is short of memory | Do nothing if it happens once; the watch restarts the worker itself. If hourly for days, tell your developer |
| Saturday 11:00 summary did not arrive | Saturday job failed, or Telegram is broken | Run the uptime test message (Actions, Uptime alarm, Run workflow, tick the test box). No message there either means Telegram is the problem: see next row |
| Telegram stopped completely | Bot token or chat id changed or revoked | Create a new token in BotFather, then GitHub Settings, Secrets, update `TELEGRAM_BOT_TOKEN`; the droplet `.env` also needs it (droplet step). Test with the Uptime alarm test message |
| "Brain daily check missing" | The 16:20 job did not run | Check the site is up; check the Kite login; run `docker logs --since 6h stml-worker \| tail -50` on the droplet |
| h05 report shows more missed sessions | A morning/evening run did not happen | Do not backfill (protocol). Note the date. Check the worker was running |
| Zerodha not connected message | Daily auto-login failed | Press "Log in to Kite" in the app (production site only). Paper mode, no money at risk |
| Uptime says DOWN | Site, database or scheduler down | Wait 10 minutes (two checks are made). If still down: on the droplet `docker ps` and `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` |
| Padlock or certificate warning in the browser | Certificate renewal failed | On the droplet: `certbot renew --dry-run` and `systemctl list-timers \| grep certbot` (assumes certbot; unconfirmed) |
| No GitHub emails or Telegram after late January | GitHub may have switched off scheduled workflows | GitHub, Actions, enable each workflow, or make any small commit. Do this on a calendar reminder every month |
| Dependabot PR appears | A library update | Ignore until January. Never merge on a weekday before 16:30 IST; never "force" a deploy without the developer |

## 7. Gap list

Needs-owner means a secret, a droplet command or a decision. "Small PR" means doable by 30 Nov, docs or workflow only, no trading code.

### P0 (could silently lose evidence or leave the owner blind)

| # | Gap | Evidence | Proposed fix | Who |
|---|---|---|---|---|
| P0-1 | Off-site backup not set up; "success" hides it | 10 Nov log; `daily-backup.sh:78-80` exits 0 | (a) Owner sets up rclone + passphrase (`BACKUP-OFFSITE.md`, 10 minutes), (b) small PR: make the script say `offsite=not set up` as a Telegram warning once a week | Owner (a), small PR (b) |
| P0-2 | h05 lane misses a session without any alert | `h05_job.py:248-250`; report shows 1 missed | Covered by another PR, not repeated here | Other PR |
| P0-3 | Telegram token failure is invisible | `telegram.py` swallows errors; workflows ignore HTTP code | Small PR: let workflow steps fail when Telegram returns non-200 (GitHub then emails the owner), plus a weekly Telegram "alive" message from a workflow so silence is detectable. Confirm GitHub failure emails are on | Small PR + owner setting |
| P0-4 | GitHub switches scheduled workflows off after 60 days of no commits | GitHub rule | Owner: monthly calendar reminder to run any workflow manually; small PR: a docs line in the runbook. A keep-alive workflow commit is not recommended | Owner decision |

### P1

| # | Gap | Evidence | Proposed fix | Who |
|---|---|---|---|---|
| P1-1 | Disk falling fast (17 GB to 9.5 GB across 9 Nov deploys), no tested prune command in docs | backup logs; no disk text in `DEPLOY.md` | Owner runs `df -h /` and `docker system df` now; small PR: add the exact safe prune commands and a "never prune volumes" line to the runbook | Owner + small PR |
| P1-2 | Restore drill not proven since the 1 Nov fix; it is manual only | run list | Owner: Actions, Restore drill, Run workflow once, read the result; small PR: monthly schedule is not advised (it uses droplet memory) | Owner |
| P1-3 | No single "rebuild from scratch" restore page for a non-expert | `BACKUP-OFFSITE.md` points to scripts | Small PR: plain-English restore page (docs only) | Small PR |
| P1-4 | TLS renewal mechanism undocumented and not monitored | cert expires 5 Feb 2027; nothing in repo | Owner runs the two read-only commands below; small PR: add a certificate-expiry step to `uptime.yml` (alarm under 14 days) | Owner + small PR |
| P1-5 | OS/Docker updates and reboots unmanaged | not in repo | Owner runs `systemctl is-enabled unattended-upgrades` and `ls /var/run/reboot-required` | Owner |
| P1-6 | Model files not copied off-site (flag off) | `daily-backup.sh:63-70` | Owner decision after one passing verify drill | Owner |

### P2

| # | Gap | Evidence | Proposed fix | Who |
|---|---|---|---|---|
| P2-1 | `docs/DEPLOY.md` "Timing" says market-hours deploys are fine; the guard now refuses them | `DEPLOY.md` vs `deploy.yml:25-37` | One-paragraph docs fix | Small PR |
| P2-2 | A scan ran on the 10 Nov holiday (`last_scan_at`); behaviour not verified | /status | Read the worker log for 10 Nov 15:45 | Owner command |
| P2-3 | Secrets have no rotation reminder | | Calendar reminder every 6 months | Owner |
| P2-4 | `test.yml` showed two failed PR runs on 10 Nov | run list | Not prod-affecting; check before any December merge | Developer |

## 8. Read-only commands for the owner on the droplet

None of these change anything. Run them over SSH and keep the output.

```bash
df -h /                                        # disk: look at Use% (warning at 80%, bad at 90%)
docker system df                               # what Docker is using (builder cache is the usual culprit)
cat /root/backups/daily-last.txt               # last backup result and whether off-site is ok / not set up / failed
ls -ld /root/.backup-passphrase /root/.backup-models-enabled   # exist = off-site / model copy configured
rclone listremotes                             # should list gdrive: if Drive is set up
docker logs --since 24h stml-worker 2>&1 | grep -E "job.failed|h05\." | tail -30
free -m; docker stats --no-stream              # memory
systemctl list-timers | grep -i certbot        # certificate renewal timer (if certbot is used)
sudo certbot certificates                      # expiry date seen by the server (if certbot is used)
systemctl is-enabled unattended-upgrades; ls /var/run/reboot-required
```

## 9. What I could not verify

- Anything on the droplet (backups' real contents, off-site flag files, prune history, certbot, OS updates, worker log).
- Whether GitHub failure emails are enabled for the owner's account.
- That the Telegram token currently works end to end (only that Telegram is `enabled` in /status; a test message needs a manual Actions run).
- Why the daily check on 9 Nov says `check`.
