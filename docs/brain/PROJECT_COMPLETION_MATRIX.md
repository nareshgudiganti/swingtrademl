# PROJECT_COMPLETION_MATRIX (authoritative, as of 2026-11-07)

Objective: finish development by 2026-11-30; controlled model experiments in December. Priorities: P0 trading safety, sealed evidence,
database correctness, production stability; P1 Phase B, Amendment 3, SX5, November release readiness; P2 reliability reporting, UI,
backups; P3 future work. Nothing below is pushed, merged, signed, tagged, deployed or trained. `origin/main` = `cbdb3f6`.

Status words: **MAIN** = already on `origin/main` (checked by ancestry, file names or blob content); **BRANCH** = built and tested on a
local branch only; **INCOMPLETE** = work remains; **DEFERRED/DROPPED** = decided.

## 1. Branch count reconciliation (why the numbers disagreed)

`git rev-list --count origin/main..branch` ("ahead") counts every commit, including merge commits and commits that are already on
`main` under a different SHA (PR merges rewrite commits). `git cherry origin/main branch` counts only patches not present on `main`
("unique"). A content check (blob compare) then shows whether even those are already on `main`. The authoritative number is the last column.

| Branch | "Ahead" (rev-list) | "Unique" (cherry) | Real work not on main |
|---|---|---|---|
| change/open-positions-portfolio | 10 | 6 | **0** (Open positions screen `79ef8b2` identical on main; rest is the table-rename `4de482a`, an old WIP commit and audit notes; archive) |
| change/stock-page-clarity | 7 | 4 | **0** (UI and risk code already on main; contains `4de482a`; archive) |
| change/live-quote-snapshot / price-snapshot-main | 2 / 1 | 2 / 1 | **0** (superseded by main's newer `quote_snapshot.py`; drop) |
| rc/combined, rel/int, rel/telegram-status-log | 21, 7, 2 | 10, 3, 2 | **0** (old integration copies; superseded) |
| change/phase-b-finish, lab-start-wrapper, amendment-3-implementation, amendment-3-draft | 2, 2, 1, 1 | 2, 2, 1, 1 | included in `release/nov-completion` |
| change/sl-mid-universe-snapshot | 3 | 3 | 2 patches → `change/amendment-3-mid-snapshot` (D11); 1 (`c59e4c9`) → `pr/15d-baseline-readiness` |
| release/nov-completion | 32+ | n/a | PR-1 (see section 3) |
| feature/prediction-reliability | 5 | 5 | 4 (one duplicate of `783c3dd` dropped) → `pr/prediction-reliability` |
| fix/143-brain-seal | 2 | 2 | 2 → `pr/brain-seal-weekly-report` |
| change/telegram-status-log | 2 | 2 | 2 → `pr-hold/telegram-status-log` (HOLD) |
| change/offsite-backup-drill, scoreboard-verify, lists-slide | 1, 1, 1 | 1, 1, 1 | 1 each → PR-5, `pr/scoreboard-verify`, `pr/lists-slide` |
| change/brain-enabled-default-on | 1 | 1 | **0** (dropped) |
| feat/td-protocol-v1, feat/td-benchmarks | 1, 1 | 0, 0 | **0** (already on main) |
| td-protocol-v2 draft, 10d-baseline-analysis | 1, 1 | 1, 1 | 10D deferred; archive, never merge |

No duplicate work: every unique patch has exactly one proposed PR; duplicates are named as dropped.

## 2. Matrix

### P0: safety, sealed evidence, database, production stability

| Feature / experiment | Where | Exact outstanding work | Tests / evidence | Proposed PR | Blocking deps | Owner approval |
|---|---|---|---|---|---|---|
| Paper mode, real-orders switch, brain stage | MAIN | none | read-only prod GETs 2026-11-07: paper, real orders `enabled=False`, stage `shadow`, 20% ceiling, 8 positions, 25% sector, 15% halt | none | none | none |
| `TESTING_NO_LIMITS` (testing mode loosens limits when on) | MAIN (code), prod value inferred OFF | confirm directly on droplet: `grep TESTING_NO_LIMITS /root/app/.env` (print only the flag) | inferred from 60 ideas blocked at "room ₹18,672" (only fits the 20% ceiling); no endpoint exposes the flag | none | none | owner runs the one command |
| Seal of the blind trial (leak tests) | MAIN, but test fix `783c3dd` NOT on main | seal-leak test fails on clean main without it; included in PR-1 and PR-2 | fails on main, passes with `783c3dd` (4,759-test suite includes it) | PR-1 | none | merge |
| Weekly report keeps brain slot out of Bot results (sealed) | BRANCH | merge | 33 passed incl. planted-leak tests; file not frozen | `pr/brain-seal-weekly-report` (`8c491aa`, `0dbf9f5`) | needs `783c3dd` (PR-1) | merge |
| Telegram SELL alert log (touches `execution.py`) | BRANCH, **ON HOLD** | none for safety; merge only after experiments start | exit path proven SAFE: 29 new tests, mutation check, 96 related tests pass | `pr-hold/telegram-status-log` (`98c42da`, `26dd838`, `395f9b9`) | none | owner (edits order path) |
| Database migrations | MAIN | none; new branches add none except notiflog1a2b3 (hold PR) | one head `corpact1a2b3`, 58 revisions, no dangling links | none | none | none |
| Company-filing table rename `4de482a` | DROPPED | **never merge** (edits an applied migration; would break the company tab on prod); a forward migration would be needed if ever wanted | audit by agent J | none | none | none |
| Secret scanning (gitleaks) | CI only | cannot run locally; runs when a branch is pushed | NOT RUN | n/a | needs branch push | owner authorises push |
| Deploy window and CI gates | MAIN | weekday 09:00-16:30 IST refused; every merge to main deploys | docs/DEPLOY.md | n/a | none | owner merges after CI green |

### P1: Phase B, Amendment 3, SX5, November release readiness

| Feature / experiment | Where | Exact outstanding work | Tests / evidence | Proposed PR | Blocking deps | Owner approval |
|---|---|---|---|---|---|---|
| Phase B (B1, B2, B3), protocol, finish tool | BRANCH `release/nov-completion` (`2fc8882`) | sign protocol; merge; tag `phase-b-completion-v1`; written "start"; run B1→B2→B3 from 2026-11-09; record by 2026-12-04 | full suite 4,821 passed, 31 skipped, 0 failed on `2fc8882`; 190 focused; 9 blob ids match; `phase_b.py` identical to tag | **PR-1** (combined) | sign by 2026-11-08 | **sign, merge, tag, start** |
| Phase B price-data disclosure | BRANCH (in PR-1) | none (all price steps disclosed; impact negligible 0.075% of label days; feature channel untestable while sealed) | `phase_b_anomaly_impact.md` | PR-1 | none | covered by signature |
| Command forms in the protocol (3 traps fixed in text) | BRANCH (in PR-1) | none; `phase_b_finish` default root bug left unfixed (blob-bound), use `--root .` | dry-run verified | PR-1 | none | covered by signature |
| 15D lab runner guard (date + Phase B enforced by runner) | BRANCH (in PR-1) | none | 24 new tests, CLI and direct call refused today | PR-1 | none | confirmed 2026-11-07 |
| Amendment 3 (`sl-protocol-v1.1`, ranking only) + D11 mid-cap snapshot | BRANCH (in PR-1) | sign: signed marker file with date; merge; tag `sl-protocol-v1.1` | 186 + 123 + 60 tests; frozen rules unchanged; no trial_freeze fingerprint | PR-1 | before 2026-12-05 | **sign, tag** |
| 15D lab (S0, S1, S2, S0M, S1M, S2M), one run each | BRANCH (in PR-1) | start from 2026-12-05 via wrapper only | wrapper refuses today (date, tags, marker) | PR-1 | Phase B record, Amendment 3 tag | owner starts |
| 15D baseline and readiness note | BRANCH | merge before 2026-11-09 or after Phase B ends (adds one ledger row, not a Phase B phrase) | 138 passed, 1 DB error also on main | `pr/15d-baseline-readiness` (`902f067`) | timing vs Phase B | merge |
| SX5 preparation (no training) | BRANCH (in PR-1) | sign the SX5 protocol; approval file (needs `code_commit`); separate training authorisation (2026-12-04 or later); refresh signing commit hash and protocol/matrix/lock hashes at signing | 209 related tests; hash sheet v5; driver `scripts/sx5_run.py` dry-run default | PR-1 | signing machine for matrix hash | **sign; later authorise training** |
| SX10, 10D, `td-protocol-v2` | DEFERRED | none; archive drafts, never merge | 10D history test failed (-0.34%/trade) | none | none | none |
| 5D evaluation (h05 run 1) | MAIN, running | run 2 and 3 started by hand after 2027-01-28; TMCV expected (new listing, <252 bars, scorable ~17-18 Nov); obv_slope serving fix decision after trial | prod report: 5/5 sessions, 0 missed; note `h05-tmcv-and-obv-slope-note.md` | none | none | post-trial decision |
| December runbook and helper scripts | BRANCH (in PR-1) | none | 51 static tests; scripts verified; 3 command traps documented | PR-1 | none | none |
| Release readiness checklist | partial | secret scan (CI); backup recovery; scheduler reliability and data freshness on prod (read-only report); prediction reproducibility (Phase B dry runs only) | backend 4,759 pass; frontend 999 pass + build + tsc; e2e 110/111 (flaky only under load); migrations single head | final report | PR-1 CI | none |

### P2: reliability, UI, backups, nonessential

| Feature | Where | Exact outstanding work | Tests / evidence | Proposed PR | Blocking deps | Owner approval |
|---|---|---|---|---|---|---|
| Prediction reliability report (read-only CLI) | BRANCH | merge | 34 passed incl. DB; no route, no migration, seal applied | `pr/prediction-reliability` (`b3757e9`, `17c28c4`, `d87333a`, `d486097`) | needs `783c3dd` (PR-1) | merge |
| Scoreboard independent tests | BRANCH | merge | 140 passed, 1 expected failure (empty-range defect) | `pr/scoreboard-verify` (`aed2a7a`) | none | merge |
| Scoreboard CLI circular-import fix | BRANCH | merge | 19 passed; new test fails on main, passes with fix; no computation changed | `pr/scoreboard-cli-import-fix` (`54c3de7`) | none | merge |
| h05 job docstring ("not wired" is stale) | BRANCH | merge (comment only; not frozen; protocol hash built from constants) | 19 passed | `pr/h05-job-docstring` (`883da32`) | none | merge |
| Stock lists as one table (lists-slide) | BRANCH | merge after screen check (slides and toggle kept; conflict resolved) | tsc 0 errors, build pass, 998-999/999 vitest | `pr/lists-slide` (`21a5491`) | none | merge after visual check |
| m09 learning speed fix (`/brain/learning` timeout) | BRANCH, **BLOCKED by trial freeze** | `m09_learn/learn.py` is trial-frozen; needs `scripts/approve_trial_change.py` | 90 + 39 passed; rows byte-identical to old implementation | `pr/m09-learning-speed` (`7036c2a`) | owner approval flow | **owner approval** |
| Offsite model backup + restore verifier | BRANCH | owner's rclone setup; workflow change kept disabled until then | 7 passed | PR-5 | rclone | merge |
| Open positions screen | MAIN | none; archive the local branch | `79ef8b2` identical | none | none | none |
| Stock page clarity, price snapshot, live quote, brain-enabled-default-on | DROPPED / archive | none | agent J audit | none | none | none |
| Housekeeping (about 50 merged worktrees, 15 old branches) | INCOMPLETE | remove merged zero-change worktrees only; archive tags; delete nothing else | agent K list | none | none | **owner approval** |

### P3: future

| Item | Status | Note |
|---|---|---|
| Multi-user portfolios B1 | design only (P0 security part on main) | parked |
| Company/news tab NSE access check (cn2), Today-clarity visual check | MAIN, unverified details | check on screen, no code planned |
| New experiments, new model families, 10D retry | none | frozen until after December evidence |
| Features already on MAIN, no work left | Stock Compare, Company tab, real-holdings manual orders (switch off), Plans manager (owner switch off), New-look switch, tv22 reserved slot, 20% stressed cap, explanation layer, Observatory, manual test page, real-orders badge, beginner features | none |

## 3. PR plan and exact safe order

| # | PR | Contents | When |
|---|---|---|---|
| PR-1 | `release/nov-completion` (merge commit, never squash) | Phase B, Amendment 3 + D11, runner guard, SX5, December scripts, runbook, matrix, seal test fix `783c3dd` | after owner signs Phase B; weekends are free of the deploy window; must be before 2026-11-09 for Phase B |
| PR-2 | `pr/15d-baseline-readiness` | ledger row | before 2026-11-09 or after Phase B ends |
| PR-3 | `pr/scoreboard-verify`, `pr/scoreboard-cli-import-fix`, `pr/h05-job-docstring` | tests, import order, comment | after PR-1 |
| PR-4 | `pr/brain-seal-weekly-report`, `pr/prediction-reliability` | seal fix, read-only report | after PR-1 (needs `783c3dd`) |
| PR-5 | `pr/lists-slide`; offsite backup | UI, infra | after PR-1; backup after rclone |
| hold | `pr-hold/telegram-status-log`, `pr/m09-learning-speed` | order path, trial-frozen file | owner decision |

Every PR needs CI green including secret scanning before merge. Phase B runs from a clean worktree cut from the signed tag so PR work cannot disturb it.

## 4. Owner authorization needed (consolidated; recommended choice first)

1. Sign Phase B protocol by 2026-11-08 (recommended: sign). 2. Authorise pushing PR branches (not `main`) so CI and the secret scan run
(recommended: yes). 3. Merge PR-1 on 2026-11-08 after signing (recommended: yes) and run the four tag commands yourself.
4. Sign Amendment 3 and SX5 in November (recommended: yes). 5. m09 speed fix: approve through `approve_trial_change.py` or leave until after the trial
(recommended: leave until after the trial; the page timeout does not affect trading or evidence). 6. Telegram log: after experiments start.
7. rclone for the backup PR. 8. Housekeeping: remove merged worktrees, archive tags, delete nothing. 9. Confirm `TESTING_NO_LIMITS` on the droplet.
10. December fallback support for P0 only. 11. Calendar reminders. Items already decided on 2026-11-07 are not repeated.
