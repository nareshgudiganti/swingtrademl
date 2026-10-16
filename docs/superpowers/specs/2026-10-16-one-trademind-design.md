# One TradeMind app: design (revision 1, 2026-10-16)

Status: **revision 2 (2026-10-16). Phase 1 approved for implementation; production deployment NOT approved.**
Revision 2 applies the owner's four corrections (model validation wording, browser-level parity, branch and
dependency safety, existing functionality). Phases 2 to 6 and every deployment need separate approval.

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
every classic URL until the deletion gate in section 6 is met, and **plan-user behaviour**: `/home` redirects to
Today only while plans are disabled; if plans are enabled, `/home` and the plan-user pages keep working exactly
as today.

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
| Model status | **"Experimental, unproven"** for every signal today (section 3). It becomes "Validated" only for a horizon whose frozen protocol passed | `trademind/honest.tsx` + the verdict registry |

Nothing on the card is invented: a missing item shows "Not available" and why.

## 3. Horizons (1, 5, 15, 30, 90 trading days)

**Three different things are kept apart, in code and on screen:**

| State | Meaning | Today |
|---|---|---|
| **Validated** | a frozen protocol with a **passing** result exists for this horizon, and the owner approved it | **none** |
| **Experimental, unproven** | a model is implemented and configured for this horizon, but no frozen validation has passed | **15 trading days** |
| **Unavailable** | no model exists for this horizon | 1, 5, 30, 90 |

Honest starting point: the 15-day model is **not** validated. The frozen walk-forward test (`wf-protocol-v1`, 21
untouched windows) failed on predictive skill (7 of 21 windows won) and on profit after costs (9 of 21), and the
calibrated model (M06) is still in shadow, below break-even in tests. So a 15-day signal is shown as
**"Experimental, unproven"**, never as proven, validated or profitable. `CLAUDE.md` principle 7 fixes
"horizon <= 15 trading days", the Atlas lists 5/30/90-day horizons under "not building now", and the production v1
models ask a different question ("+2% in 5 days") that the brain has never validated.

- **Phase 1 builds none of this.** Phase 3 builds the selector and the card. The selector shows all five horizons.
  An **Experimental** horizon is selectable but always carries the "Experimental, unproven" label on the selector
  and on every card. An **Unavailable** horizon is disabled with "No model for this horizon yet". A horizon never
  shows as **Validated** unless its frozen protocol passed (the same rule as the Observatory's "Proven").
- Validating any horizon is a research and approval project of its own, per horizon. It is **not** part of this
  redesign. Showing 30 or 90 day opportunities also needs the owner to change `CLAUDE.md` principle 7.
- Data shape: the card and selector read `horizon_days` and one read-only list of `{horizon, state}` (initially
  `[{15, experimental}]`, the rest unavailable). Registering a model, or later a passing validation, is then a
  data change, not a redesign.

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

**The API-call comparison is a safety check, not proof of feature parity.** A screen can make the same call and
still lose a button, a filter, a permission rule, a report or a navigation path. So the gate has two parts, and
**both** must pass before any classic screen is deleted:

**Part A: API-call comparison** (reproducible; run 2026-10-16 against `origin/main`). For each classic page, list
the backend calls it makes and check whether any file under `frontend/src/trademind/` makes the same call.
Script: `frontend/scripts/classic-parity.mjs` (Phase 1, Task 4), with an allow-list that explains every gap.
Known blind spots: it reads `api.x` in the page and in local modules the page imports directly (one level), ignores
comments, and reports `api['x']`, `const { x } = api` and passing `api` as a value as an unreadable-access gap that
must be explained. It cannot see calls made through code more than one import away.

**Part B: browser-level verification** (Phase 6, per screen, signed off by the owner). For each classic screen, a
written inventory of every control and path, each linked to its new location and **clicked through in a real
browser**, as the owner and as a non-owner, with DOM assertions saved as a script:
buttons (each action, its confirmation dialog and its result), filters and sorts, form validation, owner-only and
plan-only permission rules, reports and exports, links and navigation paths, empty and error states. A control
with no equivalent is either built, or listed with the owner's explicit decision.

| Classic screen | Lines | Calls with no TradeMind equivalent today | Where it goes | Status |
|---|---|---|---|---|
| Brain | 1060 | none | Today, stock page, Admin > System | covered by calls; Part B pending |
| Positions | 529 | none | Portfolio > Bot | covered by calls; Part B pending |
| Holdings | 274 | none | Portfolio > My Zerodha | covered by calls; Part B pending |
| RealReport | 345 | none | Portfolio > My Zerodha, Insights | covered by calls; Part B pending |
| Reports | 310 | none | Insights > Records | covered by calls; Part B pending |
| ScanResults | 126 | none | Discover / Insights (read-only) | covered by calls; Part B pending |
| Settings | 350 | none | Admin > Setup, Control | covered by calls; Part B pending |
| ModelLab | 214 | none | Admin > Setup (read-only) | covered by calls; Part B pending |
| Capital | 225 | `riskEvents` | Admin > Risk | **build (oa2)** |
| Safety | 234 | `riskEvents` | Admin > Control | **build (oa2)** |
| Dashboard | 787 | `predict`, `strategySignals` | `strategySignals`: read-only list in Discover (oa5). **`predict`** (POST `/ml/predict?persist=true`, the Dashboard's "full model-ranked watchlist"): **owner decision** | **decide + build** |
| Models | 360 | `activateModel`, `train`, `predictions` | **`activateModel` (choose which trained model the live system uses): owner decision, NOT assumed v2. TradeMind Setup is view-only, so retiring this page would remove it.** `train`: v2 (your 10-04 rule). `predictions`: Insights | **decide** (`activateModel`) |
| Strategies | 391 | `createStrategy`, `deleteStrategy`, `strategyTypes`, `scanAll`, `positionsAllBooks` | create, delete, types: v2 (your 10-04 rule). `scanAll`: deferred (oa4). `positionsAllBooks`: Portfolio > Overview, labelled, never summed. On/off already in Setup | **build** (`positionsAllBooks`) |
| PlansManager | 415 | all seven plan calls | Admin > Plans | **build (oa3)** |
| PlanHome | 245 | `picks`, `topPicks` | **kept as is while plans are enabled**; `/home` redirects to Today only while plans are disabled (prod today) | **keep (oa10)** |
| Finance | 1626 | all | stays a separate app | **excluded by your rule** |

**Deferral rule (correction 4):** a call may be labelled "v2" or "deferred" only if the owner's written decision
says so, and the entry cites it (10-04 for create, delete, train; oa4 for scan). Anything else that would remove
a capability the owner has today is `decide`: the classic screen stays until the owner decides.

**Deletion gate (all must hold before any classic screen is deleted, Phase 6):**
1. Part A: `classic-parity.mjs --strict` reports no gap that is only `planned` or `decide`.
2. Part B: the browser-level inventory for that screen is complete, scripted, passing and signed off.
3. Two weeks of normal use of the new layout with no "I can't find X".
4. Old URLs redirect (never 404) and stay redirected; plan-user behaviour is intact when plans are enabled.
5. Deletion is its own commit, so it can be reverted alone.

## 7. Feature mapping and dependencies

| Task | Delivers | Depends on | Phase |
|---|---|---|---|
| oa1 | the five-section menu (decided) | owner approval (done) | 1 |
| oa7 | Brain Logs dissolved (Decisions → Today, AI → stock page, Observatory → Admin) | oa1 | 1 (menu), 3 (merge into Today) |
| oa17 | menu module, tests, classic-parity script | oa1 | 1 |
| oa6 | Portfolio with four tabs | oa1 | 2 |
| oa12 | one recommendation card | oa1 | 3 |
| oa13 | horizon selector (Validated / Experimental / Unavailable states; 15 = Experimental, unproven) | oa12 | 3 |
| oa5 | Today = Home + Dashboard | oa12, oa13 | 3 |
| oa2 | risk-event log in Admin › Risk | oa1; existing `/safety/risk-events` | 4 |
| oa3 | Plans manager in Admin › Plans | oa1; existing `/admin` plan endpoints | 4 |
| oa8 | alerts bell + stage chip | oa1; **new read-only alerts endpoint** | 5 |
| oa11 | Insights: daily / weekly / monthly, paper vs real, benchmarks, evidence panel | oa1; **new read-only grouping endpoint**; Observatory outcomes | 5 |
| oa15 | classic parity: API comparison plus browser-level verification, and the deletion gate | oa17 and every build above | 6 |
| oa9 | retire the classic screens | oa15, two weeks of use | 6 |
| oa10 | `/home` redirects to Today only while plans are disabled; plan users keep PlanHome while plans are enabled | oa5 | 6 |
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
| oa12 | one component renders signal, score (labelled "model score"), entry/exit, risk, explanation, evidence, horizon and the model status; every signal today says "Experimental, unproven"; a missing field says "Not available" and why; a test proves no score is shown as a probability unless its source is calibrated, and none says validated, proven or profitable |
| oa13 | selector lists 1/5/15/30/90; each horizon shows Validated, Experimental or Unavailable; today 15 is **Experimental, unproven** and 1/5/30/90 are Unavailable and disabled; no horizon shows Validated without a passing frozen protocol |
| oa5 | one Today page covers everything Home and Dashboard did (checked against a feature list) |
| oa2 | the log shows the same events as the classic Safety page for the same period |
| oa3 | the Plans page behaves as it does today, owner only, existing endpoints unchanged |
| oa8 | the bell lists recent alerts from `brain_alerts`; "seen" is kept in the browser only; no write to the database |
| oa11 | daily / weekly / monthly figures equal a direct SQL query; paper and real never summed; every benchmark names its definition; "improving" is never claimed without a frozen passing test |
| oa15 | Part A (script, strict) passes **and** Part B (browser-level, per screen: buttons, filters, permissions, reports, navigation, as owner and non-owner) is scripted, passing and signed off |
| oa9 | classic screens removed in their own commit only after oa15; old URLs redirect; plan-user behaviour intact when plans are enabled; rollback is that one revert |

## 9. Phases and approvals

| Phase | Scope | Approval |
|---|---|---|
| 1 | menu shell only: five sections, Admin grouping, Brain Logs dissolved in the menu, test tooling, parity script. **No page and no URL changes** | approve the Phase 1 plan; deployment approved separately |
| 2 | Portfolio four tabs | separate |
| 3 | recommendation card, horizon selector, Today | separate |
| 4 | risk-event log, Plans manager | separate |
| 5 | alerts bell, stage chip, Insights | separate (new read-only endpoints) |
| 6 | parity gate, retire classic, `/home` | separate, after two weeks of use |

## 10. Owner decisions recorded 2026-10-16

| # | Decision |
|---|---|
| 1 | YES: five sections Today, Discover, Portfolio, Insights, Admin |
| 2 | YES: Vitest as a dev-only dependency; tests run in CI |
| 3 | YES: `/home` redirects to Today **when plans are disabled**; plan-user functionality is preserved when plans are enabled |
| 4 | YES: model-prediction history moves to Insights |
| 5 | YES: per-strategy signals shown read-only in Discover |
| 6 | YES: preserve existing URLs, pages and owner-only access |
| 7 | NO: do not activate real trading or change the paper-trading brain |
| C1 | 15-day signals are shown as experimental and unproven; implemented models are kept apart from validated ones |
| C2 | Parity needs browser-level verification, not only the API comparison, before any deletion |
| C3 | The Observatory prerequisite fails hard; isolated dependencies in the new worktree |
| C4 | Deferring a classic call must not remove approved existing functionality: `activateModel` and `predict` are owner decisions, not v2 |
