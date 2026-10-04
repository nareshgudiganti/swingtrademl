# TradeMind Screens on Live Brain Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sample data behind the ten TradeMind screens (`/trademind`, built on branch `brain/ui-trademind`) with the real brain and app API, and show an honest "Not connected yet" wherever no real source exists — never an invented number.

**Architecture:** One live-data layer, `frontend/src/trademind/live.ts`: TanStack Query hooks over the existing `api` client (`frontend/src/api/client.ts`) plus small pure mappers from API shapes to what each screen draws. Screens import from `live.ts` instead of `data.ts`. A shared `<NotConnected what="…" />` component (in `frontend/src/trademind/ui.tsx`) replaces any panel with no real source. `data.ts` keeps only pure chart helpers still used (e.g. nothing that is shown as fact); sample values are removed from what the screens render.

**Tech Stack:** React 18 + TypeScript, react-router, TanStack Query (already used across the app), the existing `api` client and types in `frontend/src/api/`.

**Spec:** TradeMind brain build book (main checkout `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html`; screens part) and the brain's own console (`frontend/src/pages/Brain.tsx`), which already shows every live field in plain words — use it as the reference for meaning and wording.

## Global Constraints

- Work ONLY in worktree `D:/machine learning/swing-trade-bot/.claude/worktrees/brain-m00`, branch `brain/trademind-live` (brain/integration + the TradeMind screens merged). Never push, never touch `main`, never `git stash`, never switch branches.
- **No invented numbers.** Every number, word and chart on a TradeMind screen must come from an API response. Where the brain/app has no source, render `<NotConnected what="…" />` with a one-line plain reason, e.g. "Fundamentals are not connected yet — the brain does not read company results." Never keep a sample value "for looks".
- Plain English for an owner with no finance background (match the wording used in `frontend/src/pages/Brain.tsx`; decision words TRADE / WATCH / WAIT / AVOID and HOLD / MONITOR / REDUCE / EXIT).
- Loading and error states on every live panel (reuse the app's `Loading`/`ErrorBox` components or TradeMind equivalents in `ui.tsx`). When `/brain/*` answers 404 (brain switched off) show one clear state: "The brain is switched off on this server."
- The top-bar chip reads "Live" when the latest brain run loads, "Brain off" on 404, and "Demo data" must disappear.
- Keep the TradeMind look (`trademind.css`, components in `ui.tsx`); match each file's existing style by hand (single quotes, no semicolons, 2-space indent). NEVER run prettier (no repo config). Check: `cd frontend && npx tsc --noEmit -p .` must pass.
- Commit after each green step; message ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Local servers already running: brain API on http://localhost:8001 (check DB, brain on), Vite from this worktree on http://localhost:5174 (talks to :8001). Login: user `brainreview`, password `Review-M17-check` (POST /api/v1/auth/login JSON → `access_token`; the app stores it in localStorage `stml.token`). You may open http://localhost:5174/trademind/... to look, but the controller does the full browser check.

## Live sources (all through `api` in frontend/src/api/client.ts; types in frontend/src/api/types.ts)

- `api.brainLatestRun()` → BrainRun: banner {mode, headline}, decisions[] (symbol, kind idea|holding, word, entry_low/high, target, stop, qty, horizon_days, confidence, evidence_text, reasons[]), sectors[] (rank, name, rotation, strength_20d), situations[] (scope market|stock, label, evidence[], is_unknown, suggest_defensive), portfolio {largest_position, top_sector, holdings_moving_together}, quality, modules, started_at.
- `api.brainWhy(symbol)` → one decision + its trace (step, module_id, status, reason).
- `api.brainTrack(symbol)` → points[{day_n, ret, status, reason}], band[[day,p25,p50,p75]].
- `api.brainWhatIf(symbol, qty)`, `api.brainEpisodes()`, `api.brainModules()`, `api.brainHealth()`, `api.brainRuns(n)`, `api.brainLearning()`, `api.brainProposals()`, `api.brainProposalDecide(...)`, `api.brainRevertBuyLevel()`.
- App (v1) sources already in the client — read `client.ts` for exact names: `api.status()`, `api.riskLimits()`, portfolio/positions/candles/instrument endpoints. Use these for prices, candles, holdings value and risk limits.

## Review Focus

1. A panel with no real source still showing a sample number — every task's reviewer checks the screen's imports from `data.ts`.
2. Brain off (404) → each screen shows the "switched off" state, not a crash or a blank page.
3. Empty lists (no TRADE ideas today, no holdings, 0 finished ideas) → a plain empty message, not an empty table.
4. A symbol in the URL that the brain has no decision for (StockDetail/AI) → plain "No decision for this stock today".
5. Decision words and statuses keep the brain's exact vocabulary.

---

### Task 1: The live-data layer and the "Not connected yet" component

**Files:** Create `frontend/src/trademind/live.ts`; modify `frontend/src/trademind/ui.tsx` (add `NotConnected`, `BrainOff`), `frontend/src/trademind/TradeMindApp.tsx` (chip: Live / Brain off), `frontend/src/trademind/data.ts` (mark `useTradeMind` deprecated — removed in Task 5 once no screen uses it).

**Produces (exact names other tasks use):**
```ts
export function useLatestRun(): UseQueryResult<BrainRun>            // queryKey ['brainLatest','nightly']
export function useBrainStatus(): 'live' | 'off' | 'loading' | 'error'   // from useLatestRun (404 → 'off')
export function ideasFrom(run: BrainRun): BrainDecision[]            // kind idea, TRADE/WATCH first then by confidence desc
export function holdingsFrom(run: BrainRun): BrainDecision[]
export function marketSituation(run: BrainRun): BrainSituation | undefined
export function stockSituations(run: BrainRun, symbol: string): BrainSituation[]
export function useWhy(symbol?: string), useTrack(symbol?: string), useEpisodes(), useModules(), useHealth(),
       useRuns(n?: number), useLearning(), useProposals()   // thin useQuery wrappers, keys matching Brain.tsx's
```
`NotConnected({ what, reason? })` renders a muted TradeMind card: title = `what`, body = `reason ?? 'Not connected yet.'`. `BrainOff()` renders "The brain is switched off on this server."

- [ ] Implement; `npx tsc --noEmit -p .` passes; commit.

### Task 2: Home, Market and Opportunities on live data

**Files:** `frontend/src/trademind/pages/Home.tsx`, `Market.tsx`, `Opportunities.tsx`.
- Home: market mode + headline + situation line; counts of TRADE/WATCH/WAIT/AVOID ideas and holdings needing attention (MONITOR/REDUCE/EXIT); top ideas from `ideasFrom`; "today's insights" only from real lines (banner reasons, situation evidence, failure/learning notes) — none invented.
- Market: mode + reasons, market situation + "never seen before" flag, sector table (`run.sectors`), market history (`useEpisodes`). Indices/breadth/VIX panels: use real values only if an existing endpoint provides them (check client.ts); otherwise `NotConnected`.
- Opportunities: the idea list from `ideasFrom` with word, confidence (label it "model score" — a ranking, not a chance), entry zone/target/stop for TRADE, first reason; filters by word; featured = top TRADE or top WATCH; click → StockDetail.
- [ ] Implement; tsc passes; commit.

### Task 3: Stock detail and AI decision on live data

**Files:** `pages/StockDetail.tsx`, `pages/AIDecision.tsx`.
- StockDetail: the decision for the symbol from the latest run (or `useWhy(symbol)` when the symbol is not in it), its reasons, evidence text, levels, stock situations (`stockSituations`), price chart from the app's candles endpoint if one exists (else `NotConnected`). Fundamentals, news, options, "AI scores" with no source → `NotConnected`.
- AIDecision: reasoning chain = the why-trace steps (step, module, used/trial/fallback, reason) in order; key factors = the decision's reasons; evidence text; risk check = the risk step's trace entry; similar cases = the evidence text when it contains "Similar cases", else `NotConnected`.
- Unknown symbol → "No decision for this stock today."
- [ ] Implement; tsc passes; commit.

### Task 4: Portfolio and Positions on live data

**Files:** `pages/Portfolio.tsx`, `pages/Positions.tsx`.
- Portfolio: holdings = `holdingsFrom` with word + first reason; value/cash/P&L from the app's portfolio endpoint (read client.ts); allocation by sector computed from holdings × price where available; `run.portfolio` (largest position, top sector, holdings moving together); a what-if form (`api.brainWhatIf`) with its warnings. Suggestions = only the brain's real holding notes (e.g. "A stronger idea is waiting…").
- Positions: list of holdings; selected position shows `useTrack(symbol)` — day counter "day N of up to 15", status word, reason, band chart (band p25–p75 + the trade's line, same idea as `frontend/src/components/HoldingTracker.tsx`), stop and target from the decision. Re-evaluation triggers / exit plan: from the decision's reasons and the locked rule (+5% book half, +8% target, −4% stop, 30 calendar-day time stop) — stated as the rule, not invented numbers.
- [ ] Implement; tsc passes; commit.

### Task 5: Risk, Learn and System on live data; remove sample data

**Files:** `pages/Risk.tsx`, `pages/Learn.tsx`, `pages/System.tsx`, `frontend/src/trademind/data.ts`, `TradeMindApp.tsx` if needed.
- Risk: limits from `api.riskLimits()`; market mode; risk-gate reasons from the latest run's refused decisions ("risk check said no: …"); drawdown chart only if an endpoint provides the series, else `NotConnected`.
- Learn: `useLearning()` (note, expected-vs-actual by model score, by word, by week, stop-out patterns, drift note/lines) and `useProposals()` with Accept/Reject (same behaviour and wording as Brain.tsx's Learning card, including "Nothing changes until you press Accept").
- System: modules with ON/TRIAL/OFF (`useModules`), last run and data health (`useHealth`), recent runs (`useRuns`), active model name/version from `api.status()` if present. Invented performance (accuracy %, profit factor, annual return, backtests, feature importance, equity curve) → `NotConnected` with reason "Not measured yet — the learning loop reports real results once ideas finish."
- Remove every sample value no screen uses from `data.ts` (delete the file if nothing remains; keep pure helpers only if still imported).
- [ ] Implement; tsc passes; `grep -rn "from '../data'" frontend/src/trademind` shows only helper imports (or none); commit.

### Task 6: Browser check of all ten screens (controller)

Log in, visit every `/trademind/...` route at desktop and 390 px width: no console errors, no failed requests other than intentional 404s, no horizontal scroll, every panel either live or `NotConnected`.
