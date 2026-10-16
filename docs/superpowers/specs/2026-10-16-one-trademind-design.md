# One TradeMind app: design (revision 1, 2026-10-16)

Status: **for owner approval. Nothing implemented, nothing deployed.** The owner approved the reuse-based
design and the five sections on 2026-10-16 and asked for the changes below. Implementation and every
production deployment need separate approval.

Atlas: System Atlas → Pending work → "One TradeMind app" (oa1–oa17). Related: `docs/architecture/CODE-MAP.md`,
the 10-13 UI audit (Atlas tab 19), the Observatory spec (`2026-10-15-brain-observatory-design.md`).

## 0. Goal and guardrails

One workspace, five sections: **Today · Discover · Portfolio · Insights · Admin (owner only)**. It reuses the
TradeMind pages that already work and moves them into the new structure. It is not a from-scratch rewrite.

**Must not change (any phase):**
- the brain's decision logic, the order path (`services/execution.py`, `brokers/`), risk rules and limits
- the forward-trial protocol and the frozen validation protocols
- existing API contracts (new endpoints are additive and read-only), stored data, or any migration
- `TRADING_MODE=paper`. Real BUY/SELL stays behind its own separately approved safety gate; the UI only
  surfaces what that gate allows

**Must preserve:** every working page, every old TradeMind URL (they keep working; Phase 1 renames no path),
every classic URL until the deletion gate in section 6 is met.

**Scanning never creates trades.** Scan results are read-only. `oa4` ("Scan all now") stays deferred until
after the trial.

## 1. Target structure

| Section | Pages | Notes |
|---|---|---|
| **Today** | Today (merge of Home and Dashboard), then the "needs you" list | Phase 3 merges them; until then both pages sit here |
| **Discover** | Opportunities, Watchlist (owner), Market, stock page (absorbs "AI") | Horizon selector lives here and on Today (section 3) |
| **Portfolio** | one page, four tabs: **Bot (paper) · My Zerodha (real, manual) · Testing · Overview** | Paper and real are labelled on every number and never summed |
| **Insights** | Records, Learn, trial journal, daily / weekly / monthly performance | Real and paper reported apart, with benchmarks and an evidence panel |
| **Admin** (owner only) | Control, Go-live, Risk (+ risk-event log), System, Setup, Observatory, Plans | The "Brain Logs" section is dissolved |
| **Top bar** | market chip, Zerodha chip, stage chip, alerts bell | stage chip and bell arrive in Phase 5 |

Finance stays a separate app. Strategies and models stay view and on/off only (no create, delete or train
until v2). Classic view stays hidden.

## 2. Recommendation card (Today and Discover)

Every stock recommendation, everywhere it appears, shows the same card (`trademind/ui.tsx` kit, one
component; this fixes the "same building blocks everywhere" task bx6):

| Part | Content | Source today |
|---|---|---|
| Signal | TRADE / WATCH / WAIT / AVOID (or HOLD / MONITOR / REDUCE / EXIT for holdings) | `brain_decisions.word` |
| Score | the number, labelled **"model score"**, with the plain note "a ranking, not a chance of winning". It is never shown as a probability unless the decision's `score_source` is a calibrated probability, and then it says "calibrated estimate" | `confidence`, `score_source`; wording in `trademind/honest.tsx` |
| Entry and exit context | entry zone, target, stop, last exit day, the half-out level | `entry_low/high`, `target`, `stop`, `horizon_days` |
| Risk information | what the risk check said (allowed or blocked and the rule), shares allowed, ₹ at stake and the ₹ lost if the stop hits (task bx3) | M07 verdict in the decision reasons; sizing in `qty` |
| Brain explanation | the stored reasons in plain English, expandable | `reasons`, `evidence_text` |
| Evidence strip | how this kind of idea has done so far, and whether any of it is proven (the Observatory's "Not proven" wording) | outcomes and frozen verdicts |
| Horizon chip | the trading-day horizon this idea was made for | `horizon_days` |

Nothing on the card is invented: a missing item shows "Not available" and why.

## 3. Horizons (1, 5, 15, 30, 90 trading days)

Honest starting point: today the brain has **one validated horizon, 15 trading days**. `CLAUDE.md` principle 7
fixes "horizon ≤ 15 trading days", the Atlas lists 5/30/90-day horizons under "not building now", and the
production v1 models ask a different question ("+2% in 5 days") that has never been validated by the brain.
So:

- **Phase 1 to 3 build the UI horizon-ready, not horizon-complete.** The Today and Discover pages get a horizon
  selector (1 · 5 · 15 · 30 · 90). A horizon is **selectable only when a validated model for it is registered**.
  Every other horizon is shown but disabled, with "No validated model for this horizon yet".
- A model counts as validated for a horizon only when a **frozen protocol with a passing result** exists for it
  (the same rule as the Observatory's "Proven"). That is a research and approval project of its own, per horizon.
  It is **not** part of this redesign.
- Showing 30 or 90 day opportunities also needs the owner to change `CLAUDE.md` principle 7. The UI work does
  not assume that decision.
- Data shape: the card and the selector read `horizon_days` and a small "available horizons" list from one
  read-only function (initially returning `[15]`). Adding a validated horizon later is then a data change,
  not a redesign.

## 4. Portfolio (four tabs)

| Tab | What it is | Rules |
|---|---|---|
| **Bot (paper)** | the bot's own paper positions (today's Positions) | label "Paper" on every figure |
| **My Zerodha (real, manual)** | the owner's own real shares, import, "I sold this", the real report (today's My Holdings) | visible only to the account allowed to see it (existing gate); every action keeps its existing confirmation and safety checks; **Real BUY/SELL stays behind the independently approved gate and stays off by default** |
| **Testing** | the tester's own manual paper trades (today's PaperPositions) | owner view; shown only when paper testing is switched on |
| **Overview** | account summary, allocation, sector shares, drawdown | each total says Paper or Real; **no total ever mixes the two books** (task bx2) |

## 5. Insights (daily, weekly, monthly)

| Panel | Content |
|---|---|
| Period switch | Daily · Weekly · Monthly, applied to every panel below |
| Paper vs real | two columns, never summed: profit booked and open, costs, worst fall from a peak, win rate, number of finished trades |
| Benchmarks | against NIFTY 50 and against "every stock the brain looked at" (the evidence-defs-v1 definitions already built for the Observatory), after trading costs |
| Is the brain improving? | an **evidence panel**, not a score: results collected vs the 30-idea gate, the forward gate answer, the frozen test verdicts (model ranking "Not proven", full brain "No frozen protocol yet"), learning activity (collected / proposed / proven) |
| Trial journal | the existing journal |

Wording rule: "improving" is only claimed when a predefined, independent test supports it (Observatory
section 6). Otherwise the panel says "not proven" or "insufficient evidence".

## 6. Classic screens: feature parity and the deletion gate

Method (reproducible, run 2026-10-16 against `origin/main`): for each classic page, list the backend calls it
makes and check whether any file under `frontend/src/trademind/` makes the same call. Script:
`frontend/scripts/classic-parity.mjs` (Phase 1, Task 4), so the check can be re-run before any deletion.

| Classic screen | Lines | Calls with no TradeMind equivalent today | Where it goes | Status |
|---|---|---|---|---|
| Brain | 1060 | none | Today, stock page, Admin › System | covered |
| Positions | 529 | none | Portfolio › Bot | covered |
| Holdings | 274 | none | Portfolio › My Zerodha | covered |
| RealReport | 345 | none | Portfolio › My Zerodha, Insights | covered |
| Reports | 310 | none | Insights › Records | covered |
| ScanResults | 126 | none | Discover / Insights (read-only) | covered |
| Settings | 350 | none | Admin › Setup, Control | covered |
| ModelLab | 214 | none | Admin › Setup (read-only) | covered |
| Capital | 225 | `riskEvents` | Admin › Risk | **build (oa2)** |
| Safety | 234 | `riskEvents` | Admin › Control | **build (oa2)** |
| Dashboard | 787 | `predict` ("Score now"), `strategySignals` | `predict` dropped until v2; signals per strategy: Discover (read-only list) | **decide + build** |
| Models | 360 | `activateModel`, `train`, `predictions` | train and activate: v2 (not built); `predictions` (accuracy history): Insights | **decide** (`predictions`) |
| Strategies | 391 | `createStrategy`, `deleteStrategy` (v2); `scanAll` (oa4, deferred); `positionsAllBooks`, `strategyTypes` | on/off already in Setup; all-books positions: Portfolio › Overview (labelled, not summed) | **build** (`positionsAllBooks`) |
| PlansManager | 415 | all seven plan calls | Admin › Plans | **build (oa3)** |
| PlanHome | 245 | `picks`, `topPicks` | only used when the plans switch is ON (off on prod); redirect `/home` to Today, revisit if plans are switched on | **decide (oa10)** |
| Finance | 1626 | all | stays a separate app | **excluded by your rule** |

**Deletion gate (all must hold before any classic screen is deleted, Phase 6):**
1. The parity script reports **no unexplained gap**: every remaining call is either built, or listed above as
   "v2", "deferred" or "separate app" with your sign-off.
2. A written feature-by-feature checklist per classic screen, each item linked to its new location, checked
   by clicking through it.
3. Two weeks of normal use of the new layout with no "I can't find X".
4. Old URLs redirect (never 404) and stay redirected.
5. Deletion is its own commit, so it can be reverted alone.

## 7. Feature mapping and dependencies

| Task | Delivers | Depends on | Phase |
|---|---|---|---|
| oa1 | the five-section menu (decided) | owner approval (done) | 1 |
| oa7 | Brain Logs dissolved (Decisions → Today, AI → stock page, Observatory → Admin) | oa1 | 1 (menu), 3 (merge into Today) |
| oa17 | menu module, tests, classic-parity script | oa1 | 1 |
| oa6 | Portfolio with four tabs | oa1 | 2 |
| oa12 | one recommendation card | oa1 | 3 |
| oa13 | horizon selector (15 only enabled) | oa12 | 3 |
| oa5 | Today = Home + Dashboard | oa12, oa13 | 3 |
| oa2 | risk-event log in Admin › Risk | oa1; existing `/safety/risk-events` | 4 |
| oa3 | Plans manager in Admin › Plans | oa1; existing `/admin` plan endpoints | 4 |
| oa8 | alerts bell + stage chip | oa1; **new read-only alerts endpoint** | 5 |
| oa11 | Insights: daily / weekly / monthly, paper vs real, benchmarks, evidence panel | oa1; **new read-only grouping endpoint**; Observatory outcomes | 5 |
| oa15 | classic feature-parity check and deletion gate | oa17 and every build above | 6 |
| oa9 | retire the classic screens | oa15, two weeks of use | 6 |
| oa10 | what `/home` becomes for plan users | oa5 | 6 |
| oa4 | "Scan all now" | after the trial; never auto-creates trades | deferred |
| oa14 | validated models for 1 / 5 / 30 / 90 day horizons | separate research project, frozen protocols, and an owner change to `CLAUDE.md` principle 7 | not in this redesign |

## 8. Acceptance criteria

Applies to every phase:
- `npm run typecheck` and `npm run build` pass; the backend suite is unchanged and green; no file under
  `brain/`, `strategies/`, `workers/`, `db/`, `alembic/`, `infra/`, `services/execution.py` or the order path changes
  (scope guard, same method as the Observatory).
- Every moved page is browser-checked at desktop and phone width as the owner and as a non-owner, with DOM
  assertions (not only screenshots); console clean; no old URL breaks.
- An independent review before any deployment request. Deploys only after 16:30 IST on weekdays (or at
  weekends), each by your push.

Per task:

| Task | Accepted when |
|---|---|
| oa1 | five sections visible to the owner, four to a non-owner (no Admin); every previous TradeMind URL still opens its page and highlights the right section |
| oa17 | the menu module has tests; the parity script runs and reproduces section 6 |
| oa6 | four tabs; paper and real never share a total; My Zerodha obeys the existing gate; every action keeps its confirmation dialog |
| oa12 | one component renders signal, score (labelled "model score"), entry/exit, risk, explanation, evidence and horizon; a missing field says "Not available" and why; a test proves no score is shown as a probability unless its source is calibrated |
| oa13 | selector lists 1/5/15/30/90; only horizons with a registered validated model are selectable; today only 15 |
| oa5 | one Today page covers everything Home and Dashboard did (checked against a feature list) |
| oa2 | the log shows the same events as the classic Safety page for the same period |
| oa3 | the Plans page behaves as it does today, owner only, existing endpoints unchanged |
| oa8 | the bell lists recent alerts from `brain_alerts`; "seen" is kept in the browser only; no write to the database |
| oa11 | daily / weekly / monthly figures equal a direct SQL query; paper and real never summed; every benchmark names its definition; "improving" is never claimed without a frozen passing test |
| oa15 | the parity script shows no unexplained gap and the per-screen checklist is signed off |
| oa9 | classic screens removed in their own commit; old URLs redirect; rollback is that one revert |

## 9. Phases and approvals

| Phase | Scope | Approval |
|---|---|---|
| 1 | menu shell only: five sections, Admin grouping, Brain Logs dissolved in the menu, test tooling, parity script. **No page and no URL changes** | approve the Phase 1 plan; deployment approved separately |
| 2 | Portfolio four tabs | separate |
| 3 | recommendation card, horizon selector, Today | separate |
| 4 | risk-event log, Plans manager | separate |
| 5 | alerts bell, stage chip, Insights | separate (new read-only endpoints) |
| 6 | parity gate, retire classic, `/home` | separate, after two weeks of use |

Open decisions for you (recommendation first): `/home` for plan users → redirect to Today; `predictions` (model
accuracy history) → Insights; per-strategy signals → read-only list in Discover; add `vitest` as a dev-only
dependency for menu tests (Phase 1 Task 1, needs your yes).
