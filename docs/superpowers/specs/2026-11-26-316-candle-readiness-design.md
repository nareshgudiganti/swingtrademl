# #316 Candle readiness and delayed scan recovery: design (for owner approval)

Date: 2026-11-26 (IST). Status: DESIGN AND REVIEW RECORD ONLY. This PR changes no code and applies nothing.
Base checked: `origin/main` at `2f0696d7`. The implementation exists only as an uncommitted local change (section 3).
Related design: `2026-11-26-260-scan-record-and-rankings-design.md`.

## 1. The problem, in plain English

The daily scan decides which stocks to buy or sell from the newest daily price bar. If today's bar has not arrived yet
(a late data feed), the scan quietly uses yesterday's bar as if it were today's, and can send signals and paper
orders from old prices. Nothing re-checks later. #316 makes the scan wait for today's prices and run exactly once.

## 2. Current behaviour on `origin/main` (verified, file and line)

All in `backend/src/swing_trade_ml/workers/`:

- Three separate jobs on fixed clocks, none waiting for another (`scheduler.py`):
  - `daily_ingest` 15:40 IST (lines 132-135), runs `job_daily_ingest` (`jobs.py:396`).
  - `predict_watchlist` 15:42 (lines 138-141).
  - `signal_scan` 15:45 (lines 144-152, from `SIGNAL_SCAN_CRON_HOUR/MINUTE`), runs `job_signal_scan` (`jobs.py:500`).
- `job_signal_scan` calls `engine.run_all_active(db, interval="day")` straight away (`jobs.py:~510`). There is no check
  that today's candles exist, no retry, no lock and no once-per-session rule. If it fails it reports an error
  and ends (`jobs.py:~558`).
- Downstream jobs also run on fixed clocks whatever the scan did:
  `brain_nightly` 15:50 (`scheduler.py:340-343`), `daily_summary` 16:00 (`scheduler.py:204-207`),
  `brain_daily_check` 16:20 (`scheduler.py:376-380`).
- The record of the last scan is the file `.last_scan.json`, holding the current session only
  (`heartbeat.py:68-80`, written at `jobs.py:~519`).
- Nothing in this path writes a database table, so there is no scan history (that is #260).

## 3. Proposed behaviour (already implemented locally, not committed)

- Branch `fix/candle-readiness-scan`, worktree `D:/machine learning/candle-ready-wt`, base `193848b`
  (older than current main `2f0696d7`; a rebase will be needed and is not done).
- State: uncommitted, not pushed. 21 files changed in total including docs; 15 code files per the issue.
- Diff identity. The issue (#316 comment of 2026-11-20 12:08 IST) records the code-only diff
  (`git diff -- backend frontend`) as sha256 `4eabac880bb4`. I recomputed it read-only on 2026-11-26 and got
  `da987241d354`. They differ, so either the worktree changed after that comment or the hash was computed another way
  (line-ending warnings appeared for the new files). Unverified which; recompute with the issue's exact command
  before the owner approves anything.
- Review status: reviewed independently, read-only (Codex review 2026-11-20 gave three findings, all fixed with tests
  written first; a separate independent review on 2026-11-25 confirmed the capabilities listed below). The owner has
  not approved. Gaps that review named are #353 and #360, both gated.
- Tests recorded on the issue: full backend suite `6091 passed, 100 skipped, 1 xfailed`, 0 failed (2026-11-20). Not
  re-run for this document.

What it does:

1. Readiness check, read-only (`services/scan_readiness.py`, new). Target session = today once 15:40 IST has passed.
   - waiting: the benchmark index, or every stock the scan scores, has no bar for the session.
   - partial: some stocks are missing. The scan runs, and the record names them (up to 20; the count is exact).
   - complete: everything required is in.
   No new coverage threshold is invented; that rule belongs to #279.
2. While waiting, the strategies do not run, so no signals or orders come from yesterday's bar.
3. Retries every 5 minutes (`SCAN_RETRY_EVERY_MINUTES`) from 15:00 to the deadline 17:00 IST
   (`SCAN_RETRY_DEADLINE_HOUR/MINUTE`), then stops with one alert and never scans late (`scheduler.py` +
   `config.py` changes).
4. Restart recovery: a one-off check 60 seconds after the worker starts.
5. One scan per session: a Postgres advisory lock on its own connection (`workers/scan_claim.py`, new); a finished
   session is never re-scanned; a scan cut off part-way is marked interrupted with one alert and is not re-run (to
   avoid duplicate signals or orders).
6. Session state lives in the existing record file, now written atomically. No table, no migration.
7. Downstream gating: `brain_nightly` (and the brain strategy chained to it), `brain_daily_check` and `daily_summary`
   run only once the scan is finished. Normal day: unchanged times. Late prices: held, then run in order. No prices
   by 17:00: summary and health check still run; the brain is skipped for the day.
8. Manual scans ("Scan all", the CLI `scan`) use the same lock, price check and once-per-day rule; a refusal is HTTP
   409 (CLI exit 1). Scanning one ACTIVE strategy by hand is refused, because the daily scan already scores it.
9. Settings page shows the state in plain words (`frontend/src/pages/Settings.tsx`).

Not changed: sizing, stops, limits, drawdown, order placement code, `services/engine.py`, strategies, brain modules
(`git diff --stat` on `brain/`, `engine.py`, `horizon_nightly.py` in that worktree is empty, checked 2026-11-26).
All the behaviour changes move toward caution, but they change trading timing, so they need owner approval before
`main`.

## 4. Open owner decisions

- O1. Approve the behaviour change (scan waits; brain and summary held; brain skipped on no-price days).
  Recommended: yes.
- O2. Owner re-run of an interrupted or given-up day. Recommended: add later as a small admin action.
- O3. Keep the scan record as a file, or move it to a table (`scan_sessions` or the #260 `scan_runs`). Recommended:
  keep the file for now (no migration), add a table only if scan history is wanted.
- O4. Timing: first scan stays 15:45; a 16:15 target and evening or morning recovery slots wait for measured
  candle-arrival times. Recommended: measure first. Unverified: no arrival data is in this PR.
- O5. #353 (a stock missing today's candle can still be scored from yesterday in a partial scan and in the 15:42
  watchlist prediction): needs a narrow change to frozen files. Gated, post-trial.
- O6. #360 (duplicate signals on a re-run): gated, post-trial. #316 avoids it by never re-running a session.
- O7. Manual scan-all can run a deferred nightly brain inside the API request (slow), and a manual scan after the
  deadline marks the session gave-up with the same single alert (both from the review record).
- O8. Rebase onto current main before commit (base `193848b` is behind `2f0696d7`).

## 5. Acceptance evidence (what proves it, pass or fail)

| # | Criterion | Evidence on the issue / local branch |
|---|---|---|
| 1 | No scan from yesterday's bar when today's is missing | `test_scan_readiness.py` (10 tests), recorded as written failing first |
| 2 | Retries to 17:00 IST, one alert, never a late scan | `test_scan_retry_recovery.py` (14 tests) |
| 3 | Restart recovery within the window | same file |
| 4 | One scan per session, no duplicate signals | same file and `test_manual_scan_safeguards.py` |
| 5 | Brain, health check and summary wait for the scan; run once each; skipped brain on no-price day | `test_scan_followups.py` (9 tests plus 3 from the review fix) |
| 6 | Manual paths use the same safeguards | `test_manual_scan_safeguards.py` |
| 7 | No frozen file, risk rule or migration changed | stated on the issue; diff stat on frozen areas empty (verified 2026-11-26) |
| 8 | Whole suite green | `6091 passed, 0 failed` on 2026-11-20 (recorded, not re-run) |

Before merge, still to do: rebase, re-run the full suite on the rebased code, recompute the diff hash, owner approval.

## 6. Interaction with h05 (must be preserved)

- The h05 lane has its own readiness rule and schedule, separate from the scan: it records the latest closed session
  only once the NIFTY bar exists and at least 90% of its frozen universe has a candle, retries until 09:00 IST next
  day, then marks the session missed (`brain/lanes/h05_job.py:~8-20`, `SCHEDULE` line 48:
  mon-sat at 07:30, 08:30, 18:30, 20:30, 22:30). It writes only `h05_*` tables, takes its own database lock, and
  never trades.
- #316 must not touch it. Verified: the local diff has no change under `brain/` (empty stat). Preserve: (a) h05 keeps
  its own 90% rule and 09:00 deadline, and does not wait for the 15:45 scan; (b) the scan's 17:00 deadline and
  advisory lock are separate from h05's lock; (c) the scan's "partial" rule (no new threshold) must not be read as
  h05's 90% rule, which stays the sealed protocol's rule.
- The horizon nightly job (`services/horizon_nightly.py:50`, 17:30, 19:30, 21:30 IST, off by default) is also not
  gated by #316. Its first pass at 17:30 comes after the 17:00 scan deadline, so on a late-price day the scan has
  finished or given up before it runs. Unverified by test; worth one test at build time.

## 7. Risks and rollback

- Rollback: no migration, so reverting the commit restores the old fixed-time behaviour. The leftover state is the
  record file `.last_scan.json`; the old code reads it with the same key names for the fields it already used
  (unverified: the new state fields are extra keys; confirm old readers ignore them).
- Main risk: a late-price day delays the brain and summary. That is the intended caution; a bug in the gate could
  skip the brain on a normal day. The normal-day test (times unchanged) covers it.
