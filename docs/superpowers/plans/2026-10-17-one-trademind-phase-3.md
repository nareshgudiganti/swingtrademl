# One TradeMind, Phase 3: one recommendation card, horizon selector, Today — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** PLAN ONLY, for owner review. Nothing is built until the owner approves it. No push, merge or deployment without separate approval.

**Goal:** Every stock recommendation shows the same card. A 1/5/15/30/90-day selector says honestly which horizons have a model. Home and Swing Picks become one Today page. No existing URL breaks and nothing in the frozen paper trial changes.

**Architecture:** Mostly frontend. It reuses the building blocks already built and reviewed on `feature/beginner-safe-now`: `IdeaCard`, `MoneyAtStake`, `StockBrief`, `UpcomingEvents` and the read-only `/api/v1/beginner/*` endpoints. One new read-only endpoint lists each horizon's state. There is no database change. Home.tsx and Dashboard.tsx stay in the tree, unrouted, until Phase 6 (oa10) removes them.

**Tech Stack:** React 18 + React Query + react-router, Vitest `renderToString` tests, FastAPI read-only session (`get_readonly_db`).

**Spec:** `docs/superpowers/specs/2026-10-16-one-trademind-design.md` §1 (Today), §2 (recommendation card), §3 (horizons), §8 (acceptance oa5, oa12, oa13), §9 (phases), §10 (owner decisions 6, 7, C1). Atlas tasks: oa12, oa13, oa5. bx6 is already built.

**Branch:** `feature/one-trademind-phase-3`, in a new worktree `.claude/worktrees/one-app-p3`, created from `feature/beginner-safe-now`. That branch was rebased onto `main` 4f3cc19, so it includes Phase 2. If the beginner branch merges to `main` first, branch from `main` instead.

## Global Constraints

- **Frozen trial (from 2026-10-14):** no change to the brain, its modules, `horizon_days`, scoring, which stocks are picked, orders, sizing, stops, limits or config. The selector is a display filter only. Choosing a horizon never starts a brain run, never calls `/brain/why`, and never writes anything.
- **Honest states (spec §3, decision C1):**
  - **Experimental, unproven** applies to 15 days today.
  - **Unavailable** applies to 1, 5, 30 and 90 days. These options are disabled and say "No model for this horizon yet".
  - **Validated** only appears when a frozen protocol for that horizon passed. Today none has.
  - The words "validated", "proven" and "profitable" never appear next to a signal unless that state is true.
  - The word "probability" never appears.
  - A % chance appears only through `honest.tsx` (`honest_score`).
- **URLs (decision 6):** every current `/trademind/*` URL keeps working, including `/trademind/dashboard`. Owner-only access stays as it is.
- **Overrule:** the word shown is always `finalWord(d)` (live.ts:25, the owner's overrule wins). The backend uses `strategies.brain.effective_word`.
- **Plain English.** Missing data says "Not available" and why, never 0 or a blank. Paper and real are never summed (bx2, Phase 2).
- **Do not edit:**
  - `MyHoldings.tsx`
  - anything under `backend/` except the files this plan names
  - `client.ts`, except one optional typed call in Task 6
  - `honest.tsx`
  - classic `pages/*` outside `trademind/`
- **Tests:**
  - Backend: `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=$PWD/src <venv python> -m pytest`, run from `backend/`.
  - Frontend: run `npx vitest run`, `npx tsc --noEmit -p .`, `npm run build` and `node scripts/classic-parity.mjs --check` from `frontend/`.
- **Deploy window:** only after 16:30 or before 09:00 IST.

## Review Focus

1. **`?h=` set to a bad or unavailable value** (`?h=7`, `?h=90`, `?h=abc`): the page falls back to 15. It never shows an empty list as if no ideas exist. → Task 3 test.
2. **No brain run today, or the brain is switched off:** Today shows the existing `BrainGate` / "no run yet" state, and the market and portfolio parts still show. The page never crashes or shows a blank. → Task 5 test.
3. **A non-owner opening `/trademind/dashboard` or Today:** they never see owner-only cards (Watchlist links, Control, approvals) and never see real-money figures. → Task 5 test.
4. **An overruled idea:** the card shows the owner's word, no buy plan and no money. Today's counts use the same word. → Task 2 test.
5. **A phone-width screen:** the selector and cards stay within the screen, with no sideways scroll. → Task 7 browser check.

---

### Task 1: Close the card's open items before it is used (wiring prerequisites)

**Files:**
- Modify: `frontend/src/trademind/beginner/IdeaCard.tsx`, `MoneyAtStake.tsx`, `StockBrief.tsx`, `StockSearch.tsx`, `BottomBar.tsx`, and their tests
- Modify: `backend/src/swing_trade_ml/services/beginner_views.py`, `backend/tests/test_beginner_money.py`

**Interfaces:**
- `money_at_stake(...)` adds `"half_out_pct": float` (from `settings.ML_FIRST_TARGET_PCT`) and `"half_out_applies": bool` (false when the position is below `settings.SCALE_OUT_MIN_POSITION_INR`).
- IdeaCard accepts `actions?: ReactNode` (a slot for page-specific buttons such as the tester buy).

Each of these comes from a deferred item in the beginner build record:
- [ ] **Half-out level:** "+5%" is read from `money.half_out_pct`, never typed. When `half_out_applies` is false the card says "Too small to sell half — all sold at target or stop". Test: a ₹10,000 position shows that line.
- [ ] **Risk rule:** the "No shares allowed: <rule>" line names a rule only when the reason starts with the risk-check prefix the M07 module writes (find it in `brain/modules/m07_risk`). Test: "Large market cap" is never shown as a rule.
- [ ] **Overruled ideas:** the reasons list is headed "The brain's own reasons" when `overruled_word` is set. Test.
- [ ] **Keys:** React keys include the index. Signed ₹ shows as "−₹300.00".
- [ ] **StockSearch:** Enter acts only while the list is open. Test.
- [ ] **BottomBar:** uses `resolveSection(path, owner)`. Test: a non-owner on an owner-only path gets no wrong active tab.
- [ ] Run all suites. Commit: `"Phase 3 prep: card open items (half-out from settings, risk rule prefix, overrule label, search/bottom bar fixes)"`.

### Task 2: One recommendation card everywhere (oa12)

**Files:**
- Modify (render only, no data or logic change):
  - `trademind/pages/Opportunities.tsx`: table rows and FeaturedCard → `IdeaCard compact`, with the tester-buy button passed in through `actions`, behaviour unchanged.
  - `Home.tsx` top ideas: replaced by Today in Task 5, so it is not edited here.
  - `Dashboard.tsx` PickDetail: replaced by Today in Task 5.
  - `StockDetail.tsx`: the decision block → `StockBriefForSymbol` (built on the beginner branch). It keeps the chart and everything else on the page.
  - `Positions.tsx`: holding decision block → `IdeaCard` (holding words, no buy plan).
- Not changed: `AIDecision.tsx` (a trace view, not a recommendation) and `Watchlist.tsx` (a list of symbols).
- Test: `frontend/src/trademind/card-everywhere.test.tsx`

**Interfaces:** consumes `IdeaCard({decision, money?, events?, compact?, actions?, horizonState?})`. `horizonState` comes from Task 3. Until then the card defaults to "Experimental, unproven".

- [ ] **Step 1: Failing tests.**
  - Render Opportunities, StockDetail and Positions with a fixture run. Each recommendation contains the card's marker (`data-card="idea"`), "model score", "a ranking, not a chance of winning" and "Experimental, unproven".
  - None contains "probability", "validated", "proven" or "profitable".
  - An overruled fixture shows the owner's word and no "Buy between".
  - The tester-buy button is still present on Opportunities for the owner and absent for others (same rule as today).
- [ ] **Step 2: Implement.** Replace the markup only. Keep every query, mutation, filter, sort and link.
- [ ] **Step 3: Parity.** The same fixture gives the same TRADE/WATCH counts and the same symbols on each page before and after. Snapshot the symbol lists in the test.
- [ ] **Step 4: All suites green. Commit:** `"Phase 3 (oa12): one recommendation card on Opportunities, stock page and holdings"`.

### Task 3: Horizon states, backend (oa13 data)

**Files:**
- Create: `backend/src/swing_trade_ml/brain/horizons.py` (pure: the five horizons and the rule that gives each one its state)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/beginner.py`, adding `GET /beginner/horizons` on `ReadOnlyDb`. router.py is not changed, because the router is already registered.
- Test: `backend/tests/test_horizons.py`

**Interfaces:**
- `HORIZONS: tuple[int, ...] = (1, 5, 15, 30, 90)`
- `horizon_states(configured: set[int], verdicts: list[dict]) -> list[dict]` returns items of the form `{"horizon": int, "state": "validated"|"experimental"|"unavailable", "label": str, "why": str}`.
- The endpoint passes `configured` = the horizons the brain is set up to produce: the setting M08 writes into `horizon_days`. Find it with `git grep -n "horizon_days" backend/src/swing_trade_ml/brain/modules/m08*`. The value is 15 today.
- `verdicts` comes from `services.brain_observatory.verdicts.evaluate(load_registry())`.
- **Validated** requires a verdict whose `claim == f"horizon_{h}d"` with a passing status, AND `h in configured`. No such claim exists in code today, so no horizon can be Validated. Adding one needs a frozen protocol plus owner approval, which is a data or code change, not a redesign (spec §3).
- Labels:
  - validated → "Validated"
  - experimental → "Experimental, unproven"
  - unavailable → "No model for this horizon yet"
- `why` examples:
  - "The 15-day model has not passed its frozen test (7 of 21 windows)". Take this text from the verdict's own wording where one exists. Never type the numbers in.
  - "No model is built for 30 days".

- [ ] **Step 1: Failing tests.**
  - Today's inputs give 15 experimental and 1/5/30/90 unavailable.
  - A fake passing `horizon_15d` verdict gives validated.
  - A passing verdict for a different claim (`model_ranking_predictive`) does not validate anything.
  - A passing `horizon_30d` with 30 not configured stays unavailable.
  - The endpoint is GET only, uses the read-only session, needs auth (401 without it), and never calls `run_brain` (monkeypatched to raise).
- [ ] **Step 2: Implement. Step 3: green. Commit:** `"Phase 3 (oa13): horizon states — only a passing frozen protocol can say Validated"`.

### Task 4: Horizon selector, frontend (oa13)

**Files:**
- Create: `frontend/src/trademind/beginner/HorizonSelector.tsx` and its test. Add `useHorizons()` to `beginner/api.ts`.
- Modify: `IdeaCard.tsx`. The horizon chip and model-status line come from `horizonState`.

**Interfaces:**
- `HorizonSelector({states, value, onChange})`
- `useHorizonParam(): [number, (h: number) => void]` reads and writes `?h=` in the URL. It defaults to 15. An invalid or unavailable value falls back to 15 and the URL is corrected with `replace`.

- [ ] **Step 1: Failing tests.**
  - The selector shows the five options in order: 1, 5, 15, 30, 90 days.
  - 15 is enabled and labelled "Experimental, unproven".
  - The other four have `disabled`, and their title reads "No model for this horizon yet".
  - "Validated" is never rendered unless a state says so. A fixture with a validated state renders it.
  - `?h=90` resolves to 15, and so do `?h=abc` and a missing `?h=`.
  - If the horizons request fails, only 15 is shown, as "Experimental, unproven", with the note "Horizon list not available". This fails safe and never claims more than is true.
- [ ] **Step 2: Implement. Step 3: green. Commit:** `"Phase 3 (oa13): 1/5/15/30/90 selector, honest states, URL ?h="`.

### Task 5: Today = Home + Swing Picks (oa5)

**Feature list.** Today must cover everything both pages show today. The test asserts each item:

| From | Item |
|---|---|
| Home | market situation and banner; idea counts by word; holdings needing attention (MONITOR/REDUCE/EXIT, using `finalWord`); top ideas; "Today's insights" (learning) |
| Dashboard | summary strip (market view, NIFTY 50, top sectors, estimated chance through honest.tsx, total picks); pick list with search, sector filter and minimum score; pick detail; "How it works?" |
| New | horizon selector (Task 4) filtering the pick list by `horizon_days`; upcoming events for held and watchlist stocks (`UpcomingEvents`, scope `held`, then `watchlist`) |

The Dashboard's "5D: — / 30D: — / 3M: —" placeholders and its local `Window` toggle are replaced by the selector. Choosing an unavailable horizon is not possible, so there is never an empty "0 picks" view.

**Files:**
- Create: `frontend/src/trademind/pages/Today.tsx`. It composes the pieces moved out of Home and Dashboard; moved, not rewritten. `SummaryStrip` and the filter bar move into `frontend/src/trademind/today/` files.
- Modify: `TradeMindApp.tsx`:
  - `index` → `<Today />`
  - `dashboard` → `<Today focus="picks" />`, which scrolls to the picks and keeps the same URL, so no redirect is needed
- Modify: `menu.ts` and `menu.test.ts`. The Today section has one page, "Today". `/trademind/dashboard` moves to `also`, so the section stays highlighted there.
- Keep: `Home.tsx` and `Dashboard.tsx` stay in the tree, unrouted. Phase 6 (oa10) deletes them after two weeks of use, with a single revert as rollback.
- Tests: `pages/Today.test.tsx`, plus updates to `navigation.test.tsx`

- [ ] **Step 1: Failing tests.**
  - Every feature-list row is present for the owner.
  - For a non-owner, owner-only parts are absent: watchlist editing links, approvals, any real-money figure.
  - `/trademind` and `/trademind/dashboard` both render Today. The second has the picks section first in view (`id="picks"` plus the focus prop).
  - The navigation test still renders every URL in `SECTIONS` without throwing, for owner and non-owner.
  - With no run, `BrainGate` / "no run yet" shows while market and portfolio parts still render.
  - The idea counts equal Home's old counts for the same fixture.
- [ ] **Step 2: Implement.** Move the code, then compose it. No new queries except `useHorizons` and `useUpcomingEvents`.
- [ ] **Step 3: Gates.** All suites, build, and `classic-parity --check` with the same "unexplained: 0".
- [ ] **Step 4: Commit:** `"Phase 3 (oa5): one Today page (Home + Swing Picks), horizon selector, events; old URLs kept"`.

### Task 6: Stock page and Discover wiring

- [ ] `StockDetail.tsx`: `StockBriefForSymbol` (Task 2) gets the horizon chip from `useHorizons`. Opportunities gets the selector above its list, filtering by `horizon_days`, with the same `?h=` param.
- [ ] Optional, only if the multi-user session has already merged its `client.ts` changes: move `beginner/api.ts`'s local `getJson` onto the shared client. Otherwise leave it (ruling on the beginner branch).
- [ ] Tests:
  - Opportunities with `?h=15` lists the same symbols as before.
  - The selector's disabled options cannot be chosen.
- [ ] Commit: `"Phase 3: horizon selector on Opportunities and the stock page"`.

### Task 7: Verification, review and handover

- [ ] **Browser run.** Use the local API on the worktree's code with the local DB. Never log in to Kite locally. Test the owner (`trading`) and a non-owner, each on desktop (1280 px) and phone (390 px). Save screenshots to the scratchpad. Check:
  - `/trademind`
  - `/trademind/dashboard`
  - `/trademind/opportunities?h=15` and `?h=90`
  - `/trademind/stock/RELIANCE`
  - `/trademind/positions`
  - no console errors
  - no sideways scroll on phone
  - the same TRADE/WATCH symbols as `main` for the same run
- [ ] **Independent whole-branch review** (requesting-code-review, most capable model). Then one fix wave.
- [ ] **Atlas:** oa12, oa13 and oa5 → `built`, then `tested` after the browser run. They become `done` only after the prod check below, with screenshots as evidence.
- [ ] Open a PR for the owner. Do not merge it.

## Backend changes (summary)

| Change | Kind |
|---|---|
| `brain/horizons.py` (pure) + `GET /beginner/horizons` | new, read-only |
| `money_at_stake` gains `half_out_pct`, `half_out_applies` | additive field |
| Nothing else | — |

## Database impact

**None.** No migration and no new table. Every new read uses the read-only session. B1 (portfolio ownership) is independent: Phase 3 reads decisions and paper positions through the existing helpers and will follow B1's filters once B1 merges, with no Phase 3 change needed.

## Rollout

1. **Merge order:** the multi-user P0/B1 work and `feature/beginner-safe-now` first, then rebase this branch and re-run all gates.
2. **PR:** the owner reviews the PR and screenshots, and approves deployment separately.
3. **Deploy:** owner runs `git push origin develop:main` (or merges the PR) after 16:30 or before 09:00 IST. The existing deploy workflow and health check run as usual.
4. **Prod check, read-only:**
   - `/api/v1/beginner/horizons` returns 15 experimental and the rest unavailable.
   - The owner opens Today and the stock page on desktop and phone.
   - A non-owner account confirms the owner-only parts are hidden.
   - Record the result in the Atlas daily log.
5. **Rollback:** revert the merge commit and redeploy. There is no database step, and no data is written by anything in this phase.

## Acceptance criteria

- **oa12:** one component shows signal, "model score", entry and exit, risk with ₹, explanation, evidence, horizon and model status on Opportunities, the stock page, holdings and Today. Every signal says "Experimental, unproven". A missing field says "Not available" and why. No "probability", "validated", "proven" or "profitable" appears unless true (tested).
- **oa13:** the selector lists 1/5/15/30/90 days. 15 is "Experimental, unproven"; 1/5/30/90 are Unavailable and disabled. Validated is possible only from a passing `horizon_<h>d` frozen verdict (tested).
- **oa5:** Today covers every feature-list row (tested). `/trademind` and `/trademind/dashboard` both work, and owner-only parts stay owner-only.
- **No change** to brain output, trial counts, orders or URLs:
  - the same symbols per page for the same run
  - `classic-parity --check` unexplained = 0
  - the navigation test is green for every URL

## Questions for the owner

1. Today's sub-row: one "Today" page only? Or keep "Swing Picks" as a second sub-row entry that opens the picks section of the same page?
2. Should the 5-day horizon say "Unavailable" (spec), or "Version 1's 5-day model — not checked by the brain"? The v1 models do ask "+2% in 5 days", but that is a different question and has never been validated. The spec says Unavailable, and this plan follows the spec.
3. Should the stock search and phone bottom bar (bx7) be mounted in the app shell in Phase 3, or kept for a later small change? This plan leaves them out.
