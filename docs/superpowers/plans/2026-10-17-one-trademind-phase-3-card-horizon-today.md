# One TradeMind, Phase 3: horizon selector now (3a), one card and Today later (3b)

**Status:** revision 2, for owner review. Owner approved Option C in principle with seven corrections (17 Oct). Nothing is built until this plan is approved. No push, merge or deploy without separate approval.
**Spec:** `docs/superpowers/specs/2026-10-16-one-trademind-design.md` sections 2 and 3; tasks oa13 (3a), oa12 and oa5 (3b).

## What I checked in the code (17 Oct, `main` 4f3cc19)
| Point in the review | What the code does today | Effect on the plan |
|---|---|---|
| 5-day model exists | True. The v1 models ask "+2% within 5 days". That is a research prediction, not a 5-day trading strategy | 5 days: "No supported trading strategy"; the 5-day predictions are labelled research, unvalidated |
| Horizon tabs | Swing Picks already has tabs 5 / 15 / 30 / 90 days; only 15 is live. There is no 1-day tab | 3a replaces these tabs with the shared selector and adds 1 day |
| Show only the final decision | The brain's `word` is already the word after the risk check (`downgraded_from` keeps the original). `finalWord()` then applies the owner's overrule | Already correct. 3a/3b add tests that pin it |
| No trading rules in the frontend | **Swing Picks computes the half-out level in the browser** (`Dashboard.tsx:49`, `FIRST_TARGET = 0.05`). Brain decisions carry entry, target and stop, but not a half-out level | Needs your decision for 3b (see Questions). 3a does not touch it |
| Today must not mix Paper and Real | Home's "Holdings needing attention" comes from the brain's run (the bot's paper book) | 3b labels it Paper and keeps My Zerodha out of Today |
| Real-money buy from an idea | No idea screen has a real Buy button. Opportunities has the paper testing buy only | 3b keeps it that way, with a test |
| "Test the local preview against production" | I cannot sign in to the live site. I can compare the new build with the current `main` on the same local data, and run read-only checks against the live API | After a deploy you approve: my read-only API smoke test plus your visual check on the live site |

## Phase 3a (now): shared horizon selector, availability and validation labels
Frontend only. Does not change any card, the brain, trading or the backend.

**Two separate labels per horizon:**
| Horizon | Availability (can it produce a trading idea?) | Validation (has that strategy shown evidence?) |
|---|---|---|
| 1 day | No supported trading strategy | — |
| 5 days | No supported trading strategy. Research predictions exist (+2% in 5 days), unvalidated, not a trading plan | — |
| 15 days | Available | **Experimental, unproven** |
| 30 days | No supported trading strategy | — |
| 90 days | No supported trading strategy | — |

Nothing is labelled "Validated". The labels live in one table in the code, so a horizon can later get its own model, evidence and status without redesigning screens.

**Rules for the selector:**
- Choosing a horizon with no supported strategy shows a plain message that no trading idea is available for it. It never shows 15-day ideas under another horizon's name.
- The 15-day ideas show the "Experimental, unproven" label beside the horizon.
- Used on Swing Picks now (replacing its four tabs). Built as one reusable component so 3b and Safe-now's card can use the same labels.

**Steps (tests first):**
1. Horizon table and labels: tests that every horizon has both labels, 15 is the only available one, nothing says "Validated", 5 days says research and unvalidated.
2. Selector component: tests that an unsupported horizon shows the "no supported trading idea" message and no idea rows; 15 shows the ideas.
3. Swing Picks uses the selector: tests and a browser check that the 15-day list and every figure are unchanged from today.
4. Checks: typecheck, unit tests, backend suite, build, permission tests, parity `--check` passes and `--strict` shows the same 16 documented gaps and no new one.
5. Browser: new build vs current `main` on the same local data, owner and non-owner, desktop and phone, in-app clicks into and out of Swing Picks, loading, empty and error states.
6. Independent review, fixes, PR for your review.

## Phase 3b (after B1 and Safe-now have merged)
- **One card:** Safe-now's idea card, with a compact view (Today, Discover) and an expanded view (stock page). No second card.
- **Final decision only:** the card's signal is the final word. A draft model ranking may appear only as "Model ranking: 88/100, not a probability".
- **No buy plan for WATCH, WAIT or AVOID:** "No trade plan shown because the final decision is WATCH".
- **No trading rules in the frontend:** entry, stop, target, last day and sizing come from the backend. Half-out per your answer below.
- **Evidence:** only approved historical evidence with dates, sample size and limits. Nothing from the sealed brain trial. A ranking is never turned into a chance of profit.
- **Today (order):** Market overview (condition, brain status, last updated) · Today's brain decisions (compact cards) · Paper portfolio summary (open positions, exposure, risk limits; labelled Paper) · Legacy ML Swing Picks as a link only, labelled "Research only, unvalidated". No real-money figures or buttons on Today.
- `/trademind/dashboard` and every other URL keep working.
- Same tests, checks, browser comparison, review and PR as 3a, plus permission tests for non-owners on Today.

## Not in Phase 3
Backend changes, new trading strategies or horizons, stock selection, trading rules, risk settings, the frozen trial, real trading, B1 and Safe-now themselves.

## Release checks (both parts)
- Before the PR: the new build compared with current `main` on the same local data; strict parity shows only the 16 documented gaps.
- After a deploy you approve: read-only API smoke test by me, and your visual check of the changed screens as owner and as a non-owner.
- Rollback: revert the merge commit (frontend only).

## Questions for you
1. **Half-out level (for 3b).** Swing Picks currently works it out in the browser (+5%), which goes against correction 4. The +5% half-out is part of the settled trading rules (CLAUDE.md), but the brain does not send the level. Choose:
   - (a) show "Not available" until the backend sends it, or
   - (b) a small read-only backend change so each decision carries its half-out level (a separate approval, since it touches the backend).
2. **Phase 3a:** approve building it now on a local branch?
