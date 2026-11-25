# Feature 2: Today, Discover and Scanner (#227): status

Last updated: 25 Nov 2026 (IST). Source of truth: GitHub board (project 2) and the issues. This file is a summary; do not treat it as a record of decisions.

**Feature state:** open. Closure needs owner approval. Not deployed to production.

## Done (merged to main, or closed)

| Item | What | Evidence |
|---|---|---|
| #239 Discover filters | Buy list and top picks use a 5-completed-session window (provisional, subject to signal-contract check), one row per stock across strategies, owner-private books removed first | PR #497 merged 25 Nov 09:33 IST, commit 111581ed |
| #243 Market and sector context | Verification done; gaps moved to #281 | PR #487 |
| #238 (verification) | 5-day ideas tests and findings merged | PR #490 |
| G11 (under #486 / #281) | One canonical stored decision word on every screen; room limit on its own line | PR #499 merged 25 Nov 01:09 IST, commit f72f104a |

## Waiting for review or approval

| Item | Status | Next action | Owner action |
|---|---|---|---|
| #498 G10 plan percentages from Brain policy | Open PR, self-review posted | Independent review of fixture-guard error and alias change in replay_scoring.py | Approve review and merge |
| #281 Requirements | Review; decisions recorded | Owner sign-off on section 8 items | Sign off |
| #316 Candle readiness | Review; independent read-only review done | Owner approval | Approve |
| #326 5D/10D/15D flags | Review | Not re-checked this session | Review |
| #240 Quotes and charts | Review | Chart date labels (G7) and NaN chart (G8) still open | Review |
| #242 Brain evidence / WATCH | Review | Not re-checked this session | Review |
| #360 Duplicate signals on re-run | Review; gated | Post-trial | Decide timing |

## In progress

| Item | Status | Blocker |
|---|---|---|
| #227 Feature | Open, In Progress | Owner closure approval |
| #238 5-day ideas across screens | G9 open | Frozen-file approval (see G9 below) |
| #241 Plan and holding-period labels | In progress | Depends on G9 decision |
| #416 Trading-rule numbers from backend | Merged part; G10 fixed in #498 | Merge #498 |
| #328 Model data feed design | In progress; model card PR #496 under separate review | Separate Core Platform review |
| #353 Stale candle scoring | Gated | Post-trial |
| #357 Candle-fetch failure reporting | In progress | Not re-checked this session |

## Not started

| Item | What | Blocker |
|---|---|---|
| #260 Daily candle scan and rankings | Remaining: scan history (migration), scores and ranks per stock, 5-day rankings, versioned inputs, out-of-sample comparison | #316 approval; gated bugs #353, #360 |
| #310 Saved screens and watchlist digest | Planning only | Not started |
| #356 Test scenarios for 5D flow | Backlog | Not started |
| #358 Telegram retries and alert record | Backlog | Not started |
| #486 Stale picks, undated or 0% numbers | Partly covered by #497 and #499 | Remainder not checked |
| #385 5D and 15D model view, admin dashboard | Ready. Owner approved a read-only admin dashboard | Not started |
| Chart missing-data markers | Owner approved | Not started |

## Blocked on owner approval (frozen files)

| Item | Proposal | Needs |
|---|---|---|
| G1: missing breadth or VIX keeps market DEFENSIVE | Ready. Changes `brain/modules/m10_market/judge.py` | Trial-freeze approval |
| G9: 5-session model shows 5D | Ready. Changes five frozen files and needs a migration (`brain_decisions.prediction_horizon_days`) | Trial-freeze approval and migration approval |

Proposal text: scratchpad `g1-g9-proposal.md` (not in repo).

## Gated until after the trial

#341, #353, #354, #355, #360.

## Owner decisions still open (from #281 section 8)

1. Strongest-sectors gate: on by default, and how many sectors.
2. Maximum BUY age (5 completed sessions is provisional; check against signal contract).
3. Owner and member see the same word when only the test portfolio's room held the idea back. Decision recorded (canonical word); confirm the owner-visible change.
4. What a position with no price shows (G6).
5. Breadth or VIX missing: keep DEFENSIVE (decided) and wording.
6. Horizon label for a 5-session model (decided: 5D; plan horizon separate).
7. Chart missing-data markers (decided: only expected sessions with unavailable validated candles).
8. Admin model view scope (decided: read-only dashboard, #385).

## Secret scans

Pinned gitleaks (v8.21.2) clean on PR ranges for #497, #498, #499. Full-history scan shows 11 generic-key matches in old fixtures and hash files, not from this work. Discrepancy with CI secret-scan on main needs checking.
