# Feature 3: Stock detail and trade plan (#228): status

Last updated: 25 Nov 2026 (IST). Baseline: `main` = eacbb42d (PR #502).
Source of truth: GitHub project 2 and the issues. This file is a summary. Verification levels:
**CODE** = read on main and/or run in this session; **PR** = PR state only; **DOC** = documentation only.

**Feature state:** open (#228 is Backlog on project 2; #282 requirements In Progress). Not deployed to production.
Closure needs owner approval. Feature 2 is #227 (Today, Discover and Scanner), not this feature.

## Requirements (from #282 section 6)

| ID | Requirement | State | Verification | Evidence / next action |
|---|---|---|---|---|
| A1 | One decision on Today, AI Analysis and Stock detail | Built (test names cited in #282) | DOC | Re-check after #499 and #506 merge |
| A2 | Score line ends on the decision's score and names its model | Built | DOC | `test_the_score_line_on_stock_detail_*` not located on main this session |
| A3 | One score rounding on every screen | Built | DOC | `fiveDayIdeaScreens.test.ts` not run |
| A4 | Same word on every screen (G3) | Code on main via PR #499 (merged 25 Nov 01:09 IST) | CODE | `live.ts` `shownWord` = `finalWord`; room note is separate (`ROOM_NOTE`). Independent post-merge review pending. Owner confirmation of the owner-visible change pending. |
| A5 | Idea list and plain answers read the same run (G3b) | Open gap | DOC | #238 w2 |
| A6 | Horizon shown is the horizon of the scoring model (G1) | **HOLD**: owner decision pending | DOC | Shared decision note: `docs/status/feature-228-g1-decision-note.md` |
| A7 | Plan percentages equal the plan's prices (G2) | #479 merged (shared plan numbers). #498 open for Brain-policy aliases. | CODE | See G2 below |
| B1 | TRADE shows buy zone, target, stop, last day; missing levels show "plan incomplete" | Built | DOC | `beginner_views._plan_in_order` on main |
| B2 | Non-TRADE shows no buy plan and no money figures | Built | DOC | `beginner_views.py:493-494`; no named test |
| B3 | "Out by" day = horizon counted in trading days | Built | DOC | `test_the_last_exit_day_on_stock_detail_*` not located |
| B4 | Held-back idea keeps levels, size zero | Built | DOC | #242 pinned test |
| B5 | 5-day score labelled as 5-day; plan as separate rule | Open | DOC | Depends on G1 |
| C1–C6 | Decision and explanation rules | Built (per #282) | DOC | Not re-run this session |
| D1 | Stale quote never shown as live | Built | DOC | `test_quote_snapshot.py`, `priceSnapshot.test.tsx` cited, not re-run |
| D2 | Stock page shows the date of a fallback close (G4) | Open | PR | PR #506 (not merged); overlaps PR #509 (see Overlaps) |
| D3 | Chart dates are India dates; no NaN chart (G5, G6) | Open | PR | G6 in PR #506 and PR #509 (both open). G5 not started. |
| D4 | Dated reader and M01 flag stale data | Built | DOC | `test_verify_246_data_freshness.py` cited |
| D5 | Scan after failed download does not plan from an old bar (G8) | **Design only, approved**. No code. Engine files frozen. | CODE | `services/engine.py` is on `backend/tests/trial_freeze.json`. Also #353 is gated until after the trial. |
| E1 | Admin sees decision trace and job status and data age | Built | DOC | Existing System and Jobs tests cited |
| E2 | Admin sees which model scored an idea (#385) | **HOLD** for expanded scope. PR #510 (read-only 5D/15D overview) is open. | PR | Expanded scope needs owner approval |

## Gaps

| Gap | What | State |
|---|---|---|
| G1 | 5-session score shown with a 15-day plan | HOLD. Owner decision and architectural clarification needed. Shared with Feature 2 G9. |
| G2 | Plan percentages from v1 settings, not the Brain policy | #479 (merged) made the trading-rule endpoint read the Brain policy. #498 (open) replaces the remaining hard-coded copies in `replay_scoring.py` with aliases of the same policy. Values are unchanged (8% / 4% / 5% / 15 sessions). Tests: 7 focused and 447 related tests pass on the #498 head (e9d508d). |
| G3 | One word per screen | Code on main (#499). Post-merge review pending. |
| G4 | Undated close | PR #506 (open). |
| G5 | Chart date label uses the browser time zone | Not started. |
| G6 | Chart prints NaN | PR #506 and PR #509 (both open, overlapping). |
| G7 | Coverage dates read candle times as UTC | Not started. Folded into the standard trading-date work (see #282 G5/G7). |
| G8 | Scan on stale data | Design packet only. No code until owner approval. |
| G9 | 4 pm bar expectation | Owner input needed: when the data provider publishes the day's bar. |
| G10 | Late and corrected candles not shown | Not started. |

## Overlaps and duplicates (must be resolved before merge)

- **PR #506 and PR #509** both change the stock page's chart states and dated close (`stockParts.tsx`, `ui.tsx`,
  `verify240.test.tsx`, `StockNew.tsx`). One must be rebased on the other, or one closed. Not decided.
- **PR #498 and PR #479** both touch the plan-numbers path. #479 is merged, #498 builds on it. There must be one
  authoritative source: `DEFAULT_POLICY` in `brain/modules/m08_decide/policy.py`.
- **PR #510 (#385)** builds the admin model view that #282 says to HOLD in its expanded form.

## Frozen files touched by this feature

- `backend/src/swing_trade_ml/brain/modules/m08_decide/policy.py`: on the frozen list. Read only by #498. Not modified.
- `backend/src/swing_trade_ml/brain/modules/m08_decide/engine.py`: on the frozen list. Not modified.
- `backend/src/swing_trade_ml/services/engine.py`: on the frozen list. G8 is design only.

## Owner decisions recorded (25 Nov 2026)

1. G1: HOLD. Explain the 5-session prediction horizon and the 15-day plan horizon. Coordinate with Feature 2 G9. No frozen-file change without approval.
2. G2: one shared implementation (`DEFAULT_POLICY`). Independent review of #498 assigned to Dev-2. Independence not yet verified: the author of #498 is not recorded in the handoff (all PRs show the owner's account). Verify from commit authorship before the review starts.
3. G3: canonical stock verdict, separate test-portfolio eligibility status. Review #499 against it.
4. Held-back ideas: historical or hypothetical levels may be shown only with an explicit conditional label. Never as active plans.
5. G4/G6: independent review of #506 assigned to Dev-4. Independence not yet verified (same reason as item 2). Also check overlap with #509 first.
6. G5/G7: standard exchange trading dates and Asia/Kolkata display timestamps.
7. G8: design only now. Gate not implemented. Engine files frozen.
8. G9/G10: explicit validation and audit records for delayed candles, duplicates and missing sessions.
9. Research horizons (10D and 15D): admin view only (the API already has `include_research`).
10. #385: expanded scope (six model slots, lane classification, versions, training information, validation results,
    evidence sufficiency, separate Brain observability) on HOLD until explicitly approved.

## Testing run in this session

| Check | Where | Result |
|---|---|---|
| `tests/test_plan_percentages_from_brain_policy.py` | PR #498 head e9d508d (detached worktree) | 7 passed |
| `tests/test_trading_rules_endpoint.py`, `test_plans_route_coverage.py`, `test_brain_replay_scoring.py` | same | 447 passed, 1 skipped |
| Frontend tests for #499 and #506 | not run | Not verified |
| Full backend suite | not run | Not verified |

## Not started or blocked

- G5, G7 and G10: not started.
- #389 stock identity and signal contracts: schema design for owner approval (not started here).
- The shared-contracts list for Features 1–3 is in the cross-feature execution queue (local file, not committed).
