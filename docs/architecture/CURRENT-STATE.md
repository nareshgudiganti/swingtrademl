# Current state: 2026-11-10

Written from `origin/main` `9deb26a` (2026-11-10). The authoritative project status is
`docs/brain/PROJECT_COMPLETION_MATRIX.md` (status updates dated 2026-11-09 and 2026-11-10). This file is a short
summary that points at it; if the two disagree, the matrix wins. Anything not confirmed from a document or git history
is marked **unverified**.

## What is on `main` and deployed

- **Production** runs from `main` on the DigitalOcean droplet (swingtrademl.com). Every merge to `main` deploys, after the
  tests pass and outside the deploy window (see `docs/DEPLOY.md` and `docs/OPERATIONS-AND-LAUNCH.md`).
  Rollback tag `v1` = `64fcb05` is a frozen reference only.
- **Paper only.** Matrix, read-only prod checks 2026-11-07 and owner check on the droplet 2026-11-09: `TRADING_MODE=paper`,
  `ALLOW_LIVE_TRADING=false`, `ALLOW_REAL_HOLDINGS_ORDERS=false`, `BRAIN_ENABLED=true`; `TESTING_NO_LIMITS` and
  `LANE_SHADOW_ENABLED` unset (code defaults are off). The model registry was not checked by that step.
- **Brain** modules M00-M18 are live in practice (shadow) stage since 2026-10-04: it records ideas and their outcomes and
  places no orders. Stage is `shadow` (matrix, 2026-11-07 read-only check).
- **November release merged and deployed** (PR #151 and the smaller PRs): Phase B finish tool and protocol, Amendment 3
  tooling, 15D lab runner guard, SX5 preparation (no training), December runbook, activation-readiness audit, protocol
  wording fixes. Deploys of `c4a79ba` and `47350a9` succeeded (matrix 2026-11-09).
- **After that, on `main` up to `9deb26a`:** matrix status updates (#173, #174), off-machine model backup and restore
  verifier (code merged; the model copy stays OFF until the owner creates `/root/.backup-models-enabled`, see
  `docs/BACKUP-OFFSITE.md`), Dependabot holding back frontend major bumps, h05 watch workflow (daily Telegram check of the
  5-day report), daily-check watch with a simulate input, the December readiness check
  (`docs/brain/DECEMBER-READINESS-CHECK.md`), a tv27 proposal marked NOT FOR MERGE, and small frontend dependency bumps.
  Whether each of these has finished deploying to the droplet is **unverified** (check Actions, "Deploy to production").
- **Also on `main`** (matrix P3 list): Open positions screen, Stock Compare, Company tab, manual real-holdings orders
  (switch off), Plans manager (owner switch off), New-look switch, tv22 reserved slot, 20% stressed cap, explanation layer,
  Observatory, Groww Tracker with edit, beginner features.

## Trial seal and freeze

- The blind brain trial is sealed: frozen files change only through `scripts/approve_trial_change.py`. Reports keep the
  brain slot out of the "Bot results" while sealed (`pr/brain-seal-weekly-report`; its merge status is **unverified**).
- Development freeze: feature development ends 2026-11-30 (matrix objective), testing-first after. Held until after the
  freeze: Telegram SELL-log changes, the m09 speed fix, 10D, unapproved lanes, worktree cleanup.

## Experiments and signatures

| Item | State on 2026-11-10 (source: matrix) |
|---|---|
| Phase B protocol | **Signed 2026-11-09** (merge `fee8d98`, PR #172); annotated tag `phase-b-completion-v1` points at it. Gates G1-G14 passed on branch `phase-b-run`. |
| Phase B runs B1, B2, B3 | **B1 not run yet** (ledger has 0 candidate rows). All three due by **2026-12-04**. |
| Amendment 3 (`sl-protocol-v1.1`, ranking only) | **Unsigned.** Needs D1-D10 decisions, a signed marker file and tag before **2026-12-05**. |
| SX5 sector challenger protocol | **Unsigned**, due by 2026-11-30. Built and tested on synthetic data only, never trained; training needs a separate written owner authorisation and cannot start before 2026-12-04. |
| 5D (h05 lane, models 2, 16, 17) | Run 1 **in progress** (2 Nov to 28 Jan 2027); INCONCLUSIVE until about 40 matured days. Runs 2 and 3 are started by hand after 2027-01-28. |
| 10D | **Failed** (td-protocol-v1, about -0.34% per trade) and **deferred**; no v2, no retrain, no 10D slot. |
| 15D selection lab (S0/S1/S2, S0M/S1M/S2M) | Tooling done; **starts 2026-12-05** at the earliest, after the Phase B record and a signed, tagged Amendment 3. Runner refuses earlier. Shadow lanes off. |
| Activation guard (design steps 4-7) | Not approved, nothing built. Passing tests never authorises activation. |
| HINDUNILVR / BAJAJELEC | Excluded from Phase B (owner decision 2026-11-07, final). |

## Release controls (all off, per code defaults)

`ALLOW_SIGNUP`, `ALLOW_REAL_HOLDINGS_ORDERS`, `ALLOW_LIVE_TRADING` default to false in `core/config.py`. Plans manager and
New-look are owner switches (off). The names `ALLOW_CUSTOMER_SCREENS` and `ALLOW_MODEL_PROMOTION` were **not found** in the
code on `9deb26a`: treat them as planned, not existing (unverified meaning). Payments and billing are not built.
See `docs/OPERATIONS-AND-LAUNCH.md`.

## Known issues (still true, verified against matrix unless noted)

- **`obv_slope` train/serve mismatch** for 5D models 2/16/17 (prod serves it differently from training since 2026-10-05).
  Inside the sealed trial, NOT fixed; decision after the trial. Note: the older entry in this file that said an `obv_slope`
  train/serve fix shipped in `fcaef35` conflicts with the matrix; the matrix is the later source.
- **Seal-leak test fix `783c3dd`**: the matrix says it was needed on main; it is in the release that has since merged
  (whether it is on `main` is **unverified**; confirm with `git branch -r --contains 783c3dd`).
- **`/brain/learning` page can time out** (m09 speed fix is blocked by the trial freeze; trading and evidence unaffected).
- **Telegram SELL alert log** not merged (on hold; touches order path).
- **Off-site (Google Drive) database backup not set up**, droplet disk filling, Telegram token a single point of failure,
  GitHub may switch off scheduled workflows after 60 days without commits, restore drill not re-run since its fix: all from
  `docs/brain/DECEMBER-READINESS-CHECK.md` (2026-11-10; the 60-day date is its own calculation and unverified).
- **M06 meta-model** below break-even; ideas often WAIT (expected). **Gap #3** adjusted price layer deferred (split-check
  clean 2026-10-05; not re-verified since). Service 1 gap list: `docs/architecture/architecture-gaps.md`.
- **Removed as no longer current:** the 2026-10-09 "brain recorded no ideas" bug. Its fix (`blocked_by_risk_limit`) is in
  `strategies/brain.py` and `brain_golive/compare.py` on `main`, but whether it behaves correctly on prod today is
  **unverified**; the matrix does not list it as open.

## Next exact tasks (owner; from the matrix)

1. Run B1, B2, B3 from the clean `phase-b-run` worktree by 2026-12-04.
2. Decide Amendment 3 D1-D10; sign, merge, tag `sl-protocol-v1.1` before 2026-12-05.
3. Sign the SX5 protocol by 2026-11-30 (training separately authorised, 2026-12-04 or later).
4. Set up the off-site backup (`docs/BACKUP-OFFSITE.md`).
5. Daily and weekly checks: `docs/OPERATIONS-AND-LAUNCH.md`.

## Doc pointers

- Matrix (authoritative): `docs/brain/PROJECT_COMPLETION_MATRIX.md`; December: `docs/brain/DECEMBER-RUNBOOK.md`,
  `docs/brain/DECEMBER-READINESS-CHECK.md`
- Operations and launch: `docs/OPERATIONS-AND-LAUNCH.md`
- Solution vision: `docs/architecture/TRADEMIND-SOLUTION-OVERVIEW.md`; gaps: `docs/architecture/architecture-gaps.md`
- Roadmap: `docs/brain/ROADMAP.md`, `docs/ROADMAP_TRACKER.md`; testing: `docs/brain/TESTING.md`
